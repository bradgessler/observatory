"""Mosaic step 14 (only with a master flat): the recipe written by step 13 says what the pipeline does; this adds what
the rerun with real flat frames changed, and replaces the sentences of the first run that are no longer true.
Reads: the recipe of step 13, before-flats/m31-mosaic-recipe.json (the first run), and the work files of steps 5c,
6c, 10 and 12b. Keeps the small calibration files of the rerun beside the results (calibration-rerun/)."""
import json, os, shutil, hashlib
import numpy as np
from mcommon import *
L = lambda n: json.load(open(W(n)))
rp = os.path.join(OUT, 'm31-mosaic-recipe.json'); r = json.load(open(rp)); old = json.load(open(os.path.join(OUT, 'before-flats', 'm31-mosaic-recipe.json')))
C5 = L('m5c_masterflat_check.json'); BA = L('m12b_before_after.json'); BG = L('m10_background.json'); M11 = L('m11_six.json'); M12 = L('m12_deliver.json'); PL = L('m8_place.json')
C6 = L('m6c_before_after.json') if os.path.exists(W('m6c_before_after.json')) else None; FV = L('flat_variant_check.json') if os.path.exists(W('flat_variant_check.json')) else None
PLAIN = os.environ.get('M31M_MASTER_FLAT_PLAIN') or C5['master_flat']
core_rec = json.load(open(os.path.join(CORE_DIR, 'm31-core-recipe.json')))
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''): h.update(b)
    return h.hexdigest()
steps_old = {s['step']: s for s in old['steps']}; bg_old = steps_old['background']['rms_of_block_differences_all_overlaps_dn']
bg_new = {c: {m: round(BG[c][m]['rms_all_blocks_away_from_nucleus'], 2) for m in bg_old[c]} for c in 'RGB'}
MODEL = M11['background_model']
ov_old = old['overlaps']; ov_new = r['overlaps']
pairs = {k: dict(green_rms_dn=dict(before=round(ov_old[k]['background_green_dn']['rms_after_model_used'], 2), after=round(ov_new[k]['background_green_dn']['rms_after_model_used'], 2)),
                 red_rms_dn=dict(before=round(ov_old[k]['background_red_rms_after_model_used'], 2), after=round(ov_new[k]['background_red_rms_after_model_used'], 2)),
                 blue_rms_dn=dict(before=round(ov_old[k]['background_blue_rms_after_model_used'], 2), after=round(ov_new[k]['background_blue_rms_after_model_used'], 2)), blocks=dict(before=ov_old[k]['blocks'], after=ov_new[k]['blocks'])) for k in ov_new if k in ov_old}
better = sum(1 for v in pairs.values() if v['green_rms_dn']['after'] < v['green_rms_dn']['before']); worse = sum(1 for v in pairs.values() if v['green_rms_dn']['after'] > v['green_rms_dn']['before'])
dg_old = old['outputs']['m31-mosaic-diagnostic.png']['difference_in_overlaps_dn']; dg_new = M12['outputs']['m31-mosaic-diagnostic.png']['difference_in_overlaps_dn']
pan_old = old['panels']; pan_new = r['panels']
cz = BA['colour_zero']; d2 = C5['dust_depth_agreement']['master_flat_shadow_deeper_than_2pct']
r['first_made_utc'] = old['made_utc']
r['what'] = r['what'] + '; re-made on 2026-10-04 with the flat built from that morning\'s twilight sky frames'
r['rerun_with_twilight_flat'] = dict(
    in_one_line='Re-made with real flat frames. Small gains (dust, a few false smudges, the weight of 4% of the pixels); the large things did not move: the panels\' backgrounds are the Moon and the cloud, not the flat, and their red and blue zeros still disagree, so the outer panels are still shown in grey.',
    flat=dict(file=PLAIN, sha256=sha(PLAIN) if os.path.exists(PLAIN) else None, which='the HYBRID of the M42 run (m42/calibration/flat-delivered.npy): the twilight master flat (26 sky flats, 1348 to 1407 UTC: dust, edge shading, pixel response) with the large-scale shape, above about 300 plane px, of this night\'s cloud-glow flat. Made by m42/scripts/s6_twilight.py and s6_hybrid.py; m42/calibration/flat.json.',
              applied_as='every plane of every frame / that flat (step 6, M31M_MASTER_FLAT), instead of the cloud-glow flat x the dust map measured from clouded frames. Inside %d small patches (%.2f%% of the sensor) the flat is this hour\'s own response instead (step 5c).' % (C5['patches'], 100 * C5['marked_fraction_of_sensor']),
              core_stack='the core stack was re-made first with the same flat (m31-core-linear.tif, its recipe m31-core-recipe.json) and the mosaic is tied to that one (M31_CORE_TIF)'),
    which_flat_and_why=dict(
        tested='both variants on these six panels (steps 5c to 10 run twice): the hybrid, and the twilight master flat as measured (m42/calibration/flat-twilight-master.npy), which is 2 to 3.5% brighter at the corners and tilted by 1.7% per 3000 px against the hybrid.',
        result=FV,
        reading='No decision from this target. With one plane per panel (models B, C) the two agree to 3%%: green %.2f against %.2f DN (B), %.2f against %.2f (C). With constants alone the flat as measured looks better (%.1f against %.1f DN) and every panel\'s slope in x moves by about +6 DN per 1000 px; but all six panels sit the same way round on the sky, so a tilt of the flat times a 250 to 500 DN moonlit sky and a gradient of that sky towards the Moon are the same thing in these overlaps and cannot be told apart. The second-order part (corners), which could, is too small against 2 DN of block noise. The HYBRID is used, for the reason the M42 run found on clear stacks of very different sky level (with the flat as measured its panels needed tilts and went below zero; with the hybrid they agreed with constants alone to 1.3 DN), and so that core, mosaic and M42 rest on one flat. The Pleiades mosaic of the same night (m45/m45-mosaic-recipe.json, same key), whose sky is dark and whose nine stacks overlap on all sides, can see the second-order part: there the flat as measured is the worse of the two with constants alone (green 0.96 against 0.92 DN rms) and leaves the larger pattern.' % (
            FV['rms_dn']['G']['B']['hybrid'], FV['rms_dn']['G']['B']['twilight_as_measured'], FV['rms_dn']['G']['C']['hybrid'], FV['rms_dn']['G']['C']['twilight_as_measured'], FV['rms_dn']['G']['A']['twilight_as_measured'], FV['rms_dn']['G']['A']['hybrid']) if FV else None),
    is_the_dust_of_dawn_the_dust_of_this_hour=dict(
        how='step 5c: per panel the sum of all its frames over the master flat, small-scale part; the median over the six panels (what all panels show at one place on the sensor is the sensor).',
        answer='Yes. Where the master flat shows a shadow deeper than 2%% (%d plane px) this hour shows the same shadow: depth %.2f%% against %.2f%%, slope %.3f, correlation %.3f; after the division what is left there is %+.2f%% in the mean (about %.1f DN on this sky) and %.2f%% rms, which is the noise of the measurement (%.2f%%).' % (d2['plane_px'], 100 * d2['this_hour_depth_mean'], 100 * d2['master_depth_mean'], d2['slope_this_hour_over_master'], d2['correlation'], 100 * d2['left_after_dividing_by_the_master_mean'], abs(d2['left_after_dividing_by_the_master_mean']) * 330, 100 * d2['left_rms'], 100 * C5['ratio_noise_sigma_2_5']),
        exceptions=C5['all_patches'], exceptions_reading='four patches, each seen alike in the panels (so sensor, not sky): two rings where the flat is too dark by 2.5% (dust that came after this hour), one where it is too bright by 2.4% (dust that left), and one at the top edge that changed in the middle of the hour. There the flat is multiplied by this hour\'s measured response, the pixels are left out of the average where a panel has enough clean frames, and the rest are flagged (2).',
        numbers={k: v for k, v in C5.items() if k not in ('all_patches',)},
        a_mistake_found_on_the_way='A first version of this check took the median over the 19 heavily clouded frames, as step 5b of the first run does for its dust map. It marked 20 bright patches of 2 to 4%. Every one was a galaxy or bright star of ONE panel (M32 in (2,1), the bulge in (1,0)): with 4 of 19 frames far too bright there and 8% of noise per pixel, a median still rises by 3%. THE FIRST RUN\'S SMALL-SCALE FLAT HAD THOSE PATCHES IN IT and divided every panel by them: false dark smudges of about 1% of the sky (3 DN) at the same place on the sensor in every panel, the largest 140 x 140 sensor px (see what_the_stacks_hold). They are gone now.',
        the_flats_own_flaw='where the hair lay at dawn (top edge, sensor px x 3700..3840, y 0..80) the delivered flat was patched with its own smooth part, which still dips there by 5 to 9%. NO data is taken from sensor px x 3660..3900, y 0..120 (M31M_NODATA_MASK).'),
    the_hair='unchanged: found in every used frame from the frame itself, a circle of 220 px radius left out, no data where no frame is clear of it. Never divided by any map.',
    before_and_after=dict(
        overlap_disagreement=dict(
            what='rms of the 64 px block differences between every pair of images, blocks more than 13 arcmin from the nucleus, after the background model, DN in the core\'s units',
            all_overlaps=dict(before=bg_old, after=bg_new), model_used=MODEL, per_overlap=pairs, green_better_in=better, green_worse_in=worse,
            diagnostic_picture=dict(before=dg_old, after=dg_new),
            reading='with the model used (%s): green %.2f -> %.2f DN, red %.2f -> %.2f, blue %.2f -> %.2f: 5 to 6%% lower. With constants alone %.1f -> %.1f DN in green: unchanged, because that is the moonlit sky\'s own gradient in each panel (slopes of up to 25 DN per 1000 px), not a flat error. Per overlap green is lower in %d of %d and higher in %d. In the finished mosaic\'s seams (diagnostic picture) the median difference is %.2f -> %.2f DN and the 90th percentile %.1f -> %.1f: no visible change.' % (
                MODEL[0], bg_old['G'][MODEL], bg_new['G'][MODEL], bg_old['R'][MODEL], bg_new['R'][MODEL], bg_old['B'][MODEL], bg_new['B'][MODEL], bg_old['G']['A_constants'], bg_new['G']['A_constants'], better, len(pairs), worse, dg_old['median_abs'], dg_new['median_abs'], dg_old['p90_abs'], dg_new['p90_abs'])),
        panel_backgrounds=dict(
            planes_did_not_shrink={k: dict(green_surface_range_dn=dict(before=old['panels'][k]['background_fitted']['G']['surface_min_max_over_the_panel_dn'], after=pan_new[k]['background_fitted']['G']['surface_min_max_over_the_panel_dn']),
                                           red=dict(before=old['panels'][k]['background_fitted']['R']['surface_min_max_over_the_panel_dn'], after=pan_new[k]['background_fitted']['R']['surface_min_max_over_the_panel_dn']),
                                           blue=dict(before=old['panels'][k]['background_fitted']['B']['surface_min_max_over_the_panel_dn'], after=pan_new[k]['background_fitted']['B']['surface_min_max_over_the_panel_dn'])) for k in pan_new},
            reading='the fitted planes are what they were (for example panel (1,0) +-44 DN in green before and after, (1,1) -51..+32). The first run hoped that real flats would shrink them. They did not, and with this flat they could not: its large-scale shape is the cloud-glow flat the first run already used. What the planes take off is sky.'),
        colour_zeros=dict(
            what='where only panels have data and the light is faint (64 px blocks, green under 30 DN): red - 1.05 x green and blue - 0.95 x green (the galaxy\'s own colour in the core field taken off); 0 if a panel\'s red and blue zeros agreed with its green',
            before=cz['before'], after=cz['after'],
            reading='NOT IMPROVED. The panels\' medians run from %+.0f to %+.0f DN in red (before %+.0f to %+.0f) and %+.0f to %+.0f in blue (before %+.0f to %+.0f); inside a panel red wanders by up to %.0f DN (before %.0f) and blue by up to %.0f (before %.0f), against a block noise of 1 to 3 DN and a galaxy of 7 to 23 DN of green there. Red and blue zeros do not agree between panels or inside them. The outer panels are therefore still rendered in neutral grey (colour pedestal 300 DN), exactly as before.' % (
                cz['after']['spread_of_the_panel_medians_dn']['red']['min'], cz['after']['spread_of_the_panel_medians_dn']['red']['max'], cz['before']['spread_of_the_panel_medians_dn']['red']['min'], cz['before']['spread_of_the_panel_medians_dn']['red']['max'],
                cz['after']['spread_of_the_panel_medians_dn']['blue']['min'], cz['after']['spread_of_the_panel_medians_dn']['blue']['max'], cz['before']['spread_of_the_panel_medians_dn']['blue']['min'], cz['before']['spread_of_the_panel_medians_dn']['blue']['max'],
                cz['after']['largest_block_departure_dn']['red'], cz['before']['largest_block_departure_dn']['red'], cz['after']['largest_block_departure_dn']['blue'], cz['before']['largest_block_departure_dn']['blue'])),
        dust=dict(
            pixels_flagged_dust_divided_per_panel={k: dict(before=old['panels'][k]['pixels']['from_dust_divided_combine_fraction'], after=pan_new[k]['pixels']['from_dust_divided_combine_fraction']) for k in pan_new},
            mosaic_pixels_resting_on_dust_divided_data_only=BA['dust_divided_only'],
            what_the_stacks_hold=None if C6 is None else {k: {run: {kk: vv for kk, vv in v.items() if kk != 'rows'} for run, v in d.items()} for k, d in C6['results'].items()},
            what_the_stacks_hold_how='step 6c: at the 42 dust shadows of 3% and deeper, and at the places where the first run\'s small-scale flat was above 1.012, the median of green inside over a ring outside, minus 1, in every panel stack; the median over the panels per place, then mean and rms over the places',
            reading=None if C6 is None else 'at the real dust shadows the panel stacks held %+.2f%% in the mean (%.1f DN rms) and now hold %+.2f%% (%.1f DN rms): both small, the new one about half. At the first run\'s false patches they held %+.2f%% (the largest, sensor px 2968, 3410: -3.3 DN in every panel) and now %+.2f%%. The share of each panel flagged as dust-divided, which counted a quarter in the weights and not at all in the background fit, went from 2 to 8%% to 0.0 to 0.1%%; in the mosaic the pixels that rest on such data alone went from %.1f%% to %.2f%%.' % (
                C6['results']['dust']['before']['mean_percent'], C6['results']['dust']['before']['rms_dn'], C6['results']['dust']['after']['mean_percent'], C6['results']['dust']['after']['rms_dn'], C6['results']['false']['before']['mean_percent'], C6['results']['false']['after']['mean_percent'],
                100 * BA['dust_divided_only']['before_fraction_of_data'], 100 * BA['dust_divided_only']['after_fraction_of_data'])),
        noise=dict(stack_noise_g1_dn_per_panel={k: dict(before=old['panels'][k]['noise']['stack_per_half_grid_px_panel_units_dn']['G1'], after=pan_new[k]['noise']['stack_per_half_grid_px_panel_units_dn']['G1']) for k in pan_new},
                   mosaic_green_median_dn=BA['noise_green_dn'], core_green_per_mosaic_px_dn=dict(before=old['steps'][[s['step'] for s in old['steps']].index('one grid')]['noise_green_per_mosaic_px_core_units_dn']['core']['median'], after=r['steps'][[s['step'] for s in r['steps']].index('one grid')]['noise_green_per_mosaic_px_core_units_dn']['core']['median']),
                   reading='unchanged: per panel within 2%%; the mosaic\'s median %.1f -> %.1f DN (fewer pixels at quarter weight).' % (BA['noise_green_dn']['before_median'], BA['noise_green_dn']['after_median'])),
        how_much_the_picture_changed=dict(what='64 px block medians of (after - before), DN', numbers=BA['change'], reading='inside the core field %.1f DN rms in green about a shift of %+.1f (the zero is set in the core field\'s corner; the core stack itself changed by 0.24 DN rms at large scale); in the panels %.1f DN rms in green, %.1f in red, %.1f in blue. Side by side the two pictures look the same; two small dark smudges in the east and south (the false patches) are gone.' % (
            BA['change']['where the core stack has data']['G']['rms'], BA['change']['where the core stack has data']['G']['median'], BA['change']['where only panels have data']['G']['rms'], BA['change']['where only panels have data']['R']['rms'], BA['change']['where only panels have data']['B']['rms'])),
        zero=dict(before=steps_old['combine and zero']['six_panel']['colours_in_the_zero_region_before_dn'], after=M11['colours_in_the_zero_region_before_dn'], note='R, G, B in the darkest region before the one number is taken off: red sits 6 DN under green both times')),
    what_the_first_run_expected_and_what_came=dict(expected=old['dawn_flats']['would_they_change_the_result'],
        came='(1) the dust: yes, as said. (2) the smooth flat: NO. The dawn sky flats\' own large-scale shape did not agree with the night sky (stray light at the corners, the dawn\'s gradient), so the flat that was delivered keeps the cloud-glow flat\'s large-scale shape; the planes are the same and the red and blue zeros did not come closer. (3) the core stack: re-made; at large scale it is its old version C. The four things listed under NO are as they were.'),
    hooks_that_were_written_but_untested=dict(
        worked=['M31M_MASTER_FLAT in step 6', 'M31M_DUST_MASK in step 6', 'M31_CORE_TIF in step 7', 'step 13 no longer tries to copy the calibration folder onto itself (it already guarded that)'],
        fixed_or_added=['step 5c (new): the check of the flat against this hour, the patches where it does not hold, the flat adjusted there (flat_master_hour.npy), the dawn hair\'s zone',
                        'step 6: M31M_NODATA_MASK (new), for the dawn hair\'s zone: the old hook could only LEAVE OUT such pixels, and where a panel had no clean frame it fell back to data divided by the wrong flat',
                        'step 9: the core\'s noise map used the cloud-glow flat whatever the core was made with; M31_CORE_FLAT names the flat of a re-made core',
                        'step 13: the core stack named in the recipe is the one given by M31_CORE_TIF',
                        'run_all.sh: with M31M_MASTER_FLAT it runs step 5c and hands its products to step 6 and later; M31M_BEFORE_WORK adds the before/after measurement of step 6c; steps 12b and 14 (new) measure against before-flats/ and write this section',
                        'the note "about 12 minutes": it takes about 3'],
        without_the_hooks='with none of the variables set the scripts do what they did: step 6 run that way reproduced the first run\'s panel stacks (same noise and flag counts in all seven).'),
    files_written=sorted(k for k in r['outputs']['files'] if 'level' not in k), before='before-flats/ beside this file holds every picture, tif and json as they were before the rerun',
    not_made_by_this_pipeline='m31-mosaic-level.png / .jpg / .json appeared in this folder while the rerun was running (another job, 10:23 local): a turned and cropped copy of before-flats/m31-mosaic.png, i.e. of the picture BEFORE the rerun. Left alone.',
    kept_for_reproduction=dict(folder=os.path.join(OUT, 'calibration-rerun'), files={'leaveout_master.npy': 'boolean (2012, 3012): the patches of step 5c', 'nodata_master.npy': 'boolean: the dawn hair\'s zone', 'mismatch_master.npy': 'float32: this hour\'s response over the master flat, Gaussian sigma 2.5 (step 5c); flat_master_hour.npy = master flat x this, inside the patches',
                                                                                         'm5c_masterflat_check.json, m6c_before_after.json, m12b_before_after.json, flat_variant_check.json, m10_background.json': 'the numbers quoted here'}),
    how_to_run_it_again='PY=<python> M31M_WORK=<scratch, 13 GB> M31M_MASTER_FLAT=%s M31_CORE_TIF=%s sh scripts/run_all.sh   (about 3 minutes; overwrites the deliverables)' % (PLAIN, os.environ.get('M31_CORE_TIF', '<core tif>')))
# ---- sentences of the first run that no longer hold ----
S_ = {s['step']: s for s in r['steps']}
S_['dust and hair']['first_run_detail'] = S_['dust and hair']['detail']
S_['dust and hair']['detail'] = 'RERUN: the master flat holds the dust. Checked against this hour (step 5c, the sum of every panel\'s frames over the flat, median over the panels): the shadows are where and as deep as the flat says (slope %.3f, correlation %.3f). %d patches (%.2f%% of the sensor) where they are not are left out of the average or flagged; the first run\'s masks covered %.1f%%. THE HAIR, as before: it moved 140 px from its place in the core run and a further 175 px and 55 degrees during this hour; it is found in every used frame from the frame itself and a circle of 220 px radius round it is left out. The hair\'s place in the FLAT (at dawn, top edge) gives no data either.' % (d2['slope_this_hour_over_master'], d2['correlation'], C5['patches'], 100 * C5['marked_fraction_of_sensor'], 100 * C5['before_marked_fraction_of_sensor_dust_masks'])
S_['flat field']['first_run_detail'] = S_['flat field']['detail']
S_['flat field']['detail'] = 'RERUN: each colour plane divided by the master flat of real flat frames (see rerun_with_twilight_flat.flat): twilight dust, edge shading and pixel response, large-scale shape of the cloud-glow flat.'
S_['stack per panel']['detail'] = S_['stack per panel']['detail'].replace('Dust-masked samples left out; where fewer than half the frames are clean, the combine with them left in (they are divided by the small-scale flat) is used and flagged', 'Samples from the patches of step 5c left out; where fewer than half the frames are clean, the combine with them left in (there the flat is this hour\'s measured response) is used and flagged')
S_['one grid']['core_own_shadows'] = 'the hair and one small patch still in the re-made core stack (its dust map, transmission under 0.985, grown 20 px) are given no weight; the panels fill them'
S_['placing on the sky']['reading'] = S_['placing on the sky']['reading'].replace('0.35 to 0.56 arcsec', '%.2f to %.2f arcsec' % (min(v['rms_arcsec'] for v in PL['overlaps_after_joint_solve'].values()), max(v['rms_arcsec'] for v in PL['overlaps_after_joint_solve'].values()))).replace('it was 0.38 to 0.84 arcsec', 'it was %.2f to %.2f arcsec' % (min(v['rms_arcsec'] for v in PL['overlaps_plate_solutions_alone'].values()), max(v['rms_arcsec'] for v in PL['overlaps_plate_solutions_alone'].values())))
S_['pictures']['differs_from_the_core_pictures'] = S_['pictures']['differs_from_the_core_pictures'].replace('m31-core-cloudflat.png', 'the core pictures')
dn = list(r['do_not_trust'])
for i, t in enumerate(dn):
    if t.startswith('The colour of anything outside the core field'):
        dn[i] = 'The colour of anything outside the core field. After the rerun too: the panels\' red zeros differ by %.0f DN between panels and wander by up to %.0f DN inside one (blue: %.0f and %.0f), against 7 to 23 DN of galaxy; the pictures show the panels in neutral grey for that reason. The linear file has the colours as they came: do not read them.' % (
            cz['after']['spread_of_the_panel_medians_dn']['red']['max'] - cz['after']['spread_of_the_panel_medians_dn']['red']['min'], cz['after']['largest_block_departure_dn']['red'], cz['after']['spread_of_the_panel_medians_dn']['blue']['max'] - cz['after']['spread_of_the_panel_medians_dn']['blue']['min'], cz['after']['largest_block_departure_dn']['blue'])
    if t.startswith('Small round dark or light smudges'):
        dn[i] = 'Sensor dust in the panels: divided by the dawn flat, which this hour confirms to %.2f%% of a 250 to 500 DN sky (under 1 DN) in the shadows; four small patches where the flat was not this hour\'s are flagged (bit 128 of the coverage file where nothing else covers, %.2f%% of the mosaic).' % (abs(100 * d2['left_after_dividing_by_the_master_mean']), 100 * BA['dust_divided_only']['after_fraction_of_data'])
    if t.startswith('Everything the core recipe lists'):
        dn[i] = 'Everything the (re-made) core recipe lists under do_not_trust still holds inside the core field, except its hair smudge, which is replaced here by panel data.'
    if t.startswith('Photometry between panels'):
        dn[i] = t.replace('some of them in the corners where the flat is least sure', 'some of them in the corners where the flat is least sure (its large-scale shape is still the cloud-glow flat\'s)')
r['do_not_trust'] = dn
r['dawn_flats'] = dict(done='2026-10-04: see rerun_with_twilight_flat', first_run_text=old['dawn_flats'])
r['what_would_help_most'] = [t if not t.startswith('The dawn flats') else 'Flats that fix the LARGE-scale shape: an even panel or lamp over the aperture the same night, or sky flats taken well away from the dawn\'s gradient and with the tube baffled. The dawn sky flats settled the dust; the tilt and the corners still rest on the cloud\'s glow, and with them the panels\' colour.' for t in r['what_would_help_most']]
r['calibration_kept'] = r['calibration_kept'] + ' RERUN: calibration-rerun/ holds the patches and the numbers of step 5c; the master flat itself is m42/calibration/flat-delivered.npy.'
r['scripts'] = r['scripts'].replace('m5b_dustcheck.py, m6_stack.py', 'm5b_dustcheck.py, m5c_masterflat_check.py (rerun), m6_stack.py, m6c_before_after.py (rerun, a measurement)').replace('m12_deliver.py, m13_recipe.py;', 'm12_deliver.py, m12b_before_after.py (rerun, a measurement), m13_recipe.py, m14_rerun_notes.py (rerun);')
r['outputs']['files'] = {k: v for k, v in r['outputs']['files'].items() if 'level' not in k}
keep = os.path.join(OUT, 'calibration-rerun'); os.makedirs(keep, exist_ok=True)
for f in ('leaveout_master.npy', 'nodata_master.npy', 'mismatch_master.npy', 'm5c_masterflat_check.json', 'm6c_before_after.json', 'm12b_before_after.json', 'flat_variant_check.json', 'm10_background.json'):
    if os.path.exists(W(f)): shutil.copy2(W(f), keep)
json.dump(r, open(rp, 'w'), indent=1)
dst = os.path.join(OUT, 'scripts')
for f in ('m14_rerun_notes.py', 'run_all.sh'):
    if os.path.abspath(os.path.join(SCR, f)) != os.path.abspath(os.path.join(dst, f)): shutil.copy2(os.path.join(SCR, f), dst)
print('recipe with the rerun notes:', os.path.getsize(rp), 'bytes')
for k in ('overlap_disagreement', 'colour_zeros', 'dust', 'noise', 'how_much_the_picture_changed'): print(' -', k + ':', r['rerun_with_twilight_flat']['before_and_after'][k]['reading'])
