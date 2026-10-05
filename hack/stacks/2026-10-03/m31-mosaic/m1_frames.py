"""Mosaic step 1: find the frames, group them into panels, and measure each frame's levels.
Frames are grouped by the mount's pointing in the sidecar (a new group starts when the pointing moves by more
than 0.1 degrees); the 2 s ISO 6400 finder frames are left out. Each group is given to the panel of the plan
whose declination offset it matches (the mount's RA in the sidecars carries an offset of about 0.1 degrees
between finder and long frames, so RA is not used to name a panel; the plate solve places it later).
Per frame: 3-sigma clipped mean and scatter of each colour plane in the top-left corner and in a 12 x 8 grid of
blocks, the nucleus if it is in the frame, the as-shot white balance. Nothing is written but a table."""
import json
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from mcommon import *


def probe(fr):
    planes, ceil, meta = load_planes(fr['path'])
    G = (planes[1] + planes[2]) / 2
    corner = [clipped_stats(planes[p][CORNER]) for p in range(4)]
    meta['corner'] = [dict(clipped_mean=c[0], clipped_std=c[1]) for c in corner]
    meta['corner_green'] = clipped_stats(G[CORNER])[0]
    bs = 251
    meta['blocks'] = [[[clipped_stats(planes[p][i * bs:(i + 1) * bs:2, j * bs:(j + 1) * bs:2], k=2.5)[0] for j in range(W2 // bs)] for i in range(H2 // bs)] for p in range(4)]
    meta['median_plane'] = [float(np.median(planes[p][::4, ::4])) for p in range(4)]
    # the nucleus, if it is in this frame: the maximum of a wide blur of the median-filtered green, single values capped
    m5 = cv2.medianBlur(G, 5)
    c = np.clip(m5 - np.percentile(m5[::8, ::8], 5), 0, 1500)
    sm = cv2.GaussianBlur(c, (0, 0), 25)
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    meta['nucleus_peak_capped'] = float(sm[y, x])
    if sm[y, x] > 700 and 60 < x < W2 - 60 and 60 < y < H2 - 60:
        y0, x0 = y - 60, x - 60
        box = cv2.GaussianBlur(m5, (0, 0), 3)[y0:y + 60, x0:x + 60]; yy, xx = np.unravel_index(np.argmax(box), box.shape)
        meta['nucleus_sensor_xy'] = [2 * float(x0 + xx) + 0.5, 2 * float(y0 + yy) + 0.5]
    else:
        meta['nucleus_sensor_xy'] = None
    meta['ceiling_pixels'] = [int(ceil[p].sum()) for p in range(4)]
    return meta


if __name__ == '__main__':
    allf = frame_list()
    ok = [f for f in allf if f['exposure_s'] == EXPOSURE_S and f['iso'] == ISO]
    left = [f for f in allf if f not in ok]
    print(len(allf), 'stills in the window;', len(ok), 'at 30 s ISO 3200; left out:', [(f['stamp'], f['exposure_s'], f['iso']) for f in left])
    # groups by pointing
    groups = []
    for f in ok:
        if groups and abs(f['dec_deg'] - groups[-1][0]['dec_deg']) < 0.1 and abs(f['ra_deg'] - groups[-1][0]['ra_deg']) * np.cos(np.radians(41.3)) < 0.1 and tsec(f['t']) - tsec(groups[-1][-1]['t']) < 240:
            groups[-1].append(f)
        else:
            groups.append([f])
    assert len(groups) == len(PANELS), [len(g) for g in groups]
    for g, (name, e, n) in zip(groups, PANELS):
        dd = (np.mean([f['dec_deg'] for f in g]) - NUC_DEC) * 60
        assert abs(dd - n) < 1.5, (name, dd, n)
        for f in g: f['panel'] = name
        print('%-6s %2d frames %s .. %s  mount dec offset %+.1f arcmin (plan %+.1f)  mount ra %.3f' % (name, len(g), g[0]['stamp'][9:], g[-1]['stamp'][9:], dd, n, np.mean([f['ra_deg'] for f in g])))
    with ProcessPoolExecutor(8) as ex:
        metas = list(ex.map(probe, ok))
    out = []
    for f, m in zip(ok, metas):
        d = dict(f); d.update(m); out.append(d)
        b = np.array(m['blocks'][1])
        print('%s %-6s corner G %.1f R %.1f B %.1f std G1 %.1f | G1 blocks min %.0f med %.0f max %.0f | nucleus %s (peak %.0f) | wb %s flip %d alt %.1f' % (
            f['stamp'], f['panel'], m['corner_green'], m['corner'][0]['clipped_mean'], m['corner'][3]['clipped_mean'], m['corner'][1]['clipped_std'], b.min(), np.median(b), b.max(),
            None if m['nucleus_sensor_xy'] is None else np.round(m['nucleus_sensor_xy']).astype(int).tolist(), m['nucleus_peak_capped'], [int(v) for v in m['wb'][:3]], m['flip'], f['alt_deg']), flush=True)
    json.dump(dict(frames=out, left_out=left), open(W('m1.json'), 'w'), indent=1)
