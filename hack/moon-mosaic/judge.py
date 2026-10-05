"""One line of numbers for a stack, so variants can be compared fairly: the blur across the sunlit
limb (an error-function fit, in arcsec), and at three tiles the finest detail that stands above the
noise, with the noise floor. Usage: judge.py stack-a.npz [stack-b.npz ...]"""
import sys, numpy as np, cv2
from scipy.optimize import curve_fit
from scipy.special import erfc
import moonlib
TILES = dict(copernicus=(900, 700), south=(840, 1900), apennines=(1150, 640)); N = 384

def limit(t):
    t = t / t.mean() - 1; w = np.hanning(N)[:, None] * np.hanning(N)[None, :]
    P = np.abs(np.fft.fftshift(np.fft.fft2(t * w))) ** 2
    yy, xx = np.indices(P.shape); rr = np.hypot(yy - N // 2, xx - N // 2).astype(int)
    prof = np.bincount(rr.ravel(), P.ravel()) / np.maximum(np.bincount(rr.ravel()), 1)
    floor = np.median(prof[int(N * 0.42):N // 2]); k = np.where(prof[2:N // 2] / floor > 2.0)[0].max() + 2
    return N / k * moonlib.ARCSEC_PER_PX, float(np.sqrt(floor))

def limb(g):
    mask = (cv2.GaussianBlur(g, (0, 0), 3) > 0.05)
    lit = (cv2.GaussianBlur(g, (0, 0), 2) > 0.5 * np.percentile(g[mask], 50)).astype(np.uint8)
    cnt = max(cv2.findContours(lit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)[:, 0, :].astype(np.float64)
    def c3(p):
        A = np.c_[2 * p, np.ones(len(p))]; b = (p ** 2).sum(1); cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
        return cx, cy, np.sqrt(max(c + cx * cx + cy * cy, 0))
    rng = np.random.default_rng(7); best = (0, None)
    for _ in range(4000):
        cx, cy, r = c3(cnt[rng.choice(len(cnt), 3, replace=False)])
        if 880 <= r * moonlib.ARCSEC_PER_PX <= 1010:
            on = np.abs(np.hypot(cnt[:, 0] - cx, cnt[:, 1] - cy) - r) < 1.5
            if on.sum() > best[0]: best = (int(on.sum()), on)
    p = cnt[best[1]]; cx, cy, r = c3(p)
    ang = np.arctan2(p[:, 1] - cy, p[:, 0] - cx); a0, a1 = np.percentile(ang, [3, 97]); rs = np.arange(-14, 14.01, 0.25); profs = []
    for a in np.linspace(a0, a1, 1200):
        xs = (cx + (r + rs) * np.cos(a)).astype(np.float32)[None]; ys = (cy + (r + rs) * np.sin(a)).astype(np.float32)[None]
        pr = cv2.remap(g, xs, ys, cv2.INTER_CUBIC)[0]; lo, hi = pr[-8:].mean(), pr[:8].mean()
        if 0.1 < hi < 0.9 and lo < 0.2 * hi:
            n = (pr - lo) / (hi - lo); k = np.argmin(np.abs(n - 0.5)); profs.append(np.interp(rs, rs - rs[k], n))
    esf = np.mean(profs, 0)
    (r0, sig), _ = curve_fit(lambda x, r0, s: 0.5 * erfc((x - r0) / (np.sqrt(2) * s)), rs, esf, p0=(0, 1.5))
    return 2.355 * abs(sig) * moonlib.ARCSEC_PER_PX, len(profs)

for path in sys.argv[1:]:
    g = np.load(path)["img"][:, :, 1]
    fwhm, n = limb(g)
    parts = []
    for name, (x, y) in TILES.items():
        lim, floor = limit(g[y:y + N, x:x + N].astype(np.float64)); parts.append("%s %.2f\" (noise %.2f)" % (name, lim, floor))
    print("%-34s limb blur %.2f\"   detail: %s" % (path, fwhm, "   ".join(parts)))
