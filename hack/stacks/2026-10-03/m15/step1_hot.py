"""Step 1: read every RAW, subtract black, measure and subtract sky per plane (outside the cluster and the
saturated star), find hot pixels (fixed ones from the unregistered median of all frames, transient ones per
frame), replace them with the 3x3 median of the same colour plane, cache the cleaned planes. Also counts
pixels at the sensor's ceiling in the cluster and in the bright field star (hot pixels left out)."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

def load(fr):
    planes, ceil, meta = load_planes(fr['path'])
    G = (planes[1] + planes[2]) / 2
    cl = find_cluster(G); br = find_bright(G, cl)
    mask = sky_mask(planes.shape[1:], cl, br)
    bg = []
    for p in range(4):
        m, s, med = clipped_stats(planes[p][mask][::3])
        bg.append(dict(clipped_mean=m, clipped_std=s, median=med))
        planes[p] -= m
    meta['bg'] = bg
    meta['cluster_sensor_xy'] = [2 * cl[0] + 0.5, 2 * cl[1] + 0.5]; meta['bright_star_sensor_xy'] = [2 * br[0] + 0.5, 2 * br[1] + 0.5]
    meta['sky_mask_fraction'] = float(mask.mean())
    return planes, ceil, meta

if __name__ == '__main__':
    frames = frame_list()
    for f in frames: print(f['name'], f['exposure_s'], f['iso'])
    ok = [f for f in frames if f['exposure_s'] == EXPOSURE_S and f['iso'] == ISO]
    print(len(frames), 'in window,', len(ok), 'at 15 s ISO 1600')
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(load, ok))
    cube = np.stack([r[0] for r in res])      # (n, 4, h, w)
    ceils = [r[1] for r in res]; metas = [r[2] for r in res]
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
        if p == 1: np.save(W('unreg_median_G1.npy'), M)
    np.save(W('hotmap.npy'), hot)
    out = []
    os.makedirs(W('planes'), exist_ok=True)
    h, w = cube.shape[2:]; yy, xx = np.mgrid[0:h, 0:w]
    for i, fr in enumerate(ok):
        trans = 0
        cx, cy = [(v - 0.5) / 2 for v in metas[i]['cluster_sensor_xy']]; bx, by = [(v - 0.5) / 2 for v in metas[i]['bright_star_sensor_xy']]
        in_cl = np.hypot(xx - cx, yy - cy) <= 400      # 800 sensor px = 5.2 arcmin radius: the whole bright part of the cluster
        in_br = np.hypot(xx - bx, yy - by) <= 30
        ceil_cl, ceil_br, max_cl = {}, {}, {}
        for p in range(4):
            P = cube[i, p]
            med3 = cv2.medianBlur(P, 3)
            s = metas[i]['bg'][p]['clipped_std']
            spike = (P - med3) > np.maximum(8 * s, 0.5 * np.clip(med3, 0, None) + 8 * s)
            spike &= ~hot[p]
            trans += int(spike.sum())
            bad = hot[p] | spike
            good_ceil = ceils[i][p] & ~bad
            ceil_cl[PLANE_NAMES[p]] = int((good_ceil & in_cl).sum()); ceil_br[PLANE_NAMES[p]] = int((good_ceil & in_br).sum())
            P[bad] = med3[bad]
            max_cl[PLANE_NAMES[p]] = float(P[in_cl].max() + metas[i]['bg'][p]['clipped_mean'])   # black-subtracted DN, hot pixels repaired
        np.save(W('planes/' + fr['stamp'] + '.npy'), cube[i])
        d = dict(fr); d.update(metas[i]); d['transient_spikes_replaced'] = trans; d['fixed_hot_replaced'] = int(hot.sum())
        d['ceiling_pixels_in_cluster'] = ceil_cl; d['ceiling_pixels_in_bright_star'] = ceil_br; d['cluster_max_dn_above_black'] = max_cl
        out.append(d)
        print(fr['stamp'], 'bg', [round(b['clipped_mean'], 2) for b in d['bg']], 'std', [round(b['clipped_std'], 1) for b in d['bg']], 'wb', d['wb'], 'flip', d['flip'], 'spikes', trans,
              'cluster', np.round(d['cluster_sensor_xy']).tolist(), 'bright', np.round(d['bright_star_sensor_xy']).tolist(), 'ceil cl', sum(ceil_cl.values()), 'br', sum(ceil_br.values()), 'clmax', [int(v) for v in max_cl.values()])
    json.dump(dict(frames=out, hot=hot_stats, all_in_window=frames), open(W('step1.json'), 'w'), indent=1)
