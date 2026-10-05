"""Step 5: put every frame's four colour planes onto the reference frame's sensor grid (rotation + shift,
Lanczos-4 from the half-size plane straight to the sensor grid, no demosaic), then combine per pixel with a
sigma-clipped mean. Also keeps the plain mean, the median, the count of frames used per pixel, and the
reference frame alone on the same grid."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

KAPPA = 3.0
MARGIN = 64          # sensor px trimmed from each edge so every output pixel has all frames
H, W = 4024, 6024
tr = {o['stamp']: o for o in json.load(open(os.path.join(SCR, 'step3_transforms.json')))}
st1 = json.load(open(os.path.join(SCR, 'step1.json')))
USE = [l.strip() for l in open(os.path.join(SCR, 'use.txt'))] if os.path.exists(os.path.join(SCR, 'use.txt')) else [f['stamp'] for f in st1['frames']]
offs = [(0, 0), (1, 0), (0, 1), (1, 1)]
y0, y1, x0, x1 = MARGIN, H - MARGIN, MARGIN, W - MARGIN
gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)

def warp(stamp, p):
    P = np.load(os.path.join(SCR, 'planes', stamp + '.npy'), mmap_mode='r')[p]
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64)
    ox, oy = offs[p]
    mx = ((R[0, 0] * gx + R[0, 1] * gy + t[0]) - ox) / 2
    my = ((R[1, 0] * gx + R[1, 1] * gy + t[1]) - oy) / 2
    return cv2.remap(np.ascontiguousarray(P), mx.astype(np.float32), my.astype(np.float32), cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))

def clip_chunk(c, floor):
    med = np.median(c, axis=0)
    dev = np.abs(c - med)
    sig = np.maximum(1.4826 * np.median(dev, axis=0), floor)
    keep = dev <= KAPPA * sig
    n1 = keep.sum(0); m1 = (c * keep).sum(0) / n1
    sd = np.sqrt(((c - m1) ** 2 * keep).sum(0) / np.maximum(n1 - 1, 1)); sd = np.maximum(sd, floor)
    keep = np.abs(c - m1) <= KAPPA * sd
    n2 = keep.sum(0); m2 = (c * keep).sum(0) / n2
    return m2.astype(np.float32), n2.astype(np.uint8), c.mean(0).astype(np.float32), med.astype(np.float32)

if __name__ == '__main__':
    n = len(USE); hh, ww = y1 - y0, x1 - x0
    out = np.zeros((4, hh, ww), np.float32); cnt = np.zeros((4, hh, ww), np.uint8); plain = np.zeros_like(out); medn = np.zeros_like(out); single = np.zeros_like(out)
    info = []
    for p in range(4):
        t0 = time.time()
        with ThreadPoolExecutor(6) as ex:
            cube = np.stack(list(ex.map(lambda s: warp(s, p), USE)))
        assert np.isfinite(cube).all(), 'a frame does not cover the output area; raise MARGIN'
        single[p] = cube[USE.index(REF_STAMP)]
        # per-frame noise on the output grid, in a patch of plain sky
        sk = cube[:, 400:900, 2600:3100]
        frame_sig = [clipped_stats(s)[1] for s in sk]
        floor = 0.5 * float(np.median(frame_sig))
        rows = [(a, min(a + 96, hh)) for a in range(0, hh, 96)]
        def work(ab):
            a, b = ab
            return ab, clip_chunk(cube[:, a:b], floor)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), (m2, n2, pm, md) in ex.map(work, rows):
                out[p, a:b] = m2; cnt[p, a:b] = n2; plain[p, a:b] = pm; medn[p, a:b] = md
        rej = 1 - cnt[p].mean() / n
        info.append(dict(plane=PLANE_NAMES[p], frame_sigma_on_grid=[float(v) for v in frame_sig], sigma_floor=floor, rejected_fraction=float(rej), min_frames_used=int(cnt[p].min())))
        print(PLANE_NAMES[p], 'frame sigma %.1f' % np.median(frame_sig), 'rejected %.3f%%' % (100 * rej), 'min used', cnt[p].min(), '%.0fs' % (time.time() - t0), flush=True)
        del cube
    np.save(os.path.join(SCR, 'stack_planes.npy'), out); np.save(os.path.join(SCR, 'stack_count.npy'), cnt)
    np.save(os.path.join(SCR, 'stack_plainmean.npy'), plain); np.save(os.path.join(SCR, 'stack_median.npy'), medn); np.save(os.path.join(SCR, 'single_planes.npy'), single)
    json.dump(dict(used=USE, kappa=KAPPA, margin=MARGIN, origin_sensor_xy=[x0, y0], size=[ww, hh], planes=info), open(os.path.join(SCR, 'step5.json'), 'w'), indent=1)
