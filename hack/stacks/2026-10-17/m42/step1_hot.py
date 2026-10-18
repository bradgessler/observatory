"""Step 1: list the frames of the three runs (pre, long, short: common.TURNS), check each against its kind's exposure
and ISO by the RAW's own EXIF (long 30 s ISO 1600, short 2 s ISO 400), and that it is on M42 by its own plate solve
(within POINTING_RADIUS_DEG of the Trapezium; a frame with no plate solve by its sidecar pointing, within 1.5 degrees,
as the 13 October M33 frames were), measure each frame's pixel noise, and find the sensor's hot pixels from the frames
themselves, one map per kind (a 30 s ISO 1600 frame and a 2 s ISO 400 frame show different warm pixels).

Left out here: centring frames (2 s at ISO 6400), anything not at its kind's exposure and ISO, anything not on M42.

Hot pixels, two kinds, both replaced by the 3 x 3 median of the same colour plane (there are no darks):
  fixed      per kind, the median WITHOUT registration of every HOT_EVERY-th frame (the field moves by drift and dither,
             so no star stays on one pixel): a pixel above the 5 x 5 median of that median image by more than
             max(6 sigma, 25% of the level) is the sensor (sigma floored at 1 DN: in the short frames' red plane
             the median of integer values has a MAD of 0).
  transient  per frame, above the 3 x 3 median by more than 8 sigma + 50% of that median (common.load_clean)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

HOT_EVERY = dict(long=int(os.environ.get('M42_HOT_EVERY', '6')), short=int(os.environ.get('M42_HOT_EVERY_SHORT', '3')))   # 32 long frames, 16 short


def meta_of(fr):
    planes, ceil, meta = load_planes(fr['path'])
    meta['ceiling_pixels'] = [int(c.sum()) for c in ceil]
    meta['near_ceiling_pixels'] = [int((planes[p] >= NEAR_CEILING * (CEILING_RAW - meta['black'][0])).sum()) for p in range(4)]
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
        want = EXPECT[f['kind']]
        if (f['exposure_s'], f['iso']) != want:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='%g s at ISO %d, not part of the %g s ISO %d %s series%s' % (f['exposure_s'], f['iso'], want[0], want[1], f['kind'], ' (a centring frame)' if f['iso'] == 6400 else '')))
        elif f['pointing_from_target_deg'] is None:
            sp = None
            if f['ra_deg'] is not None:
                sp = float(np.hypot((f['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), f['dec_deg'] - TARGET['dec_deg']))
            if sp is not None and sp <= 1.5:
                f['pointing_from'] = 'sidecar pointing (no plate solve), %.2f deg from the Trapezium' % sp; ok.append(f)
            else:
                left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='no plate solve%s' % (' and no pointing in the sidecar' if sp is None else ', sidecar pointing %.1f deg from M42' % sp)))
        elif f['pointing_from_target_deg'] > POINTING_RADIUS_DEG:
            left.append(dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='plate solve %.1f deg from M42: another target' % f['pointing_from_target_deg']))
        else:
            f['pointing_from'] = 'plate solve'; ok.append(f)
    for l in left: print('left out', l['file'], l['why'])
    print(len(frames), 'in the windows,', len(ok), 'on M42 at their kind\'s exposure:', {k: sum(f['kind'] == k for f in ok) for k in EXPECT}, flush=True)
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(meta_of, ok))
    hot_stats = []; hot_from = {}
    for kind in ('long', 'short'):
        sub = [f for f in ok if f['kind'] == kind][::HOT_EVERY[kind]]
        if not sub: continue
        hot_from[kind] = [f['name'] for f in sub]
        hot = np.zeros((4, h2, w2), bool)
        with ProcessPoolExecutor(WORKERS) as ex:
            cube4 = np.stack(list(ex.map(_planes, sub)))
        for p in range(4):
            M = np.median(cube4[:, p], axis=0)
            L = cv2.medianBlur(M, 5)
            E = M - L
            sM = max(1.4826 * np.median(np.abs(E - np.median(E))), 1.0)   # floor 1 DN: a median of integer DN can have a MAD of 0 (the short red plane)
            hot[p] = E > np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
            hot_stats.append(dict(kind=kind, frames=len(sub), plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), fraction=float(hot[p].mean())))
            print(hot_stats[-1], flush=True)
        del cube4
        np.save(W('hotmap_%s.npy' % kind), hot)
    out = []
    for fr, m in zip(ok, metas):
        d = dict(fr); d.update(m); d['fixed_hot_replaced'] = int(np.load(W('hotmap_%s.npy' % fr['kind'])).sum())
        out.append(d)
        print(fr['stamp'], fr['turn'], 'pixel sigma', [round(v, 1) for v in d['pix_sigma']], 'level', [round(v) for v in d['plane_median']], 'near ceiling', d['near_ceiling_pixels'], 'since move %.0f s' % (fr['since_slew_s'] or -1), 'alt %.0f' % (fr['alt_deg'] or -1), flush=True)
    jdump(dict(frames=out, hot=hot_stats, hot_from=hot_from, left_out=left, all_in_window=[f['name'] for f in frames]), 'step1.json')
