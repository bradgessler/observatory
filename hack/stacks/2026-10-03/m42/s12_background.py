"""Step 12: the backgrounds of the panels. ONE additive constant per panel and colour, plus (model B) one plane
per panel and colour, solved over ALL overlaps at once so that the panels agree with each other and with the
deep centred stack where they share sky (method of the M31 mosaic run, m10_background.py). Nothing is fitted to
any panel by itself; no free-form surface anywhere.

Data: 64 x 64 px blocks of the mosaic grid (50 arcsec). For each stack the median of each colour in a block
(blocks with at least 60% of their pixels from clean data). For every pair of stacks and every block both
have: D = a - b. The nebula and the true sky are the same in both and cancel; what is left is the difference of
their backgrounds (sky level, moonlight gradient, cloud glow, flat-field error times sky) plus noise, plus
(photometric error) x (nebula), which is why blocks are weighted down where the nebula is bright (weight / (1 +
(nebula / 150 DN)^2)) and blocks within NEAR arcmin of the Trapezium are kept out of the equations altogether
(there, too, thin cloud scatters the bright core's light into a halo that is not background).

Unknowns: for each panel p and colour, background_p(X, Y) = c_p [+ gx_p (X - Xp) / 1000 + gy_p (Y - Yp) / 1000],
(Xp, Yp) the panel's centre, in mosaic pixels. The deep stack is the fixed reference (background 0: its own
sky is still in it and is taken off the whole mosaic as one constant per colour in step 13). Equations:
background_a - background_b = D for every block of every overlap; weights 1 / (noise_a^2 + noise_b^2 + 1 DN^2);
3-sigma rejection; least squares. Model A (constants) and model B (constants and planes) are both solved and
compared; as a yardstick, what each overlap would leave if fitted alone (A1, B1)."""
import json, itertools, sys
import numpy as np, cv2
from common import *

PL = json.load(open(W('s10_place.json'))); R9 = json.load(open(W('s11_resample.json'))); grid = PL['grid']
IMAGES = PL['images']; BS = 64
NEAR = 6.0      # arcmin
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
            NZ[by, bx] = 1.2533 / np.sqrt(np.median(iv[ya:yb, xa:xb][m])) / np.sqrt(m.sum())
    return T, NZ


tabs = {}
for k in IMAGES:
    tabs[k] = block_table(k); print(k, 'blocks', int(np.isfinite(tabs[k][0][:, :, 1]).sum()), flush=True)
np.savez(W('s12_blocks.npz'), **{k + '_T': tabs[k][0] for k in IMAGES}, **{k + '_N': tabs[k][1] for k in IMAGES})
BY, BX = np.mgrid[0:NBY, 0:NBX]; XC = (BX + 0.5) * BS; YC = (BY + 0.5) * BS
RC = np.hypot(XC - grid['trapezium_pixel'][0], YC - grid['trapezium_pixel'][1]) * grid['pixel_scale_arcsec'] / 60
cen = {k: [(R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2] for k in IMAGES}
NOISE_COLOUR = dict(R=0.8, G=1.0, B=0.85)        # red and blue plane noise over green's (one plane against the mean of two), roughly: only the weights use it
panels = IMAGES[1:]
MODELS = dict(A_constants={k: 0 for k in panels}, B_constants_and_planes={k: 1 for k in panels})
NT = {0: 1, 1: 3}
floor_g = float(np.nanpercentile(tabs['deep'][0][:, :, 1], 2))


def terms(k, x, y, order):
    u, v = (x - cen[k][0]) / 1000, (y - cen[k][1]) / 1000
    return [1.0, u, v][:NT[order]]


def equations(c, model):
    order = MODELS[model]
    off = {}; n = 0
    for k in panels: off[k] = n; n += NT[order[k]]
    rows, rhs, wts, tags, neb, pos, near = [], [], [], [], [], [], []
    for a, b in itertools.combinations(IMAGES, 2):
        Ta, Na = tabs[a]; Tb, Nb = tabs[b]
        ok = np.isfinite(Ta[:, :, c]) & np.isfinite(Tb[:, :, c])
        if ok.sum() < 6: continue
        for by, bx in zip(*np.nonzero(ok)):
            r = np.zeros(n)
            for k, sgn in ((a, 1.0), (b, -1.0)):
                if k == 'deep': continue
                t = terms(k, XC[by, bx], YC[by, bx], order[k]); r[off[k]:off[k] + len(t)] = sgn * np.array(t)
            g = max(float(min(Ta[by, bx, 1], Tb[by, bx, 1]) - floor_g), 0.0)
            f = 'RGB'[c]; s2 = (Na[by, bx] ** 2 + Nb[by, bx] ** 2) * NOISE_COLOUR[f] ** 2 + 1.0
            rows.append(r); rhs.append(float(Ta[by, bx, c] - Tb[by, bx, c])); wts.append(1.0 / s2 / (1 + (g / 150.0) ** 2)); tags.append((a, b)); neb.append(g); pos.append((bx, by))
            near.append(bool(RC[by, bx] < NEAR))
    return np.array(rows), np.array(rhs), np.array(wts), tags, np.array(neb), pos, np.array(near), off


def solve(c, model):
    A, d, w, tags, neb, pos, near, off = equations(c, model)
    keep = ~near; sw = np.sqrt(w)
    for _ in range(6):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], d[keep] * sw[keep], rcond=None)
        res = d - A @ sol; z = res * sw; keep = ~near & (np.abs(z) < 3 * 1.4826 * np.median(np.abs(z[keep])))
    Aw = A[keep] * sw[keep, None]; cov = np.linalg.pinv(Aw.T @ Aw) * (1.4826 * np.median(np.abs((res * sw)[keep]))) ** 2
    return sol, np.sqrt(np.diag(cov)), res, keep, tags, neb, d, pos, near, off


def pair_stats(res, keep, tags, neb, d, pos, near):
    out = {}
    tags_a = np.array(['%s-%s' % t for t in tags])
    for key in dict.fromkeys(tags_a):
        m = (tags_a == key) & ~near & (neb < 300)
        if m.sum() < 6: continue
        r = res[m]; mn = (tags_a == key) & near
        out[key] = dict(blocks=int(m.sum()), blocks_near_the_core=int(mn.sum()), near_the_core_median=float(np.median(res[mn])) if mn.sum() else None,
                        mean=float(np.mean(r)), median=float(np.median(r)), rms=float(np.sqrt(np.mean(r ** 2))), p05=float(np.percentile(r, 5)), p95=float(np.percentile(r, 95)), raw_median_difference=float(np.median(d[m])))
    return out


def alone(tags, d, pos, near, neb, plane):
    out = {}; tags_a = np.array(['%s-%s' % t for t in tags]); P = np.array(pos, float)
    for key in dict.fromkeys(tags_a):
        m = (tags_a == key) & ~near & (neb < 300)
        if m.sum() < 6: continue
        A = np.column_stack([np.ones(m.sum())] + ([P[m, 0] - P[m, 0].mean(), P[m, 1] - P[m, 1].mean()] if plane else []))
        co, *_ = np.linalg.lstsq(A, d[m], rcond=None); out[key] = float(np.sqrt(np.mean((d[m] - A @ co) ** 2)))
    return out


def surface_range(k, coef, order):
    A_ = np.array(R9[k]['to_mosaic_pixels']); w, h = PL['size'][k]
    vals = [float(np.dot(coef, terms(k, *(A_ @ np.array([px, py, 1.0])), order))) - coef[0] for px in np.linspace(0, w, 7) for py in np.linspace(0, h, 5)]
    return [min(vals), max(vals)]


result = dict(near_core_arcmin=NEAR, block_px=BS, panel_centres_mosaic_px=cen, nebula_floor_green_dn=floor_g,
              surface='background_p(X, Y) = t0 + t1 u + t2 v, u = (X - Xp) / 1000, v = (Y - Yp) / 1000, mosaic pixels, (Xp, Yp) the panel centre')
for c, cn in enumerate('RGB'):
    result[cn] = {}
    for model in MODELS:
        sol, err, res, keep, tags, neb, d, pos, near, off = solve(c, model)
        order = MODELS[model]
        par = {k: dict(order=order[k], terms=[float(v) for v in sol[off[k]:off[k] + NT[order[k]]]], errors=[float(v) for v in err[off[k]:off[k] + NT[order[k]]]],
                       surface_min_max_over_the_panel_dn=surface_range(k, sol[off[k]:off[k] + NT[order[k]]], order[k])) for k in panels}
        st = pair_stats(res, keep, tags, neb, d, pos, near)
        faint = ~near & (neb < 300)
        result[cn][model] = dict(parameters=par, overlaps=st, blocks=int(len(d)), blocks_in_equations=int((~near).sum()), blocks_kept=int(keep.sum()), rms_faint_blocks_away_from_core=float(np.sqrt(np.mean(res[faint] ** 2))),
                                 each_overlap_fitted_alone_rms=alone(tags, d, pos, near, neb, order[panels[0]] >= 1))
    print('\n=== %s ===' % cn)
    for model in MODELS:
        M_ = result[cn][model]
        print('%s: rms of block differences over all overlaps (faint blocks, more than %.0f arcmin from the Trapezium): %.2f DN' % (model, NEAR, M_['rms_faint_blocks_away_from_core']))
        print('    ' + '  '.join('%s %+.1f (%+.0f..%+.0f)' % (k, M_['parameters'][k]['terms'][0], *M_['parameters'][k]['surface_min_max_over_the_panel_dn']) for k in panels))
    print('overlap        blocks | rms (5 to 95 percent) under A [alone] | under B [alone] | near the core: blocks, median under B')
    for key in result[cn]['A_constants']['overlaps']:
        o = {m[0]: result[cn][m]['overlaps'][key] for m in MODELS}
        print('  %-13s %5d | %5.2f (%+6.1f..%+5.1f) [%.2f] | %5.2f (%+5.1f..%+5.1f) [%.2f]%s' % (key, o['A']['blocks'], o['A']['rms'], o['A']['p05'], o['A']['p95'], result[cn]['A_constants']['each_overlap_fitted_alone_rms'][key], o['B']['rms'], o['B']['p05'], o['B']['p95'],
              result[cn]['B_constants_and_planes']['each_overlap_fitted_alone_rms'][key], '' if not o['B']['blocks_near_the_core'] else ' | %d: %+.1f' % (o['B']['blocks_near_the_core'], o['B']['near_the_core_median'])))
json.dump(result, open(W('s12_background.json'), 'w'), indent=1)
