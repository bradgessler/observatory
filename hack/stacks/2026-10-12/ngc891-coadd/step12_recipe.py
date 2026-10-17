"""Step 12: deliver and write recipe.json: every number that shaped the stack and the picture, which frames, why the
others were dropped, the flat, the sky constants, the registration, the weights, the stretch, the crop, the finish.

Copies final-trial/ngc891-coadd.jpg to ngc891-coadd/ngc891-coadd.jpg (checked free of EXIF / XMP / comment segments first).
(Trial: the combine step is the proper coadd of step8_coadd.py; its every number is in steps[combine] and in
work/step8_coadd.json; the comparison with the delivered stack is work/step14_compare.json.)"""
import json, os, platform, datetime, shutil
import numpy as np, cv2, scipy, rawpy, tifffile, PIL
from common import *
import render

s1 = jload('step1.json'); s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json'); s7 = jload('step7_flat.json'); s8 = jload('step8_stack.json'); s8c = jload('step8_coadd.json'); s9 = jload('step9_solve.json'); s10 = jload('step10_deliver.json')
fin = json.load(open(os.path.join(FINAL, NAME + '.json'))); crop = json.load(open(W(NAME + '-crop.json'))); finf = json.load(open(os.path.join(OUT, NAME + '-field.json')))
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


mk = jpeg_markers(os.path.join(FINAL, NAME + '.jpg'))
assert not [m for m in mk if m in ('FFE1', 'FFE2', 'FFED', 'FFFE')], mk
shutil.copyfile(os.path.join(FINAL, NAME + '.jpg'), os.path.join(OUT, NAME + '.jpg'))
pic = cv2.imread(os.path.join(FINAL, NAME + '.png'), cv2.IMREAD_COLOR); hh, ww = pic.shape[:2]
fld = cv2.imread(os.path.join(OUT, NAME + '-field.png'), cv2.IMREAD_COLOR); fh, fw = fld.shape[:2]

frames = []
for f in s1['frames']:
    s = f['stamp']; t = s3[s]; q = s4[s]
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'], seconds_since_last_slew=f['since_slew_s'],
                       used=s in used, why_dropped=rej[s]['why'] if s in rej else None, weight=round(used[s]['weight'], 4) if s in used else 0.0,
                       transparency=round(q['transparency'], 4), star_half_flux_diameter_arcsec=round(q['hfd_arcsec'], 3), box_star_size_arcsec=f['box_star_size_arcsec'],
                       elongation_median=round(min(q['elong_median'], 99.0), 3), smear_common_ellipticity=round(q['smear'], 3), smear_angle_deg=round(q['smear_angle_deg'], 1),
                       registration=dict(rotation_deg=round(t['rotation_deg'], 4), shift_at_sensor_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], stars_used=t['used'], weighted_rms_px=round(t['wrms_px'], 3),
                                         scale_if_left_free=round(t['similarity_scale'], 5), found_by_coarse_vote=bool(t.get('coarse_vote', False)), R=t['R'], t=t['t']),
                       sky_constant_dn=dict(zip(PLANE_NAMES, [round(v, 2) for v in s8['constants'][s]])) if s in used else None,
                       black_level=f['black'], pixel_noise_dn=dict(zip(PLANE_NAMES, [round(v, 1) for v in f['pix_sigma']])), transient_pixels_replaced=dict(zip(PLANE_NAMES, s2[s]['transient_replaced'])),
                       pixels_at_ceiling=dict(zip(PLANE_NAMES, f['ceiling_pixels']))))
st_sorted = sorted(s3); rot = np.array([s3[s]['rotation_deg'] for s in st_sorted]); sh = np.array([s3[s]['shift_at_centre_px'] for s in st_sorted])
C = np.array([s8['constants'][s] for s in s8['frames']]); n10 = s10['noise_faint_region']; g = s10['galaxy']; d = g['dust_lane']
minutes = (datetime.datetime.fromisoformat(s1['frames'][-1]['t'].replace('Z', '+00:00')) - datetime.datetime.fromisoformat(s1['frames'][0]['t'].replace('Z', '+00:00'))).total_seconds() / 60
hfds = [s4[s]['hfd_arcsec'] for s in used]; smears = [s4[s]['smear'] for s in used]; trans = [s4[s]['transparency'] for s in used]
A8 = s7['against_8_october']; LS = s7['large_scale_remainder_green']
seen = dict(
    galaxy='yes: the edge-on disc, followed %.1f arcmin along its length (%.1f and %.1f arcmin either side of the centre; the catalogue gives 13.5), at the catalogue position angle (the reference-frame check of step 6: %.1f deg off)' % (g['major_axis_profile']['followed_length_arcmin'], *g['major_axis_profile']['followed_to_arcmin_each_side'], abs(s6['angle_difference_deg'])),
    dust_lane='yes: a dark lane down the middle of the disc. Across the centre the green light has two ridges of %.1f and %.1f DN, %.0f arcsec apart, and falls to %.1f DN between them: %.1f DN below the lower ridge, %.0f times the noise of that profile (%.2f DN). The odd and the even frames alone each show it (%.1f and %.1f DN deep).' % (
        d['stack']['ridge_one_dn'], d['stack']['ridge_two_dn'], d['width_between_ridges_arcsec'], d['stack']['dip_dn'], d['stack']['depth_below_lower_ridge_dn'], d['depth_over_noise'], d['profile_noise_dn'], d['odd_frames']['depth_below_lower_ridge_dn'], d['even_frames']['depth_below_lower_ridge_dn']),
    bulge='yes: the bright, warm-coloured middle either side of the lane (the two ridges above); it is the only part bright enough to carry colour',
    structure_in_the_lane='the lane is seen as one dark band that thins towards the ends of the disc; its fine filaments reaching up out of the disc are NOT seen (stars are %.1f arcsec across and the picture is smoothed where it is faint)' % s10['star_size']['hfd_stack_arcsec'],
    halo_and_outer_disc='the faint outer 1.2 arcmin of each end of the disc and the thick halo are NOT seen: 7.5 minutes at f/10 under a suburban sky stops at about 3 times the noise',
    companions='none identified. No companion galaxy was looked up or measured; a few faint smudges in the full field (ngc891-field.jpg) were not checked against a catalogue and are not claimed.')
recipe = dict(
    what='NGC 891, an edge-on spiral galaxy in Andromeda with a dust lane down its middle. %d x 15 s at ISO 3200 (%.1f min), Sony a6000 on a Celestron 8SE (%.0f mm by plate solve, f/10), EQ6-R on a tripod with the polar axis about 5 degrees off, tracking in both axes on a pointing model, night of 12/13 October 2026, the galaxy about 85 degrees up. Stacked from RAW colour planes.' % (len(used), len(used) * 15 / 60, s9['focal_length_mm']),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, tifffile=tifffile.__version__, pillow=PIL.__version__, astrometry_net='solve-field (local index files)',
               note='deterministic array arithmetic only: averages, medians, measured shadows divided out, fixed curves and matrices. Nothing generative, learned or upscaled; no neural denoise or sharpening; no deconvolution.'),
    trial='A TRIAL, not the published picture: hack/stacks/2026-10-12/ngc891 with only the combine step replaced by proper coaddition. The published picture is final/ngc891.*; this one is final-trial/ngc891-coadd.*. The comparison: work/step14_compare.json.',
    scripts='hack/stacks/2026-10-12/ngc891-coadd/ in the observatory repository: run_all.sh runs step1_hot ... step7_flat, step8_coadd, step9_solve ... step12_recipe, step14_compare, then step13_clean. render.py is the colour and stretch, finish16.py the finish-pictures tool reading 16 bits, crop.py the finish-pictures crop tool, solvelib.py the plate solving, fitsmin.py the FITS helper. With no environment variables set it reproduces this run. Adapted from hack/stacks/2026-10-12/m33/.',
    source=dict(folder=STILLS, window=[T0, T1], files_in_window=len(s1['all_in_window']), left_out_before_stacking=s1['left_out'], frames_15s_iso3200_on_target=len(s1['frames']), frames_used=len(used), frames_dropped=len(rej),
                total_exposure_s=len(used) * 15, run_minutes=round(minutes, 1), originals='read in place, never written; nothing cached per frame',
                note='31 frames of 15 s at ISO 3200 were found (30 were expected), all present on this machine when the stack was made; the 2 s ISO 6400 frames in the window are centring pictures and are not stacked'),
    is_it_the_thing=dict(before_stacking=dict(frame=s6['frame'], solved=True, pixel_scale_arcsec=round(s6['pixscale_arcsec'], 4), centre_ra_dec_deg=[round(v, 4) for v in s6['centre_ra_dec']], catalogue_place_px=[round(v, 1) for v in s6['galaxy_ellipse']['centre_px']],
                                              from_frame_centre_arcmin=round(s6['offset_from_frame_centre_arcmin'], 2), green_there_dn=round(s6['green_at_catalogue_place_dn'], 1), green_sky_dn=round(s6['green_sky_median_dn'], 1),
                                              light_centroid_from_catalogue_arcsec=round(s6['light_centroid_from_catalogue_arcsec'], 1), light_long_axis_against_catalogue_position_angle_deg=round(s6['angle_difference_deg'], 2)),
                         verdict='NGC 891: an elongated glow %.1f arcsec from the catalogue place, its long axis %.1f deg from the catalogue position angle of 22 deg' % (s6['light_centroid_from_catalogue_arcsec'], abs(s6['angle_difference_deg']))),
    selection=dict(rule='drop a frame if it is smeared (common-direction ellipticity above %.2f), or its stars are wider than %.2f x the median half-flux diameter, or its stars are below %.0f%% of their usual brightness, or the registration rms is above %.1f px, or it was taken within %.0f s of a move, or it is the first frame after the slew' % (
                       s5['limits']['smear_max'], s5['limits']['hfd_max_rel'], 100 * s5['limits']['transparency_min'], s5['limits']['registration_wrms_max_px'], s5['limits']['since_slew_min_s']),
                   limits=s5['limits'], median_star_half_flux_diameter_arcsec=round(s5['hfd_run_median_arcsec'], 3),
                   story='no frame is trailed (the tracking was fixed at 08:19 UTC, before this run): smear %.2f to %.2f, stars %.2f to %.2f arcsec, every frame within %.1f%% of the run\'s median star brightness. One frame dropped: the first after the slew, by rule (it measured fine).' % (min(smears), max(smears), min(hfds), max(hfds), 100 * max(abs(np.array(trans) - 1))),
                   dropped=[dict(file=[f['name'] for f in s1['frames'] if f['stamp'] == r['stamp']][0], why=r['why']) for r in s5['rejected']],
                   weights='(transparency / noise)^2, noise = the frame\'s zero-level pixel noise over the run median; each used frame also scaled by 1 / transparency', effective_frames=round(s5['effective_frames'], 2)),
    frames=frames,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (6024 x 4024, RGGB), black level 512 subtracted, four colour planes R, G1, G2, B kept apart (3012 x 2012 each), no demosaic. Exposure and ISO from the RAW\'s own EXIF; the run is the frames whose sidecar pointing is within %.1f deg of NGC 891.' % POINTING_RADIUS_DEG),
        dict(step='hot pixels', detail='fixed: per plane, the median without registration of all %d frames of the run (the field wandered by 50 plane px meanwhile); pixels above the 5 x 5 median of that by more than max(6 sigma, 25%% of the level). Transient: per frame, above the 3 x 3 median by more than 8 sigma + 50%% of the level. Both replaced by the 3 x 3 median of the same plane. No darks.' % len(s1['hot_from']),
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s1['hot']}),
        dict(step='stars', detail='green planes averaged; smooth light taken off; detection at 6 sigma of a local noise model; windowed centroids, 14 px aperture flux, second moments, half-flux radius.'),
        dict(step='register', detail='rotation + shift (scale held at 1), weighted least squares on matched stars, 3.5-sigma rejection, frames walked outward in time from the reference %s; the field turned because the polar axis is about 5 degrees off.' % REF_STAMP,
             rotation_deg=dict(first=round(float(rot[0]), 4), last=round(float(rot[-1]), 4), total=round(float(rot[0] - rot[-1]), 4), per_minute=round(float((rot[0] - rot[-1]) / minutes), 4)),
             shift_range_px=dict(x=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], y=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]),
             weighted_rms_px_used_frames=[round(min(s3[s]['wrms_px'] for s in used if s != REF_STAMP), 3), round(max(s3[s]['wrms_px'] for s in used), 3)]),
        dict(step='flat', detail='the night\'s flat, built from this run\'s own open sky (step7_flat.py; rebuilt by this trial in %s, identical to the night\'s flat/). Multiplicative, per colour: a profile 1 + a2 rho^2 + a4 rho^4 + a6 rho^6 with rho^2 = (dx^2 + e dy^2) / 3000^2 fitted to the sky of all %d frames outside the galaxy (stars masked, 8 px block medians, median over frames without registration, a linear sky slope fitted beside it and left out), times a measured dust map (shadows that the first and the second half of the run both show; exactly 1 elsewhere).' % (FLAT_DIR, len(s7['made_from']['frames'])),
             planes={p: {k: v for k, v in s7['planes'][p].items() if k in ('applied_a2_a4_a6', 'applied_e', 'applied_at_long_edge_short_edge_corner', 'fit_rms', 'sky_slope_gx_gy_not_applied', 'radial_only_a2_a4_a6', 'corner_value', 'minus_8_october_max_abs', 'minus_8_october_at_corner')} for p in PLANE_NAMES},
             sky_level_dn=s7['made_from']['sky_level_dn_median'], dust_measured=s7.get('dust_measured'), dust_modelled_for_comparison=dict(shadows=len(s7['dust']['shadows']), deepest=s7['dust']['deepest_applied'], blind_area=s7['dust']['blind_area']),
             against_8_october=dict(what=A8['what'], green_max_abs_difference=round(A8['green_max_abs_difference'], 4), green_rms_difference_inside_2000px=round(A8['green_rms_difference_inside_2000px'], 4), corner_tonight_green=round(A8['corner_tonight_green'], 3), corner_8_october=round(A8['corner_8_october'], 3),
                                    verdict='fitted the same way (plain radial), tonight\'s green profile is the 8 October one within %.1f%% rms inside 2000 px and %.1f%% at the far corner (%.3f against %.3f); blue the same within %.1f%%; red is steeper (corner %.2f), as it was on 8 October. But a plain radial profile leaves a pattern of %.1f%% rms (%.3f to %.3f) in tonight\'s sky; with the fall-off allowed to differ between the sensor\'s long and short sides (e about 1.7) it is %.1f%% rms (%.3f to %.3f). That elliptical profile is the flat.' % (
                                        100 * A8['green_rms_difference_inside_2000px'], 100 * A8['green_max_abs_difference'], A8['corner_tonight_green'], A8['corner_8_october'], 100 * s7['planes']['B']['minus_8_october_max_abs'], s7['planes']['R']['corner_value'],
                                        100 * LS['radial_only']['rms'], LS['radial_only']['min'], LS['radial_only']['max'], 100 * LS['applied_model']['rms'], LS['applied_model']['min'], LS['applied_model']['max'])),
             first_try='a flat with only the 13 modelled disc shadows left a dozen dark streaks (smaller ring-shaped shadows 3 to 5% deep, dragged along the field\'s wander) in the stack; the measured dust map replaced it'),
        dict(step='resample', detail='each plane of each used frame divided by its colour\'s flat and scaled by 1/transparency, then mapped straight onto the reference frame\'s grid of 2 x 2 colour cells (rotation + shift + the plane\'s own place in the cell), OpenCV remap, Lanczos-4. One output pixel per colour cell; nothing enlarged.'),
        dict(step='sky', detail='ONE constant per colour per frame in the stack, nothing else: the 3-sigma clipped mean of the resampled plane over the sky region (the area every used frame covers, outside the galaxy\'s 8.5 x 3.0 arcmin ellipse, the darker %.0f%% of the smoothed reference green), subtracted.' % s8['faint_region']['percentile'],
             sky_region=s8['faint_region'], constants_dn_range={p: [round(float(C[:, i].min()), 2), round(float(C[:, i].max()), 2)] for i, p in enumerate(PLANE_NAMES)},
             note='G1 and G2 see the same sky, yet their constants differ by up to %.1f DN within a frame (rms %.1f DN), and red moves by %.0f DN frame to frame: the camera\'s black level wobbles by a few DN per frame and colour. The constant takes it out at the centre; towards the corners it leaves that wobble times (1 / flat - 1).' % (
                 float(np.max(np.abs(C[:, 1] - C[:, 2]))), float(np.std(C[:, 1] - C[:, 2])), float(C[:, 0].max() - C[:, 0].min()))),
        dict(step='combine', detail='PROPER COADDITION (Zackay & Ofek 2017, ApJ 836, 188; .claude/skills/stack-pictures/tools/coadd.py), per colour plane: each frame filtered with its own measured PSF, weighted by F_j / s_j^2 (F_j = 1: the transparency was divided out when the frame was read; s_j the frame\'s own sky noise), summed, and whitened by sqrt(sum_j |P_hat_j|^2 / s_j^2); the result in the units of one frame, PSF P_R. Delivered: %s. Outliers: a mask (5 sigma per pixel, 4 sigma on a 3 x 3 box, against the per-pixel median of all frames; grown 1 px), flagged pixels filled with what the other frames say that frame saw; linear given the mask. The PSF changes across the field (the optics) but changes the same way in every frame, so one PSF per frame gives the proper weights everywhere.' % s8c['deliver'],
             planes={p: dict(F_R=v['F_R'], psf_R=v['psf_R'], psf_stars=v['psf_stars'], psf_radius_px=v['psf_radius_px'], theory=v['theory'], theory_with_the_control_weights=v['theory_with_the_control_weights'],
                             outliers={k: v['outliers'][k] for k in ('rule', 'kappa', 'beta', 'beta_why', 'kappa_smooth', 'grow_px', 'flagged_fraction', 'flagged_fraction_in_sky_region')},
                             field_variation={k: v['field_variation'][k] for k in ('hfd_spread', 'ellipticity_range', 'varies', 'rule')}, separable=v['separable'], halves=v['halves'],
                             frames=[dict(stamp=f['stamp'], noise=round(f['noise'], 3), share_of_point_source_snr2=round(f['share_of_point_source_snr2'], 4), pixels_filled=f['pixels_filled'], psf_hfd_px=f['psf']['hfd_px'], psf_ellipticity=f['psf']['ellipticity']) for f in v['frames']])
                     for p, v in s8c['planes'].items()},
             control='the delivered combine (3-sigma clips about the median and the weighted mean, then the weighted mean) made from the same cube as control_*.npy: dropped fraction %s' % {p['plane']: round(p['dropped_fraction'], 5) for p in s8['planes']},
             tool=s8c['planes']['G1']['tool'], paper=s8c['planes']['G1']['paper']),
        dict(step='full field', detail='the largest rectangle in which every pixel has at least %d of the %d frames: x %d..%d, y %d..%d of the reference grid, %d x %d px' % (s9['crop_on_reference_grid']['cover_min_frames'], len(used), s9['crop_on_reference_grid']['x0'], s9['crop_on_reference_grid']['x1'], s9['crop_on_reference_grid']['y0'], s9['crop_on_reference_grid']['y1'], s9['crop_on_reference_grid']['width'], s9['crop_on_reference_grid']['height'])),
        dict(step='plate solve', detail='astrometry.net (local) on the stack\'s green: solved; the light at NGC 891\'s catalogue place has its centroid %.1f arcsec from it' % s9['catalogue'][TARGET['name']]['offset_arcsec'], pixel_scale_arcsec=round(s9['pixscale_arcsec'], 4), focal_length_mm=round(s9['focal_length_mm'], 1),
             field_arcmin=[round(v, 2) for v in s9['field_arcmin']], centre_ra_dec_deg=[round(v, 5) for v in s9['centre_ra_dec']], catalogue_check=s9['catalogue'], wcs_header=s9['wcs_header'],
             orientation='as the camera saw it, not mirrored, not turned (a turn would resample the picture): north points %.0f deg anticlockwise from up, east %.0f deg anticlockwise from up' % (-s9['north_angle_from_up_deg_clockwise'], -s9['east_angle_from_up_deg_clockwise'])),
        dict(step='sky plane, in the picture only', detail='a plane a + b x + c y per colour, fitted to the stack\'s sky far from the galaxy (the sky region; 64 px block medians, 3-sigma clipped) and subtracted before the stretch. Not in ngc891-stack.tif. It is the sky\'s own slope (and the black-level wobble over the flat); the flat\'s fit found the same slope.', planes=s10['sky_plane_in_the_picture_only']),
        dict(step='colour and stretch', detail=render.__doc__.strip(), white_balance_daylight=s10['white_balance_daylight'], camera_to_srgb=s10['rgb_cam'], parameters=s10['render_params'],
             luminance_weights=s10['render_info']['luminance_weights'], colour_shown_on_fraction_of_picture=round(s10['render_info']['colour_shown_fraction'], 4), stars_at_ceiling_px=s10['render_info']['ceiling_pixels']),
        dict(step='crop', detail='crop.py (the finish-pictures tool), before the levels', recipe=crop, on_the_full_field=s9['galaxy_crop'], crop_arcmin=[round(crop['crop_px'][2] * s9['pixscale_arcsec'] / 60, 1), round(crop['crop_px'][3] * s9['pixscale_arcsec'] / 60, 1)]),
        dict(step='finish', detail='finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch at full depth), one line in step11_finish.sh; the same options for the full field', recipe=fin, recipe_full_field=finf,
             skycheck=skycheck(os.path.join(FINAL, NAME + '.png')), skycheck_full_field=skycheck(os.path.join(OUT, NAME + '-field.png')),
             tried='black-pct 50 with a 5 px median and sat 1.3 (sky mottled, outer disc in daubs, the bulge a hard orange patch; colour ramp then 6 to 18 DN); black-pct 65 with a 3 px median (11% of the picture exactly black, grainier disc); kept black-pct 60, no median, sat 1.15, colour ramp 3 to 14 DN'),
    ],
    numbers=dict(noise=dict(units=n10['units'], planes_single=n10['planes_single'], planes_stack=n10['planes_stack'], improvement=n10['improvement'], ideal_for_these_weights=n10['ideal'], odd_even_half_difference=n10['planes_half_difference_odd_even'], luminance=n10['luminance'], green_mean_of_two=n10['green_mean_of_two']),
                 star_half_flux_diameter=dict(stack_px=round(s10['star_size']['hfd_stack_px'], 2), stack_arcsec=round(s10['star_size']['hfd_stack_arcsec'], 2), single_px=round(s10['star_size']['hfd_single_px'], 2), single_arcsec=round(s10['star_size']['hfd_single_arcsec'], 2), stars=s10['star_size']['stars'],
                                              note='green, 14 px aperture, compact unsaturated isolated stars, on the linear stack (before the %.1f px blur of the picture)' % s10['render_params']['LUM_BLUR']),
                 galaxy=g),
    what_is_seen=seen,
    outputs={NAME + '-stack.tif': s10['tif'],
             'final-trial/' + NAME + '.png': dict(what='the finished picture: a %d x %d px cut around the galaxy at the stack\'s own scale, 8-bit' % (ww, hh), size_px=[ww, hh], pixel_scale_arcsec=s9['pixscale_arcsec'], metadata='none'),
             'final-trial/' + NAME + '.jpg': dict(what='the same as a JPEG (quality 93); also copied to ngc891-coadd/ngc891-coadd.jpg', markers=mk, metadata='none'),
             'final-trial/' + NAME + '.json': 'the finish recipe written by finish16.py',
             NAME + '-field.png, .jpg, .json': dict(what='the full well-covered field finished with the same options', size_px=[fw, fh])},
    caveats=[
        'Short: %.1f minutes in all. The outer disc and halo are below the noise; the picture is smoothed where it is faint (bilateral filter in the finish), so the faint ends of the disc are soft.' % (len(used) * 15 / 60),
        'Colour is shown only where the light is bright enough to carry it (%.1f%% of the picture: stars and the galaxy\'s middle; the ramp is %.0f to %.0f DN). The ends of the disc are grey on purpose.' % (100 * s10['render_info']['colour_shown_fraction'], s10['render_params']['COLOUR_FROM'], s10['render_params']['COLOUR_FULL']),
        'White stars come out faintly green: camera daylight white balance and the camera\'s own matrix, with no star-colour calibration. The same in tonight\'s M33 and on 8 October.',
        'The flat was made from these same frames. The galaxy itself (a 7 x 1 arcmin ellipse) hid the sensor under it: dust there could not be measured or divided out. Shallow dust rings under 2% deep are not in the flat either; dragged along the field\'s wander they are under 1.5 DN in a sky whose noise is 1.5 DN after the picture\'s blur, and the black point hides them.',
        'The red plane\'s flat is steeper than green\'s; that may be a constant of a few DN in red and not the optics (see flat/README.txt). At the galaxy (the middle of the sensor, flat above 0.97) it does not matter; red stars near the corners of the full field may be up to 10% too red.',
        'No darks: hot pixels from the run itself. The sky plane is in the picture only.',
        'About 1% of the picture, the darkest sky, is exactly black: the black point was raised for a quiet sky.',
        'The frame is in the camera\'s orientation, not north-up.'])
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('recipe.json: %d frames (%d used, %d dropped), %.1f min; stars %.2f arcsec in the stack' % (len(frames), len(used), len(rej), len(used) * 15 / 60, s10['star_size']['hfd_stack_arcsec']))
for k, v in seen.items(): print('  %s: %s' % (k, v))
print(NAME + '.jpg markers', mk, '| sky', recipe['steps'][-1]['skycheck'])
