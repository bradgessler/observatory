"""Step 6: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

The sky was clear (step 5: every frame's stars within 6% of the clearest, apart from the smeared frames, whose stars
spill out of the measuring aperture). What went wrong in this run was the mount: the centring frames, and frames
smeared while the hold settled after centring and again in single frames later (stars drawn into short streaks, all
in one direction: elongation 1.6 to 2.9, common-direction ellipticity 0.45 to 0.75). So the rule is about star size
and shape first:

A frame is used if:
  - it was not taken during a slew or the settle after it (sidecar: settling false, and more than SETTLE_S seconds
    since the last slew or centring nudge);
  - stars no wider than HFD_MAX_ARCSEC (half-flux diameter, the median over step 5's quality stars), as asked;
  - median elongation <= ELONG_MAX and common-direction ellipticity <= COH_MAX (no trailing or shake);
  - transparency >= T_MIN: step 5's measure over the whole field (the median, over 18 bright unclipped stars found in
    nearly every frame, of each star's flux against its own median over the run, scaled so the clearest frame is 1).
    The field was evenly clear (step 5's straight-line fit of the ratio across the field: under 6% per 3000 px in the
    frames used), so the whole field's 18 stars measure the light at the nebula better than the 7 stars near it, whose
    "local" ratio scatters by about 5% from star noise alone; the local value is kept in the record as a check;
  - registration rms <= WRMS_MAX px.
Used frames are multiplied by 1 / transparency (so the nebula agrees from frame to frame) and averaged with
weight (transparency / noise)^2, noise = that frame's green pixel noise over the clear-frame median.
Adapted from this night's m57/step5_select.py; the HFD limit is absolute (in arcsec), the settle and shape rules
are added, and the transparency is the whole field's (m57 had patchy cloud and needed the local one)."""
import numpy as np
from common import *

LIMITS = dict(settle_s=10.0, hfd_max_arcsec=6.5, elong_max=1.35, coh_max=0.20, t_min=0.80, wrms_max_px=1.5, clear_min=0.90, local_radius_px=1200, local_min_flux=8000)
res = jload('step2_stars.json'); by = {r['stamp']: r for r in res}
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
Q = {o['stamp']: o for o in jload('step5_quality.json')['quality']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
S4 = jload('step4_solve_ref.json'); NEB = np.array(S4['target_sensor_px'])
ref = by[REF]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
A0 = np.array([nat(s) for s in ref['stars']]); F0 = np.array([s['flux'] for s in ref['stars']])
near = [i for i in range(len(A0)) if F0[i] >= LIMITS['local_min_flux'] and not ref['stars'][i]['saturated'] and 60 < np.hypot(*(A0[i] - NEB)) < LIMITS['local_radius_px']]
print('local stars:', len(near), 'reference fluxes', sorted(int(F0[i]) for i in near))
flux = {}
for s, o in tr.items():
    if o['failed']: continue
    xy = np.array([nat(k) for k in by[s]['stars']]); P = poly_apply(o, A0[near]); row = {}
    for i, p in zip(near, P):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not by[s]['stars'][j]['saturated']: row[i] = by[s]['stars'][j]['flux']
    flux[s] = row
smed = {i: np.median([flux[s][i] for s in flux if i in flux[s]]) for i in near}
loc = {s: (float(np.median([flux[s][i] / smed[i] for i in flux[s] if i in smed])), len(flux[s])) for s in flux}
top = max(v[0] for v in loc.values())
TL = {s: v[0] / top for s, v in loc.items()}
TF = {s: Q[s]['transparency'] for s in Q}                      # whole field, clearest frame = 1 (step 5)
clear = [s for s in TF if TF[s] >= LIMITS['clear_min']]
noise0 = float(np.median([Q[s]['pixel_noise_dn'][1] for s in clear]))
use, rej = [], []
for s in sorted(tr):
    o = tr[s]; q = Q.get(s); f = s1[s]; why = []
    if o['failed']: rej.append(dict(stamp=s, why='registration failed')); continue
    if f['settling'] or (f['since_slew_s'] is not None and f['since_slew_s'] < LIMITS['settle_s']):
        why.append('taken %.1f s after a slew or centring nudge%s (limit %.0f s): the first frame after a move' % (f['since_slew_s'], ', flagged settling' if f['settling'] else '', LIMITS['settle_s']))
    if q['hfd_arcsec'] > LIMITS['hfd_max_arcsec']: why.append('stars %.2f arcsec half-flux diameter (limit %.1f)' % (q['hfd_arcsec'], LIMITS['hfd_max_arcsec']))
    if q['elong_median'] > LIMITS['elong_max']: why.append('elongation %.2f (limit %.2f)' % (q['elong_median'], LIMITS['elong_max']))
    if q['coherent_ellipticity'] > LIMITS['coh_max']: why.append('stars stretched in one direction (common ellipticity %.2f at %+.0f deg, limit %.2f): smeared by the mount' % (q['coherent_ellipticity'], q['coherent_angle_deg'], LIMITS['coh_max']))
    t = TF[s]
    if t < LIMITS['t_min']: why.append('stars at %.0f%% of the clearest frame (limit %.0f%%)' % (100 * t, 100 * LIMITS['t_min']))
    wr = o['model_wrms_px'] if o['model_wrms_px'] is not None else o['wrms_px']
    if wr > LIMITS['wrms_max_px']: why.append('registration rms %.2f px' % wr)
    if why:
        rej.append(dict(stamp=s, why='; '.join(why), hfd_arcsec=q['hfd_arcsec'], elong_median=q['elong_median'], coherent_ellipticity=q['coherent_ellipticity'], transparency=t, local_transparency=TL[s], box_star_size_arcsec=f['box_star_size_arcsec']))
        continue
    nrel = q['pixel_noise_dn'][1] / noise0
    use.append(dict(stamp=s, transparency=t, local_transparency_check=TL[s], local_stars=loc[s][1], scale=1.0 / t, noise_rel=nrel / t, weight=(t / nrel) ** 2,
                    hfd_px=q['hfd_px'], hfd_arcsec=q['hfd_arcsec'], elong_median=q['elong_median'], coherent_ellipticity=q['coherent_ellipticity'], box_star_size_arcsec=f['box_star_size_arcsec']))
wsum = sum(u['weight'] for u in use)
jsave(dict(limits=LIMITS, transparency_from='step 5, whole field', local_stars=len(near), clearest=max(TF, key=TF.get), noise_clear_median_dn=noise0, transparency=TF, local_transparency_check=TL,
           used=use, rejected=rej, sum_of_weights=wsum, effective_frames=wsum ** 2 / sum(u['weight'] ** 2 for u in use)), 'step6_select.json')
print('used %d, rejected %d; sum of weights %.2f; effective frames %.2f' % (len(use), len(rej), wsum, wsum ** 2 / sum(u['weight'] ** 2 for u in use)))
for s in sorted(tr):
    u = [x for x in use if x['stamp'] == s]
    if u: u = u[0]; print('  use  %s  T %.3f (local check %.3f, %d stars)  weight %.3f  HFD %.2f"  elong %.2f coh %.2f' % (s, u['transparency'], u['local_transparency_check'], u['local_stars'], u['weight'], u['hfd_arcsec'], u['elong_median'], u['coherent_ellipticity']))
    else: r = [x for x in rej if x['stamp'] == s][0]; print('  drop %s  %s' % (s, r['why']))
