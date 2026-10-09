"""Step 6: put every used frame's four colour planes onto one output grid and combine them per pixel with a
weighted, sigma-clipped mean. Usage: step6_stack.py ref | north

  ref    the reference frame's colour-cell grid: output pixel (X, Y) is the centre of the reference frame's 2 x 2
         cell at sensor (2X + 0.5 + x0, 2Y + 0.5 + y0), 0.776 arcsec per pixel; the rectangle every used frame
         covers. This is the registered stack (m76-stack.tif) and what step 7 plate-solves.
  north  a rectangle round M76 at the same 0.776 arcsec per pixel, north up and east left, laid out from step 7's
         plate solution of the ref stack (step7_grid.json). Each frame is resampled straight onto it, so the
         picture's pixels are interpolated once, as registration needs, and never enlarged. Here the red and blue
         planes are also sampled where their stars sit (step 7 measures it: the air's slight prism).

Each plane of each frame is mapped with its own place in the RGGB cell (R at sensor (0, 0) of the cell, G1 (1, 0),
G2 (0, 1), B (1, 1)), so the colours line up without a demosaic. Resampling: OpenCV remap, Lanczos-4. Before
combining, each frame is divided by its transparency (step 5) so stars match; per pixel and plane, values more than
3 sigma from the median (sigma = 1.4826 x MAD, floor half the single-frame noise) are rejected, then 3 sigma about
the weighted mean of the survivors, then the weighted mean. The reference frame alone goes through the same
resampling (and the same transparency scaling) for comparison. Adapted from ../../2026-10-03/ngc7662/step5_stack.py."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

GRID = sys.argv[1] if len(sys.argv) > 1 else 'ref'
KAPPA = 3.0
EDGE = 10            # sensor px kept clear of every frame's edge (Lanczos-4 on the half-size planes reaches 8)
tr = {o['stamp']: o for o in json.load(open(W('step4_transforms.json')))}
q5 = json.load(open(W('step5_quality.json')))
USE = [l.strip() for l in open(W('use.txt')) if l.strip()]
HALF = os.environ.get('M76_HALF')          # a | b: every other used frame, for the "is it real?" test (step 8)
if HALF: USE = USE[0::2] if HALF == 'a' else USE[1::2]
WT = q5['weights']; TR = {o['stamp']: o['transparency'] for o in q5['quality']}


def common_rect():
    """The rectangle of the reference sensor grid, in whole 2 x 2 cells, that every used frame covers."""
    x0, y0, x1, y1 = 0, 0, Wd, H
    while True:
        moved = False
        for s in USE:
            R = np.array(tr[s]['R']); t = np.array(tr[s]['t'])
            for left, top in ((1, 1), (0, 1), (1, 0), (0, 0)):
                cx = x0 if left else x1 - 1; cy = y0 if top else y1 - 1
                px, py = R @ np.array([cx, cy], float) + t
                if px < EDGE or px > Wd - 1 - EDGE:
                    if left: x0 += 2
                    else: x1 -= 2
                    moved = True
                if py < EDGE or py > H - 1 - EDGE:
                    if top: y0 += 2
                    else: y1 -= 2
                    moved = True
        if not moved: return x0, y0, x1, y1


if GRID == 'ref':
    x0, y0, x1, y1 = common_rect()
    ww, hh = (x1 - x0) // 2, (y1 - y0) // 2
    # output (u, v) -> reference sensor (2u + 0.5 + x0, 2v + 0.5 + y0)
    A = np.array([[2.0, 0.0, 0.5 + x0], [0.0, 2.0, 0.5 + y0]])
    grid_info = dict(kind='reference frame colour-cell grid', reference=REF_STAMP, origin_sensor_xy=[x0, y0], size=[ww, hh], out_to_ref_sensor=A.tolist())
else:
    g = json.load(open(W('step7_grid.json')))
    A = np.array(g['out_to_ref_sensor']); ww, hh = g['size']
    grid_info = dict(g, kind='north up, east left, same scale')
    # red and blue sampled where their stars sit (step 7): R plane, G1, G2, B in reference sensor px
    COLOUR_SHIFT = [g['colour_offsets']['red_minus_green_ref_sensor_px'], [0, 0], [0, 0], g['colour_offsets']['blue_minus_green_ref_sensor_px']]
if GRID == 'ref':
    COLOUR_SHIFT = [[0, 0]] * 4
TAG = GRID + ('_' + HALF if HALF else '') + '_'
gy, gx = np.mgrid[0:hh, 0:ww].astype(np.float64)
sx = A[0, 0] * gx + A[0, 1] * gy + A[0, 2]; sy = A[1, 0] * gx + A[1, 1] * gy + A[1, 2]     # reference sensor coords


def warp(stamp, p):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p]) / np.float32(TR[stamp])
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64)
    ox, oy = OFFS[p]; dx, dy = COLOUR_SHIFT[p]
    mx = ((R[0, 0] * (sx + dx) + R[0, 1] * (sy + dy) + t[0]) - ox) / 2
    my = ((R[1, 0] * (sx + dx) + R[1, 1] * (sy + dy) + t[1]) - oy) / 2
    return cv2.remap(P, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))


def clip_chunk(c, wv, floor):
    """c: (n, rows, w) values, wv: (n,) weights."""
    with np.errstate(invalid='ignore'):
        med = np.nanmedian(c, axis=0)
        dev = np.abs(c - med)
        sig = np.maximum(1.4826 * np.nanmedian(dev, axis=0), floor)
        keep = dev <= KAPPA * sig
        W3 = wv[:, None, None] * keep
        m1 = (np.where(keep, c, 0) * W3).sum(0) / np.maximum(W3.sum(0), 1e-9)
        n1 = keep.sum(0)
        sd = np.sqrt(np.where(keep, (c - m1) ** 2, 0).sum(0) / np.maximum(n1 - 1, 1)); sd = np.maximum(sd, floor)
        keep = np.abs(c - m1) <= KAPPA * sd
        W3 = wv[:, None, None] * keep
        m2 = np.where(W3.sum(0) > 0, (np.where(keep, c, 0) * W3).sum(0) / np.maximum(W3.sum(0), 1e-9), np.nan)
        n2 = keep.sum(0)
        nv = (~np.isnan(c)).sum(0)
        plain = np.nanmean(c, 0)
    return m2.astype(np.float32), n2.astype(np.uint8), plain.astype(np.float32), med.astype(np.float32), nv.astype(np.uint8)


if __name__ == '__main__':
    n = len(USE); wv = np.array([WT[s] for s in USE], np.float32)
    print('grid', GRID, 'frames', n, 'size', ww, hh, flush=True)
    out = np.zeros((4, hh, ww), np.float32); cnt = np.zeros((4, hh, ww), np.uint8); plain = np.zeros_like(out); medn = np.zeros_like(out); single = np.zeros_like(out); seen = np.zeros((4, hh, ww), np.uint8)
    info = []
    # a patch of plain sky for the noise: ref grid, 1200 cells from the nebula; north grid, its corners
    for p in range(4):
        t0 = time.time()
        with ThreadPoolExecutor(8) as ex:
            cube = np.stack(list(ex.map(lambda s: warp(s, p), USE)))
        single[p] = warp(REF_STAMP, p) if not HALF else np.nan
        if GRID == 'ref':
            SKY = [(slice(150, 450), slice(150, 450))]
        else:
            SKY = [(slice(10, 160), slice(10, 160)), (slice(10, 160), slice(ww - 160, ww - 10)), (slice(hh - 160, hh - 10), slice(10, 160)), (slice(hh - 160, hh - 10), slice(ww - 160, ww - 10))]
        frame_sig = [float(np.median([clipped_stats(s[k])[1] for k in SKY])) for s in cube]
        floor = 0.5 * float(np.median(frame_sig))
        rows = [(a, min(a + 64, hh)) for a in range(0, hh, 64)]
        def work(ab):
            a, b = ab
            return ab, clip_chunk(cube[:, a:b], wv, floor)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), (m2, n2, pm, md, nv) in ex.map(work, rows):
                out[p, a:b] = m2; cnt[p, a:b] = n2; plain[p, a:b] = pm; medn[p, a:b] = md; seen[p, a:b] = nv
        rej = 1 - cnt[p].sum() / max(seen[p].sum(), 1)
        info.append(dict(plane=PLANE_NAMES[p], frame_sigma_on_grid=[round(v, 3) for v in frame_sig], sigma_floor=floor, rejected_fraction=float(rej),
                         min_frames_seen=int(seen[p].min()), min_frames_used=int(cnt[p].min()), pixels_with_fewer_than_all_frames=int((seen[p] < n).sum())))
        print(PLANE_NAMES[p], 'frame sigma %.1f' % np.median(frame_sig), 'rejected %.3f%%' % (100 * rej), 'min seen', seen[p].min(), 'min used', cnt[p].min(), 'px < all', int((seen[p] < n).sum()), '%.0fs' % (time.time() - t0), flush=True)
        del cube
    np.save(W(TAG + 'stack.npy'), out); np.save(W(TAG + 'count.npy'), cnt); np.save(W(TAG + 'seen.npy'), seen)
    np.save(W(TAG + 'plainmean.npy'), plain); np.save(W(TAG + 'median.npy'), medn); np.save(W(TAG + 'single.npy'), single)
    json.dump(dict(grid=grid_info, colour_shift_ref_sensor_px=dict(zip(PLANE_NAMES, COLOUR_SHIFT)), used=USE, weights={s: WT[s] for s in USE}, transparency_divisor={s: TR[s] for s in USE}, kappa=KAPPA, edge=EDGE, planes=info), open(W('step6_%s.json' % TAG[:-1]), 'w'), indent=1)
