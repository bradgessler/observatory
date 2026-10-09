"""Step 1: read every RAW, subtract black, measure and subtract sky per plane, find hot pixels
(fixed ones from the unregistered median of all frames, transient ones per frame), replace them
with the 3x3 median of the same colour plane, cache the cleaned planes."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

def load(fr):
    planes, meta = load_planes(fr['path'])
    mask = sky_mask(planes.shape[1:], [NEB_REF, STAR_REF])
    bg = []
    for p in range(4):
        m, s, med = clipped_stats(planes[p][mask][::3])
        bg.append(dict(clipped_mean=m, clipped_std=s, median=med))
        planes[p] -= m
    meta['bg'] = bg
    return planes, meta

if __name__ == '__main__':
    frames = frame_list()
    for f in frames: print(f['name'], f['exposure_s'], f['iso'])
    ok = [f for f in frames if f['exposure_s'] == 6.0 and f['iso'] == 1600]
    print(len(frames), 'in window,', len(ok), 'at 6 s ISO 1600')
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(load, ok))
    cube = np.stack([r[0] for r in res])      # (n, 4, h, w)
    metas = [r[1] for r in res]
    n = len(ok)
    print('cube', cube.shape, cube.nbytes / 1e9, 'GB')
    hot = np.zeros(cube.shape[1:], bool); hot_stats = []
    for p in range(4):
        M = np.median(cube[:, p], axis=0)
        L = cv2.medianBlur(M, 5)
        E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        hot[p] = E > thr
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean())))
        print(hot_stats[-1])
        if p == 1: np.save(os.path.join(SCR, 'unreg_median_G1.npy'), M)
    np.save(os.path.join(SCR, 'hotmap.npy'), hot)
    out = []
    os.makedirs(os.path.join(SCR, 'planes'), exist_ok=True)
    for i, fr in enumerate(ok):
        trans = 0
        for p in range(4):
            P = cube[i, p]
            med3 = cv2.medianBlur(P, 3)
            s = metas[i]['bg'][p]['clipped_std']
            spike = (P - med3) > np.maximum(8 * s, 0.5 * np.clip(med3, 0, None) + 8 * s)
            spike &= ~hot[p]
            trans += int(spike.sum())
            bad = hot[p] | spike
            P[bad] = med3[bad]
        np.save(os.path.join(SCR, 'planes', fr['stamp'] + '.npy'), cube[i])
        d = dict(fr); d.update(metas[i]); d['transient_spikes_replaced'] = trans; d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'bg', [round(b['clipped_mean'], 2) for b in d['bg']], 'std', [round(b['clipped_std'], 1) for b in d['bg']], 'wb', d['wb'], 'flip', d['flip'], 'spikes', trans)
    json.dump(dict(frames=out, hot=hot_stats, all_in_window=frames), open(os.path.join(SCR, 'step1.json'), 'w'), indent=1)
