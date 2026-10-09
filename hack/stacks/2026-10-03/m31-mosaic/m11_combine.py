"""Mosaic step 11: combine. Per pixel and colour:

    mosaic = sum_k W_k (image_k - background_k) / sum_k W_k,   W_k = feather_k x inverse variance_k x quality_k

image_k in the core's units (step 9), background_k = the panel's fitted background of step 10 (model C: constant
and plane, for panel (1,1) also the three second-order terms; zero for the core), the same W for the three colours. Where the deep core stack covers the sky it carries 85 to 99% of the
weight by its lower noise alone; toward its edge its feather hands over to the panels.
A pixel no image covers stays without data (weight 0); nothing is filled in.

Then ONE number is taken off the whole mosaic, the same for the three colours, so that its darkest well-covered
part sits at zero in green: the 3-sigma clipped mean of green over the 64 px blocks whose smoothed green is in
the lowest 2% (blocks fully covered, clean, at least 150 px inside the footprint). The same number for R, G and B,
so that the core stack's own colour zero is kept: the panels were matched to the core colour by colour, and what
red and blue do in that darkest region (recorded) is within the core's own uncertainty of a few DN, not something
to re-zero a picture by. With the panels matched to it, the core's zero turns out to BE the darkest part of the
whole mosaic to within about 1 DN (it lies 20 arcmin out along the minor axis). It is still NOT a measured sky.

Written (working grid, 0.776 arcsec/px): <set>_rgb.npy, <set>_noise.npy (expected 1-sigma of green in one pixel,
from the weights; 0 = no data), <set>_cover.npy (bit mask of the images that contribute: 1 core, 2 p00, 4 p10,
8 p20, 16 p21, 32 p11, 64 p01; 128 = every contributing sample came from the dust-divided combine),
<set>_coreshare.npy (the core stack's share of the weight, 0..255)."""
import json, sys, warnings
warnings.filterwarnings('ignore', message='All-NaN slice encountered')
import numpy as np, cv2
from mcommon import *

PL = json.load(open(W('m8_place.json'))); R9 = json.load(open(W('m9_resample.json'))); BG = json.load(open(W('m10_background.json'))); grid = PL['grid']
Hm, Wm = grid['height'], grid['width']
BIT = dict(core=1, p00=2, p10=4, p20=8, p21=16, p11=32, p01=64)
SETS = dict(six=['core', 'p00', 'p10', 'p20', 'p21', 'p11', 'p01'], centre=['core', 'p10', 'p11'], panels_only=['p00', 'p10', 'p20', 'p21', 'p11', 'p01'])


MODEL = 'C_planes_and_second_order_for_p11'


def background(k, shape, x0, y0, model=None):
    """The fitted background of panel k on a patch of the mosaic grid (step 10): t0 + t1 u + t2 v [+ t3 u^2 + t4 u v + t5 v^2]."""
    if k == 'core': return None
    Y, X = np.mgrid[y0:y0 + shape[0], x0:x0 + shape[1]].astype(np.float32)
    cx, cy = BG['panel_centres_mosaic_px'][k]
    u = (X - np.float32(cx)) / 1000; v = (Y - np.float32(cy)) / 1000
    out = np.empty(shape + (3,), np.float32)
    for c, cn in enumerate('RGB'):
        t = BG[cn][model or MODEL]['parameters'][k]['terms']
        s = t[0] + t[1] * u + t[2] * v
        if len(t) == 6: s = s + t[3] * u * u + t[4] * u * v + t[5] * v * v
        out[:, :, c] = s
    return out


def combine(name):
    num = np.zeros((Hm, Wm, 3), np.float32); den = np.zeros((Hm, Wm), np.float32); var = np.zeros((Hm, Wm), np.float32); cover = np.zeros((Hm, Wm), np.uint8); clean = np.zeros((Hm, Wm), bool)
    share = {}
    for k in SETS[name]:
        x0, y0, x1, y1 = R9[k]['bbox']
        rgb = np.load(W('grid/%s_rgb.npy' % k)); iv = np.load(W('grid/%s_invvar.npy' % k)); fe = np.load(W('grid/%s_feather.npy' % k)); q = np.load(W('grid/%s_q.npy' % k))
        ok = np.isfinite(rgb).all(2) & (iv > 0) & (fe > 0)
        bg = background(k, rgb.shape[:2], x0, y0)
        if bg is not None: rgb = rgb - bg
        w = np.where(ok, fe * iv * q, 0).astype(np.float32)
        num[y0:y1, x0:x1] += np.where(ok[:, :, None], rgb, 0) * w[:, :, None]
        den[y0:y1, x0:x1] += w
        var[y0:y1, x0:x1] += np.where(ok, w * w / np.maximum(iv, 1e-12), 0)
        cover[y0:y1, x0:x1] |= np.where(ok, BIT[k], 0).astype(np.uint8)
        clean[y0:y1, x0:x1] |= ok & (q > 0.99)
        share[k] = (slice(y0, y1), slice(x0, x1), w)
    has = den > 0
    mos = np.where(has[:, :, None], num / np.maximum(den, 1e-30)[:, :, None], np.nan).astype(np.float32)
    noise = np.where(has, np.sqrt(var) / np.maximum(den, 1e-30), 0).astype(np.float32)
    cover[has & ~clean] |= 128
    # ---- the zero ----
    BS = 64; ny, nx = Hm // BS, Wm // BS
    G = mos[:ny * BS, :nx * BS, 1].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        frac = np.isfinite(G).mean(2); bm = np.nanmedian(G, axis=2)
    # blocks fully covered, clean, and at least 150 px inside the footprint (away from feathered edges)
    inside = cv2.erode(has.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (301, 301))).astype(bool)
    insb = inside[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).all((1, 3)) & (clean[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).mean((1, 3)) > 0.9)
    okb = (frac > 0.98) & insb
    sm = cv2.blur(np.where(okb, bm, 0).astype(np.float32), (3, 3)) / np.maximum(cv2.blur(okb.astype(np.float32), (3, 3)), 1e-6)
    full3 = cv2.blur(okb.astype(np.float32), (3, 3)) > 0.99
    cand = okb & full3
    thr = np.percentile(sm[cand], 2.0)
    dark = cand & (sm <= thr)
    zero = []
    for c in range(3):
        v = mos[:ny * BS, :nx * BS, c].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3)[dark]
        zero.append(float(clipped_stats(v.ravel()[::3])[0]))
    mos -= np.float32(zero[1])              # the green level of the darkest part, off all three colours alike
    by, bx = np.nonzero(dark); X0, Y0 = grid['nucleus_pixel']; PS = grid['pixel_scale_arcsec']
    where = [dict(east_arcmin=float((X0 - (x + 0.5) * BS) * PS / 60), north_arcmin=float((Y0 - (y + 0.5) * BS) * PS / 60), images=[k for k in SETS[name] if cover[int((y + 0.5) * BS), int((x + 0.5) * BS)] & BIT[k]]) for y, x in zip(by, bx)]
    np.save(W('%s_rgb.npy' % name), mos); np.save(W('%s_noise.npy' % name), noise); np.save(W('%s_cover.npy' % name), cover)
    cs = np.zeros((Hm, Wm), np.float32)
    if 'core' in share:
        ys, xs, w = share['core']; cs[ys, xs] = w / np.maximum(den[ys, xs], 1e-30)
    np.save(W('%s_coreshare.npy' % name), (cs * 255 + 0.5).astype(np.uint8))
    # how the weight is shared where the core is
    core_share = None
    if 'core' in share:
        ys, xs, w = share['core']; d = den[ys, xs]; m = w > 0
        fr = w[m] / d[m]; core_share = dict(median=float(np.median(fr)), p05=float(np.percentile(fr, 5)), pixels=int(m.sum()))
    area = float(has.sum() * PS * PS / 3600)
    out = dict(images=SETS[name], background_model=MODEL, zero_taken_off_all_colours_dn=zero[1], colours_in_the_zero_region_before_dn=dict(zip('RGB', zero)), zero_region=dict(blocks=int(dark.sum()), block_px=BS, percentile=2.0, smoothed_green_threshold_before_zero_dn=float(thr), where=where),
               area_with_data_sq_arcmin=area, area_with_data_sq_deg=area / 3600, core_share_of_weight_where_it_has_data=core_share,
               noise_green_dn_per_pixel=dict(median=float(np.median(noise[has])), p05=float(np.percentile(noise[has][::11], 5)), p95=float(np.percentile(noise[has][::11], 95))),
               pixels_relying_on_dust_divided_data_only=int((cover & 128 > 0).sum()), pixels_with_data=int(has.sum()))
    json.dump(out, open(W('m11_%s.json' % name), 'w'), indent=1)
    print('%-12s images %s: data over %.0f sq arcmin (%.2f sq deg); darkest region at R %.2f G %.2f B %.2f DN, green taken off all (%d blocks, e.g. at %s); core share of the weight where it has data: median %s; green noise median %.1f DN' % (
        name, SETS[name], area, area / 3600, *zero, int(dark.sum()), [(round(w_['east_arcmin'], 1), round(w_['north_arcmin'], 1), w_['images']) for w_ in where[:4]], None if core_share is None else round(core_share['median'], 3), out['noise_green_dn_per_pixel']['median']), flush=True)


if __name__ == '__main__':
    for nm in (sys.argv[1:] or ['six', 'centre']): combine(nm)
