"""Step 2: hot pixels from the run itself (there are no darks). Read every frame again, find the fixed hot pixels
from the median of all frames WITHOUT registration (each frame's darkest-corner level taken off first): the field
drifts about 80 sensor px over the series and the four centring frames sit 200 to 700 px away, so a star does not
survive the median but the sensor does. Find single-frame spikes (cosmic rays) in each frame. Replace both with the
3 x 3 median of the same colour plane, and cache the black-subtracted, repaired planes (nothing else is subtracted).

A fixed hot pixel must stand above the 5 x 5 median of the median image by more than max(6 sigma, 25% of the level)
AND above its highest neighbour by half that, so that the peak of a star that barely moves on the sensor is not
taken for one. A spike stands above its frame's 3 x 3 median by more than 8 sigma + 50% of the level, sigma being
the corner noise grown with the square root of the level (shot noise)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

F = jload('step1.json')['frames']
NB = np.ones((3, 3), np.uint8); NB[1, 1] = 0
DARK = 'top_left'          # the darkest corner in every frame (step 1)


def load(fr):
    planes, ceil, meta = load_planes(fr['path'])
    return planes, np.packbits(ceil, axis=None)


if __name__ == '__main__':
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(load, F, chunksize=2))
    shp = res[0][0].shape
    hot = np.zeros(shp, bool); hot_stats = []
    for p in range(4):
        sub = np.stack([res[i][0][p] - np.float32(F[i]['corners'][DARK]['planes'][p]) for i in range(len(F))])
        M = np.median(sub, axis=0); del sub
        L = cv2.medianBlur(M, 5); E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        alone = (M - cv2.dilate(M, NB)) > 0.5 * thr
        hot[p] = (E > thr) & alone
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean()), above_5x5_median_only=int((E > thr).sum())))
        print(hot_stats[-1], flush=True)
        if p == 1: np.save(W('unreg_median_G1.npy'), M)
    np.save(W('hotmap.npy'), hot)
    os.makedirs(W('planes'), exist_ok=True)
    out = []
    for i, fr in enumerate(F):
        P4 = res[i][0]; ceil = np.unpackbits(res[i][1])[:P4.size].reshape(P4.shape).astype(bool)
        nx, ny = [int(round((v - 0.5) / 2)) for v in fr['nucleus_sensor_xy']]
        trans = 0; ceil_n = []; nmax = []; ceil_all = []
        for p in range(4):
            P = P4[p]
            med3 = cv2.medianBlur(P, 3)
            s0 = fr['corners'][DARK]['std'][p]; l0 = max(fr['corners'][DARK]['planes'][p], 1.0)
            s = s0 * np.sqrt(np.maximum(med3, l0) / l0)
            spike = (P - med3) > (8 * s + 0.5 * np.clip(med3, 0, None))
            spike &= ~hot[p]
            trans += int(spike.sum())
            bad = hot[p] | spike
            good_ceil = ceil[p] & ~bad
            box = (slice(max(ny - 100, 0), ny + 100), slice(max(nx - 100, 0), nx + 100))
            ceil_n.append(int(good_ceil[box].sum())); ceil_all.append(int(good_ceil.sum()))
            P[bad] = med3[bad]
            nmax.append(float(P[box].max()))
        np.save(W('planes/' + fr['stamp'] + '.npy'), P4)
        out.append(dict(stamp=fr['stamp'], transient_spikes_replaced=trans, ceiling_pixels_near_nucleus=ceil_n, ceiling_pixels_whole_frame=ceil_all, nucleus_max_dn_above_black_repaired=nmax))
        print(fr['stamp'], 'spikes', trans, 'ceiling near nucleus', ceil_n, 'whole frame', ceil_all, 'nucleus max', [int(v) for v in nmax], flush=True)
    jdump(dict(dark_corner=DARK, frames_in_hot_median=[f['stamp'] for f in F], hot=hot_stats, frames=out), 'step2.json')
