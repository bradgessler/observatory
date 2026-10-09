"""Step 1: which frames in the window are M1, then read those RAWs, subtract black, subtract a provisional sky (3-sigma
clipped mean of the whole plane; the definitive per-frame sky constant is measured after registration, in step 7), find
hot pixels from the run itself and repair them with the 3 x 3 median of the same colour plane, cache the cleaned planes
in the work folder.

On target: a frame is on target when its sidecar pointing is within ON_TARGET_DEG of M1; the others would be listed with
their pointing (and the box's own plate solve where there is one) and not read. In the window 07:53:00 to 08:15:00 every
frame present is on M1 (DSC00670 to DSC00691; DSC00692 has its sidecar but its RAW is still on the box). Exposure and ISO
are read from the RAW itself, not only the sidecar.

Fixed hot pixels: the per-plane median of all on-target frames WITHOUT registration (the centring moved the field by
about 1500 px, and the field drifts while tracking, so stars drop out of the median; what stays is the sensor). A pixel
standing above the 5 x 5 median of that by more than max(6 sigma, 25% of the level) is hot (a star core 6 cells across
stands about 15% above its 5 x 5 median, so it is not taken).
Transient (cosmic rays, single-frame spikes): per frame, above the 3 x 3 median by more than 8 sigma + 50% of the level.
Copied from this night's ngc1514/step1_hot.py (itself from m57 and 2026-10-03/ngc7662); only the words changed."""
import os, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

PL = W_('planes')


def load(fr):
    planes, meta = load_planes(fr['path'])
    meta.update(raw_exif=raw_meta(fr['path']))
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
    on, off = [], []
    for f in frames:
        if f['off_target_deg'] is not None and f['off_target_deg'] <= ON_TARGET_DEG:
            on.append(f)
        else:
            bs = f['box_solve']
            f['why'] = 'another target: the sidecar pointing (RA %.3f, Dec %.3f) is %.1f degrees from M1%s' % (
                f['pointing_ra_dec'][0], f['pointing_ra_dec'][1], f['off_target_deg'],
                '; the box\'s own plate solve put it at RA %.3f, Dec %.3f' % (bs['ra_deg'], bs['dec_deg']) if bs and bs.get('ra_deg') else '')
            off.append(f)
    for f in frames:
        print(f['name'], f['exposure_s'], f['iso'], 'off %.2f deg' % f['off_target_deg'], 'settling', f['settling'], 'since slew', f['since_slew_s'], 'box T', f['box_transparency'], 'box HFD', f['box_star_size_arcsec'])
    ok = [f for f in on if f['exposure_s'] == 15.0 and f['iso'] == 3200]
    print(len(frames), 'in window,', len(on), 'on M1,', len(ok), 'at 15 s ISO 3200 by the sidecar', flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(load, ok))
    for f, m in zip(ok, metas):
        assert m['raw_exif']['exposure_s'] == 15.0 and m['raw_exif']['iso'] == 3200, (f['name'], m['raw_exif'])
    print('read %.0fs; exposure and ISO confirmed from the RAWs' % (time.time() - t0), flush=True)
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
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        hot[p] = E > thr
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=sM, fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean())))
        print(hot_stats[-1], flush=True)
    np.save(W_('hotmap.npy'), hot)
    with ProcessPoolExecutor(WORKERS) as ex:
        trans = list(ex.map(repair, zip(ok, metas)))
    out = []
    for fr, meta, tr_ in zip(ok, metas, trans):
        d = dict(fr); d.update(meta); d['transient_spikes_replaced'] = tr_; d['fixed_hot_replaced'] = int(hot.sum())
        out.append(d)
        print(fr['stamp'], 'sky', [round(b['clipped_mean'], 1) for b in d['bg_provisional']], 'std', [round(b['clipped_std'], 1) for b in d['bg_provisional']],
              'wb', [round(v) for v in d['wb_as_shot']], 'flip', d['flip'], 'rawmax', d['rawmax'], 'ceiling px', d['pixels_at_ceiling'], 'spikes', tr_)
    jsave(dict(frames=out, hot=hot_stats, all_in_window=frames, off_target=off), 'step1.json')
    print('done %.0fs' % (time.time() - t0))
