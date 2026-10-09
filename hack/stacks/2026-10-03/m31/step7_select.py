"""Step 7: which frames go into the stack, and with what weight. The rule is fixed here and recorded.

What the frames show (step 5): the 'bright sky' frames are CLOUD, not a lamp. In every frame where the corner
level is up, the stars are down, by up to 97%. So the test is the measured transparency (star brightness
relative to the clear frames), and the corner level goes with it.

A frame is used if: transparency >= T_MIN; the transparency is even across the field (a straight-line fit of
star brightness against position changes by less than TILT_MAX from the centre to 3000 px out); stars no wider than
HFD_MAX_REL x the clear-frame median; median elongation <= ELONG_MAX; registration rms <= WRMS_MAX px.
Used frames are multiplied by 1 / transparency (so that they agree) and averaged with weight
(transparency / noise)^2, noise = the measured corner noise of that frame over the clear-frame median: the
inverse of the variance of the scaled frame in the faint parts. Clear frames get weights near 1."""
import json, numpy as np
from common import *
LIMITS = dict(transparency_min=0.80, tilt_max=0.10, hfd_max_rel=1.10, elongation_max=1.40, registration_wrms_max_px=1.0, clear_min=0.97)
res = json.load(open(W('step3_stars.json'))); by = {r['stamp']: r for r in res}
T4 = json.load(open(W('step4_transforms.json'))); tr = {o['stamp']: o for o in T4['transforms']}
Q = json.load(open(W('step5_quality.json'))); q = {o['stamp']: o for o in Q['quality']}
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
sxy = {int(k): np.array(v) for k, v in Q['star_xy'].items()}; smed = {int(k): v for k, v in Q['star_medians'].items()}
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
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
clear = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= LIMITS['clear_min']]
hfd_med = float(np.median([q[s]['hfd_arcsec'] for s in clear])); floor = float(np.median([s1[s]['corner_green'] for s in clear]))
noise0 = float(np.median([s1[s]['corner'][1]['clipped_std'] for s in clear]))
use, rej = [], []
for s in stamps:
    o = q[s]; lv = s1[s]['corner_green']; why = []
    if tr[s].get('failed') or o['flux_rel'] is None:
        why.append('cloud: too few stars to register or measure (%d detected); corner green %.0f DN, %.1f x the clear level' % (o['stars_detected'], lv, lv / floor))
    else:
        if o['flux_rel'] < LIMITS['transparency_min']: why.append('cloud: stars at %.0f%% of their clear brightness (limit %.0f%%); corner green %.0f DN, %.2f x the clear level' % (100 * o['flux_rel'], 100 * LIMITS['transparency_min'], lv, lv / floor))
        gx, gy, sd = tilt(s); o['tilt'] = [gx, gy]
        if not why and max(abs(gx), abs(gy)) > LIMITS['tilt_max']: why.append('thin cloud uneven across the field: star brightness changes by %.0f%% in x and %.0f%% in y per 3000 px (limit %.0f%%); transparency %.0f%%' % (100 * gx, 100 * gy, 100 * LIMITS['tilt_max'], 100 * o['flux_rel']))
        if o['hfd_arcsec'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the clear-frame median %.2f (limit 10%%)' % (o['hfd_arcsec'], 100 * (o['hfd_arcsec'] / hfd_med - 1), hfd_med))
        if o['elong_median'] > LIMITS['elongation_max']: why.append('elongation %.2f' % o['elong_median'])
        if tr[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tr[s]['wrms_px'])
    if why: rej.append(dict(stamp=s, why='; '.join(why), transparency=o['flux_rel'], corner_green=lv)); continue
    nrel = s1[s]['corner'][1]['clipped_std'] / noise0 / o['flux_rel']         # noise of the scaled frame relative to a clear frame
    use.append(dict(stamp=s, transparency=o['flux_rel'], scale=1.0 / o['flux_rel'], noise_rel=nrel, weight=1.0 / nrel ** 2, corner_green=lv, tilt=o['tilt'], clear=bool(o['flux_rel'] >= LIMITS['clear_min'])))
json.dump(dict(limits=LIMITS, hfd_clear_median_arcsec=hfd_med, corner_green_clear_median=floor, corner_noise_clear_median=noise0, used=use, rejected=rej,
               corner_green_max_used=max(u['corner_green'] for u in use), effective_clear_frames=float(sum(u['weight'] for u in use))), open(W('step7_select.json'), 'w'), indent=1)
print('clear-frame corner level (green) %.1f DN, noise %.1f DN; used %d (of which clear %d), rejected %d; highest corner level used %.0f DN = %.2f x clear; sum of weights %.1f' % (floor, noise0, len(use), sum(u['clear'] for u in use), len(rej), max(u['corner_green'] for u in use), max(u['corner_green'] for u in use) / floor, sum(u['weight'] for u in use)))
import collections
print(collections.Counter(r['why'].split(':')[0].split(' at ')[0][:40] for r in rej))
for u in use: print(u['stamp'], 'T %.3f w %.3f corner %.0f tilt %+.3f %+.3f' % (u['transparency'], u['weight'], u['corner_green'], *u['tilt']), 'clear' if u['clear'] else '')
for r in rej:
    if 'uneven' in r['why'] or 'wider' in r['why'] or 'registration' in r['why'] or 'elong' in r['why']: print('  rejected', r['stamp'], r['why'])
