"""Mosaic step 10b: the 0915 check frames (2 x 30 s on the nucleus, taken just before the panels) against the deep
core stack, as a test of the method on a field where the answer is known. Not part of the mosaic.

The check stack (step 6, same pipeline as a panel) is placed with its own plate solution, scaled by the stars it
shares with the core (same aperture photometry and weights as step 8), resampled onto the core's half grid, and
compared in 64 px blocks: after ONE constant per colour, and after a constant and a plane, both fitted outside
13 arcmin of the nucleus; and the excess in rings about the nucleus (the bulge's light scattered in thin cloud)."""
import json, numpy as np, cv2
from mcommon import *
S7 = json.load(open(W('m7_solve.json'))); PL = json.load(open(W('m8_place.json')))
WB_R, WB_B = PL['white_balance']['R'], PL['white_balance']['B']
Mc = np.array(PL['affine_to_tangent_plane_arcsec']['core']); Mk = np.array(S7['centre']['affine_to_tangent_plane_arcsec'])
# check pixel -> core pixel: core^-1 o check
def aug(M): return np.vstack([M, [0, 0, 1]])
T = np.linalg.inv(aug(Mc)) @ aug(Mk)          # 3x3: check half px -> core half px
core = np.load(W('core_rgb.npy')); P = np.load(W('centre_planes.npy')); flag = np.load(W('centre_flag.npy'))
rgb = np.dstack([P[0] * WB_R, (P[1] + P[2]) / 2, P[3] * WB_B]).astype(np.float32); rgb[flag != 1] = np.nan
h, w = core.shape[:2]
wk = cv2.warpAffine(rgb, T[:2], (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(np.nan,) * 3)
# stars: shared, by position
sc = json.load(open(W('m7_stars_core.json')))['stars']; sk = json.load(open(W('m7_stars_centre.json')))['stars']
ck = np.array([[s['x'], s['y']] for s in sk]); pk = (np.column_stack([ck, np.ones(len(ck))]) @ T[:2].T); cc = np.array([[s['x'], s['y']] for s in sc])
ratios = []; wts = []
nk = json.load(open(W('m6_centre.json')))['noise_of_stack_dn_per_half_grid_px']; nk = float(np.hypot(nk['G1'], nk['G2']) / 2)
sig = nk * np.sqrt(np.pi * 14 ** 2 * (1 + 1.57 * 14 ** 2 / (27 ** 2 - 19 ** 2)))
for i, p in enumerate(pk):
    d = np.hypot(*(cc - p).T); j = int(np.argmin(d))
    if d[j] < 2.0 and sk[i]['nearest'] > 24 and sc[j]['nearest'] > 24 and min(sk[i]['flux'], sc[j]['flux']) > 6000 and sc[j]['peak'] < 9000 and sk[i]['peak'] < 12000:
        ratios.append(np.log(sc[j]['flux'] / sk[i]['flux'])); wts.append(1 / ((sig / sk[i]['flux']) ** 2 + 0.02 ** 2))
ratios = np.array(ratios); wts = np.array(wts); keep = np.ones(len(ratios), bool)
for _ in range(4):
    m = np.sum(ratios[keep] * wts[keep]) / np.sum(wts[keep]); keep = np.abs(ratios - m) * np.sqrt(wts) < 3 * max(1.0, 1.4826 * np.median(np.abs((ratios - m) * np.sqrt(wts))[keep]))
mult = float(np.exp(m)); print('check frames: %d shared stars, multiplier %.4f -> transparency against the core\'s clear sky %.3f' % (keep.sum(), mult, (20 / 30) / mult))
d = wk * mult - core
BS = 64; ny, nx = h // BS, w // BS
X0 = (np.linalg.inv(aug(Mc)) @ np.array([0, 0, 1]))[:2]      # the nucleus in core half px
out = dict(shared_stars=int(keep.sum()), multiplier=mult, transparency_against_core=(20 / 30) / mult, colours={})
YY, XX = np.mgrid[0:ny, 0:nx]; xc = (XX + 0.5) * BS; yc = (YY + 0.5) * BS; rn = np.hypot(xc - X0[0], yc - X0[1]) * 0.776 / 60
for c, cn in enumerate('RGB'):
    b = d[:ny * BS, :nx * BS, c].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'): fr = np.isfinite(b).mean(2); bm = np.nanmedian(b, axis=2)
    ok = (fr > 0.6); far = ok & (rn > 13)
    A = np.column_stack([np.ones(far.sum()), (xc[far] - w / 2) / 1000, (yc[far] - h / 2) / 1000]); v = bm[far]
    co, *_ = np.linalg.lstsq(A, v, rcond=None); r_plane = v - A @ co; r_const = v - np.median(v)
    full = bm - (co[0] + co[1] * (xc - w / 2) / 1000 + co[2] * (yc - h / 2) / 1000)
    rings = []
    for a_, b_ in [(0.3, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 8), (8, 10), (10, 13)]:
        m_ = ok & (rn >= a_) & (rn < b_)
        if m_.sum() >= 3: rings.append(dict(arcmin=[a_, b_], excess_dn=float(np.median(full[m_]))))
    out['colours'][cn] = dict(blocks=int(far.sum()), constant=float(np.median(v)), plane=dict(constant=float(co[0]), slope_x_dn_per_1000px=float(co[1]), slope_y_dn_per_1000px=float(co[2])),
                              rms_after_constant_dn=float(np.sqrt(np.mean(r_const ** 2))), rms_after_plane_dn=float(np.sqrt(np.mean(r_plane ** 2))), p05_p95_after_plane=[float(np.percentile(r_plane, 5)), float(np.percentile(r_plane, 95))], excess_near_nucleus_after_plane=rings)
    print('%s: sky + cloud of the check frames above the core\'s zero %.1f DN; slope %+.1f, %+.1f DN per 1000 px; block rms after a constant %.2f, after a plane %.2f (5..95%%: %+.1f..%+.1f); excess near the nucleus: %s' % (
        cn, co[0], co[1], co[2], out['colours'][cn]['rms_after_constant_dn'], out['colours'][cn]['rms_after_plane_dn'], *out['colours'][cn]['p05_p95_after_plane'], ', '.join('%g-%g\': %+.1f' % (*r_['arcmin'], r_['excess_dn']) for r_ in rings)))
json.dump(out, open(W('m10b_centre_check.json'), 'w'), indent=1)
