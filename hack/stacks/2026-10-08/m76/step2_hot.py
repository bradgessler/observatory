"""Step 2: read every RAW of the run, subtract black, measure and subtract one sky constant per plane, find hot
pixels (fixed ones from the unregistered median of all frames: the stars move between frames, the sensor's defects
do not; transient ones per frame), replace them with the 3 x 3 median of the same colour plane, cache the cleaned
planes. The frame flagged settling (the box had already started the slew to M57) is not read: it is not M76.
Adapted from ../../2026-10-03/ngc7662/step1_hot.py."""
import json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

SOLVE = {s['stamp']: s for s in json.load(open(W('step1_solve.json')))}
# where the nebula can be in any frame (sensor px): the solved frames put it at x 3000 to 3144, y 1677 to 1866
NEB_ZONE = (3070.0, 1770.0, 800.0)


def load(fr):
    planes, meta = load_planes(fr['path'])
    cx, cy, r = NEB_ZONE
    mask = ~mask_circle(planes.shape[1:], (cx - 0.5) / 2, (cy - 0.5) / 2, r / 2)
    bg = []
    for p in range(4):
        m, s, med = clipped_stats(planes[p][mask][::3])
        bg.append(dict(clipped_mean=m, clipped_std=s, median=med))
        planes[p] -= m
    meta['bg'] = bg
    meta['raw_exif'] = raw_meta(fr['path'])
    return planes, meta


if __name__ == '__main__':
    frames = frame_list()
    ok, skipped = [], []
    for f in frames:
        why = []
        if f['settling']: why.append('flagged settling in its sidecar (%.1f s since a slew)' % (f['since_slew_s'] or 0))
        if f['pointing_ra_dec'][0] is not None and abs(f['pointing_ra_dec'][0] - TARGET['ra_deg']) > 1: why.append('the mount was pointing at RA %.2f Dec %.2f (M57), the next target' % tuple(f['pointing_ra_dec']))
        if f['cloud']: why.append('flagged cloud in its sidecar')
        if f['exposure_s'] != 15.0 or f['iso'] != 3200: why.append('not 15 s at ISO 3200')
        (skipped if why else ok).append(dict(f, why='; '.join(why)) if why else f)
    for f in frames: print(f['name'], f['exposure_s'], f['iso'], 'settling' if f['settling'] else '', f['cloud'])
    print(len(frames), 'in window,', len(ok), 'read;', [(s['stamp'], s['why']) for s in skipped])
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(load, ok))
    cube = np.stack([r[0] for r in res])      # (n, 4, h, w)
    metas = [r[1] for r in res]
    for f, m in zip(ok, metas):
        assert m['raw_exif']['exposure_s'] == 15.0 and m['raw_exif']['iso'] == 3200, (f['stamp'], m['raw_exif'])
    n = len(ok)
    print('cube', cube.shape, '%.1f GB' % (cube.nbytes / 1e9))
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
    np.save(W('hotmap.npy'), hot)
    out = []
    os.makedirs(W('planes'), exist_ok=True)
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
        np.save(W('planes/' + fr['stamp'] + '.npy'), cube[i])
        d = dict(fr); d.update(metas[i]); d['transient_spikes_replaced'] = trans; d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'sky', [round(b['clipped_mean'], 2) for b in d['bg']], 'std', [round(b['clipped_std'], 1) for b in d['bg']], 'wb', d['wb'], 'flip', d['flip'], 'spikes', trans, 'rawmax', d['rawmax'])
    json.dump(dict(frames=out, hot=hot_stats, all_in_window=frames, not_read=skipped, sky_mask=dict(centre_sensor_px=NEB_ZONE[:2], radius_sensor_px=NEB_ZONE[2])), open(W('step2.json'), 'w'), indent=1)
