"""Step 8: every used frame's four colour planes onto the canvas (step 7) and combined.

Per frame and plane: read from the RAW in place (black-subtracted, hot pixels repaired on the fly; nothing cached)
/ that night's flat (step 7: the 13 October hybrid flat times that night's own measured dust) x 1/transparency ->
resampled onto the canvas (rotation + shift + the plane's own place in the 2 x 2 colour cell, Lanczos-4, no demosaic,
no enlargement: one output pixel per colour cell) -> minus ONE constant: the 3-sigma clipped mean over the FAINT
REGION. That is the only sky handling; no surface is fitted over the galaxy. The faint region: the area every used frame
covers, and of that the darker FAINT_PCT percent of the first green stack (16 px block medians, 5 x 5 median, Gaussian
32 px). M33 fills the field, so the stack's zero is the galaxy's faintest level in the area every frame saw, not the
true sky.

Combine (the template's control combine, step8_stack.combine of hack/stacks/2026-10-17/m27, the same arithmetic): per
pixel and plane, values further than 3 sigma from the median dropped (sigma = 1.4826 x MAD across the frames, floor 0.4 x
the single-frame noise, widened by each frame's own noise factor), again 3 sigma about the weighted mean of the
survivors, then the weighted mean (step 5 weights). With the same keep mask, the subsets alone: odd and even frames (the
half-stack test), tonight's frames alone and 13 October's alone (what 13 October added). The cube is held as float16
(relative step 0.05%, far below a frame's noise); all arithmetic is float32.

NOT done here, for the time limit, and said in the recipe: the proper coadd (tools/coadd.py; the skill measured +1 to
+4% point-source S/N from it on 15 s frames) and the air-dispersion shift (0.3 sensor px on M27 tonight)."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import canvas as CV

KAPPA = 3.0
FAINT_PCT = float(os.environ.get('M33_FAINT_PCT', '30'))
INSET = 16
sel = jload('step5_select.json'); USE = sel['used']
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
night = {u['stamp']: u['night'] for u in USE}
iref = stamps.index(REF_STAMP)
X0, Y0, HC, WC = CV.load()
FL = {n: np.load(W('flat_%s.npy' % n)) for n in set(night.values())}


def warp(s, p):
    P = load_clean_plane(path_of(s), p) / FL[night[s]][p] * np.float32(scale[s])
    mx, my = CV.maps(np.array(tr[s]['R']), np.array(tr[s]['t']), X0, Y0, HC, WC, ox=OFFS[p][0], oy=OFFS[p][1])
    v = (mx >= INSET / 2) & (mx <= w2 - 1 - INSET / 2) & (my >= INSET / 2) & (my <= h2 - 1 - INSET / 2)
    o = cv2.remap(P, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    o[~v] = np.nan
    return o


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
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint16))
        for name, idx in subs.items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


if __name__ == '__main__':
    t00 = time.time()
    cover = np.load(W('pass1_cover.npy')); allcov = cover == N
    T1 = np.load(W('pass1_green.npy'))
    Gs = cv2.GaussianBlur(smooth_level(np.nan_to_num(T1, nan=float(np.nanmedian(T1))), 16, 5), (0, 0), 32)
    thr = np.percentile(Gs[allcov], FAINT_PCT); faint = allcov & (Gs <= thr)
    np.save(W('faint_region.npy'), faint); ys, xs = np.nonzero(faint)
    samp = (ys[::5], xs[::5])
    print('canvas %d x %d; area every frame covers %.1f%%; faint region %d px (darkest %.0f%% of it); %d frames' % (WC, HC, 100 * allcov.mean(), faint.sum(), FAINT_PCT, N), flush=True)
    order = np.arange(N)
    SUB = dict(odd=order[1::2], even=order[0::2], tonight=np.array([i for i, s in enumerate(stamps) if night[s] == '18oct']), oct13=np.array([i for i, s in enumerate(stamps) if night[s] == '13oct']))
    SUB = {k: v for k, v in SUB.items() if len(v)}
    res = {k: np.zeros((4, HC, WC), np.float32) for k in ['mean'] + list(SUB)}
    used = np.zeros((4, HC, WC), np.uint16); single = np.zeros((4, HC, WC), np.float32)
    CONST = np.zeros((N, 4)); info = []
    for p in range(4):
        t0 = time.time()
        cube = np.empty((N, HC, WC), np.float16)
        def put(i):
            a = warp(stamps[i], p)
            m, sd, _ = clipped_stats(a[samp]); CONST[i, p] = m
            cube[i] = (a - np.float32(m)).astype(np.float16)
            return sd
        with ThreadPoolExecutor(WORKERS) as ex:
            fs = np.array(list(ex.map(put, range(N))))
        single[p] = cube[iref].astype(np.float32)
        floor = np.float32(0.4 * np.median(fs))
        rows = [(a, min(a + 48, HC)) for a in range(0, HC, 48)]
        def work(ab):
            a, b = ab
            c = cube[:, a:b].astype(np.float32); g = np.isfinite(c)
            return ab, combine(c, g, floor, SUB)
        with ThreadPoolExecutor(WORKERS) as ex:
            for (a, b), o in ex.map(work, rows):
                for k in res: res[k][p, a:b] = o[k]
                used[p, a:b] = o['used']
        del cube
        info.append(dict(plane=PLANE_NAMES[p], frame_noise_in_faint_region_median=float(np.median(fs)), sigma_floor=float(floor), constants_range=[float(CONST[:, p].min()), float(CONST[:, p].max())]))
        print('%s: constants %.1f..%.1f DN, frame noise in the faint region %.1f DN (median); %.0fs' % (PLANE_NAMES[p], CONST[:, p].min(), CONST[:, p].max(), np.median(fs), time.time() - t0), flush=True)
    for k, v in res.items(): np.save(W('stack_%s.npy' % k), v)
    np.save(W('stack_used.npy'), used); np.save(W('stack_single.npy'), single); np.save(W('stack_cover.npy'), cover)
    noise = {k: [clipped_stats(res[k][p][faint])[1] for p in range(4)] for k in res}
    noise['single'] = [clipped_stats(single[p][faint & np.isfinite(single[p])])[1] for p in range(4)]
    noise['half_difference'] = [clipped_stats(((res['odd'][p] - res['even'][p]) / 2)[faint])[1] for p in range(4)]
    for k, v in noise.items(): print('noise in the faint region, %-15s %s DN' % (k, ' '.join('%s %.2f' % (PLANE_NAMES[p], v[p]) for p in range(4))))
    jdump(dict(frames=stamps, reference=REF_STAMP, kappa=KAPPA, canvas=dict(X0=X0, Y0=Y0, HC=HC, WC=WC), combine='3-sigma clipped weighted mean (the template control combine), float16 cube, float32 arithmetic',
               faint_region=dict(percentile=FAINT_PCT, pixels=int(faint.sum()), smoothed_green_max=float(thr), what='area every frame covers, darkest part of the first green stack'),
               constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info, noise_faint_region_dn=noise,
               not_done=['proper coadd (tools/coadd.py)', 'air-dispersion shift']), 'step8_stack.json')
    print('%.0f s' % (time.time() - t00))
