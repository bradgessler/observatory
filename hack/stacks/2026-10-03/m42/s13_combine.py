"""Step 13: combine (method of the M31 mosaic run, m11_combine.py). Per pixel and colour:

    mosaic = sum_k W_k (stack_k - background_k) / sum_k W_k,   W_k = feather_k x inverse variance_k x quality_k

stack_k in the deep stack's units (step 11), background_k = the panel's fitted background of step 12 (model B:
a constant and a plane per colour; zero for the deep centred stack), the same W for the three colours. Where
the deep centred stack (HDR) covers the sky it carries most of the weight by its lower noise alone; toward its
edge its feather hands over to the panels. A pixel no stack covers stays without data; nothing is filled in.

THE ZERO: one constant per colour, taken off the whole mosaic and, the same three numbers, off the centred
picture. They are the levels of R, G and B in the DARKEST well-covered part of the whole mosaic: the 3-sigma
clipped mean of each colour over the 64 px blocks whose smoothed green is in the lowest 2% (blocks fully
covered, clean, at least 150 px inside the footprint). That region is made black and neutral by this choice. It
is NOT a measured sky: the Orion Nebula's outer glow and the dust of the Orion cloud fill the whole field, and
whatever they give in the darkest part (plus the moonlit sky, plus 45 to 77 DN of dark signal) goes with it.

Written (working grid, 0.776 arcsec/px): mosaic_rgb.npy, mosaic_noise.npy (expected 1-sigma of green in one pixel,
from the weights; 0 = no data), mosaic_cover.npy (bit mask of the stacks that contribute), mosaic_share.npy (the
deep centred stack's share of the weight, 0..255), mosaic_white.npy (weighted white mark, 0..1)."""
import json, sys, warnings
warnings.filterwarnings('ignore', message='All-NaN slice encountered')
import numpy as np, cv2
from common import *

PL = json.load(open(W('s10_place.json'))); R9 = json.load(open(W('s11_resample.json'))); BG = json.load(open(W('s12_background.json'))); grid = PL['grid']
Hm, Wm = grid['height'], grid['width']
IMAGES = PL['images']
BIT = {k: 1 << i for i, k in enumerate(IMAGES)}
MODEL = 'B_constants_and_planes'
# the colour pedestal of each stack (DN): how well the zero of its three colours is known decides below what brightness
# its colour is shown as grey. The deep centred stack: 25. The panels taken under a clear sky (zero matched to the deep
# stack to 1 to 3 DN per colour): 60. The two panels taken through thin cloud (zero matched to 5 to 10 DN, and tilted): 300.
CP = dict(deep=25.0, p00=60.0, p10=60.0, stray1=60.0, p01=300.0, p11=300.0)


def background(k, shape, x0, y0):
    if k == 'deep': return None
    Y, X = np.mgrid[y0:y0 + shape[0], x0:x0 + shape[1]].astype(np.float32)
    cx, cy = BG['panel_centres_mosaic_px'][k]
    u = (X - np.float32(cx)) / 1000; v = (Y - np.float32(cy)) / 1000
    out = np.empty(shape + (3,), np.float32)
    for c, cn in enumerate('RGB'):
        t = BG[cn][MODEL]['parameters'][k]['terms']
        out[:, :, c] = t[0] + t[1] * u + t[2] * v
    return out


def combine(names, tag):
    num = np.zeros((Hm, Wm, 3), np.float32); den = np.zeros((Hm, Wm), np.float32); var = np.zeros((Hm, Wm), np.float32); cover = np.zeros((Hm, Wm), np.uint8); clean = np.zeros((Hm, Wm), bool)
    wnum = np.zeros((Hm, Wm), np.float32); deepw = np.zeros((Hm, Wm), np.float32); cpn = np.zeros((Hm, Wm), np.float32)
    for k in names:
        x0, y0, x1, y1 = R9[k]['bbox']
        rgb = np.load(W('grid/%s_rgb.npy' % k)); iv = np.load(W('grid/%s_invvar.npy' % k)); fe = np.load(W('grid/%s_feather.npy' % k)); q = np.load(W('grid/%s_q.npy' % k)); wh = np.load(W('grid/%s_white.npy' % k))
        ok = np.isfinite(rgb).all(2) & (iv > 0) & (fe > 0)
        bg = background(k, rgb.shape[:2], x0, y0)
        if bg is not None: rgb = rgb - bg
        w = np.where(ok, fe * iv * q, 0).astype(np.float32)
        if k != 'deep': w = w * (1 - 0.999 * np.clip(wh, 0, 1))
        num[y0:y1, x0:x1] += np.where(ok[:, :, None], rgb, 0) * w[:, :, None]
        den[y0:y1, x0:x1] += w
        var[y0:y1, x0:x1] += np.where(ok, w * w / np.maximum(iv, 1e-12), 0)
        wnum[y0:y1, x0:x1] += w * np.where(ok, wh, 0)
        cpn[y0:y1, x0:x1] += w * np.float32(CP.get(k, 300.0))
        cover[y0:y1, x0:x1] |= np.where(ok, BIT[k], 0).astype(np.uint8)
        clean[y0:y1, x0:x1] |= ok & (q > 0.99)
        if k == 'deep': deepw[y0:y1, x0:x1] = w
    has = den > 0
    mos = np.where(has[:, :, None], num / np.maximum(den, 1e-30)[:, :, None], np.nan).astype(np.float32)
    noise = np.where(has, np.sqrt(var) / np.maximum(den, 1e-30), 0).astype(np.float32)
    white = np.where(has, wnum / np.maximum(den, 1e-30), 0).astype(np.float32)
    cover[has & ~clean] |= 128
    # ---- the zero ----
    BS = 64; ny, nx = Hm // BS, Wm // BS
    G = mos[:ny * BS, :nx * BS, 1].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        frac = np.isfinite(G).mean(2); bm = np.nanmedian(G, axis=2)
    inside = cv2.erode(has.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (301, 301))).astype(bool)
    insb = inside[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).all((1, 3)) & (clean[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).mean((1, 3)) > 0.9)
    # only where the deep stack and the panels taken under a clear sky carry the weight: the two panels taken through thin
    # cloud have backgrounds known to 5 to 10 DN and tilted, and their far ends must not set the zero of everything
    cpm = np.where(has, cpn / np.maximum(den, 1e-30), 1e3)
    trusted = (cpm[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).max((1, 3)) < 80.0)
    # ... and only where at least TWO of those stacks see the sky: a panel's far end, which nothing else covers, carries
    # its background plane extrapolated and the flat's error of the sensor's corners
    ntr = np.zeros((Hm, Wm), np.uint8)
    for k in names:
        if CP.get(k, 300.0) < 80.0: ntr += (cover & BIT[k] > 0)
    trusted &= ntr[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).min((1, 3)) >= 2
    okb = (frac > 0.98) & insb & trusted
    sm = cv2.blur(np.where(okb, bm, 0).astype(np.float32), (3, 3)) / np.maximum(cv2.blur(okb.astype(np.float32), (3, 3)), 1e-6)
    full3 = cv2.blur(okb.astype(np.float32), (3, 3)) > 0.99
    cand = okb & full3
    thr = np.percentile(sm[cand], 2.0)
    dark = cand & (sm <= thr)
    zero = []
    for c in range(3):
        v = mos[:ny * BS, :nx * BS, c].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3)[dark]
        zero.append(float(clipped_stats(v.ravel()[::3])[0]))
    by, bx = np.nonzero(dark); X0, Y0 = grid['trapezium_pixel']; PS = grid['pixel_scale_arcsec']
    where = [dict(east_arcmin=float((X0 - (x + 0.5) * BS) * PS / 60), north_arcmin=float((Y0 - (y + 0.5) * BS) * PS / 60), green_dn=float(bm[y, x]), stacks=[k for k in names if cover[int((y + 0.5) * BS), int((x + 0.5) * BS)] & BIT[k]]) for y, x in zip(by, bx)]
    # the darkest part of the deep centred stack alone, in the same units, for comparison
    x0, y0, x1, y1 = R9['deep']['bbox']; dm = np.load(W('grid/deep_rgb.npy')); dfe = np.load(W('grid/deep_feather.npy'))
    gy, gx = (y1 - y0) // BS, (x1 - x0) // BS
    with np.errstate(all='ignore'):
        dG = np.nanmedian(np.where((dfe > 0.99), dm[:, :, 1], np.nan)[:gy * BS, :gx * BS].reshape(gy, BS, gx, BS).transpose(0, 2, 1, 3).reshape(gy, gx, -1), axis=2)
    okd = np.isfinite(dG); smd = cv2.blur(np.where(okd, dG, 0).astype(np.float32), (3, 3)) / np.maximum(cv2.blur(okd.astype(np.float32), (3, 3)), 1e-6)
    fulld = cv2.blur(okd.astype(np.float32), (3, 3)) > 0.99
    thd = np.percentile(smd[fulld], 2.0); dkd = fulld & (smd <= thd)
    zd = []
    for c in range(3):
        v = dm[:gy * BS, :gx * BS, c].reshape(gy, BS, gx, BS).transpose(0, 2, 1, 3)[dkd]; zd.append(float(clipped_stats(v.ravel()[::3])[0]))
    yy, xx = np.nonzero(dkd)
    where_d = [dict(east_arcmin=float((X0 - (x0 + (x + 0.5) * BS)) * PS / 60), north_arcmin=float((Y0 - (y0 + (y + 0.5) * BS)) * PS / 60)) for y, x in zip(yy, xx)]
    mos -= np.array(zero, np.float32)
    np.save(W('%s_rgb.npy' % tag), mos); np.save(W('%s_noise.npy' % tag), noise); np.save(W('%s_cover.npy' % tag), cover); np.save(W('%s_white.npy' % tag), white)
    np.save(W('%s_cp.npy' % tag), np.where(has, cpn / np.maximum(den, 1e-30), 0).astype(np.float32))
    np.save(W('%s_share.npy' % tag), (np.where(has, deepw / np.maximum(den, 1e-30), 0) * 255 + 0.5).astype(np.uint8))
    area = float(has.sum() * PS * PS / 3600)
    out = dict(stacks=names, bits=BIT, background_model=MODEL, colour_pedestal_dn=CP, zero_taken_off_dn=dict(zip('RGB', zero)), zero_region=dict(blocks=int(dark.sum()), block_px=BS, percentile=2.0, smoothed_green_threshold_dn=float(thr), where=where),
               darkest_part_of_the_centred_stack_alone=dict(levels_dn=dict(zip('RGB', zd)), above_the_mosaic_zero_dn=dict(zip('RGB', [a - b for a, b in zip(zd, zero)])), blocks=int(dkd.sum()), where=where_d),
               area_with_data_sq_arcmin=area, area_with_data_sq_deg=area / 3600,
               noise_green_dn_per_pixel=dict(median=float(np.median(noise[has])), p05=float(np.percentile(noise[has][::11], 5)), p95=float(np.percentile(noise[has][::11], 95))),
               pixels_relying_on_second_combine_only=int((cover & 128 > 0).sum()), pixels_with_data=int(has.sum()))
    json.dump(out, open(W('s13_%s.json' % tag), 'w'), indent=1)
    print('%s: stacks %s: data over %.0f sq arcmin (%.2f sq deg); zero R %.1f G %.1f B %.1f DN from %d blocks, e.g. %s' % (tag, names, area, area / 3600, *zero, int(dark.sum()), [(round(w_['east_arcmin'], 1), round(w_['north_arcmin'], 1), w_['stacks']) for w_ in where[:6]]))
    print('   darkest part of the centred stack alone: R %.1f G %.1f B %.1f = %+.1f %+.1f %+.1f above the mosaic zero; at %s' % (*zd, *[a - b for a, b in zip(zd, zero)], [(round(w_['east_arcmin'], 1), round(w_['north_arcmin'], 1)) for w_ in where_d[:6]]))
    print('   green noise median %.1f DN (5%% %.1f, 95%% %.1f)' % (out['noise_green_dn_per_pixel']['median'], out['noise_green_dn_per_pixel']['p05'], out['noise_green_dn_per_pixel']['p95']), flush=True)


if __name__ == '__main__':
    combine(IMAGES, 'mosaic')
