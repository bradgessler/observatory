"""Step 1: list the run (15 s at ISO 3200 by the RAW's own EXIF, pointing within POINTING_RADIUS_DEG of M1 by the
sidecar), measure each frame's pixel noise, and find the sensor's hot pixels from the run itself.

Nothing is cached per frame (the disk is tight): later steps read the RAWs again and repair on the fly (common.load_clean).

Hot pixels, two kinds, both replaced by the 3 x 3 median of the same colour plane (there are no darks; this stands in
for them):
  fixed      per plane, the median WITHOUT registration of every HOT_EVERY-th frame of the run (the field wanders by
             2 to 20 sensor px from frame to frame, 140 px over the run, so no star stays on one pixel): a pixel that stands above the
             5 x 5 median of that median image by more than max(6 sigma, 25% of the level) is the sensor.
  transient  per frame, a pixel above the 3 x 3 median of its own plane by more than 8 sigma + 50% of that median
             (cosmic rays, a hot pixel that only fires sometimes). Done when a frame is read (common.load_clean)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

HOT_EVERY = int(os.environ.get('M1_HOT_EVERY', '1'))


def meta_of(fr):
    planes, ceil, meta = load_planes(fr['path'])
    meta['ceiling_pixels'] = [int(c.sum()) for c in ceil]
    meta['pix_sigma'] = []
    for p in range(4):
        d = (planes[p] - cv2.medianBlur(planes[p], 3))[::3, ::3]
        meta['pix_sigma'].append(float(1.4826 * np.median(np.abs(d - np.median(d)))))
    meta['plane_median'] = [float(np.median(planes[p][::4, ::4])) for p in range(4)]
    return meta


if __name__ == '__main__':
    frames = frame_list()
    for f in frames:
        f['exposure_s'], f['iso'] = raw_exif(f['path'])
    ok, left = [], []
    for f in frames:
        if (f['exposure_s'], f['iso']) != (EXPOSURE_S, ISO):
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='%.0f s at ISO %d, not part of the 15 s ISO 3200 series' % (f['exposure_s'], f['iso'])))
        elif f['pointing_from_target_deg'] is None:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='no pointing in the sidecar (taken while the telescope was being re-aimed)'))
        elif f['pointing_from_target_deg'] > POINTING_RADIUS_DEG:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='pointing %.1f deg from M1: another target' % f['pointing_from_target_deg']))
        else:
            ok.append(f)
    for l in left: print('left out', l['file'], l['why'])
    print(len(frames), 'in window,', len(ok), 'at %.0f s ISO %d on M1' % (EXPOSURE_S, ISO), flush=True)
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(meta_of, ok))
    sub = ok[::HOT_EVERY]
    cube = np.stack([load_planes(f['path'])[0] for f in sub])
    print('hot-pixel cube', cube.shape, '%.1f GB in memory' % (cube.nbytes / 1e9), flush=True)
    hot = np.zeros(cube.shape[1:], bool); hot_stats = []
    for p in range(4):
        M = np.median(cube[:, p], axis=0)
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
        print(fr['stamp'], 'pixel sigma', [round(v, 1) for v in d['pix_sigma']], 'level', [round(v) for v in d['plane_median']], 'ceiling', d['ceiling_pixels'], 'since slew %.0f s' % (fr['since_slew_s'] or -1), 'box star size', fr['box_star_size_arcsec'], flush=True)
    jdump(dict(frames=out, hot=hot_stats, hot_from=[f['name'] for f in sub], left_out=left, all_in_window=[f['name'] for f in frames]), 'step1.json')
