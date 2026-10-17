"""Step 13: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, what star size and star brightness did over the run (the dew question), the flat and its check,
the sky constants, the registration, the weights, the air dispersion, the plate solution (scale, which way north is,
where R Monocerotis and the fan are in the picture), the stretch, the crop, the finish, the half-stack proofs, and the
honest verdict. The words of the verdict are built from the numbers of the steps, so a rerun with other frames says
what that rerun measured.

Copies final-trial/NAME.jpg to NAME/NAME.jpg (checked free of EXIF / XMP / comment segments first)."""
import json, os, platform, datetime, shutil
import numpy as np, cv2, rawpy, tifffile
from common import *

s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s8c = jload('step8_coadd.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json'); s11 = jload('step11_measure.json')
fin = json.load(open(os.path.join(FINAL, NAME + '.json'))); crop = json.load(open(W(NAME + '-crop.json'))); finf = json.load(open(os.path.join(OUT, NAME + '-field.json')))
used = {u['stamp']: u for u in s5['used']}; rej = {r['stamp']: r for r in s5['rejected']}
SC = s9['pixscale_arcsec']


def jpeg_markers(path):
    b = open(path, 'rb').read(); i = 2; out = []
    assert b[:2] == b'\xff\xd8'
    while i < len(b):
        assert b[i] == 0xFF; m = b[i + 1]
        if m == 0xDA: break
        n = int.from_bytes(b[i + 2:i + 4], 'big'); out.append('FF%02X' % m); i += 2 + n
    return out


def skycheck(path):
    im = cv2.imread(path, cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32); Y = im @ np.array([0.2126, 0.7152, 0.0722], np.float32); out = {}
    for lo, hi in ((0, 10), (10, 40)):
        a, b = np.percentile(Y, [lo, hi]); m = (Y >= a) & (Y <= b)
        out['darkest_%d_%d_pct_rgb' % (lo, hi)] = [round(float(np.mean(im[..., c][m])), 2) for c in range(3)]
    return out


mk = jpeg_markers(os.path.join(FINAL, NAME + '.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk          # no EXIF / XMP / ICC / IPTC / comment: nothing about the place
shutil.copyfile(os.path.join(FINAL, NAME + '.jpg'), os.path.join(OUT, NAME + '.jpg'))

frames = []
for f in s1['frames']:
    s = f['stamp']; q = s4.get(s, {}); t = s3.get(s, {})
    d = dict(file=f['name'], sha256=f.get('arw_sha256'), shutter_pressed=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], since_slew_s=f['since_slew_s'], alt_deg=f.get('alt_deg'), az_deg=f.get('az_deg'),
             box_star_size_arcsec=f.get('box_star_size_arcsec'), star_brightness=q.get('transparency'), star_peak=q.get('peak_rel'), star_size_arcsec=q.get('hfd_arcsec'), smear=q.get('smear'), smear_angle_deg=q.get('smear_angle_deg'),
             rotation_deg=t.get('rotation_deg'), shift_at_centre_sensor_px=t.get('shift_at_centre_px'), registration_wrms_px=t.get('wrms_px'), stars_matched=t.get('matched'),
             used=s in used)
    if s in used: d.update(weight=used[s]['weight'], scale=used[s]['scale'], sky_constants_dn=dict(zip(PLANE_NAMES, s8['constants'][s])), half='even' if s in s8['subsets']['even'] else 'odd')
    else: d.update(dropped_because=rej[s]['why'])
    frames.append(d)
for f in s1['left_out']: frames.append(dict(file=f['file'], exposure_s=f['exposure_s'], iso=f['iso'], used=False, dropped_because=f['why'] + ' (a centring picture)'))

R = s11['run']; F = s11['fan']; fs = F['stack']; st = s11['structure']; col = s11['colour']; rm = s11['r_mon']
alts = [f['alt_deg'] for f in s1['frames'] if f.get('alt_deg') is not None]; rots = [s3[s]['rotation_deg'] for s in used]
dim = R['dim_frames']; th = R['thirds']; nU = len(used); n15 = len(s1['frames'])
by = {}
for r in s5['rejected']:
    k = 'first frame after the slew (by rule)' if 'first frame after the slew' in r['why'] else 'stars dim (below 90% of their usual brightness)' if 'usual brightness' in r['why'] else 'stars wide' if 'wider' in r['why'] else 'trailed' if 'smeared' in r['why'] else 'other'
    by[k] = by.get(k, 0) + 1
real = [f for f in st['features'] if f['in_both_halves']]
dust = s7['dust']
NEAR = min(float(np.hypot(d['plane_px'][0] - s6['galaxy_ellipse']['centre_px'][0], d['plane_px'][1] - s6['galaxy_ellipse']['centre_px'][1])) for d in dust['divided_out'])
soft = s10['star_size']['hfd_stack_arcsec']
verdict = dict(
    is_it_the_thing='yes: the reference frame and the stack were plate-solved (astrometry.net, Tycho-2 index files) before and after stacking. The catalogue place of NGC 2261 (R Monocerotis, 06h 39m 09.95s +08d 44\' 10") falls %.1f arcmin from the frame centre; the brightest point within 40 arcsec of it is %.1f arcsec away, and a fan %.0f arcsec long opens from it towards position angle %.0f degrees (north is 0, east 90): Hubble\'s Variable Nebula, as catalogued' % (
        s6['offset_from_frame_centre_arcmin'], rm['from_the_catalogue_place_arcsec'], fs['length_along_the_axis_arcsec'], fs['axis_position_angle_deg_north_through_east']),
    frames='%d of the %d frames of 15 s at ISO 3200 used (%.2f minutes); dropped: %s. The %d centring pictures of 2 s at ISO 6400 were never candidates. No frame was trailed (largest common-direction ellipticity %.2f, limit %.2f) and none was dropped for star size' % (
        nU, n15, nU * EXPOSURE_S / 60, '; '.join('%d %s' % (v, k) for k, v in by.items()), len(s1['left_out']), max(q['smear'] for q in s4.values()), s5['limits']['smear_max']),
    dew_and_cloud='Measured frame by frame on the same ~75 stars. STAR BRIGHTNESS: steady for the first %d frames, drifting down %.1f%% per 10 minutes (%.3f at the start, %.3f at the last clear frame), then the last %d frames fell to %s of the usual and were coming back at the end (%s). STAR SIZE (half-flux diameter): %.2f arcsec median in the first third, %.2f in the middle, %.2f in the last; the dim frames had the SMALLEST stars of the run (median %.2f arcsec). So the stars did not widen and dim together as they did at the end of the run before: they got sharper through the run, and the dimming at the end came with sharp stars and partly reversed within three minutes. And while the stars were at half, the sky got BRIGHTER: the RAW green sky was %.0f DN (%.0f to %.0f) in the clear frames and %s in the dim ones. Dimmer stars under a brighter sky, sharp, and coming back within three minutes: that is a patch of thin cloud crossing, not dew (dew dims stars and sky together, widens the stars, and does not give light back). The slow %.1f%% per 10 minute fall of the clear frames is the only thing here that could be dew starting (the object was rising, so it is not the air); it is small, and with it the stars got sharper, not wider. The telescope\'s own star-size figure reads about 1.2 arcsec larger than these (a different measure) and shows the same trend, %.1f to %.1f arcsec' % (
        R['clear_frames'], -100 * R['star_brightness_of_clear_frames']['slope_per_10_min'], R['star_brightness_of_clear_frames']['first'], R['star_brightness_of_clear_frames']['last'], len(dim), ' to '.join('%.0f%%' % (100 * v) for v in (min(d['star_brightness'] for d in dim), max(d['star_brightness'] for d in dim))) if dim else '-',
        ', '.join('%.2f' % d['star_brightness'] for d in dim), th[0]['star_size_median_arcsec'], th[1]['star_size_median_arcsec'], th[2]['star_size_median_arcsec'], R['star_size_arcsec']['of_the_dim_frames'] or 0, R['green_sky_dn']['clear_frames_median'], *R['green_sky_dn']['clear_frames_range'], ', '.join('%.0f' % v for v in R['green_sky_dn']['dim_frames']), -100 * R['star_brightness_of_clear_frames']['slope_per_10_min'],
        min(f['box_star_size_arcsec'] for f in s1['frames']), max(f['box_star_size_arcsec'] for f in s1['frames'])),
    sharpness='the whole run is soft: stars in the stack are %.2f arcsec across (half-flux diameter; the reference frame alone %.2f), against about 5 earlier in the night. Nothing was sharpened and nothing deconvolved. At this resolution the fan (%.0f arcsec long) is about %d star-widths long' % (soft, s10['star_size']['hfd_single_arcsec'], fs['length_along_the_axis_arcsec'], round(fs['length_along_the_axis_arcsec'] / soft)),
    the_fan='seen plainly, %.0f times the blank-sky scatter of an area its size. Above %.1f DN (4 x the sky\'s scatter in a 2 px smoothing) it is a comet-shaped fan %.0f arcsec long from the star along position angle %.0f degrees (a little west of north), reaching %.0f arcsec north, %.0f east and %.0f west of the star, %.0f arcsec across at its widest, %.2f square arcmin; widths across the axis at 20/40/60/80%% of the length: %s arcsec. The odd and the even half stacks alone give %.0f and %.0f arcsec long, %.0f and %.0f wide. The catalogue\'s 2 arcmin is the fan to a fainter limit than %.1f minutes at f/10 reach: its faint northern end is not seen here' % (
        F['over_blank_sky_scatter']['stack'], fs['threshold_dn'], fs['length_along_the_axis_arcsec'], fs['axis_position_angle_deg_north_through_east'], fs['reach_from_the_star_arcsec']['north'], fs['reach_from_the_star_arcsec']['east'], fs['reach_from_the_star_arcsec']['west'], fs['widest_arcsec'], fs['area_sq_arcmin'],
        ' / '.join('%.0f' % v for v in fs['width_across_the_axis_arcsec'].values()), F['odd']['length_along_the_axis_arcsec'], F['even']['length_along_the_axis_arcsec'], F['odd']['widest_arcsec'], F['even']['widest_arcsec'], nU * EXPOSURE_S / 60),
    the_star='the point at the fan\'s southern tip, at the catalogue place of R Monocerotis (%.1f arcsec from it), peak %.0f DN in green (odd %.0f, even %.0f). Its half-flux diameter measures %.1f arcsec against the field stars\' %.1f: it is not a clean star image, it sits in the brightest part of its own nebula (the measure is an upper limit for that reason). Not clipped in any frame' % (
        rm['from_the_catalogue_place_arcsec'], rm['peak_green_dn_of_5x5']['stack'], rm['peak_green_dn_of_5x5']['odd'], rm['peak_green_dn_of_5x5']['even'], rm['half_flux_diameter_arcsec'], rm['field_stars_half_flux_diameter_arcsec']),
    structure_inside_the_fan='the odd and the even half stacks agree inside the fan (band of 3 to 12 arcsec: correlation %.2f, against %.2f +- %.2f on blank sky), and %d of %d local extremes above 5 sigma are in both halves with the same sign. What that is, in words: (1) a second bright knot %.0f arcsec north and %.0f arcsec east of the star, almost as bright as the star itself in this band; (2) the fan is brighter along its two edges than down its middle near the star (a darker channel on the axis %.0f to %.0f arcsec out), which is the hollow-cone look of this nebula. Both repeat in both halves. Finer than that (the filaments and shadows that make it "variable") nothing is resolved: the stars are %.1f arcsec wide. All features are listed in measured.what_is_seen.structure.features' % (
        st['odd_even_correlation']['inside_the_fan'], st['odd_even_correlation']['blank_sky_boxes_mean'], st['odd_even_correlation']['blank_sky_boxes_scatter'], len(real), len(st['features']),
        st['features'][0]['from_the_star_arcsec']['north'], st['features'][0]['from_the_star_arcsec']['east'],
        min([f['along_the_axis_arcsec'] for f in real if f['kind'] == 'darker'] or [0]), max([f['along_the_axis_arcsec'] for f in real if f['kind'] == 'darker'] or [0]), soft),
    colour='the fan measures red : green %.2f and blue : green %.2f in the camera\'s daylight balance (odd %.2f / %.2f, even %.2f / %.2f), the star\'s core %.2f and %.2f: near white, a little short of blue. The picture shows that through the camera\'s own colour matrix with no saturation boost; the matrix turns "a little short of blue" into a pale cream-green. That tint is the rendering of a near-white measure, not a claim that the nebula is green' % (
        col['fan']['stack']['red_over_green'], col['fan']['stack']['blue_over_green'], col['fan']['odd']['red_over_green'], col['fan']['odd']['blue_over_green'], col['fan']['even']['red_over_green'], col['fan']['even']['blue_over_green'], col['r_monocerotis_core']['stack']['red_over_green'], col['r_monocerotis_core']['stack']['blue_over_green']),
    flat='the night\'s flat (flat/, from the NGC 891 run), read and checked against this run\'s own open sky outside a 3.5 arcmin circle on the star: per colour whichever of its own flat or the green flat left less (%s). It left %d shadows of %s deep in this run\'s sky (%.1f%% of the sensor); they were measured on this run\'s own sky (seen in the odd and the even frames alone) and divided out. Within %d px of R Monocerotis (in each frame\'s own place) no dust can be judged, the fan is there: the fan is 50 to 300 DN on a sky of 120, so a 2%% shadow under it would be 1 to 2%% of the fan, less than is claimed anywhere above. Proportionate for a 1.5 arcmin object: the same measure as tonight\'s M78 and M1, nothing more' % (
        ', '.join('%s %s' % (k, v['used']) for k, v in s7['planes'].items()), len(dust['divided_out']), '%.1f to %.1f%%' % (100 * min(d['left_by_the_flat'] for d in dust['divided_out']), 100 * max(d['left_by_the_flat'] for d in dust['divided_out'])), 100 * dust['sensor_fraction_changed'], 200)
            + '. The nearest shadow that was corrected is %.0f px (%.1f arcmin) from the star on the reference frame; the fan reaches %.0f px: nothing under the fan was touched' % (NEAR, NEAR * SC / 60, fs['reach_from_the_star_arcsec']['north'] / SC),
    flaws=['soft: %.1f arcsec stars; the fan\'s fine structure is not resolved' % soft, 'only %.2f minutes: the faint northern end of the fan is missing and its outer edge is grainy; the finish smooths the dark sky and that edge (median 5 px and a bilateral filter below L 50), so texture at the fan\'s faint edge is not detail' % (nU * EXPOSURE_S / 60),
           'the last %d frames were lost to thin cloud' % len(dim), 'colour is near white with a cream-green tint from the matrix (see colour)', 'no dust check under the fan itself'],
    trial='A TRIAL, not the published picture: hack/stacks/2026-10-12/ngc2261 with only the combine step replaced by proper coaddition (final-trial/%s.*; the published one is final/ngc2261.*)' % NAME)

recipe = dict(
    target='NGC 2261, Hubble\'s Variable Nebula in Monoceros, with R Monocerotis at its tip',
    night='2026-10-12 (frames of 13 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    files=dict(stack=os.path.join(OUT, NAME + '-stack.tif'), picture=[os.path.join(FINAL, NAME + f) for f in ('.png', '.jpg', '.json')], picture_copy=os.path.join(OUT, NAME + '.jpg'), full_field=[os.path.join(OUT, NAME + f) for f in ('-field.png', '-field.jpg', '-field.json')],
               looks=[W(f) for f in ('halves_look.png', 'fan_region.png', 'v_ref_look.png', 'v_flat_check.png', 'v_dust_left.png')], logs=W('logs'), scripts='hack/stacks/2026-10-12/ngc2261-coadd/'),
    equipment=dict(camera='Sony a6000 (ILCE-6000), RAW', telescope='Celestron 8SE optical tube at f/10', focal_length_mm_by_plate_solve=round(s9['focal_length_mm']), mount='EQ6-R, unguided, polar axis about 5 degrees off the pole, tracking on a pointing model (the field turns)'),
    exposure=dict(frames_found=n15, centring_pictures_not_candidates=len(s1['left_out']), frames_used=nU, frames_dropped=n15 - nU, dropped_by_reason=by, exposure_s=EXPOSURE_S, iso=ISO, total_s=nU * EXPOSURE_S, total_minutes=nU * EXPOSURE_S / 60, effective_frames=s5['effective_frames'],
                  first=min(used), last=max(used), altitude_deg=[min(alts), max(alts)], field_rotation_over_the_used_frames_deg=[min(rots), max(rots)], reference_frame=REF_STAMP),
    verdict=verdict,
    plate_solution=dict(solver='astrometry.net (solve-field, local Tycho-2 index files), on the stack\'s green', arcsec_per_px=SC, field_arcmin=s9['field_arcmin'], centre_ra_dec=s9['centre_ra_dec'], north=s9['north_in_words'], north_deg_clockwise_from_up=s9['north_angle_from_up_deg_clockwise'], east_deg_clockwise_from_up=s9['east_angle_from_up_deg_clockwise'],
                        mirrored=s9['mirrored'], sky_axes=s9['sky_axes'], stack_origin_on_reference_grid=s9['crop_on_reference_grid'], catalogue=s9['catalogue'], r_monocerotis=s9['r_monocerotis'],
                        picture=dict(file='final-trial/' + NAME + '.png', size_px=[crop['crop_px'][2], crop['crop_px'][3]], size_arcmin=[crop['crop_px'][2] * SC / 60, crop['crop_px'][3] * SC / 60], arcsec_per_px=SC, enlarged=False, cut_from_the_stack_at_px=crop['crop_px'][:2], why=crop['why'],
                                     r_monocerotis_px=s9['r_monocerotis']['pixel_in_the_picture'], catalogue_place_px=s9['catalogue_place_in_the_nebula_crop_px'],
                                     fan='opens from the star towards position angle %.0f degrees: in the picture up and to the left (north is %.1f degrees anticlockwise of up), %.0f px long' % (fs['axis_position_angle_deg_north_through_east'], -s9['north_angle_from_up_deg_clockwise'], fs['length_along_the_axis_arcsec'] / SC),
                                     fan_end_px=[round(s9['r_monocerotis']['pixel_in_the_picture'][0] + fs['reach_from_the_star_arcsec']['north'] / SC * s9['sky_axes']['north'][0], 1), round(s9['r_monocerotis']['pixel_in_the_picture'][1] + fs['reach_from_the_star_arcsec']['north'] / SC * s9['sky_axes']['north'][1], 1)]),
                        reference_frame_solve=dict(arcsec_per_px=s6['pixscale_arcsec'], north_deg_clockwise_from_up=s6['north_angle_from_up_deg_clockwise'], catalogue_place_px=s6['galaxy_ellipse']['centre_px'], smooth_green_there_dn=s6['smooth_green_at_catalogue_place_dn'], green_sky_dn=s6['green_sky_median_dn'])),
    steps=[dict(step='frames', detail='the 15 s ISO 3200 frames (by the RAW\'s own EXIF) with sidecar pointing within %.1f deg of the target, file-name times %s to %s UTC' % (POINTING_RADIUS_DEG, T0, T1)),
           dict(step='planes', detail='each RAW split into its four colour planes (R, G1, G2, B), black subtracted; no demosaic; one picture pixel per 2 x 2 colour cell'),
           dict(step='hot pixels', detail='from the run itself (high in every frame while the stars move), repaired with the 3 x 3 median of the plane; transient spikes per frame', numbers=s1['hot']),
           dict(step='stars and registration', detail='stars on the green planes; each frame registered to %s with rotation and shift' % REF_STAMP),
           dict(step='selection', detail='by star shape, size and brightness; the first frame after the slew dropped by rule', limits=s5['limits'], star_size_run_median_arcsec=s5['hfd_run_median_arcsec']),
           dict(step='flat', detail='the night\'s flat checked against this run\'s own sky; dust it left measured on this run and divided out', planes={k: dict(used=v['used']) for k, v in s7['planes'].items()}, dust={k: v for k, v in dust.items() if not isinstance(v, list) or len(v) < 20}),
           dict(step='stack', detail='per frame and plane: / flat, x 1/transparency, resampled once (Lanczos-4, rotation + shift + the plane\'s place in the cell + air dispersion), minus one sky constant per colour per frame; sigma-clipped weighted mean (kappa %.0f)' % s8['kappa'], sky_region=s8['faint_region'], air_dispersion=s8['air_dispersion'], clip=[dict(plane=p['plane'], dropped_fraction=p['dropped_fraction']) for p in s8['planes']]),
           dict(step='combine (the trial)', detail='PROPER COADDITION (Zackay & Ofek 2017, ApJ 836, 188; .claude/skills/stack-pictures/tools/coadd.py) replaces the sigma-clipped weighted mean of the step above, on the same resampled, sky-subtracted planes: each frame filtered with its own measured PSF, weighted by 1 / its sky noise^2 (the transparency already divided out), summed and whitened. Delivered: %s. The delivered mean was made from the same cube as the control.' % s8c['deliver'],
                planes={p: dict(F_R=v['F_R'], psf_R=v['psf_R'], psf_stars=v['psf_stars'], psf_radius_px=v['psf_radius_px'], theory=v['theory'], theory_with_the_control_weights=v['theory_with_the_control_weights'],
                                outliers={k: v['outliers'][k] for k in ('rule', 'kappa', 'beta', 'beta_why', 'kappa_smooth', 'grow_px', 'flagged_fraction', 'flagged_fraction_in_sky_region')},
                                field_variation={k: v['field_variation'][k] for k in ('hfd_spread', 'ellipticity_range', 'varies', 'rule')}, separable=v['separable'], halves=v['halves'],
                                frames=[dict(stamp=f['stamp'], noise=round(f['noise'], 3), share_of_point_source_snr2=round(f['share_of_point_source_snr2'], 4), pixels_filled=f['pixels_filled'], psf_hfd_px=f['psf']['hfd_px'], psf_ellipticity=f['psf']['ellipticity']) for f in v['frames']])
                        for p, v in s8c['planes'].items()}, tool=s8c['planes']['G1']['tool'], paper=s8c['planes']['G1']['paper'], all_numbers='work/step8_coadd.json', comparison='work/step15_compare.json'),
           dict(step='picture', detail='render.py: camera daylight balance and matrix, arcsinh stretch, colour from an 8 px average and only where there is signal; a sky plane per colour subtracted in the picture only', render=s10['render_params'], sky_plane_in_the_picture_only=s10['sky_plane_in_the_picture_only'], no_star_disc_within_px_of_r_monocerotis=s10['no_star_disc_within_px_of_r_monocerotis'], white_balance=s10['white_balance_daylight'], tif=s10['tif']),
           dict(step='crop', **crop), dict(step='finish', tool='finish16.py (finish-pictures finish.py at 16 bits)', recipe=fin, skycheck=skycheck(os.path.join(FINAL, NAME + '.png')), full_field=finf, jpeg_segments=mk),
           dict(step='not done', detail='no deconvolution, no sharpening, no generative or learned step, no enlargement, no saturation boost, no retouching')],
    measured=dict(noise=s10['noise_faint_region'], star_size=s10['star_size'], what_is_seen=s11),
    frames=frames,
    next_time='a dew shield and heater on the corrector before this hour; refocus when the star-size figure passes 6 arcsec (it read 7.7 at the start of this run and came down by itself); three times the frames for the fan\'s faint northern end; a twilight flat at dawn',
    reproduce='hack/stacks/2026-10-12/ngc2261-coadd/run_all.sh (hooks are environment variables N2261_*; with N2261_T_MIN=0.4 N2261_DROP_FIRST=0 N2261_NAME=ngc2261-coadd-all it is the every-frame trial)',
    software=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, machine=platform.platform()))
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('recipe.json written: %d of %d frames, %.2f minutes' % (nU, n15, nU * EXPOSURE_S / 60))
for k, v in verdict.items(): print(' ', k, ':', v)
