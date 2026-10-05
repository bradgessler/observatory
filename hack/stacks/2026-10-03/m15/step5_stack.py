"""Step 5: put every used frame's four colour planes onto the reference frame's sensor grid (rotation + shift,
Lanczos-4 from the half-size plane straight to the sensor grid, no demosaic), then combine per pixel with a
sigma-clipped mean. Before resampling, the pixels under a dust shadow (step 4b, about 1% of the sensor, and the
one moving shadow placed where it was in that frame) are divided by the shadow's measured transmission, sky
included: (value + frame sky) / divisor - frame sky. The stacked area is
the rectangle every frame covers. Also keeps the plain mean, the median, the count of frames used per pixel,
and the reference frame alone on the same grid (same dust division, so the comparison shows only averaging)."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

KAPPA = 3.0
EDGE = 10            # sensor px kept clear of every frame's edge (Lanczos-4 on the half-size planes reaches 8)
H, Wd = 4024, 6024
tr = {o['stamp']: o for o in json.load(open(W('step3_transforms.json')))}
st1 = json.load(open(W('step1.json')))
USE = [l.strip() for l in open(W('use.txt')) if l.strip()]
NODUST = os.environ.get('M15_NODUST') == '1'
TAG = 'nodust_' if NODUST else ''
div = None if NODUST else np.load(W('dustdiv.npy'))
BARP = json.load(open(W('bar_places.json'))) if (not NODUST and os.path.exists(W('bar_places.json'))) else None
BART = np.load(W('bar_template.npy')) if BARP is not None else None
SKYDN = {f['stamp']: [b['clipped_mean'] for b in f['bg']] for f in st1['frames']}

def common_rect():
    """The rectangle of the reference grid that every used frame covers: a corner that lands outside a frame
    moves its own side in by 2 px, until all four corners of all frames are inside (corners are enough: the
    maps are affine and a frame is convex)."""
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

x0, y0, x1, y1 = common_rect()
gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)

def warp(stamp, p, masked=True):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p])
    if masked and not NODUST:
        sk = SKYDN[stamp][p]; d = div
        if BARP is not None:
            bx0, by0, bx1, by1 = BARP['window']; pl = BARP['places'][stamp]
            Mx = np.float32([[1, 0, pl['dx']], [0, 1, pl['dy']]])
            d = div.copy(); d[by0:by1, bx0:bx1] *= cv2.warpAffine(BART, Mx, (bx1 - bx0, by1 - by0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1.0)
        m = d < 1
        P[m] = (P[m] + sk) / d[m] - sk
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64)
    ox, oy = OFFS[p]
    mx = ((R[0, 0] * gx + R[0, 1] * gy + t[0]) - ox) / 2
    my = ((R[1, 0] * gx + R[1, 1] * gy + t[1]) - oy) / 2
    return cv2.remap(P, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))

def clip_chunk(c, floor):
    bad = np.isnan(c).any(0)
    with np.errstate(invalid='ignore'):
        med = np.median(c, axis=0)
        if bad.any(): med[bad] = np.nanmedian(c[:, bad], axis=0)
        dev = np.abs(c - med)
        mad = np.median(dev, axis=0)
        if bad.any(): mad[bad] = np.nanmedian(dev[:, bad], axis=0)
        sig = np.maximum(1.4826 * mad, floor)
        keep = dev <= KAPPA * sig                       # a NaN is never kept
        n1 = keep.sum(0); m1 = np.where(keep, c, 0).sum(0) / np.maximum(n1, 1)
        sd = np.sqrt(np.where(keep, (c - m1) ** 2, 0).sum(0) / np.maximum(n1 - 1, 1)); sd = np.maximum(sd, floor)
        keep = np.abs(c - m1) <= KAPPA * sd
        n2 = keep.sum(0); m2 = np.where(n2 > 0, np.where(keep, c, 0).sum(0) / np.maximum(n2, 1), np.nan)
        nv = (~np.isnan(c)).sum(0)
        plain = np.where(nv > 0, np.nansum(c, 0) / np.maximum(nv, 1), np.nan)
    return m2.astype(np.float32), n2.astype(np.uint8), plain.astype(np.float32), med.astype(np.float32), nv.astype(np.uint8)

if __name__ == '__main__':
    n = len(USE); hh, ww = y1 - y0, x1 - x0
    print('frames', n, 'stacked area x', x0, x1, 'y', y0, y1, 'size', ww, hh, 'dust division', not NODUST, flush=True)
    out = np.zeros((4, hh, ww), np.float32); cnt = np.zeros((4, hh, ww), np.uint8); plain = np.zeros_like(out); medn = np.zeros_like(out); single = np.zeros_like(out); seen = np.zeros((4, hh, ww), np.uint8)
    info = []
    SKY = (slice(1500, 2000), slice(1900, 2400))      # a patch of plain sky on the output grid, 1400 px from the cluster
    for p in range(4):
        t0 = time.time()
        with ThreadPoolExecutor(6) as ex:
            cube = np.stack(list(ex.map(lambda s: warp(s, p), USE)))
        single[p] = warp(REF_STAMP, p)
        assert np.isfinite(single[p]).all(), 'the reference frame does not cover the output area'
        frame_sig = [clipped_stats(s[SKY])[1] for s in cube]
        floor = 0.5 * float(np.median(frame_sig))
        rows = [(a, min(a + 96, hh)) for a in range(0, hh, 96)]
        def work(ab):
            a, b = ab
            return ab, clip_chunk(cube[:, a:b], floor)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), (m2, n2, pm, md, nv) in ex.map(work, rows):
                out[p, a:b] = m2; cnt[p, a:b] = n2; plain[p, a:b] = pm; medn[p, a:b] = md; seen[p, a:b] = nv
        rej = 1 - cnt[p].sum() / max(seen[p].sum(), 1)
        info.append(dict(plane=PLANE_NAMES[p], frame_sigma_on_grid=[float(v) for v in frame_sig], sigma_floor=floor, rejected_fraction_of_clean_samples=float(rej), min_frames_clean=int(seen[p].min()), min_frames_used=int(cnt[p].min()),
                         pixels_with_fewer_than_all_frames_clean=int((seen[p] < n).sum()), pixels_with_fewer_than_8_frames_clean=int((seen[p] < 8).sum()), pixels_with_no_frame=int((cnt[p] == 0).sum())))
        print(PLANE_NAMES[p], 'frame sigma %.1f' % np.median(frame_sig), 'rejected %.3f%%' % (100 * rej), 'min clean', seen[p].min(), 'min used', cnt[p].min(), 'px < all clean', int((seen[p] < n).sum()), 'px < 8 clean', int((seen[p] < 8).sum()), '%.0fs' % (time.time() - t0), flush=True)
        del cube
    np.save(W(TAG + 'stack_planes.npy'), out); np.save(W(TAG + 'stack_count.npy'), cnt); pass
    np.save(W(TAG + 'stack_plainmean.npy'), plain); np.save(W(TAG + 'stack_median.npy'), medn); np.save(W(TAG + 'single_planes.npy'), single)
    json.dump(dict(used=USE, kappa=KAPPA, edge=EDGE, origin_sensor_xy=[x0, y0], size=[ww, hh], dust_division=not NODUST, sky_patch_on_grid=dict(rows=[1500, 2000], cols=[1900, 2400]), planes=info), open(W(TAG + 'step5.json'), 'w'), indent=1)
