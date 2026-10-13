"""Step 13: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat and its check, the sky constants and how far the sky can be trusted, the registration, the
weights, the air dispersion, the plate solution (scale, which way north is, where the nebula's two bright stars are in
the picture), the stretch, the crop, the finish, the half-stack proofs, and the honest verdict.

Copies final/m78.jpg to m78/m78.jpg (checked free of EXIF / XMP / comment segments first)."""
import json, os, platform, datetime, shutil, hashlib
import numpy as np, cv2, rawpy, tifffile
from common import *

FINAL = os.environ.get('M78_FINAL', os.path.join(NIGHT, 'final'))
s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json'); s11 = jload('step11_measure.json')
fin = json.load(open(os.path.join(FINAL, 'm78.json'))); crop = json.load(open(W('m78-crop.json'))); finf = json.load(open(os.path.join(OUT, 'm78-field.json')))
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


mk = jpeg_markers(os.path.join(FINAL, 'm78.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, 'm78.jpg'), os.path.join(OUT, 'm78.jpg'))
pic = cv2.imread(os.path.join(FINAL, 'm78.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
star = s10['star_size']; gc = s9['nebula_crop']; cat = s9['catalogue']; two = s9['the_two_stars']; pair = s9['the_two_stars_as_a_pair']
frames = []
for f in s1['frames']:
    s = f['stamp']; q = s4.get(s, {}); t = s3.get(s, {})
    frames.append(dict(file=f['name'], sha256=f.get('arw_sha256'), shutter_pressed=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], since_slew_s=f['since_slew_s'], alt_deg=f.get('alt_deg'), az_deg=f.get('az_deg'),
                       used=s in used, why_not=rej[s]['why'] if s in rej else None, transparency=q.get('transparency'), star_peak_relative=q.get('peak_rel'), star_size_arcsec=q.get('hfd_arcsec'), smear=q.get('smear'), elongation=q.get('elong_median'),
                       shift_at_centre_sensor_px=t.get('shift_at_centre_px'), rotation_deg=t.get('rotation_deg'), registration_wrms_sensor_px=t.get('wrms_px'), stars_matched=t.get('used'),
                       weight=used[s]['weight'] if s in used else None, scale=used[s]['scale'] if s in used else None, sky_constants_dn=dict(zip(PLANE_NAMES, [round(v, 3) for v in s8['constants'][s]])) if s in s8['constants'] else None,
                       pixel_sigma_dn=f['pix_sigma'], raw_black=f['black'], pixels_at_the_ceiling=f['ceiling_pixels']))
alts = [f.get('alt_deg') for f in s1['frames'] if f.get('alt_deg') is not None]
rot = [s3[s]['rotation_deg'] for s in used]
order = sorted(s4)
hf = [s4[s]['hfd_arcsec'] for s in order]; sm = [s4[s]['smear'] for s in order]; tp = [s4[s]['transparency'] for s in order]; pkr = [s4[s]['peak_rel'] for s in order]; box = [s4[s]['box_star_size_arcsec'] for s in order]
third = len(order) // 3
skyG = [0.5 * (s8['constants'][s][1] + s8['constants'][s][2]) for s in sorted(used)]
run = dict(star_size_arcsec=dict(measure='half-flux diameter, median of the compact stars of each frame (step 4; 11 stars: the field lies in a dark cloud and has few)', median=round(float(np.median(hf)), 2), min=round(min(hf), 2), max=round(max(hf), 2),
                                 first_third_median=round(float(np.median(hf[:third])), 2), middle_third_median=round(float(np.median(hf[third:2 * third])), 2), last_third_median=round(float(np.median(hf[2 * third:])), 2),
                                 last_four_frames=[round(v, 2) for v in hf[-4:]], the_boxs_own_measure_arcsec=[min(box), max(box)]),
           smear=dict(what='common-direction ellipticity of the stars (step 4)', median=round(float(np.median(sm)), 3), max=round(max(sm), 3), frames_over_the_limit_0_20=[s for s in order if s4[s]['smear'] > 0.20]),
           transparency=dict(what='star flux against each star\'s median over the run', first_third_median=round(float(np.median(tp[:third])), 3), middle_third_median=round(float(np.median(tp[third:2 * third])), 3), last_third_median=round(float(np.median(tp[2 * third:])), 3),
                             min=round(min(tp), 3), max=round(max(tp), 3), last_four_frames=[round(v, 3) for v in tp[-4:]], star_peak_relative_last_four_frames=[round(v, 2) for v in pkr[-4:]]),
           sky_green_dn=dict(what='the sky constant of each used frame, mean of G1 and G2, after the flat and the transparency scale', first=round(skyG[0], 1), last=round(skyG[-1], 1), min=round(min(skyG), 1), max=round(max(skyG), 1)),
           said='no frame was trailed (largest common-direction ellipticity %.2f, limit 0.20). Star size: half-flux diameter %.2f arcsec in the first third of the run, %.2f in the middle, %.2f in the last; best about %.1f at 10:40 to 10:47 UTC, then the stars grew in the last four frames, %s arcsec, while their flux fell to %s of the run\'s median and their peaks to %s. Until then transparency was steady within %.0f%% (%.3f to %.3f). Stars that widen and dim together over three minutes at the end of the run are what dew starting on the corrector plate does (thin cloud is the other reading; the next target\'s frames, two minutes later, measured 7.2 to 8.1 arcsec by the box). The last frame is dropped for size; the three before it are used, scaled and weighted.' % (
               max(sm), float(np.median(hf[:third])), float(np.median(hf[third:2 * third])), float(np.median(hf[2 * third:])), min(hf), ', '.join('%.2f' % v for v in hf[-4:]), ', '.join('%.3f' % v for v in tp[-4:]), ', '.join('%.2f' % v for v in pkr[-4:]),
               100 * (max(tp[:-4]) - min(tp[:-4])), min(tp[:-4]), max(tp[:-4])))
ex = s11['extent']; exb = ex['in_the_stack_and_in_both_halves']; ln = s11['lane']['numbers']; col = s11['colour']; blue = col['blue']; b0 = col['bands'][0]; oth = s11['others']; d7 = s7['dust']
dc = np.array([x['plane_px'] for x in d7['divided_out']]); dr = np.hypot(dc[:, 0] - s6['galaxy_ellipse']['centre_px'][0], dc[:, 1] - s6['galaxy_ellipse']['centre_px'][1]) if len(dc) else np.array([])
sky_g = s7['own_sky']['sky_level_dn_median']; skyc = float(np.median(skyG))
n64 = oth['NGC 2064']['as_a_small_patch']; n71 = oth['NGC 2071']
verdict = dict(
    is_it_the_thing='yes: the reference frame and the stack were plate-solved (astrometry.net, Tycho-2 index files) before and after stacking. M78\'s catalogue place falls %.1f arcmin from the frame centre, inside the glow, between and just beside the two stars the catalogue describes: they are measured at RA %.5f Dec %+.5f and RA %.5f Dec %+.5f, %.1f arcsec apart, the second %.2f magnitudes fainter in green.' % (
        s6['offset_from_frame_centre_arcmin'], two[0]['ra_deg'], two[0]['dec_deg'], two[1]['ra_deg'], two[1]['dec_deg'], pair['separation_arcsec'], pair['magnitude_difference']),
    seen=dict(
        glow_round_the_two_stars='seen, strongly: within 1.5 arcmin of the pair\'s midpoint the mean green is %.1f DN a pixel (stars masked), %.0f times the scatter of the same circle on %d places of blank sky; the odd and the even half stacks give %.2f and %.2f. The central level is %.0f DN; it falls to half at %.1f arcmin radius.' % (
            s11['glow']['stack']['mean_dn']['G'], s11['glow']['stack']['times_the_blank_sky_scatter']['G'], s11['glow']['blank_sky_places'], s11['glow']['odd']['mean_dn']['G'], s11['glow']['even']['mean_dn']['G'], s11['central_level_green_dn'], s11['half_level_radius_arcmin']),
        dark_lane='seen, and real: on a strip from the two stars towards the north-west (%.0f degrees east of north) the green falls from %.0f DN in the body to %.1f at %.1f arcmin, then rises to %.1f at %.1f arcmin (the far bank of the lane: the arc of NGC 2067) and fades into the sky. The far bank stands %.1f DN above the lane: %.1f times the scatter of the same pair of patches on blank sky; odd frames alone %.1f DN (%.1f sigma), even alone %.1f DN (%.1f sigma), the minimum at the same place within 20 px. The body\'s edge at the lane is sharp: from 39 to 3 DN in 90 arcsec along the strip.' % (
            s11['lane']['heading_deg_east_of_north'], ln['stack']['body_peak_dn'], ln['stack']['lane_minimum_dn'], ln['stack']['lane_at_arcmin'], ln['stack']['far_bank_peak_dn'], ln['stack']['far_bank_at_arcmin'], ln['stack']['far_bank_above_the_lane_dn'], ln['stack']['far_bank_above_the_lane_sigma'],
            ln['odd']['far_bank_above_the_lane_dn'], ln['odd']['far_bank_above_the_lane_sigma'], ln['even']['far_bank_above_the_lane_dn'], ln['even']['far_bank_above_the_lane_sigma']),
        extent='smaller than the catalogue\'s 8 x 6 arcmin: the glow that stands above the blank sky by 4 times its scatter (green smoothed 8 px) in the stack and in both half stacks alone covers %.1f square arcmin, %.1f arcmin east-west by %.1f north-south (equivalent diameter %.1f); it reaches %.1f arcmin south of the catalogue place but only %.1f north, where the lane cuts it. In rings it is above the sky out to %.1f arcmin radius. Beyond that nothing of M78 is measured. Two things make this an underestimate: %.1f minutes of exposure through a %.0f DN sky, and a sky zero that is probably about 1.5 DN too high under the nebula (see sky).' % (
            exb['area_arcmin2'], exb['east_west_arcmin'], exb['north_south_arcmin'], exb['equivalent_diameter_arcmin'], exb['reaches_south_arcmin'], exb['reaches_north_arcmin'], s11['above_twice_the_sky_scatter_out_to_arcmin'], len(used) * EXPOSURE_S / 60, skyc),
        ngc_2067='the arc beyond the lane: seen as the lane\'s far bank (above), %.1f DN at its brightest, proven in both halves. As a round patch at its catalogue place it is not there (%.1f sigma).' % (ln['stack']['far_bank_peak_dn'], oth['NGC 2067']['as_a_small_patch']['stack']['sigma'] if oth['NGC 2067']['as_a_small_patch'] and oth['NGC 2067']['as_a_small_patch'].get('stack') else float('nan')),
        ngc_2064='seen, small and faint, at the right of the picture (pixel %s): within 35 arcsec of its catalogue place the green stands %.1f DN above the ring around it, %.1f times the scatter of the same on blank sky; odd %.1f sigma, even %.1f sigma.' % (
            cat['NGC 2064']['pixel_in_the_picture'], n64['stack']['contrast_dn'], n64['stack']['sigma'], n64['odd']['sigma'], n64['even']['sigma']) if n64 and n64.get('stack') else 'not measured',
        ngc_2071='clearly there, but NOT in the finished picture: %.1f arcmin from M78, %d px from the stack\'s left edge, a glow of %.1f DN mean green within 1.5 arcmin of its catalogue place (%.1f times the blank-sky scatter; odd %.1f, even %.1f) round a 10th magnitude star. A cut holding both would be 1,750 px wide with M78 a quarter of it and NGC 2071 against the edge, its glow running off the frame. It is in the full field, m78/m78-field.png, at pixel %s.' % (
            cat['NGC 2071']['from_m78_arcmin'], round(cat['NGC 2071']['from_the_nearest_edge_px']), n71['stack']['mean_dn']['G'], n71['stack']['times_the_blank_sky_scatter']['G'], n71['odd']['times_the_blank_sky_scatter']['G'], n71['even']['times_the_blank_sky_scatter']['G'], cat['NGC 2071']['pixel']),
        structure='the fine structure of the body repeats between the half stacks: band-passed green of the odd and the even frames correlates at r = %.2f (detail of 5 to 22 arcsec) and %.2f (11 to 44 arcsec) within 3.9 arcmin of M78, against %.2f +- %.2f and %.2f +- %.2f on %d blank-sky places (%.0f and %.0f sigma).' % (
            s11['structure']['sigma_3_px']['halves_correlation_in_nebula'], s11['structure']['sigma_6_px']['halves_correlation_in_nebula'], s11['structure']['sigma_3_px']['blank_sky_correlation_mean'], s11['structure']['sigma_3_px']['blank_sky_correlation_std'],
            s11['structure']['sigma_6_px']['blank_sky_correlation_mean'], s11['structure']['sigma_6_px']['blank_sky_correlation_std'], s11['structure']['sigma_3_px']['blank_sky_places'], s11['structure']['sigma_3_px']['significance_sigma'], s11['structure']['sigma_6_px']['significance_sigma'])),
    colour='IS THE BLUE MEASURED? Relative to its stars, yes; as blue in itself, no. In the camera\'s daylight white balance (white = 1 : 1 : 1) the bright body of the nebula (smoothed green above 20 DN, %d px) is red : green : blue %.2f : 1 : %.2f, the same in the odd and the even half stacks (blue : green %.3f and %.3f); a sky-zero error of one blank-sky scatter moves blue : green by %.3f. The two stars that light it measure blue : green %.2f and %.2f and the field\'s other stars %.2f (median of %d, all reddened by the cloud): the nebula is bluer than the bluer of its two stars by %.1f sigma, which is what scattering by dust does. But against white it is %+.1f sigma: neutral, not blue. So the picture shows the body a faint cool white beside yellow and orange stars, with no saturation added (finish --sat 1.0), and shows no colour at all below 14 DN (fading in to 24), where red : green drifts up to 1.2 to 1.5 with an error of 0.17 to 0.32 from the sky zero alone. The slight pink in the fainter part of the body is that drift and is not claimed.' % (
        b0['pixels'], b0['stack']['r_over_g'], b0['stack']['b_over_g'], b0['odd']['b_over_g'], b0['even']['b_over_g'], b0['b_over_g_error_from_the_sky_zero'], blue['lighting_stars_b_over_g'][0], blue['lighting_stars_b_over_g'][1], blue['field_stars_b_over_g_median'], col['field_stars']['stars'], blue['bluer_than_its_stars_by_sigma'], blue['bluer_than_white_by_sigma']),
    sky=dict(
        how_it_was_set=s11['sky']['how_it_was_set'],
        how_much_could_be_trusted=s11['sky']['trusted'] + ' The sky under the frames was %.0f DN in green (R %.0f, B %.0f before the flat): the nebula\'s centre is a quarter of the sky, its measured edge under 2%% of it.' % (skyc, sky_g['R'], sky_g['B']),
        the_weak_point='the dark lane reads %.1f DN BELOW the stack\'s zero and %.1f below the mean of the blank sky (%.1f%% of the sky). The likeliest reason is the night\'s flat: tonight\'s M77 and M1 stacks both found it about 1.5%% high in the middle of the sensor (NGC 891 hid the sky there when it was made), the M1 recipe has its own sky 0.8 to 1.5 DN low 3.5 to 6 arcmin from its nebula at the sensor centre half an hour earlier, and M78 sits %.1f arcmin from the centre. If so, everything within a few arcmin of M78 is about 1.5 to 2 DN too low in green: nothing in the bright body (under 6%%), but the faint edge is trimmed and the nebula is somewhat larger than measured here. It cannot be measured under the nebula from these frames (no sky is seen there), so it was NOT corrected. The other reading, that the lane truly hides a little background light, cannot be ruled out.' % (
            -ln['stack']['lane_minimum_dn'], ln['stack']['lane_below_the_blank_skys_mean_dn'], 100 * ln['stack']['lane_below_the_blank_skys_mean_dn'] / skyc, s6['offset_from_frame_centre_arcmin'])),
    flaws=['the sky zero under the nebula (sky.the_weak_point): the faint edge is probably trimmed by 1.5 to 2 DN.',
           'a short dark streak at the nebula\'s southern edge, near pixel (690, 780) of the finished picture, running from upper right to lower left: it lies along the path the field wandered on the sensor, so it is a dust shadow that the flat did not carry, smeared by the drift, inside the %.1f arcmin where no dust can be judged from these frames (the nebula itself). It was left: not painted out, and it cannot be cropped.' % (330 * 0.7772 / 60),
           'dust: the night\'s flat left its own fitted shadows up to %.1f%% deep under this run\'s sky; %d shadows (%.1f%% of the sensor, the deepest %.1f%%) were measured on this run\'s own sky, each seen in the odd and in the even frames alone, and divided out; after that the worst of the flat\'s fitted shadows is %.1f%%. %d of them lie between 4.3 and 7 arcmin from M78, where the arc and the dark cloud are: a real dark patch of sky smaller than 2 arcmin there would have been taken for dust and filled in (the frames wandered only %.0f x %.0f arcsec, so sky and sensor are not well separated). The arc and the lane themselves are brighter or larger than what that test touches.' % (
               100 * d7['worst_left_by_the_nights_flat'], len(d7['divided_out']), 100 * d7['sensor_fraction_changed'], 100 * (1 - d7['deepest_factor']), 100 * d7['worst_left_after_own_correction'], int((dr < 7 * 60 / 0.7772).sum()), *[0.388 * float(np.ptp([s3[k]['shift_at_centre_px'][i] for k in used])) for i in (0, 1)]),
           'the stars carry haloes: the two lighting stars are 370,000 and 280,000 DN each; some of the light within 20 to 40 arcsec of them is the telescope\'s own spread of starlight, not nebula. It was not modelled or removed.',
           'the brighter stars keep a thin coloured rim where their own colour meets the nebula\'s (render.py, star discs).',
           '%.1f minutes of exposure: the dark sky is set near black and smoothed, by choice (less noise over faint detail); %.1f%% of the picture is exactly black, and the nebula\'s faintest edge, the arc and NGC 2064 are smoothed with the sky.' % (len(used) * EXPOSURE_S / 60, fin.get('clipped_to_black_pct', 0)),
           'the red plane was flat-fielded with the green profile (it left the smaller remainder; the night\'s red flat is the weak one, see its README), and the two green planes disagree about the sky\'s slope down the short side by about 2 DN (planes fitted and taken off in the picture only).'],
    not_done='no deconvolution, nothing generative, nothing retouched, never enlarged (one picture pixel per 2 x 2 colour cell of the sensor).')
rec = dict(
    target='Messier 78 (NGC 2068), a reflection nebula in Orion, with NGC 2067 and NGC 2064; NGC 2071 in the full field', night='2026-10-12 (frames of 13 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    files=dict(stack=os.path.join(OUT, 'm78-stack.tif'), picture=[os.path.join(FINAL, f) for f in ('m78.png', 'm78.jpg', 'm78.json')], picture_copy=os.path.join(OUT, 'm78.jpg'), full_field=[os.path.join(OUT, f) for f in ('m78-field.png', 'm78-field.jpg', 'm78-field.json')], scripts=SCR, logs=W('logs')),
    equipment=dict(camera='Sony a6000 (ILCE-6000), RAW', telescope='Celestron 8SE optical tube at f/10', focal_length_mm_by_plate_solve=round(s9['focal_length_mm']), mount='EQ6-R, unguided, polar axis about 5 degrees off the pole, tracking on a pointing model (the field turns)'),
    exposure=dict(frames_found=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej), exposure_s=EXPOSURE_S, iso=ISO, total_s=len(used) * EXPOSURE_S, total_minutes=round(len(used) * EXPOSURE_S / 60, 2), effective_frames=s5['effective_frames'],
                  first=min(u for u in used), last=max(u for u in used), altitude_deg=[min(alts), max(alts)] if alts else None, field_turned_deg=round(max(rot) - min(rot), 3), also_in_the_window=s1['left_out'],
                  not_stacked='the two 2 s ISO 6400 centring pictures of 10:24 and 10:25 UTC (listed in also_in_the_window): never stacked', all_raws_were_present='all %d frames of the run were on this Mac when the work started (the run ended 10:50:15 UTC; the copy was complete)' % len(s1['frames']),
                  what_the_run_was_like=run),
    verdict=verdict,
    plate_solution=dict(solver='astrometry.net (solve-field, local Tycho-2 index files), on the stack\'s green', arcsec_per_px=SC, field_arcmin=s9['field_arcmin'], centre_ra_dec=s9['centre_ra_dec'], north=s9['north_in_words'],
                        north_angle_from_up_deg_clockwise=s9['north_angle_from_up_deg_clockwise'], east_angle_from_up_deg_clockwise=s9['east_angle_from_up_deg_clockwise'], mirrored=s9['mirrored'], sky_axes=s9['sky_axes'],
                        picture=dict(size_px=[ww, hh], size_arcmin=[round(ww * SC / 60, 1), round(hh * SC / 60, 1)], origin_in_the_stack_px=[gc['x'], gc['y']], m78_catalogue_place_px=s9['catalogue_place_in_the_nebula_crop_px'],
                                     the_two_bright_stars_px=[t['pixel_in_the_picture'] for t in two], ngc_2067_catalogue_place_px=cat['NGC 2067']['pixel_in_the_picture'], ngc_2064_catalogue_place_px=cat['NGC 2064']['pixel_in_the_picture'], ngc_2071='not in the picture; in the full field at %s' % cat['NGC 2071']['pixel']),
                        the_two_bright_stars=two, the_two_bright_stars_as_a_pair=pair, catalogue_places_in_the_stack=cat,
                        stack_origin_on_reference_grid=s9['crop_on_reference_grid'], corners_ra_dec=s9['corners_ra_dec'], brightest_sources=s9['brightest_sources_of_the_reference_frame'], wcs_header=s9['wcs_header'],
                        reference_frame_solve=dict(frame=s6['frame'], arcsec_per_px=s6['pixscale_arcsec'], north_angle_from_up_deg_clockwise=s6['north_angle_from_up_deg_clockwise'], target_from_frame_centre_arcmin=s6['offset_from_frame_centre_arcmin'], object_mask=dict(m78_circle_arcmin=s6['mask_radius_arcmin'], others=s6['extra_masks'], fraction_of_frame=s6['object_mask_fraction_of_frame']))),
    steps=[
        dict(step='frames', detail='the 15 s ISO 3200 frames (by the RAW\'s own EXIF) with sidecar pointing within %.1f deg of M78, file-name times %s to %s UTC' % (POINTING_RADIUS_DEG, T0, T1)),
        dict(step='planes', detail='each RAW split into its four colour planes (R, G1, G2, B), black subtracted; no demosaic'),
        dict(step='hot pixels', detail='from the run itself (no darks): fixed map from the unregistered median of the frames, transient spikes per frame; replaced by the 3 x 3 median of the plane', numbers=s1['hot']),
        dict(step='stars and registration', detail='stars on the mean green plane; rotation + shift to the reference frame %s (scale held at 1); 22 or 23 stars matched per frame (a dark-cloud field), weighted rms 0.33 to 0.59 sensor px' % REF_STAMP, reference=REF_STAMP),
        dict(step='selection', limits=s5['limits'], star_size_median_arcsec=s5['hfd_run_median_arcsec'], rejected=s5['rejected']),
        dict(step='flat', detail='the night\'s flat (from the NGC 891 run), checked against this run\'s own open sky outside the object mask; dust it left measured on this run\'s own sky and divided out', numbers=s7,
             flat_file=dict(path=os.path.join(FLAT_DIR, 'flat_planes.npz'), sha256_when_the_recipe_was_written=hashlib.sha256(open(os.path.join(FLAT_DIR, 'flat_planes.npz'), 'rb').read()).hexdigest(),
                            modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(FLAT_DIR, 'flat_planes.npz')), datetime.timezone.utc).isoformat(timespec='seconds'))),
        dict(step='stack', detail='per frame and plane: / flat, x 1/transparency, one Lanczos-4 resampling onto the reference frame\'s colour-cell grid (rotation + shift + the plane\'s place in the cell + the air dispersion offset), minus ONE constant (3-sigma clipped mean over the sky region, outside the object mask); combined per pixel by a 3-sigma clipped weighted mean', kappa=s8['kappa'], sky_region=s8['faint_region'], planes=s8['planes'], subsets=s8['subsets']),
        dict(step='air dispersion', numbers=s8['air_dispersion'], said='at 43 to 46 degrees up red sat (%+.2f, %+.2f) and blue (%+.2f, %+.2f) sensor px from green (red to blue %.2f arcsec); taken out in the one resampling; left in the stack: red (%+.3f, %+.3f), blue (%+.3f, %+.3f)' % (
            *s8['air_dispersion']['measured_in_the_frames']['red_minus_green_sensor_px'], *s8['air_dispersion']['measured_in_the_frames']['blue_minus_green_sensor_px'],
            0.388 * float(np.hypot(*(np.array(s8['air_dispersion']['measured_in_the_frames']['red_minus_green_sensor_px']) - np.array(s8['air_dispersion']['measured_in_the_frames']['blue_minus_green_sensor_px'])))),
            *s8['air_dispersion']['left_in_the_stack']['red_minus_green_sensor_px'], *s8['air_dispersion']['left_in_the_stack']['blue_minus_green_sensor_px'])),
        dict(step='linear TIF', numbers=s10['tif']),
        dict(step='picture: sky plane (in the picture only, not in the TIF)', numbers=s10['sky_plane_in_the_picture_only']),
        dict(step='picture: colour and stretch (render.py)', params=s10['render_params'], info=s10['render_info'], white_balance=s10['white_balance_daylight'], rgb_cam=s10['rgb_cam']),
        dict(step='picture: crop (crop.py)', numbers=crop, said='%d x %d px = %.1f x %.1f arcmin, pixels untouched, never enlarged; NGC 2071 left to the full field' % (gc['w'], gc['h'], gc['w'] * SC / 60, gc['h'] * SC / 60)),
        dict(step='is it real? (step 11)', detail='half stacks of the odd and the even frames; the same apertures on blank sky; see verdict and measured.nebula_and_proofs', looks=[W('halves_look.png')]),
        dict(step='picture: finish (finish16.py = the finish-pictures tool reading 16 bits)', numbers=fin, full_field=finf, skycheck=dict(picture=skycheck(os.path.join(FINAL, 'm78.png')), full_field=skycheck(os.path.join(OUT, 'm78-field.png'))), jpeg_markers=mk),
    ],
    measured=dict(noise=s10['noise_faint_region'], star_size=star, nebula_and_proofs=s11),
    frames=frames,
    next_time='a twilight flat at dawn (the middle of the sensor is where every target sits and where tonight\'s flat is blind); dither more than 2 arcmin between frames so that dust and sky separate; three times the exposure for the nebula\'s edge and NGC 2067; a dew shield or heater by 10:45 UTC.',
    reproduce='hack/stacks/2026-10-12/m78/run_all.sh (hooks are environment variables M78_*; none set reproduces this run)',
    software=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, machine=platform.platform()))
json.dump(rec, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
print('recipe.json written: %d frames found, %d used (%.2f min), %d dropped' % (len(s1['frames']), len(used), len(used) * EXPOSURE_S / 60, len(rej)))
def show(k, v, ind='  '):
    if isinstance(v, dict):
        print(ind + k + ':')
        for a, b in v.items(): show(a, b, ind + '    ')
    elif isinstance(v, list): print(ind + k + ':\n' + '\n'.join(ind + '    - ' + x for x in v))
    else: print(ind + k + ':', v)
for k, v in verdict.items(): show(k, v)
print('  the run:', run['said'])
print('picture %d x %d px; M78 catalogue place at %s; the two stars at %s and %s; %s' % (ww, hh, s9['catalogue_place_in_the_nebula_crop_px'], two[0]['pixel_in_the_picture'], two[1]['pixel_in_the_picture'], s9['north_in_words']))
