"""Step 4c: which frames go into the stack. The rule is fixed here and recorded; a frame is rejected if any
limit is crossed."""
import json, numpy as np
from common import *
LIMITS = dict(brightness_min=0.90, hfd_max_rel=1.10, elongation_max=1.40, registration_wrms_max_px=1.0)
q = json.load(open(W('step4_quality.json')))['quality']; tr = {o['stamp']: o for o in json.load(open(W('step3_transforms.json')))}
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
hfd_med = float(np.median([o['hfd_arcsec'] for o in q])); sky_med = float(np.median([s1[o['stamp']]['bg'][1]['clipped_mean'] for o in q]))
use, rej = [], []
for o in q:
    why = []
    if o['flux_rel'] < LIMITS['brightness_min']: why.append('stars %.1f%% dimmer than the run median (limit 10%%) while the sky was %.0f%% brighter (green sky %.1f DN against a run median of %.1f): something was in the light path or lit the tube' % (100 * (1 - o['flux_rel']), 100 * (s1[o['stamp']]['bg'][1]['clipped_mean'] / sky_med - 1), s1[o['stamp']]['bg'][1]['clipped_mean'], sky_med))
    if o['hfd_arcsec'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the run median %.2f (limit 10%%); peak brightness %.0f%% of the median' % (o['hfd_arcsec'], 100 * (o['hfd_arcsec'] / hfd_med - 1), hfd_med, 100 * o['peak_rel']))
    if o['elong_median'] > LIMITS['elongation_max']: why.append('elongation %.2f' % o['elong_median'])
    if tr[o['stamp']]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[o['stamp']]['wrms_px'])
    (rej if why else use).append(dict(stamp=o['stamp'], why='; '.join(why), hfd_arcsec=o['hfd_arcsec'], elongation=o['elong_median'], brightness_rel=o['flux_rel'], peak_rel=o['peak_rel'], stars_detected=o['stars_detected']))
open(W('use.txt'), 'w').write('\n'.join(u['stamp'] for u in use) + '\n')
json.dump(dict(limits=LIMITS, hfd_run_median_arcsec=hfd_med, used=[u['stamp'] for u in use], rejected=rej), open(W('step4c_select.json'), 'w'), indent=1)
print('used', len(use), 'rejected', len(rej))
for r in rej: print('  ', r['stamp'], r['why'])
