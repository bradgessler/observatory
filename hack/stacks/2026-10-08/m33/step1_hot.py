"""Step 1: read every RAW in the window, keep the 15 s ISO 3200 frames (by the RAW's own EXIF), split into colour planes
(black subtracted), find hot pixels from the run itself and repair them, cache the cleaned planes.

Hot pixels, two kinds, both replaced by the 3 x 3 median of the same colour plane (there are no darks; this stands in
for them):
  fixed      per plane, the median of all frames WITHOUT registration: a pixel that stands above the 5 x 5 median of that
             median image by more than max(6 sigma, 25% of the level) is high in most frames while the stars and the
             galaxy drift across the sensor, so it is the sensor.
  transient  per frame, a pixel above the 3 x 3 median of its own plane by more than 8 sigma + 50% of that median
             (cosmic rays, a hot pixel that only fires sometimes). Stars are smooth over 3 x 3 at this focus, so their
             cores are not touched (checked: the count of replaced pixels per frame is printed and recorded)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *


def load(fr):
    planes, ceil, meta = load_planes(fr['path'])
    meta['ceiling_pixels'] = [int(c.sum()) for c in ceil]
    # noise of each plane from the pixel-to-pixel scatter (robust to the galaxy's glow): MAD of plane - its 3 x 3 median
    meta['pix_sigma'] = []
    for p in range(4):
        d = (planes[p] - cv2.medianBlur(planes[p], 3))[::3, ::3]
        meta['pix_sigma'].append(float(1.4826 * np.median(np.abs(d - np.median(d)))))
    return planes, meta


if __name__ == '__main__':
    frames = frame_list()
    for f in frames:
        f['exposure_s'], f['iso'] = raw_exif(f['path'])
        print(f['name'], 'EXIF %.1f s ISO %d' % (f['exposure_s'], f['iso']), 'sidecar %s s ISO %s' % (f['sidecar_exposure_s'], f['sidecar_iso']), 'since slew %.0f s' % f['since_slew_s'])
    ok = [f for f in frames if (f['exposure_s'], f['iso']) == (EXPOSURE_S, ISO)]
    left = [dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='centring frame (%.0f s at ISO %d), not part of the 15 s ISO 3200 series' % (f['exposure_s'], f['iso'])) for f in frames if f not in ok]
    print(len(frames), 'in window,', len(ok), 'at %.0f s ISO %d' % (EXPOSURE_S, ISO))
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(load, ok))
    cube = np.stack([r[0] for r in res]); metas = [r[1] for r in res]; del res
    print('cube', cube.shape, '%.1f GB' % (cube.nbytes / 1e9), flush=True)
    hot = np.zeros(cube.shape[1:], bool); hot_stats = []
    for p in range(4):
        M = np.median(cube[:, p], axis=0)
        L = cv2.medianBlur(M, 5)
        E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        hot[p] = E > np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), fraction=float(hot[p].mean())))
        print(hot_stats[-1], flush=True)
        if p == 1:
            np.save(W('unreg_median_G1.npy'), M)
    np.save(W('hotmap.npy'), hot)
    os.makedirs(W('planes'), exist_ok=True)
    out = []
    for i, fr in enumerate(ok):
        trans = []
        for p in range(4):
            P = cube[i, p]
            med3 = cv2.medianBlur(P, 3)
            s = metas[i]['pix_sigma'][p]
            spike = ((P - med3) > 8 * s + 0.5 * np.clip(med3, 0, None)) & ~hot[p]
            trans.append(int(spike.sum()))
            bad = hot[p] | spike
            P[bad] = med3[bad]
        np.save(W('planes/%s.npy' % fr['stamp']), cube[i])
        d = dict(fr); d.update(metas[i]); d['transient_replaced'] = trans; d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'pixel sigma', [round(v, 1) for v in d['pix_sigma']], 'transient', trans, 'ceiling', d['ceiling_pixels'], 'wb', [round(v, 3) for v in d['wb']], 'flip', d['flip'], flush=True)
    jdump(dict(frames=out, hot=hot_stats, left_out=left, all_in_window=[f['name'] for f in frames]), 'step1.json')
