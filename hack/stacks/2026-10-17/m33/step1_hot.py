"""Step 1: list the frames of the four turns (15 s at ISO 3200 by the RAW's own EXIF; on M33 by the frame's own plate
solve, within POINTING_RADIUS_DEG; a 13 October frame with no plate solve by its sidecar pointing, within 1.5 degrees, as
that night's pipeline did), measure each frame's pixel noise, and find the sensor's hot pixels from the frames themselves,
one map per night (the sensor's warm pixels change with temperature).

Left out here: centring frames (2 s at ISO 6400), Saturn (1/60 s), anything not at 15 s ISO 3200, anything not on M33.

Hot pixels, two kinds, both replaced by the 3 x 3 median of the same colour plane (there are no darks):
  fixed      per night, the median WITHOUT registration of every HOT_EVERY-th frame (the field moves by drift and dither,
             so no star stays on one pixel): a pixel above the 5 x 5 median of that median image by more than
             max(6 sigma, 25% of the level) is the sensor.
  transient  per frame, above the 3 x 3 median by more than 8 sigma + 50% of that median (common.load_clean)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

HOT_EVERY = int(os.environ.get('M33_HOT_EVERY', '6'))   # every 6th frame of a night: 40 tonight, 20 from 13 October


def meta_of(fr):
    planes, ceil, meta = load_planes(fr['path'])
    meta['ceiling_pixels'] = [int(c.sum()) for c in ceil]
    meta['pix_sigma'] = []
    for p in range(4):
        d = (planes[p] - cv2.medianBlur(planes[p], 3))[::3, ::3]
        meta['pix_sigma'].append(float(1.4826 * np.median(np.abs(d - np.median(d)))))
    meta['plane_median'] = [float(np.median(planes[p][::4, ::4])) for p in range(4)]
    return meta


def _planes(f):
    return load_planes(f['path'])[0]


if __name__ == '__main__':
    frames = frame_list()
    for f in frames:
        f['exposure_s'], f['iso'] = raw_exif(f['path'])
    ok, left = [], []
    for f in frames:
        if (f['exposure_s'], f['iso']) != (EXPOSURE_S, ISO):
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='%.0f s at ISO %d, not part of the 15 s ISO 3200 series' % (f['exposure_s'], f['iso'])))
        elif f['pointing_from_target_deg'] is None:
            sp = None
            if f['night'] == '13oct' and f['ra_deg'] is not None:
                sp = float(np.hypot((f['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), f['dec_deg'] - TARGET['dec_deg']))
            if sp is not None and sp <= 1.5:
                f['pointing_from'] = 'sidecar pointing (no plate solve)'; ok.append(f)
            else:
                left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='no plate solve%s' % (' and no pointing in the sidecar (taken while the telescope was being re-aimed)' if sp is None else ', sidecar pointing %.1f deg from M33' % sp)))
        elif f['pointing_from_target_deg'] > POINTING_RADIUS_DEG:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='plate solve %.1f deg from M33: another target' % f['pointing_from_target_deg']))
        else:
            f['pointing_from'] = 'plate solve'; ok.append(f)
    for l in left: print('left out', l['file'], l['why'])
    print(len(frames), 'in window,', len(ok), 'at %.0f s ISO %d on M33' % (EXPOSURE_S, ISO), flush=True)
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(meta_of, ok))
    hot_stats = []; hot_from = {}
    for night in ('18oct', '13oct'):
        sub = [f for f in ok if f['night'] == night][::HOT_EVERY]
        if not sub: continue
        hot_from[night] = [f['name'] for f in sub]
        hot = np.zeros((4, h2, w2), bool)
        with ProcessPoolExecutor(WORKERS) as ex:
            cube4 = np.stack(list(ex.map(_planes, sub)))
        for p in range(4):
            M = np.median(cube4[:, p], axis=0)
            L = cv2.medianBlur(M, 5)
            E = M - L
            sM = 1.4826 * np.median(np.abs(E - np.median(E)))
            hot[p] = E > np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
            hot_stats.append(dict(night=night, frames=len(sub), plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), fraction=float(hot[p].mean())))
            print(hot_stats[-1], flush=True)
        del cube4
        np.save(W('hotmap_%s.npy' % night), hot)
    out = []
    for fr, m in zip(ok, metas):
        d = dict(fr); d.update(m); d['fixed_hot_replaced'] = int(np.load(W('hotmap_%s.npy' % fr['night'])).sum())
        out.append(d)
        print(fr['stamp'], fr['turn'], 'pixel sigma', [round(v, 1) for v in d['pix_sigma']], 'level', [round(v) for v in d['plane_median']], 'ceiling', d['ceiling_pixels'], 'since slew %.0f s' % (fr['since_slew_s'] or -1), 'box star size', fr['box_star_size_arcsec'], flush=True)
    jdump(dict(frames=out, hot=hot_stats, hot_from=hot_from, left_out=left, all_in_window=[f['name'] for f in frames]), 'step1.json')
