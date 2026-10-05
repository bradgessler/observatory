"""Step 4: per-frame star width, elongation and brightness from the same bright stars in every frame."""
import json, os, numpy as np
from common import *
res = json.load(open(os.path.join(SCR, 'step2_stars.json'))); tr = json.load(open(os.path.join(SCR, 'step3_transforms.json')))
by = {r['stamp']: r for r in res}; ref = by[REF_STAMP]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])
neb_idx = int(np.argmin(np.hypot(*(refxy - np.array([3476, 2282])).T)))
bright = [i for i in range(len(refxy)) if refflux[i] >= 17000 and i != neb_idx]
print('nebula is ref index', neb_idx, '; quality stars:', len(bright), [int(refflux[i]) for i in bright])
table = {}
for o in tr:
    R = np.array(o['R']); t = np.array(o['t']); r = by[o['stamp']]
    xy = np.array([nat(s) for s in r['stars']])
    row = {}
    for i in bright:
        p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4: row[i] = r['stars'][j]
    table[o['stamp']] = row
common_ = [i for i in bright if all(i in table[s] for s in table)]
print('stars present in every frame:', len(common_))
med = {i: {k: np.median([table[s][i][k] for s in table]) for k in ('hfr', 'sig_major', 'sig_minor', 'flux', 'elong')} for i in common_}
out = []
for s, row in table.items():
    hfr = np.median([row[i]['hfr'] / med[i]['hfr'] for i in common_])
    sig = np.median([np.sqrt((row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) / 2) / np.sqrt((med[i]['sig_major'] ** 2 + med[i]['sig_minor'] ** 2) / 2) for i in common_])
    el = np.median([row[i]['elong'] for i in common_])
    el3 = np.mean([row[i]['elong'] for i in common_[:3]])
    fl = np.median([row[i]['flux'] / med[i]['flux'] for i in common_])
    # coherent elongation: mean of e*exp(2i theta) over stars (trailing gives a common direction)
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in common_])
    b = row[common_[0]]
    out.append(dict(stamp=s, hfr_rel=float(hfr), width_rel=float(sig), elong_median=float(el), elong_top3=float(el3), flux_rel=float(fl), coherent_ellipticity=float(abs(e)), coherent_angle_deg=float(np.degrees(np.angle(e)) / 2),
                    bright_star=dict(hfr_px=2 * b['hfr'], sig_major_px=2 * b['sig_major'], sig_minor_px=2 * b['sig_minor'], elong=b['elong'], peak=b['peak'], max_plane=max(b['plane_max']), flux=b['flux'])))
    print('%s hfr_rel %.3f width_rel %.3f elong_med %.3f top3 %.3f coh_e %.3f @%+4.0f flux_rel %.3f | bright star: HFD %.1f px, sigma %.2f/%.2f px, elong %.2f, peak %.0f, max plane %.0f' % (s, hfr, sig, el, el3, abs(e), np.degrees(np.angle(e)) / 2, fl, 4 * b['hfr'], 2 * b['sig_major'], 2 * b['sig_minor'], b['elong'], b['peak'], max(b['plane_max'])))
for k in ('hfr_rel', 'width_rel', 'elong_median', 'coherent_ellipticity', 'flux_rel'):
    v = np.array([o[k] for o in out]); m = np.median(v); s = 1.4826 * np.median(np.abs(v - m))
    print('%-22s median %.3f  robust sigma %.4f  min %.3f max %.3f  worst z %.1f' % (k, m, s, v.min(), v.max(), np.max(np.abs(v - m)) / max(s, 1e-9)))
json.dump(dict(quality=out, quality_star_ref_index=common_, nebula_ref_index=neb_idx, star_medians={str(i): med[i] for i in common_}, star_xy={str(i): refxy[i].tolist() for i in common_}), open(os.path.join(SCR, 'step4_quality.json'), 'w'), indent=1)
