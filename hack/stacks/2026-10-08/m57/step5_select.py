"""Step 5: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

Thin cloud came through in patches (step 4: in one frame the stars at the top of the field are 1.4 x brighter than
those at the bottom, in another 0.5 x). What matters for the picture is the light at the nebula, so the transparency
used here is LOCAL: the median, over stars within 1200 px of the nebula (brighter than 8000 DN in the reference, not
clipped), of each star's flux against its own median over the run, scaled so that the clearest frame is 1.
A frame is used if: local transparency >= T_MIN; stars no wider than HFD_MAX_REL x the median of the clear frames
(local transparency >= 0.9); median elongation <= ELONG_MAX and common-direction ellipticity <= COH_MAX (no trailing);
registration rms <= WRMS_MAX px. Used frames are multiplied by 1 / local transparency (so the nebula agrees from frame
to frame) and averaged with weight (transparency / noise)^2, noise = that frame's green pixel noise over the clear-frame
median: the inverse variance of the scaled frame where the picture is faint (the noise is mostly the sensor's read noise,
so a frame at half transparency counts a quarter)."""
import numpy as np
from common import *
LIMITS = dict(t_min=0.50, hfd_max_rel=1.20, elong_max=1.35, coh_max=0.20, wrms_max_px=1.5, clear_min=0.90, local_radius_px=1200, local_min_flux=8000)
res = jload('step2_stars.json'); by = {r['stamp']: r for r in res}
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
Q = {o['stamp']: o for o in jload('step4_quality.json')['quality']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
ref = by[REF]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
A0 = np.array([nat(s) for s in ref['stars']]); F0 = np.array([s['flux'] for s in ref['stars']])
UC = np.array([3012.0, 2012.0]); NEB = np.array(NEB_REF_GUESS)
def apply(o, A):
    u = (A - UC) / 3000
    X = np.column_stack([np.ones(len(A)), u[:, 0], u[:, 1], u[:, 0] ** 2, u[:, 0] * u[:, 1], u[:, 1] ** 2])
    return np.column_stack([X @ np.array(o['cx']), X @ np.array(o['cy'])])
near = [i for i in range(len(A0)) if F0[i] >= LIMITS['local_min_flux'] and not ref['stars'][i]['saturated'] and np.hypot(*(A0[i] - NEB)) < LIMITS['local_radius_px'] and np.hypot(*(A0[i] - NEB)) > 60]
print('local stars:', len(near), 'reference fluxes', sorted(int(F0[i]) for i in near))
flux = {}
for s, o in tr.items():
    if o['failed']: continue
    xy = np.array([nat(k) for k in by[s]['stars']]); P = apply(o, A0[near]); row = {}
    for i, p in zip(near, P):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not by[s]['stars'][j]['saturated']: row[i] = by[s]['stars'][j]['flux']
    flux[s] = row
smed = {i: np.median([flux[s][i] for s in flux if i in flux[s]]) for i in near}
loc = {s: (float(np.median([flux[s][i] / smed[i] for i in flux[s]])), len(flux[s])) for s in flux}
top = max(v[0] for v in loc.values())
TL = {s: v[0] / top for s, v in loc.items()}
clear = [s for s in TL if TL[s] >= LIMITS['clear_min']]
hfd_clear = float(np.median([Q[s]['hfd_px'] for s in clear])); noise0 = float(np.median([Q[s]['pixel_noise_dn'][1] for s in clear]))
use, rej = [], []
for s in sorted(tr):
    o = tr[s]; q = Q.get(s); why = []
    if o['failed']: rej.append(dict(stamp=s, why='registration failed')); continue
    t = TL[s]
    if t < LIMITS['t_min']: why.append('cloud: stars near the nebula at %.0f%% of the clearest frame (limit %.0f%%); over the whole field %.0f%%, changing by %+.0f%% / %+.0f%% per 3000 px in x / y' % (100 * t, 100 * LIMITS['t_min'], 100 * q['transparency'], 100 * q['tilt_per_3000px'][0], 100 * q['tilt_per_3000px'][1]))
    if q['hfd_px'] > LIMITS['hfd_max_rel'] * hfd_clear: why.append('stars %.1f px (%.2f arcsec) half-flux diameter, %.0f%% wider than the clear frames (limit %.0f%%)' % (q['hfd_px'], q['hfd_arcsec'], 100 * (q['hfd_px'] / hfd_clear - 1), 100 * (LIMITS['hfd_max_rel'] - 1)))
    if q['elong_median'] > LIMITS['elong_max']: why.append('elongation %.2f (limit %.2f)' % (q['elong_median'], LIMITS['elong_max']))
    if q['coherent_ellipticity'] > LIMITS['coh_max']: why.append('stars stretched in one direction (common ellipticity %.2f, limit %.2f): trailing or shake' % (q['coherent_ellipticity'], LIMITS['coh_max']))
    wr = o['model_wrms_px'] if o['model_wrms_px'] is not None else o['wrms_px']
    if wr > LIMITS['wrms_max_px']: why.append('registration rms %.2f px' % wr)
    if why: rej.append(dict(stamp=s, why='; '.join(why), local_transparency=t, transparency_field=q['transparency'])); continue
    nrel = q['pixel_noise_dn'][1] / noise0
    use.append(dict(stamp=s, local_transparency=t, local_stars=loc[s][1], transparency_field=q['transparency'], tilt_per_3000px=q['tilt_per_3000px'], scale=1.0 / t, noise_rel=nrel / t, weight=(t / nrel) ** 2,
                    hfd_px=q['hfd_px'], hfd_arcsec=q['hfd_arcsec'], clear=bool(t >= LIMITS['clear_min'])))
wsum = sum(u['weight'] for u in use)
jsave(dict(limits=LIMITS, local_stars=len(near), clearest=max(TL, key=TL.get), hfd_clear_median_px=hfd_clear, noise_clear_median_dn=noise0, local_transparency=TL,
           used=use, rejected=rej, sum_of_weights=wsum), 'step5_select.json')
print('clear frames (local T >= %.2f): %d, their median HFD %.1f px; used %d, rejected %d; sum of weights %.2f (equivalent clear frames)' % (LIMITS['clear_min'], len(clear), hfd_clear, len(use), len(rej), wsum))
for s in sorted(tr):
    u = [x for x in use if x['stamp'] == s]
    if u: u = u[0]; print('  use %s  local T %.3f (%2d stars)  field T %.3f  weight %.3f  HFD %.2f"' % (s, u['local_transparency'], u['local_stars'], u['transparency_field'], u['weight'], u['hfd_arcsec']))
    else: r = [x for x in rej if x['stamp'] == s][0]; print('  drop %s  %s' % (s, r['why']))
