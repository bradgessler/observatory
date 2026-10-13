"""Step 11: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat, the sky constants, the registration, the weights, the stretch, the finish.

Copies final/m33.jpg to m33/m33.jpg (checked free of EXIF / XMP / comment segments first) and writes m33/m33-1600.jpg,
the same picture area-averaged to 1600 px wide (never enlarged)."""
import json, os, platform, datetime, shutil
import numpy as np, cv2, scipy, rawpy, tifffile, PIL
from common import *
import render

FINAL = os.environ.get('M33_FINAL', os.path.join(NIGHT, 'final'))
s1 = jload('step1.json'); s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_flat.json'); s7 = jload('step7_stack.json'); s8 = jload('step8_solve.json'); s9 = jload('step9_deliver.json')
fin = json.load(open(os.path.join(FINAL, 'm33.json')))
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


mk = jpeg_markers(os.path.join(FINAL, 'm33.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, 'm33.jpg'), os.path.join(OUT, 'm33.jpg'))
pic = cv2.imread(os.path.join(FINAL, 'm33.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
W16 = 1600; H16 = int(round(hh * W16 / ww))
cv2.imwrite(os.path.join(OUT, 'm33-1600.jpg'), cv2.resize(pic, (W16, H16), interpolation=cv2.INTER_AREA), [cv2.IMWRITE_JPEG_QUALITY, 92])

frames = []
for f in s1['frames']:
    s = f['stamp']; t = s3[s]; q = s4[s]
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'], seconds_since_last_slew=f['since_slew_s'],
                       used=s in used, why_dropped=rej[s]['why'] if s in rej else None, weight=round(used[s]['weight'], 4) if s in used else 0.0,
                       transparency=round(q['transparency'], 4), star_half_flux_diameter_arcsec=round(q['hfd_arcsec'], 3), box_star_size_arcsec=f['box_star_size_arcsec'],
                       elongation_median=round(min(q['elong_median'], 99.0), 3), smear_common_ellipticity=round(q['smear'], 3), smear_angle_deg=round(q['smear_angle_deg'], 1),
                       registration=dict(rotation_deg=round(t['rotation_deg'], 4), shift_at_sensor_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], stars_used=t['used'], weighted_rms_px=round(t['wrms_px'], 3),
                                         scale_if_left_free=round(t['similarity_scale'], 5), found_by_coarse_vote=bool(t.get('coarse_vote', False)), R=t['R'], t=t['t']),
                       sky_constant_dn=dict(zip(PLANE_NAMES, [round(v, 2) for v in s7['constants'][s]])) if s in used else None,
                       black_level=f['black'], pixel_noise_dn=dict(zip(PLANE_NAMES, [round(v, 1) for v in f['pix_sigma']])), transient_pixels_replaced=dict(zip(PLANE_NAMES, s2[s]['transient_replaced'])),
                       pixels_at_ceiling=dict(zip(PLANE_NAMES, f['ceiling_pixels']))))
st_sorted = sorted(s3); rot = np.array([s3[s]['rotation_deg'] for s in st_sorted]); sh = np.array([s3[s]['shift_at_centre_px'] for s in st_sorted])
C = np.array([s7['constants'][s] for s in s7['frames']]); n9 = s9['noise_faint_region']
trailed = [r for r in s5['rejected'] if r['smear'] > s5['limits']['smear_max']]
trailed_before = sum(1 for r in trailed if r['stamp'] < '20261013-081900'); n_before = sum(1 for f in s1['frames'] if f['stamp'] < '20261013-081900')
OLD = os.path.expanduser('~/.observatory/nights/2026-10-08-a6000/m33/recipe.json'); old = json.load(open(OLD)) if os.path.exists(OLD) else None
cmp8 = None
if old:
    on = old['numbers']
    cmp8 = dict(recipe=OLD, frames_used=[old['source']['frames_used'], len(used)], minutes=[old['source']['frames_used'] * 15 / 60, len(used) * 15 / 60],
                plane_noise_dn={p: [on['noise']['planes_stack'][p], round(n9['planes_stack'][p], 2)] for p in PLANE_NAMES},
                luminance_noise_after_1px_blur_dn=[on['noise']['luminance']['stack_after_blur'], round(n9['luminance']['stack_after_blur'], 2)],
                star_half_flux_diameter_arcsec=[on['star_half_flux_diameter']['stack_arcsec'], round(s9['star_size']['hfd_stack_arcsec'], 2)], order='[8 October, 12 October]',
                verdict='12 October is the better picture: three times the exposure (%.1f against %.2f min), half the noise per pixel (green %.1f against %.1f DN), stars a little smaller (%.2f against %.2f arcsec). '
                        'The dust lanes of the inner arms, the chains of clusters and the faint outer arms that were grain on 8 October are there now. The same colour handling (disk shown grey, colour only where bright), '
                        'the same greenish tint on white stars, the same field (a little smaller: %d x %d against 2970 x 1980 px, because the field wandered and turned).' % (
                            len(used) * 15 / 60, old['source']['frames_used'] * 15 / 60, 0.5 * (n9['planes_stack']['G1'] + n9['planes_stack']['G2']), 0.5 * (on['noise']['planes_stack']['G1'] + on['noise']['planes_stack']['G2']),
                            s9['star_size']['hfd_stack_arcsec'], on['star_half_flux_diameter']['stack_arcsec'], ww, hh))
recipe = dict(
    what='M33, the Triangulum Galaxy: core and inner arms. %d x 15 s at ISO 3200 (%.1f min), Sony a6000 on a Celestron 8SE (%.0f mm by plate solve, f/10), EQ6-R on a tripod with the polar axis about 5 degrees off, tracking in both axes on a pointing model, night of 12/13 October 2026. Stacked from RAW colour planes.' % (len(used), len(used) * 15 / 60, s8['focal_length_mm']),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, tifffile=tifffile.__version__, pillow=PIL.__version__, astrometry_net='solve-field (local index files 4107-4115)',
               note='deterministic array arithmetic only: averages, medians, measured blurs, fixed curves and matrices. Nothing generative, learned or upscaled; no neural denoise or sharpening; no deconvolution.'),
    scripts='hack/stacks/2026-10-12/m33/ in the observatory repository: run_all.sh runs step1_hot ... step11_recipe, then step12_clean. render.py is the colour and stretch, finish16.py the finish-pictures tool reading 16 bits, fitsmin.py the FITS helper. With no environment variables set it reproduces this run. Adapted from hack/stacks/2026-10-08/m33/.',
    source=dict(folder=STILLS, window=[T0, T1], files_in_window=len(s1['all_in_window']), left_out_before_stacking=s1['left_out'], frames_15s_iso3200_on_m33=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej),
                other_sets_of_the_night_not_used=[
                    dict(what='177 x 2 s at ISO 6400, 05:09 to 06:31 UTC', why='5.9 min in all, read-noise limited at f/10 (about 12 DN of sky per frame); nothing in the 15 s frames needs them: the nucleus peaks at about 450 DN above its surroundings in a 15 s frame, far from the ceiling, and the %d star-core pixels at the ceiling are shown white' % s9['render_info']['ceiling_pixels']),
                    dict(what='34 x 1 s at ISO 1000, 07:01 to 07:20 UTC, and nine 15 s and 30 s test frames at ISO 6400, 06:31 to 06:37 UTC', why='too short to add signal; different settings')],
                originals='read in place, never written; nothing cached per frame'),
    selection=dict(rule='drop a frame if it is smeared (common-direction ellipticity above %.2f: every star stretched the same way, the mount letting go during the exposure), or its stars are wider than %.2f x the median half-flux diameter of the unsmeared frames, or its stars are below %.0f%% of their usual brightness, or the registration rms is above %.1f px, or it was taken within %.0f s of a move' % (s5['limits']['smear_max'], s5['limits']['hfd_max_rel'], 100 * s5['limits']['transparency_min'], s5['limits']['registration_wrms_max_px'], s5['limits']['since_slew_min_s']),
                   limits=s5['limits'], unsmeared_median_star_half_flux_diameter_arcsec=round(s5['hfd_run_median_arcsec'], 3),
                   trailed_frames=len(trailed), trailed_before_0819=trailed_before, frames_before_0819=n_before, trailed_after_0819=len(trailed) - trailed_before,
                   dropped_for_star_size_alone=s5['dropped_for_size_only'],
                   story='until 08:19 UTC the tracking let go of both motors for about 5 s now and then (a software bug, fixed at 08:19). %d of the %d frames before 08:19 are trailed (stars a dot with a tail towards -50 to -60 deg, 4 to 9 arcsec); %d after (the first frame after the fix, taken during a move). %d more were dropped for soft stars alone (4.4 to 4.7 arcsec, 07:48 to 07:55, not trailed).' % (trailed_before, n_before, len(trailed) - trailed_before, s5['dropped_for_size_only']),
                   weights='(transparency / noise)^2, noise = the frame\'s zero-level pixel noise over the run median; each used frame also scaled by 1 / transparency', effective_frames=round(s5['effective_frames'], 2),
                   night='clear: every untrailed frame within 5% of the run\'s median star brightness'),
    frames=frames,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (6024 x 4024, RGGB), black level 512 subtracted, four colour planes R, G1, G2, B kept apart (3012 x 2012 each), no demosaic. Exposure and ISO from the RAW\'s own EXIF; the run is the frames whose sidecar pointing is within %.1f deg of M33.' % POINTING_RADIUS_DEG),
        dict(step='hot pixels', detail='fixed: per plane, the median without registration of every 4th frame of the run (%d frames); pixels above the 5 x 5 median of that by more than max(6 sigma, 25%% of the level). Transient: per frame, above the 3 x 3 median by more than 8 sigma + 50%% of the level. Both replaced by the 3 x 3 median of the same plane. No darks.' % len(s1['hot_from']),
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s1['hot']}),
        dict(step='stars', detail='green planes averaged; the galaxy\'s smooth light taken off; detection at 6 sigma of a local noise model; windowed centroids, 14 px aperture flux, second moments, half-flux radius.'),
        dict(step='register', detail='rotation + shift (scale held at 1), weighted least squares on matched stars, 3.5-sigma rejection, frames walked outward in time from the reference %s; the field turned because the polar axis is about 5 degrees off.' % REF_STAMP,
             rotation_deg=dict(first=round(float(rot[0]), 4), last=round(float(rot[-1]), 4), total=round(float(rot[0] - rot[-1]), 4), per_minute=round(float((rot[0] - rot[-1]) / 72.3), 4)),
             shift_range_px=dict(x=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], y=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]),
             weighted_rms_px_used_frames=[round(min(s3[s]['wrms_px'] for s in used if s != REF_STAMP), 3), round(max(s3[s]['wrms_px'] for s in used), 3)]),
        dict(step='flat', detail='no flat panel, no twilight flats (yet), and no open-sky run at these settings tonight. Vignetting: the radial profile measured on 8 October 2026 from that night\'s two open-sky runs (same telescope, camera, settings), mean of its green fits, the same for all four planes; M33\'s own frames cannot check it. Dust: found in TONIGHT\'s frames, from two halves of the run (before and after 07:57 UTC) whose sky behind the dust differs because the field wandered: a shadow is divided out only where both halves alone show it alike, each modelled as a round disc with a soft edge; the flat is exactly 1 elsewhere. See step6_flat.py.',
             vignetting=s6['vignetting'], dust=s6['dust'], halves=s6['halves'],
             dust_against_8_october='%d of tonight\'s %d shadows sit where 8 October had one (same sensor dust, depths within about 1 to 4 percentage points); %d are new; %d shallow ones of 8 October (about 4%% deep, near the middle of the sensor where the galaxy is brightest) are not confirmed by both halves tonight and were NOT divided out: if still there, they are smeared over the field\'s wander in the stack' % (
                 sum(1 for d in s6['dust']['shadows'] if d['on_8_october']), len(s6['dust']['shadows']), sum(1 for d in s6['dust']['shadows'] if not d['on_8_october']), len(s6['dust']['of_8_october_not_seen_tonight_not_applied']))),
        dict(step='resample', detail='each plane of each used frame divided by the flat and scaled by 1/transparency, then mapped straight onto the reference frame\'s grid of 2 x 2 colour cells (rotation + shift + the plane\'s own place in the cell), OpenCV remap, Lanczos-4. One output pixel per colour cell; nothing enlarged.'),
        dict(step='sky', detail='ONE constant per colour per frame, nothing else: the 3-sigma clipped mean of the resampled plane over the faint region, subtracted. The faint region is the darkest %.0f%% (of the green, smoothed) of the area every used frame covers, on the reference frame: the same sky pixels for every frame and colour. No surface is fitted: the galaxy fills the frame. The stack\'s zero is therefore the galaxy\'s faintest level in this field, not the true sky.' % s7['faint_region']['percentile'],
             faint_region=s7['faint_region'], constants_dn_range={p: [round(float(C[:, i].min()), 2), round(float(C[:, i].max()), 2)] for i, p in enumerate(PLANE_NAMES)}),
        dict(step='combine', detail='per pixel and plane: values further than 3 sigma from the median dropped (sigma = 1.4826 x MAD across frames, floor 0.4 x the single-frame noise, widened by each frame\'s noise factor), then 3 sigma about the weighted mean of the survivors, then the weighted mean.',
             dropped_fraction={p['plane']: round(p['dropped_fraction'], 5) for p in s7['planes']}),
        dict(step='crop', detail='the largest rectangle in which every pixel has at least %d of the %d frames: x %d..%d, y %d..%d of the reference grid, %d x %d px' % (s8['crop_on_reference_grid']['cover_min_frames'], len(used), s8['crop_on_reference_grid']['x0'], s8['crop_on_reference_grid']['x1'], s8['crop_on_reference_grid']['y0'], s8['crop_on_reference_grid']['y1'], s8['crop_on_reference_grid']['width'], s8['crop_on_reference_grid']['height'])),
        dict(step='plate solve', detail='astrometry.net (local) on the stack\'s green: solved; M33\'s nucleus found %.1f arcsec from its catalogue place' % s8['catalogue']['M33 nucleus']['offset_arcsec'], pixel_scale_arcsec=round(s8['pixscale_arcsec'], 4), focal_length_mm=round(s8['focal_length_mm'], 1),
             field_arcmin=[round(v, 2) for v in s8['field_arcmin']], centre_ra_dec_deg=[round(v, 5) for v in s8['centre_ra_dec']], catalogue_check=s8['catalogue'],
             orientation='as the camera saw it, not mirrored, not turned (a turn would resample the picture): north points %.0f deg anticlockwise from up, east %.0f deg anticlockwise from up' % (-s8['north_angle_from_up_deg_clockwise'], -s8['east_angle_from_up_deg_clockwise'])),
        dict(step='colour and stretch', detail=render.__doc__.strip(), white_balance_daylight=s9['white_balance_daylight'], camera_to_srgb=s9['rgb_cam'], parameters=s9['render_params'],
             luminance_weights=s9['render_info']['luminance_weights'], colour_shown_on_fraction_of_picture=round(s9['render_info']['colour_shown_fraction'], 4), stars_at_ceiling_px=s9['render_info']['ceiling_pixels']),
        dict(step='finish', detail='finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch at full depth), one line in step10_finish.sh', recipe=fin,
             skycheck=skycheck(os.path.join(FINAL, 'm33.png')), tried='black-pct 6 (sky read grey, 26 of 255, and flat), black-pct 20 with gamma 0.9 (5% of the picture exactly black); kept black-pct 14'),
    ],
    numbers=dict(noise=dict(units=n9['units'], planes_single=n9['planes_single'], planes_stack=n9['planes_stack'], improvement=n9['improvement'], ideal_for_these_weights=n9['ideal'], odd_even_half_difference=n9['planes_half_difference_odd_even'], luminance=n9['luminance']),
                 star_half_flux_diameter=dict(stack_px=round(s9['star_size']['hfd_stack_px'], 2), stack_arcsec=round(s9['star_size']['hfd_stack_arcsec'], 2), single_px=round(s9['star_size']['hfd_single_px'], 2), single_arcsec=round(s9['star_size']['hfd_single_arcsec'], 2), stars=s9['star_size']['stars'],
                                              note='green, 14 px aperture, compact unsaturated isolated stars, on the linear stack (before the 1 px blur of the picture)'),
                 galaxy_green_profile=s9['galaxy_green_profile']),
    outputs={'m33-stack.tif': s9['tif'],
             'final/m33.png': dict(what='the finished picture at the stack\'s own scale, 8-bit', size_px=[ww, hh], pixel_scale_arcsec=s8['pixscale_arcsec'], metadata='none'),
             'final/m33.jpg': dict(what='the same as a JPEG (quality 93); also copied to m33/m33.jpg', markers=mk, metadata='none'),
             'final/m33.json': 'the finish recipe written by finish16.py',
             'm33-1600.jpg': dict(what='the same, area-averaged to 1600 px wide', size_px=[W16, H16], resampling='cv2.INTER_AREA, %.3f x' % (W16 / ww))},
    compared_with_8_october=cmp8,
    caveats=[
        'The stack\'s zero is the galaxy\'s faintest level in the field, not the true sky: M33 is bigger than the frame.',
        'Colour is shown only where the light is bright enough to carry it (%.1f%% of the picture: stars, the core, the brightest HII regions such as NGC 604). The disk is shown grey on purpose.' % (100 * s9['render_info']['colour_shown_fraction']),
        'White stars come out faintly green: camera daylight white balance and the camera\'s own matrix, with no star-colour calibration (measured R : G : B of such stars in the stack about 0.91 : 1 : 0.94). The same on 8 October.',
        'Stars towards the corners have a short flare pointing away from the centre (the optics off axis, not the tracking: registration is good to 0.4 to 0.7 px).',
        'No darks, no flat frames: hot pixels from the run itself, vignetting from the 8 October profile (not checkable tonight), dust from tonight\'s frames. Two shallow shadows near the middle were left uncorrected (see the flat step).',
        'The brightest picture pixels (0.03%) are white and about 2% of the picture, the darkest sky, is exactly black: the black point was raised for a quiet sky.',
        'The frame is in the camera\'s orientation, not north-up.'])
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('recipe.json: %d frames (%d used, %d dropped: %d trailed, %d soft); %s' % (len(frames), len(used), len(rej), len(trailed), s5['dropped_for_size_only'], cmp8['verdict'] if cmp8 else ''))
print('m33.jpg markers', mk, '| m33-1600.jpg', [W16, H16], '| sky', recipe['steps'][-1]['skycheck'])
