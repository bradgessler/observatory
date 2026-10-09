"""Step 3: stars in every frame (green planes averaged, half-size grid): centroids, fluxes, widths, elongation.
The detector of the M31 runs (m3_stars.py): the smooth light (nebula, sky, cloud glow) is taken off first (plane
shrunk 8x, 5x5 median, Gaussian sigma 2, grown back), detection on the remainder blurred with sigma 2.5 in units
of the local noise (variance = a + b x level fitted to the frame's own 64 px blocks), 6 sigma, blobs of 8 px or
more. Gaussian-windowed centroid; 28 px (sensor) aperture, ring 38 to 54 px for the local level.
In a nebula some 'stars' are knots of nebula: they are fixed on the sky like stars, and the registration and the
transparency use medians over many, with rejection; within CORE_RADIUS of the brightest nebula nothing is used."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *
import prep

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
    if not np.isfinite(ann).all() or not np.isfinite(t).all(): return None
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


def detect_image(G, P=None, core=None, nsig=6.0):
    """Stars of a green half-grid image G. P: the four planes (for the ceiling test), core: brightest nebula in sensor px or None."""
    bg = smooth_light(G); D = G - bg
    bs = 64; h, w = G.shape; ny, nx = h // bs, w // bs
    Db = D[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1)
    Lb = bg[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).mean((1, 3)).ravel()
    fin = np.isfinite(Db).all(1) & np.isfinite(Lb)
    Db = Db[fin]; Lb = Lb[fin]
    med = np.median(Db, axis=1); sd = 1.4826 * np.median(np.abs(Db - med[:, None]), axis=1)
    A = np.stack([np.ones_like(Lb), Lb], 1); keep = np.ones(len(Lb), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], sd[keep] ** 2, rcond=None); r = sd ** 2 - A @ co; s = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * s
    var = np.maximum(co[0] + co[1] * np.maximum(bg, 0), max(0.05 * float(np.median(sd)) ** 2, 1e-6))
    sm = cv2.GaussianBlur(D, (0, 0), 2.5)
    z = sm / np.sqrt(var)
    m, s, _ = clipped_stats(z[::2, ::2])
    lab_n, lab, stats, cent = cv2.connectedComponentsWithStats((z > m + nsig * s).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, lab_n):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(D, float(cent[i][0]), float(cent[i][1]))
        if r is None: continue
        if np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        r['area'] = int(stats[i, cv2.CC_STAT_AREA])
        xi, yi = int(round(r['x'])), int(round(r['y']))
        if P is not None:
            cut = P[:, yi - AP:yi + AP + 1, xi - AP:xi + AP + 1]
            r['plane_max'] = [float(c.max()) for c in cut]
        r['level'] = float(bg[yi, xi])
        stars.append(r)
    stars.sort(key=lambda s_: -s_['flux']); keep_ = []
    for s_ in stars:
        if all(np.hypot(s_['x'] - k['x'], s_['y'] - k['y']) > 6 for k in keep_): keep_.append(s_)
    xy = np.array([[k['x'], k['y']] for k in keep_]).reshape(-1, 2)
    for i, k in enumerate(keep_):
        k['r_core'] = float(np.hypot(2 * k['x'] + 0.5 - core[0], 2 * k['y'] + 0.5 - core[1])) if core is not None else 1e6     # sensor px
        d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9; k['nearest'] = float(2 * d.min()) if len(keep_) > 1 else 1e6               # sensor px
        if P is not None: k['saturated'] = bool(max(k['plane_max']) >= CEILING_RAW - 512 - 1500)
    return keep_, dict(a=float(co[0]), b=float(co[1])), float(s)


def detect(stamp):
    P = prep.load_repaired(stamp)
    G = (P[1] + P[2]) / 2
    stars, nm, zs = detect_image(G, P, prep.s1()[stamp]['core_sensor_xy'])
    return dict(stamp=stamp, z_sigma=zs, noise_model=nm, stars=stars)


if __name__ == '__main__':
    s1 = prep.s1(); stamps = sorted(s1)
    old = {}
    if os.path.exists(W('s3_stars.json')) and 'fresh' not in sys.argv:
        old = {r['stamp']: r for r in json.load(open(W('s3_stars.json')))}
    todo = [s for s in stamps if s not in old]
    with ProcessPoolExecutor(8) as ex:
        new = list(ex.map(detect, todo))
    res = sorted(list(old.values()) + new, key=lambda r: r['stamp'])
    res = [r for r in res if r['stamp'] in s1]
    json.dump(res, open(W('s3_stars.json'), 'w'))
    for r in res:
        b = [k for k in r['stars'] if not k['saturated']][:2]
        print(r['stamp'], '%-7s' % s1[r['stamp']]['set'], 'n', len(r['stars']), 'sat', sum(k['saturated'] for k in r['stars']), 'noise a %.0f b %.2f' % (r['noise_model']['a'], r['noise_model']['b']),
              ' | '.join('(%.1f,%.1f) F=%.0f pk=%.0f el=%.2f hfr=%.1f' % (s['x'], s['y'], s['flux'], s['peak'], s['elong'], s['hfr']) for s in b))
