"""Step 2: stars in every frame (green planes, half-size grid), centroids, widths, elongation.
Every star also gets its distance from the cluster centre, the distance to its nearest detected neighbour and
whether any of its pixels sat at the sensor ceiling, so that later steps can leave out the crowded core,
blends and saturated stars."""
import json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

st1 = json.load(open(W('step1.json')))
CL = {f['stamp']: f['cluster_sensor_xy'] for f in st1['frames']}
BGMAX = {f['stamp']: max(b['clipped_mean'] for b in f['bg']) for f in st1['frames']}
AP = 14      # aperture radius, plane px (28 sensor px)
SW = 5.0     # Gaussian window sigma for centroids, plane px

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
    # half-flux radius
    order = np.argsort(rr[a]); cum = np.cumsum((t - lb)[a][order]); hfr = float(rr[a][order][np.searchsorted(cum, flux / 2)]) if cum[-1] > 0 else None
    return dict(x=float(x), y=float(y), flux=flux, peak=float(t[a].max() - lb), local_bg=lb,
                sig_major=float(max(l1, 0) ** 0.5), sig_minor=float(max(l2, 1e-9) ** 0.5), elong=float((max(l1, 1e-9) / max(l2, 1e-9)) ** 0.5),
                theta=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))), hfr=hfr)

def detect(stamp):
    P = np.load(W('planes/' + stamp + '.npy'))
    G = (P[1] + P[2]) / 2
    sm = cv2.GaussianBlur(G, (0, 0), 2.5)
    m, s, _ = clipped_stats(sm[::2, ::2])
    lab_n, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m + 6 * s).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, lab_n):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        x0, y0, w, h = stats[i, :4]
        sub = sm[y0:y0 + h, x0:x0 + w] * (lab[y0:y0 + h, x0:x0 + w] == i)
        py, px = np.unravel_index(np.argmax(sub), sub.shape)
        r = measure(G, float(cent[i][0]), float(cent[i][1]))
        if r is None: continue
        if np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        r['area'] = int(stats[i, cv2.CC_STAT_AREA])
        # saturation and colour from the four planes
        xi, yi = int(round(r['x'])), int(round(r['y']))
        cut = P[:, yi - AP:yi + AP + 1, xi - AP:xi + AP + 1]
        r['plane_max'] = [float(c.max()) for c in cut]
        yy, xx = np.mgrid[-AP:AP + 1, -AP:AP + 1]; a = np.hypot(xx, yy) <= AP
        r['plane_flux'] = [float((c[a]).sum()) for c in cut]
        stars.append(r)
    # merge duplicates (two components converging on the same star)
    stars.sort(key=lambda s: -s['flux']); keep = []
    for s_ in stars:
        if all(np.hypot(s_['x'] - k['x'], s_['y'] - k['y']) > 6 for k in keep): keep.append(s_)
    cl = CL[stamp]; xy = np.array([[k['x'], k['y']] for k in keep])
    for i, k in enumerate(keep):
        k['r_cluster'] = float(np.hypot(2 * k['x'] + 0.5 - cl[0], 2 * k['y'] + 0.5 - cl[1]))       # sensor px
        d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9; k['nearest'] = float(2 * d.min())               # sensor px
        k['saturated'] = bool(max(k['plane_max']) + BGMAX[stamp] >= CEILING_RAW - 512 - 1500)      # within 1500 DN of the ceiling counts
    return dict(stamp=stamp, sm_sigma=s, stars=keep)

if __name__ == '__main__':
    stamps = [f['stamp'] for f in st1['frames']]
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(detect, stamps))
    json.dump(res, open(W('step2_stars.json'), 'w'))
    for r in res:
        b = [k for k in r['stars'] if k['r_cluster'] > CORE_RADIUS and not k['saturated']][:3]
        print(r['stamp'], 'n', len(r['stars']), 'outside core', sum(k['r_cluster'] > CORE_RADIUS for k in r['stars']), 'sat', sum(k['saturated'] for k in r['stars']), 'smσ %.2f' % r['sm_sigma'], ' | '.join('(%.1f,%.1f) F=%.0f pk=%.0f el=%.2f sig=%.2f/%.2f hfr=%.1f max=%s' % (s['x'], s['y'], s['flux'], s['peak'], s['elong'], s['sig_major'], s['sig_minor'], s['hfr'], int(max(s['plane_max']))) for s in b))
