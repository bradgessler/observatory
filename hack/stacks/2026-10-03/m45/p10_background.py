"""Step 10: the background between stacks, solved over ALL overlaps at once. Nothing is fitted to any stack by
itself; no free-form surface anywhere.

Data: 64 x 64 px blocks of the fine grid (50 arcsec). For each stack the median of each colour in a block (blocks
with at least 60% of their pixels from clean data; pixels under a mapped dust shadow are left out). For every
pair of stacks and every block both have: D = a - b. The stars, the glare that travels with the stars and the
nebulosity are the same in both and cancel; what is left is the difference of their backgrounds plus noise, plus
(photometric error) x (brightness), which is why blocks are weighted down where the picture is bright
(weight / (1 + (level / 150 DN)^2)).

Models (each solved per colour, weight 1 / variance of D from the stacks' noise maps, 3-sigma rejection):
 A  one additive constant per stack.
 B  one plane per stack (constant + two slopes about the stack's centre).
 E  one additive constant per stack + ONE PATTERN FIXED TO THE SENSOR, the same for every stack: an additive
    level under the flat, P(u, v) = sum of a_k u^i v^j (u, v = sensor x, y from the centre, -1..1), in DN of a raw
    frame. In a stack it appears as multiplier x mean(1 / transparency) x white balance x P / flat. The linear
    terms of P cannot be seen in differences between stacks (they are the same as shifting the constants) and are
    left out; the terms used are named in TERMS.
 G  E + a plane for the two stacks taken through passing cloud, (2,0) and (0,2) (CLOUD).
 K  as E, but the sensor pattern is measured from the nine CLEAR stacks alone (no pair with a cloud stack), then
    held fixed while every stack, the cloud ones too, gets its one constant. In that last solve every equation is
    also weighted by how much the mosaic really mixes the two stacks at that block: 4 wa wb / (wa + wb)^2 with
    wa, wb their weights in the combine (step 11) for two stacks of a kind, 4 F (1 - F) for a cloud stack against
    a clear one (F = the clear stacks' summed feather: the cloud stacks only fill in across the clear stacks'
    edge ramp). It is 1 where the mosaic hands over from one stack to the other and 0 where one of them carries
    the pixel alone. Where two stacks differ by more than a constant (the cloud stacks do), the constant is
    thereby chosen to make them meet where they are joined. THIS IS THE ONE USED.

Why not A: with constants alone the stacks disagree in their overlaps by 1.2 DN rms in green (noise alone 0.3),
with a slope of 5 to 7 DN per 1000 px ACROSS every strip where a stack's bottom edge meets its lower neighbour's
top edge, the same in every such pair. Why not B: planes do fit that (0.55 DN), but with slopes that go -5, +1,
+6 DN per 1000 px from the top row to the bottom row of the mosaic: what every stack really has is the same
shallow dome along the sensor's short side, and tilting the rows against each other only hides it at the seams
while bending the whole mosaic by some 20 DN, several times the nebulosity. The dome is additive and close to the
same number of raw DN in R, G and B (about -1.5 to -2 DN at the top and bottom edge against the middle; a
separate check, raw block level against frame sky level over all 72 frames, finds the same dome, -2 DN, in all
four colour planes): it is in the sensor's dark level, not in the light. K takes it off as what it is.
Why not G: the two cloud stacks do disagree with their neighbours by more than a constant (thin cloud spreads the
light of the bright stars into wide glows, and those are on the cluster's side of both stacks), but a plane
fitted to two edge strips and carried 3000 px to the far corner makes that corner 15 DN too dark. They get a
constant like the rest; their glows stay in and are named in the report.
The constants are fixed only up to one number per colour (the same amount added to every stack changes no
difference): the solve holds their mean at 0, and step 11 sets the mosaic's zero at its darkest clear part.
THE ABSOLUTE ZERO IS NOT KNOWN."""
import json, itertools, sys
import numpy as np, cv2
from c import *
from p9_resample import to_grid

PL = json.load(open(W('p8_place.json'))); R9 = json.load(open(W('p9_resample.json'))); grid = PL['grid']
IMAGES = PL['images']; BS = 64; NBX, NBY = grid['width'] // BS + 1, grid['height'] // BS + 1
TERMS = [(0, 0), (2, 0), (1, 1), (0, 2)]          # (i, j): u^i v^j / flat. (0, 0) is a plain pedestal
TERMS_WIDE = TERMS + [(3, 0), (2, 1), (1, 2), (0, 3), (4, 0), (2, 2), (0, 4)]
WBC = [PL['white_balance']['R'], 1.0, PL['white_balance']['B']]
blk = {}; nvar = {}; basis = {}; cw = {}; FCLEAR = np.zeros((NBY, NBX), np.float32)
BYc, BXc = np.mgrid[0:NBY, 0:NBX]; BXc = ((BXc + 0.5) * BS).astype(np.float32); BYc = ((BYc + 0.5) * BS).astype(np.float32)
for k in IMAGES:
    bx0, by0, bx1, by1 = R9[k]['bbox']
    img = np.load(W('grid/%s_rgb.npy' % k)); wv = np.load(W('grid/%s_invvar.npy' % k)); q = np.load(W('grid/%s_q.npy' % k)); fe = np.load(W('grid/%s_feather.npy' % k))
    fc = np.zeros((NBY * BS, NBX * BS), np.float32); fc[by0:by1, bx0:bx1] = fe * wv * q
    cw[k] = fc.reshape(NBY, BS, NBX, BS).mean((1, 3))           # the weight this stack has among its kind in the mosaic (step 11), block mean
    fc[:] = 0; fc[by0:by1, bx0:bx1] = fe
    if k not in CLOUD: FCLEAR = FCLEAR + fc.reshape(NBY, BS, NBX, BS).mean((1, 3))
    full = np.full((NBY * BS, NBX * BS, 3), np.nan, np.float32); full[by0:by1, bx0:bx1] = np.where((q[:, :, None] >= 1.0), img, np.nan)
    fw = np.zeros((NBY * BS, NBX * BS), np.float32); fw[by0:by1, bx0:bx1] = wv
    b = full.reshape(NBY, BS, NBX, BS, 3).transpose(0, 2, 1, 3, 4).reshape(NBY, NBX, BS * BS, 3)
    with np.errstate(all='ignore'):
        n = np.isfinite(b[..., 1]).sum(2); med = np.nanmedian(b, axis=2)
    med[n < 0.6 * BS * BS] = np.nan
    blk[k] = med
    wb_ = fw.reshape(NBY, BS, NBX, BS).transpose(0, 2, 1, 3).reshape(NBY, NBX, -1)
    with np.errstate(all='ignore'):
        mv = np.where(n > 0, 1.0 / np.maximum(np.median(wb_, axis=2), 1e-12), np.nan)
    nvar[k] = 1.57 * mv / np.maximum(n, 1)
    # the sensor pattern's terms at the block centres: block centre -> the stack's half-grid pixel -> u, v, flat
    A = to_grid(PL['affine_to_tangent_plane_arcsec'][k]); Ai = np.linalg.inv(np.vstack([A, [0, 0, 1]]))
    hx = Ai[0, 0] * (BXc - 0.5) + Ai[0, 1] * (BYc - 0.5) + Ai[0, 2]; hy = Ai[1, 0] * (BXc - 0.5) + Ai[1, 1] * (BYc - 0.5) + Ai[1, 2]
    fl = cv2.remap(np.load(W(k + '_flatref.npy')), hx.astype(np.float32), hy.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    u = (hx + 0.5 - W2 / 2) / (W2 / 2); v = (hy + 0.5 - H2 / 2) / (H2 / 2)
    amp = R9[k]['multiplier'] * R9[k]['mean_inverse_transparency_of_used_frames']
    basis[k] = {t: amp * u ** t[0] * v ** t[1] / fl for t in TERMS_WIDE}
cen = {k: ((R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2) for k in IMAGES}
WBN = [WBC[0] * np.sqrt(2), 1.0, WBC[2] * np.sqrt(2)]
floor = {c_: float(np.nanpercentile(np.concatenate([blk[k][..., c_][np.isfinite(blk[k][..., c_])] for k in IMAGES]), 5)) for c_ in range(3)}
pairs = []
for a, b in itertools.combinations(IMAGES, 2):
    both = np.isfinite(blk[a][..., 1]) & np.isfinite(blk[b][..., 1])
    if both.sum() >= 6: pairs.append((a, b, both))


def solve(c_, planes=(), terms=(), fixed_pattern=None, exclude=(), handover=False):
    """planes: True (every stack), or the names of the stacks that get two slopes besides their constant.
    fixed_pattern: coefficients (raw DN) of `terms` held fixed (taken off D before the solve) instead of solved.
    Returns constants+slopes as an (n, 3) array (slopes 0 where a stack has none)."""
    if planes is True: planes = tuple(IMAGES)
    planes = tuple(planes or ())
    idx = {k: i for i, k in enumerate(IMAGES)}; n = len(IMAGES); pidx = {k: n + 2 * i for i, k in enumerate(planes)}; npl = 2 * len(planes); nt = 0 if fixed_pattern is not None else len(terms)
    rows, rhs, wts, tag = [], [], [], []
    for a, b, both in pairs:
        if a in exclude or b in exclude: continue
        ys, xs = np.nonzero(both)
        D = blk[a][ys, xs, c_] - blk[b][ys, xs, c_]
        if fixed_pattern is not None:
            for t, co in zip(terms, fixed_pattern): D = D - WBC[c_] * co * (basis[a][t][ys, xs] - basis[b][t][ys, xs])
        lev = 0.5 * (blk[a][ys, xs, 1] + blk[b][ys, xs, 1]) - floor[1]
        var = (nvar[a][ys, xs] + nvar[b][ys, xs]) * WBN[c_] ** 2
        w = 1.0 / var / (1.0 + (lev / 150.0) ** 2)
        if handover:
            if (a in CLOUD) != (b in CLOUD):
                f_ = np.clip(FCLEAR[ys, xs], 0, 1); w = w * 4 * f_ * (1 - f_)          # a cloud stack meets the clear ones only across their edge ramp
            else:
                wa, wb_ = cw[a][ys, xs], cw[b][ys, xs]
                w = w * 4 * wa * wb_ / np.maximum(wa + wb_, 1e-30) ** 2
        R = np.zeros((len(ys), n + npl + nt))
        R[:, idx[a]] = 1.0; R[:, idx[b]] = -1.0
        if a in pidx: R[:, pidx[a]] = (BXc[ys, xs] - cen[a][0]) / 1000; R[:, pidx[a] + 1] = (BYc[ys, xs] - cen[a][1]) / 1000
        if b in pidx: R[:, pidx[b]] = -(BXc[ys, xs] - cen[b][0]) / 1000; R[:, pidx[b] + 1] = -(BYc[ys, xs] - cen[b][1]) / 1000
        for j, t in enumerate(terms if nt else ()):
            R[:, n + npl + j] = WBC[c_] * (basis[a][t][ys, xs] - basis[b][t][ys, xs])
        rows.append(R); rhs.append(D); wts.append(w); tag += [(a, b, int(y_), int(x_), float(l_)) for y_, x_, l_ in zip(ys, xs, lev)]
    A = np.vstack(rows); y = np.concatenate(rhs); w = np.concatenate(wts); keep = np.ones(len(y), bool)
    G = []; nn = n + npl + nt
    g = np.zeros(nn); g[0:n] = 1.0; G.append(g)                                       # the mean constant is 0
    if len(planes) == n:                                                             # every stack has a plane: a common tilt cancels in every difference
        g = np.zeros(nn); g[n:n + npl:2] = 1.0; G.append(g); g = np.zeros(nn); g[n + 1:n + npl:2] = 1.0; G.append(g)
    G = np.array(G) * 1e3
    for _ in range(6):
        sw = np.sqrt(w[keep]); Aa = np.vstack([A[keep] * sw[:, None], G]); ya = np.concatenate([y[keep] * sw, np.zeros(len(G))])
        sol, *_ = np.linalg.lstsq(Aa, ya, rcond=None)
        res = y - A @ sol; z = res * np.sqrt(w); s = 1.4826 * np.median(np.abs(z[keep])); keep = np.abs(z) < 3 * max(s, 1.0)
    Aw = A[keep] * np.sqrt(w[keep])[:, None]; cov = np.linalg.pinv(Aw.T @ Aw + G.T @ G) * max(s, 1.0) ** 2
    sig = np.sqrt(np.diag(cov))
    pat = [(float(sol[n + npl + j]), float(sig[n + npl + j])) for j in range(nt)]
    full = np.zeros((n, 3)); full[:, 0] = sol[:n]; fsig = np.zeros((n, 3)); fsig[:, 0] = sig[:n]
    for k, j in pidx.items(): full[idx[k], 1:] = sol[j:j + 2]; fsig[idx[k], 1:] = sig[j:j + 2]
    solve.sigma = fsig
    return full, res, w, keep, tag, pat


def stats(res, w, keep, tag):
    lev = np.array([t[4] for t in tag]); faint = keep & (lev < 60)
    per = {}
    for a, b, both in pairs:
        m = np.array([(t[0] == a and t[1] == b) for t in tag]); mk = m & keep; f = mk & (lev < 60)
        if mk.sum() < 3: continue
        cloudy = a in CLOUD or b in CLOUD
        slope = None
        if f.sum() >= 8:
            xs = np.array([BXc[t[2], t[3]] for t in tag])[f]; ys = np.array([BYc[t[2], t[3]] for t in tag])[f]; rr = res[f]
            p_ = np.column_stack([xs - xs.mean(), ys - ys.mean()]); u_, s_, vt = np.linalg.svd(p_, full_matrices=False); t_ = p_ @ vt[0]
            slope = dict(dn_per_1000px_along=float(np.polyfit(t_ / 1000, rr, 1)[0]), length_px=float(t_.max() - t_.min()), dn_per_1000px_across=float(np.polyfit((p_ @ vt[1]) / 1000, rr, 1)[0]) if s_[1] > 200 else None)
        per['%s-%s' % (a, b)] = dict(with_a_cloud_stack=cloudy, blocks=int(m.sum()), kept=int(mk.sum()), faint_blocks=int(f.sum()), mean_residual_dn=float(np.average(res[mk], weights=w[mk])),
                                     rms_residual_faint_dn=float(np.sqrt(np.mean(res[f] ** 2))) if f.any() else None, expected_noise_rms_faint_dn=float(np.sqrt(np.mean(1 / w[f]))) if f.any() else None, slope=slope)
    cl = np.array([(t[0] in CLOUD or t[1] in CLOUD) for t in tag])
    return dict(equations=int(len(res)), kept=int(keep.sum()), rms_residual_faint_dn_clear_pairs=float(np.sqrt(np.mean(res[faint & ~cl] ** 2))), rms_residual_faint_dn_pairs_with_a_cloud_stack=float(np.sqrt(np.mean(res[faint & cl] ** 2))) if (faint & cl).any() else None,
                expected_noise_rms_dn_clear_pairs=float(np.sqrt(np.mean(1 / w[faint & ~cl]))), rms_residual_faint_dn=float(np.sqrt(np.mean(res[faint] ** 2))), expected_noise_rms_dn=float(np.sqrt(np.mean(1 / w[faint]))),
                scatter_in_units_of_noise=float(1.4826 * np.median(np.abs(res[keep] * np.sqrt(w[keep])))), pairs=per)


def show_pairs(per):
    for key, v in per.items():
        sl = v['slope']
        print('       %-10s blocks %4d faint %4d  mean %+6.2f  rms %5.2f (noise %4.2f)  slope along %s over %s px, across %s' % (key, v['blocks'], v['faint_blocks'], v['mean_residual_dn'], v['rms_residual_faint_dn'] or -1, v['expected_noise_rms_faint_dn'] or -1,
              '%+6.2f DN/1000px' % sl['dn_per_1000px_along'] if sl else '   -  ', '%.0f' % sl['length_px'] if sl else '-', ('%+6.2f' % sl['dn_per_1000px_across']) if sl and sl['dn_per_1000px_across'] is not None else '-'))


def picture(tag, res, keep, label):
    rs = np.zeros((NBY, NBX)); cnt = np.zeros((NBY, NBX))
    for t, r_, k_ in zip(tag, res, keep):
        if k_: rs[t[2], t[3]] += abs(r_); cnt[t[2], t[3]] += 1
    v = np.where(cnt > 0, rs / np.maximum(cnt, 1), 0)
    cv2.imwrite(W('v_p10_absresid_%s.png' % label), cv2.resize((np.clip(v / 6.0, 0, 1) * 255).astype(np.uint8), None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST))


if __name__ == '__main__':
    out = dict(blocks_px=BS, floor_dn=floor, terms=['u^%d v^%d / flat' % t for t in TERMS], cloud_stacks=list(CLOUD), adopted='K', models={})
    MODELS = (('A_constants', dict()), ('B_planes', dict(planes=True)), ('E_constants_and_sensor_pattern_from_all_stacks', dict(terms=TERMS)),
              ('G_constants_sensor_pattern_and_planes_for_the_cloud_stacks', dict(planes=CLOUD, terms=TERMS)), ('K_constants_and_sensor_pattern_from_the_clear_stacks', None))
    for label, kw in MODELS:
        mod = {}
        for c_, cn in enumerate('RGB'):
            if kw is None:
                # the sensor pattern from the nine clear stacks alone, then held fixed while every stack gets its constant
                _, res0, w0, keep0, tag0, pat = solve(c_, terms=TERMS, exclude=CLOUD)
                st0 = stats(res0, w0, keep0, tag0)
                sol, res, w, keep, tag, _ = solve(c_, terms=TERMS, fixed_pattern=[p[0] for p in pat], handover=True); kwt = TERMS
            else:
                sol, res, w, keep, tag, pat = solve(c_, **kw); kwt = kw.get('terms', ()); st0 = None
            st = stats(res, w, keep, tag)
            mod[cn] = dict(solution={k: sol[i].tolist() for i, k in enumerate(IMAGES)}, solution_sigma={k: solve.sigma[i].tolist() for i, k in enumerate(IMAGES)},
                           sensor_pattern_raw_dn=[dict(term='u^%d v^%d' % t, ij=list(t), value=p[0], sigma=p[1]) for t, p in zip(kwt, pat)], **st)
            if st0: mod[cn]['pattern_fit_on_clear_stacks'] = dict(equations=st0['equations'], kept=st0['kept'], rms_residual_faint_dn=st0['rms_residual_faint_dn'], expected_noise_rms_dn=st0['expected_noise_rms_dn_clear_pairs'])
            print('%s %s: %d equations, %d kept; rms of residuals in faint blocks %.2f DN: clear pairs %.2f (noise alone %.2f), pairs with a cloud stack %s; scatter in units of noise %.2f' % (label, cn, st['equations'], st['kept'], st['rms_residual_faint_dn'],
                  st['rms_residual_faint_dn_clear_pairs'], st['expected_noise_rms_dn_clear_pairs'], '%.2f' % st['rms_residual_faint_dn_pairs_with_a_cloud_stack'], st['scatter_in_units_of_noise']))
            if pat: print('     sensor pattern, DN of a raw frame: ' + '  '.join('u^%d v^%d %+.2f+-%.2f' % (*t, *p) for t, p in zip(kwt, pat)))
            for i, k in enumerate(IMAGES): print('     %-5s %s' % (k, '  '.join('%+8.2f' % v for v in sol[i])))
            if label[0] in 'AK': show_pairs(st['pairs'])
            if cn == 'G': picture(tag, res, keep, label[0])
        out['models'][label[0]] = dict(name=label, **mod)
    json.dump(out, open(W('p10_background.json'), 'w'), indent=1)
