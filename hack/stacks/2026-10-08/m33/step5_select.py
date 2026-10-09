"""Step 5: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

A frame is used if: stars no wider than HFD_MAX_REL x the run's median half-flux diameter; common-direction smear
(trailing) <= SMEAR_MAX; transparency >= T_MIN; registration weighted rms <= WRMS_MAX px. The night was clear (every
frame but the smeared one within 2% of the run's median star brightness), so the cuts that bite are star size and
smear: frames taken while the mount was settling after a nudge or drifting during the exposure.

Used frames are multiplied by 1 / transparency (so that they agree) and averaged with weight (transparency / noise)^2,
noise = the frame's own zero-level pixel noise over the run's median: the inverse variance of the scaled frame."""
import json, os, numpy as np
from common import *

LIMITS = dict(hfd_max_rel=float(os.environ.get('M33_HFD_MAX_REL', '1.15')), smear_max=float(os.environ.get('M33_SMEAR_MAX', '0.25')),
              transparency_min=0.90, registration_wrms_max_px=1.0)
Q = jload('step4_quality.json'); q = {o['stamp']: o for o in Q['quality']}
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
stamps = sorted(q)
hfd_med = float(np.median([q[s]['hfd_px'] for s in stamps])); noise0 = float(np.median([q[s]['noise_zero_dn'] for s in stamps]))
use, rej = [], []
for s in stamps:
    o = q[s]; why = []
    if o['hfd_px'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the run median %.2f (limit %.0f%%)' % (o['hfd_arcsec'], 100 * (o['hfd_px'] / hfd_med - 1), hfd_med * SCALE, 100 * (LIMITS['hfd_max_rel'] - 1)))
    if o['smear'] > LIMITS['smear_max']: why.append('smeared: every star stretched the same way, common ellipticity %.2f at %.0f deg (limit %.2f); median elongation %.2f' % (o['smear'], o['smear_angle_deg'], LIMITS['smear_max'], o['elong_median']))
    if o['transparency'] < LIMITS['transparency_min']: why.append('stars at %.0f%% of their usual brightness (limit %.0f%%)' % (100 * o['transparency'], 100 * LIMITS['transparency_min']))
    if tr[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[s]['wrms_px'])
    if why:
        rej.append(dict(stamp=s, why='; '.join(why), transparency=o['transparency'], hfd_arcsec=o['hfd_arcsec'], smear=o['smear'], step_from_previous_px=o['step_from_previous_px'])); continue
    nrel = o['noise_zero_dn'] / noise0 / o['transparency']
    use.append(dict(stamp=s, transparency=o['transparency'], scale=1.0 / o['transparency'], noise_rel=nrel, weight=1.0 / nrel ** 2, hfd_arcsec=o['hfd_arcsec'], smear=o['smear']))
jdump(dict(limits=LIMITS, hfd_run_median_px=hfd_med, hfd_run_median_arcsec=hfd_med * SCALE, noise_run_median_dn=noise0, used=use, rejected=rej,
           effective_frames=float(sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use))), 'step5_select.json')
print('run median HFD %.2f px = %.2f arcsec; used %d, rejected %d; effective frames %.2f' % (hfd_med, hfd_med * SCALE, len(use), len(rej), sum(u['weight'] for u in use) ** 2 / sum(u['weight'] ** 2 for u in use)))
for u in use: print('  use', u['stamp'], 'T %.3f w %.3f HFD %.2f" smear %.3f' % (u['transparency'], u['weight'], u['hfd_arcsec'], u['smear']))
for r in rej: print('  DROP', r['stamp'], r['why'])
