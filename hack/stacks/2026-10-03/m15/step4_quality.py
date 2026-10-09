"""Step 4: per-frame star width, elongation and brightness from the same stars in every frame: stars outside
the cluster's core, not saturated, no neighbour within 40 px, brighter than 17000 DN in the reference frame."""
import json, os, numpy as np
from common import *
res = json.load(open(W('step2_stars.json'))); tr = json.load(open(W('step3_transforms.json')))
by = {r['stamp']: r for r in res}
QFLUX = 17000.0
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
ref = [s for s in by[REF_STAMP]['stars'] if s['r_cluster'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > 40 and s['flux'] >= QFLUX]
refxy = np.array([nat(s) for s in ref]); refflux = np.array([s['flux'] for s in ref])
table = {}
for o in tr:
    R = np.array(o['R']); t = np.array(o['t']); r = by[o['stamp']]
    xy = np.array([nat(s) for s in r['stars']])
    row = {}
    for i in range(len(ref)):
        p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not r['stars'][j]['saturated']: row[i] = r['stars'][j]
    table[o['stamp']] = row
common_ = [i for i in range(len(ref)) if all(i in table[s] for s in table)]
print('quality stars in the reference frame:', len(ref), '; present in every frame:', len(common_))
med = {i: {k: np.median([table[s][i][k] for s in table]) for k in ('hfr', 'sig_major', 'sig_minor', 'flux', 'elong')} for i in common_}
out = []
for s, row in table.items():
    hfr = np.median([row[i]['hfr'] / med[i]['hfr'] for i in common_])
    hfd_abs = np.median([4 * row[i]['hfr'] for i in common_])       # sensor px
    sig = np.median([np.sqrt((row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) / 2) / np.sqrt((med[i]['sig_major'] ** 2 + med[i]['sig_minor'] ** 2) / 2) for i in common_])
    el = np.median([row[i]['elong'] for i in common_])
    fl = np.median([row[i]['flux'] / med[i]['flux'] for i in common_])
    pk = np.median([row[i]['peak'] / np.median([table[s2][i]['peak'] for s2 in table]) for i in common_])
    # coherent elongation: mean of e*exp(2i theta) over stars (trailing gives a common direction)
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in common_])
    out.append(dict(stamp=s, hfr_rel=float(hfr), hfd_px=float(hfd_abs), hfd_arcsec=float(hfd_abs * SCALE), width_rel=float(sig), elong_median=float(el), flux_rel=float(fl), peak_rel=float(pk),
                    coherent_ellipticity=float(abs(e)), coherent_angle_deg=float(np.degrees(np.angle(e)) / 2), stars_detected=len(by[s]['stars'])))
    print('%s HFD %.2f px = %.2f" (rel %.3f) width_rel %.3f elong_med %.3f coh_e %.3f @%+4.0f flux_rel %.3f peak_rel %.3f  stars %d' % (s, hfd_abs, hfd_abs * SCALE, hfr, sig, el, abs(e), np.degrees(np.angle(e)) / 2, fl, pk, len(by[s]['stars'])))
for k in ('hfd_arcsec', 'hfr_rel', 'width_rel', 'elong_median', 'coherent_ellipticity', 'flux_rel', 'peak_rel'):
    v = np.array([o[k] for o in out]); m = np.median(v); s = 1.4826 * np.median(np.abs(v - m))
    print('%-22s median %.3f  robust sigma %.4f  min %.3f max %.3f  worst z %.1f' % (k, m, s, v.min(), v.max(), np.max(np.abs(v - m)) / max(s, 1e-9)))
json.dump(dict(quality=out, quality_stars=len(common_), star_medians={str(i): med[i] for i in common_}, star_xy={str(i): refxy[i].tolist() for i in common_}), open(W('step4_quality.json'), 'w'), indent=1)
