"""Step 13: the recipe. Everything that was done, with the numbers each step produced, in one JSON beside the
pictures; and the scripts themselves copied next to it."""
import json, os, sys, glob, shutil, datetime, subprocess
import numpy as np, cv2, scipy, rawpy, tifffile, PIL
from c import *

J = lambda n: json.load(open(W(n)))
p1 = J('p1.json'); p2 = J('p2.json'); hair = J('p2b_hair.json'); p4 = J('p4_transforms.json'); p5 = J('p5_select.json'); p7 = J('p7_solve.json'); p8 = J('p8_place.json'); p9 = J('p9_resample.json')
p10 = J('p10_background.json'); p11 = J('p11_combine.json'); p12 = J('p12_deliver.json'); gl = J('p12b_glare.json'); p6 = {k: J('p6_%s.json' % k) for k in PANELS}
p3 = J('p3_stars.json'); dk = J('p10b_dark_check.json'); tw = J('p12c_seen_twice.json')
nstars = [len(r['stars']) for r in p3]
reg = [o for k in PANELS for o in p4[k]['transforms'] if not o.get('failed') and o['wrms_px'] > 0.01]
surf_rng = {True: [], False: []}
for k in PANELS:
    for s_, pl in p6[k]['surfaces_taken_off'].items():
        g1 = pl[1]
        if not g1.get('reference'): surf_rng[k in CLOUD].append(g1['surface_min_max_dn'][1] - g1['surface_min_max_dn'][0])
hc = {k: hair[k]['centre_sensor_px'] for k in PANELS}; ha = {k: hair[k]['angle_deg'] for k in PANELS}
sat2 = np.load(W('deliver_sat2.npy')); n_sat_stars = cv2.connectedComponents(sat2.astype(np.uint8), connectivity=8)[0] - 1
LABEL = dict(c='centre check', p00a='(0,0) first try', p00='(0,0) retake', p10='(1,0)', p20='(2,0)', p21='(2,1)', p11='(1,1)', p01='(0,1)', p02='(0,2)', p12='(1,2)', p22='(2,2)')
plan = {n: (e, nn) for n, e, nn in PLAN}
K = p10['models']['K']; A_ = p10['models']['A']; B_ = p10['models']['B']; E_ = p10['models']['E']; G_ = p10['models']['G']
MULT = p8['photometric_multipliers']
frames_by = {f['stamp']: f for f in p1['frames']}
r2 = lambda v, n=2: None if v is None else round(float(v), n)

panels = []
for k in PANELS:
    sel = p5[k]; cat = p8['catalogue_after_joint_solve'][k]; s7 = p7[k]; c_ = cat['centre_offset_arcmin_east_north']
    used = {u['stamp']: u for u in sel['used']}; rej = {r['stamp']: r for r in sel['rejected']}; qual = {q['stamp']: q for q in sel['quality']}
    fr = []
    for f in [f for f in p1['frames'] if f['panel'] == k]:
        s = f['stamp']; q = qual.get(s, {}); t4 = next(o for o in p4[k]['transforms'] if o['stamp'] == s)
        d = dict(frame=f['name'], shutter_utc=f['t'], altitude_deg=r2(f['alt_deg'], 1), sky_green_dn_top_left_corner=r2(f['corner_green'], 1), noise_green_dn=r2(f['corner'][1]['clipped_std'], 1),
                 transparency_against_the_panels_clear_frames=r2(q.get('flux_rel'), 3), stars_measured=q.get('stars_matched'), star_width_hfd_arcsec=r2(q.get('hfd_arcsec')), elongation=r2(q.get('elong_median')),
                 shift_px=[r2(v, 1) for v in t4.get('shift_at_centre_px', [None, None])], turn_deg=r2(t4.get('rotation_deg'), 4), registration_rms_px=r2(t4.get('wrms_px')), arw_sha256=f['arw_sha256'])
        if s in used:
            d.update(used=True, weight=r2(used[s]['weight']), scaled_by=r2(used[s]['scale'], 3)); 
            if used[s].get('below_the_limits'): d['note'] = used[s]['below_the_limits']
            if s == sel['background_reference']: d['role'] = 'clearest frame of the panel: the other frames are brought to its background'
        else:
            d.update(used=False, why=rej[s]['why'])
        fr.append(d)
    n6 = p6[k]['noise_of_stack_dn_per_half_grid_px']
    panels.append(dict(stack=k, panel=LABEL[k], taken_utc=[sel['used'][0]['stamp'][9:] if False else [f for f in p1['frames'] if f['panel'] == k][0]['stamp'][9:], [f for f in p1['frames'] if f['panel'] == k][-1]['stamp'][9:]],
                       frames_found=sel['frames_found'], frames_used=sel['frames_used'], exposure_used_s=sel['frames_used'] * EXPOSURE_S, through_cloud=k in CLOUD,
                       planned_offset_arcmin_east_north=list(plan[k]), solved_centre_offset_arcmin_east_north=[r2(c_[0]), r2(c_[1])], centre_ra_dec_j2000=[r2(v, 4) for v in ungnomonic(c_[0] * 60, c_[1] * 60)],
                       off_the_plan_by_arcmin=r2(np.hypot(c_[0] - plan[k][0], c_[1] - plan[k][1])), x_axis_deg_south_of_west=r2(cat['x_axis_deg_south_of_west']), scale_arcsec_per_sensor_px=r2(np.mean(cat['scale_arcsec_per_half_px']) / 2, 5),
                       catalogue_stars_fitted=cat['stars'], catalogue_rms_arcsec=r2(cat['rms_arcsec']),
                       photometric_multiplier_green=r2(MULT['G'][k], 4), multiplier_red_blue_as_a_check=[r2(MULT['R'][k], 4), r2(MULT['B'][k], 4)], transparency_against_the_clearest_stack=r2(1 / MULT['G'][k], 3),
                       stack_noise_dn_per_half_grid_px=dict(R=r2(n6['R'], 1), G1=r2(n6['G1'], 1), G2=r2(n6['G2'], 1), B=r2(n6['B'], 1)), noise_green_in_common_units_dn_per_fine_px=r2(p9[k]['noise_green_per_fine_px_common_units']['median_inside_the_feather'], 1),
                       sky_level_of_the_stack_dn=dict(zip(PLANE_NAMES, [r2(v, 1) for v in p6[k]['level_in_faintest_quarter_dn'].values()])),
                       samples_dropped_by_the_clip_fraction_green=r2(p6[k]['planes'][1]['fraction_dropped_by_the_clip'], 4), spikes_repaired_per_frame=p6[k]['spikes_repaired'], pixels_at_the_ceiling=p6[k]['pixels_at_the_ceiling_in_any_frame'],
                       hair_centre_sensor_px=[round(v) for v in hair[k]['centre_sensor_px']], hair_angle_deg=round(hair[k]['angle_deg']), hair_circle_filled_by_other_stacks=p12['holes']['hair_circles'][k]['fraction_of_the_circle_filled_by_other_stacks'],
                       background_constant_dn=dict(R=r2(K['R']['solution'][k][0]), G=r2(K['G']['solution'][k][0]), B=r2(K['B']['solution'][k][0])), frames=fr))
total_found = sum(p['frames_found'] for p in panels); total_used = sum(p['frames_used'] for p in panels)

overlaps = []
for key, a in p8['overlaps_after_joint_solve'].items():
    b = p8['overlaps_plate_solutions_alone'].get(key); ph = p8['photometric_pairs']['G'].get(key); bg = {c_: K[c_]['pairs'].get(key) for c_ in 'RGB'}; x, y = key.split('-')
    overlaps.append(dict(pair='%s | %s' % (LABEL[x], LABEL[y]), stacks=key, with_a_cloud_stack=x in CLOUD or y in CLOUD,
                         shared_stars=a['shared_stars'], star_position_rms_arcsec=dict(plate_solutions_alone=r2(b['rms_arcsec']) if b else None, after_the_joint_solve=r2(a['rms_arcsec'])), mean_offset_after_arcsec_east_north=[r2(v) for v in a['mean_offset_arcsec']],
                         photometry=None if ph is None else dict(stars=ph['stars'], flux_ratio_measured=r2(ph['flux_ratio_b_over_a_weighted'], 4), left_after_the_multipliers=r2(ph['after_scaling_weighted'], 4), error=r2(ph['error_of_that'], 4)),
                         background_green=None if bg['G'] is None else dict(blocks=bg['G']['blocks'], faint_blocks=bg['G']['faint_blocks'], mean_residual_dn=r2(bg['G']['mean_residual_dn']), rms_residual_dn=r2(bg['G']['rms_residual_faint_dn']), noise_alone_dn=r2(bg['G']['expected_noise_rms_faint_dn']),
                                                                         slope_dn_per_1000px=None if not bg['G']['slope'] else dict(along=r2(bg['G']['slope']['dn_per_1000px_along']), across=r2(bg['G']['slope']['dn_per_1000px_across']))),
                         background_mean_residual_red_blue_dn=[r2(bg['R']['mean_residual_dn']) if bg['R'] else None, r2(bg['B']['mean_residual_dn']) if bg['B'] else None]))

def model_row(M): return {c_: dict(rms_clear_pairs_dn=r2(M[c_]['rms_residual_faint_dn_clear_pairs']), rms_pairs_with_a_cloud_stack_dn=r2(M[c_]['rms_residual_faint_dn_pairs_with_a_cloud_stack']), noise_alone_dn=r2(M[c_]['expected_noise_rms_dn_clear_pairs'])) for c_ in 'RGB'}
pattern = {c_: {t['term']: [r2(t['value']), r2(t['sigma'])] for t in K[c_]['sensor_pattern_raw_dn']} for c_ in 'RGB'}

stars = {}
for nm, s in p12['named_stars'].items():
    g = gl['stars'][nm]; rings = []
    for rg in g['rings']:
        if rg['mean_of_sectors_dn'] is None: continue
        rings.append(dict(ring_arcmin=rg['ring_arcmin'], green_dn=r2(rg['mean_of_sectors_dn'], 1), brightest_minus_faintest_sector_dn=r2(rg['brightest_minus_faintest_sector_dn'], 1), brightest_sector=rg['brightest_sector'],
                          scaled_to_merope_magnitude_dn=r2(rg['level_scaled_to_merope_magnitude_dn'], 1), glare_upper_limit_dn=r2(rg['glare_upper_limit_dn'], 1), above_the_glare_limit_dn=r2(rg['above_glare_limit_dn'], 1), b_over_g=r2(rg['b_over_g']), r_over_g=r2(rg['r_over_g'])))
    cloud = (s['cloud_stack_share'] or 0) > 0.5
    reading = dict(Merope='REAL NEBULOSITY beyond about 1 arcmin: 2 to 3 times more light per unit of star light than Alcyone has (at least 60 to 70% of it cannot be glare), brightest to the south in every ring, with an edge and streaks to the east; the lopsided structure repeats in all six pairs of the four stacks that hold the star (step 12c). Inside 1 arcmin: glare.',
                   Maia='REAL NEBULOSITY from about 1 to 5 arcmin: about 2.5 times more light per unit of star light than Alcyone has (at least half of it cannot be glare), brightest to the west and south-west, with streaks that repeat in the two stacks that hold the star (step 12c). Inside 1 arcmin: glare. Only 9 frames here.',
                   Alcyone='The reference for glare. Its own glow (9 DN at 1 to 2 arcmin, 3 at 3 to 5) cannot be split into glare and nebulosity with this data; the lopsidedness to the west is the three companion stars there.',
                   Electra='Not told apart from glare: at most 1 to 2 DN above Alcyone\'s curve, which is the unevenness between stacks.',
                   Taygeta='Glare. On its west side the mosaic goes over to the cloud stack (2,0), whose cloud glow makes the star lopsided to the south-west: that lopsidedness is not nebulosity.',
                   Asterope='Glare (levels under 2 DN beyond 1 arcmin: not significant).',
                   Atlas='CLOUD GLOW. 5 to 15 times more light per unit of star light than a star in a clear stack: thin cloud in front of the star, in the only panel that holds it. Not nebulosity, not the optics.',
                   Pleione='CLOUD GLOW, the same as Atlas (it sits inside Atlas\'s glow).',
                   Celaeno='CLOUD GLOW: 3 to 4 times more light per unit of star light than a star in a clear stack, in the cloud stack (2,0), the only one that holds it.')[nm]
    stars[nm] = dict(catalogue_ra_dec_j2000=s['catalogue_ra_dec'], v_mag=g['v_mag'], offset_arcmin_east_north=[r2(v, 1) for v in s['offset_arcmin_east_north']], inside_the_mosaic=s['inside_the_mosaic'],
                     in_m45_mosaic_png_at_px=[round(v) for v in s['core_centroid_px']], saturated_core_minus_catalogue_arcsec_east_north=[r2(v, 1) for v in s['core_minus_catalogue_arcsec_east_north']],
                     frames=s['frames_at_the_star'], stacks=[LABEL[x] for x in s['stacks']], from_a_cloud_stack=cloud, arcmin_to_the_nearest_edge=r2(s['arcmin_to_the_nearest_edge_or_hole'], 1), light_round_it=rings, reading=reading)

zb = p11['clear_block_levels_against_the_zero_dn_by_percentile_RGB']
out = {}
out['what'] = 'The Pleiades (M45), nine-panel mosaic: %d x 10 s at ISO 1600 used of %d taken (%d s in all, 30 to 70 s per panel), Sony a6000 at f/10, 0.388 arcsec per sensor pixel, under a 41%% Moon with thin cloud passing; from RAW colour planes, no demosaic' % (total_used, total_found, total_used * 10)
out['made_utc'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
out['tools'] = dict(python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=list(rawpy.libraw_version), tifffile=tifffile.__version__, pillow=PIL.__version__,
                    astrometry_net='solve-field and image2xy (Homebrew), 2MASS index files of the 4204 series in ~/.observatory/astrometry: used only to say where each stack lies on the sky',
                    note='deterministic array arithmetic only; nothing generative or learned. Every pixel of every output is a weighted average of measured pixels (resampled with Lanczos-4, divided by measured flats, minus one fitted constant per stack and one four-number pattern common to all stacks); the pictures add a plain Gaussian blur where the data is thin and a fixed curve. Where there is no data the pictures are black and the linear file is 0 with coverage 0. Nothing is drawn on any picture.')
out['the_short_answer'] = dict(
    picture='m45-mosaic.png: 4612 x 4238 px at 1.553 arcsec per px (1.99 x 1.83 degrees of canvas, 1.90 square degrees with data), north up, east left. All nine named stars are inside. No gaps between panels.',
    what_is_real='The nebulosity round Merope (NGC 1435) and round Maia (NGC 1432) is real and is in the picture: 3 to 8 DN of green above the dark sky a few arcmin out, 2 to 3 times what the same optics put round Alcyone per unit of star light, lopsided (Merope: to the south, with an edge and streaks to the east; Maia: to the west and south-west, with streaks), and its lopsided structure repeats between independent stacks in which the star sits on different parts of the sensor (4 to 11 sigma per pair). It is bluer than the stars\' glare only slightly (B/G 1.7 against 1.45).',
    what_is_not='The bright blue cloud round Atlas and Pleione is thin cloud lit by those two stars, in the only panel that holds them; the glow round Celaeno, the lopsided glow west of Taygeta and the patch north of Electra are the same thing in the other cloud panel. The round glow within about 1 arcmin of every bright star is glare from the optics. Anything fainter than about 3 DN and wider than a few arcmin (the faint grey bands) is unevenness between and inside stacks, not sky.',
    what_cannot_be_said='The absolute zero is not known: the sky, the moonlight and any nebulosity that fills the whole field evenly were removed together. Alcyone\'s and Electra\'s own nebulosity cannot be told from glare here.',
    weakest_parts='Panels (2,0) and (0,2): 3 frames each, through cloud, 2 and 3 times the noise of the others, with cloud glows; the backgrounds of their far sides come out 3 to 5 DN too dark. The centre and four corners of every panel carry a 1 to 3 DN unevenness that the overlaps could only partly pin down.')
out['source'] = dict(folder=STILLS, window_utc=[T0, T1], frames_in_the_window=len(p1['frames']) + len(p1['left_out']), finder_frames_left_out=[dict(frame=f['name'], exposure_s=f['exposure_s'], iso=f['iso']) for f in p1['left_out']],
                     frames_10s_iso1600=total_found, used=total_used, exposure_s=EXPOSURE_S, iso=ISO, camera='Sony ILCE-6000, RAW 6024 x 4024 RGGB, 14-bit scale, black level 512', originals='read in place, never written',
                     calibration=dict(flat='flat2d.npy (the smooth flat of the M31 core run: vignetting, tilt, edge shading, per colour plane, 1 at the centre, 0.67 to 0.71 in the corners)',
                                      small_scale_flat='dustratio.npy and dustmask.npy of the M31 core run (the sensor dust map, measured three hours earlier). Checked here against the median of this hour\'s own 72 frames (frame / flat / level): where the map shows a shadow, this hour\'s flat follows it with slope %.2f and correlation %.2f, and %.3f +- %.3f is left after dividing (shadows %.0f%% deep on average). The dust has not moved; the hair has. In the box the hair moved in, nothing is divided.' % (
                                          p2['dust_check']['slope_of_this_hour_against_the_core_map'], p2['dust_check']['correlation'], p2['dust_check']['left_after_dividing_mean'], p2['dust_check']['left_after_dividing_rms'], 100 * p2['dust_check']['shadow_depth_core_map_mean']),
                                      kept_copy=CORE_WORK,
                                      hair='not taken from any map: found in each panel\'s own frames. Its centre went from sensor px (%d, %d) at 1025 UTC to (%d, %d) at 1038 and then stayed within %d px of (%d, %d); it turned from %d to %d degrees and settled near %d. A circle of 200 sensor px round it is left out of every frame.' % (
                                          *[round(v) for v in hc['c']], *[round(v) for v in hc['p20']], round(max(np.hypot(hc[k][0] - hc['p00'][0], hc[k][1] - hc['p00'][1]) for k in ('p21', 'p11', 'p01', 'p02', 'p12', 'p22', 'p00'))), *[round(v) for v in hc['p00']], round(ha['c']), round(ha['p20']), round(ha['p00'])),
                                      darks='none exist; see steps: the sensor pattern'))
out['panels'] = panels
out['overlaps'] = overlaps
steps = []
steps.append(dict(step='1 frames', script='p1_frames.py', detail='stills between 1025 and 1114 UTC at 10 s ISO 1600; grouped by the mount\'s pointing in the sidecar (a new group when it moves by more than 0.03 degrees or 60 s pass); the groups named in the order of the plan. The centre check is 2 frames, not 1.'))
steps.append(dict(step='2 hot pixels', script='p2_hot.py', detail='fixed hot pixels from the per-plane median, without registration, of all 72 frames (eleven pointings: no star survives); hot = above the 5x5 median by more than max(6 sigma, 25% of the level) and above its highest neighbour by half that. Single-frame spikes: above the 3x3 median by more than 8 sigma + 50% of the level. Both replaced by the 3x3 median of the same colour plane.',
                  fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in p2['hot']}, also_in_the_m31_core_map={h['plane']: h['also_in_m31_core_map'] for h in p2['hot']}))
steps.append(dict(step='2b the hair', script='p2b_hair.py', detail='per panel, the median of its frames (green / flat / small flat / level) in a box at the top of the sensor, smoothed; the blob under 0.94 of its surroundings and under 0.97 of the sky.', found_in_every_panel=True))
steps.append(dict(step='3 stars', script='p3_stars.py', detail='per frame, on the half-size green: smooth light removed, 6 sigma detection in units of local noise, windowed centroids, 28 px (sensor) aperture fluxes, widths, elongation', stars_per_frame=[min(nstars), max(nstars)]))
steps.append(dict(step='4 register', script='p4_register.py', detail='inside each panel: rotation + shift to the panel\'s frame with the most stars, on matched star centroids (rigid, weighted, 3.5 sigma rejection); every frame registered', stars_used_per_frame=[min(o['used'] for o in reg), max(o['used'] for o in reg)], weighted_rms_px=[r2(min(o['wrms_px'] for o in reg)), r2(max(o['wrms_px'] for o in reg))],
                  largest_drift_from_the_reference_px=r2(max(np.hypot(*o['shift_at_centre_px']) for o in reg), 1), largest_turn_deg=r2(max(abs(o['rotation_deg']) for o in reg), 3)))
steps.append(dict(step='5 select', script='p5_select.py', limits=p5['c']['limits'], detail='transparency of a frame = median over the panel\'s stars of (aperture flux / that star\'s flux in the panel\'s clear frames). Used if transparency >= 0.80, even across the field (< 10% per 3000 px), stars no wider than 1.3 x the clear median, elongation <= 1.6, registration rms <= 1 px. Used frames are multiplied by 1 / transparency and weighted (transparency / noise)^2. Panel (0,2) had one frame within the limits: its three most transparent frames are used so that an outlier can be rejected at all (the other two at 78% and 63% of the first).'))
steps.append(dict(step='6 stack', script='p6_stack.py', detail='per panel on the half grid of its reference frame (3012 x 2012, 0.7763 arcsec; one sample of each colour plane per pixel): frame / (smooth flat x small-scale flat) / transparency, resampled with Lanczos-4 (rotation, shift, the plane\'s place in the colour cell), minus a second-order surface fitted to (this frame - the panel\'s clearest frame) on 64 px blocks (the sky is the same in both, so no nebulosity is in the fit); then 3-sigma clipping about the median and about the weighted mean, weighted mean. The hair\'s circle is no data. Pixels under mapped dust are kept (divided by the shadow\'s transmission) and flagged.',
                  surface_range_green_dn=dict(frames_of_clear_stacks=dict(median=r2(np.median(surf_rng[False]), 1), max=r2(max(surf_rng[False]), 1)), frames_of_the_two_cloud_stacks=dict(median=r2(np.median(surf_rng[True]), 1), max=r2(max(surf_rng[True]), 1)))))
steps.append(dict(step='7 plate solutions', script='p7_solve.py', detail='each stack solved with astrometry.net (hint: planned centre, 2 degrees) against the 2MASS 4204 index; matched stars get this pipeline\'s own centroids; affine fit to the tangent plane about RA 56.75 Dec +24.20. The Tycho-2 files the night\'s config tries first give under 20 stars in most panels, nearly all saturated here. Catalogue positions are of epoch 1998 to 2000 and the cluster\'s stars have moved 1.3 arcsec since: absolute placement is good to about 1 arcsec.',
                  stars_fitted_per_stack=[min(p7[k]['used_in_fit'] for k in PANELS), max(p7[k]['used_in_fit'] for k in PANELS)], fit_rms_arcsec=[r2(min(p7[k]['fit_rms_arcsec'] for k in PANELS)), r2(max(p7[k]['fit_rms_arcsec'] for k in PANELS))],
                  field_turn='the frame\'s long side lay 25.8 degrees south of west at 1025 UTC and 27.2 degrees at 1112 UTC'))
steps.append(dict(step='8 placing and scale', script='p8_place.py', detail='all eleven affine maps solved again together: catalogue stars (sigma 0.5 arcsec) + stars shared in overlaps (sigma 0.2 arcsec), 3-sigma rejection. Photometric multiplier per stack from the aperture fluxes of shared unsaturated stars, all overlaps at once in the logarithm; green applied to all colours.',
                  shared_star_rms_arcsec=dict(min=min(o['star_position_rms_arcsec']['after_the_joint_solve'] for o in overlaps), max=max(o['star_position_rms_arcsec']['after_the_joint_solve'] for o in overlaps), median=r2(np.median([o['star_position_rms_arcsec']['after_the_joint_solve'] for o in overlaps]))),
                  star_pairs_used_green=MULT['G_stars'], scatter_in_units_of_expected_noise=dict(R=r2(MULT['R_chi']), G=r2(MULT['G_chi']), B=r2(MULT['B_chi'])), unit=MULT['unit'], white_balance_as_shot=p8['white_balance']))
steps.append(dict(step='9 resample', script='p9_resample.py', detail='every stack onto one fine grid (0.7763 arcsec, north up, east left) with Lanczos-4; a noise weight (inverse variance of green), a feather (0 for the first 40 px inside any edge or hole, then a 200 px smoothstep), dust-divided pixels count a quarter', fine_grid=p8['grid']))
steps.append(dict(step='10 background', script='p10_background.py', used='model K',
                  detail='Solved over all overlaps at once from differences of 64 px block medians (the sky cancels in a difference). ONE ADDITIVE CONSTANT PER STACK AND COLOUR, as asked, plus one thing the overlaps clearly needed and a plane per panel would have got wrong: a pattern fixed to the SENSOR, the same four numbers per colour for every stack.',
                  why='With constants alone the stacks disagree in their overlaps by 0.9 DN rms in green between clear stacks (noise alone 0.3), with a slope of 5 to 7 DN per 1000 px across every strip where a stack\'s bottom edge meets its lower neighbour\'s top edge, the same in every such pair. A plane per stack fits that (0.44 DN) but with slopes of -5, +1, +6 DN per 1000 px from the top row to the bottom row of the mosaic: every stack really has the same shallow dome along the sensor\'s short side, and tilting the rows against each other only hides it at the seams while bending the whole mosaic by some 20 DN, several times the nebulosity. The dome is additive and nearly the same number of raw DN in R, G and B, so it is in the sensor\'s dark level, not in the light (no dark frames exist to measure it directly). A separate check that uses no overlaps (step 10b: raw block level against frame sky level over all 72 frames) finds the same dome in all four colour planes.',
                  second_look_step_10b=dict(script='p10b_dark_check.py', dome_v2_term_raw_dn={pn: [r2(dk['planes'][pn]['d_fit_dn']['v^2'][0]), r2(dk['planes'][pn]['d_fit_dn']['v^2'][1])] for pn in PLANE_NAMES},
                                            u2_term_raw_dn={pn: r2(dk['planes'][pn]['d_fit_dn']['u^2'][0]) for pn in PLANE_NAMES}, against_step_10_v2={c_: pattern[c_]['u^0 v^2'][0] for c_ in 'RGB'},
                                            note='the dome (v^2) agrees with the overlaps to about 0.5 DN; this fit\'s tilt and u v terms are tangled with uneven cloud glow and are not comparable'),
                  sensor_pattern=dict(form='P(u, v) = a00 + a20 u^2 + a11 u v + a02 v^2 in DN of a raw frame, u, v = sensor x, y from the centre, -1..1; in a stack it appears as multiplier x mean(1 / transparency) x white balance x P / flat. Its linear terms cannot be seen in differences between stacks and are left at 0: a tilt of the whole mosaic is not measurable.',
                                      measured_from='the nine clear stacks only (no pair with a cloud stack)', coefficients_value_sigma=pattern),
                  constants='then one constant per stack and colour with the pattern held fixed, each equation weighted by how much the mosaic really mixes the two stacks at that block (so stacks meet where they are joined); the constants are in panels[].background_constant_dn (their mean is 0; the zero comes in step 11)',
                  planes='NOT USED. Tried for all stacks (model B) and for the two cloud stacks only (model G): a plane fitted to two edge strips of a cloud stack and carried 3000 px to its far corner made that corner 15 DN too dark.',
                  rms_of_overlap_residuals_dn=dict(A_constants_only=model_row(A_), B_a_plane_per_stack=model_row(B_), E_constants_and_sensor_pattern_from_all_stacks=model_row(E_), G_E_and_planes_for_the_cloud_stacks=model_row(G_), K_used=model_row(K)),
                  note='rms over 64 px blocks fainter than 60 DN; the K column is from the solve weighted towards the joins, so its figure for pairs with a cloud stack is over their whole overlaps, where a cloud stack and a clear one differ by the cloud glow'))
steps.append(dict(step='11 combine', script='p11_combine.py', detail='stack minus its background; weighted mean of the clear stacks (feather x noise weight x quality); the two cloud stacks fill in only where the clear stacks\' summed feather is under 1 (F x clear + (1 - F) x cloud across the clear stacks\' 200 px edge ramp). No seam lines are cut anywhere.',
                  zero=dict(how='per colour, the median of the darker half (by green) of the 64 px blocks that no cloud stack touches', blocks=p11['zero_blocks'], of_clear_blocks=p11['clear_blocks'],
                            clear_block_levels_against_the_zero_dn_RGB={'percentile_%s' % k_: [r2(v, 1) for v in zb[k_]] for k_ in zb}, darkest_2_percent_dn=p11['darkest_2_percent_of_clear_blocks_against_the_zero_dn'],
                            statement='THE ABSOLUTE ZERO IS NOT KNOWN. The typical dark sky of the clear stacks is called 0 in each colour; whatever sky, moonlight or even nebulosity fills those places is gone with it. The dark sky itself is uneven by about -2 to +2 DN (10th to 90th percentile of blocks) in green.'),
                  frames_per_pixel=p11['frames_per_pixel'], stacks_per_pixel_fine_px=p11['stacks_per_pixel']))
steps.append(dict(step='12 pictures', script='p12_deliver.py, render.py', detail='2 x 2 block mean of the fine grid for the mosaic; the detail resampled from the stacks at the sensor\'s scale. Pictures only: Gaussian blur where the expected noise is above a target (never on the linear file), every colour cut at 12000 DN so saturated cores are white, brightness = green on an asinh curve above a black point, colour ratios from a blurred copy with a pedestal (colour is shown only where the light is well above the zero\'s uncertainty; no saturation is added), sRGB curve.'))
steps.append(dict(step='12c seen twice', script='p12c_seen_twice.py', detail='pairs of stacks that share sky near Merope (four stacks, the star in a different corner of the sensor in each) and Maia (two): stars masked, the round part about the star taken off, band-pass 10 to 60 arcsec; correlation between the two stacks over the shared sky 1 to 8 arcmin from the star. Noise is independent between stacks and glare is round, so what correlates is on the sky and lopsided.',
                  pairs={st: {k_: dict(shared_sq_arcmin=r2(v['area_sq_arcmin'], 0), correlation=r2(v['correlation'], 3), sigma=r2(v['sigma'], 1), common_structure_dn_rms=r2(v['common_part_dn_rms'])) for k_, v in tw[st].items()} for st in ('Merope', 'Maia')},
                  control_blank_sky={k_: dict(shared_sq_arcmin=r2(v['area_sq_arcmin'], 0), correlation=r2(v['correlation'], 3), sigma=r2(v['sigma'], 1), common_structure_dn_rms=r2(v['common_part_dn_rms'])) for k_, v in tw['control_blank_sky'].items()},
                  reading='near Merope every one of the six pairs of stacks shares non-round structure of 0.3 to 0.4 DN rms (4 to 8 sigma each); near Maia 0.36 DN rms (11 sigma, with the two-frame centre check); blank sky shows 0.1 to 0.2 DN (faint stars the mask misses). The streaks are real and small: a few tenths of a DN rms, about 1 to 2 DN at their brightest.'))
steps.append(dict(step='12b glare or nebulosity', script='p12b_glare.py', detail='green level in rings and eight sectors round each named star; scaled by the star\'s magnitude; Alcyone\'s curve as the upper limit of what the optics give', glare_upper_limit=gl['glare_upper_limit']))
out['steps'] = steps
out['named_stars'] = stars
out['all_nine_named_stars_inside'] = all(s['inside_the_mosaic'] for s in stars.values())
out['colour'] = p12['colour']
out['gaps_and_seams'] = dict(gaps='none between panels: no enclosed hole without data', notches=[dict(stack=LABEL[k], offset_arcmin_east_north=[r2(v, 1) for v in h['offset_arcmin_east_north']], what='the hair\'s circle of a top-row stack, 200 sensor px radius plus the 31 arcsec margin: no data, black, at the north edge') for k, h in p12['holes']['hair_circles'].items() if h['fraction_of_the_circle_filled_by_other_stacks'] < 0.5],
                             hair_circles_filled='the hair\'s circle of the eight other stacks lies under a neighbour and is filled by it',
                             seams='no cut lines; between clear stacks the levels meet to 0.5 DN rms in green (noise 0.3 to 0.45), which does not show. Where the mosaic goes over to a cloud stack it shows as a change over 2.6 arcmin: (2,0) west of a line through Taygeta, Celaeno and Electra (sky goes from faintly grainy to black, stars get fatter, the cloud glows begin), and (0,2) east of Alcyone (Atlas and Pleione\'s cloud glow fades out towards the clear stacks). A faint lighter band along the mosaic\'s south-east edge and across panel (0,1) is the 1 to 3 DN unevenness.',
                             outline='the mosaic is a rectangle turned 26 to 27 degrees; the first try of (0,0) adds a step at the north-east; the corners of the canvas are black (no data)')
out['outputs'] = {k: v for k, v in p12.items() if k.startswith('m45-')}
out['do_not_trust'] = [
    'The glow round Atlas and Pleione (out to 6 arcmin, the brightest cloud in the picture), round Celaeno, on the west side of Taygeta and the patch north of Electra: thin cloud lit by those stars, in the two panels taken through cloud.',
    'The sky level of the far sides of panels (2,0) and (0,2) (the west and east ends of the mosaic): 3 to 5 DN below the zero, so black. Their constants are tied to joins that lie inside their cloud glows.',
    'Any smooth light fainter than about 3 DN (green) over more than a few arcmin: the dark level pattern was inferred from overlaps (four numbers per colour), its tilt cannot be seen, and stacks still differ by 0.5 DN rms where they meet and 1 to 3 DN inside.',
    'The colour of anything fainter than about 10 DN: the zero of red is known to 2 to 3 DN and red has 4 times green\'s noise; the pictures show such light nearly grey on purpose.',
    'The cores of the nine named stars and of %d more: at the sensor\'s ceiling, white, not corrected.' % (n_sat_stars - 9) + '  The round glow inside about 1 arcmin of each is glare from the optics; the purple fringe round medium stars is the optics\' colour error.',
    'Star positions to better than about 1 arcsec (catalogue epoch 1998 to 2000, cluster proper motion 1.3 arcsec since), and star shapes in the two cloud panels (blurred up to sigma 3 px in the pictures).',
    'Three circles without data at the north edge (the hair on the sensor): black.']
out['what_would_help_most'] = [
    'Retake panels (2,0) and (0,2) under a clear sky: they hold Atlas, Pleione and Celaeno and half of what lies round Taygeta and Electra, and their cloud glows are the largest untruth in the picture. 7 clear frames each would also bring their noise down 2 to 3 times.',
    'Dark frames (10 s, ISO 1600, cap on, same night): the dark level of the sensor has a dome of 1.5 to 2 DN that had to be inferred from overlaps; darks measure it outright, tilt included. With the sky at 37 DN and the nebulosity at 3 to 8 DN this is the largest systematic.',
    'Much more exposure, in longer frames: at f/10 a 10 s frame holds 37 DN of sky (about 3.5 electrons) under 25 DN of read noise, so every frame is read-noise limited. 60 s frames (or 30 s at ISO 3200) and 10 to 20 minutes per panel would put the nebulosity at 5 to 10 sigma per 1.5 arcsec pixel instead of 1.',
    'No Moon, and a focal reducer: the Moon (41%) sets the sky the nebulosity has to be seen against; f/6.3 gives 2.5 times the light per pixel and needs 4 panels instead of 9.',
    'More overlap or a second pass shifted by half a panel: Merope sits where four panels meet, each of which sees one quarter of its nebula; glare and nebulosity can only be told apart where two stacks with the star at different places on the sensor share the sky.',
    'Clean the sensor (the hair and the dust shadows cost three holes and 8% of the pixels a quarter of their weight).']
out['scripts'] = dict(folder='scripts/ beside this file (run_all.sh runs them in order; they read the RAWs in place and need the flat arrays of the M31 run)', files=sorted(os.path.basename(f) for f in glob.glob(os.path.join(SCR, '*.py')) + glob.glob(os.path.join(SCR, '*.sh')) if not os.path.basename(f).startswith('x_')))
json.dump(out, open(os.path.join(OUT, 'm45-mosaic-recipe.json'), 'w'), indent=1)
# the scripts beside the recipe
dst = os.path.join(OUT, 'scripts'); os.makedirs(dst, exist_ok=True)
for f in glob.glob(os.path.join(SCR, '*.py')) + glob.glob(os.path.join(SCR, '*.sh')):
    if not os.path.basename(f).startswith('x_'): shutil.copy2(f, dst)
print('recipe written: %d bytes; %d of %d frames used; panels:' % (os.path.getsize(os.path.join(OUT, 'm45-mosaic-recipe.json')), total_used, total_found))
for p in panels:
    print('  %-16s found %d used %d  transparency %.2f  mult %.3f  noise G %.1f DN/fine px  centre %+6.2f E %+6.2f N (plan off %.2f\')  rot %.2f  const G %+.1f %s' % (p['panel'], p['frames_found'], p['frames_used'], p['transparency_against_the_clearest_stack'], p['photometric_multiplier_green'],
          p['noise_green_in_common_units_dn_per_fine_px'], *p['solved_centre_offset_arcmin_east_north'], p['off_the_plan_by_arcmin'], p['x_axis_deg_south_of_west'], p['background_constant_dn']['G'], 'CLOUD' if p['through_cloud'] else ''))
