"""Mosaic step 10: the background. ONE additive constant per panel and colour, plus (model B) one plane per panel
and colour, solved over ALL overlaps at once so that the panels agree with each other and with the deep core
stack where they share sky. Nothing is fitted to any panel by itself; no free-form surface anywhere.

Data: 64 x 64 px blocks of the mosaic grid (50 arcsec). For each image the median of each colour in a block
(blocks with at least 60% of their pixels from clean data; pixels taken from the dust-divided combine are left
out). For every pair of images and every block both have: D = a - b. The galaxy and the true sky are the same in
both and cancel; what is left is the difference of their backgrounds (sky level, moonlight gradient, cloud glow,
flat-field error times sky) plus noise, plus (photometric error) x (galaxy), which is why blocks are weighted down
where the galaxy is bright (weight / (1 + (galaxy / 150 DN)^2)).

One more thing does not cancel, and it was found here: within about 10 arcmin of the nucleus the two centre
panels are BRIGHTER than the core stack by a smooth halo centred on the nucleus (panel (1,0): +19 DN green at
1 to 2 arcmin, +7 at 4 to 6, gone by 8; panel (1,1), the cloudiest: +40, +22, and +4 still at 10 to 13). That is
the bulge's own light scattered by the thin cloud the panels were taken through (their stars are at 59 to 75% of
the core run's). It is not background in the sense of this step, so blocks within NEAR_NUCLEUS arcmin of the
nucleus are kept OUT of the equations (they would pull the planes), and are reported separately.

Unknowns: for each panel p and colour, background_p(X, Y) = c_p [+ gx_p (X - Xp) / 1000 + gy_p (Y - Yp) / 1000],
(Xp, Yp) the panel's centre, in mosaic pixels. The core stack is the fixed reference (background 0: its own zero,
which is the darkest part of ITS field, not the sky). Equations: background_a - background_b = D for every
block of every overlap; weights 1 / (noise_a^2 + noise_b^2 + 1 DN^2); 3-sigma rejection; least squares.

Three models are solved and compared: A constants only; B constants + planes; and, as a yardstick only, what
each overlap would leave if it were fitted alone with its own constant (A1) or own plane (B1). The absolute zero
of the result is the core stack's and is NOT the sky: unknown."""
import json, itertools, sys
import numpy as np, cv2
from mcommon import *

PL = json.load(open(W('m8_place.json'))); R9 = json.load(open(W('m9_resample.json'))); grid = PL['grid']
IMAGES = PL['images']; BS = 64
NEAR_NUCLEUS = 13.0      # arcmin
NBX, NBY = grid['width'] // BS + 1, grid['height'] // BS + 1


def block_table(k):
    x0, y0, x1, y1 = R9[k]['bbox']
    rgb = np.load(W('grid/%s_rgb.npy' % k)); q = np.load(W('grid/%s_q.npy' % k)); iv = np.load(W('grid/%s_invvar.npy' % k))
    ok = np.isfinite(rgb).all(2) & (q > 0.99)
    T = np.full((NBY, NBX, 3), np.nan, np.float32); NZ = np.full((NBY, NBX), np.nan, np.float32)
    for by in range(y0 // BS, (y1 - 1) // BS + 1):
        for bx in range(x0 // BS, (x1 - 1) // BS + 1):
            ya, yb = max(by * BS - y0, 0), min((by + 1) * BS - y0, y1 - y0); xa, xb = max(bx * BS - x0, 0), min((bx + 1) * BS - x0, x1 - x0)
            if ya >= yb or xa >= xb: continue
            m = ok[ya:yb, xa:xb]
            if m.sum() < 0.6 * BS * BS: continue
            T[by, bx] = np.median(rgb[ya:yb, xa:xb][m], axis=0)
            NZ[by, bx] = 1.2533 / np.sqrt(np.median(iv[ya:yb, xa:xb][m])) / np.sqrt(m.sum())        # noise of a median of n values (green)
    return T, NZ


tabs = {}
if os.path.exists(W('m10_blocks.npz')) and 'cached' in sys.argv:
    z = np.load(W('m10_blocks.npz')); tabs = {k: (z[k + '_T'], z[k + '_N']) for k in IMAGES}
else:
    for k in IMAGES:
        tabs[k] = block_table(k); print(k, 'blocks', int(np.isfinite(tabs[k][0][:, :, 1]).sum()), flush=True)
    np.savez(W('m10_blocks.npz'), **{k + '_T': tabs[k][0] for k in IMAGES}, **{k + '_N': tabs[k][1] for k in IMAGES})
BY, BX = np.mgrid[0:NBY, 0:NBX]; XC = (BX + 0.5) * BS; YC = (BY + 0.5) * BS
RNUC = np.hypot(XC - grid['nucleus_pixel'][0], YC - grid['nucleus_pixel'][1]) * grid['pixel_scale_arcsec'] / 60      # arcmin from the nucleus
cen = {k: [(R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2] for k in IMAGES}
NOISE_COLOUR = dict(R=3.0, G=1.0, B=2.0)        # red and blue noise over green, roughly (white balance times the planes' noise): only the weights use it
panels = IMAGES[1:]; pid = {k: i for i, k in enumerate(panels)}


MODELS = dict(
    A_constants=dict(order={k: 0 for k in panels}, near_ok=()),
    B_constants_and_planes=dict(order={k: 1 for k in panels}, near_ok=()),
    C_planes_and_second_order_for_p11=dict(order={k: (2 if k == 'p11' else 1) for k in panels}, near_ok=()),
    D_as_C_with_p11_tied_to_the_core_near_the_nucleus=dict(order={k: (2 if k == 'p11' else 1) for k in panels}, near_ok=('p11',)))
NT = {0: 1, 1: 3, 2: 6}


def terms(k, x, y, order):
    u, v = (x - cen[k][0]) / 1000, (y - cen[k][1]) / 1000
    return [1.0, u, v, u * u, u * v, v * v][:NT[order]]


def equations(c, model):
    order = MODELS[model]['order']; near_ok = MODELS[model]['near_ok']
    off = {}; n = 0
    for k in panels: off[k] = n; n += NT[order[k]]
    rows, rhs, wts, tags, gal, pos, near = [], [], [], [], [], [], []
    for a, b in itertools.combinations(IMAGES, 2):
        Ta, Na = tabs[a]; Tb, Nb = tabs[b]
        ok = np.isfinite(Ta[:, :, c]) & np.isfinite(Tb[:, :, c])
        if ok.sum() < 6: continue
        floor = np.nanpercentile(Ta[:, :, 1], 2)
        allow_near = (a in near_ok or b in near_ok)
        for by, bx in zip(*np.nonzero(ok)):
            r = np.zeros(n)
            for k, sgn in ((a, 1.0), (b, -1.0)):
                if k == 'core': continue
                t = terms(k, XC[by, bx], YC[by, bx], order[k]); r[off[k]:off[k] + len(t)] = sgn * np.array(t)
            g = max(float(Ta[by, bx, 1] - floor), 0.0)
            f = 'RGB'[c]; s2 = (Na[by, bx] ** 2 + Nb[by, bx] ** 2) * NOISE_COLOUR[f] ** 2 + 1.0
            rows.append(r); rhs.append(float(Ta[by, bx, c] - Tb[by, bx, c])); wts.append(1.0 / s2 / (1 + (g / 150.0) ** 2)); tags.append((a, b)); gal.append(g); pos.append((bx, by))
            near.append(bool(RNUC[by, bx] < NEAR_NUCLEUS) and not allow_near)
    return np.array(rows), np.array(rhs), np.array(wts), tags, np.array(gal), pos, np.array(near), off


def solve(c, model):
    A, d, w, tags, gal, pos, near, off = equations(c, model)
    keep = ~near; sw = np.sqrt(w)
    for _ in range(6):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], d[keep] * sw[keep], rcond=None)
        res = d - A @ sol; z = res * sw; keep = ~near & (np.abs(z) < 3 * 1.4826 * np.median(np.abs(z[keep])))
    Aw = A[keep] * sw[keep, None]; cov = np.linalg.pinv(Aw.T @ Aw) * (1.4826 * np.median(np.abs((res * sw)[keep]))) ** 2
    return sol, np.sqrt(np.diag(cov)), res, keep, tags, gal, d, pos, near, off


def pair_stats(res, keep, tags, gal, d, pos):
    """Statistics per overlap, always over the same blocks: those more than NEAR_NUCLEUS from the nucleus; and separately the near ones."""
    out = {}
    tags_a = np.array(['%s-%s' % t for t in tags]); nr = np.array([RNUC[y, x] < NEAR_NUCLEUS for x, y in pos])
    for key in dict.fromkeys(tags_a):
        m = (tags_a == key) & ~nr
        if m.sum() < 6: continue
        r = res[m]; mn = (tags_a == key) & nr
        out[key] = dict(blocks=int(m.sum()), blocks_near_nucleus=int(mn.sum()), near_nucleus_median=float(np.median(res[mn])) if mn.sum() else None, near_nucleus_p05_p95=[float(np.percentile(res[mn], 5)), float(np.percentile(res[mn], 95))] if mn.sum() else None,
                        mean=float(np.mean(r)), median=float(np.median(r)), rms=float(np.sqrt(np.mean(r ** 2))), rms_about_own_mean=float(np.std(r)), p05=float(np.percentile(r, 5)), p95=float(np.percentile(r, 95)), raw_median_difference=float(np.median(d[m])))
    return out


def alone(tags, d, pos, plane):
    """Yardstick: each overlap fitted by itself with its own constant (or own plane), blocks away from the nucleus."""
    out = {}; tags_a = np.array(['%s-%s' % t for t in tags]); P = np.array(pos, float); nr = np.array([RNUC[y, x] < NEAR_NUCLEUS for x, y in pos])
    for key in dict.fromkeys(tags_a):
        m = (tags_a == key) & ~nr
        if m.sum() < 6: continue
        A = np.column_stack([np.ones(m.sum())] + ([P[m, 0] - P[m, 0].mean(), P[m, 1] - P[m, 1].mean()] if plane else []))
        co, *_ = np.linalg.lstsq(A, d[m], rcond=None); out[key] = float(np.sqrt(np.mean((d[m] - A @ co) ** 2)))
    return out


def surface_range(k, coef, order):
    """Least and greatest value of the panel's fitted surface over its own footprint, about its constant."""
    A_ = np.array(R9[k]['to_mosaic_pixels']); w, h = PL['size'][k]
    vals = [float(np.dot(coef, terms(k, *(A_ @ np.array([px, py, 1.0])), order))) - coef[0] for px in np.linspace(0, w, 7) for py in np.linspace(0, h, 5)]
    return [min(vals), max(vals)]


result = dict(near_nucleus_arcmin=NEAR_NUCLEUS, block_px=BS, panel_centres_mosaic_px=cen,
              surface='background_p(X, Y) = t0 + t1 u + t2 v [+ t3 u^2 + t4 u v + t5 v^2], u = (X - Xp) / 1000, v = (Y - Yp) / 1000, mosaic pixels, (Xp, Yp) the panel centre')
for c, cn in enumerate('RGB'):
    result[cn] = {}
    for model in MODELS:
        sol, err, res, keep, tags, gal, d, pos, near, off = solve(c, model)
        order = MODELS[model]['order']
        par = {k: dict(order=order[k], terms=[float(v) for v in sol[off[k]:off[k] + NT[order[k]]]], errors=[float(v) for v in err[off[k]:off[k] + NT[order[k]]]],
                       surface_min_max_over_the_panel_dn=surface_range(k, sol[off[k]:off[k] + NT[order[k]]], order[k])) for k in panels}
        st = pair_stats(res, keep, tags, gal, d, pos)
        nr = np.array([RNUC[y, x] < NEAR_NUCLEUS for x, y in pos])
        result[cn][model] = dict(parameters=par, overlaps=st, blocks=int(len(d)), blocks_in_equations=int((~near).sum()), blocks_kept=int(keep.sum()), rms_all_blocks_away_from_nucleus=float(np.sqrt(np.mean(res[~nr] ** 2))),
                                 each_overlap_fitted_alone_rms=alone(tags, d, pos, order['p00'] >= 1))
        np.savez(W('m10_residuals_%s_%s.npz' % (cn, model[0])), res=res, pos=np.array(pos), tags=np.array(['%s-%s' % t for t in tags]), gal=gal, keep=keep, near=near)
    print('\n=== %s ===' % cn)
    for model in MODELS:
        M_ = result[cn][model]
        print('%s: rms of block differences over all overlaps, blocks more than %.0f arcmin from the nucleus: %.2f DN' % (model, NEAR_NUCLEUS, M_['rms_all_blocks_away_from_nucleus']))
        print('    ' + '  '.join('%s %+.1f (%+.0f..%+.0f)' % (k, M_['parameters'][k]['terms'][0], *M_['parameters'][k]['surface_min_max_over_the_panel_dn']) for k in panels))
    keys = list(result[cn]['A_constants']['overlaps'])
    print('overlap      blocks | rms (5 to 95 percent) under A | B [fitted alone] | C | D | near the nucleus: blocks, median under B, C, D')
    for key in keys:
        o = {m[0]: result[cn][m]['overlaps'][key] for m in MODELS}
        print('  %-10s %5d | %5.2f (%+6.1f..%+5.1f) | %5.2f (%+5.1f..%+5.1f) [%.2f] | %5.2f (%+5.1f..%+5.1f) | %5.2f (%+5.1f..%+5.1f)%s' % (key, o['A']['blocks'], o['A']['rms'], o['A']['p05'], o['A']['p95'], o['B']['rms'], o['B']['p05'], o['B']['p95'],
              result[cn]['B_constants_and_planes']['each_overlap_fitted_alone_rms'][key], o['C']['rms'], o['C']['p05'], o['C']['p95'], o['D']['rms'], o['D']['p05'], o['D']['p95'],
              '' if not o['B']['blocks_near_nucleus'] else ' | %d: %+.1f, %+.1f, %+.1f' % (o['B']['blocks_near_nucleus'], o['B']['near_nucleus_median'], o['C']['near_nucleus_median'], o['D']['near_nucleus_median'])))
json.dump(result, open(W('m10_background.json'), 'w'), indent=1)
