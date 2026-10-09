"""Step 6: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

What this run was like (steps 2 and 5): M1 was rising out from behind something near the telescope. The light that got
through grew 13-fold over the 13 minutes, from 8% to 100% of the last frame's (stars only), unevenly across the field
(the flux ratio tilts by up to 100% per 3000 px in the early frames), while the background in green and blue grew and
the red stayed put: early frames are mostly the warm glow of a lit, out-of-focus object in the way, not sky. And the
mount: the first two frames are centring frames, and from 08:03:45 on every frame but one is smeared in one direction
(elongation 1.7 to 1.9, common-direction ellipticity 0.49 to 0.58), the periodic disturbance seen on NGC 1514 earlier
grown continuous. The seeing 30 degrees up gives 5.2 to 7 arcsec stars at best.

Transparency AT M1: because the light varies across the field, each frame's transparency is measured where the nebula
is. Every star of the reference frame brighter than 3000 DN (not clipped, more than 300 px from M1) is found in the
frame; the ratio of its flux to the reference frame's is fitted with a plane across the field (weights from the aperture
noise of both frames plus 5%, 3-sigma rejection), and the plane's value at M1's position is the frame's transparency
relative to the reference; then scaled so the clearest frame is 1. The error of that value is about 1% (chi^2/dof 1.0 to
1.5); step 5's whole-field median is kept as a check.

A frame is used if:
  - it was not taken during a slew or the settle after it (sidecar: settling false, and more than SETTLE_S seconds
    since the last slew or centring nudge);
  - stars no wider than HFD_MAX_ARCSEC (half-flux diameter, the median over step 5's 42 quality stars): "roughly 6.5
    arcsec", as asked, taken as 6.6 so that 6.53 and 6.56 are kept;
  - median elongation <= ELONG_MAX and common-direction ellipticity <= COH_MAX (no trailing or shake);
  - transparency at M1 >= T_MIN: below a third, the frame's background is mostly the glow of the obstruction (a
    different smooth pattern in every frame), and its weight would be under a fifth of the best used frame's;
  - registration rms <= WRMS_MAX px.
Used frames are multiplied by 1 / transparency (so the nebula agrees from frame to frame) and averaged with
weight (transparency / noise)^2, noise = that frame's green pixel noise over the clear-frame median.
Adapted from this night's ngc1514/step6_select.py: the transparency is measured at the nebula (as m57's local one, here
with a plane through all the stars, because the light changed across the field), the HFD limit is 6.6 and T_MIN 0.30."""
import numpy as np
from common import *

LIMITS = dict(settle_s=10.0, hfd_max_arcsec=6.6, elong_max=1.35, coh_max=0.20, t_min=0.30, wrms_max_px=1.5, clear_min=0.90,
              t_star_min_flux=3000, t_exclude_px=300, t_floor_frac=0.05)
res = jload('step2_stars.json'); by = {r['stamp']: r for r in res}
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
Q = {o['stamp']: o for o in jload('step5_quality.json')['quality']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
S4 = jload('step4_solve_ref.json'); NEB = np.array(S4['target_sensor_px'])
ref = by[REF]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
A0 = np.array([nat(s) for s in ref['stars']]); F0 = np.array([s['flux'] for s in ref['stars']])
sel_i = [i for i in range(len(A0)) if F0[i] >= LIMITS['t_star_min_flux'] and not ref['stars'][i]['saturated'] and np.hypot(*(A0[i] - NEB)) > LIMITS['t_exclude_px']]
AP_PX = np.pi * 14 ** 2                                       # step 2's aperture, plane px
nz_ref = Q[REF]['pixel_noise_dn'][1]
TM = {}
for s, o in tr.items():
    if o['failed']: continue
    xy = np.array([nat(k) for k in by[s]['stars']]); P = poly_apply(o, A0[sel_i]); rows = []
    for i, p in zip(sel_i, P):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not by[s]['stars'][j]['saturated']: rows.append((A0[i][0], A0[i][1], F0[i], by[s]['stars'][j]['flux']))
    r = np.array(rows)
    if len(r) < 5: TM[s] = None; continue
    ratio = r[:, 3] / r[:, 2]; med = float(np.median(ratio))
    err = np.sqrt((Q[s]['pixel_noise_dn'][1] * np.sqrt(AP_PX) / r[:, 2]) ** 2 + (med * nz_ref * np.sqrt(AP_PX) / r[:, 2]) ** 2 + (LIMITS['t_floor_frac'] * med) ** 2)
    u, v = (r[:, 0] - NEB[0]) / 3000, (r[:, 1] - NEB[1]) / 3000
    X = np.column_stack([np.ones(len(r)), u, v]); w = 1 / err ** 2; keep = np.ones(len(r), bool)
    for _ in range(6):
        sw = np.sqrt(w[keep]); co, *_ = np.linalg.lstsq(X[keep] * sw[:, None], ratio[keep] * sw, rcond=None)
        z = (ratio - X @ co) / err; keep = np.abs(z) < 3
    dof = max(int(keep.sum()) - 3, 1); chi = float(np.sum(z[keep] ** 2) / dof)
    cov = np.linalg.inv((X[keep] * w[keep][:, None]).T @ X[keep])
    TM[s] = dict(at_m1_vs_reference=float(co[0]), error=float(np.sqrt(cov[0, 0] * max(chi, 1))), tilt_per_3000px=[float(co[1] / co[0]), float(co[2] / co[0])],
                 stars=int(len(r)), stars_used=int(keep.sum()), chi2_per_dof=chi, median_ratio=med)
top = max(v['at_m1_vs_reference'] for v in TM.values() if v)
TF = {s: Q[s]['transparency'] for s in Q}                      # whole field, clearest frame = 1 (step 5), the check
T = {s: (v['at_m1_vs_reference'] / top if v else None) for s, v in TM.items()}
clear = [s for s in T if T[s] is not None and T[s] >= LIMITS['clear_min']]
noise0 = float(np.median([Q[s]['pixel_noise_dn'][1] for s in clear]))
use, rej = [], []
for s in sorted(tr):
    o = tr[s]; q = Q.get(s); f = s1[s]; why = []
    if f['settling'] or (f['since_slew_s'] is not None and f['since_slew_s'] < LIMITS['settle_s']):
        why.append('a centring frame: taken %.1f s after a slew or centring nudge%s (limit %.0f s)' % (f['since_slew_s'], ', flagged settling' if f['settling'] else '', LIMITS['settle_s']))
    if o['failed']:
        why.append('registration failed (%d stars matched: the field was about 1500 px from the rest and few stars got through)' % o['matched'])
        rej.append(dict(stamp=s, why='; '.join(why), box_star_size_arcsec=f['box_star_size_arcsec'])); continue
    if q['hfd_arcsec'] > LIMITS['hfd_max_arcsec']: why.append('stars %.2f arcsec half-flux diameter (limit %.1f)' % (q['hfd_arcsec'], LIMITS['hfd_max_arcsec']))
    if q['elong_median'] > LIMITS['elong_max']: why.append('elongation %.2f (limit %.2f)' % (q['elong_median'], LIMITS['elong_max']))
    if q['coherent_ellipticity'] > LIMITS['coh_max']: why.append('stars stretched in one direction (common ellipticity %.2f at %+.0f deg, limit %.2f): smeared by the mount' % (q['coherent_ellipticity'], q['coherent_angle_deg'], LIMITS['coh_max']))
    t = T[s]
    if t is None or t < LIMITS['t_min']: why.append('%s of the clearest frame\'s light reached M1 (limit %.0f%%): mostly behind the obstruction' % ('%.0f%%' % (100 * t) if t is not None else 'too little', 100 * LIMITS['t_min']))
    wr = o['model_wrms_px'] if o['model_wrms_px'] is not None else o['wrms_px']
    if wr > LIMITS['wrms_max_px']: why.append('registration rms %.2f px' % wr)
    if why:
        rej.append(dict(stamp=s, why='; '.join(why), hfd_arcsec=q['hfd_arcsec'], elong_median=q['elong_median'], coherent_ellipticity=q['coherent_ellipticity'], transparency_at_m1=t,
                        transparency_whole_field_check=TF[s], stars_matched=o['matched'], box_star_size_arcsec=f['box_star_size_arcsec']))
        continue
    nrel = q['pixel_noise_dn'][1] / noise0
    use.append(dict(stamp=s, transparency=t, transparency_error=TM[s]['error'] / top, transparency_whole_field_check=TF[s], scale=1.0 / t, noise_rel=nrel / t, weight=(t / nrel) ** 2,
                    hfd_px=q['hfd_px'], hfd_arcsec=q['hfd_arcsec'], elong_median=q['elong_median'], coherent_ellipticity=q['coherent_ellipticity'], stars_matched=o['matched'],
                    box_star_size_arcsec=f['box_star_size_arcsec']))
wsum = sum(u['weight'] for u in use)
wref = [u['weight'] for u in use if u['stamp'] == REF]
jsave(dict(limits=LIMITS, transparency_from='at M1: plane through the star flux ratios (frame / reference), clearest frame = 1', transparency_at_m1=T, transparency_fit=TM,
           transparency_whole_field_check=TF, clearest=max((s for s in T if T[s] is not None), key=lambda s: T[s]), noise_clear_median_dn=noise0,
           used=use, rejected=rej, sum_of_weights=wsum, effective_frames=wsum ** 2 / sum(u['weight'] ** 2 for u in use),
           expected_noise_gain_vs_reference=float(np.sqrt(wsum / wref[0])) if wref else None), 'step6_select.json')
print('used %d, rejected %d; sum of weights %.3f; effective frames %.2f; expected noise gain against the reference frame alone %.2f' % (
    len(use), len(rej), wsum, wsum ** 2 / sum(u['weight'] ** 2 for u in use), np.sqrt(wsum / wref[0]) if wref else float('nan')))
for s in sorted(tr):
    u = [x for x in use if x['stamp'] == s]
    if u: u = u[0]; print('  use  %s  T at M1 %.3f +- %.3f (whole field %.3f)  weight %.4f  HFD %.2f"  elong %.2f coh %.2f  matched %d' % (s, u['transparency'], u['transparency_error'], u['transparency_whole_field_check'], u['weight'], u['hfd_arcsec'], u['elong_median'], u['coherent_ellipticity'], u['stars_matched']))
    else: r = [x for x in rej if x['stamp'] == s][0]; print('  drop %s  %s' % (s, r['why']))
