"""Exploration (not used for the delivered mosaic unless said so in the recipe): what a second-order surface for
some panels would do to the overlap residuals."""
import json, itertools, sys
import numpy as np
from mcommon import *
PL = json.load(open(W('m8_place.json'))); R9 = json.load(open(W('m9_resample.json'))); grid = PL['grid']
IMAGES = PL['images']; BS = 64; z = np.load(W('m10_blocks.npz')); tabs = {k: (z[k + '_T'], z[k + '_N']) for k in IMAGES}
NBY, NBX = tabs['core'][0].shape[:2]; BY, BX = np.mgrid[0:NBY, 0:NBX]; XC = (BX + 0.5) * BS; YC = (BY + 0.5) * BS
RN = np.hypot(XC - grid['nucleus_pixel'][0], YC - grid['nucleus_pixel'][1]) * grid['pixel_scale_arcsec'] / 60
cen = {k: [(R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2] for k in IMAGES}
panels = IMAGES[1:]
def terms(k, x, y, order):
    u, v = (x - cen[k][0]) / 1000, (y - cen[k][1]) / 1000
    t = [1.0, u, v]
    if order == 2: t += [u * u, u * v, v * v]
    return t
def solve(c, orders):
    off = {}; n = 0
    for k in panels: off[k] = n; n += 6 if orders[k] == 2 else 3
    rows, rhs, wts, tags = [], [], [], []
    for a, b in itertools.combinations(IMAGES, 2):
        Ta, Na = tabs[a]; Tb, Nb = tabs[b]; ok = np.isfinite(Ta[:, :, c]) & np.isfinite(Tb[:, :, c]) & (RN > 13)
        if ok.sum() < 6: continue
        floor = np.nanpercentile(Ta[:, :, 1], 2)
        for by, bx in zip(*np.nonzero(ok)):
            r = np.zeros(n)
            for k, sgn in ((a, 1.0), (b, -1.0)):
                if k == 'core': continue
                t = terms(k, XC[by, bx], YC[by, bx], orders[k]); r[off[k]:off[k] + len(t)] = sgn * np.array(t)
            g = max(float(Ta[by, bx, 1] - floor), 0.0); s2 = (Na[by, bx] ** 2 + Nb[by, bx] ** 2) * [9, 1, 4][c] + 1.0
            rows.append(r); rhs.append(float(Ta[by, bx, c] - Tb[by, bx, c])); wts.append(1 / s2 / (1 + (g / 150) ** 2)); tags.append('%s-%s' % (a, b))
    A = np.array(rows); d = np.array(rhs); sw = np.sqrt(np.array(wts)); keep = np.ones(len(d), bool); tags = np.array(tags)
    for _ in range(6):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], d[keep] * sw[keep], rcond=None); res = d - A @ sol; zz = res * sw; keep = np.abs(zz) < 3 * 1.4826 * np.median(np.abs(zz[keep]))
    return sol, off, res, tags
if __name__ == '__main__':
    for label, orders in (('planes for all', {k: 1 for k in panels}), ('second order for p11 only', {k: (2 if k == 'p11' else 1) for k in panels}), ('second order for all', {k: 2 for k in panels})):
        sol, off, res, tags = solve(1, orders)
        print(label, ': green rms over all overlaps %.2f DN' % np.sqrt(np.mean(res ** 2)))
        print('   ' + '  '.join('%s %.2f' % (key, np.sqrt(np.mean(res[tags == key] ** 2))) for key in dict.fromkeys(tags)))
        for k in panels:
            nt = 6 if orders[k] == 2 else 3
            # the surface's range over the panel's own footprint (corners and edge midpoints), about its constant
            x0, y0, x1, y1 = R9[k]['bbox']; A_ = np.array(R9[k]['to_mosaic_pixels']); w, h = PL['size'][k]
            pts = [(A_ @ np.array([px, py, 1.0])) for px in (0, w / 2, w) for py in (0, h / 2, h)]
            vals = [float(np.dot(sol[off[k]:off[k] + nt], terms(k, p[0], p[1], orders[k]))) - sol[off[k]] for p in pts]
            print('   %s: constant %+.1f, surface over the panel %+.1f..%+.1f DN%s' % (k, sol[off[k]], min(vals), max(vals), '' if nt == 3 else '  second-order terms %s' % np.round(sol[off[k] + 3:off[k] + 6], 2).tolist()))
