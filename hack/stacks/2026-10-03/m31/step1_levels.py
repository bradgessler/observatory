"""Step 1: read every RAW in the window, check exposure and ISO in the sidecar, and measure in every frame:
the level in the same corner (3-sigma clipped mean of each colour plane in CORNER; clipped mean, not median,
because the RAW values step in 4 DN), block levels over the whole frame (for a look at the shape of the light),
where the nucleus is, how many pixels sit at the sensor's ceiling, the as-shot white balance and the flip flag.
Nothing is written but a table."""
import json, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

def probe(fr):
    planes, ceil, meta = load_planes(fr['path'])
    G = (planes[1] + planes[2]) / 2
    corner = [clipped_stats(planes[p][CORNER]) for p in range(4)]
    meta['corner'] = [dict(clipped_mean=c[0], clipped_std=c[1]) for c in corner]
    cg = clipped_stats(G[CORNER]); meta['corner_green'] = cg[0]
    corners = {}
    for nm, sl in (('top_left', CORNER), ('top_right', (slice(20, 320), slice(-320, -20))), ('bottom_left', (slice(-320, -20), slice(20, 320))), ('bottom_right', (slice(-320, -20), slice(-320, -20)))):
        corners[nm] = clipped_stats(G[sl])[0]
    meta['corners_green'] = corners
    # block levels of green, 8 x 12 blocks
    h, w = G.shape; bs = 251
    meta['blocks_green'] = [[clipped_stats(G[i * bs:(i + 1) * bs:2, j * bs:(j + 1) * bs:2], k=2.5)[0] for j in range(w // bs)] for i in range(h // bs)]
    # nucleus: the maximum of a wide blur of the median-filtered green with single values capped, so a star cannot win
    m5 = cv2.medianBlur(G, 5)
    c = np.clip(m5 - cg[0], 0, 1500)
    sm = cv2.GaussianBlur(c, (0, 0), 25)
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    y0, x0 = max(y - 60, 0), max(x - 60, 0)
    box = cv2.GaussianBlur(m5, (0, 0), 3)[y0:y + 60, x0:x + 60]; yy, xx = np.unravel_index(np.argmax(box), box.shape)
    nx, ny = x0 + xx, y0 + yy
    meta['nucleus_sensor_xy'] = [2 * float(nx) + 0.5, 2 * float(ny) + 0.5]
    r = 40
    meta['nucleus_max_dn_above_black'] = [float(cv2.medianBlur(planes[p], 3)[ny - r:ny + r, nx - r:nx + r].max()) for p in range(4)]
    meta['nucleus_rawmax_dn_above_black'] = [float(planes[p][ny - r:ny + r, nx - r:nx + r].max()) for p in range(4)]
    meta['nucleus_ceiling_pixels'] = [int(ceil[p][ny - r:ny + r, nx - r:nx + r].sum()) for p in range(4)]
    meta['ceiling_pixels'] = [int(ceil[p].sum()) for p in range(4)]
    return meta

if __name__ == '__main__':
    frames = frame_list()
    ok = [f for f in frames if f['exposure_s'] == EXPOSURE_S and f['iso'] == ISO]
    print(len(frames), 'in window,', len(ok), 'at 20 s ISO 3200; others:', [(f['stamp'], f['exposure_s'], f['iso']) for f in frames if f not in ok])
    with ProcessPoolExecutor(8) as ex:
        metas = list(ex.map(probe, ok))
    out = []
    for f, m in zip(ok, metas):
        d = dict(f); d.update(m); out.append(d)
        print(f['stamp'], 'corner G %.1f  R %.1f B %.1f  std G1 %.1f | corners %s | nucleus %s max %s raw %s ceil %s | wb %s flip %d allceil %d alt %.1f' % (
            m['corner_green'], m['corner'][0]['clipped_mean'], m['corner'][3]['clipped_mean'], m['corner'][1]['clipped_std'], ' '.join('%.0f' % v for v in m['corners_green'].values()),
            np.round(m['nucleus_sensor_xy']).astype(int).tolist(), [int(v) for v in m['nucleus_max_dn_above_black']], [int(v) for v in m['nucleus_rawmax_dn_above_black']], sum(m['nucleus_ceiling_pixels']), [int(v) for v in m['wb'][:3]], m['flip'], sum(m['ceiling_pixels']), f['alt_deg']))
    json.dump(dict(frames=out, all_in_window=frames), open(W('step1.json'), 'w'), indent=1)
