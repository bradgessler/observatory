"""Step 8: put every used frame's four colour planes onto the reference frame's grid of colour cells and combine.

Per frame and plane: read from the RAW in place (black-subtracted, hot pixels repaired on the fly; nothing cached)
/ that colour's flat (step 7)  x 1/transparency  ->  resampled onto the reference cell grid (rotation + shift + the
plane's own place in the 2 x 2 colour cell, Lanczos-4, no demosaic, no enlargement: one output pixel per colour cell)
->  minus ONE constant: the 3-sigma clipped mean of that resampled plane over the SKY REGION. That is the only sky
handling. No surface is fitted.

Air dispersion (the nebula was 55 to 60 degrees up): red and blue star images sit a fraction of a pixel from green. Measured
before the stack on the frames themselves (every DISP_EVERY-th used frame: the windowed centroid of each bright,
unclipped, isolated star in the R, the B and the mean-green plane, each plane's own place in the colour cell allowed
for; the median over stars and frames, sensor px), then taken out in the one resampling: red and blue are sampled at
green's place plus their offset. Measured again on the stack afterwards (it should be near zero). The field turns by
0.4 degrees over the run, so one offset in the sensor's axes serves all frames. Hook M1_DISPERSION=0 leaves it in.

The sky region: the area that every used frame covers (inset 16 px), outside the nebula's generous ellipse (step 6:
4.5 x 3.6 arcmin semi-axes, 1.5 x the catalogue's size and a little more across), and of that the darker SKY_PCT percent of the reference
frame's flat-fielded, smoothed green (16 px block medians, 5 x 5 median of those, Gaussian sigma 32 px), which keeps it
off the glow around bright stars. The same sky pixels for every frame and every colour, so the sky there is zero and
neutral in every frame. It is real sky: the stack's zero is the sky's level.

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
import solvelib

KAPPA = 3.0
FAINT_PCT = float(os.environ.get('M1_SKY_PCT', '60'))
INSET = 16
sel = jload('step5_select.json'); USE = sel['used']
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
iref = stamps.index(REF_STAMP)
FLAT = np.load(W('flat.npy'))
PATHS = {f['stamp']: f['path'] for f in jload('step1.json')['frames']}
Yc, Xc = np.mgrid[0:h2, 0:w2].astype(np.float32)
SX, SY = 2 * Xc + 0.5, 2 * Yc + 0.5            # sensor position of each output cell centre (reference frame)


def prep(stamp, p):
    P = load_clean_plane(PATHS[stamp], p)
    P /= FLAT[p]
    P *= np.float32(scale[stamp])
    return P


DISP = {}                         # plane -> (dx, dy), sensor px: where that colour's star images sit against green (air dispersion)
DISP_EVERY = 3


def maps(stamp, p):
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64); ox, oy = OFFS[p]
    dx, dy = DISP.get(p, (0.0, 0.0))
    fx = (R[0, 0] * SX + R[0, 1] * SY + t[0] + dx).astype(np.float32); fy = (R[1, 0] * SX + R[1, 1] * SY + t[1] + dy).astype(np.float32)
    return (fx - ox) / 2, (fy - oy) / 2


def offsets_in_frame(stamp):
    """Red and blue centroids against green for the bright unclipped isolated stars of one frame, sensor px."""
    from step2_stars import measure, smooth_light
    P, _ = load_clean(PATHS[stamp]); rows = []
    D = [P[0] - smooth_light(P[0]), 0.5 * (P[1] + P[2]) - smooth_light(0.5 * (P[1] + P[2])), P[3] - smooth_light(P[3])]
    for s_ in s2[stamp]['stars']:
        if s_['saturated'] or s_['flux'] < 20000 or s_['nearest'] < 40 or s_['hfr'] > 4.0: continue
        r = measure(D[0], s_['x'], s_['y']); g = measure(D[1], s_['x'], s_['y']); b = measure(D[2], s_['x'], s_['y'])
        if r and g and b:                                  # plane px -> sensor px: R cell (0, 0), mean green (0.5, 0.5), B (1, 1)
            rows.append((2 * (r['x'] - g['x']) - 0.5, 2 * (r['y'] - g['y']) - 0.5, 2 * (b['x'] - g['x']) + 0.5, 2 * (b['y'] - g['y']) + 0.5))
    return rows


def offsets_in_stack(planes):
    """The same on stacked planes, which share one grid: output px x 2 = sensor px."""
    from step2_stars import measure, smooth_light
    D = [np.nan_to_num(planes[0]), np.nan_to_num(0.5 * (planes[1] + planes[2])), np.nan_to_num(planes[3])]; D = [d - smooth_light(d) for d in D]; rows = []
    for s_ in s2[REF_STAMP]['stars']:
        if s_['saturated'] or s_['flux'] < 20000 or s_['nearest'] < 40 or s_['hfr'] > 4.0: continue
        r = measure(D[0], s_['x'], s_['y']); g = measure(D[1], s_['x'], s_['y']); b = measure(D[2], s_['x'], s_['y'])
        if r and g and b: rows.append((2 * (r['x'] - g['x']), 2 * (r['y'] - g['y']), 2 * (b['x'] - g['x']), 2 * (b['y'] - g['y'])))
    return rows


def offsets_summary(rows):
    a = np.array(rows)
    return dict(measures=len(a), red_minus_green_sensor_px=np.median(a[:, :2], 0).round(4).tolist(), blue_minus_green_sensor_px=np.median(a[:, 2:], 0).round(4).tolist(),
                scatter_sensor_px=(1.4826 * np.median(np.abs(a - np.median(a, 0)), 0)).round(4).tolist(), error_of_the_median_sensor_px=(1.2533 * 1.4826 * np.median(np.abs(a - np.median(a, 0)), 0) / np.sqrt(len(a))).round(4).tolist())


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
    # ---- air dispersion, from the frames
    with ThreadPoolExecutor(WORKERS) as ex:
        rows = sum(ex.map(offsets_in_frame, stamps[::DISP_EVERY]), [])
    disp_before = offsets_summary(rows); disp_before['frames'] = stamps[::DISP_EVERY]
    print('colour offsets in the frames (sensor px): red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f), scatter %s, %d measures' % (*disp_before['red_minus_green_sensor_px'], *disp_before['blue_minus_green_sensor_px'], disp_before['scatter_sensor_px'], disp_before['measures']), flush=True)
    if os.environ.get('M1_DISPERSION', '1') == '1':
        DISP[0] = tuple(disp_before['red_minus_green_sensor_px']); DISP[3] = tuple(disp_before['blue_minus_green_sensor_px'])
    # ---- where every used frame has data (inset), on the reference grid ----
    common = np.ones((h2, w2), bool)
    for s in stamps:
        mx, my = maps(s, 0)
        common &= (mx >= INSET) & (mx <= w2 - 1 - INSET) & (my >= INSET) & (my <= h2 - 1 - INSET)
    # ---- the faint region, from the reference frame ----
    G = (prep(REF_STAMP, 1) + prep(REF_STAMP, 2)) / 2
    Gs = smooth_level(G, 16, 5); Gs = cv2.GaussianBlur(Gs, (0, 0), 32)
    ell = solvelib.ellipse_mask(jload('step6_solve_ref.json')['galaxy_ellipse'], (h2, w2))
    thr = np.percentile(Gs[common & ~ell], FAINT_PCT)
    faint = common & ~ell & (Gs <= thr)
    del G
    np.save(W('faint_region.npy'), faint)
    ys, xs = np.nonzero(faint)
    print('common area %.1f%% of the grid; sky region %.1f%% of it (%d px), smoothed green there %.1f..%.1f DN, centroid (%d, %d), box x %d..%d y %d..%d' % (100 * common.mean(), 100 * faint.sum() / common.sum(), faint.sum(), Gs[faint].min(), thr, xs.mean(), ys.mean(), xs.min(), xs.max(), ys.min(), ys.max()), flush=True)
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
        print(PLANE_NAMES[p], 'constants (DN) %.2f..%.2f, median %.2f; frame noise in the sky region %.1f; dropped by the clip %.3f%%; %.0fs' % (CONST[:, p].min(), CONST[:, p].max(), np.median(CONST[:, p]), np.median(fs), 100 * info[-1]['dropped_fraction'], time.time() - t0), flush=True)
        del cube, geo
    disp_after = offsets_summary(offsets_in_stack(store['mean']))
    print('colour offsets left in the stack (sensor px): red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f), %d stars' % (*disp_after['red_minus_green_sensor_px'], *disp_after['blue_minus_green_sensor_px'], disp_after['measures']), flush=True)
    for k, v in store.items(): np.save(W('stack_%s.npy' % k), v)
    np.save(W('stack_single.npy'), single); np.save(W('stack_cover.npy'), cover); np.save(W('common_area.npy'), common)
    for i, s in enumerate(stamps): print(s, 'constants R G1 G2 B', np.round(CONST[i], 2).tolist())
    jdump(dict(frames=stamps, reference=REF_STAMP, kappa=KAPPA, faint_region=dict(what='the sky region', percentile=FAINT_PCT, pixels=int(faint.sum()), smoothed_green_max_dn=float(thr), centroid_xy=[float(xs.mean()), float(ys.mean())], box=[int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())]),
               constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, constants_statistical_error={s: CONST_ERR[i].tolist() for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info,
               air_dispersion=dict(measured_in_the_frames=disp_before, taken_out_sensor_px={PLANE_NAMES[k]: list(v) for k, v in DISP.items()}, left_in_the_stack=disp_after,
                                   picture_px='1 picture px = 2 sensor px', how='red and blue sampled at green\'s place plus their offset, in the one Lanczos-4 resampling')), 'step8_stack.json')
