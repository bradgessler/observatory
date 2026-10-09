"""Step 2: stars in every frame (the two green planes averaged, plane grid), Gaussian-windowed centroids, aperture
flux, half-flux radius, (after a smooth background from 64 px block medians is taken off) second moments (width and elongation), whether any colour plane touches the sensor ceiling.
Copied from this night's m57/step2_stars.py (itself from 2026-10-03/ngc7662 with a saturation flag added)."""
import os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

AP = 14      # aperture radius, plane px (28 sensor px, 10.8 arcsec)
SW = 5.0     # Gaussian window sigma for centroids, plane px
BLK = 64     # block size of the background taken off before finding stars, plane px


def measure(G, x, y, sw=SW, ap=AP):
    """Windowed centroid (iterated), aperture flux, second moments in the aperture."""
    h, w = G.shape
    for _ in range(12):
        xi, yi = int(round(x)), int(round(y)); r = int(3 * sw) + 2
        if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
        t = G[yi - r:yi + r + 1, xi - r:xi + r + 1]
        yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
        wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sw * sw)) * t
        s = wgt.sum()
        if s <= 0: return None
        nx = x + 2 * ((wgt * (xx - x)).sum() / s); ny = y + 2 * ((wgt * (yy - y)).sum() / s)
        d = np.hypot(nx - x, ny - y); x, y = nx, ny
        if d < 0.002: break
    xi, yi = int(round(x)), int(round(y)); r = 28
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
    t = G[yi - r:yi + r + 1, xi - r:xi + r + 1]
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
    rr = np.hypot(xx - x, yy - y)
    ann = t[(rr > 19) & (rr < 27)]
    lb = float(np.median(ann))
    a = rr <= ap; v = (t - lb) * a
    flux = float(v.sum())
    if flux <= 0: return None
    mx = (v * (xx - x)).sum() / flux; my = (v * (yy - y)).sum() / flux
    mxx = (v * (xx - x - mx) ** 2).sum() / flux; myy = (v * (yy - y - my) ** 2).sum() / flux; mxy = (v * (xx - x - mx) * (yy - y - my)).sum() / flux
    tr, det = mxx + myy, mxx * myy - mxy * mxy
    disc = max(tr * tr / 4 - det, 0) ** 0.5
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    order = np.argsort(rr[a]); cum = np.cumsum((t - lb)[a][order]); hfr = float(rr[a][order][np.searchsorted(cum, flux / 2)]) if cum[-1] > 0 else None
    return dict(x=float(x), y=float(y), flux=flux, peak=float(t[a].max() - lb), local_bg=lb,
                sig_major=float(max(l1, 0) ** 0.5), sig_minor=float(max(l2, 1e-9) ** 0.5), elong=float((max(l1, 1e-9) / max(l2, 1e-9)) ** 0.5),
                theta=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))), hfr=hfr)


def detect(args):
    stamp, bg = args
    P = np.load(os.path.join(WORK, 'planes', stamp + '.npy'))
    G = (P[1] + P[2]) / 2
    # the sky has a strong gradient (light pollution, about 50 DN across the frame in green): for finding and measuring
    # stars only, take off a smooth background made from 64 px block medians (the annulus does the rest)
    bh, bw = h2 // BLK, w2 // BLK
    blocks = np.median(G[:bh * BLK, :bw * BLK].reshape(bh, BLK, bw, BLK), axis=(1, 3)).astype(np.float32)
    G = G - cv2.resize(cv2.medianBlur(blocks, 3), (w2, h2), interpolation=cv2.INTER_LINEAR)
    sm = cv2.GaussianBlur(G, (0, 0), 2.5)
    m, s, _ = clipped_stats(sm[::2, ::2])
    lab_n, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m + 6 * s).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, lab_n):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(G, float(cent[i][0]), float(cent[i][1]))
        if r is None: continue
        if np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        r['area'] = int(stats[i, cv2.CC_STAT_AREA])
        xi, yi = int(round(r['x'])), int(round(r['y']))
        cut = P[:, yi - AP:yi + AP + 1, xi - AP:xi + AP + 1]
        r['plane_max'] = [float(c.max()) for c in cut]
        r['saturated'] = bool(any(c.max() + bg[k] >= SAT_DN for k, c in enumerate(cut)))
        yy, xx = np.mgrid[-AP:AP + 1, -AP:AP + 1]; a = np.hypot(xx, yy) <= AP
        r['plane_flux'] = [float((c[a] - np.median(c[~a])).sum()) for c in cut]
        stars.append(r)
    stars.sort(key=lambda s_: -s_['flux']); keep = []
    for s_ in stars:
        if all(np.hypot(s_['x'] - k['x'], s_['y'] - k['y']) > 6 for k in keep): keep.append(s_)
    return dict(stamp=stamp, sm_sigma=s, stars=keep)


if __name__ == '__main__':
    st1 = jload('step1.json')
    args = [(f['stamp'], [b['clipped_mean'] for b in f['bg_provisional']]) for f in st1['frames']]
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(detect, args))
    jsave(res, 'step2_stars.json')
    for r in res:
        b = [s for s in r['stars'] if not s['saturated']][:3]
        print(r['stamp'], 'n %4d' % len(r['stars']), 'sat %2d' % sum(s['saturated'] for s in r['stars']), 'smσ %.2f' % r['sm_sigma'],
              ' | '.join('(%.0f,%.0f) F=%.0f el=%.2f hfd=%.1fpx' % (s['x'], s['y'], s['flux'], s['elong'], 4 * s['hfr']) for s in b))
