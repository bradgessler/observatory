"""Step 1: read every RAW in the window and measure, writing nothing but a table (step1.json):
exposure and ISO from the RAW's own EXIF (and the sidecar's, as a check); the level in each corner of each colour
plane (3-sigma clipped mean: the RAW values step in 4 DN, so a mean, not a median); where the nucleus is (the
maximum of a wide blur of the median-filtered green with values capped, so that a star cannot win); the brightest
pixels at the nucleus and how many pixels sit at the sensor's ceiling; the as-shot white balance; the flip flag."""
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *


def probe(fr):
    planes, ceil, meta = load_planes(fr['path'])
    meta['exif_exposure_s'], meta['exif_iso'] = raw_exif(fr['path'])
    G = (planes[1] + planes[2]) / 2
    meta['corners'] = {}
    for nm, sl in corners():
        meta['corners'][nm] = dict(green=clipped_stats(G[sl])[0], planes=[clipped_stats(planes[p][sl]) [0] for p in range(4)],
                                   std=[clipped_stats(planes[p][sl])[1] for p in range(4)])
    # nucleus
    m5 = cv2.medianBlur(G, 5)
    base = min(c['green'] for c in meta['corners'].values())
    sm = cv2.GaussianBlur(np.clip(m5 - base, 0, 1500), (0, 0), 25)
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    y0, x0 = max(y - 60, 0), max(x - 60, 0)
    box = cv2.GaussianBlur(m5, (0, 0), 3)[y0:y + 60, x0:x + 60]; yy, xx = np.unravel_index(np.argmax(box), box.shape)
    nx, ny = x0 + xx, y0 + yy
    meta['nucleus_sensor_xy'] = [2 * float(nx) + 0.5, 2 * float(ny) + 0.5]
    r = 40
    meta['nucleus_max_dn_above_black_med3'] = [float(cv2.medianBlur(planes[p], 3)[ny - r:ny + r, nx - r:nx + r].max()) for p in range(4)]
    meta['nucleus_ceiling_pixels'] = [int(ceil[p][ny - r:ny + r, nx - r:nx + r].sum()) for p in range(4)]
    meta['ceiling_pixels'] = [int(ceil[p].sum()) for p in range(4)]
    # coarse shape of the light: 8 x 12 blocks of green
    bs = 251; h, w = G.shape
    meta['blocks_green'] = [[round(clipped_stats(G[i * bs:(i + 1) * bs:2, j * bs:(j + 1) * bs:2], k=2.5)[0], 1) for j in range(w // bs)] for i in range(h // bs)]
    return meta


if __name__ == '__main__':
    frames = frame_list()
    with ProcessPoolExecutor(WORKERS) as ex:
        metas = list(ex.map(probe, frames))
    out = []
    for f, m in zip(frames, metas):
        d = dict(f); d.update(m); out.append(d)
        c = m['corners']; dark = min(c, key=lambda k: c[k]['green'])
        print(f['stamp'], 'seq', f['seq'], 'exif %.0fs ISO %d (sidecar %s s ISO %s)' % (m['exif_exposure_s'], m['exif_iso'], f['sidecar_exposure_s'], f['sidecar_iso']),
              '| corners G', ' '.join('%s %.1f' % (k[:1] + k.split('_')[1][:1], v['green']) for k, v in c.items()), 'darkest', dark,
              '| nucleus', np.round(m['nucleus_sensor_xy']).astype(int).tolist(), 'max', [int(v) for v in m['nucleus_max_dn_above_black_med3']], 'ceil', sum(m['nucleus_ceiling_pixels']),
              '| wb', [int(v) for v in m['wb'][:3]], 'flip', m['flip'], 'rawmax', int(m['rawmax']), 'allceil', sum(m['ceiling_pixels']), 'since slew', f['since_slew_s'], flush=True)
    jdump(dict(frames=out), 'step1.json')
