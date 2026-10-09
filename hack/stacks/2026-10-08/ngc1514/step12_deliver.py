"""Step 12: deliver. The finished JPEG goes to the target folder (checked free of EXIF / XMP / comments: OpenCV writes
none, and the check refuses to deliver one that has any); the single frame against the stack, same stretch and same
levels, no smoothing, brightness only; and recipe.json with every number that shaped the pictures."""
import datetime, glob, json, os, platform, shutil, subprocess
import numpy as np, cv2, rawpy, scipy, tifffile, PIL
from common import *

S1, S3, S4, S5, S6, S7, S8, S9, S10 = (jload(n) for n in ('step1.json', 'step3_transforms.json', 'step4_solve_ref.json', 'step5_quality.json', 'step6_select.json', 'step7.json', 'step8_solve.json', 'step9_measure.json', 'step10.json'))
FIN = json.load(open(W_('ngc1514-finished.json')))
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
markers = deliver_jpeg(W_('ngc1514-finished.jpg'), os.path.join(OUT, 'ngc1514.jpg'))

# ---- single frame against the stack: brightness only, the stack's own black and white points, gamma, no smoothing
LUMA = np.array([0.2126, 0.7152, 0.0722])
def lum(name):
    a = cv2.imread(W_(name), cv2.IMREAD_UNCHANGED)[..., ::-1].astype(np.float64) / 65535.0
    return a @ LUMA
lev = [s for s in FIN['steps'] if s['step'] == 'levels'][0]; mid_ = [s for s in FIN['steps'] if s['step'] == 'midtones'][0]
b, w = lev['black_point'] / 255.0, lev['white_point'] / 255.0
def show(Y): return (np.clip((Y - b) / (w - b), 0, 1) ** mid_['gamma'] * 255 + 0.5).astype(np.uint8)
one, stk = show(lum('single-stretched.png')), show(lum('ngc1514-stretched.png'))
GAP = 8; H_, W_px = one.shape
panel = np.zeros((H_, 2 * W_px + GAP), np.uint8); panel[:, :W_px] = one; panel[:, W_px + GAP:] = stk
for x, text in ((12, 'One 15 s frame'), (W_px + GAP + 12, '%d frames, %.1f minutes' % (len(S7['frames']), len(S7['frames']) * 15 / 60))):
    cv2.putText(panel, text, (x, H_ - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 200, 1, cv2.LINE_AA)
cv2.imwrite(W_('ngc1514-single-vs-stack.jpg'), panel, [cv2.IMWRITE_JPEG_QUALITY, 92])
deliver_jpeg(W_('ngc1514-single-vs-stack.jpg'), os.path.join(OUT, 'ngc1514-single-vs-stack.jpg'))

# ---- recipe
SCALE = float(np.mean(S8['scale_arcsec_per_px']))
f1 = {f['stamp']: f for f in S1['frames']}; tr = {o['stamp']: o for o in S3['transforms']}; q5 = {o['stamp']: o for o in S5['quality']}
used = {u['stamp']: u for u in S6['used']}; rej = {r['stamp']: r for r in S6['rejected']}
frames = []
for s in sorted(f1):
    f = f1[s]; o = tr[s]; q = q5[s]
    d = dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['raw_exif']['exposure_s'], iso=f['raw_exif']['iso'], arw_sha256=f['arw_sha256'], used=s in used,
             why_dropped=rej[s]['why'] if s in rej else None,
             star_hfd_arcsec=round(q['hfd_arcsec'], 2), elongation_median=round(q['elong_median'], 3), common_direction_ellipticity=round(q['coherent_ellipticity'], 3),
             transparency=round(q['transparency'], 3), box_sidecar=dict(star_size_arcsec=f['box_star_size_arcsec'], transparency=f['box_transparency'], since_slew_s=f['since_slew_s'], settling=f['settling']),
             registration=dict(rotation_deg=round(o['rotation_deg'], 4), shift_at_frame_centre_sensor_px=[round(v, 2) for v in o['shift_at_centre_px']], stars_used=o['model_used'], model=o['model'],
                               weighted_rms_px=round(o['model_wrms_px'] if o['model_wrms_px'] is not None else o['wrms_px'], 3)),
             provisional_sky_dn=dict(zip(PLANE_NAMES, [round(x['clipped_mean'], 2) for x in f['bg_provisional']])), transient_spikes_replaced=f['transient_spikes_replaced'])
    if s in used:
        d.update(weight=round(used[s]['weight'], 4), scale=round(used[s]['scale'], 4), sky_constant_dn=S7['constants_dn'][s])
    frames.append(d)
off = [dict(file=f['name'], shutter_pressed_utc=f['t'], why=f['why']) for f in S1['off_target']]
sh = np.array([o['shift_at_centre_px'] for o in S3['transforms'] if o['stamp'] in used]); rot = np.array([o['rotation_deg'] for o in S3['transforms'] if o['stamp'] in used])
sh9 = S9['shell']
ts = sorted(datetime.datetime.fromisoformat(f1[s]['t'].replace('Z', '+00:00')) for s in used); span_min = (ts[-1] - ts[0]).total_seconds() / 60
recipe = dict(
    what='NGC 1514, the Crystal Ball Nebula: %d x 15 s at ISO 3200 (%.1f minutes), Sony a6000 on a Celestron 8SE (2081 mm by plate solve, f/10), EQ6-R tracking on a pointing model; stacked from RAW colour planes' % (len(used), len(used) * 0.25),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    target=TARGET,
    verdict=dict(shell_detected=True,
                 how_strongly='The shell is there. Its mean light 12 to 60 arcsec from the star is %.1f DN in green per pixel (raw camera units; blue %.1f, red %.1f), %d times the uncertainty from pixel noise and %.0f times the scatter of the same ring laid on blank sky nearby (sky structure left by the missing flat). Per pixel it is %.1f times the noise at the sensor\'s scale, %.1f times after a 2 x 2 mean and about %.0f times after a 2 px Gaussian: a faint glow that needs the gentle smoothing the picture has. Both half stacks show it on their own (%.1f and %.1f DN) with the same shape (correlation %.2f inside the shell against %.2f +- %.2f on blank sky). The central star\'s own spilled light, predicted from other bright stars in the stack, is %.0f%% of the light in that ring, nearly all of it within 25 arcsec of the star.' % (
                     sh9['stack']['shell_mean_dn']['G'], sh9['stack']['shell_mean_dn']['B'], sh9['stack']['shell_mean_dn']['R'], int(sh9['stack']['signal_to_pixel_noise']['G']), sh9['stack']['signal_to_sky_structure']['G'],
                     sh9['stack']['shell_mean_dn']['G'] / S9['noise_per_px_dn']['stack'][1], sh9['stack']['shell_mean_dn']['G'] / S9['noise_per_px_dn']['stack_2x2_mean'][1], sh9['stack']['shell_mean_dn']['G'] / S9['noise_per_px_dn']['stack_gauss2'][1],
                     sh9['odd']['shell_mean_dn']['G'], sh9['even']['shell_mean_dn']['G'], S9['halves']['shape_correlation_in_shell'], S9['halves']['blank_sky_correlation_mean'], S9['halves']['blank_sky_correlation_std'],
                     100 * S9['central_star_light']['fraction_of_shell_annulus_light']),
                 size='bright to %.0f arcsec from the star, half as bright by %.0f arcsec, fading into the sky by about 90 arcsec: about %.1f arcmin across at half brightness (catalogue 2.2 x 1.9)' % (47, S9['shell_half_brightness_radius_arcsec'], 2 * S9['shell_half_brightness_radius_arcsec'] / 60),
                 colour='blue-green: in the camera\'s daylight white balance the shell\'s red : green : blue is %.2f : 1 : %.2f' % (S9['shell_colour']['ratio_to_green']['R'], S9['shell_colour']['ratio_to_green']['B'])),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, tifffile=tifffile.__version__, pillow=PIL.__version__,
               astrometry_net=subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip(),
               note='deterministic array arithmetic only (averages, medians, fitted planes, Gaussian and bilateral filters, a fixed arcsinh curve); nothing generative or learned, no AI denoise, sharpening or upscaling'),
    source=dict(folder=STILLS, originals='read in place, never written', window=[T0, T1], frames_in_window=len(S1['all_in_window']), frames_on_target=len(S1['frames']), frames_used=len(used), frames_dropped=len(rej),
                off_target=off),
    selection=dict(rule=S6['limits'], rule_words='used if: not taken during or right after a slew or centring nudge (settling false and more than 10 s since the move); star half-flux diameter <= 6.5 arcsec; median elongation <= 1.35 and common-direction ellipticity <= 0.20 (no trailing); transparency >= 0.80; registration rms <= 1.5 px',
                   transparency='whole field: the median over %d bright unclipped stars of each star\'s flux against its own median over the run, clearest frame = 1; every used frame 0.97 to 1.00, the sky was clear' % len(S5['quality_star_ref_index']),
                   weights='(transparency / noise)^2, noise = the frame\'s green pixel noise over the clear-frame median; each used frame multiplied by 1 / transparency first; sum of weights %.2f, effective frames %.2f' % (S6['sum_of_weights'], S6['effective_frames']),
                   what_went_wrong='the clear sky was not the problem; the mount was: the three centring frames (07:38:11 to 07:39:38) and frames smeared in one direction while the hold settled (07:40:13 to 07:43:54) and again in single frames at 07:48:02, 07:51:02 and 07:52:51 (stars 6.1 to 9.7 arcsec, elongation 1.6 to 2.9, all stretched along the same angle, -54 to -68 degrees in the sensor frame). Two sharp frames between the smeared ones (07:42:05, 07:43:17) pass and are used.'),
    frames=frames,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (sensor orientation, 6024 x 4024, RGGB), black level 512 subtracted, four colour planes R, G1, G2, B at 3012 x 2012, no demosaic; exposure and ISO confirmed from each RAW\'s EXIF'),
        dict(step='hot pixels', detail='fixed: per-plane median of all 25 on-target frames without registration (the centring moved the field by up to 1050 px and it drifted while tracking), pixels above the 5 x 5 median of that by more than max(6 sigma, 25% of the level); transient: per frame, above the 3 x 3 median by more than 8 sigma + 50% of the level. Both replaced by the 3 x 3 median of the same colour plane. No darks.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in S1['hot']}),
        dict(step='stars', detail='green planes averaged, smooth background from 64 px block medians taken off, 6-sigma blobs, Gaussian-windowed centroid, 14 px (plane) aperture flux, half-flux radius, second moments'),
        dict(step='register', detail='reference %s (most stars). Rotation and offset by a vote over the brightest 80 stars (+-2.5 degrees, +-1600 px), then weighted least squares with rejection: rigid, then a 2nd-order polynomial (50+ stars) used for resampling. Scale left free came out within 0.0002 of 1.' % S3['reference'],
             used_frames=dict(rotation_deg=[round(float(rot.min()), 4), round(float(rot.max()), 4)], field_rotation_deg_per_minute=round(float((rot.max() - rot.min()) / span_min), 4), shift_at_centre_sensor_px=dict(x=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], y=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]))),
        dict(step='is it the thing', detail='the reference frame alone plate-solved (astrometry.net, %d index stars): NGC 1514\'s catalogue position at sensor px (%.1f, %.1f); the brightest star there, %.2f arcsec from it, is the 9.4 mag central star' % (S4['index_stars_matched'], *S4['target_sensor_px'], S4['central_star']['offset_from_catalogue_arcsec'])),
        dict(step='stack', detail='each used frame\'s planes resampled once (Lanczos-4) straight onto the reference frame\'s colour-cell grid (one picture pixel per 2 x 2 cell, %.3f arcsec), times 1 / transparency, minus one constant per colour per frame (3-sigma clipped mean of a sky ring 3.2 to 9 arcmin around the nebula, stars masked). Combined per pixel: 3-sigma clip about the median (sigma from the MAD, floor 0.4 x single-frame noise), again about the weighted mean, then the weighted mean. Red and blue resampled again with their offset against green (air dispersion) taken out.' % SCALE,
             kappa=S7['kappa'], colour_offsets=S7['colour_offsets'], rejected_by_the_clip={p['plane']: round(p['dropped_fraction'], 4) for p in S7['planes']}, full_coverage_fraction=S7['full_coverage_fraction']),
        dict(step='plate solve of the stack', detail='astrometry.net on the stack\'s green, each matched star re-centred by this pipeline and a straight-line map fitted', catalogue_stars_used=S8['used_in_fit'], rms_arcsec=round(S8['fit_rms_arcsec'], 2),
             scale_arcsec_per_px=round(SCALE, 4), focal_length_mm=round(S8['focal_length_mm'], 0), parity=S8['parity'], north_deg_clockwise_from_up_in_the_stack=round(S8['north_is_deg_clockwise_from_up'], 2),
             central_star_from_catalogue_arcsec=round(S8['central_star_centroid']['offset_arcsec'], 2), shell_light_centroid_from_catalogue_arcsec=round(S8['shell_light_centroid']['offset_arcsec'], 1)),
        dict(step='measure', detail='step9_measure.py: sky plane, noise, the shell against blank sky, the half stacks, the central star\'s own light from comparison stars. Numbers below.'),
        dict(step='render', detail='crop centred on the central star, quarter turns only, sky plane outside 101 arcsec, camera colour matrix, Gaussian 1 px, colour noise step (colour from an 8 px blur where faint, star cores left out), clipped cores shown white, arcsinh stretch on luminance (colour ratios kept)', numbers={k: v for k, v in S10.items() if k not in ('rgb_cam', 'tif')}),
        dict(step='finish', detail='finish.py from the finish-pictures skill (16-bit input); the exact line is in step11_finish.sh', recipe=FIN),
    ],
    not_done=dict(deconvolution='not made. The central star\'s core is clipped in green and blue (a restoration rings around a clipped core), and the shell is %.1f times the noise per pixel: dividing out the 4.9 arcsec blur would raise that noise long before it sharpened a shell whose rims are tens of arcsec wide.' % (sh9['stack']['shell_mean_dn']['G'] / S9['noise_per_px_dn']['stack'][1]),
                  darks_and_flats='none were taken: hot pixels are repaired from the run itself; vignetting and dust are not corrected (a plane is taken off the sky around the nebula instead)',
                  enlargement='none: one picture pixel per colour cell'),
    numbers=dict(noise_per_px_dn=S9['noise_per_px_dn'], noise_improvement_green=round(S9['noise_per_px_dn']['single_reference_frame'][1] / S9['noise_per_px_dn']['stack'][1], 2), ideal=round(float(np.sqrt(S6['effective_frames'])), 2),
                 stars=S9['stars'], shell=S9['shell'], shell_annulus_arcsec=S9['shell_annulus_arcsec'], blank_sky_positions=S9['blank_sky_positions'], halves=S9['halves'],
                 central_star_light=dict(fraction_of_shell_annulus_light=S9['central_star_light']['fraction_of_shell_annulus_light'], comparison_stars=len(S9['central_star_light']['comparison_stars']), rings=[r for r in S9['central_star_light']['rings'] if r['r_px'][0] < 120]),
                 profile_green=[dict(r_arcsec=p['r_arcsec'], mean_dn=p['mean_dn']['G'], odd=p['odd_mean_g'], even=p['even_mean_g'], error=p['mean_error_g']) for p in S9['profile']],
                 shell_colour=S9['shell_colour'], sky_plane=S9['sky_plane']),
    outputs={
        'ngc1514.jpg': dict(what='finished picture, the sensor\'s scale (%.3f arcsec per px), cropped around the nebula' % SCALE, size_px=S10['picture_size'], field_arcmin=S10['field_arcmin'],
                            orientation='north %.0f degrees clockwise from up, east %.0f degrees anticlockwise from up (as the sky looks, not mirrored); quarter turns only, no resampling' % (S10['north_deg_clockwise_from_up_after'], -S10['east_deg_clockwise_from_up_after']),
                            central_star_px=[round(v, 1) for v in S10['central_star_in_picture_px']], jpeg_markers=markers, metadata='none (no EXIF, XMP, ICC or comment segments)'),
        'ngc1514-single-vs-stack.jpg': dict(what='the reference frame alone (left) and the stack (right): same crop, same sky plane, same stretch, the stack\'s own black and white points and gamma, brightness only, no smoothing or colour'),
        'ngc1514-stack.tif': dict(what='the stack, linear, 16-bit RGB (R, mean of G1 and G2, B, times the camera\'s daylight white balance), the area every used frame covers, sensor orientation of the reference frame', **S10['tif'],
                                  pixel_scale_arcsec=round(SCALE, 4), origin='pixel (0, 0) is stack px (%d, %d) = sensor px (%d, %d) of the reference frame %s' % (S10['tif']['area_stack_px']['x0'], S10['tif']['area_stack_px']['y0'], 2 * S10['tif']['area_stack_px']['x0'], 2 * S10['tif']['area_stack_px']['y0'], S3['reference']),
                                  wcs='stack px -> sky: step 8 (astrometry.net WCS of the stack; subtract the origin above)', wcs_crval=S8['solver']['wcs_crval'], wcs_crpix_stack_px=S8['solver']['wcs_crpix'], wcs_cd=S8['solver']['wcs_cd'])},
    caveats=[
        'No darks and no flats. Hot pixels were repaired from the run; vignetting is not corrected. The sky around the nebula is taken off with a plane, and the scatter of %.1f DN (green) between blank-sky rings of the shell\'s size is that uncorrected structure: faint light 90 to 190 arcsec from the star (about 2 to 3 DN, the level of that structure) is not claimed as nebula.' % S9['shell']['stack']['blank_sky_scatter_dn']['G'],
        'The central star\'s core is clipped in green and blue in every frame; there its colour is unknown and is shown white by rule. Its photometry is not usable.',
        'The shell is faint: about %.1f times the per-pixel noise at the sensor\'s scale. The picture smooths the dark parts (5 px median and a bilateral filter in finish.py, colour from an 8 px blur): the shell\'s large shape (the round shell, the brighter lobes on either side of the star) is measured and repeats in both half stacks; pixel-scale texture inside it is not information.' % (sh9['stack']['shell_mean_dn']['G'] / S9['noise_per_px_dn']['stack'][1]),
        'Colour is camera-native through the camera\'s own matrix and daylight white balance. A stock camera passes little hydrogen-alpha, so the shell shows mostly its blue-green light.',
        'Only %d of the 25 frames on NGC 1514 are used (%.1f minutes): the rest were centring frames or smeared by the mount.' % (len(used), len(used) * 0.25),
    ],
    scripts='hack/stacks/2026-10-08/ngc1514/ in the observatory repo: run_all.sh, common.py, step1_hot.py, step2_stars.py, step3_register.py, step4_solve_ref.py, step5_quality.py, step6_select.py, step7_stack.py, step8_solve.py, step9_measure.py, step10_render.py, step11_finish.sh, step12_deliver.py, step13_clean.py, finish.py, skycheck.py, fitsmin.py',
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print(json.dumps(recipe['verdict'], indent=1))
print('delivered:', sorted(os.listdir(OUT)))
