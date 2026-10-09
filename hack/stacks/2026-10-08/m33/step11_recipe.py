"""Step 11: recipe.json beside the pictures: every number that shaped them, which frames, why the others were dropped,
the flat, the sky constants and how uncertain they are, the registration, the weights, the stretch, the versions."""
import json, os, platform, datetime
import numpy as np, cv2, scipy, rawpy, tifffile, PIL
from common import *
import render

s1 = jload('step1.json'); s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s4 = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s5 = jload('step5_select.json'); s6 = jload('step6_vignette.json'); s7 = jload('step7_stack.json'); s8 = jload('step8_solve.json'); s9 = jload('step9_deliver.json'); s10 = jload('step10_decon.json'); s9b = jload('step9b_checks.json')
used = {u['stamp']: u for u in s5['used']}; rej = {r['stamp']: r for r in s5['rejected']}
frames = []
for f in s1['frames']:
    s = f['stamp']; t = s3[s]; q = s4[s]
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'], seconds_since_last_slew=f['since_slew_s'],
                       used=s in used, why_dropped=rej[s]['why'] if s in rej else None, weight=round(used[s]['weight'], 4) if s in used else 0.0,
                       transparency=round(q['transparency'], 4), star_half_flux_diameter_arcsec=round(q['hfd_arcsec'], 3), box_star_size_arcsec=f['box_star_size_arcsec'],
                       elongation_median=round(q['elong_median'], 3), smear_common_ellipticity=round(q['smear'], 3), smear_angle_deg=round(q['smear_angle_deg'], 1),
                       registration=dict(rotation_deg=round(t['rotation_deg'], 4), shift_at_sensor_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], stars_used=t['used'], weighted_rms_px=round(t['wrms_px'], 3),
                                         scale_if_left_free=round(t['similarity_scale'], 5), found_by_coarse_vote=bool(t.get('coarse_vote', False)), R=t['R'], t=t['t']),
                       sky_constant_dn=dict(zip(PLANE_NAMES, [round(v, 2) for v in s7['constants'][s]])) if s in used else None,
                       black_level=f['black'], white_balance_as_shot=f['wb'], hot_pixels_fixed=f['fixed_hot_replaced'], transient_pixels_replaced=dict(zip(PLANE_NAMES, f['transient_replaced'])),
                       pixels_at_ceiling=dict(zip(PLANE_NAMES, f['ceiling_pixels']))))
sh = np.array([s3[s]['shift_at_centre_px'] for s in sorted(s3)]); rot = np.array([s3[s]['rotation_deg'] for s in sorted(s3)])
C = np.array([s7['constants'][s] for s in s7['frames']])
n9 = s9['noise_faint_region']
recipe = dict(
    what='M33, the Triangulum Galaxy: core and inner arms. %d x 15 s at ISO 3200 (%.2f min), Sony a6000 on a Celestron 8SE (2,083 mm by plate solve, f/10), EQ6-R tracking on a pointing model, night of 8/9 October 2026. Stacked from RAW colour planes.' % (len(used), len(used) * 15 / 60),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, tifffile=tifffile.__version__, pillow=PIL.__version__, astrometry_net='solve-field (local Tycho-2 index files 4107-4115)',
               note='deterministic array arithmetic only: averages, medians, measured blurs, fixed curves and matrices. Nothing generative, learned or upscaled; no neural denoise or sharpening.'),
    scripts='hack/stacks/2026-10-08/m33/ in the observatory repository: run_all.sh runs step1_hot ... step11_recipe, then step12_clean; render.py is the finish, fitsmin.py the FITS helper. With no environment variables set it reproduces this run.',
    source=dict(folder=STILLS, window=[T0, T1], files_in_window=len(s1['all_in_window']), left_out_before_stacking=s1['left_out'], frames_15s_iso3200=len(s1['frames']), frames_used=len(used),
                frames_dropped=[dict(file=[f['name'] for f in s1['frames'] if f['stamp'] == r['stamp']][0], why=r['why']) for r in s5['rejected']], originals='read in place, never written'),
    selection=dict(rule='drop a frame if its stars are wider than %.2f x the run median half-flux diameter, or smeared (common-direction ellipticity above %.2f: every star stretched the same way, the mount moving during the exposure), or its stars are below %.0f%% of their usual brightness, or the registration rms is above %.1f px' % (s5['limits']['hfd_max_rel'], s5['limits']['smear_max'], 100 * s5['limits']['transparency_min'], s5['limits']['registration_wrms_max_px']),
                   run_median_star_half_flux_diameter_arcsec=round(s5['hfd_run_median_arcsec'], 3), weights='(transparency / noise)^2, noise = the frame\'s zero-level pixel noise over the run median; each used frame also scaled by 1 / transparency',
                   effective_frames=round(s5['effective_frames'], 2), night='clear: every frame except the smeared 0657 one within 2% of the run\'s median star brightness',
                   smeared_frames_story='0657:25 was taken while the mount was nudged (the field jumped 185 px before the next frame; its stars are 2 to 1 long). 0659:12 and 0659:49 drifted about 31 px each between frames and are smeared in the same direction. 0655:39 to 0656:49 sit about 280 px from the rest (before the nudge) and are sharp, so they are used.'),
    frames=frames,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (6024 x 4024, RGGB), black level 512 subtracted, four colour planes R, G1, G2, B kept apart (3012 x 2012 each), no demosaic. Exposure and ISO from the RAW\'s own EXIF.'),
        dict(step='hot pixels', detail='fixed: per plane, the median of all 24 frames without registration; pixels above the 5 x 5 median of that by more than max(6 sigma, 25% of the level). Transient: per frame, above the 3 x 3 median by more than 8 sigma + 50% of the level. Both replaced by the 3 x 3 median of the same colour plane. No darks were taken; this stands in for them.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s1['hot']}),
        dict(step='stars', detail='green planes averaged; the galaxy\'s smooth light (1/8-scale block mean, 5 x 5 median, Gaussian 2, grown back) taken off; detection at 6 sigma of a local noise model; windowed centroids, 14 px aperture flux, second moments, half-flux radius (hack/stacks/2026-10-03/m31 method).'),
        dict(step='register', detail='rotation + shift (scale held at 1; left free it comes out within 0.0002 of 1), weighted least squares on matched stars, 3.5-sigma rejection, frames walked outward in time from the reference %s; two frames needed a coarse pair-offset vote first (the nudge).' % REF_STAMP,
             rotation_deg=dict(first=round(float(rot[0]), 4), last=round(float(rot[-1]), 4), total=round(float(rot[0] - rot[-1]), 4), per_minute=round(float((rot[0] - rot[-1]) / 13.6), 4)),
             shift_range_px=dict(x=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], y=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]),
             rms_px=[round(min(s3[s]['wrms_px'] for s in s3 if s != REF_STAMP), 3), round(max(s3[s]['wrms_px'] for s in s3), 3)]),
        dict(step='flat', detail='no flat frames. Measured from the same night\'s open-sky runs at the same exposure and ISO, one before M33 (M57, 0602-0621) and one after (NGC 1514, 0738-0752): stars masked, each frame over its own sky, 8 px block medians, median over frames. (1) Vignetting: centred radial polynomial fitted jointly to both runs (each with its own sky slope, which is not applied); one profile, the mean of the two green fits, for all four planes (the faint red and blue sky made their own fits disagree between runs by up to 18% and 4%). (2) Dust: the shadows both runs see alike are each fitted with a round flat-bottomed model and divided out; elsewhere the dust map is exactly 1.',
             vignetting_profile=dict(r_sensor_px=s6['profile_r_sensor_px'][::4], value=[round(v, 4) for v in s6['profile_applied'][::4]], corner=round(s6['profile_applied_corner'], 4),
                                     green_runs_agree_within=round(max(s6['planes']['G1']['runs_alone_differ_max'], s6['planes']['G2']['runs_alone_differ_max']), 3),
                                     per_colour_corner_values={k: round(v['corner_value'], 3) for k, v in s6['planes'].items()}, sky_slopes_of_the_flat_runs={k: v['per_run'] for k, v in s6['planes'].items() if k == 'G1'}),
             dust_shadows=[dict(plane_px=d['plane_px'], depth=d['depth'], radius_plane_px=d['radius_plane_px'], depth_each_run=[d['depth_m57'], d['depth_ngc1514']], depth_seen_in_m33_frames=d['depth_in_m33_frames']) for d in s6['dust']['shadows']],
             dust_check=dict(depth_in_m33_frames_over_depth_in_flats_median=round(float(np.median([d['depth_in_m33_frames'] / d['depth'] for d in s6['dust']['shadows']])), 3),
                             left_in_stack=[dict(picture_px=d['picture_px'], depth_divided_out=d['depth_divided_out'], centre_left_dn=d['centre_left_dn'], rings_0_to_80px_dn=d['left_in_stack_green_dn_rings_0_to_80px']) for d in s9b['dust']],
                             note='what is left of each shadow in the stack\'s green (median in 8 px rings, minus the ring at 72-80 px); the noise of a ring average is about 0.5 to 1 DN, and galaxy structure adds to it')),
        dict(step='resample', detail='each plane of each used frame divided by the flat and scaled by 1/transparency, then mapped straight onto the reference frame\'s grid of 2 x 2 colour cells (rotation + shift + the plane\'s own place in the cell), OpenCV remap, Lanczos-4. One output pixel per colour cell: nothing enlarged.'),
        dict(step='sky', detail='ONE constant per colour per frame, nothing else: the 3-sigma clipped mean of the resampled plane over the faint region, subtracted. The faint region is the darkest 5% (of the green, smoothed over about 50 px) of the area every used frame covers, on the reference frame: strips along the top and bottom edges of the picture, the galaxy\'s minor axis, about 12 arcmin from the nucleus. The same pixels for every frame and colour, so that region is zero and neutral by construction. No surface was fitted: the galaxy fills the frame.',
             faint_region=s7['faint_region'], constants_dn_range={p: [round(float(C[:, i].min()), 2), round(float(C[:, i].max()), 2)] for i, p in enumerate(PLANE_NAMES)},
             constants_dn_weighted_mean={p: round(float((C[:, i] * np.array([used[s]['weight'] for s in s7['frames']])).sum() / sum(used[s]['weight'] for s in s7['frames'])), 2) for i, p in enumerate(PLANE_NAMES)},
             uncertainty=dict(
                 statistical='under 0.1 DN per constant (270,000 pixels)',
                 frame_to_frame='the constants spread over %s DN (R, G1, G2, B) between frames, by similar amounts in DN in all four planes although the sky is 3 to 4 times fainter in red than in green, and G1 - G2 moves by %.1f..%.1f DN: an additive offset in the camera\'s read-out, removed frame by frame by the constant' % ('/'.join('%.0f' % s9b['constants'][p]['spread'] for p in PLANE_NAMES), *s9b['constants']['G1_minus_G2']['range']),
                 galaxy_in_the_faint_region='unknown and not zero: M33\'s disk reaches well beyond this 38 x 26 arcmin field, so the stack\'s zero is the galaxy\'s faintest level in the field, not the true sky. These frames cannot say how much galaxy light was subtracted with the sky (for scale: the subtracted constant is about 97 DN in green, the galaxy\'s light above it 3 to 20 DN in the outer parts of the picture).',
                 flat='the two flat runs\' green profiles differ by up to 3% at the edges: with about 97 DN of sky (+ galaxy) divided by the profile, that is up to about 3 DN at the edges of the picture, as much as the faint outer glow there',
                 sky_slope='not removed (one constant only). The open-sky runs had slopes of 2.4% (NGC 1514, altitude 47 deg) and 18% (M57, altitude 37 deg, in the Milky Way) of their sky across 3000 px; M33 was at 69 to 72 deg, where a slope of 1 to 2% would be 1 to 2 DN across the picture',
                 black_offset='an additive offset common to all frames (true black not exactly 512) cannot be measured without darks; it would be divided by the flat and leave up to 0.36 x that offset at the extreme corners; the agreement of the two flat runs (sky 49 and 122 DN) limits it to a few DN',
                 colour=dict(note='the faint glow\'s colour depends on the flat in each colour (camera RGB, daylight balance; R/G and B/G in rings around the nucleus, as stacked and with per-colour profiles). Beyond a few arcmin the choice moves R/G by 0.2 or more, so colour is shown only where the light is bright enough to carry it (render step 2); the rest is grey.', rings=s9b['colour']),
                 verdict='the core, the inner arms, the dust lanes and the HII regions (10 to 200+ DN) are well measured; the outermost glow along the picture\'s left and right edges (3 to 8 DN) is real in kind (M33\'s disk continues there along its major axis) but its exact brightness is uncertain by a few DN')),
        dict(step='combine', detail='per pixel and plane: values further than 3 sigma from the median dropped (sigma = 1.4826 x MAD across frames, floor 0.4 x the single-frame noise, widened by each frame\'s noise factor), then 3 sigma about the weighted mean of the survivors, then the weighted mean (hack/stacks/2026-10-03/m31/step8_stack.py).',
             dropped_fraction={p['plane']: round(p['dropped_fraction'], 5) for p in s7['planes']}),
        dict(step='crop', detail='the largest rectangle in which every pixel has at least %d of the %d frames (the three early frames sit 280 px off): x %d..%d, y %d..%d of the reference grid, %d x %d px' % (s8['crop_on_reference_grid']['cover_min_frames'], len(used), s8['crop_on_reference_grid']['x0'], s8['crop_on_reference_grid']['x1'], s8['crop_on_reference_grid']['y0'], s8['crop_on_reference_grid']['y1'], s8['crop_on_reference_grid']['width'], s8['crop_on_reference_grid']['height'])),
        dict(step='plate solve', detail='astrometry.net on the stack\'s green: solved', pixel_scale_arcsec=round(s8['pixscale_arcsec'], 4), focal_length_mm=round(s8['focal_length_mm'], 1), field_arcmin=[round(v, 2) for v in s8['field_arcmin']],
             centre_ra_dec_deg=[round(v, 5) for v in s8['centre_ra_dec']], catalogue_check=s8['catalogue'],
             orientation='as the camera saw it, not mirrored; north points %.0f deg anticlockwise from up (up and to the left), east %.0f deg anticlockwise from up (down, slightly left). Not turned: a turn would resample the picture. M33\'s long axis runs left to right.' % (-s8['north_angle_from_up_deg_clockwise'], -s8['east_angle_from_up_deg_clockwise'])),
        dict(step='colour and finish', detail=render.__doc__.strip(), white_balance_daylight=s9['white_balance_daylight'], white_balance_as_shot_median=s9['as_shot_white_balance_median'], camera_to_srgb=s9['rgb_cam'],
             parameters=s9['render_params'], luminance_weights=s9['render_info']['luminance_weights'], colour_shown_on_fraction_of_picture=round(s9['render_info']['colour_shown_fraction'], 4),
             stars_at_ceiling_px=s9['render_info']['ceiling_pixels'], white_clipped_pct=round(s9['render_info']['white_clipped_pct'], 4), black_clipped_pct=round(s9['render_info']['black_clipped_pct'], 4),
             skycheck=s9['jpg']['native']['skycheck']),
    ],
    numbers=dict(
        noise=dict(units='DN per stack pixel in the faint region, 3-sigma clipped std; single frame = the reference frame %s through the same hot-pixel repair, flat, resampling and constant' % REF_STAMP,
                   planes_single={k: round(v, 2) for k, v in n9['planes_single'].items()}, planes_stack={k: round(v, 2) for k, v in n9['planes_stack'].items()}, improvement=n9['improvement'], ideal_for_these_weights=n9['ideal'],
                   odd_even_half_difference={k: round(v, 2) for k, v in n9['planes_half_difference_odd_even'].items()},
                   luminance={k: round(v, 2) for k, v in n9['luminance'].items()}),
        star_half_flux_diameter=dict(stack_px=round(s9['star_size']['hfd_stack_px'], 2), stack_arcsec=round(s9['star_size']['hfd_stack_arcsec'], 2), single_px=round(s9['star_size']['hfd_single_px'], 2), single_arcsec=round(s9['star_size']['hfd_single_arcsec'], 2),
                                     stars=s9['star_size']['stars'], note='green, 14 px aperture, compact unsaturated isolated stars; the box\'s own star-size readout (a different measure on the JPEG) said 4.8 to 5.4 arcsec on the used frames'),
        galaxy_green_profile=s9['galaxy_green_profile']),
    outputs={
        'm33-stack.tif': s9['tif'],
        'm33.jpg': dict(what='the finished picture at the stack\'s own scale', **s9['jpg']['native'], metadata='none'),
        'm33-1600.jpg': dict(what='the same, area-averaged to 1600 px wide', **s9['jpg']['w1600'], metadata='none'),
    },
    deconvolution=dict(delivered=s10['delivered'], blur='measured from %d compact unsaturated isolated stars in the stack\'s luminance (half-flux diameter %.2f px)' % (s10['psf_stars'], s10['psf_hfd_px']),
                       trials=[dict((k, v) for k, v in t.items() if k != 'moats_dn') for t in s10['trials']], plain=dict((k, v) for k, v in s10['plain'].items() if k != 'moats_dn'), verdict=s10['verdict']),
    what_it_shows='the nucleus (found 1.5 arcsec from its catalogue place) in a yellowish core, the inner spiral arms with their dark dust lanes, many star clusters and HII regions along the arms, NGC 604 (the large HII region, left of centre, blue-violet) and NGC 595 and NGC 592 at their catalogue places, and the disk\'s glow running out to the left and right edges along the galaxy\'s long axis. Stars are about 3.9 arcsec across (half-flux diameter).',
    caveats=[
        'Short: 5.25 minutes in all at f/10 on a low-surface-brightness galaxy. Per pixel the stack has a signal-to-noise of about 2 at 2 arcmin from the nucleus and below 1 beyond 10 arcmin; the picture trades faint detail for a quiet sky (1 px Gaussian on brightness, 2 px in the dark parts).',
        'Colour is shown only where the light is bright enough to carry it (about 0.5% of the picture: stars, the core, the brightest HII regions). The disk is shown grey on purpose: its colour in these frames is set by the flat and the sky handling, not measured (see steps / sky / uncertainty / colour).',
        'The stack\'s zero is the galaxy\'s faintest level in the field, not the true sky (see steps / sky / uncertainty).',
        'No dark frames and no flat frames: hot pixels from the run itself; flat from the same night\'s open-sky runs. Ten dust shadows were divided out; what is left at their centres is %s DN (stack green), the worst the one cut by the top edge of the sensor (picture x about %d, y about %d) and the broad faint one at picture x about %d, y about %d.' % (', '.join('%+.1f' % d['centre_left_dn'] for d in s9b['dust']), s9b['dust'][1]['picture_px'][0], s9b['dust'][1]['picture_px'][1], s9b['dust'][-1]['picture_px'][0], s9b['dust'][-1]['picture_px'][1]),
        'Stars that touched the sensor\'s ceiling are shown white; the brightest one, near the right edge, keeps a faint violet and yellow-green fringe in its halo (colour of the optics at the field edge; not corrected).',
        'The frame is in the camera\'s orientation, not north-up (north is up-left).',
    ],
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('recipe written:', os.path.join(OUT, 'recipe.json'), '%d frames listed, %d used' % (len(frames), len(used)))
