"""(Copied from hack/stacks/2026-10-03/m31/measure.py; called here with the lengths halved for the colour-cell grid.)
Star measurements on the sensor grid (the stack, or one frame resampled to the same grid).
Same method as step 2, with every length doubled because the grid is twice as fine as a colour plane."""
import numpy as np, cv2

AP, SW, ANN = 28, 10.0, (38, 54)      # aperture radius, centroid window sigma, sky ring; sensor px

def star(G, x, y, ap=AP, sw=SW, ann=ANN):
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
    xi, yi = int(round(x)), int(round(y)); r = ann[1] + 2
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
    t = G[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float64)
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
    rr = np.hypot(xx - x, yy - y)
    lb = float(np.median(t[(rr > ann[0]) & (rr < ann[1])]))
    a = rr <= ap; v = (t - lb) * a
    flux = float(v.sum())
    if flux <= 0: return None
    mx = (v * (xx - x)).sum() / flux; my = (v * (yy - y)).sum() / flux
    mxx = (v * (xx - x - mx) ** 2).sum() / flux; myy = (v * (yy - y - my) ** 2).sum() / flux; mxy = (v * (xx - x - mx) * (yy - y - my)).sum() / flux
    tr, det = mxx + myy, mxx * myy - mxy * mxy
    disc = max(tr * tr / 4 - det, 0) ** 0.5
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    order = np.argsort(rr[a]); cum = np.cumsum((t - lb)[a][order]); hfr = float(rr[a][order][np.searchsorted(cum, flux / 2)])
    # FWHM from the ring-median profile (first radius where it falls below half the central value)
    prof = [float(np.median(t[(rr >= k - 0.5) & (rr < k + 0.5)]) - lb) for k in range(0, ap)]
    pk = float(t[rr <= 1.5].mean() - lb); half = next((k for k, v_ in enumerate(prof) if v_ < pk / 2), None)
    fwhm = None
    if half is not None and half > 0:
        fwhm = 2 * (half - 1 + (prof[half - 1] - pk / 2) / max(prof[half - 1] - prof[half], 1e-9))
    return dict(x=float(x), y=float(y), flux=flux, peak=pk, local_bg=lb, hfd=2 * hfr, fwhm=fwhm,
                sig_major=float(max(l1, 0) ** 0.5), sig_minor=float(max(l2, 1e-9) ** 0.5), elong=float((max(l1, 1e-9) / max(l2, 1e-9)) ** 0.5),
                theta=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))))

def count_stars(G, sky_patch, k=5.0, s1=4.0, s2=16.0, win=9):
    """Stars as local maxima of a difference of Gaussians (sigma s1 minus sigma s2: point sources kept, the
    cluster's smooth glow and the sky removed), above k times the robust scatter of that image in a sky patch."""
    d = cv2.GaussianBlur(G, (0, 0), s1) - cv2.GaussianBlur(G, (0, 0), s2)
    p = d[sky_patch]; med = np.median(p); sig = 1.4826 * np.median(np.abs(p - med))
    mx = cv2.dilate(d, np.ones((win, win), np.uint8))
    pk = (d == mx) & (d > med + k * sig)
    ys, xs = np.nonzero(pk)
    return np.stack([xs, ys], 1), d[ys, xs], float(sig)
