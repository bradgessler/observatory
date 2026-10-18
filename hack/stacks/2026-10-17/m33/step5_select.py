"""Step 5: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

A frame is used if: common-direction smear (trailing) <= SMEAR_MAX (0.20, the skill's rule: someone at the telescope, the
hold settling, a periodic wobble); stars no wider than HFD_MAX_REL x the median half-flux diameter of the unsmeared
frames of ITS NIGHT (13 October's seeing was better: one limit for both would drop tonight for being tonight);
transparency >= T_MIN of its turn's median (the turns differ in altitude and sky: light lost is judged against the
turn's own clear plateau); registration weighted rms <= WRMS_MAX px; not within SLEW_MIN_S of a move (a slew, a centring
or a dither step); and it is not the first frame after the slew to the target in a turn (DROP_FIRST: the skill's rule,
applied whatever that frame measures; its numbers are in the recipe). Dither steps are moves but not slews to the target:
the frames after them are judged by the 10 s rule and by their stars.

Used frames are multiplied by 1 / transparency (absolute: the frames are brought to one brightness) and averaged with
weight (transparency / noise)^2, noise = the frame's own zero-level pixel noise over the median of all frames."""
import json, os, numpy as np
from common import *

LIMITS = dict(hfd_max_rel=float(os.environ.get('M33_HFD_MAX_REL', '1.20')), smear_max=float(os.environ.get('M33_SMEAR_MAX', '0.20')),
              transparency_min=0.90, registration_wrms_max_px=1.0, since_slew_min_s=10.0, drop_first_frame_after_slew=os.environ.get('M33_DROP_FIRST', '1') == '1')
Q = jload('step4_quality.json'); q = {o['stamp']: o for o in Q['quality']}
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
stamps = sorted(q)
S1 = {f['stamp']: f for f in jload('step1.json')['frames']}
turn = {s: S1[s]['turn'] for s in stamps}; night = {s: S1[s]['night'] for s in stamps}
hfd_night = {n: float(np.median([q[s]['hfd_px'] for s in stamps if night[s] == n and q[s]['smear'] <= LIMITS['smear_max']])) for n in set(night.values())}
t_turn = {t: float(np.median([q[s]['transparency'] for s in stamps if turn[s] == t])) for t in set(turn.values())}
hfd_med = float(np.median([q[s]['hfd_px'] for s in stamps if q[s]['smear'] <= LIMITS['smear_max']])); noise0 = float(np.median([q[s]['noise_zero_dn'] for s in stamps]))
first_after_slew = set()
for t in set(turn.values()):
    ss = sorted(s for s in stamps if turn[s] == t)
    for i, s in enumerate(ss):
        v = q[s]['since_slew_s']
        if v is None: continue
        if i == 0 and v < 120: first_after_slew.add(s)
        elif i > 0 and q[ss[i - 1]]['since_slew_s'] is not None and v < q[ss[i - 1]]['since_slew_s'] and not S1[s].get('dither') and v < 120: first_after_slew.add(s)
use, rej = [], []
for s in stamps:
    o = q[s]; why = []
    hm = hfd_night[night[s]]
    if o['hfd_px'] > LIMITS['hfd_max_rel'] * hm: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the median of that night\'s unsmeared frames, %.2f (limit %.0f%%)' % (o['hfd_arcsec'], 100 * (o['hfd_px'] / hm - 1), hm * SCALE, 100 * (LIMITS['hfd_max_rel'] - 1)))
    if o['smear'] > LIMITS['smear_max']: why.append('smeared: every star stretched the same way, common ellipticity %.2f at %.0f deg (limit %.2f); median elongation %.2f' % (o['smear'], o['smear_angle_deg'], LIMITS['smear_max'], o['elong_median']))
    if o['transparency'] < LIMITS['transparency_min'] * t_turn[turn[s]]: why.append('stars at %.0f%% of their usual brightness in turn %s (limit %.0f%%)' % (100 * o['transparency'] / t_turn[turn[s]], turn[s], 100 * LIMITS['transparency_min']))
    if o['since_slew_s'] is not None and o['since_slew_s'] < LIMITS['since_slew_min_s']: why.append('taken %.0f s after a move (limit %.0f s)' % (o['since_slew_s'], LIMITS['since_slew_min_s']))
    if tr[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[s]['wrms_px'])
    if LIMITS['drop_first_frame_after_slew'] and s in first_after_slew: why.append('the first frame after the slew to the target (%.0f s after it): dropped by rule; it measured stars of %.2f arcsec, smear %.2f, transparency %.3f' % (o['since_slew_s'] or -1, o['hfd_arcsec'], o['smear'], o['transparency']))
    if why:
        rej.append(dict(stamp=s, turn=turn[s], why='; '.join(why), transparency=o['transparency'], hfd_arcsec=o['hfd_arcsec'], smear=o['smear'], step_from_previous_px=o['step_from_previous_px'])); continue
    nrel = o['noise_zero_dn'] / noise0 / o['transparency']
    use.append(dict(stamp=s, turn=turn[s], night=night[s], transparency=o['transparency'], scale=1.0 / o['transparency'], noise_rel=nrel, weight=1.0 / nrel ** 2, hfd_arcsec=o['hfd_arcsec'], smear=o['smear']))
trailed = [r for r in rej if r['smear'] > LIMITS['smear_max']]
jdump(dict(limits=LIMITS, hfd_night_median_arcsec={n: v * SCALE for n, v in hfd_night.items()}, transparency_turn_median=t_turn, first_after_slew=sorted(first_after_slew), trailed=len(trailed), dropped_for_size_only=len([r for r in rej if r['smear'] <= LIMITS['smear_max']]), hfd_run_median_px=hfd_med, hfd_run_median_arcsec=hfd_med * SCALE, noise_run_median_dn=noise0, used=use, rejected=rej,
           effective_frames=float(sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use))), 'step5_select.json')
print('median HFD of the unsmeared frames %.2f px = %.2f arcsec; used %d, rejected %d; effective frames %.2f' % (hfd_med, hfd_med * SCALE, len(use), len(rej), sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use)))
for u in use: print('  use', u['stamp'], 'T %.3f w %.3f HFD %.2f" smear %.3f' % (u['transparency'], u['weight'], u['hfd_arcsec'], u['smear']))
for r in rej: print('  DROP', r['stamp'], r['turn'], r['why'])
for t in ('1a', '1b', '2', '13oct'):
    print('turn %-5s used %3d dropped %3d' % (t, sum(u['turn'] == t for u in use), sum(r['turn'] == t for r in rej)))
