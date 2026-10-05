"""Step 5: per-frame transparency, star width and elongation from the same stars in every frame they can be
found in: stars more than CORE_RADIUS from the nucleus, not saturated, no neighbour within 40 px, brighter than
QFLUX in the reference frame. Brightness is each star's aperture flux over that star's flux in the clear
frames (the 90th percentile over the run), median over stars: 1.0 = a clear sky, 0.5 = half the starlight
lost on the way (cloud)."""
import json, os, numpy as np
from common import *
res = json.load(open(W('step3_stars.json'))); T = json.load(open(W('step4_transforms.json'))); tr = T['transforms']
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
by = {r['stamp']: r for r in res}
QFLUX = 30000.0
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
ref = [s for s in by[REF_STAMP]['stars'] if s['r_nucleus'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > 40 and s['flux'] >= QFLUX]
refxy = np.array([nat(s) for s in ref])
table = {}
for o in tr:
    if o.get('failed'): table[o['stamp']] = {}; continue
    R = np.array(o['R']); t = np.array(o['t']); r = by[o['stamp']]
    xy = np.array([nat(s) for s in r['stars']])
    row = {}
    for i in range(len(ref)):
        p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not r['stars'][j]['saturated']: row[i] = r['stars'][j]
    table[o['stamp']] = row
print('quality stars in the reference frame:', len(ref))
def per_star(k, q):
    out = {}
    for i in range(len(ref)):
        v = [table[s][i][k] for s in table if i in table[s]]
        if len(v) >= 20: out[i] = float(np.percentile(v, q))
    return out
clearflux = per_star('flux', 90); clearpeak = per_star('peak', 90)
# first pass brightness, then the clear set = frames within 5% of the top, and medians of width over the clear set
def bright(row): 
    v = [row[i]['flux'] / clearflux[i] for i in row if i in clearflux]
    return float(np.median(v)) if len(v) >= 5 else None
b0 = {s: bright(table[s]) for s in table}
clear = [s for s in table if b0[s] is not None and b0[s] > 0.93]
med = {i: {k: float(np.median([table[s][i][k] for s in clear if i in table[s]])) for k in ('hfr', 'flux', 'peak')} for i in clearflux if sum(i in table[s] for s in clear) >= 10}
out = []
for s, row in table.items():
    ids = [i for i in row if i in med]
    if len(ids) < 5:
        out.append(dict(stamp=s, stars_matched=len(ids), flux_rel=None, corner_green=s1[s]['corner_green'], stars_detected=len(by[s]['stars']))); print(s, 'too few stars', len(ids), 'corner', round(s1[s]['corner_green'], 1)); continue
    fl = float(np.median([row[i]['flux'] / med[i]['flux'] for i in ids]))
    hfd = float(np.median([4 * row[i]['hfr'] for i in ids]))
    hfr_rel = float(np.median([row[i]['hfr'] / med[i]['hfr'] for i in ids]))
    el = float(np.median([row[i]['elong'] for i in ids]))
    pk = float(np.median([row[i]['peak'] / med[i]['peak'] for i in ids]))
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in ids])
    out.append(dict(stamp=s, stars_matched=len(ids), flux_rel=fl, hfd_px=hfd, hfd_arcsec=hfd * SCALE, hfr_rel=hfr_rel, elong_median=el, peak_rel=pk, coherent_ellipticity=float(abs(e)), coherent_angle_deg=float(np.degrees(np.angle(e)) / 2),
                    corner_green=s1[s]['corner_green'], stars_detected=len(by[s]['stars'])))
    print('%s stars %3d  brightness %.3f  peak %.3f  HFD %.2f" (rel %.3f)  elong %.3f coh %.3f @%+4.0f  corner G %.1f  detected %d' % (s, len(ids), fl, pk, hfd * SCALE, hfr_rel, el, abs(e), np.degrees(np.angle(e)) / 2, s1[s]['corner_green'], len(by[s]['stars'])))
json.dump(dict(quality=out, quality_stars=len(med), qflux=QFLUX, star_xy={str(i): refxy[i].tolist() for i in med}, star_medians={str(i): med[i] for i in med}), open(W('step5_quality.json'), 'w'), indent=1)
