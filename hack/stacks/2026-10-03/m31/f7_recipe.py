"""Rerun step f7: the recipe again. The core run's recipe (before-flats/m31-core-recipe.json) is the base: the frames,
the selection, the registration, versions A and C and everything that did not change stay as they were written;
what the rerun with the twilight-based flat changed is added and the entries of the main picture are replaced."""
import json, os, sys, datetime, hashlib, shutil
import numpy as np
from common import *
CAL = os.path.join(NIGHT, 'm42', 'calibration'); KEEP = os.path.join(OUT, 'calibration-rerun')
old = json.load(open(os.path.join(OUT, 'before-flats', 'm31-core-recipe.json')))
ev = json.load(open(W('f5_evaluate.json'))); sm = json.load(open(W('f5b_smudge.json'))); d6 = json.load(open(W('f6_deliver.json'))); hair = json.load(open(W('f2_hair.json'))); lo = json.load(open(W('f3_leaveout.json')))
ctl = json.load(open(W('f4_control.json'))); s8 = json.load(open(W('step8_F.json'))); pl = json.load(open(W('f1_planes.json'))); flatj = json.load(open(os.path.join(CAL, 'flat.json')))
def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()
r = dict(old)
r['made_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
r['first_made_utc'] = old['made_utc']
r['what'] = old['what'] + '; main picture re-made on 2026-10-04 with the flat built from that morning\'s twilight sky frames'
DF = lambda v, k: ev['dust'][v][k]['fraction_of_pattern_left']
ALL = 'all shadows deeper than 0.3%'
hc = [v['centre_sensor_xy'] for v in hair['every_frame'].values() if v]
left = d6['shadows']['shadows_left']
r['rerun_with_twilight_flat'] = dict(
    why='The core run had no flat frames. On the morning after, 26 twilight sky flats were taken; the M42 run built a master flat from them. This rerun divides every frame by that flat and re-makes the MAIN picture (m31-core.*). Frames, selection, weights, registration, scaling, the one constant per frame, the clip, the crop, the zero rule, the colour and the stretch are the core run\'s, unchanged.',
    flat=dict(file=os.path.join(CAL, 'flat-delivered.npy'), sha256=sha(os.path.join(CAL, 'flat-delivered.npy')), layout='float32 (4, 2012, 3012), planes R, G1, G2, B, each 1 at the sensor centre',
              what=flatj['what'], how_it_was_made=os.path.join(CAL, 'flat.json') + ' and m42/scripts/s6_twilight.py, s6_hybrid.py',
              which_variant='the HYBRID (twilight dust, edge shading and pixel response; large-scale shape, above about 300 plane px, from this night\'s cloud-glow flat), the one the M42 run delivered with',
              why_this_variant='tested on the two mosaics of this night, not here: for the core alone the choice hardly matters at small scale (the dust is the same in both variants) and cannot be tested at large scale (the field moves only 170 px). M31 mosaic (m31/mosaic/m31-mosaic-recipe.json, rerun_with_twilight_flat.which_flat_and_why): the six panels cannot tell the two apart; with one plane per panel they agree to 3%, and a tilt of the flat times a moonlit sky is the same thing there as the Moon\'s own gradient. M45 mosaic (m45/m45-mosaic-recipe.json, same key): with constants alone the flat as measured is the worse of the two in every colour (green 0.96 against 0.92 DN rms between clear stacks) and leaves the larger second-order pattern. The M42 run found the same on its own panels (tilts and negative far ends with the flat as measured; 1.3 DN with constants alone under the hybrid). So the hybrid, for all of them.',
              large_scale_consequence='the hybrid\'s large-scale shape IS the cloud-glow flat\'s (their ratio over 256 px: 0.999 to 1.003), so at large scale the new main picture is the core run\'s extra version C by construction. What the twilight frames add is the dust, the pixel-scale response and a flat near the nucleus, where the cloud-glow flat was blind.'),
    is_the_dust_of_dawn_the_dust_of_this_hour=dict(
        how='this run\'s own cloud-glow flat (cloudflat.npy, 36 clouded frames, sensor coordinates) is the sensor\'s response between 0736 and 0846 UTC; the twilight flat was taken at 1348 to 1407 UTC. Green, each over its own wide smooth part.',
        answer='yes, with a few exceptions. Where the twilight flat shows a shadow deeper than 2%% (74892 plane px) the core-hour flat shows the same depth: slope 1.007, correlation 0.95; after dividing the core-hour flat by the twilight-based flat what is left there is 0.0%% in the mean and 0.85%% rms, against 0.52%% of noise in the core-hour flat itself. Exceptions, found by the same division (step f3): %d patches (%.2f%% of the sensor) where the two differ by more than 2%% (or 1.4%% in a wider blur). Most are what is left of stars in the cloud-glow flat (pairs of a dark and a light dot). Real ones: a mote that was there in this hour and gone by dawn (sensor px 1046, 3304, 4%% deep), one that came later (2863, 3527, 6%%), a ring that changed (3194, 1465), one that deepened (5348, 3435). All of them are LEFT OUT of the average, not divided.' % (lo['patches'], 100 * lo['marked_fraction_of_sensor']),
        thresholds=lo['thresholds'], ratio_noise=dict(sigma_2_5=lo['ratio_noise_sigma_2_5'], sigma_4=lo['ratio_noise_sigma_4']), not_judged=lo['not_judged'], largest_patches=lo['all_patches'][:12],
        the_flats_own_flaw='where the hair lay at dawn (top edge, sensor px x 3700..3840, y 0..80) the delivered flat was patched with its own smooth part, which still dips there by 5% (9% against this hour\'s response). Sensor px x 3660..3900, y 0..120 are left out for that reason. It is outside this picture\'s crop for most frames.'),
    the_hair=dict(
        rule='never divided, never taken from a fixed map. Found afresh in every one of the 109 frames of the run (the clouded ones show it best): green over the flat\'s smooth part, blurred sigma 3 plane px, over its own 61 px grey closing; the largest patch below 0.86, 300 to 8000 plane px, out to its 0.93 contour. A used frame\'s mask is the union of the patches of the frames within 100 s of it, grown by 12 plane px (24 sensor px); those samples are left out of the average.',
        found_in_frames=sum(1 for v in hair['every_frame'].values() if v), of_frames=len(hair['every_frame']),
        centre_first_last_sensor_px=[hc[0], hc[-1]], centre_x_range=[min(c[0] for c in hc), max(c[0] for c in hc)], centre_y_range=[min(c[1] for c in hc), max(c[1] for c in hc)],
        mask_plane_px_range=[min(v['masked_plane_px'] for v in hair['used'].values()), max(v['masked_plane_px'] for v in hair['used'].values())],
        margin='12 plane px: measured in seven clouded frames, the shadow beyond the 0.93 contour is 0.951 in the first 4 plane px, 0.984 in the next 4, 0.995 in the next, 0.998 to 1.000 from 12 px on. (A first pass with the M42 run\'s 30 px made the smudge twice as large as before; the field only moves +-110 px in x and +-45 px in y.)',
        what_is_left='the field does not move far enough to clear it: where fewer than 12 frames are clear of the hair the combine with it left in is blended in (fully below 4), as the core run did for dust, and the picture is dark there. ' + json.dumps(left[0]) if left else 'nothing',
        smudge_before_and_after=sm, smudge_reading='against the old main picture (B) the smudge is the same depth (23 DN) and about the same size (10973 against 10415 sensor px more than 10 DN low; 17361 against 25477 more than 5 DN low). Against the old extra (C) it is larger and deeper (C had divided it by a fixed map of the hair, 2696 px more than 10 DN low, 18 DN deep): that division is not done any more, on purpose.'),
    control=dict(what='the new stacking script (f4_stack.py) run with the core run\'s own cloud flat and dust mask on plane G1, from RAW planes repaired again (the cache had been deleted)', result=ctl, spike_counts_equal_to_the_core_run_in_all_frames=pl['all_equal'],
                 reading='identical to the core run\'s version C to the last bit: whatever differs between old and new is the flat and the leave-out rule, nothing else.'),
    stack=dict(script='f4_stack.py F', planes=s8['planes'], samples_left_out_fraction=float(s8['planes'][1]['samples_left_out'] / s8['planes'][1]['samples_in_coverage']), before_version_C_left_out_fraction=0.0706),
    before_and_after=dict(
        versions='A as recorded (unchanged); B = the old main picture (radial profile, dust left out); C = the old extra (whole cloud-glow flat, dust left out, five shadow cores divided); F = the new main picture (twilight-based flat).',
        sensor_dust_left_in_the_picture=dict(
            how='the dust pattern a stack would hold with nothing done about it (the twilight flat\'s dust, carried onto the picture with every frame\'s registration and weight) fitted to each version\'s high-passed green over its level; the slope is the fraction of that pattern still in the picture. Checked on A, where nothing was done: %.2f +- %.2f.' % (DF('A', ALL), ev['dust']['A'][ALL]['error']),
            fraction_left={v: dict(all_shadows=round(DF(v, ALL), 3), error=round(ev['dust'][v][ALL]['error'], 3), left_rms_dn=round(ev['dust'][v][ALL]['left_rms_dn'], 2), shadows_deeper_than_1pct=round(DF(v, 'deeper than 1%'), 3)) for v in 'ABCF'},
            reading='B kept about 30%% of the dust pattern (0.37 DN rms; in the shadows deeper than 1%%, %.0f%% more than F, about 2 DN); C and F keep none that can be measured (%.2f +- %.2f and %.2f +- %.2f). The subset of shadows deeper than 2%% is too small to read (a slope of 2.6 in C and F alike: galaxy structure, not dust).' % (100 * (DF('B', 'deeper than 1%') - DF('F', 'deeper than 1%')), DF('C', ALL), ev['dust']['C'][ALL]['error'], DF('F', ALL), ev['dust']['F'][ALL]['error']),
            the_four_smudges='the four 6 to 8% smudges the old recipe lists for B (and the fainter ones in its dust map) are gone: they were shadow cores that could not be left out; they are now divided by the flat that shows them.',
            still_in_the_picture=left),
        flat_field_test_first_third_minus_last_third=dict(what='check_flat.py: green, the field sits 170 px away and turned 2.3 degrees between the two', per_version=ev['early_minus_late'],
            reading='on 256 px blocks C and F show the same slope (1.4 and -1.9 DN per 3000 px: the sky\'s own gradient changed during the hour, see do_not_trust) and after it 0.39 and 0.35 DN; B 0.62. On 64 px blocks about their local mean (dust and noise): A 1.34, B 1.09, C 1.07, F %.2f DN: F is the smoothest, because nothing is left out along dust tracks any more and the faint rings under the old thresholds are divided out too.' % ev['early_minus_late']['F']['rms_64px_blocks_about_their_9x9_mean_dn']),
        large_scale=dict(F_minus_C=ev['large_scale']['F_minus_C'], F_minus_B={k: v for k, v in ev['large_scale']['F_minus_B'].items() if k != 'blocks'},
            reading='F - C on 256 px blocks: 0.24 DN rms (largest: -1.9 DN just south of the nucleus, where the cloud-glow flat was blind and C\'s flat was interpolated). F - B: a tilt of +-8 DN across the frame, which is the tilt and edge shading the old main picture left in.'),
        colour_of_the_outer_glow=dict(what='384 px blocks with 6 to 30 DN of green: red / green and blue / green after the as-shot white balance', per_version=d6['outer_glow_colour'], bulge=d6['bulge_colour'],
            reading='old main picture (B): red / green 1.34 (1.07 to 1.54), brown. New main picture: 1.03 (0.80 to 1.14), the colour of the bulge (1.06), as in C (1.04). Blue / green 0.94 in all. The spread (0.80 to 1.14) is the limit: 1 DN of red is 2.75 DN after white balance.'),
        noise=dict(stack_per_plane_dn=ev['noise'], reading='unchanged. In the same patch: F %.2f DN (G1) against B %.2f and C %.2f; the 2%% over B is the larger division by the flat in that corner (the whole flat is lower there than the radial profile), not more noise in the data.' % (ev['noise']['F']['G1'], ev['noise']['B']['G1'], ev['noise']['C']['G1'])),
        zero=dict(F=d6['zero'], C=old['steps'][[s['step'] for s in old['steps']].index('zero level')]['per_version']['C'])),
    files_written=['m31-core.png', 'm31-core.jpg', 'm31-core-dust.png', 'm31-core-dust.jpg', 'm31-core-linear.tif', 'm31-core-coverage.tif', 'm31-core-sensor-dust-map.png', 'm31-core-recipe.json'],
    files_left_as_the_core_run_made_them=['m31-core-as-recorded.png / .jpg (A: no flat at all)', 'm31-core-cloudflat.png / .jpg, m31-core-cloudflat-starwhite.png / .jpg, m31-core-dust-cloudflat.png / .jpg, m31-core-cloudflat-linear.tif (C: the cloud-glow flat; kept as the comparison)'],
    before='before-flats/ beside this file holds every picture, tif and json as they were before the rerun',
    kept_for_reproduction=dict(folder=KEEP, files={'cloudflat.npy': 'the core run\'s cloud-glow flat (step 6), float32 (4, 2012, 3012): the sensor\'s response during this hour; input of step f3', 'f3_leaveout.npy': 'boolean (2012, 3012): sensor pixels left out (flat not valid for this hour, and the dawn hair\'s place)',
                                                   'f2_hair.json': 'the hair in every frame: centre, area, depth, box; and each used frame\'s mask', 'f2_hair.npz': 'each used frame\'s hair mask (packed bits, m_<stamp>) and transmission window (t_<stamp>)'}),
    scripts='scripts/f1_planes.py, f2_hair.py, f3_leaveout.py, f4_stack.py F, f5_evaluate.py, f5b_smudge.py, f6_deliver.py, f7_recipe.py, with M31_WORK=<scratch holding the core run\'s step JSONs>, M31_MASTER_FLAT=<flat-delivered.npy>, M31_OLD_WORK=<the core run\'s work folder, for the comparisons only>')
r['which_picture_is_which'] = dict(
    A=old['which_picture_is_which']['A'],
    MAIN=dict(files=['m31-core.png', 'm31-core.jpg', 'm31-core-dust.png', 'm31-core-dust.jpg', 'm31-core-linear.tif'], version='F',
              what='FLAT-FIELDED WITH REAL FLAT FRAMES (re-made 2026-10-04): each colour plane of each frame divided by the master flat of the morning\'s twilight sky flats (dust, edge shading, pixel response) with the large-scale shape of this night\'s cloud-glow flat. The hair is cut out frame by frame. Before the rerun these files held version B (radial profile only, dust left out): those are in before-flats/.'),
    C=dict(old['which_picture_is_which']['C'], what=old['which_picture_is_which']['C']['what'] + ' UNCHANGED by the rerun; at large scale the new main picture agrees with it to 0.24 DN rms.'))
steps = []
for s in old['steps']:
    s = dict(s)
    if s['step'] in ('vignetting profile (versions B and C)', 'what the radial profile leaves in (version B)', 'dust shadows'): s['note'] = 'core run, versions B and C. The main picture no longer uses this (see the steps marked rerun).'
    if s['step'] == 'zero level': s['per_version'] = dict(s['per_version'], F=d6['zero'])
    if s['step'] == 'combine': s['per_plane'] = dict(s['per_plane'], F=s8['planes'])
    steps.append(s)
i = [s['step'] for s in steps].index('dust shadows') + 1
steps[i:i] = [
    dict(step='rerun: flat field (main picture, version F)', detail='each plane of each frame divided by the master flat (m42/calibration/flat-delivered.npy): ' + flatj['what'] + '. Nothing is left out for dust as such: the flat holds every shadow.', flat_min_max=flatj['flat_min_max']),
    dict(step='rerun: the hair (version F)', detail=r['rerun_with_twilight_flat']['the_hair']['rule']),
    dict(step='rerun: sensor pixels where the dawn flat is not this hour\'s response (version F)', detail='this run\'s cloud-glow flat over the twilight-based flat, each green over its wide smooth part; marked where a sigma 2.5 copy is more than 2%% from 1 or a sigma 4 copy more than 1.4%%, blobs of 60 plane px or more, grown by 6 px; plus the dawn hair\'s place at the top edge. %d patches, %.2f%% of the sensor. LEFT OUT of the average; where fewer than 12 clean frames are left the combine with them left in is blended in (fully below 4).' % (lo['patches'], 100 * lo['marked_fraction_of_sensor']))]
r['steps'] = steps
r['numbers'] = dict(old['numbers'])
r['numbers']['noise'] = dict(d6['noise'], raw_plane_single_frame_dn=old['numbers']['noise']['raw_plane_single_frame_dn'], raw_plane_note=old['numbers']['noise']['raw_plane_note'], version='F (the main picture after the rerun)')
r['numbers']['stars_in_the_stack'] = dict(old['numbers']['stars_in_the_stack'], **d6['stars_in_the_stack'])
r['numbers']['glow_block_medians'] = dict(what=old['numbers']['glow_block_medians']['what'], F=d6['glow_block_medians'], C=old['numbers']['glow_block_medians']['C'])
r['numbers_before_the_rerun'] = dict(note='version B, the main picture before the rerun', noise=old['numbers']['noise'], stars_in_the_stack=old['numbers']['stars_in_the_stack'], glow_block_medians_B=old['numbers']['glow_block_medians']['B'])
o = dict(old['outputs'])
o['m31-core.png / .jpg'] = dict(old['outputs']['m31-core.png / .jpg'], version='F', **d6['outputs']['m31-core'])
o['m31-core-dust.png / .jpg'] = dict(old['outputs']['m31-core-dust.png / .jpg'], version='F', **d6['outputs']['m31-core-dust'])
o['m31-core-linear.tif'] = dict(old['outputs']['m31-core-linear.tif'], version='F')
o['m31-core-coverage.tif'] = dict(what='8-bit: the number of frames used at each pixel (green plane, version F: after the hair, the left-out pixels and the clip), same grid as the linear file; 38 = all')
o['m31-core-sensor-dust-map.png'] = dict(what='diagnostic, half scale, same geometry as m31-core.png: where a sensor shadow is still in the MAIN picture and how deep (white = none, black = 20% of the light or more). After the rerun that is the hair, and one small patch at the bottom-left edge where the dawn flat is not this hour\'s response (marked as a shadow of the size of the mismatch, whichever its sign).',
                                         check='what the left-in combine holds, predicted from each frame\'s measured hair transmission, against the stack where both combines exist: measured = %.2f x predicted, correlation %.2f' % (d6['shadows']['check_against_stack']['measured_over_predicted'], d6['shadows']['check_against_stack']['correlation']))
r['outputs'] = o
r['do_not_trust'] = [
    old['do_not_trust'][0],
    'The large-scale shape of the main picture rests on the cloud-glow flat (the twilight flat\'s own large-scale shape was not used: it is 2 to 3.5% brighter at the corners and tilted by 1.7% per 3000 px against it, and the mosaic panels disagree with each other under it). So the outer glow, its brightness to the left against the right and its colour are as trustworthy as that flat: the glow now has the colour of the bulge everywhere (red / green 1.03 against 1.06), which is why it is believed, but that is the same evidence the old extra version C rested on. The twilight frames did not add an independent check of the tilt.',
    old['do_not_trust'][2],
    old['do_not_trust'][3],
    'One black smudge near the top edge, right of centre (whole-field picture px about 1886, 102; sensor px 3880, 313; 187 x 143 sensor px): the hair on the sensor. It is cut out of every frame, but the field does not move far enough to clear it, so the middle of its track has no clean frame and shows the shadow itself (up to 23 DN low). It is not divided out. Not sky.',
    'The sensor dust: divided out with the dawn flat, which was taken five to six hours after these frames. Where the dust had not moved (nearly everywhere: depth for depth, slope 1.007) nothing measurable is left (fraction of the pattern left -0.06 +- 0.07). Where the two hours differ the pixels were left out instead; a patch the test could not see (it is blind within 480 px of the nucleus) would be in the picture as a ring or spot of up to a few percent, smeared 150 to 250 px along the drift.',
    old['do_not_trust'][8], old['do_not_trust'][9], old['do_not_trust'][10],
    'The corners: fewer frames (see the coverage file) and the strongest flat correction (divided by 0.66 to 0.72 at the very corner), so the grain is 1.4 to 1.5 times coarser there.']
r['what_would_help_most'] = [old['what_would_help_most'][0],
    'Flats taken the same night, at the same focus, with an even lamp or panel over the aperture: the dawn sky flats settled the dust and the edge shading, but their large-scale shape did not agree with the night sky (stray light at the corners, the dawn sky\'s own gradient), so the tilt still rests on the cloud.',
    old['what_would_help_most'][2], 'Moving the field on purpose between frames by more than 400 px: then the hair can be cleared everywhere and no smudge is left.', old['what_would_help_most'][4], 'Clean the sensor (the hair).']
r['scripts'] = old['scripts'] + ' RERUN (2026-10-04): f1_planes.py, f2_hair.py, f3_leaveout.py, f4_stack.py F, f5_evaluate.py, f5b_smudge.py, f6_deliver.py, f7_recipe.py.'
r['tools'] = old['tools']
os.makedirs(KEEP, exist_ok=True)
for f in ('cloudflat.npy', 'f3_leaveout.npy', 'f2_hair.json', 'f2_hair.npz', 'f3_leaveout.json', 'f5_evaluate.json', 'f6_deliver.json'): shutil.copy2(W(f), KEEP)
json.dump(r, open(os.path.join(OUT, 'm31-core-recipe.json'), 'w'), indent=1)
print('recipe written:', os.path.getsize(os.path.join(OUT, 'm31-core-recipe.json')), 'bytes; keys', list(r.keys()))
