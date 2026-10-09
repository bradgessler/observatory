"""Step 1: read every RAW in the window, subtract black, subtract a provisional sky (3-sigma clipped mean of the whole
plane; the definitive per-frame sky constant is measured after registration, in step 6), find hot pixels from the run
itself and repair them with the 3 x 3 median of the same colour plane, cache the cleaned planes in the work folder.

Fixed hot pixels: the per-plane median of all frames WITHOUT registration. The field drifted about 190 px and turned
1.3 degrees over the run, so stars and the nebula move across the sensor and drop out of the median; what stays is the
sensor. A pixel standing above the 5 x 5 median of that by more than max(3.5 sigma, 25% of the level) is hot (the median of
33 frames has about 10,000 more pixels per plane between 3.5 and 6 sigma than noise would give: warm pixels, so they are
repaired too; the false alarms at 3.5 sigma, about 1,400 per plane, cost nothing); one more than 5 sigma below it is cold.
(The 3 October scripts used 6 sigma.)
Transient (cosmic rays, single-frame spikes): per frame, above the 3 x 3 median by more than 8 sigma + 50% of the level.
Adapted from hack/stacks/2026-10-03/ngc7662/step1_hot.py; the cube is read plane by plane from disk to keep memory low."""
import os, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

PL = W_('planes')
HOT_SIGMA, COLD_SIGMA = 3.5, 5.0


def load(fr):
    planes, meta = load_planes(fr['path'])
    bg = []
    for p in range(4):
        m, s, med = clipped_stats(planes[p][::3, ::3])
        bg.append(dict(clipped_mean=m, clipped_std=s, median=med))
        planes[p] -= m
    meta['pixels_at_ceiling'] = int((planes + np.array([b['clipped_mean'] for b in bg], np.float32)[:, None, None] >= SAT_DN).sum())
    np.save(os.path.join(PL, fr['stamp'] + '.npy'), planes)
    meta['bg_provisional'] = bg
    return meta


def repair(args):
    fr, meta = args
    hot = np.load(W_('hotmap.npy'))
    P = np.load(os.path.join(PL, fr['stamp'] + '.npy'))
    trans = 0
    for p in range(4):
        med3 = cv2.medianBlur(P[p], 3)
        s = meta['bg_provisional'][p]['clipped_std']
        spike = (P[p] - med3) > np.maximum(8 * s, 0.5 * np.clip(med3, 0, None) + 8 * s)
        spike &= ~hot[p]
        trans += int(spike.sum())
        bad = hot[p] | spike
        P[p][bad] = med3[bad]
    np.save(os.path.join(PL, fr['stamp'] + '.npy'), P)
    return trans


if __name__ == '__main__':
    os.makedirs(PL, exist_ok=True)
    frames = frame_list()
    for f in frames: print(f['name'], f['exposure_s'], f['iso'], 'settling', f['settling'], 'cloud flag', f['cloud_flag'], 'box T', f['box_transparency'])
    ok = [f for f in frames if f['exposure_s'] == 15.0 and f['iso'] == 3200]
    print(len(frames), 'in window,', len(ok), 'at 15 s ISO 3200', flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(load, ok))
    print('read %.0fs' % (time.time() - t0), flush=True)
    n = len(ok)
    hot = np.zeros((4, h2, w2), bool); hot_stats = []
    for p in range(4):
        M = np.empty((h2, w2), np.float32)
        mm = [np.load(os.path.join(PL, f['stamp'] + '.npy'), mmap_mode='r') for f in ok]
        for a in range(0, h2, 256):
            b = min(a + 256, h2)
            M[a:b] = np.median(np.stack([m[p, a:b] for m in mm]), axis=0)
        del mm
        L = cv2.medianBlur(M, 5)
        E = M - L
        sM = 1.4826 * float(np.median(np.abs(E - np.median(E))))
        thr = np.maximum(HOT_SIGMA * sM, 0.25 * np.clip(L, 0, None))
        hot[p] = (E > thr) | (E < -COLD_SIGMA * sM)
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=sM, hot_sigma=HOT_SIGMA, cold_sigma=COLD_SIGMA, fixed_hot=int((hot[p] & (E > 0)).sum()), fixed_cold=int((hot[p] & (E < 0)).sum()), frac=float(hot[p].mean())))
        print(hot_stats[-1], flush=True)
        if p == 1: np.save(W_('unreg_median_G1.npy'), M)
    np.save(W_('hotmap.npy'), hot)
    with ProcessPoolExecutor(WORKERS) as ex:
        trans = list(ex.map(repair, zip(ok, metas)))
    out = []
    for fr, meta, tr_ in zip(ok, metas, trans):
        d = dict(fr); d.update(meta); d['transient_spikes_replaced'] = tr_; d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'sky', [round(b['clipped_mean'], 1) for b in d['bg_provisional']], 'std', [round(b['clipped_std'], 1) for b in d['bg_provisional']],
              'wb', [round(v) for v in d['wb_as_shot']], 'flip', d['flip'], 'rawmax', d['rawmax'], 'ceiling px', d['pixels_at_ceiling'], 'spikes', tr_)
    jsave(dict(frames=out, hot=hot_stats, all_in_window=frames), 'step1.json')
    print('done %.0fs' % (time.time() - t0))
