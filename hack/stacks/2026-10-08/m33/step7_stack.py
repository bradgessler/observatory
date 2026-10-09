"""Step 7: put every used frame's four colour planes onto the reference frame's grid of colour cells and combine.

Per frame and plane: (black-subtracted, hot pixels repaired) / flat (step 6)  x 1/transparency  ->  resampled onto the
reference cell grid (rotation + shift + the plane's own place in the 2 x 2 colour cell, Lanczos-4, no demosaic, no
enlargement: one output pixel per colour cell)  ->  minus ONE constant: the 3-sigma clipped mean of that resampled
plane over the FAINT REGION. That is the only sky handling. No surface is fitted: the galaxy fills the frame.

The faint region: on the reference frame (flat-fielded green, smoothed: 16 px block medians, 5 x 5 median of those,
Gaussian sigma 2 blocks), the darkest FAINT_PCT percent of the area that every used frame covers (inset 16 px).
The same sky pixels for every frame and every colour, so after the subtraction that region is zero and neutral in
every frame. It is not empty sky: M33's own light is there too, so the stack's zero sits at the galaxy's faintest
level in this field, not at the true sky. Step 9 says how big that offset may be.

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD across the
frames, floor 0.4 x the single-frame noise, widened by each frame's own noise factor), then again 3 sigma about the
weighted mean of the survivors, then the weighted mean (weights from step 5). As hack/stacks/2026-10-03/m31/step8_stack.py.
Also kept: the count of frames used per pixel, the count covering each pixel, the odd and the even frames combined alone
(their half-difference is the stack's noise; their agreement says what is real), and the reference frame alone through
the same steps (the single-frame comparison)."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

KAPPA = 3.0
FAINT_PCT = float(os.environ.get('M33_FAINT_PCT', '5'))
INSET = 16
sel = jload('step5_select.json'); USE = sel['used']
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
iref = stamps.index(REF_STAMP)
FLAT = np.load(W('flat.npy'))
Yc, Xc = np.mgrid[0:h2, 0:w2].astype(np.float32)
SX, SY = 2 * Xc + 0.5, 2 * Yc + 0.5            # sensor position of each output cell centre (reference frame)


def prep(stamp, p):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p])
    P /= FLAT
    P *= np.float32(scale[stamp])
    return P


def maps(stamp, p):
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64); ox, oy = OFFS[p]
    fx = (R[0, 0] * SX + R[0, 1] * SY + t[0]).astype(np.float32); fy = (R[1, 0] * SX + R[1, 1] * SY + t[1]).astype(np.float32)
    return (fx - ox) / 2, (fy - oy) / 2


def warp(stamp, p):
    mx, my = maps(stamp, p)
    return cv2.remap(prep(stamp, p), mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))


def take(s, k): return np.take_along_axis(s, k[None], 0)[0]


def combine(c, valid, floor, subs):
    f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        lo = np.clip((n - 1) // 2, 0, N - 1); hi = np.clip(n // 2, 0, N - 1)
        s = np.sort(cv_, axis=0); med = 0.5 * (take(s, lo) + take(s, hi)); del s
        dev = np.abs(cv_ - med); sd = np.sort(dev, axis=0); mad = 0.5 * (take(sd, lo) + take(sd, hi)); del sd
        sig = np.maximum(1.4826 * mad, floor)
        keep = valid & (dev <= KAPPA * sig * f); del dev
        c0 = np.where(valid, c, 0)
        ws = (w * keep).sum(0); m1 = (w * keep * c0).sum(0) / np.maximum(ws, 1e-9)
        r = np.where(keep, (c0 - m1) / f, 0); nk = keep.sum(0)
        sd1 = np.maximum(np.sqrt((r ** 2).sum(0) / np.maximum(nk - 1, 1)), floor); del r
        keep = valid & (np.abs(c0 - m1) <= KAPPA * sd1 * f)
        ws = (w * keep).sum(0)
        mean = np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32)
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint8))
        for name, idx in (subs or {}).items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


if __name__ == '__main__':
    # ---- where every used frame has data (inset), on the reference grid ----
    common = np.ones((h2, w2), bool)
    for s in stamps:
        mx, my = maps(s, 0)
        common &= (mx >= INSET) & (mx <= w2 - 1 - INSET) & (my >= INSET) & (my <= h2 - 1 - INSET)
    # ---- the faint region, from the reference frame ----
    G = (prep(REF_STAMP, 1) + prep(REF_STAMP, 2)) / 2
    Gs = smooth_level(G, 16, 5); Gs = cv2.GaussianBlur(Gs, (0, 0), 32)
    thr = np.percentile(Gs[common], FAINT_PCT)
    faint = common & (Gs <= thr)
    del G
    np.save(W('faint_region.npy'), faint)
    ys, xs = np.nonzero(faint)
    print('common area %.1f%% of the grid; faint region %.1f%% of it (%d px), smoothed green there %.1f..%.1f DN, centroid (%d, %d), box x %d..%d y %d..%d' % (100 * common.mean(), 100 * faint.sum() / common.sum(), faint.sum(), Gs[faint].min(), thr, xs.mean(), ys.mean(), xs.min(), xs.max(), ys.min(), ys.max()), flush=True)
    cv2.imwrite(W('v_faint_region.png'), cv2.resize((faint * 200 + common * 55).astype(np.uint8), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA))
    order = np.arange(N)
    SUB = dict(odd=order[1::2], even=order[0::2])
    names = ['mean', 'used'] + list(SUB)
    store = {k: np.zeros((4, h2, w2), np.uint8 if k == 'used' else np.float32) for k in names}
    single = np.zeros((4, h2, w2), np.float32); cover = np.zeros((h2, w2), np.uint8)
    CONST = np.zeros((N, 4)); CONST_ERR = np.zeros((N, 4)); info = []
    for p in range(4):
        t0 = time.time()
        with ThreadPoolExecutor(WORKERS) as ex:
            cube = np.stack(list(ex.map(lambda s: warp(s, p), stamps)))
        for i in range(N):
            m, sd, _ = clipped_stats(cube[i][faint])
            CONST[i, p] = m; CONST_ERR[i, p] = sd / np.sqrt(faint.sum())
            cube[i] -= np.float32(m)
        geo = np.isfinite(cube)
        if p == 1: cover[:] = geo.sum(0)
        single[p] = cube[iref]
        fs = np.array([clipped_stats(cube[i][faint][::7])[1] for i in range(N)])
        floor = np.float32(0.4 * np.median(fs))
        rows = [(a, min(a + 64, h2)) for a in range(0, h2, 64)]
        def work(ab):
            a, b = ab
            return ab, combine(cube[:, a:b], geo[:, a:b], floor, SUB)
        with ThreadPoolExecutor(WORKERS) as ex:
            for (a, b), o in ex.map(work, rows):
                for k, v in o.items(): store[k][p, a:b] = v
        seen = int(geo.sum()); usedn = int(store['used'][p].sum())
        info.append(dict(plane=PLANE_NAMES[p], frame_noise_in_faint_region=fs.tolist(), sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=float((seen - usedn) / seen)))
        print(PLANE_NAMES[p], 'constants (DN) %.2f..%.2f, median %.2f; frame noise in the faint region %.1f; dropped by the clip %.3f%%; %.0fs' % (CONST[:, p].min(), CONST[:, p].max(), np.median(CONST[:, p]), np.median(fs), 100 * info[-1]['dropped_fraction'], time.time() - t0), flush=True)
        del cube, geo
    for k, v in store.items(): np.save(W('stack_%s.npy' % k), v)
    np.save(W('stack_single.npy'), single); np.save(W('stack_cover.npy'), cover); np.save(W('common_area.npy'), common)
    for i, s in enumerate(stamps): print(s, 'constants R G1 G2 B', np.round(CONST[i], 2).tolist())
    jdump(dict(frames=stamps, reference=REF_STAMP, kappa=KAPPA, faint_region=dict(percentile=FAINT_PCT, pixels=int(faint.sum()), smoothed_green_max_dn=float(thr), centroid_xy=[float(xs.mean()), float(ys.mean())], box=[int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())]),
               constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, constants_statistical_error={s: CONST_ERR[i].tolist() for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info), 'step7_stack.json')
