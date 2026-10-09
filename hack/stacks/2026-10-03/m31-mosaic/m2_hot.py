"""Mosaic step 2: hot pixels (same rule as the core run's step2_hot.py, rebuilt for 30 s frames).
Fixed hot pixels: the per-plane median, WITHOUT registration, of the frames with the lower sky levels (each minus
its corner level); these come from six different pointings, so no star survives the median. A pixel is hot if it
stands above the 5x5 median of that by more than max(6 sigma, 25% of the level) AND above its highest neighbour
by half that. Single-frame spikes: above the 3x3 median by more than 8 sigma + 50% of the level. Both are
replaced by the 3x3 median of the same colour plane, and the repaired, black-subtracted planes are cached."""
import json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from mcommon import *

F = json.load(open(W('m1.json')))['frames']
NB = np.ones((3, 3), np.uint8); NB[1, 1] = 0


def load(fr):
    planes, ceil, meta = load_planes(fr['path'])
    return planes


if __name__ == '__main__':
    lv = np.array([f['corner_green'] for f in F])
    low = [i for i in np.argsort(lv)[:36]]
    print('hot-pixel median from the %d frames with the lowest corner level (%.0f..%.0f DN green), panels: %s' % (len(low), lv[low].min(), lv[low].max(), sorted(set(F[i]['panel'] for i in low))))
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(load, F, chunksize=2))
    shp = res[0].shape
    hot = np.zeros(shp, bool); hot_stats = []
    core_hot = np.load(CW('hotmap.npy'))
    for p in range(4):
        sub = np.stack([res[i][p] - np.float32(F[i]['corner'][p]['clipped_mean']) for i in low])
        M = np.median(sub, axis=0); del sub
        L = cv2.medianBlur(M, 5); E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        alone = (M - cv2.dilate(M, NB)) > 0.5 * thr
        hot[p] = (E > thr) & alone
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean()),
                              also_in_core_map=int((hot[p] & core_hot[p]).sum()), core_map=int(core_hot[p].sum())))
        print(hot_stats[-1], flush=True)
    np.save(W('hotmap.npy'), hot)
    os.makedirs(W('planes'), exist_ok=True)
    out = []
    for i, fr in enumerate(F):
        P4 = res[i]; trans = 0
        for p in range(4):
            P = P4[p]
            med3 = cv2.medianBlur(P, 3)
            s0 = fr['corner'][p]['clipped_std']; l0 = max(fr['corner'][p]['clipped_mean'], 1.0)
            s = s0 * np.sqrt(np.maximum(med3, l0) / l0)
            spike = (P - med3) > (8 * s + 0.5 * np.clip(med3, 0, None))
            spike &= ~hot[p]
            trans += int(spike.sum())
            bad = hot[p] | spike
            P[bad] = med3[bad]
        np.save(W('planes/' + fr['stamp'] + '.npy'), P4)
        out.append(dict(stamp=fr['stamp'], transient_spikes_replaced=trans))
        print(fr['stamp'], fr['panel'], 'spikes', trans, flush=True)
    json.dump(dict(frames_in_hot_median=[F[i]['stamp'] for i in low], hot=hot_stats, frames=out), open(W('m2.json'), 'w'), indent=1)
