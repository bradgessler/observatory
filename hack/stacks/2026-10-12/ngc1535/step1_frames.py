"""Step 1: list the run (4 s at ISO 1600 by the RAW's own EXIF, pointing within POINTING_RADIUS_DEG of NGC 1535 by the
sidecar; the 2 s ISO 6400 centring pictures just before it are listed and left out), measure each frame's pixel noise
and how many pixels sit at the sensor's ceiling, and find the sensor's hot pixels from the run itself.

Nothing is cached per frame (the disk is tight): later steps read the RAWs again and repair on the fly (common.load_clean).

Hot pixels, two kinds, both replaced by the 3 x 3 median of the same colour plane (there are no darks; this stands in
for them):
  fixed      per plane, the median WITHOUT registration of every frame of the run: a pixel that stands above the 5 x 5
             median of that median image by more than max(6 sigma, 25% of the level) is the sensor. (A star here is
             about 7 plane px across at half flux: its peak stands under 20% above its own 5 x 5 median, so stars and
             the nebula's disc, which sat on nearly the same pixels within each of the two runs, are not taken for hot
             pixels. The log counts how many flagged pixels lie within 30 px of the nebula: see step 6's check.)
  transient  per frame, a pixel above the 3 x 3 median of its own plane by more than 8 sigma + 50% of that median
             (cosmic rays, a hot pixel that only fires sometimes). Done when a frame is read (common.load_clean)."""
import os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *


def read(fr):
    P16, meta = load_raw16(fr['path'])
    meta['ceiling_pixels'] = [int((P16[p] >= CEILING_RAW).sum()) for p in range(4)]
    meta['pix_sigma'] = []
    for p in range(4):
        a = P16[p].astype(np.float32)
        d = (a - cv2.medianBlur(a, 3))[::3, ::3]
        meta['pix_sigma'].append(float(1.4826 * np.median(np.abs(d - np.median(d)))))
    meta['plane_median'] = [float(np.median(P16[p][::4, ::4])) - 512.0 for p in range(4)]
    return P16, meta


if __name__ == '__main__':
    frames = frame_list('093400', T1)
    for f in frames:
        f['exposure_s'], f['iso'] = raw_exif(f['path'])
    ok, left = [], []
    for f in frames:
        if (f['exposure_s'], f['iso']) != (EXPOSURE_S, ISO):
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='%.0f s at ISO %d: a centring picture (or another target), not part of the 4 s ISO 1600 series' % (f['exposure_s'], f['iso'])))
        elif f['pointing_from_target_deg'] is None or f['pointing_from_target_deg'] > POINTING_RADIUS_DEG:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='pointing not within %.1f deg of NGC 1535: another target' % POINTING_RADIUS_DEG))
        else:
            ok.append(f)
    for l in left: print('left out', l['file'], l['why'])
    print(len(frames), 'in window,', len(ok), 'at %.0f s ISO %d on NGC 1535' % (EXPOSURE_S, ISO), flush=True)
    with ThreadPoolExecutor(WORKERS) as ex:
        res = list(ex.map(read, ok))
    cube = np.stack([r[0] for r in res]); metas = [r[1] for r in res]; del res
    print('hot-pixel cube', cube.shape, cube.dtype, '%.1f GB in memory' % (cube.nbytes / 1e9), flush=True)
    hot = np.zeros(cube.shape[1:], bool); hot_stats = []
    for p in range(4):
        M = np.empty((h2, w2), np.float32)
        for a in range(0, h2, 128):
            M[a:a + 128] = np.median(cube[:, p, a:a + 128], axis=0)
        M -= 512.0
        L = cv2.medianBlur(M, 5)
        E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        hot[p] = E > np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), fraction=float(hot[p].mean())))
        print(hot_stats[-1], flush=True)
    np.save(W('hotmap.npy'), hot)
    out = []
    for fr, m in zip(ok, metas):
        d = dict(fr); d.update(m); d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'pixel sigma', [round(v, 1) for v in d['pix_sigma']], 'level', [round(v) for v in d['plane_median']], 'ceiling', d['ceiling_pixels'], 'since slew %.0f s' % (fr['since_slew_s'] if fr['since_slew_s'] is not None else -1),
              'axes turned', [round(v) for v in fr['mount_axes_turned_arcsec'] or []], 'box star size', fr['box_star_size_arcsec'], flush=True)
    jdump(dict(frames=out, hot=hot_stats, hot_from=[f['name'] for f in ok], left_out=left, all_in_window=[f['name'] for f in frames]), 'step1.json')
