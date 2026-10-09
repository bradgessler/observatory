"""Step 3 (as hack/stacks/2026-10-03/m31/step3_stars.py, unchanged in method): stars in every frame (green planes averaged, half-size grid): centroids, fluxes, widths, elongation.
The galaxy is under every star, so the smooth light is taken off first: the green plane shrunk 8 times (block
mean), 5x5 median there (40 plane px, a star is under one pixel of it), Gaussian sigma 2, grown back. Detection is on the
remainder, blurred with sigma 2.5, in units of the local noise (noise^2 = a + b x level, fitted to the frame's
own blocks) so that the bright bulge does not flood the list. Each star gets its distance from the nucleus, the
distance to its nearest neighbour and whether it is within 1500 DN of the ceiling."""
import json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
AP = 14      # aperture radius, plane px (28 sensor px)
SW = 5.0     # Gaussian window sigma for centroids, plane px

def smooth_light(G):
    small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 2)
    return cv2.resize(small, (G.shape[1], G.shape[0]), interpolation=cv2.INTER_CUBIC)

def measure(G, x, y, sw=SW, ap=AP):
    """Windowed centroid (iterated), aperture flux, second moments in the aperture. G has the smooth light removed."""
    h, w = G.shape
    for _ in range(12):
        xi, yi = int(round(x)), int(round(y)); r = int(3 * sw) + 2
        if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
        t = G[yi - r:yi + r + 1, xi - r:xi + r + 1]
        yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
        wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sw * sw)) * np.clip(t, 0, None)
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
    order = np.argsort(rr[a]); cum = np.cumsum((t - lb)[a][order]); hfr = float(rr[a][order][min(np.searchsorted(cum, flux / 2), a.sum() - 1)]) if cum[-1] > 0 else None
    return dict(x=float(x), y=float(y), flux=flux, peak=float(t[a].max() - lb), local_bg=lb,
                sig_major=float(max(l1, 0) ** 0.5), sig_minor=float(max(l2, 1e-9) ** 0.5), elong=float((max(l1, 1e-9) / max(l2, 1e-9)) ** 0.5),
                theta=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))), hfr=hfr)

def detect(stamp):
    P = np.load(W('planes/' + stamp + '.npy'))
    G = (P[1] + P[2]) / 2
    bg = smooth_light(G); D = G - bg
    # noise model from the frame's own blocks: variance of the remainder against the smooth level
    bs = 64; h, w = G.shape; ny, nx = h // bs, w // bs
    Db = D[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1)
    Lb = bg[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).mean((1, 3)).ravel()
    med = np.median(Db, axis=1); sd = 1.4826 * np.median(np.abs(Db - med[:, None]), axis=1)
    A = np.stack([np.ones_like(Lb), Lb], 1); keep = np.ones(len(Lb), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], sd[keep] ** 2, rcond=None); r = sd ** 2 - A @ co; s = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * s
    var = np.maximum(co[0] + co[1] * np.maximum(bg, 0), 100.0)
    sm = cv2.GaussianBlur(D, (0, 0), 2.5)
    z = sm / np.sqrt(var)
    m, s, _ = clipped_stats(z[::2, ::2])
    lab_n, lab, stats, cent = cv2.connectedComponentsWithStats((z > m + 6 * s).astype(np.uint8), connectivity=8)
    nuc = s1[stamp]['nucleus_sensor_xy']
    stars = []
    for i in range(1, lab_n):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(D, float(cent[i][0]), float(cent[i][1]))
        if r is None: continue
        if np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        r['area'] = int(stats[i, cv2.CC_STAT_AREA])
        xi, yi = int(round(r['x'])), int(round(r['y']))
        cut = P[:, yi - AP:yi + AP + 1, xi - AP:xi + AP + 1]
        r['plane_max'] = [float(c.max()) for c in cut]
        r['level'] = float(bg[yi, xi])
        stars.append(r)
    stars.sort(key=lambda s_: -s_['flux']); keep_ = []
    for s_ in stars:
        if all(np.hypot(s_['x'] - k['x'], s_['y'] - k['y']) > 6 for k in keep_): keep_.append(s_)
    xy = np.array([[k['x'], k['y']] for k in keep_])
    for i, k in enumerate(keep_):
        k['r_nucleus'] = float(np.hypot(2 * k['x'] + 0.5 - nuc[0], 2 * k['y'] + 0.5 - nuc[1]))     # sensor px
        d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9; k['nearest'] = float(2 * d.min())               # sensor px
        k['saturated'] = bool(max(k['plane_max']) >= CEILING_RAW - 512 - 1500)
    return dict(stamp=stamp, z_sigma=s, noise_model=dict(a=float(co[0]), b=float(co[1])), stars=keep_)

if __name__ == '__main__':
    stamps = sorted(s1)
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(detect, stamps))
    json.dump(res, open(W('step3_stars.json'), 'w'))
    for r in res:
        b = [k for k in r['stars'] if not k['saturated']][:2]
        print(r['stamp'], 'n', len(r['stars']), 'sat', sum(k['saturated'] for k in r['stars']), 'noise a %.0f b %.2f' % (r['noise_model']['a'], r['noise_model']['b']),
              ' | '.join('(%.1f,%.1f) F=%.0f pk=%.0f el=%.2f hfr=%.1f' % (s['x'], s['y'], s['flux'], s['peak'], s['elong'], s['hfr']) for s in b))
