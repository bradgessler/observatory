"""Step 11: combine the stacks into the mosaic on any north-up grid of the mosaic's tangent plane.

Per stack: RGB in common units (step 9) minus its background of step 10 (model K: one constant per stack and
colour; and the sensor-fixed additive pattern, the same four numbers per colour for every stack, as it appears in
the stack: multiplier x mean(1 / transparency) x white balance x P(u, v) / flat).
Then the weighted mean over the stacks that have data at a pixel, weight = feather x noise weight x quality
(step 9), the same weight for the three colours. No seams are cut: every stack fades over its feather.
The two stacks taken through cloud, (2,0) and (0,2), are combined the same way among themselves and then FILL IN
behind the clear ones: thin cloud spreads the light of their bright stars into wide glows, so where the clear
stacks are complete (their summed feather is 1) the cloud stacks are not used at all; across the clear stacks'
200 px edge ramp the picture goes over from clear to cloud data in step with that feather (F x clear + (1 - F)
x cloud); beyond the clear stacks' edge a cloud stack is all there is and is used as it is.

Zero: the constants of step 10 are fixed only up to one number per colour. The mosaic's zero is set, per colour,
at the level of its dark sky: the median over the DARKER HALF of its 64 px blocks (chosen by green, the same
blocks for the three colours), among the blocks in which no cloud stack has any weight (a cloud stack's constant
is tied to overlaps that lie in its glows, so its far side comes out too dark; such places go below zero and are
not what the zero is taken from). So the typical dark sky of the clear part is zero in all three colours and
about half of it lies a little below. Whatever sky, moonlight or thin wide nebulosity those places hold is called
zero: THE ABSOLUTE ZERO IS NOT KNOWN. (The very darkest 2% of the blocks, a patch at the west edge, lie 3 DN lower
in green: residual unevenness between and inside stacks is 1 to 3 DN, and the zero is not taken from an extreme.)

Noise: the expected noise of green in a pixel is carried through the weights (sqrt(sum of weight^2 x variance) /
sum of weights), from the single-frame noise measured in step 1; it is used only to choose how much the PICTURES
are smoothed where the data is thin (render.py), never on the linear file.

Grids: the fine grid of step 8 (0.7763 arcsec per px) for the whole mosaic; any other scale and window (the detail
crop at the sensor's own scale) is resampled from the stacks directly, never from the mosaic."""
import json, sys
import numpy as np, cv2
from c import *
import p9_resample as p9

PL = json.load(open(W('p8_place.json'))); R9 = json.load(open(W('p9_resample.json'))); BG = json.load(open(W('p10_background.json')))
grid = PL['grid']; PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['centre_pixel']; IMAGES = PL['images']
MODEL = BG['models'][BG['adopted']]
WBC = [PL['white_balance']['R'], 1.0, PL['white_balance']['B']]
cen = {k: ((R9[k]['bbox'][0] + R9[k]['bbox'][2]) / 2, (R9[k]['bbox'][1] + R9[k]['bbox'][3]) / 2) for k in IMAGES}
_loaded = {}


def loaded(k):
    if k not in _loaded: _loaded[k] = (p9.load(k), p9.NUSED.copy(), np.load(W(k + '_flatref.npy')))
    return _loaded[k]


def background(k, Xf, Yf):
    """The background of stack k (step 10, model G) at fine-grid pixel coordinates Xf, Yf: (h, w, 3), common units."""
    A = p9.to_grid(PL['affine_to_tangent_plane_arcsec'][k]); Ai = np.linalg.inv(np.vstack([A, [0, 0, 1]]))
    hx = (Ai[0, 0] * Xf + Ai[0, 1] * Yf + Ai[0, 2]).astype(np.float32); hy = (Ai[1, 0] * Xf + Ai[1, 1] * Yf + Ai[1, 2]).astype(np.float32)
    fl = cv2.remap(loaded(k)[2], hx, hy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    u = (hx + 0.5 - W2 / 2) / (W2 / 2); v = (hy + 0.5 - H2 / 2) / (H2 / 2)
    amp = R9[k]['multiplier'] * R9[k]['mean_inverse_transparency_of_used_frames']
    out = np.zeros(Xf.shape + (3,), np.float32)
    for c_, cn in enumerate('RGB'):
        s = MODEL[cn]['solution'][k]
        b = s[0] + s[1] * (Xf - cen[k][0]) / 1000 + s[2] * (Yf - cen[k][1]) / 1000
        P = sum(t['value'] * u ** t['ij'][0] * v ** t['ij'][1] for t in MODEL[cn]['sensor_pattern_raw_dn'])
        out[..., c_] = b + WBC[c_] * amp * P / fl
    return out


def combine(ps, x0, y0, width, height, names=None, subtract_background=True):
    """Mosaic on the grid X = x0 - xi / ps, Y = y0 - eta / ps (pixel-index coordinates). Returns mosaic (nan where no
    data), summed weight, ceiling mask, frames per pixel, stacks per pixel, and per stack its bbox."""
    acc = {g: np.zeros((height, width, 3), np.float32) for g in (0, 1)}; ws = {g: np.zeros((height, width), np.float32) for g in (0, 1)}; vn = {g: np.zeros((height, width), np.float32) for g in (0, 1)}
    fsum = np.zeros((height, width), np.float32); sat = np.zeros((height, width), bool)
    frames = np.zeros((height, width), np.uint8); nst = np.zeros((height, width), np.uint8); boxes = {}
    todo = []
    for k in names or IMAGES:
        ld, nused, fl = loaded(k); h, w = ld[1].shape
        A = p9.to_grid(PL['affine_to_tangent_plane_arcsec'][k], ps, x0, y0)
        c_ = (A @ np.array([[-0.5, -0.5, 1], [w - 0.5, -0.5, 1], [w - 0.5, h - 0.5, 1], [-0.5, h - 0.5, 1]]).T).T
        bx0, by0 = max(int(np.floor(c_[:, 0].min())) - 2, 0), max(int(np.floor(c_[:, 1].min())) - 2, 0); bx1, by1 = min(int(np.ceil(c_[:, 0].max())) + 3, width), min(int(np.ceil(c_[:, 1].max())) + 3, height)
        if bx1 <= bx0 or by1 <= by0: continue
        Ab = A.copy(); Ab[0, 2] -= bx0; Ab[1, 2] -= by0
        p9.NUSED = nused
        img, wv, fe, qq, st, ok = p9.warp(k, ld, Ab, (bx1 - bx0, by1 - by0))
        if not ok.any(): continue
        if subtract_background:
            Yg, Xg = np.mgrid[by0:by1, bx0:bx1].astype(np.float32)
            Xf = X0 - (x0 - Xg) * (ps / PS); Yf = Y0 - (y0 - Yg) * (ps / PS)
            img -= background(k, Xf, Yf)
        wgt = (fe * wv * qq).astype(np.float32); wgt[~ok] = 0
        g = 1 if k in CLOUD else 0; sl = (slice(by0, by1), slice(bx0, bx1))
        acc[g][sl] += np.where(ok[..., None], img, 0) * wgt[..., None]; ws[g][sl] += wgt
        vn[g][sl] += np.where(wv > 0, wgt * wgt / np.maximum(wv, 1e-30), 0)          # weight^2 x variance
        if g == 0: fsum[sl] += np.where(ok, fe, 0)
        todo.append((k, sl, st, p9.NUW.copy(), ok, g))
        boxes[k] = [bx0, by0, bx1, by1]
    has_c = ws[0] > 0; has_k = ws[1] > 0; both = has_c & has_k
    F = np.where(has_c, np.clip(fsum, 0, 1), 0).astype(np.float32)            # how complete the clear stacks are here: 1 inside them, ramping to 0 at their edge
    Fk = np.where(both, 1 - F, np.where(has_k, 1.0, 0.0)).astype(np.float32)  # the cloud stacks' share of the pixel
    with np.errstate(invalid='ignore', divide='ignore'):
        Mc = np.where(has_c[..., None], acc[0] / np.where(has_c, ws[0], 1)[..., None], 0); Mk = np.where(has_k[..., None], acc[1] / np.where(has_k, ws[1], 1)[..., None], 0)
        mos = np.where((has_c | has_k)[..., None], (1 - Fk)[..., None] * Mc + Fk[..., None] * Mk, np.nan).astype(np.float32)
        vc = np.where(has_c, vn[0] / np.where(has_c, ws[0], 1) ** 2, 0); vk = np.where(has_k, vn[1] / np.where(has_k, ws[1], 1) ** 2, 0)
        var = (1 - Fk) ** 2 * vc + Fk ** 2 * vk
    for k, sl, st, nuw, ok, g in todo:
        used = ok & ((Fk[sl] > 0) if g == 1 else (Fk[sl] < 1))            # a cloud stack is not used where the clear stacks are complete
        sat[sl] |= st & used; frames[sl] += np.where(used, nuw, 0).astype(np.uint8); nst[sl] += used
    combine.cloud_share = Fk
    combine.noise = np.where(has_c | has_k, np.sqrt(var), np.nan).astype(np.float32)   # expected noise of green in one pixel of this grid, DN
    return mos, ws[0] + ws[1], sat, frames, nst, boxes


if __name__ == '__main__':
    Wm, Hm = grid['width'], grid['height']
    mos, wsum, sat, frames, nst, boxes = combine(PS, X0, Y0, Wm, Hm)
    # zero: the darkest 2% of the 64 px blocks
    BS = 64; nby, nbx = Hm // BS, Wm // BS
    b = mos[:nby * BS, :nbx * BS].reshape(nby, BS, nbx, BS, 3).transpose(0, 2, 1, 3, 4).reshape(nby, nbx, BS * BS, 3)
    with np.errstate(all='ignore'):
        n = np.isfinite(b[..., 1]).sum(2); med = np.nanmedian(b, axis=2)
    cs = combine.cloud_share[:nby * BS, :nbx * BS].reshape(nby, BS, nbx, BS).max((1, 3))
    okb = (n >= 0.9 * BS * BS) & (cs == 0)
    g3 = cv2.medianBlur(np.where(okb, med[..., 1], 1e6).astype(np.float32), 3)
    cand = okb & (g3 < 1e5)
    thr = np.percentile(g3[cand], 50); dark = cand & (g3 <= thr)
    zero = [float(np.median(med[..., c_][dark])) for c_ in range(3)]
    d2 = cand & (g3 <= np.percentile(g3[cand], 2)); darkest = [float(np.median(med[..., c_][d2])) for c_ in range(3)]
    ys, xs = np.nonzero(d2)
    where = [[float((X0 - (x_ + 0.5) * BS) * PS / 60), float((Y0 - (y_ + 0.5) * BS) * PS / 60)] for y_, x_ in zip(ys, xs)]
    pct = {str(p_): [float(np.percentile(med[..., c_][cand], p_)) - zero[c_] for c_ in range(3)] for p_ in (2, 10, 25, 50, 75, 90, 98)}
    mos -= np.array(zero, np.float32)
    np.save(W('mosaic_fine.npy'), mos); np.save(W('mosaic_fine_w.npy'), wsum); np.save(W('mosaic_fine_sat.npy'), sat); np.save(W('mosaic_fine_frames.npy'), frames); np.save(W('mosaic_fine_nst.npy'), nst); np.save(W('mosaic_fine_cloudshare.npy'), combine.cloud_share); np.save(W('mosaic_fine_noise.npy'), combine.noise)
    okm = wsum > 0
    json.dump(dict(grid=grid, zero_dn=dict(zip('RGB', zero)), zero_blocks=int(dark.sum()), clear_blocks=int(cand.sum()), zero_block_px=BS, darkest_2_percent_of_clear_blocks_against_the_zero_dn=dict(zip('RGB', [d - z for d, z in zip(darkest, zero)])),
                   darkest_2_percent_blocks_offsets_arcmin_east_north_first_20=where[:20], clear_block_levels_against_the_zero_dn_by_percentile_RGB=pct,
                   pixels_with_data=int(okm.sum()), area_sq_deg=float(okm.sum() * PS * PS / 3600 ** 2), frames_per_pixel=dict(max=int(frames.max()), median_where_data=float(np.median(frames[okm]))),
                   stacks_per_pixel={str(i): int((nst == i).sum()) for i in range(int(nst.max()) + 1)}, boxes=boxes), open(W('p11_combine.json'), 'w'), indent=1)
    print('mosaic %d x %d fine px; data on %.2f sq deg; zero (median of the darker half of the clear blocks, %d blocks) R %.2f G %.2f B %.2f DN of the mean-zero solution; frames per pixel up to %d' % (Wm, Hm, okm.sum() * PS * PS / 3600 ** 2, dark.sum(), *zero, frames.max()))
    print('clear block levels against the zero, percentiles 2 10 25 50 75 90 98 (R G B):', {k: np.round(v, 1).tolist() for k, v in pct.items()})
    # a quick look: binned 8x, green and colour
    q8 = mos[:Hm // 8 * 8, :Wm // 8 * 8].reshape(Hm // 8, 8, Wm // 8, 8, 3)
    with np.errstate(all='ignore'): q = np.nanmean(q8, axis=(1, 3))
    np.save(W('mosaic_q8.npy'), q)
    for nm, sc in (('a', 12.0), ('b', 40.0)):
        v = np.clip(np.nan_to_num(q, nan=0.0), 0, None); lum = v.mean(2, keepdims=True)
        g = np.arcsinh(lum / sc) / np.arcsinh(4000.0 / sc) / np.maximum(lum, 1e-6)
        o = np.clip(v * g, 0, 1) ** (1 / 2.2)
        cv2.imwrite(W('v_mosaic_q8_%s.png' % nm), (o[..., ::-1] * 255 + 0.5).astype(np.uint8))
