"""Step 5: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

The tracking bug of earlier tonight (both motors let go for about 5 s now and then) was fixed at 08:19 UTC, before this
run, so no frame should be trailed; the frames are still selected by star shape and size, as the skill says.

A frame is used if: common-direction smear (trailing) <= SMEAR_MAX (0.20, the skill's 8 October note); stars no wider
than HFD_MAX_REL x the median half-flux diameter of the unsmeared frames; transparency >= T_MIN; registration weighted
rms <= WRMS_MAX px; not within SLEW_MIN_S of a move; and it is not the first frame after the slew to the target
(DROP_FIRST: the skill's rule, applied whatever that frame measures; its numbers are in the recipe).

Used frames are multiplied by 1 / transparency (so that they agree) and averaged with weight (transparency / noise)^2,
noise = the frame's own zero-level pixel noise over the run's median: the inverse variance of the scaled frame."""
import json, os, numpy as np
from common import *

LIMITS = dict(hfd_max_rel=float(os.environ.get('N891_HFD_MAX_REL', '1.20')), smear_max=float(os.environ.get('N891_SMEAR_MAX', '0.20')),
              transparency_min=0.90, registration_wrms_max_px=1.0, since_slew_min_s=10.0, drop_first_frame_after_slew=os.environ.get('N891_DROP_FIRST', '1') == '1')
Q = jload('step4_quality.json'); q = {o['stamp']: o for o in Q['quality']}
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
stamps = sorted(q)
hfd_med = float(np.median([q[s]['hfd_px'] for s in stamps if q[s]['smear'] <= LIMITS['smear_max']])); noise0 = float(np.median([q[s]['noise_zero_dn'] for s in stamps]))
with_slew = [s for s in stamps if q[s]['since_slew_s'] is not None]
first_after_slew = min(with_slew, key=lambda s: q[s]['since_slew_s']) if with_slew else stamps[0]
use, rej = [], []
for s in stamps:
    o = q[s]; why = []
    if o['hfd_px'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the median of the unsmeared frames, %.2f (limit %.0f%%)' % (o['hfd_arcsec'], 100 * (o['hfd_px'] / hfd_med - 1), hfd_med * SCALE, 100 * (LIMITS['hfd_max_rel'] - 1)))
    if o['smear'] > LIMITS['smear_max']: why.append('smeared: every star stretched the same way, common ellipticity %.2f at %.0f deg (limit %.2f); median elongation %.2f' % (o['smear'], o['smear_angle_deg'], LIMITS['smear_max'], o['elong_median']))
    if o['transparency'] < LIMITS['transparency_min']: why.append('stars at %.0f%% of their usual brightness (limit %.0f%%)' % (100 * o['transparency'], 100 * LIMITS['transparency_min']))
    if o['since_slew_s'] is not None and o['since_slew_s'] < LIMITS['since_slew_min_s']: why.append('taken %.0f s after a move (limit %.0f s)' % (o['since_slew_s'], LIMITS['since_slew_min_s']))
    if tr[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[s]['wrms_px'])
    if LIMITS['drop_first_frame_after_slew'] and s == first_after_slew: why.append('the first frame after the slew to the target (%.0f s after it): dropped by rule; it measured stars of %.2f arcsec, smear %.2f, transparency %.3f' % (o['since_slew_s'] or -1, o['hfd_arcsec'], o['smear'], o['transparency']))
    if why:
        rej.append(dict(stamp=s, why='; '.join(why), transparency=o['transparency'], hfd_arcsec=o['hfd_arcsec'], smear=o['smear'], step_from_previous_px=o['step_from_previous_px'])); continue
    nrel = o['noise_zero_dn'] / noise0 / o['transparency']
    use.append(dict(stamp=s, transparency=o['transparency'], scale=1.0 / o['transparency'], noise_rel=nrel, weight=1.0 / nrel ** 2, hfd_arcsec=o['hfd_arcsec'], smear=o['smear']))
trailed = [r for r in rej if r['smear'] > LIMITS['smear_max']]
jdump(dict(limits=LIMITS, trailed=len(trailed), dropped_for_size_only=len([r for r in rej if r['smear'] <= LIMITS['smear_max']]), hfd_run_median_px=hfd_med, hfd_run_median_arcsec=hfd_med * SCALE, noise_run_median_dn=noise0, used=use, rejected=rej,
           effective_frames=float(sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use))), 'step5_select.json')
print('median HFD of the unsmeared frames %.2f px = %.2f arcsec; used %d, rejected %d; effective frames %.2f' % (hfd_med, hfd_med * SCALE, len(use), len(rej), sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use)))
for u in use: print('  use', u['stamp'], 'T %.3f w %.3f HFD %.2f" smear %.3f' % (u['transparency'], u['weight'], u['hfd_arcsec'], u['smear']))
for r in rej: print('  DROP', r['stamp'], r['why'])
