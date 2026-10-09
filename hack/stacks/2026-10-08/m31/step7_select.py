"""Step 7 (from hack/stacks/2026-10-03/m31/step7_select.py): which frames go into the stack, and with what weight.
The rule is fixed here and recorded.

A frame is used if: it is not the first frame after a slew (the box's since_slew_s under 10 s: the mount is still
settling, the skill's rule); transparency (star brightness against the clear frames, step 5) >= 0.80; the
transparency is even across the field (a straight-line fit of star brightness against position changes by less
than 10% from the centre to 3000 px out); stars no wider than 1.10 x the median half-flux diameter of the clear
frames; median elongation <= 1.40; stars not drawn out in one shared direction (coherent ellipticity <= 0.25: the
mount moving during the exposure); registration weighted rms <= 1.0 px.
Used frames are multiplied by 1 / transparency and averaged with weight (transparency / noise)^2, noise = the
frame's measured dark-corner noise over the median of the used frames: the inverse variance of the scaled frame.
Tonight was clear, so every weight is close to 1."""
import numpy as np
from common import *

LIMITS = dict(since_slew_min_s=10.0, transparency_min=0.80, tilt_max=0.10, hfd_max_rel=1.10, elongation_max=1.40, coherent_ellipticity_max=0.25, registration_wrms_max_px=1.0, clear_min=0.97)
res = jload('step3_stars.json'); by = {r['stamp']: r for r in res}
T4 = jload('step4_transforms.json'); tr = {o['stamp']: o for o in T4['transforms']}
Q = jload('step5_quality.json'); q = {o['stamp']: o for o in Q['quality']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
DARK = jload('step2.json')['dark_corner']
sxy = {int(k): np.array(v) for k, v in Q['star_xy'].items()}; smed = {int(k): v for k, v in Q['star_medians'].items()}


def tilt(stamp):
    o = tr[stamp]; R = np.array(o['R']); t = np.array(o['t']); r = by[stamp]; T = q[stamp]['flux_rel']
    xy = np.array([nat(k) for k in r['stars']]); X, Y = [], []
    for i, p0 in sxy.items():
        p = p0 @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not r['stars'][j]['saturated']: X.append((p - CENTRE) / 3000); Y.append(r['stars'][j]['flux'] / smed[i]['flux'] / T)
    X = np.array(X); Y = np.array(Y); A = np.column_stack([np.ones(len(Y)), X]); keep = np.ones(len(Y), bool)
    for _ in range(3):
        co, *_ = np.linalg.lstsq(A[keep], Y[keep], rcond=None); rr = Y - A @ co; sd = 1.4826 * np.median(np.abs(rr[keep])); keep = np.abs(rr) < 3 * sd
    return float(co[1]), float(co[2]), float(sd)


stamps = sorted(s1)
clear = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= LIMITS['clear_min'] and s1[s]['since_slew_s'] >= LIMITS['since_slew_min_s']]
hfd_med = float(np.median([q[s]['hfd_arcsec'] for s in clear]))
use, rej = [], []
for s in stamps:
    o = q[s]; why = []
    if s1[s]['since_slew_s'] < LIMITS['since_slew_min_s']:
        why.append('first frame after a slew (%.1f s after it ended; the box solved this frame to centre the target): stars %.2f arcsec half-flux diameter, elongation %.2f, coherent ellipticity %.2f' % (s1[s]['since_slew_s'], o['hfd_arcsec'], o['elong_median'], o['coherent_ellipticity']))
    if tr[s].get('failed') or o['flux_rel'] is None:
        why.append('too few stars to register or measure')
    else:
        if o['flux_rel'] < LIMITS['transparency_min']: why.append('stars at %.0f%% of their clear brightness (limit %.0f%%)' % (100 * o['flux_rel'], 100 * LIMITS['transparency_min']))
        gx, gy, sd = tilt(s); o['tilt'] = [gx, gy]
        if max(abs(gx), abs(gy)) > LIMITS['tilt_max']: why.append('star brightness uneven across the field: %.0f%% in x, %.0f%% in y per 3000 px' % (100 * gx, 100 * gy))
        if o['hfd_arcsec'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the clear median %.2f (limit 10%%)' % (o['hfd_arcsec'], 100 * (o['hfd_arcsec'] / hfd_med - 1), hfd_med))
        if o['elong_median'] > LIMITS['elongation_max']: why.append('stars drawn out: median elongation %.2f (limit %.2f)' % (o['elong_median'], LIMITS['elongation_max']))
        if o['coherent_ellipticity'] > LIMITS['coherent_ellipticity_max']: why.append('stars drawn out in one direction (coherent ellipticity %.2f at %.0f deg, limit %.2f): the mount moved during the exposure' % (o['coherent_ellipticity'], o['coherent_angle_deg'], LIMITS['coherent_ellipticity_max']))
        if tr[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[s]['wrms_px'])
    if why: rej.append(dict(stamp=s, why='; '.join(why), transparency=o['flux_rel'])); continue
    use.append(dict(stamp=s, transparency=o['flux_rel'], noise_dn=s1[s]['corners'][DARK]['std'][1], tilt=o['tilt'], hfd_arcsec=o['hfd_arcsec'], elongation=o['elong_median'], coherent_ellipticity=o['coherent_ellipticity']))
noise0 = float(np.median([u['noise_dn'] for u in use]))
for u in use:
    u['noise_rel'] = u['noise_dn'] / noise0 / u['transparency']; u['scale'] = 1.0 / u['transparency']; u['weight'] = 1.0 / u['noise_rel'] ** 2
    u['clear'] = bool(u['transparency'] >= LIMITS['clear_min'])
jdump(dict(limits=LIMITS, hfd_clear_median_arcsec=hfd_med, corner_noise_median_used=noise0, used=use, rejected=rej, effective_frames=float(sum(u['weight'] for u in use))), 'step7_select.json')
print('clear-frame HFD median %.2f arcsec; used %d, rejected %d; sum of weights %.2f' % (hfd_med, len(use), len(rej), sum(u['weight'] for u in use)))
for r in rej: print('  rejected', r['stamp'], r['why'])
for u in use: print('  used', u['stamp'], 'T %.3f w %.3f HFD %.2f el %.2f coh %.2f tilt %+.3f %+.3f' % (u['transparency'], u['weight'], u['hfd_arcsec'], u['elongation'], u['coherent_ellipticity'], *u['tilt']))
