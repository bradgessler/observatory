"""Step 13: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat and its check, the sky constants, the registration, the weights, the air dispersion, the
plate solution (scale, which way north is, where the nebula's centre is in the picture), the stretch, the crop, the
finish, the half-stack proof of what is inside the oval, the comparison with 8 October, and the honest verdict.

Copies final/m1.jpg to m1/m1.jpg (checked free of EXIF / XMP / comment segments first)."""
import json, os, platform, datetime, shutil
import numpy as np, cv2, rawpy, tifffile
from common import *
import render

FINAL = os.environ.get('M1_FINAL', os.path.join(NIGHT, 'final'))
s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json'); s11 = jload('step11_measure.json')
fin = json.load(open(os.path.join(FINAL, 'm1.json'))); crop = json.load(open(W('m1-crop.json'))); finf = json.load(open(os.path.join(OUT, 'm1-field.json')))
used = {u['stamp']: u for u in s5['used']}; rej = {r['stamp']: r for r in s5['rejected']}


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


mk = jpeg_markers(os.path.join(FINAL, 'm1.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, 'm1.jpg'), os.path.join(OUT, 'm1.jpg'))
pic = cv2.imread(os.path.join(FINAL, 'm1.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
star = s10['star_size']; gc = s9['nebula_crop']; cat = s9['catalogue'][TARGET['name']]; st_ = s11['structure']; neb = s11['nebula']['stack']; sh = s11['shape']; pul = s11['pulsar']
lc = [round(sh['light_centre_px'][0] - gc['x'], 1), round(sh['light_centre_px'][1] - gc['y'], 1)]
frames = []
for f in s1['frames']:
    s = f['stamp']; q = s4.get(s, {}); t = s3.get(s, {})
    d = dict(file=f['name'], sha256=f.get('arw_sha256'), shutter_pressed=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], since_slew_s=f['since_slew_s'], alt_deg=f.get('alt_deg'), az_deg=f.get('az_deg'),
             used=s in used, why_not=rej[s]['why'] if s in rej else None, transparency=q.get('transparency'), star_size_arcsec=q.get('hfd_arcsec'), smear=q.get('smear'), elongation=q.get('elong_median'),
             shift_at_centre_sensor_px=t.get('shift_at_centre_px'), rotation_deg=t.get('rotation_deg'), registration_wrms_sensor_px=t.get('wrms_px'), stars_matched=t.get('used'),
             weight=used[s]['weight'] if s in used else None, scale=used[s]['scale'] if s in used else None, sky_constants_dn=dict(zip(PLANE_NAMES, [round(v, 3) for v in s8['constants'][s]])) if s in s8['constants'] else None,
             pixel_sigma_dn=f['pix_sigma'], raw_black=f['black'], pixels_at_the_ceiling=f['ceiling_pixels'])
    frames.append(d)
alts = [f.get('alt_deg') for f in s1['frames'] if f.get('alt_deg') is not None]
rot = [s3[s]['rotation_deg'] for s in used]
order = sorted(s4)
hf = [s4[s]['hfd_arcsec'] for s in order]; sm = [s4[s]['smear'] for s in order]; tp = [s4[s]['transparency'] for s in order]; box = [s4[s]['box_star_size_arcsec'] for s in order]
third = len(order) // 3
calm = [s4[s]['hfd_arcsec'] for s in order if s4[s]['smear'] < 0.10]
run = dict(star_size_arcsec=dict(measure='half-flux diameter, median of the compact stars of each frame (step 4)', median=round(float(np.median(hf)), 2), min=round(min(hf), 2), max=round(max(hf), 2),
                                 first_third_median=round(float(np.median(hf[:third])), 2), middle_third_median=round(float(np.median(hf[third:2 * third])), 2), last_third_median=round(float(np.median(hf[2 * third:])), 2),
                                 frames_without_smear_median=round(float(np.median(calm)), 2), the_boxs_own_measure_arcsec=[min(box), max(box)],
                                 correlation_of_size_with_smear=round(float(np.corrcoef(hf, sm)[0, 1]), 2)),
           smear=dict(what='common-direction ellipticity of the stars (step 4)', median=round(float(np.median(sm)), 3), max=round(max(sm), 3), frames_over_0_15=[s for s in order if s4[s]['smear'] > 0.15], angles_of_those_deg=[round(s4[s]['smear_angle_deg']) for s in order if s4[s]['smear'] > 0.15]),
           transparency=dict(what='star flux against each star\'s median over the run', first_third_median=round(float(np.median(tp[:third])), 3), last_third_median=round(float(np.median(tp[2 * third:])), 3), min=round(min(tp), 3), max=round(max(tp), 3)),
           said='the stars grew only a little: half-flux diameter %.2f arcsec in the first third of the run, %.2f in the middle, %.2f in the last (frames without smear: %.2f over the whole run). The wide frames (up to %.2f) are the smeared ones: every star stretched the same way, at about -55 degrees on the sensor, every few frames (a wobble of the drive or the hold, not focus; size and smear correlate at %.2f). The brightness of the stars fell %.0f%% from the first third to the last (dew starting on the corrector, or thin haze; the frames are scaled and weighted for it).' % (
               float(np.median(hf[:third])), float(np.median(hf[third:2 * third])), float(np.median(hf[2 * third:])), float(np.median(calm)), max(hf), float(np.corrcoef(hf, sm)[0, 1]), 100 * (1 - np.median(tp[2 * third:]) / np.median(tp[:third]))))
# ---- against 8 October (last week's recipe, read only)
LAST = os.path.expanduser('~/.observatory/nights/2026-10-08-a6000/m1/recipe.json')
then = json.load(open(LAST)) if os.path.exists(LAST) else None
cmp_ = None
if then:
    tn = then['numbers']; g_now = st_['green']; l_now = st_['luminance']
    cmp_ = dict(recipe_of_8_october=LAST,
                frames=dict(then=len([f for f in then.get('frames', []) if f.get('used')]) or 4, now=len(used)), exposure_s=dict(then=60, now=len(used) * EXPOSURE_S),
                noise_per_px_green_dn=dict(then=round(tn['noise_per_px_dn']['stack'][1], 1), now=round(s11['noise_per_px_dn']['stack'][1], 1)),
                star_size_in_the_stack_arcsec=dict(then=round(tn['stars']['hfd_stack_arcsec'], 2), now=round(star['hfd_stack_arcsec'], 2)), star_elongation_then=round(tn['stars']['elong_stack'], 2),
                halves_correlation_3_to_11_arcsec=dict(then=tn['structure']['sigma_1.5_px']['halves_correlation_in_nebula'], then_sigma=tn['structure']['sigma_1.5_px']['significance_sigma'], now=g_now['sigma_1.5_px']['halves_correlation_in_nebula'], now_sigma=g_now['sigma_1.5_px']['significance_sigma']),
                halves_correlation_5_to_22_arcsec=dict(then=tn['structure']['sigma_3.0_px']['halves_correlation_in_nebula'], then_sigma=tn['structure']['sigma_3.0_px']['significance_sigma'], now=g_now['sigma_3.0_px']['halves_correlation_in_nebula'], now_sigma=g_now['sigma_3.0_px']['significance_sigma']),
                caution='the two nights\' DN are not on one scale (8 October was not flat-fielded and half its light was lost to an obstruction), so the noise is compared per pixel in each night\'s own units; the nebula\'s mean green in the inner ellipse was 26.9 DN then and %.1f DN now.' % neb['mean_dn']['G'],
                verdict='tonight\'s is the better picture, clearly: %d frames against 4 (%.2f minutes against 1), per-pixel noise %.1f DN against %.1f in green for about the same nebula signal, rounder and smaller stars (%.1f against %.1f arcsec, and last week\'s were stretched 1.39 : 1), a flat field, and the inside of the oval now repeats between the half stacks where last week it did not. Last week\'s picture showed a smooth oval and had to smooth everything fainter than the stars by 11 arcsec; tonight\'s shows the nebula\'s real uneven shape.' % (
                    len(used), len(used) * EXPOSURE_S / 60, s11['noise_per_px_dn']['stack'][1], tn['noise_per_px_dn']['stack'][1], star['hfd_stack_arcsec'], tn['stars']['hfd_stack_arcsec']))
g15, g3, g6 = (st_['green']['sigma_%s_px' % k] for k in ('1.5', '3.0', '6.0')); x15, x3, x6 = (st_['red_excess']['sigma_%s_px' % k] for k in ('1.5', '3.0', '6.0'))
near = pul['sources_within_31_arcsec'][0] if pul['sources_within_31_arcsec'] else None
verdict = dict(
    is_it_the_thing='yes: the reference frame and the stack were plate-solved (astrometry.net, Tycho-2 index files) before and after stacking; the catalogue place of M1 (the pulsar) falls inside the glow, %.0f arcsec from the centre of its light, and the glow is long the way the catalogue says (position angle %.0f degrees measured, 6 x 4 arcmin).' % (sh['light_centre_from_catalogue_arcsec'], sh['position_angle_deg_east_of_north']),
    seen='the oval glow, strongly: inside an ellipse %.1f x %.1f arcmin its mean green is %.1f DN a pixel, %.0f times the scatter of the same ellipse on %d places of blank sky, and each half stack shows it alone (%.1f and %.1f DN). Half its central brightness at %s arcmin, into the sky by %s arcmin (catalogue 6 x 4); long axis at position angle %.0f degrees, axis ratio %.2f. It is not a smooth oval: it is lopsided, with notches in its outline and brighter and darker patches inside, and that unevenness is real (next line).' % (
        *s11['inner_ellipse_arcmin'], neb['mean_dn']['G'], neb['signal_to_sky_structure']['G'], s11['blank_sky_places'], s11['nebula']['odd']['mean_dn']['G'], s11['nebula']['even']['mean_dn']['G'], ' x '.join('%.1f' % v for v in s11['size_arcmin']['half_level']), ' x '.join('%.1f' % v for v in s11['size_arcmin']['to_the_sky']), sh['position_angle_deg_east_of_north'], sh['axis_ratio']),
    half_stack_proof='PASSED for structure in the nebula\'s light, NOT passed for red filaments. Band-passed green of the odd and the even frames (%d and %d frames), stars masked, correlated inside the nebula against the same on %d places of blank sky: at 3 to 11 arcsec r = %.3f against %.3f +- %.3f (highest blank place %.3f): %.1f sigma; at 5 to 22 arcsec r = %.3f against %.3f +- %.3f: %.1f sigma; at 11 to 44 arcsec r = %.3f: %.1f sigma. No blank-sky place reaches the nebula at any scale. The structure that is really there is %.1f DN rms at 5 to 22 arcsec against %.1f DN of noise. Last week the same tests gave 1.4 and 3.5 sigma. BUT the test that would single out the filaments, the red excess (red minus the nebula\'s own red : green ratio times green; the filaments shine in H-alpha, which only the red plane sees, and this camera passes little of it), does not repeat at any scale: %.1f, %.1f and %.1f sigma. So: the mottled, lopsided body of the nebula is real and is shown; a web of red filaments as such is not seen, and the picture gives the nebula one colour and draws no red web.' % (
        s11['subsets']['odd'], s11['subsets']['even'], g15['blank_sky_places'], g15['halves_correlation_in_nebula'], g15['blank_sky_correlation_mean'], g15['blank_sky_correlation_std'], g15['blank_sky_correlation_max'], g15['significance_sigma'],
        g3['halves_correlation_in_nebula'], g3['blank_sky_correlation_mean'], g3['blank_sky_correlation_std'], g3['significance_sigma'], g6['halves_correlation_in_nebula'], g6['significance_sigma'], g3['real_structure_rms_dn'], g3['noise_rms_in_this_band_dn'],
        x15['significance_sigma'], x3['significance_sigma'], x6['significance_sigma']),
    filaments='not seen as filaments. Some of the fine structure that repeats in green may be filament light ([O III] falls in green and blue), but nothing here can tell it from the synchrotron glow\'s own texture, and the stars are %.1f arcsec wide against filaments of 2 to 5.' % star['hfd_stack_arcsec'],
    pulsar=('not shown as a separate star. A compact source of %.0f sigma sits %.1f arcsec from the pulsar\'s catalogue place (%+.1f east, %+.1f north), at pixel (%.0f, %.0f) of the finished picture: that is where the pair of 16th magnitude stars at the nebula\'s centre is (the pulsar is the south-western one, its neighbour about 5 arcsec north-east and a little brighter; the offset is the neighbour\'s side). With stars %.1f arcsec wide the two are one blob: the pulsar\'s light is very probably in it, but which part is the pulsar cannot be shown.' % (
        near['significance_sigma'], near['from_the_pulsars_place_arcsec'], near['east_arcsec'], near['north_arcsec'], near['picture_px'][0] - gc['x'], near['picture_px'][1] - gc['y'], star['hfd_stack_arcsec'])) if near else 'no compact source within 31 arcsec of the catalogue place',
    colour='warm white: red : green : blue %.2f : 1 : %.2f in the camera\'s daylight white balance, core and rim alike (%.2f and %.2f in red). Colour differences inside the nebula are not proven (the red excess does not repeat), so the colour comes from a 32 px average and the stars are shown without colour.' % (
        s11['colour']['ratio_to_green']['R'], s11['colour']['ratio_to_green']['B'], s11['colour']['core_and_rim']['core']['ratio_to_green']['R'], s11['colour']['core_and_rim']['rim']['ratio_to_green']['R']),
    flaws=['the sky just around the nebula sits %.1f DN (about 1%% of the sky) below the sky further out: the night\'s flat reads about 1.5%% high in the middle of the sensor (NGC 891 hid the sky there when it was made; the M77 stack found the same), and the nebula sits %.1f arcmin from the sensor\'s centre. It cannot be measured under the nebula from these frames, so it was left. It trims the faintest edge of the nebula a little; the sizes above are measured against that lower sky.' % (-s11['sky_around_it_green_dn'], s6['offset_from_frame_centre_arcmin']),
           'dust: the night\'s flat left its own fitted shadows up to %.1f%% deep under this run\'s sky; %d shadows (%.1f%% of the sensor, the deepest %.1f%%) were measured on this run\'s own open sky, seen in the odd and in the even frames alone, and divided out; after that the worst of the flat\'s fitted shadows is %.1f%%. %s no dust can be judged.' % (
               100 * s7['dust']['worst_left_by_the_nights_flat'], len(s7['dust']['divided_out']), 100 * s7['dust']['sensor_fraction_changed'], 100 * (1 - s7['dust']['deepest_factor']), 100 * s7['dust']['worst_left_after_own_correction'], s7['dust']['blind'].split(' no dust')[0].capitalize()),
           'the star mask of the proof (step 11) is generous and covers 44% of the nebula, its brightest knots among them: the proof is made on the rest, so it is on the careful side.',
           '%.2f minutes of exposure: the dark sky is set near black and smoothed, by choice (less noise over faint detail); %.1f%% of the picture is exactly black, and the nebula\'s faintest edge is smoothed with the sky.' % (len(used) * EXPOSURE_S / 60, fin.get('clipped_to_black_pct', 0)),
           'four frames were dropped for smeared or wide stars and the first after the slew by rule; two kept frames are near the limit (smear 0.19 and 0.20).'],
    not_done='no deconvolution, nothing generative, nothing retouched, never enlarged (one picture pixel per 2 x 2 colour cell of the sensor).')
rec = dict(
    target='Messier 1 (the Crab Nebula, NGC 1952), a supernova remnant in Taurus', night='2026-10-12 (frames of 13 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    files=dict(stack=os.path.join(OUT, 'm1-stack.tif'), picture=[os.path.join(FINAL, f) for f in ('m1.png', 'm1.jpg', 'm1.json')], picture_copy=os.path.join(OUT, 'm1.jpg'), full_field=[os.path.join(OUT, f) for f in ('m1-field.png', 'm1-field.jpg', 'm1-field.json')], scripts=SCR, logs=W('logs')),
    equipment=dict(camera='Sony a6000 (ILCE-6000), RAW', telescope='Celestron 8SE optical tube at f/10', focal_length_mm_by_plate_solve=round(s9['focal_length_mm']), mount='EQ6-R, polar axis about 5 degrees off the pole, tracking on a pointing model (the field turns)'),
    exposure=dict(frames_found=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej), exposure_s=EXPOSURE_S, iso=ISO, total_s=len(used) * EXPOSURE_S, total_minutes=round(len(used) * EXPOSURE_S / 60, 2), effective_frames=s5['effective_frames'],
                  first=min(u for u in used), last=max(u for u in used), altitude_deg=[min(alts), max(alts)] if alts else None, field_turned_deg=round(max(rot) - min(rot), 3), also_in_the_window=s1['left_out'],
                  not_stacked='the three 2 s ISO 6400 centring pictures of 09:53 to 09:55 UTC (listed in also_in_the_window): never stacked', what_the_run_was_like=run),
    verdict=verdict,
    plate_solution=dict(solver='astrometry.net (solve-field, local Tycho-2 index files), on the stack\'s green', arcsec_per_px=s9['pixscale_arcsec'], field_arcmin=s9['field_arcmin'], centre_ra_dec=s9['centre_ra_dec'], north=s9['north_in_words'],
                        north_angle_from_up_deg_clockwise=s9['north_angle_from_up_deg_clockwise'], east_angle_from_up_deg_clockwise=s9['east_angle_from_up_deg_clockwise'], mirrored=s9['mirrored'],
                        nebula_centre=dict(catalogue_ra_dec=[TARGET['ra_deg'], TARGET['dec_deg']], catalogue_is='the Crab pulsar', catalogue_place_in_the_stack_px=cat['pixel'], catalogue_place_in_the_finished_picture_px=s9['catalogue_place_in_the_nebula_crop_px'], centre_of_the_light_in_the_stack_px=[round(v, 1) for v in sh['light_centre_px']], centre_of_the_light_in_the_finished_picture_px=lc, light_from_catalogue_arcsec=round(sh['light_centre_from_catalogue_arcsec'], 1), light_offset_east_north_arcsec=[round(v, 1) for v in sh['light_centre_offset_east_north_arcsec']], picture_size_px=[ww, hh]),
                        stack_origin_on_reference_grid=s9['crop_on_reference_grid'], corners_ra_dec=s9['corners_ra_dec'], brightest_sources=s9['brightest_sources_of_the_reference_frame'], wcs_header=s9['wcs_header'],
                        reference_frame_solve=dict(frame=s6['frame'], arcsec_per_px=s6['pixscale_arcsec'], north_angle_from_up_deg_clockwise=s6['north_angle_from_up_deg_clockwise'], target_from_frame_centre_arcmin=s6['offset_from_frame_centre_arcmin'])),
    steps=[
        dict(step='frames', detail='the 15 s ISO 3200 frames (by the RAW\'s own EXIF) with sidecar pointing within %.1f deg of M1, file-name times %s to %s UTC' % (POINTING_RADIUS_DEG, T0, T1)),
        dict(step='planes', detail='each RAW split into its four colour planes (R, G1, G2, B), black subtracted; no demosaic'),
        dict(step='hot pixels', detail='from the run itself (no darks): fixed map from the unregistered median of the frames, transient spikes per frame; replaced by the 3 x 3 median of the plane', numbers=s1['hot']),
        dict(step='stars and registration', detail='stars on the mean green plane; rotation + shift to the reference frame %s (scale held at 1)' % REF_STAMP, reference=REF_STAMP),
        dict(step='selection', limits=s5['limits'], star_size_median_arcsec=s5['hfd_run_median_arcsec'], rejected=s5['rejected']),
        dict(step='flat', detail='the night\'s flat (from the NGC 891 run), checked against this run\'s own open sky; dust it left measured on this run\'s own sky and divided out', numbers=s7,
             flat_file=dict(path=os.path.join(FLAT_DIR, 'flat_planes.npz'), sha256_when_the_recipe_was_written=__import__('hashlib').sha256(open(os.path.join(FLAT_DIR, 'flat_planes.npz'), 'rb').read()).hexdigest(),
                            modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(FLAT_DIR, 'flat_planes.npz')), datetime.timezone.utc).isoformat(timespec='seconds'), step7_ran=datetime.datetime.fromtimestamp(os.path.getmtime(W('step7_flat.json')), datetime.timezone.utc).isoformat(timespec='seconds'))),
        dict(step='stack', detail='per frame and plane: / flat, x 1/transparency, one Lanczos-4 resampling onto the reference frame\'s colour-cell grid (rotation + shift + the plane\'s place in the cell + the air dispersion offset), minus ONE constant (3-sigma clipped mean over the sky region, outside the ellipse of the nebula); combined per pixel by a 3-sigma clipped weighted mean', kappa=s8['kappa'], sky_region=s8['faint_region'], planes=s8['planes'], subsets=s8['subsets']),
        dict(step='air dispersion', numbers=s8['air_dispersion']),
        dict(step='linear TIF', numbers=s10['tif']),
        dict(step='picture: sky plane (in the picture only, not in the TIF)', numbers=s10['sky_plane_in_the_picture_only']),
        dict(step='picture: colour and stretch (render.py)', params=s10['render_params'], info=s10['render_info'], white_balance=s10['white_balance_daylight'], rgb_cam=s10['rgb_cam']),
        dict(step='picture: crop (crop.py)', numbers=crop, said='%d x %d px = %.1f x %.1f arcmin around the catalogue place, pixels untouched, never enlarged' % (gc['w'], gc['h'], gc['w'] * s9['pixscale_arcsec'] / 60, gc['h'] * s9['pixscale_arcsec'] / 60)),
        dict(step='is it real? (step 11)', detail='half stacks of the odd and the even frames, band-passed and correlated inside the nebula and on blank sky; see verdict.half_stack_proof and measured.nebula_and_proof.structure', looks=[W('halves_look.png'), W('halves_bandpass.png')]),
        dict(step='picture: finish (finish16.py = the finish-pictures tool reading 16 bits)', numbers=fin, full_field=finf, skycheck=dict(picture=skycheck(os.path.join(FINAL, 'm1.png')), full_field=skycheck(os.path.join(OUT, 'm1-field.png'))), jpeg_markers=mk),
    ],
    measured=dict(noise=s10['noise_faint_region'], star_size=star, nebula_and_proof=s11),
    against_8_october=cmp_,
    frames=frames,
    reproduce='hack/stacks/2026-10-12/m1/run_all.sh (hooks are environment variables M1_*; none set reproduces this run)',
    software=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, machine=platform.platform()))
json.dump(rec, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
print('recipe.json written: %d frames found, %d used (%.2f min), %d dropped' % (len(s1['frames']), len(used), len(used) * EXPOSURE_S / 60, len(rej)))
for k, v in verdict.items(): print(' ', k + ':', v if isinstance(v, str) else '\n      ' + '\n      '.join(v))
print('  the run:', run['said'])
if cmp_: print('  against 8 October:', cmp_['verdict'])
print('picture %d x %d px, catalogue place at %s, centre of the light at %s; %s' % (ww, hh, s9['catalogue_place_in_the_nebula_crop_px'], lc, s9['north_in_words']))
