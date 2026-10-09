"""Step 7: put every used frame's four colour planes onto the reference frame's grid of colour cells and combine.

Output pixel (X, Y) is the centre of the reference frame's 2 x 2 colour cell (sensor 2X + 0.5, 2Y + 0.5): one picture
pixel per colour cell, 0.77 arcsec, nothing enlarged. For each frame and plane: where the cell centre falls in that frame
(the step 3 polynomial), then in that plane (its own place in the cell), read with Lanczos-4 (OpenCV remap) straight from
the half-size plane; multiplied by 1 / transparency (step 6); minus ONE constant per colour per frame: the 3-sigma
clipped mean of that frame in a ring of sky around the nebula (SKY_R0 to SKY_R1 cells from its centre, stars masked).
No surface is fitted anywhere: whatever gradient the sky has across the field stays in the stack (step 10 takes a plane
off around the nebula), and the constant is measured where the picture is. The nebula's centre comes from the plate
solve of the reference frame (step 4); the ring starts 3.2 arcmin out, well clear of the ~1 arcmin radius shell.

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD across the
frames, floor 0.4 x the single-frame noise, widened by each frame's own noise factor), then again 3 sigma about the
weighted mean of the survivors, then the weighted mean (weights from step 6).
Red and blue are then resampled once more with their measured offset against green (air dispersion, about 0.2 px)
taken out of the transform: the first pass only measures it. Also kept: the count of frames used per pixel, the coverage, the odd and even frames combined alone (their
half-difference is the stack's noise with the sky cancelled; their agreement says what is real), and the reference frame
alone on the same grid (the single-frame comparison). Copied from this night's m57/step6_stack.py (adapted there from 2026-10-03/m31/step8_stack.py); only the ring, the
nebula's position (from step 4) and the file names changed."""
import os, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

KAPPA = 3.0
SKY_R0, SKY_R1 = 250, 700        # cells (3.2 to 9.0 arcmin from the nebula's centre); NGC 1514's shell is ~1 arcmin in radius
sel = jload('step6_select.json'); USE = sel['used']
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
ref_stars = [r for r in jload('step2_stars.json') if r['stamp'] == REF][0]['stars']
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = np.array([u['scale'] for u in USE], np.float32)
noise0 = sel['noise_clear_median_dn']
UC = np.array([3012.0, 2012.0]); US = 3000.0
gy, gx = np.mgrid[0:h2, 0:w2].astype(np.float64)
sx, sy = 2 * gx + 0.5, 2 * gy + 0.5                       # sensor position of each output cell centre (reference frame)
u, v = (sx - UC[0]) / US, (sy - UC[1]) / US
TERMS = [np.ones_like(u), u, v, u * u, u * v, v * v]
del gx, gy, sx, sy, u, v

# sky ring around the nebula, stars masked (reference star list; radius grows with brightness)
NEB = jload('step4_solve_ref.json')['target_sensor_px']
nx, ny = (NEB[0] - 0.5) / 2, (NEB[1] - 0.5) / 2
yy, xx = np.mgrid[0:h2, 0:w2]
rr = np.hypot(xx - nx, yy - ny)
SKY = (rr >= SKY_R0) & (rr < SKY_R1)
starmask = np.zeros((h2, w2), np.uint8)
for s in ref_stars:
    rad = int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4)))
    cv2.circle(starmask, (int(round(s['x'])), int(round(s['y']))), rad, 1, -1)
SKY &= starmask == 0
del yy, xx, rr


DISP = {}                         # plane -> (dx, dy) in output px: a colour's offset against green (air dispersion), set in __main__ after a first pass


def terms_for(p):
    if p not in DISP: return TERMS
    dx, dy = DISP[p]
    u, v = TERMS[1] + 2 * dx / US, TERMS[2] + 2 * dy / US
    return [TERMS[0], u, v, u * u, u * v, v * v]


def maps(stamp, p):
    o = tr[stamp]; cx = np.array(o['cx']); cy = np.array(o['cy']); T = terms_for(p)
    fx = sum(c * t for c, t in zip(cx, T)); fy = sum(c * t for c, t in zip(cy, T))
    ox, oy = OFFS[p]
    return ((fx - ox) / 2).astype(np.float32), ((fy - oy) / 2).astype(np.float32)


def warp(i, p):
    s = stamps[i]
    P = np.ascontiguousarray(np.load(os.path.join(WORK, 'planes', s + '.npy'), mmap_mode='r')[p])
    mx, my = maps(s, p)
    out = cv2.remap(P, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    out *= scale[i]
    ok = SKY & np.isfinite(out)
    c = clipped_stats(out[ok])[0]
    out -= np.float32(c)
    return out, c, int(ok.sum())


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
        out = dict(mean=np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32), used=keep.sum(0).astype(np.uint8))
        for name, idx in subs.items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


order = np.arange(N); SUB = dict(odd=order[1::2], even=order[0::2])
iref = stamps.index(REF)


def stack_plane(p):
    """Resample and combine one colour plane. Returns the stores, the reference frame alone, coverage, constants, numbers."""
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex: res = list(ex.map(lambda i: warp(i, p), range(N)))
    cube = np.stack([r[0] for r in res]); const = [r[1] for r in res]; del res
    geo = np.isfinite(cube); cov = geo.sum(0).astype(np.uint8); single = cube[iref].copy()
    floor = np.float32(0.4 * noise0)
    out = {k: np.zeros((h2, w2), np.uint8 if k == 'used' else np.float32) for k in ('mean', 'used', 'odd', 'even')}
    rows = [(a, min(a + 64, h2)) for a in range(0, h2, 64)]
    def work(ab):
        a, b = ab
        return ab, combine(cube[:, a:b], geo[:, a:b], floor, SUB)
    with ThreadPoolExecutor(WORKERS) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): out[k][a:b] = v
    seen = int(geo.sum()); usedn = int(out['used'].sum())
    info = dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=(seen - usedn) / seen,
                offset_against_green_px=list(DISP.get(p, (0.0, 0.0))))
    print(PLANE_NAMES[p], info, 'constants', np.round(const, 1).tolist(), '%.0fs' % (time.time() - t0), flush=True)
    return out, single, cov, const, info


if __name__ == '__main__':
    names = ['mean', 'used', 'odd', 'even']
    store = {k: np.zeros((4, h2, w2), np.uint8 if k == 'used' else np.float32) for k in names}
    single = np.zeros((4, h2, w2), np.float32); cover = np.zeros((h2, w2), np.uint8)
    CONST = np.zeros((N, 4)); info = []
    print('frames', N, 'sky ring pixels', int(SKY.sum()), flush=True)
    for p in range(4):
        out, single[p], cov, CONST[:, p], inf = stack_plane(p)
        for k in names: store[k][p] = out[k]
        if p == 1: cover[:] = cov
        info.append(inf)
    # air dispersion: the red and blue images sit a fraction of a pixel from the green one along the vertical (low in
    # the sky the air is a prism). Measured on the bright unclipped stars of this first pass; R and B are then resampled
    # again from the frames with that offset taken out (the transform is shifted by it; nothing is resampled twice).
    def colour_offsets(planes):
        from step2_stars import measure
        Gp = (planes[1] + planes[2]) / 2; rows = []
        for s_ in ref_stars:
            if s_['saturated'] or s_['flux'] < 20000: continue
            g = measure(Gp, s_['x'], s_['y']); r = measure(planes[0], s_['x'], s_['y']); b = measure(planes[3], s_['x'], s_['y'])
            if g and r and b: rows.append((r['x'] - g['x'], r['y'] - g['y'], b['x'] - g['x'], b['y'] - g['y']))
        a = np.array(rows)
        return dict(stars=len(a), red_minus_green_px=np.median(a[:, :2], 0).tolist(), blue_minus_green_px=np.median(a[:, 2:], 0).tolist(),
                    scatter_px=(1.4826 * np.median(np.abs(a - np.median(a, 0)), 0)).tolist())
    before = colour_offsets(store['mean'])
    print('colour offsets, first pass:', before, flush=True)
    DISP[0] = tuple(before['red_minus_green_px']); DISP[3] = tuple(before['blue_minus_green_px'])
    for p in (0, 3):
        out, single[p], cov, CONST[:, p], inf = stack_plane(p)
        for k in names: store[k][p] = out[k]
        info[p] = inf
    after = colour_offsets(store['mean'])
    print('colour offsets, after:', after, flush=True)
    for k, v in store.items(): np.save(W_('stack_%s.npy' % k), v)
    np.save(W_('single_planes.npy'), single); np.save(W_('cover.npy'), cover)
    jsave(dict(frames=stamps, reference=REF, kappa=KAPPA, grid='reference frame colour cells: output (X, Y) = sensor (2X + 0.5, 2Y + 0.5)',
               sky=dict(how='3-sigma clipped mean of the resampled, transparency-scaled frame in a ring around the nebula, stars masked; one constant per colour per frame',
                        ring_cells=[SKY_R0, SKY_R1], ring_centre_sensor_px=list(NEB), pixels=int(SKY.sum())),
               constants_dn={s: dict(zip(PLANE_NAMES, [round(float(c), 3) for c in CONST[i]])) for i, s in enumerate(stamps)},
               weights={s: float(wts[i]) for i, s in enumerate(stamps)}, scales={s: float(scale[i]) for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info, colour_offsets=dict(first_pass=before, applied_px={PLANE_NAMES[k]: list(v) for k, v in DISP.items()}, after=after), frames_covering_every_pixel=int(cover.min()), full_coverage_fraction=float((cover == N).mean())), 'step7.json')
