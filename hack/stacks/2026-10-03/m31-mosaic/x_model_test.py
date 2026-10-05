"""Exploration: candidate background models for the cloudiest panel, judged by (a) the overlap residuals, (b) how
well blocks NOT used in the fit (near the nucleus) are predicted, (c) whether the panel's own background-subtracted
level anywhere falls well below the zero of the mosaic (it cannot in truth)."""
import json, itertools, sys
import numpy as np
from mcommon import *
PL = json.load(open(W('m8_place.json'))); R9 = json.load(open(W('m9_resample.json'))); grid = PL['grid']
IMAGES = PL['images']; BS = 64; z = np.load(W('m10_blocks.npz')); tabs = {k: (z[k + '_T'], z[k + '_N']) for k in IMAGES}
NBY, NBX = tabs['core'][0].shape[:2]; BY, BX = np.mgrid[0:NBY, 0:NBX]; XC = (BX + 0.5) * BS; YC = (BY + 0.5) * BS
RN = np.hypot(XC - grid['nucleus_pixel'][0], YC - grid['nucleus_pixel'][1]) * grid['pixel_scale_arcsec'] / 60
cen = {k: [(R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2] for k in IMAGES}
panels = IMAGES[1:]
# unit vector of each panel's long axis in mosaic pixels
ax = {}
for k in panels:
    A = np.array(R9[k]['to_mosaic_pixels']); e = A[:, 0] / np.hypot(*A[:, 0]); ax[k] = e
def terms(k, x, y, kind):
    u, v = (x - cen[k][0]) / 1000, (y - cen[k][1]) / 1000
    if kind == 'plane': return [1.0, u, v]
    if kind == 'quad': return [1.0, u, v, u * u, u * v, v * v]
    if kind == 'bow': ul = u * ax[k][0] + v * ax[k][1]; return [1.0, u, v, ul * ul]
def solve(c, kinds):
    off = {}; n = 0
    for k in panels: off[k] = n; n += len(terms(k, 0, 0, kinds[k]))
    rows, rhs, wts, tags, nr, pos = [], [], [], [], [], []
    for a, b in itertools.combinations(IMAGES, 2):
        Ta, Na = tabs[a]; Tb, Nb = tabs[b]; ok = np.isfinite(Ta[:, :, c]) & np.isfinite(Tb[:, :, c])
        if ok.sum() < 6: continue
        floor = np.nanpercentile(Ta[:, :, 1], 2)
        for by, bx in zip(*np.nonzero(ok)):
            r = np.zeros(n)
            for k, sgn in ((a, 1.0), (b, -1.0)):
                if k == 'core': continue
                t = terms(k, XC[by, bx], YC[by, bx], kinds[k]); r[off[k]:off[k] + len(t)] = sgn * np.array(t)
            g = max(float(Ta[by, bx, 1] - floor), 0.0); s2 = (Na[by, bx] ** 2 + Nb[by, bx] ** 2) * [9, 1, 4][c] + 1.0
            rows.append(r); rhs.append(float(Ta[by, bx, c] - Tb[by, bx, c])); wts.append(1 / s2 / (1 + (g / 150) ** 2)); tags.append('%s-%s' % (a, b)); nr.append(RN[by, bx] < 13); pos.append((bx, by))
    A = np.array(rows); d = np.array(rhs); sw = np.sqrt(np.array(wts)); nr = np.array(nr); keep = ~nr; tags = np.array(tags)
    for _ in range(6):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], d[keep] * sw[keep], rcond=None); res = d - A @ sol; zz = res * sw; keep = ~nr & (np.abs(zz) < 3 * 1.4826 * np.median(np.abs(zz[keep])))
    return sol, off, res, tags, nr
for label, kinds in (('B planes', {k: 'plane' for k in panels}), ('C p11 second order', {k: ('quad' if k == 'p11' else 'plane') for k in panels}), ('E p11 plane + bow along its length', {k: ('bow' if k == 'p11' else 'plane') for k in panels}),
                     ('F bow for p11 and p10', {k: ('bow' if k in ('p11', 'p10') else 'plane') for k in panels}), ('G bow for all', {k: 'bow' for k in panels})):
    out = []
    for c in (1, 0):
        sol, off, res, tags, nr = solve(c, kinds)
        far = ~nr
        line = '%s [%s]: rms away from the nucleus %.2f; p11 pairs: %s; near the nucleus core-p11 median %+.1f, p10-p11 %+.1f, core-p10 %+.1f' % (label, 'RGB'[c], np.sqrt(np.mean(res[far] ** 2)),
               ' '.join('%s %.2f' % (key, np.sqrt(np.mean(res[far & (tags == key)] ** 2))) for key in ('core-p11', 'p10-p11', 'p21-p11', 'p11-p01', 'p00-p11', 'p20-p11')),
               np.median(res[nr & (tags == 'core-p11')]), np.median(res[nr & (tags == 'p10-p11')]), np.median(res[nr & (tags == 'core-p10')]))
        print(line)
        # each panel's own background-subtracted block medians: the lowest 2% and where
        lows = []
        for k in panels:
            T = tabs[k][0][:, :, c]; ok = np.isfinite(T)
            nt = len(terms(k, 0, 0, kinds[k])); S = np.zeros_like(T)
            for by, bx in zip(*np.nonzero(ok)): S[by, bx] = np.dot(sol[off[k]:off[k] + nt], terms(k, XC[by, bx], YC[by, bx], kinds[k]))
            v = (T - S)[ok]; p2 = np.percentile(v, 2); i = np.argmin(np.abs(v - p2)); by, bx = [a_[i] for a_ in np.nonzero(ok)]
            lows.append('%s %+.1f at (%+.0f E, %+.0f N)' % (k, p2, (grid['nucleus_pixel'][0] - XC[by, bx]) * 0.776 / 60, (grid['nucleus_pixel'][1] - YC[by, bx]) * 0.776 / 60))
        print('      lowest 2%% of each panel\'s own blocks after its background: ' + '; '.join(lows))
