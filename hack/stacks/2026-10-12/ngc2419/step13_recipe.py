"""Step 13: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat and its check, the sky constants, the registration, the weights, the air dispersion, the
plate solution (scale, which way north is, where the cluster's centre and the two bright stars are in the picture), the
stretch, the crop, the finish, the half-stack proofs, and the honest verdict.

Copies final/ngc2419.jpg to ngc2419/ngc2419.jpg (checked free of EXIF / XMP / comment segments first)."""
import json, os, platform, datetime, shutil, hashlib
import numpy as np, cv2, rawpy, tifffile
from common import *

FINAL = os.environ.get('N2419_FINAL', os.path.join(NIGHT, 'final'))
s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json'); s11 = jload('step11_measure.json')
fin = json.load(open(os.path.join(FINAL, 'ngc2419.json'))); crop = json.load(open(W('ngc2419-crop.json'))); finf = json.load(open(os.path.join(OUT, 'ngc2419-field.json')))
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


mk = jpeg_markers(os.path.join(FINAL, 'ngc2419.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, 'ngc2419.jpg'), os.path.join(OUT, 'ngc2419.jpg'))
pic = cv2.imread(os.path.join(FINAL, 'ngc2419.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
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
order = sorted(s4); TR = s5['transparency']
hf = [s4[s]['hfd_arcsec'] for s in order]; sm = [s4[s]['smear'] for s in order]; tp = [TR[s] for s in order]; box = [s4[s]['box_star_size_arcsec'] for s in order]
skyG = [0.5 * (s8['constants'][s][1] + s8['constants'][s][2]) for s in sorted(used)]
R11 = s11['run']; hz = s11['haze']; pt = s11['points']; col = s11['colour']; gl = s11['glare']; d7 = s7['dust']; loc = hz['against_the_local_sky']
cloud_drops = [s for s in rej if 'cloud' in rej[s]['why']]
run = dict(star_brightness=dict(what='the summed light of the same %d stars in each frame over the clear level (the median of the upper half of the frames, step 5)' % s4[order[0]]['stars_matched'], per_frame=dict(zip(order, [round(v, 3) for v in tp])), min=round(min(tp), 3), max=round(max(tp), 3),
                                clear_frames=R11['clear_frames'], clear_from_to=R11['clear_from_to'], clear_range=R11['clear_frames_brightness_range'], before_the_clear_stretch=R11['frames_before_the_clear_stretch'], after_it=R11['frames_after_it']),
           star_size_arcsec=dict(measure='half-flux diameter, median of the compact stars of each frame (step 4)', median=round(float(np.median(hf)), 2), min=round(min(hf), 2), max=round(max(hf), 2), of_the_used_frames=[round(min(used[s]['hfd_arcsec'] for s in used), 2), round(max(used[s]['hfd_arcsec'] for s in used), 2)], the_boxs_own_measure_arcsec=[min(box), max(box)]),
           smear=dict(what='common-direction ellipticity of the stars (step 4)', median=round(float(np.median(sm)), 3), max=round(max(sm), 3), frames_over_the_limit_0_20=[s for s in order if s4[s]['smear'] > 0.20]),
           raw_green_sky_dn=R11['raw_green_sky_dn'],
           sky_green_dn=dict(what='the sky constant of each used frame, mean of G1 and G2, after the flat and the transparency scale', min=round(min(skyG), 1), max=round(max(skyG), 1), median=round(float(np.median(skyG)), 1)),
           said='THE SKY WAS NOT CLEAR FOR THE WHOLE RUN, whatever the box\'s own measure read (it gave 40 stars a frame and a transparency that it reckons another way). Star by star (41 stars in every frame): the first five frames, 11:33:28 to 11:36:18 UTC, were taken through cloud (stars at %s of their clear brightness, the RAW green sky at %.0f DN against %.0f when clear: dimmer stars under a brighter sky is cloud); the sixth was at %.2f; then %d frames in a row, %s to %s, held within %.1f%% of each other (%.3f to %.3f): clear; then thin cloud crossed in patches until the end (%s), the last two frames at %.2f and %.2f. %d frames were dropped for cloud (under 80%% of clear); %d thin ones (80 to 90%%) are used, scaled up and weighted down. Star size was steady: %.2f to %.2f arcsec half-flux diameter, median %.2f (the box said %.1f to %.1f). One frame was trailed (common ellipticity %.2f, limit 0.20), in the cloud; none of the clear ones (largest %.2f).' % (
               ', '.join('%.0f%%' % (100 * v) for v in tp[:5]), R11['raw_green_sky_dn']['frames_under_half_brightness_median'] or float('nan'), R11['raw_green_sky_dn']['clear_frames_median'], tp[5], R11['clear_frames'], R11['clear_from_to'][0][9:], R11['clear_from_to'][1][9:],
               100 * (R11['clear_frames_brightness_range'][1] - R11['clear_frames_brightness_range'][0]), *R11['clear_frames_brightness_range'], ', '.join('%.0f%%' % (100 * v) for v in R11['frames_after_it']), tp[-2], tp[-1], len(cloud_drops),
               len([s for s in used if TR[s] < 0.95]), min(hf), max(hf), float(np.median(hf)), min(box), max(box), max(sm), max(used[s]['smear'] for s in used)))
skyc = float(np.median(skyG)); hs = hz['stack']; ho = hz['odd']; he = hz['even']; both = hz['in_the_stack_and_in_both_halves']
reps = [p for p in pt['the_points'] if p['repeats']]
verdict = dict(
    is_it_the_thing='yes: the reference frame (before stacking) and the stack were plate-solved (astrometry.net, Tycho-2 index files). NGC 2419\'s catalogue place (RA %.4f, Dec %+.4f) falls %.1f arcmin from the frame centre and a round haze sits on it: the haze\'s own flux centre is %.1f arcsec from the catalogue place. The two bright stars the catalogue describes stand in a line to its west: star A at RA %.5f Dec %+.5f, %.2f arcmin from the cluster, and star B at RA %.5f Dec %+.5f, %.2f arcmin from it, at position angle %.0f degrees from A (west); positions by this solution, names not read from any star catalogue.' % (
        TARGET['ra_deg'], TARGET['dec_deg'], s6['offset_from_frame_centre_arcmin'], s11['centre']['flux_centre_from_catalogue_arcsec']['total'], two[0]['ra_deg'], two[0]['dec_deg'], two[0]['from_the_catalogue_place_arcsec'] / 60, two[1]['ra_deg'], two[1]['dec_deg'], two[1]['from_the_catalogue_place_arcsec'] / 60, pair['second_from_first_position_angle_deg']),
    seen=dict(
        haze='seen plainly, round, brighter to the middle: %.1f DN of green a pixel at the centre (the sky under it was %.0f DN, so the centre is %.0f%% above the sky), falling to half at %.0f arcsec from the centre. Odd frames alone %.1f DN, even alone %.1f DN.' % (hs['central_ring_median_dn'], skyc, 100 * hs['central_ring_median_dn'] / skyc, hs['falls_to_half_at_radius_arcsec'], ho['central_ring_median_dn'], he['central_ring_median_dn']),
        width='%.1f arcmin across above the sky, in the stack and in the odd and the even half stacks each alone (every %.0f arcsec ring out to %.0f arcsec radius stands above 3 x the scatter of the same ring on %d blank-sky places; odd %.0f arcsec, even %.0f arcsec). That is against the stack\'s zero, and round the cluster the rings from 100 to 180 arcsec read %.2f DN below it; against those rings the haze is %.1f arcmin across (odd %.1f, even %.1f). Half of its light lies within %.0f arcsec of the centre. The catalogue gives 4 to 6 arcmin: the outer part is under %.1f DN, below what %.2f minutes through a %.0f DN sky can show.' % (
            both['width_arcmin'], hz['profile'][1]['radius_arcsec'] - hz['profile'][0]['radius_arcsec'], both['radius_arcsec'], hz['blank_sky_places'], ho['above_the_sky_out_to_radius_arcsec'], he['above_the_sky_out_to_radius_arcsec'], -loc['stack']['local_sky_dn'], loc['stack']['width_arcmin'], loc['odd']['width_arcmin'], loc['even']['width_arcmin'],
            hz['half_light_radius_arcsec'], 3 * hs['ring_scatter_dn_at_30_60_120_arcsec'][1], len(used) * EXPOSURE_S / 60, skyc),
        resolved_stars='THE HAZE IS GRAINY, AND THE GRAIN IS REAL; SINGLE STARS ARE NOT CLAIMED. Within %.0f arcsec of the centre the band-passed green (things 3 to 12 arcsec across; a star here is 5 arcsec) has, once the smooth round haze\'s own share of that band (%.1f DN at most) is taken off, %d local maxima above %.0f x its noise, and %d of them are there in the odd and in the even half stacks alone (a local maximum within 1.5 px, above 3 x a half\'s noise). The same count on %d blank-sky discs of the same size gives %.1f +- %.1f (the field\'s own faint stars; at most %d): an excess of %.0f, so about %d of the points belong to the cluster. What each one is cannot be said from these frames: the cluster\'s brightest stars are about 17th magnitude and thousands crowd into a haze 2 arcmin across seen at 5 arcsec, so a point is a bright giant, or two or three of them falling together, or one of the two or so field stars expected there. The picture shows them as grain. They are listed with their places in measured.cluster_and_proofs.points.' % (
            float(pt['where'].split()[1]), pt['smooth_haze_taken_out_first']['largest_dn'], pt['candidates'], pt['candidate_threshold_sigma'], pt['repeating_in_both_halves'], pt['blank_sky']['places'], pt['blank_sky']['repeating_points_per_disc_mean'], pt['blank_sky']['scatter'], pt['blank_sky']['most'], pt['excess_over_the_field'], round(pt['excess_over_the_field'])),
        the_two_bright_stars='both in the picture, at pixels %s (A) and %s (B). BOTH CLIP: their cores touched the sensor\'s ceiling in every frame (about 180 px of each green plane a frame over the two), so their centres are flat white discs with no true colour or brightness, shown white; nothing was repaired. Their measured fluxes (B %.2f magnitudes fainter than A) are lower limits for the same reason. Star B has a fainter orange star about 25 arcsec beside it.' % (two[0]['pixel_in_the_picture'], two[1]['pixel_in_the_picture'], pair['magnitude_difference'])),
    colour='measured, and it is the colour of the field\'s stars: within %s of the centre the haze is red : green : blue %.2f : 1 : %.2f in the camera\'s daylight white balance (white = 1 : 1 : 1), with an error of %.2f and %.2f from the sky zero alone; odd frames %.2f and %.2f, even %.2f and %.2f. The field\'s %d unclipped stars have medians %.2f and %.2f. So: a faintly warm white, a little short of blue (%.1f sigma from white), red not told from white; no more can be said. The picture shows that with no saturation added, and shows no colour at all below 14 DN.' % (
        col['what'].split('within ')[1].split(' of')[0], col['haze']['stack']['red_over_green'], col['haze']['stack']['blue_over_green'], col['error_from_the_sky_zero']['red_over_green'], col['error_from_the_sky_zero']['blue_over_green'], col['haze']['odd']['red_over_green'], col['haze']['odd']['blue_over_green'], col['haze']['even']['red_over_green'], col['haze']['even']['blue_over_green'],
        col['field_stars']['stars'], col['field_stars']['red_over_green_median'], col['field_stars']['blue_over_green_median'], (1 - col['haze']['stack']['blue_over_green']) / col['error_from_the_sky_zero']['blue_over_green']),
    sky=dict(how_it_was_set='one constant per colour per frame (the 3-sigma clipped mean over the sky region: the darker %.0f%% of the area all frames share, outside a %.0f arcmin circle on the cluster and 2 arcmin circles on the two bright stars); in the picture only, a plane per colour fitted to that same sky and taken off.' % (s8['faint_region']['percentile'], s6['mask_radius_arcmin']),
             glare_of_the_bright_stars='star A is %.1f arcmin from the cluster. Its spread light, measured on its far side where there is no cluster, is %s DN at the cluster\'s distance and 0.4 to 1.3 DN between 2.3 and 3.6 arcmin: under 5%% of the haze\'s centre, and of the order of its outermost measured ring. It was not modelled or subtracted. The sky region keeps 2 arcmin from both stars and takes only the darker part of the field.' % (gl['star_a_from_the_cluster_arcsec'] / 60, gl['at_the_clusters_distance_dn']),
             the_weak_point='the rings 100 to 180 arcsec from the cluster read %.2f DN below the stack\'s zero (%.1f%% of the sky) while star A\'s far side reads about 1 DN above it. The likeliest reason is the night\'s flat, which tonight\'s other stacks found about 1%% high in the middle of the sensor, where every target sits. It was not corrected: so the haze\'s width against the stack\'s zero (%.1f arcmin) is a lower limit and the width against the local rings (%.1f arcmin) is given beside it.' % (-loc['stack']['local_sky_dn'], -100 * loc['stack']['local_sky_dn'] / skyc, both['width_arcmin'], loc['stack']['width_arcmin'])),
    flaws=['short and partly through cloud: %d of %d frames, %.2f minutes; %d were lost to cloud at the start and the end of the run.' % (len(used), len(s1['frames']), len(used) * EXPOSURE_S / 60, len(cloud_drops)),
           'the two bright stars clip (see seen.the_two_bright_stars) and carry haloes of the telescope\'s own spread light about a minute of arc across; left as they are.',
           'the sky zero round the cluster is about %.1f DN low (sky.the_weak_point).' % -loc['stack']['local_sky_dn'],
           'dust: the night\'s flat left its own fitted shadows up to %.1f%% deep under this run\'s sky; %d shadows (%.1f%% of the sensor, the deepest %.1f%%) were measured on this run\'s own sky, each seen in the odd and in the even frames alone, and divided out; after that the worst of the flat\'s fitted shadows is %.1f%%. With 17 frames this test is close to its own noise (its limits were raised by 1.41 over tonight\'s M78 for that reason). Nothing within %.1f arcmin of the cluster or 1.9 arcmin of the two stars was judged or changed.' % (
               100 * d7['worst_left_by_the_nights_flat'], len(d7['divided_out']), 100 * d7['sensor_fraction_changed'], 100 * (1 - d7['deepest_factor']), 100 * d7['worst_left_after_own_correction'], 240 * 0.7772 / 60),
           'some of the fainter field stars carry a slight green-white tint: their colour is an average over 3 px of planes of which red and blue are the noisier (render.py); it is not a measured star colour.',
           'the dark sky is set near black and smoothed, by choice (less noise over faint detail): %.1f%% of the picture is exactly black, and the haze\'s outermost ring fades into it.' % fin.get('clipped_to_black_pct', float('nan')),
           'the two green planes disagree about the sky\'s slope by 1 to 2 DN across the field (planes fitted and taken off in the picture only).'],
    not_done='no deconvolution, nothing generative, nothing retouched, the clipped stars not repaired, never enlarged (one picture pixel per 2 x 2 colour cell of the sensor, %.3f arcsec).' % SC)
rec = dict(
    target='NGC 2419, a globular cluster in Lynx (the Intergalactic Wanderer), with the two bright field stars west of it', night='2026-10-12 (frames of 13 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    files=dict(stack=os.path.join(OUT, 'ngc2419-stack.tif'), picture=[os.path.join(FINAL, f) for f in ('ngc2419.png', 'ngc2419.jpg', 'ngc2419.json')], picture_copy=os.path.join(OUT, 'ngc2419.jpg'), full_field=[os.path.join(OUT, f) for f in ('ngc2419-field.png', 'ngc2419-field.jpg', 'ngc2419-field.json')], scripts=SCR, logs=W('logs')),
    equipment=dict(camera='Sony a6000 (ILCE-6000), RAW', telescope='Celestron 8SE optical tube at f/10', focal_length_mm_by_plate_solve=round(s9['focal_length_mm']), mount='EQ6-R, unguided, polar axis about 5 degrees off the pole, tracking on a pointing model (the field turns)'),
    exposure=dict(frames_found=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej), exposure_s=EXPOSURE_S, iso=ISO, total_s=len(used) * EXPOSURE_S, total_minutes=round(len(used) * EXPOSURE_S / 60, 2), effective_frames=s5['effective_frames'],
                  first=min(u for u in used), last=max(u for u in used), altitude_deg=[min(alts), max(alts)] if alts else None, field_turned_deg=round(max(rot) - min(rot), 3), also_in_the_window=s1['left_out'],
                  not_stacked='the two 2 s ISO 6400 centring pictures of 11:32 UTC before the run and the two pictures after it (listed in also_in_the_window): never stacked', all_raws_were_present='all %d frames of the run were on this Mac when the work started at 11:58 UTC (the run ended 11:53:14 UTC; the copy was complete, no waiting was needed)' % len(s1['frames']),
                  what_the_run_was_like=run),
    verdict=verdict,
    plate_solution=dict(solver='astrometry.net (solve-field, local Tycho-2 index files), on the stack\'s green', arcsec_per_px=SC, field_arcmin=s9['field_arcmin'], centre_ra_dec=s9['centre_ra_dec'], north=s9['north_in_words'],
                        north_angle_from_up_deg_clockwise=s9['north_angle_from_up_deg_clockwise'], east_angle_from_up_deg_clockwise=s9['east_angle_from_up_deg_clockwise'], mirrored=s9['mirrored'], sky_axes=s9['sky_axes'],
                        picture=dict(size_px=[ww, hh], size_arcmin=[round(ww * SC / 60, 1), round(hh * SC / 60, 1)], origin_in_the_stack_px=[gc['x'], gc['y']], ngc2419_catalogue_place_px=s9['catalogue_place_in_the_nebula_crop_px'], the_two_bright_stars_px=dict(A=two[0]['pixel_in_the_picture'], B=two[1]['pixel_in_the_picture']), north_unit_vector_xy=s9['sky_axes']['north'], east_unit_vector_xy=s9['sky_axes']['east']),
                        the_two_bright_stars=two, the_two_bright_stars_as_a_pair=pair, catalogue_places_in_the_stack=cat,
                        stack_origin_on_reference_grid=s9['crop_on_reference_grid'], corners_ra_dec=s9['corners_ra_dec'], brightest_sources=s9['brightest_sources_of_the_reference_frame'], wcs_header=s9['wcs_header'],
                        reference_frame_solve=dict(frame=s6['frame'], arcsec_per_px=s6['pixscale_arcsec'], north_angle_from_up_deg_clockwise=s6['north_angle_from_up_deg_clockwise'], target_from_frame_centre_arcmin=s6['offset_from_frame_centre_arcmin'], object_mask=dict(ngc2419_circle_arcmin=s6['mask_radius_arcmin'], others=s6['extra_masks'], fraction_of_frame=s6['object_mask_fraction_of_frame']))),
    steps=[
        dict(step='frames', detail='the 15 s ISO 3200 frames (by the RAW\'s own EXIF) with sidecar pointing within %.1f deg of NGC 2419, file-name times %s to %s UTC' % (POINTING_RADIUS_DEG, T0, T1)),
        dict(step='planes', detail='each RAW split into its four colour planes (R, G1, G2, B), black subtracted; no demosaic'),
        dict(step='hot pixels', detail='from the run itself (no darks): fixed map from the unregistered median of the frames, transient spikes per frame; replaced by the 3 x 3 median of the plane', numbers=s1['hot']),
        dict(step='stars and registration', detail='stars on the mean green plane; rotation + shift to the reference frame %s (scale held at 1); %d to %d stars matched per frame, weighted rms %.2f to %.2f sensor px' % (REF_STAMP, min(s3[k]['used'] for k in used), max(s3[k]['used'] for k in used), min(s3[k]['wrms_px'] for k in used), max(s3[k]['wrms_px'] for k in used)), reference=REF_STAMP),
        dict(step='selection', limits=s5['limits'], clear_level_over_run_median=s5['clear_level_over_run_median'], star_size_median_arcsec=s5['hfd_run_median_arcsec'], rejected=s5['rejected']),
        dict(step='flat', detail='the night\'s flat (from the NGC 891 run), checked against this run\'s own open sky outside the object mask; dust it left measured on this run\'s own sky and divided out', numbers=s7,
             flat_file=dict(path=os.path.join(FLAT_DIR, 'flat_planes.npz'), sha256_when_the_recipe_was_written=hashlib.sha256(open(os.path.join(FLAT_DIR, 'flat_planes.npz'), 'rb').read()).hexdigest(),
                            modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(FLAT_DIR, 'flat_planes.npz')), datetime.timezone.utc).isoformat(timespec='seconds'))),
        dict(step='stack', detail='per frame and plane: / flat, x 1/transparency, one Lanczos-4 resampling onto the reference frame\'s colour-cell grid (rotation + shift + the plane\'s place in the cell + the air dispersion offset), minus ONE constant (3-sigma clipped mean over the sky region, outside the object mask); combined per pixel by a 3-sigma clipped weighted mean', kappa=s8['kappa'], sky_region=s8['faint_region'], planes=s8['planes'], subsets=s8['subsets']),
        dict(step='air dispersion', numbers=s8['air_dispersion'], said='at %.0f to %.0f degrees up red sat (%+.2f, %+.2f) and blue (%+.2f, %+.2f) sensor px from green (red to blue %.2f arcsec); taken out in the one resampling; left in the stack: red (%+.3f, %+.3f), blue (%+.3f, %+.3f)' % (min(alts), max(alts),
            *s8['air_dispersion']['measured_in_the_frames']['red_minus_green_sensor_px'], *s8['air_dispersion']['measured_in_the_frames']['blue_minus_green_sensor_px'],
            0.388 * float(np.hypot(*(np.array(s8['air_dispersion']['measured_in_the_frames']['red_minus_green_sensor_px']) - np.array(s8['air_dispersion']['measured_in_the_frames']['blue_minus_green_sensor_px'])))),
            *s8['air_dispersion']['left_in_the_stack']['red_minus_green_sensor_px'], *s8['air_dispersion']['left_in_the_stack']['blue_minus_green_sensor_px'])),
        dict(step='linear TIF', numbers=s10['tif']),
        dict(step='picture: sky plane (in the picture only, not in the TIF)', numbers=s10['sky_plane_in_the_picture_only']),
        dict(step='picture: colour and stretch (render.py)', params=s10['render_params'], info=s10['render_info'], white_balance=s10['white_balance_daylight'], rgb_cam=s10['rgb_cam']),
        dict(step='picture: crop (crop.py)', numbers=crop, said='%d x %d px = %.1f x %.1f arcmin, pixels untouched, never enlarged; the cluster and both bright stars in it' % (gc['w'], gc['h'], gc['w'] * SC / 60, gc['h'] * SC / 60)),
        dict(step='is it real? (step 11)', detail='half stacks of the odd and the even frames; the same apertures on blank sky; see verdict and measured.cluster_and_proofs', looks=[W('halves_look.png'), W('points_look.png')]),
        dict(step='picture: finish (finish16.py = the finish-pictures tool reading 16 bits)', numbers=fin, full_field=finf, skycheck=dict(picture=skycheck(os.path.join(FINAL, 'ngc2419.png')), full_field=skycheck(os.path.join(OUT, 'ngc2419-field.png'))), jpeg_markers=mk),
    ],
    measured=dict(noise=s10['noise_faint_region'], star_size=star, cluster_and_proofs=s11),
    frames=frames,
    next_time='three or four times the exposure on a night without cloud, for the outer haze the catalogue gives (4 to 6 arcmin); a twilight flat at dawn (the middle of the sensor is where every target sits and where tonight\'s flat is weakest); dither more than 2 arcmin between frames so that dust and sky separate; shorter frames as well if the two bright stars are wanted unclipped.',
    reproduce='hack/stacks/2026-10-12/ngc2419/run_all.sh (hooks are environment variables N2419_*; none set reproduces this run)',
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
print('picture %d x %d px; NGC 2419 catalogue place at %s; star A at %s, star B at %s; %s' % (ww, hh, s9['catalogue_place_in_the_nebula_crop_px'], two[0]['pixel_in_the_picture'], two[1]['pixel_in_the_picture'], s9['north_in_words']))
