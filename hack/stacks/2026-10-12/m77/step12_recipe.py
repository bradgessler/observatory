"""Step 12: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat and its check, the sky constants, the registration, the weights, the air dispersion, the
plate solution (scale, which way north is, where the nucleus is in the picture), the stretch, the crop, the finish,
and the honest verdict on what is and is not seen.

Copies final/m77.jpg to m77/m77.jpg (checked free of EXIF / XMP / comment segments first)."""
import json, os, platform, datetime, shutil
import numpy as np, cv2, rawpy, tifffile
from common import *
import render

FINAL = os.environ.get('M77_FINAL', os.path.join(NIGHT, 'final'))
s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json')
fin = json.load(open(os.path.join(FINAL, 'm77.json'))); crop = json.load(open(W('m77-crop.json'))); finf = json.load(open(os.path.join(OUT, 'm77-field.json')))
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


mk = jpeg_markers(os.path.join(FINAL, 'm77.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, 'm77.jpg'), os.path.join(OUT, 'm77.jpg'))
pic = cv2.imread(os.path.join(FINAL, 'm77.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
g = s10['galaxy']; core = s10['core']; star = s10['star_size']; gc = s9['galaxy_crop']; cat = s9['catalogue'][TARGET['name']]
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
verdict = dict(
    is_it_the_thing='yes: the reference frame and the stack were plate-solved (astrometry.net, Tycho-2 index files); the catalogue place of the nucleus of NGC 1068 falls %.1f arcsec from the centroid of the bright, extended source. The compact source 1.45 arcmin from it is a foreground star, and the one source that touched the ceiling is a star 10.9 arcmin away (%s).' % (cat['offset_arcsec'], ', '.join('RA %.4f Dec %+.4f' % (b['ra_deg'], b['dec_deg']) for b in s9['brightest_sources_of_the_reference_frame'] if b['touched_the_ceiling'])),
    core='not clipped: the highest RAW value around the nucleus in any 15 s frame is %.0f DN above black, %.0f%% of the ceiling (%.0f). Nothing was painted or repaired. In the picture the nucleus is bright but not flat white.' % (max(core['max_over_frames_dn'].values()), 100 * core['highest_fraction_of_the_ceiling'], CEILING_RAW - 512),
    seen='the bright inner disc, about %.1f arcmin across by the strict rule (ring median above 3 x the blank-sky spread out to %.2f arcmin from the nucleus; light is still positive to about 1.5 arcmin), the star-like nucleus on a short bright bar, and the inner spiral arms as a brighter oval with knots around it.' % (g['followed_to']['diameter_arcmin'], g['followed_to']['radius_arcmin']),
    not_seen='the faint outer arms and the outer ring (2.2 to 3.6 arcmin from the nucleus, the catalogue\'s 7.1 x 6.0 arcmin): NOT seen. The ring medians there are %s DN, at or below zero, against a blank-sky spread of about %.1f DN and a sky of %.0f DN. A ring that faint would be expected under about 1 DN here (an estimate from the level of the sky, not a measurement): under what the flat and the sky leave.' % (g['outer_ring']['stack_dn_there'], float(np.median(g['outer_ring']['floor_dn_there'])), g['sky_under_it_dn']),
    flaws=['the sky within about 4 arcmin of the galaxy sits about 1 DN (1% of the sky) below the blank sky further out (ring medians -0.2 to -0.7 DN against +0.7): the night\'s flat is a fitted profile in the middle of the sensor, where NGC 891 hid the sky when it was made, and this run\'s own sky reads 1.5% low against it inside 600 sensor px. This is what hides the outer disc; it cannot be measured under the galaxy from these frames.',
           'the night\'s flat left its dust shadows 1 to 5%% deep under this run\'s sky and did not carry about 80 fainter ones; they were measured on this run\'s own sky and divided out (step 7). %s no dust can be judged.' % s7['dust']['blind'].split(' no dust')[0].capitalize(),
           'colour is shown only where the light is above 8 DN (the bright disc and the stars); the fainter edge is grey, because there the colour is set by sky and flat errors, not by the galaxy.',
           '7 minutes of exposure: the dark sky is set near black and smoothed, by choice (less noise over faint detail); %.1f%% of the picture is exactly black.' % fin.get('clipped_to_black_pct', 0)],
    not_done='no deconvolution, nothing generative, nothing retouched, never enlarged (one picture pixel per 2 x 2 colour cell of the sensor).')
rec = dict(
    target='Messier 77 (NGC 1068), a face-on spiral galaxy in Cetus', night='2026-10-12 (frames of 13 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    files=dict(stack=os.path.join(OUT, 'm77-stack.tif'), picture=[os.path.join(FINAL, f) for f in ('m77.png', 'm77.jpg', 'm77.json')], picture_copy=os.path.join(OUT, 'm77.jpg'), full_field=[os.path.join(OUT, f) for f in ('m77-field.png', 'm77-field.jpg', 'm77-field.json')], scripts=SCR, logs=W('logs')),
    equipment=dict(camera='Sony a6000 (ILCE-6000), RAW', telescope='Celestron 8SE optical tube at f/10', focal_length_mm_by_plate_solve=round(s9['focal_length_mm']), mount='EQ6-R, polar axis about 5 degrees off the pole, tracking on a pointing model (the field turns)'),
    exposure=dict(frames_found=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej), exposure_s=EXPOSURE_S, iso=ISO, total_s=len(used) * EXPOSURE_S, total_minutes=round(len(used) * EXPOSURE_S / 60, 2), effective_frames=s5['effective_frames'],
                  first=min(u for u in used), last=max(u for u in used), altitude_deg=[min(alts), max(alts)] if alts else None, field_turned_deg=round(max(rot) - min(rot), 3), also_in_the_window=s1['left_out'],
                  not_stacked='the 2 s ISO 6400 centring pictures of 09:11 and 09:12 and the black 1/60 s frames of 08:45 to 08:46 UTC are outside the time window and were never read'),
    verdict=verdict,
    plate_solution=dict(solver='astrometry.net (solve-field, local Tycho-2 index files), on the stack\'s green', arcsec_per_px=s9['pixscale_arcsec'], field_arcmin=s9['field_arcmin'], centre_ra_dec=s9['centre_ra_dec'], north=s9['north_in_words'],
                        north_angle_from_up_deg_clockwise=s9['north_angle_from_up_deg_clockwise'], east_angle_from_up_deg_clockwise=s9['east_angle_from_up_deg_clockwise'], mirrored=s9['mirrored'],
                        nucleus=dict(catalogue_ra_dec=[TARGET['ra_deg'], TARGET['dec_deg']], catalogue_place_in_the_stack_px=cat['pixel'], centroid_in_the_stack_px=cat['nucleus_centroid_within_12px'], offset_arcsec=cat['offset_arcsec'],
                                     in_the_finished_picture_px=s9['nucleus_in_the_galaxy_crop_px'], picture_size_px=[ww, hh]),
                        stack_origin_on_reference_grid=s9['crop_on_reference_grid'], corners_ra_dec=s9['corners_ra_dec'], brightest_sources=s9['brightest_sources_of_the_reference_frame'], wcs_header=s9['wcs_header'],
                        reference_frame_solve=dict(frame=s6['frame'], arcsec_per_px=s6['pixscale_arcsec'], north_angle_from_up_deg_clockwise=s6['north_angle_from_up_deg_clockwise'], target_from_frame_centre_arcmin=s6['offset_from_frame_centre_arcmin'])),
    steps=[
        dict(step='frames', detail='the 15 s ISO 3200 frames (by the RAW\'s own EXIF) with sidecar pointing within %.1f deg of M77, file-name times %s to %s UTC' % (POINTING_RADIUS_DEG, T0, T1)),
        dict(step='planes', detail='each RAW split into its four colour planes (R, G1, G2, B), black subtracted; no demosaic'),
        dict(step='hot pixels', detail='from the run itself (no darks): fixed map from the unregistered median of the frames, transient spikes per frame; replaced by the 3 x 3 median of the plane', numbers=s1['hot']),
        dict(step='stars and registration', detail='stars on the mean green plane; rotation + shift to the reference frame %s (scale held at 1)' % REF_STAMP, reference=REF_STAMP),
        dict(step='selection', limits=s5['limits'], star_size_median_arcsec=s5['hfd_run_median_arcsec'], rejected=s5['rejected']),
        dict(step='flat', detail='the night\'s flat (from the NGC 891 run), checked against this run\'s own open sky; dust it left measured on this run\'s own sky and divided out', numbers=s7,
             flat_file=dict(path=os.path.join(FLAT_DIR, 'flat_planes.npz'), sha256_when_the_recipe_was_written=__import__('hashlib').sha256(open(os.path.join(FLAT_DIR, 'flat_planes.npz'), 'rb').read()).hexdigest(),
                            modified=datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(FLAT_DIR, 'flat_planes.npz')), datetime.timezone.utc).isoformat(timespec='seconds'), step7_ran=datetime.datetime.fromtimestamp(os.path.getmtime(W('step7_flat.json')), datetime.timezone.utc).isoformat(timespec='seconds'))),
        dict(step='stack', detail='per frame and plane: / flat, x 1/transparency, one Lanczos-4 resampling onto the reference frame\'s colour-cell grid (rotation + shift + the plane\'s place in the cell + the air dispersion offset), minus ONE constant (3-sigma clipped mean over the sky region); combined per pixel by a 3-sigma clipped weighted mean', kappa=s8['kappa'], sky_region=s8['faint_region'], planes=s8['planes'], subsets=s8['subsets']),
        dict(step='air dispersion', numbers=s8['air_dispersion']),
        dict(step='linear TIF', numbers=s10['tif']),
        dict(step='picture: sky plane (in the picture only, not in the TIF)', numbers=s10['sky_plane_in_the_picture_only']),
        dict(step='picture: colour and stretch (render.py)', params=s10['render_params'], info=s10['render_info'], white_balance=s10['white_balance_daylight'], rgb_cam=s10['rgb_cam']),
        dict(step='picture: crop (crop.py)', numbers=crop, said='%d x %d px = %.1f x %.1f arcmin around the nucleus, pixels untouched; NGC 1055, half a degree away, is not in the frame' % (gc['w'], gc['h'], gc['w'] * s9['pixscale_arcsec'] / 60, gc['h'] * s9['pixscale_arcsec'] / 60)),
        dict(step='picture: finish (finish16.py = the finish-pictures tool reading 16 bits)', numbers=fin, full_field=finf, skycheck=dict(picture=skycheck(os.path.join(FINAL, 'm77.png')), full_field=skycheck(os.path.join(OUT, 'm77-field.png'))), jpeg_markers=mk),
    ],
    measured=dict(noise=s10['noise_faint_region'], star_size=star, core=core, galaxy=g),
    frames=frames,
    reproduce='hack/stacks/2026-10-12/m77/run_all.sh (hooks are environment variables M77_*; none set reproduces this run)',
    software=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, machine=platform.platform()))
json.dump(rec, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
print('recipe.json written: %d frames found, %d used (%.2f min), %d dropped' % (len(s1['frames']), len(used), len(used) * EXPOSURE_S / 60, len(rej)))
for k, v in verdict.items(): print(' ', k + ':', v if isinstance(v, str) else '\n      ' + '\n      '.join(v))
print('picture %d x %d px, nucleus at %s; %s' % (ww, hh, s9['nucleus_in_the_galaxy_crop_px'], s9['north_in_words']))
