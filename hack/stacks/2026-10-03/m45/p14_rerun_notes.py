"""Step 14 (only with M45_MASTER_FLAT): the recipe of step 13 says what the pipeline does; this adds what the rerun with
real flat frames changed, answers the question it was run for (is the 'sensor dome' a flat-field error?), and
replaces the sentences of the first run that no longer hold.
Reads the recipe of step 13, before-flats/m45-mosaic-recipe.json (the first run), the work files of steps 2c, 10,
10b, 12d, and, if they are there, the step 10 and 10b results of the same stacks made with the first run's flat
(p10_background_cloud.json, p10b_dark_check_cloud.json) and with the twilight flat as measured (..._asis.json)."""
import json, os, shutil, hashlib
import numpy as np
from c import *
J = lambda n: json.load(open(W(n))) if os.path.exists(W(n)) else None
BEF = os.path.join(NIGHT, 'm45', 'before-flats')
rp = os.path.join(OUT, 'm45-mosaic-recipe.json'); r = json.load(open(rp)); old = json.load(open(os.path.join(BEF, 'm45-mosaic-recipe.json')))
C2 = J('p2c_masterflat_check.json'); P10 = J('p10_background.json'); P10c = J('p10_background_cloud.json'); P10a = J('p10_background_asis.json'); DK = J('p10b_dark_check.json'); DKc = J('p10b_dark_check_cloud.json'); BA = J('p12d_before_after.json')
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''): h.update(b)
    return h.hexdigest()
def pat(P, c): return {t['term']: [round(t['value'], 2), round(t['sigma'], 2)] for t in P['models']['K'][c]['sensor_pattern_raw_dn']}
def rms(P, m, c, key='rms_residual_faint_dn_clear_pairs'): return round(P['models'][m][c][key], 3)
variants = dict(first_run_cloud_glow_flat=P10c, hybrid_used=P10, twilight_as_measured=P10a)
dome = {c: {nm: (pat(P, c)['u^0 v^2'] if P else None) for nm, P in variants.items()} for c in 'RGB'}
table = {c: {m: {nm: (rms(P, m, c) if P else None) for nm, P in variants.items()} for m in 'ABEGK'} for c in 'RGB'}
table_cloud = {c: {m: {nm: (rms(P, m, c, 'rms_residual_faint_dn_pairs_with_a_cloud_stack') if P else None) for nm, P in variants.items()} for m in 'AK'} for c in 'RGB'}
d2 = C2['dust_depth_agreement']['master_flat_shadow_deeper_than_2pct']; wrong = [c for c in C2['known_patches_tested'] if c['wrong_for_this_hour']]
ds = BA['dust_in_stacks']; mo = BA['mosaic']; dc = BA['dark_sky_colour']
g = lambda nm: dome['G'][nm][0]
r['first_made_utc'] = old['made_utc']
r['what'] = r['what'] + '; re-made on 2026-10-04 with the flat built from that morning\'s twilight sky frames'
r['rerun_with_twilight_flat'] = dict(
    in_one_line='Re-made with real flat frames. The picture is the same to +-0.3 DN. The sensor dome did NOT go away, so it is not a flat-field error; it is still taken off as an additive pattern. What the flat did improve is the dust, at the level of a few tenths of a DN.',
    flat=dict(file=MASTER_FLAT, sha256=sha(MASTER_FLAT), which='the HYBRID of the M42 run (m42/calibration/flat-delivered.npy): the twilight master flat (26 sky flats, 1348 to 1407 UTC: dust, edge shading, pixel response) with the large-scale shape, above about 300 plane px, of this night\'s cloud-glow flat (m42/scripts/s6_twilight.py, s6_hybrid.py; m42/calibration/flat.json).',
              applied_as='step 6: every plane of every frame / that flat, instead of the cloud-glow flat x the M31 core run\'s dust map. Inside %d small patches (%.2f%% of the sensor) the flat is this hour\'s own measured response (step 2c).' % (C2['known_patches_wrong_for_this_hour'] + len(C2['blind_patches']), 100 * C2['marked_fraction_of_sensor'])),
    the_sensor_dome=dict(
        question='The first run found a pattern common to all stacks, fixed to the sensor: about -1.7 DN at the top and bottom edge against the middle (the v^2 term), and took it off as an additive pattern in the dark level. If it were a flat-field error instead, it should shrink or vanish with real flat frames.',
        v2_term_raw_dn_value_sigma=dome, all_terms={nm: ({c: pat(P, c) for c in 'RGB'} if P else None) for nm, P in variants.items()},
        second_road_no_overlaps_no_flat=dict(what='step 10b: raw block level against frame sky level over all 72 frames; the intercept is what is there without light', v2_term_raw_dn={pn: DK['planes'][pn]['d_fit_dn']['v^2'] for pn in PLANE_NAMES},
                                             with_the_first_runs_flat={pn: DKc['planes'][pn]['d_fit_dn']['v^2'] for pn in PLANE_NAMES} if DKc else None),
        answer='IT IS STILL THERE. Green: %.2f DN with the first run\'s flat, %.2f with the flat used now, %.2f with the twilight flat as measured (each +-0.06 to 0.07); red %.2f, %.2f, %.2f; blue %.2f, %.2f, %.2f. With the flat used it is %.0f%% smaller in green and %.0f%% in red and blue: a small part of it was flat, most of it is not. It is the same number of raw DN in three colours whose sky levels differ fivefold (red 7 to 57 DN, green 34 to 144), which a multiplicative error cannot do, and the second road, which uses neither overlaps nor any flat, finds it unchanged (%.2f, %.2f, %.2f, %.2f DN in R, G1, G2, B). So the first run read it rightly: an additive pattern in the sensor\'s dark level. Dark frames would measure it outright.' % (
            g('first_run_cloud_glow_flat'), g('hybrid_used'), g('twilight_as_measured') if P10a else float('nan'), dome['R']['first_run_cloud_glow_flat'][0], dome['R']['hybrid_used'][0], dome['R']['twilight_as_measured'][0] if P10a else float('nan'), dome['B']['first_run_cloud_glow_flat'][0], dome['B']['hybrid_used'][0], dome['B']['twilight_as_measured'][0] if P10a else float('nan'),
            100 * (1 - g('hybrid_used') / g('first_run_cloud_glow_flat')), 100 * (1 - (dome['R']['hybrid_used'][0] + dome['B']['hybrid_used'][0]) / (dome['R']['first_run_cloud_glow_flat'][0] + dome['B']['first_run_cloud_glow_flat'][0])), *[DK['planes'][pn]['d_fit_dn']['v^2'][0] for pn in PLANE_NAMES]),
        treatment_kept='model K, as before: one constant per stack and colour plus the four-number sensor pattern measured from the nine clear stacks. It leaves the clear stacks agreeing to %.2f DN rms in green; constants alone to %.2f.' % (table['G']['K']['hybrid_used'], table['G']['A']['hybrid_used'])),
    which_flat_and_why=dict(
        tested='the same stacks and overlaps three times: the first run\'s flat, the hybrid, and the twilight master flat as measured (2 to 3.5% brighter at the corners, tilted by 1.7% per 3000 px against the hybrid)',
        rms_between_clear_stacks_faint_blocks_dn=table, rms_pairs_with_a_cloud_stack_dn=table_cloud, noise_alone_green_dn=round(P10['models']['A']['G']['expected_noise_rms_dn_clear_pairs'], 2),
        reading='With constants alone (model A, where the shape of the flat shows most) the flat as measured is the worst of the three in every colour: green %.3f against %.3f (hybrid) and %.3f (first run); red %.2f against %.2f and %.2f; blue %.2f against %.2f and %.2f; and its dome is the largest. That is the second-order part (corners), which this target can see; a plain tilt it cannot. With the pattern taken off (model K) the three are within 2%% of each other (green %.3f, %.3f, %.3f). So this target sides, mildly, with the M42 run\'s choice: the HYBRID is used.' % (
            table['G']['A']['twilight_as_measured'], table['G']['A']['hybrid_used'], table['G']['A']['first_run_cloud_glow_flat'], table['R']['A']['twilight_as_measured'], table['R']['A']['hybrid_used'], table['R']['A']['first_run_cloud_glow_flat'],
            table['B']['A']['twilight_as_measured'], table['B']['A']['hybrid_used'], table['B']['A']['first_run_cloud_glow_flat'], table['G']['K']['first_run_cloud_glow_flat'], table['G']['K']['hybrid_used'], table['G']['K']['twilight_as_measured']) if P10a and P10c else None),
    is_the_dust_of_dawn_the_dust_of_this_hour=dict(
        how='step 2c: per stack the sum of its frames over the master flat, small-scale part; the median over the eleven pointings. The frames are faint, so this map has %.1f%% of noise per pixel (the M31 mosaic hour\'s: 0.3%%); the known patches of the M31 hours are tested one by one, the rest only above 4.5 sigma.' % (100 * C2['ratio_noise_sigma_2_5']),
        answer='As far as these frames can say, yes: where the master flat has a shadow deeper than 2%% this hour has it too (slope %.2f, correlation %.2f); what is left after the division is %+.2f%% of a 39 DN sky in the mean, under 0.1 DN.' % (d2['slope_this_hour_over_master'], d2['correlation'], 100 * d2['left_after_dividing_by_the_master_mean']),
        patches_wrong_for_this_hour=wrong, blind_patches=C2['blind_patches'], numbers={k: v for k, v in C2.items() if k not in ('known_patches_tested', 'blind_patches')},
        the_flats_own_flaw='where the hair lay at dawn (top edge, sensor px x 3700..3840, y 0..80) the delivered flat still dips by 5 to 9%: no data is taken from sensor px x 3660..3900, y 0..120.'),
    the_hair='unchanged: found per panel from its own frames (step 2b, with the first run\'s flats, so its circles are where they were), a circle of 200 sensor px left out of every frame. Never divided by any map.',
    before_and_after=dict(
        overlap_disagreement=dict(what='rms of 64 px block differences between clear stacks, faint blocks, model K (the one used), DN', before={c: table[c]['K']['first_run_cloud_glow_flat'] for c in 'RGB'}, after={c: table[c]['K']['hybrid_used'] for c in 'RGB'},
                                  with_a_cloud_stack=dict(before={c: table_cloud[c]['K']['first_run_cloud_glow_flat'] for c in 'RGB'}, after={c: table_cloud[c]['K']['hybrid_used'] for c in 'RGB'}),
                                  reading='between clear stacks: green %.3f -> %.3f DN, blue %.3f -> %.3f, red %.3f -> %.3f (noise alone 0.44, 1.06, 1.7 in that weighted solve). Two to three percent better in green and blue, the same in red. In the pairs with a cloud stack, which differ by their cloud glows, %.2f -> %.2f in green: no better.' % (
                                      table['G']['K']['first_run_cloud_glow_flat'], table['G']['K']['hybrid_used'], table['B']['K']['first_run_cloud_glow_flat'], table['B']['K']['hybrid_used'], table['R']['K']['first_run_cloud_glow_flat'], table['R']['K']['hybrid_used'], table_cloud['G']['K']['first_run_cloud_glow_flat'], table_cloud['G']['K']['hybrid_used']) if P10c else None),
        dust=dict(what_the_stacks_hold=ds, how='step 12d: at the 42 dust shadows of 3% and deeper, the median of green inside over a ring outside, minus 1, in every stack; the median over the stacks per place; mean and rms over the places',
                  reading=None if not ds else 'before: %+.2f%% in the mean, %.2f%% rms (%.2f DN rms, worst %+.1f DN on a 39 DN sky). After: %+.2f%%, %.2f%% rms (%.2f DN rms, worst %+.1f). The first run\'s dust map was three hours old and noisy; the twilight flat is neither. The share of each stack that was flagged as dust-divided (a quarter of the weight, kept out of the background fit) went from %.1f%% to %.2f%%.' % (
                      ds['before']['mean_percent'], ds['before']['rms_percent'], ds['before']['rms_dn'], ds['before']['worst_dn'], ds['after']['mean_percent'], ds['after']['rms_percent'], ds['after']['rms_dn'], ds['after']['worst_dn'],
                      100 * np.mean(list(ds['before']['flagged_fraction_per_stack'].values())), 100 * np.mean(list(ds['after']['flagged_fraction_per_stack'].values())))),
        colour_zeros=dict(what='64 px blocks of dark clear sky (green under 3 DN, no cloud stack): R - G and B - G', before=dc['before'], after=dc['after'],
                          reading='unchanged: red - green scatters by %.2f DN over the field before and %.2f after, blue - green by %.2f and %.2f (green itself %.2f and %.2f). They agreed before to about the noise of a block and still do; nothing to gain here.' % (
                              dc['before']['red_minus_green_dn']['robust_rms'], dc['after']['red_minus_green_dn']['robust_rms'], dc['before']['blue_minus_green_dn']['robust_rms'], dc['after']['blue_minus_green_dn']['robust_rms'], dc['before']['green_dn']['robust_rms'], dc['after']['green_dn']['robust_rms'])),
        noise=dict(pixel_scatter_in_dark_clear_blocks_dn=mo['pixel_scatter_in_the_darkest_quarter_of_clear_blocks_dn'], stack_noise_g1_dn=None if not ds else dict(before=ds['before']['stack_noise_g1_dn'], after=ds['after']['stack_noise_g1_dn']), reading='unchanged (within 0.5% in every stack and in the mosaic)'),
        how_much_the_picture_changed=dict(after_minus_before_block_medians_dn=mo['after_minus_before_block_medians_dn'], pixels_with_data=mo['pixels_with_data'],
                                          reading='64 px block medians of after - before, where no cloud stack contributes: %.2f DN rms in green (2 to 98%%: %+.1f to %+.1f), the same in red and blue. Side by side the two pictures cannot be told apart.' % (mo['after_minus_before_block_medians_dn']['G']['rms_about_median'], mo['after_minus_before_block_medians_dn']['G']['p02'], mo['after_minus_before_block_medians_dn']['G']['p98']))),
    hooks_added='the first run had none. Added: M45_MASTER_FLAT (c.py, steps 2c, 6, 10b), M45_WORK and M45_OUT (work folder and destination), step 2c (the flat against this hour), step 12d (before/after), step 14 (this). Without M45_MASTER_FLAT the scripts do what they did: run that way they reproduced the first run\'s steps 1 to 10 to the last digit.',
    files_written=sorted(k for k in os.listdir(OUT) if k.startswith('m45-mosaic') and 'level' not in k),
    before='before-flats/ beside this file holds every picture, tif and json as they were before the rerun',
    not_made_by_this_pipeline='m45-mosaic-level.png / .jpg / .json appeared in this folder while the rerun was running (another job, 10:23 local): a turned and cropped copy of the picture BEFORE the rerun. Left alone.',
    kept_for_reproduction=dict(folder=os.path.join(OUT, 'calibration-rerun'), files='leaveout_master.npy, nodata_master.npy, mismatch_master.npy (step 2c); p2c_masterflat_check.json, p10_background.json and the same for the two other flats (_cloud, _asis), p10b_dark_check.json, p12d_before_after.json'),
    how_to_run_it_again='PY=<python> M45_WORK=<scratch, 5 GB> M45_MASTER_FLAT=%s sh scripts/run_all.sh   (about 5 minutes; overwrites the deliverables)' % MASTER_FLAT)
# ---- sentences of the first run that no longer hold ----
cal = r['source']['calibration']
cal['first_run'] = dict(flat=cal['flat'], small_scale_flat=cal['small_scale_flat'])
cal['flat'] = 'RERUN: the master flat of real flat frames, m42/calibration/flat-delivered.npy (twilight dust, edge shading and pixel response; large-scale shape of the cloud-glow flat), per colour plane, 1 at the centre'
cal['small_scale_flat'] = 'RERUN: in the master flat. Checked against this hour in step 2c (see rerun_with_twilight_flat).'
cal['darks'] = 'none exist; see steps: the sensor pattern (still needed after the rerun)'
S_ = {s['step']: s for s in r['steps']}
S_['6 stack']['detail'] = S_['6 stack']['detail'].replace('frame / (smooth flat x small-scale flat) / transparency', 'frame / master flat / transparency').replace('Pixels under mapped dust are kept (divided by the shadow\'s transmission) and flagged.', 'RERUN: nothing is flagged for dust any more except the few patches of step 2c; the dawn hair\'s zone gives no data.')
S_['2b the hair']['detail'] = S_['2b the hair']['detail'] + ' (RERUN: unchanged, with the first run\'s flats, so the circles are where they were.)'
S_['9 resample']['detail'] = S_['9 resample']['detail'].replace('dust-divided pixels count a quarter', 'flagged pixels (step 2c\'s patches) count a quarter')
S_['10 background']['why'] = S_['10 background']['why'] + ' RERUN: with real flat frames the dome is still there (see rerun_with_twilight_flat.the_sensor_dome), so it is not a flat-field error.'
dn = list(r['do_not_trust'])
r['do_not_trust'] = dn
r['what_would_help_most'] = [t.replace('Clean the sensor (the hair and the dust shadows cost three holes and 8% of the pixels a quarter of their weight).', 'Clean the sensor (the hair costs three holes; the dust is now divided out with the dawn flat).') for t in r['what_would_help_most']]
r['scripts']['folder'] = 'scripts/ beside this file (run_all.sh runs them in order; they read the RAWs in place and need the flat arrays of the M31 run, and for the rerun the master flat of the M42 run)'
keep = os.path.join(OUT, 'calibration-rerun'); os.makedirs(keep, exist_ok=True)
for f in ('leaveout_master.npy', 'nodata_master.npy', 'mismatch_master.npy', 'p2c_masterflat_check.json', 'p10_background.json', 'p10_background_cloud.json', 'p10_background_asis.json', 'p10b_dark_check.json', 'p10b_dark_check_cloud.json', 'p10b_dark_check_asis.json', 'p12d_before_after.json'):
    if os.path.exists(W(f)): shutil.copy2(W(f), keep)
json.dump(r, open(rp, 'w'), indent=1)
dst = os.path.join(OUT, 'scripts')
for f in ('p14_rerun_notes.py', 'run_all.sh'):
    if os.path.abspath(os.path.join(SCR, f)) != os.path.abspath(os.path.join(dst, f)): shutil.copy2(os.path.join(SCR, f), dst)
print('recipe with the rerun notes:', os.path.getsize(rp), 'bytes')
R_ = r['rerun_with_twilight_flat']
print(' - dome:', R_['the_sensor_dome']['answer']); print(' - flat:', R_['which_flat_and_why']['reading'])
for k in ('overlap_disagreement', 'dust', 'colour_zeros', 'how_much_the_picture_changed'): print(' -', k + ':', R_['before_and_after'][k]['reading'])
