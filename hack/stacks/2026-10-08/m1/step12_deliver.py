"""Step 12: deliver. The finished JPEG goes to the target folder (checked free of EXIF / XMP / comments: OpenCV writes
none, and the check refuses to deliver one that has any); the single frame against the stack, same stretch and same
levels, no finishing smoothing, brightness only; and recipe.json with every number that shaped the pictures.
Adapted from this night's ngc1514/step12_deliver.py."""
import datetime, glob, json, os, platform, shutil, subprocess
import numpy as np, cv2, rawpy, scipy, tifffile, PIL
from common import *

S1, S3, S4, S5, S6, S7, S8, S9, S10 = (jload(n) for n in ('step1.json', 'step3_transforms.json', 'step4_solve_ref.json', 'step5_quality.json', 'step6_select.json', 'step7.json', 'step8_solve.json', 'step9_measure.json', 'step10.json'))
FIN = json.load(open(W_('m1-finished.json')))
os.makedirs(OUT, exist_ok=True)


def jpeg_markers(path):
    """The marker segments before the image data: (marker, length)."""
    b = open(path, 'rb').read(); i = 2; out = []
    assert b[:2] == b'\xff\xd8'
    while i < len(b):
        assert b[i] == 0xFF; m = b[i + 1]
        if m == 0xDA: break
        n = int.from_bytes(b[i + 2:i + 4], 'big'); out.append(('FF%02X' % m, n)); i += 2 + n
    return out


def deliver_jpeg(src, dst):
    mk = jpeg_markers(src)
    bad = [m for m, n in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE') or (m.startswith('FFE') and m not in ('FFE0',))]
    assert not bad, (src, bad)
    shutil.copyfile(src, dst)
    return [m for m, n in mk]


# ---- the finished picture
markers = deliver_jpeg(W_('m1-finished.jpg'), os.path.join(OUT, 'm1.jpg'))

# ---- single frame against the stack: brightness only, the stack's own black and white points, gamma, no smoothing
LUMA = np.array([0.2126, 0.7152, 0.0722])
def lum(name):
    a = cv2.imread(W_(name), cv2.IMREAD_UNCHANGED)[..., ::-1].astype(np.float64) / 65535.0
    return a @ LUMA
lev = [s for s in FIN['steps'] if s['step'] == 'levels'][0]; mid_ = [s for s in FIN['steps'] if s['step'] == 'midtones'][0]
b, w = lev['black_point'] / 255.0, lev['white_point'] / 255.0
def show(Y): return (np.clip((Y - b) / (w - b), 0, 1) ** mid_['gamma'] * 255 + 0.5).astype(np.uint8)
one, stk = show(lum('single-stretched.png')), show(lum('m1-stretched.png'))
GAP = 8; H_, W_px = one.shape
panel = np.zeros((H_, 2 * W_px + GAP), np.uint8); panel[:, :W_px] = one; panel[:, W_px + GAP:] = stk
nf = len(S7['frames'])
for x, text in ((12, 'One 15 s frame'), (W_px + GAP + 12, '%d frames, %s' % (nf, ('%.0f minute' % (nf * 0.25)) if nf * 15 == 60 else '%.1f minutes' % (nf * 0.25)))):
    cv2.putText(panel, text, (x, H_ - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 200, 1, cv2.LINE_AA)
cv2.imwrite(W_('m1-single-vs-stack.jpg'), panel, [cv2.IMWRITE_JPEG_QUALITY, 92])
deliver_jpeg(W_('m1-single-vs-stack.jpg'), os.path.join(OUT, 'm1-single-vs-stack.jpg'))

# ---- recipe
SCALE = float(np.mean(S8['scale_arcsec_per_px']))
f1 = {f['stamp']: f for f in S1['frames']}; tr = {o['stamp']: o for o in S3['transforms']}; q5 = {o['stamp']: o for o in S5['quality']}
used = {u['stamp']: u for u in S6['used']}; rej = {r['stamp']: r for r in S6['rejected']}
TM = S6['transparency_at_m1']
frames = []
for s in sorted(f1):
    f = f1[s]; o = tr[s]; q = q5.get(s)
    d = dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['raw_exif']['exposure_s'], iso=f['raw_exif']['iso'], arw_sha256=f['arw_sha256'], used=s in used,
             why_dropped=rej[s]['why'] if s in rej else None,
             star_hfd_arcsec=round(q['hfd_arcsec'], 2) if q else None, elongation_median=round(q['elong_median'], 3) if q else None,
             common_direction_ellipticity=round(q['coherent_ellipticity'], 3) if q else None, common_direction_deg=round(q['coherent_angle_deg'], 0) if q else None,
             transparency_at_m1=round(TM[s], 3) if TM.get(s) is not None else None, transparency_whole_field_check=round(q['transparency'], 3) if q else None,
             box_sidecar=dict(star_size_arcsec=f['box_star_size_arcsec'], transparency=f['box_transparency'], since_slew_s=f['since_slew_s'], settling=f['settling']),
             stars_found=len([r for r in jload('step2_stars.json') if r['stamp'] == s][0]['stars']),
             registration=(dict(failed=True, stars_matched=o['matched']) if o['failed'] else
                           dict(stars_matched=o['matched'], stars_used=o['model_used'], model=o['model'], rotation_deg=round(o['rotation_deg'], 4),
                                shift_at_frame_centre_sensor_px=[round(v, 2) for v in o['shift_at_centre_px']],
                                weighted_rms_px=round(o['model_wrms_px'] if o['model_wrms_px'] is not None else o['wrms_px'], 3))),
             provisional_sky_dn=dict(zip(PLANE_NAMES, [round(x['clipped_mean'], 2) for x in f['bg_provisional']])), transient_spikes_replaced=f['transient_spikes_replaced'])
    if s in used:
        d.update(weight=round(used[s]['weight'], 4), scale=round(used[s]['scale'], 4), sky_constant_dn=S7['constants_dn'][s])
    frames.append(d)
sh = np.array([o['shift_at_centre_px'] for o in S3['transforms'] if o['stamp'] in used]); rot = np.array([o['rotation_deg'] for o in S3['transforms'] if o['stamp'] in used])
ts = sorted(datetime.datetime.fromisoformat(f1[s]['t'].replace('Z', '+00:00')) for s in used); span_min = (ts[-1] - ts[0]).total_seconds() / 60
nb = S9['nebula']; nz = S9['noise_per_px_dn']; stc = S9['structure']
tm_all = [TM[s] for s in sorted(TM) if TM[s] is not None]
smeared = [s for s in sorted(rej) if q5.get(s) and q5[s]['coherent_ellipticity'] > S6['limits']['coh_max'] and s >= '20261009-080200']
# the nearest miss: the clearest dropped frame that is not a centring frame and not plainly smeared (elongation within the rule)
best_dropped = max((s for s in rej if TM.get(s) is not None and q5.get(s) and q5[s]['elong_median'] <= S6['limits']['elong_max'] and 'centring' not in rej[s]['why']), key=lambda s: TM[s])
sky0 = [f1[s]['bg_provisional'] for s in sorted(f1)]
dG = sky0[-1][1]['clipped_mean'] - sky0[0][1]['clipped_mean']; dB = sky0[-1][3]['clipped_mean'] - sky0[0][3]['clipped_mean']
r_lo, r_hi = min(b[0]['clipped_mean'] for b in sky0), max(b[0]['clipped_mean'] for b in sky0)
tilt_max = max(max(abs(v) for v in S6['transparency_fit'][s]['tilt_per_3000px']) for s in S6['transparency_fit'] if S6['transparency_fit'][s])
centring = [s for s in sorted(rej) if 'centring' in rej[s]['why']]
other = [s for s in sorted(rej) if s not in centring and s not in smeared]
other_low = [s for s in other if TM.get(s) is not None and TM[s] < S6['limits']['t_min']]
other_hfd = [q5[s]['hfd_arcsec'] for s in other]
tu = sorted(u['transparency'] for u in S6['used'])
sm_coh = [q5[s]['coherent_ellipticity'] for s in smeared]; sm_ang = [q5[s]['coherent_angle_deg'] for s in smeared]
sharp_late = [s for s in sorted(f1) if s >= smeared[0] and s not in smeared]
simscale = max(abs(o['similarity_scale'] - 1) for o in S3['transforms'] if not o['failed'])
w_with = S6['sum_of_weights'] + (TM[best_dropped] / (q5[best_dropped]['pixel_noise_dn'][1] / S6['noise_clear_median_dn'])) ** 2
fr = {k: nb['stack']['blank_sky_scatter_dn'][k] / nb['stack']['mean_dn'][k] for k in 'RGB'}
col_err = (S9['colour']['ratio_to_green']['R'] * np.hypot(fr['R'], fr['G']), S9['colour']['ratio_to_green']['B'] * np.hypot(fr['B'], fr['G']))
recipe = dict(
    what='M1, the Crab Nebula: %d x 15 s at ISO 3200 (%s), Sony a6000 on a Celestron 8SE (%.0f mm by plate solve, f/10), EQ6-R tracking on a pointing model; stacked from RAW colour planes' % (
        len(used), '1 minute' if len(used) == 4 else '%.1f minutes' % (len(used) * 0.25), S8['focal_length_mm']),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    owner='Brad Gessler',
    target=TARGET,
    verdict=dict(
        nebula_detected=True,
        what_it_shows='The smooth oval glow, not the filaments. The oval is there in every test: inside an ellipse %.1f x %.1f arcmin its mean light is %.1f DN in green per pixel (raw camera units; red %.1f, blue %.1f), %.1f times the scatter of the same ellipse laid on blank sky nearby, and each half stack shows it on its own (%.1f and %.1f DN; the smoothed halves correlate at %.2f across the nebula). Per pixel it is only %.2f times the noise at the sensor\'s scale (%.1f times in its brightest middle), about %.0f times after a 2 px Gaussian. Finer structure does not repeat between the half stacks: band-passed at 3 to 14 arcsec the halves correlate at %.3f in the nebula against %.3f +- %.3f on blank sky; with the smooth oval taken out, %.2f against %.2f +- %.2f. Only at 7 to 28 arcsec is there a weak excess (%.3f against %.3f +- %.3f), which the oval\'s own edge gives. So the filaments are not seen: one minute of light, about half of it lost to the obstruction (the four frames caught %.0f%% of the clearest frame\'s light on average), is not enough. The picture shows the oval and does not draw texture inside it.' % (
            S9['inner_ellipse_arcmin'][0], S9['inner_ellipse_arcmin'][1], nb['stack']['mean_dn']['G'], nb['stack']['mean_dn']['R'], nb['stack']['mean_dn']['B'], nb['stack']['signal_to_sky_structure']['G'],
            nb['odd']['mean_dn']['G'], nb['even']['mean_dn']['G'], stc['oval_included_3px']['halves_correlation_in_nebula'],
            nb['stack']['mean_dn']['G'] / nz['stack'][1], S9['central_level_green_dn'] / nz['stack'][1], nb['stack']['mean_dn']['G'] / nz['stack_gauss2'][1],
            stc['sigma_1.5_px']['halves_correlation_in_nebula'], stc['sigma_1.5_px']['blank_sky_correlation_mean'], stc['sigma_1.5_px']['blank_sky_correlation_std'],
            stc['oval_removed_3px']['halves_correlation_in_nebula'], stc['oval_removed_3px']['blank_sky_correlation_mean'], stc['oval_removed_3px']['blank_sky_correlation_std'],
            stc['sigma_3.0_px']['halves_correlation_in_nebula'], stc['sigma_3.0_px']['blank_sky_correlation_mean'], stc['sigma_3.0_px']['blank_sky_correlation_std'],
            100 * np.mean([u['transparency'] for u in S6['used']])),
        size='half its central brightness %.1f x %.1f arcmin, down to the sky by %.1f x %.1f arcmin (catalogue 6 x 4); long axis at position angle %.0f degrees east of north, axis ratio %.2f' % (
            *S9['size_arcmin']['half_level'], *S9['size_arcmin']['to_the_sky'], S9['shape']['position_angle_deg_east_of_north'], S9['shape']['axis_ratio']),
        placement='plate solve of the stack (%d catalogue stars, %.2f arcsec rms): the light of the nebula is centred %.0f arcsec from the catalogue position (the pulsar), north-west of it; a %.0f-sigma star %.1f arcsec north-east of the pulsar\'s position is most likely its 16th magnitude neighbour (the two are about 4.5 arcsec apart, one blob at this seeing); at the pulsar\'s own position the signal is %.0f sigma, not a separate detection' % (
            S8['used_in_fit'], S8['fit_rms_arcsec'], S9['shape']['light_centre_from_catalogue_arcsec'], S9['pulsar']['nearest_significance_sigma'], S9['pulsar']['nearest_offset_arcsec'], S9['pulsar']['peak_within_4px_of_catalogue_sigma']),
        colour='warm white: in the camera\'s daylight white balance the nebula\'s red : green : blue is %.2f : 1 : %.2f (+-%.2f and +-%.2f from the blank-sky scatter of each colour); core and rim, and one end and the other, do not differ beyond that' % (
            S9['colour']['ratio_to_green']['R'], S9['colour']['ratio_to_green']['B'], col_err[0], col_err[1])),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, tifffile=tifffile.__version__, pillow=PIL.__version__,
               astrometry_net=subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip(),
               note='deterministic array arithmetic only (averages, medians, fitted planes, Gaussian filters, a fixed arcsinh curve); nothing generative or learned, no AI denoise, sharpening or upscaling, no deconvolution'),
    source=dict(folder=STILLS, originals='read in place, never written', window=[T0, T1], frames_in_window=len(S1['all_in_window']), frames_on_target=len(S1['frames']), frames_used=len(used), frames_dropped=len(rej),
                not_on_disk='20261009-080725-DSC00692: its sidecar is here, its RAW is still on the box', no_darks_no_flats='none were taken: hot pixels come from the run itself; vignetting and dust are not corrected'),
    what_the_run_was_like=dict(
        obstruction='M1 was rising out from behind something near the telescope (most likely a tree or a roofline: the field was 29 to 32 degrees up in the east). The starlight reaching M1\'s part of the field grew from %.0f%% to 100%% over the 13 minutes, unevenly across the field at first (the star flux ratio tilted by up to %.0f%% per 3000 px), while the background in green and blue grew by %.0f and %.0f DN and the red stayed between %.0f and %.0f DN: the early frames are mostly the warm glow of a lit, out-of-focus object in front of the aperture. A cloud bank clearing would have darkened a light-polluted sky, not brightened it.' % (100 * min(tm_all), 100 * tilt_max, dG, dB, r_lo, r_hi),
        mount='the first two frames are centring frames (2 and 3 s after a nudge); from %s:%s:%s on, every frame but %s is smeared in one direction (common-direction ellipticity %.2f to %.2f at %.0f to %.0f degrees in the sensor frame, the same direction as NGC 1514\'s smeared frames earlier tonight), and the pointing zig-zags from frame to frame by up to about 30 sensor px (12 arcsec)' % (
            smeared[0][9:11], smeared[0][11:13], smeared[0][13:15], ', '.join('%s:%s:%s' % (x[9:11], x[11:13], x[13:15]) for x in sharp_late), min(sm_coh), max(sm_coh), max(sm_ang), min(sm_ang)),
        seeing='30 degrees up: the sharpest frames have 5.2 to 6.6 arcsec stars (half-flux diameter), most 7 to 10'),
    selection=dict(rule=S6['limits'], rule_words='used if: not a centring frame (more than 10 s after the last move); star half-flux diameter <= 6.6 arcsec ("roughly 6.5", as asked); median elongation <= 1.35 and common-direction ellipticity <= 0.20 (no smear); transparency at M1 >= 0.30 of the clearest frame; registration rms <= 1.5 px',
                   transparency=S6['transparency_from'] + '; every star of the reference frame brighter than 3000 DN, more than 300 px from M1, weights from the aperture noise of both frames plus 5%; error about 1% (whole-field median from step 5 kept as a check)',
                   weights='(transparency / noise)^2, noise = the frame\'s green pixel noise over the clear-frame median; each used frame multiplied by 1 / transparency first; sum of weights %.3f, effective frames %.2f; expected noise gain against the reference frame alone %.2f' % (S6['sum_of_weights'], S6['effective_frames'], S6['expected_noise_gain_vs_reference']),
                   dropped_in_words='%d of %d: %d centring frames; %d smeared by the mount (from %s:%s:%s on); the other %d (%s:%s:%s to %s:%s:%s) have stars %.1f to %.1f arcsec wide, and %d of them also caught under %.0f%% of the light (%.0f to %.0f%%), behind the obstruction. The nearest miss, %s (%.0f%% of the light at M1, stars %.2f arcsec, elongation %.2f, common ellipticity %.2f), fails the size rule and is stretched in the same direction as its smeared neighbours; with it the noise gain would have been %.2f instead of %.2f.' % (
                       len(rej), len(f1), len(centring), len(smeared), smeared[0][9:11], smeared[0][11:13], smeared[0][13:15], len(other), other[0][9:11], other[0][11:13], other[0][13:15], other[-1][9:11], other[-1][11:13], other[-1][13:15],
                       min(other_hfd), max(other_hfd), len(other_low), 100 * S6['limits']['t_min'], 100 * min(TM[x] for x in other_low), 100 * max(TM[x] for x in other_low),
                       best_dropped, 100 * TM[best_dropped], q5[best_dropped]['hfd_arcsec'], q5[best_dropped]['elong_median'], q5[best_dropped]['coherent_ellipticity'],
                       np.sqrt(w_with / used[S3['reference']]['weight']), S6['expected_noise_gain_vs_reference'])),
    frames=frames,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (sensor orientation, 6024 x 4024, RGGB), black level 512 subtracted, four colour planes R, G1, G2, B at 3012 x 2012, no demosaic; exposure and ISO confirmed from each RAW\'s EXIF'),
        dict(step='hot pixels', detail='fixed: per-plane median of all 22 frames without registration (the centring moved the field by about 1500 px), pixels above the 5 x 5 median of that by more than max(6 sigma, 25% of the level); transient: per frame, above the 3 x 3 median by more than 8 sigma + 50% of the level. Both replaced by the 3 x 3 median of the same colour plane. No darks.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in S1['hot']}),
        dict(step='stars', detail='green planes averaged, smooth background from 64 px block medians taken off, 2.5 px Gaussian, blobs above %.1f sigma (NGC 1514 used 6: few stars stand out at f/10 in this sky), Gaussian-windowed centroid, 14 px (plane) aperture flux, half-flux radius, second moments; blobs wider than 2.5 x the median half-flux radius (the nebula\'s own light) left out' % jload('step2_stars.json')[0]['detect_sigma'],
             stars_found_per_frame={f['file'][:15]: f['stars_found'] for f in frames}),
        dict(step='register', detail='on the RAW green planes. Reference %s (most stars). Rotation and offset by a vote over the brightest 80 stars (+-2.5 degrees, +-2000 px), then weighted least squares with rejection: rigid, then a 2nd-order polynomial (50+ stars; affine with 20 to 49) used for resampling. Scale left free came out within %.4f of 1.' % (S3['reference'], simscale),
             stars_matched_per_frame={f['file'][:15]: f['registration'].get('stars_matched') for f in frames},
             used_frames=dict(stars_matched=[used_s['stars_matched'] for used_s in S6['used']], rotation_deg=[round(float(rot.min()), 4), round(float(rot.max()), 4)], field_rotation_deg_per_minute=round(float((rot.max() - rot.min()) / span_min), 4),
                              shift_at_centre_sensor_px=dict(x=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], y=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]))),
        dict(step='is it the thing', detail='the reference frame alone plate-solved (astrometry.net, %d index stars): M1\'s catalogue position at sensor px (%.1f, %.1f), the middle of the frame; in that one frame the mean green light within 90 arcsec of it is %.1f DN above the sky ring 6 to 11 arcmin out (%.0f times the error of that mean), centred %.1f arcsec from the catalogue position' % (
            S4['index_stars_matched'], *S4['target_sensor_px'], S4['nebula_in_this_frame']['mean_green_within_90_arcsec_dn'], S4['nebula_in_this_frame']['signal_to_noise_of_that_mean'], S4['nebula_in_this_frame']['light_centroid_from_catalogue_arcsec'])),
        dict(step='stack', detail='each used frame\'s planes resampled once (Lanczos-4) straight onto the reference frame\'s colour-cell grid (one picture pixel per 2 x 2 cell, %.3f arcsec), times 1 / transparency, minus one constant per colour per frame (3-sigma clipped mean of a sky ring 6 to 11 arcmin around M1, stars masked). Combined per pixel: 3-sigma clip about the median (sigma from the MAD, floor 0.4 x single-frame noise), again about the weighted mean, then the weighted mean. Red and blue resampled again (still one interpolation from the frames) with their measured offset against green (air dispersion, 30 degrees up) taken out of the transform.' % SCALE,
             kappa=S7['kappa'], colour_offsets=S7['colour_offsets'], rejected_by_the_clip={p['plane']: round(p['dropped_fraction'], 4) for p in S7['planes']}, full_coverage_fraction=S7['full_coverage_fraction'],
             halves=S7['subsets']),
        dict(step='plate solve of the stack', detail='astrometry.net on the stack\'s green, each matched star re-centred by this pipeline and a straight-line map fitted', catalogue_stars_used=S8['used_in_fit'], rms_arcsec=round(S8['fit_rms_arcsec'], 2),
             scale_arcsec_per_px=round(SCALE, 4), focal_length_mm=round(S8['focal_length_mm'], 0), parity=S8['parity'], north_deg_clockwise_from_up_in_the_stack=round(S8['north_is_deg_clockwise_from_up'], 2),
             m1_catalogue_stack_px=[round(v, 1) for v in S8['target_catalogue']['stack_px']], nebula_light_from_catalogue_arcsec=round(S9['shape']['light_centre_from_catalogue_arcsec'], 1)),
        dict(step='measure', detail='step9_measure.py: sky plane, noise, the nebula against blank sky, its shape and size, the half stacks and band-passed structure, the pulsar, colour, star sizes. Numbers below.'),
        dict(step='render', detail='crop centred on M1\'s catalogue position, quarter turns only; a sky plane fitted around the crop outside an ellipse 3.4 arcmin along the long axis (the only surface in the pipeline, in the picture only); camera colour matrix; Gaussian 1.5 px, and 6 px where faint (stars left out); colour from a 32 px blur where faint (stars keep their own, smoothed 6 px); arcsinh stretch on luminance (colour ratios kept)',
             numbers={k: v for k, v in S10.items() if k not in ('rgb_cam', 'tif')}),
        dict(step='finish', detail='finish.py from the finish-pictures skill (16-bit input); the exact line is in step11_finish.sh', recipe=FIN),
    ],
    not_done=dict(
        deconvolution='not made. The nebula is %.2f times the noise per pixel and step 9 finds no structure finer than about 25 arcsec that repeats between the half stacks: dividing out the %.1f arcsec blur would raise the noise at exactly the scales it would sharpen, with nothing measured there to sharpen; only the stars would shrink.' % (nb['stack']['mean_dn']['G'] / nz['stack'][1], S9['stars']['hfd_stack_arcsec']),
        enlargement='none: one picture pixel per colour cell',
        neural_or_ai='none: no AI denoise, sharpening or upscaling'),
    numbers=dict(noise_per_px_dn=nz, noise_improvement_green=round(nz['single_reference_frame'][1] / nz['stack'][1], 2), expected=round(S6['expected_noise_gain_vs_reference'], 2),
                 stars=S9['stars'], nebula=S9['nebula'], inner_ellipse_arcmin=S9['inner_ellipse_arcmin'], blank_sky_places=S9['blank_sky_places'], shape=S9['shape'],
                 structure=S9['structure'], pulsar=S9['pulsar'], colour=S9['colour'],
                 profile_green_along_long_axis=[dict(a_arcsec=p['a_arcsec'], mean_dn=p['mean_dn']['G'], odd=p['odd_g'], even=p['even_g'], error=p['error_g']) for p in S9['profile']],
                 plateau_green_dn=S9['plateau_green_dn'], sky_plane_step9=S9['sky_plane'], dark_patches=S9['dark_patches']),
    outputs={
        'm1.jpg': dict(what='finished picture, the sensor\'s scale (%.3f arcsec per px), cropped around the nebula' % SCALE, size_px=S10['picture_size'], field_arcmin=S10['field_arcmin'],
                       orientation='north %.0f degrees clockwise from up, east %.0f degrees anticlockwise from up (as the sky looks, not mirrored); quarter turns only, no resampling' % (S10['north_deg_clockwise_from_up_after'], -S10['east_deg_clockwise_from_up_after']),
                       m1_catalogue_px=[round(v, 1) for v in S10['m1_catalogue_in_picture_px']], jpeg_markers=markers, metadata='none (no EXIF, XMP, ICC or comment segments)'),
        'm1-single-vs-stack.jpg': dict(what='the reference frame alone (left, %s, the sharpest and clearest of the four) and the stack (right): same crop, same sky plane, same render and stretch, the stack\'s own black and white points and gamma, brightness only, no finishing' % S3['reference']),
        'm1-stack.tif': dict(what='the stack, linear, 16-bit RGB (R, mean of G1 and G2, B, times the camera\'s daylight white balance), the area every used frame covers, sensor orientation of the reference frame', **S10['tif'],
                             pixel_scale_arcsec=round(SCALE, 4), origin='pixel (0, 0) is stack px (%d, %d) = sensor px (%d, %d) of the reference frame %s' % (S10['tif']['area_stack_px']['x0'], S10['tif']['area_stack_px']['y0'], 2 * S10['tif']['area_stack_px']['x0'], 2 * S10['tif']['area_stack_px']['y0'], S3['reference']),
                             wcs='stack px -> sky: step 8 (astrometry.net WCS of the stack; subtract the origin above)', wcs_crval=S8['solver']['wcs_crval'], wcs_crpix_stack_px=S8['solver']['wcs_crpix'], wcs_cd=S8['solver']['wcs_cd'])},
    caveats=[
        'Only %d of %d frames (1 minute of light) pass the rule, and they caught %.0f to %.0f%% of the light the clearest frame did: the stack\'s noise is %.2f times lower than its best frame\'s (%.2f expected from the weights). Most of the run was behind the obstruction or smeared by the mount.' % (len(used), len(f1), 100 * tu[0], 100 * tu[-1], nz['single_reference_frame'][1] / nz['stack'][1], S6['expected_noise_gain_vs_reference']),
        'No darks and no flats. Without a flat the sky glow is a dome: outside the nebula the profile levels off about %.0f DN (green) above the plane fitted 6 to 8.4 arcmin out; the picture\'s own plane, fitted just outside the nebula, takes that level off. Darker patches %.0f to %.0f arcmin north of M1 (towards the top right of the picture) are %.0f to %.0f DN deep in green, about %.0f times the smoothed sky\'s scatter, and sit in both half stacks: fixed on the sensor (the four frames moved by under 40 px), most likely dust shadows, not sky.' % (
            S9['plateau_green_dn'], min(np.hypot(*p['offset_east_north_arcmin']) for p in S9['dark_patches']), max(np.hypot(*p['offset_east_north_arcmin']) for p in S9['dark_patches']),
            min(-p['depth_dn']['stack'] for p in S9['dark_patches']), max(-p['depth_dn']['stack'] for p in S9['dark_patches']), max(-p['depth_dn']['stack'] for p in S9['dark_patches']) / S9['dark_patches'][0]['smoothed_sky_sd_dn']),
        'The picture smooths everything faint, off the stars, with a 6 px Gaussian (11 arcsec across, twice the seeing) and takes colour from a 32 px blur (25 arcsec): the oval is shown as smooth as the data allow; what grain is left inside it is noise, not filaments.',
        'Colour is camera-native through the camera\'s own matrix and daylight white balance, with no saturation boost. A stock camera passes little hydrogen-alpha, so the filaments\' red is mostly missing even where they are.',
        'The light-pollution gradient across the crop (about %.0f DN in green and %.0f in blue before the plane) is taken off with one plane per colour; the neutral sky is measured, R-G and B-G within 1 of 255.' % (S10['sky_ramp_across_crop_dn']['G'], S10['sky_ramp_across_crop_dn']['B']),
    ],
    scripts='hack/stacks/2026-10-08/m1/ in the observatory repo: run_all.sh, common.py, step1_hot.py, step2_stars.py, step3_register.py, step4_solve_ref.py, step5_quality.py, step6_select.py, step7_stack.py, step8_solve.py, step9_measure.py, step10_render.py, step11_finish.sh, step12_deliver.py, step13_clean.py, finish.py, skycheck.py, fitsmin.py',
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print(json.dumps(recipe['verdict'], indent=1))
print(json.dumps(recipe['selection']['dropped_in_words'], indent=1))
print('delivered:', sorted(os.listdir(OUT)))
