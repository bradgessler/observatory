"""Step 1: find the frames, group them, and measure each frame's levels.
Settings are taken from the camera's own EXIF (in the JPEG beside each RAW) and compared with the sidecar; where
they differ the EXIF is believed and the frame is flagged. Frames are grouped by settings and by the mount's
pointing in the sidecar (a new group starts when the pointing moves by more than 0.03 degrees or 5 minutes pass):
  2 s ISO 6400            finder frames: left out
  2 s ISO 800             'short' (the core frames)
  20 s ISO 3200           by pointing relative to the main centred run (the group that starts at 1137):
                          within 4 arcmin of it 'deep'; within 5 arcmin of a planned panel offset that panel;
                          anything else a 'stray' group of its own (placed later by plate solve)
The sidecar pointing carries the mount model's error (several arcmin, different after every re-centring), so
these names are provisional: the plate solutions of the stacks (step 7) say where each really was.
Per frame: 3-sigma clipped mean and scatter of each colour plane in the top-left corner and in a 12 x 8 grid of
blocks, the place of the brightest nebula, the as-shot white balance, pixels at the ceiling. Nothing is written
but a table."""
import json, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *


def probe(fr):
    planes, ceil, meta = load_planes(fr['path'])
    G = (planes[1] + planes[2]) / 2
    corner = [clipped_stats(planes[p][CORNER]) for p in range(4)]
    meta['corner'] = [dict(clipped_mean=c[0], clipped_std=c[1]) for c in corner]
    meta['corner_green'] = clipped_stats(G[CORNER])[0]
    bs = 251
    meta['blocks'] = [[[clipped_stats(planes[p][i * bs:(i + 1) * bs:2, j * bs:(j + 1) * bs:2], k=2.5)[0] for j in range(W2 // bs)] for i in range(H2 // bs)] for p in range(4)]
    meta['median_plane'] = [float(np.median(planes[p][::4, ::4])) for p in range(4)]
    # the darkest block of the frame (by green), away from the frame's edge: the frame's sky level and noise. (The top-left
    # corner, used for this in the M31 runs, holds bright nebula in one of the panels.)
    gb = (np.array(meta['blocks'][1]) + np.array(meta['blocks'][2])) / 2
    inner = gb[1:-1, 1:-1]; bi, bj = np.unravel_index(np.argmin(inner), inner.shape); bi += 1; bj += 1
    dk = [clipped_stats(planes[p][bi * bs:(bi + 1) * bs, bj * bs:(bj + 1) * bs]) for p in range(4)]
    meta['dark_block'] = dict(block_ij=[int(bi), int(bj)], clipped_mean=[d[0] for d in dk], clipped_std=[d[1] for d in dk])
    meta['sky_green'] = float((dk[1][0] + dk[2][0]) / 2); meta['noise_g1'] = float(dk[1][1])
    meta['p10_plane'] = [float(np.percentile(planes[p][::4, ::4], 10)) for p in range(4)]
    # the brightest nebula (the Huygens region round the Trapezium): the maximum of a wide blur of the median-filtered green, single values capped
    unit = fr['exposure_s'] * fr['iso'] / 64000.0          # 1 for a 20 s ISO 3200 frame
    m5 = cv2.medianBlur(G, 5)
    c = np.clip(m5 - np.percentile(m5[::8, ::8], 5), 0, 3000 * unit)
    sm = cv2.GaussianBlur(c, (0, 0), 25)
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    meta['core_peak_capped'] = float(sm[y, x] / unit)
    meta['core_sensor_xy'] = [2 * float(x) + 0.5, 2 * float(y) + 0.5] if sm[y, x] > 1000 * unit else None
    meta['ceiling_pixels'] = [int(ceil[p].sum()) for p in range(4)]
    meta['near_ceiling_pixels'] = [int((planes[p] >= NEAR_CEILING).sum()) for p in range(4)]
    return meta


if __name__ == '__main__':
    allf = frame_list()
    for f in allf:
        f['settings_mismatch'] = bool(f['exif_exposure_s'] is not None and (abs(f['exif_exposure_s'] - (f['sidecar_exposure_s'] or -1)) > 0.01 or f['exif_iso'] != f['sidecar_iso']))
    finder = [f for f in allf if abs(f['exposure_s'] - 2.0) < 0.01 and f['iso'] == 6400]
    short = [f for f in allf if abs(f['exposure_s'] - 2.0) < 0.01 and f['iso'] == 800]
    deep = [f for f in allf if abs(f['exposure_s'] - 20.0) < 0.01 and f['iso'] == 3200]
    other = [f for f in allf if f not in finder and f not in short and f not in deep]
    print(len(allf), 'RAW stills in the window %s..%s: %d finder (2 s ISO 6400), %d short (2 s ISO 800), %d at 20 s ISO 3200, %d other %s' % (T0, T1, len(finder), len(short), len(deep), len(other), [(f['stamp'], f['exposure_s'], f['iso']) for f in other]))
    for f in allf:
        if f['settings_mismatch']: print('  sidecar and EXIF disagree:', f['stamp'], 'sidecar', f['sidecar_exposure_s'], f['sidecar_iso'], 'EXIF', f['exif_exposure_s'], f['exif_iso'], '-> EXIF believed')
    # groups of 20 s frames by pointing
    groups = []
    for f in deep:
        g = groups[-1] if groups else None
        if g and abs(f['dec_deg'] - g[0]['dec_deg']) < 0.03 and abs(f['ra_deg'] - g[0]['ra_deg']) * np.cos(np.radians(5.4)) < 0.03 and tsec(f['t']) - tsec(g[-1]['t']) < 300:
            g.append(f)
        else:
            groups.append([f])
    main = max(groups, key=lambda g: (g[0]['stamp'][9:13] == '1137', len(g)))
    assert main[0]['stamp'][9:13] == '1137', main[0]['stamp']
    ra0 = np.mean([f['ra_deg'] for f in main]); dec0 = np.mean([f['dec_deg'] for f in main])
    nstray = 0
    for g in groups:
        e = (np.mean([f['ra_deg'] for f in g]) - ra0) * np.cos(np.radians(5.4)) * 60; n = (np.mean([f['dec_deg'] for f in g]) - dec0) * 60
        name = None
        if np.hypot(e, n) < 4.0: name = 'deep'
        else:
            for pn, pe, pnn in PANELS:
                if np.hypot(e - pe, n - pnn) < 5.0: name = pn
        if name is None:
            nstray += 1; name = 'stray%d' % nstray
        for f in g: f['set'] = name; f['group_first'] = g[0]['stamp']; f['mount_offset_arcmin'] = [float(e), float(n)]
        print('%-7s %2d frames %s .. %s  mount offset from the 1137 run %+6.1f E %+6.1f N arcmin' % (name, len(g), g[0]['stamp'][9:], g[-1]['stamp'][9:], e, n))
    for f in short: f['set'] = 'short'; f['group_first'] = short[0]['stamp']
    use = deep + short
    with ProcessPoolExecutor(8) as ex:
        metas = list(ex.map(probe, use))
    out = []
    for f, m in zip(use, metas):
        d = dict(f); d.update(m); out.append(d)
        b = np.array(m['blocks'][1])
        print('%s %-7s sky G %6.1f noise %5.1f at %s | corner G %6.1f R %6.1f B %6.1f std G1 %5.1f | G1 blocks min %5.0f med %5.0f max %6.0f | core %s | ceiling px %s | wb %s alt %.1f' % (
            f['stamp'], f['set'], m['sky_green'], m['noise_g1'], m['dark_block']['block_ij'], m['corner_green'], m['corner'][0]['clipped_mean'], m['corner'][3]['clipped_mean'], m['corner'][1]['clipped_std'], b.min(), np.median(b), b.max(),
            None if m['core_sensor_xy'] is None else np.round(m['core_sensor_xy']).astype(int).tolist(), m['ceiling_pixels'], [int(v) for v in m['wb'][:3]], f['alt_deg']), flush=True)
    out.sort(key=lambda d: d['stamp'])
    json.dump(dict(frames=out, left_out=[dict(f, why='finder frame (2 s ISO 6400)') for f in finder] + [dict(f, why='other settings') for f in other]), open(W('s1.json'), 'w'), indent=1)
