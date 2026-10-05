"""The blur's true shape, measured from the Moon's sunlit limb in the stack itself.

Across the limb the picture goes from lit ground to black sky: a step, seen through the blur. The
slope of that edge is the blur's profile seen side-on (its line spread). For a blur that is the same
in every direction, the spectrum of that line spread IS the blur's spectrum along any direction
(the projection-slice theorem), so the 2-D blur follows by turning that curve about the origin and
transforming back. A smooth two-number curve exp(-(f/f0)^p) is fitted to the measured spectrum where
it stands above its own noise (p = 2 would be a Gaussian; the air alone gives 5/3), so the blur has
no noise of its own.

MOON_ARC=a0:a1 (degrees on the screen, 0 = right, 90 = down) keeps only that stretch of the limb:
this night the blur was not the same all along it. MOON_LIMB=measured.json takes the limb circle
from measure.py instead of fitting it again.

Usage: psf.py stack.npz scale out.npz     (scale: pixels per working pixel, 2 for the fine grid)
"""
import os, sys, json, numpy as np, cv2
from scipy.optimize import curve_fit
import moonlib
z = np.load(sys.argv[1]); g = z["img"][:, :, 1]; K = float(sys.argv[2]); ARC = moonlib.ARCSEC_PER_PX / K
mask = (cv2.GaussianBlur(g, (0, 0), 3 * K) > 0.05)
lit = (cv2.GaussianBlur(g, (0, 0), 2 * K) > 0.5 * np.percentile(g[mask], 50)).astype(np.uint8)
cnt = max(cv2.findContours(lit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)[:, 0, :].astype(np.float64)
def c3(p):
    A = np.c_[2 * p, np.ones(len(p))]; b = (p ** 2).sum(1); cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    return cx, cy, np.sqrt(max(c + cx * cx + cy * cy, 0))
rng = np.random.default_rng(7); best = (0, None)
for _ in range(4000):
    cx, cy, r = c3(cnt[rng.choice(len(cnt), 3, replace=False)])
    if 880 <= r * ARC <= 1010:
        on = np.abs(np.hypot(cnt[:, 0] - cx, cnt[:, 1] - cy) - r) < 1.5 * K
        if on.sum() > best[0]: best = (int(on.sum()), on)
p = cnt[best[1]]; cx, cy, r = c3(p)
if os.environ.get("MOON_LIMB"):
    ml = json.load(open(os.environ["MOON_LIMB"])); (cx, cy), r = ml["moon_centre_px"], ml["moon_radius_px"]
ang = np.arctan2(p[:, 1] - cy, p[:, 0] - cx); a0, a1 = np.percentile(ang, [3, 97])
if os.environ.get("MOON_ARC"):
    a0, a1 = [np.radians(float(v)) for v in os.environ["MOON_ARC"].split(":")]
d = 0.25; half = 24 * K; rs = np.arange(-half, half + 1e-6, d); profs = []
for a in np.linspace(a0, a1, 2400):
    xs = (cx + (r + rs) * np.cos(a)).astype(np.float32)[None]; ys = (cy + (r + rs) * np.sin(a)).astype(np.float32)[None]
    pr = cv2.remap(g, xs, ys, cv2.INTER_CUBIC)[0]; lo, hi = pr[-int(8 * K / d):].mean(), pr[:int(8 * K / d)].mean()
    if 0.1 < hi < 0.9 and lo < 0.2 * hi:
        n = (pr - lo) / (hi - lo); k = np.argmin(np.abs(n - 0.5)); profs.append(np.interp(rs, rs - rs[k], n))
esf = np.mean(profs, 0)
lsf = -np.gradient(esf, d); lsf *= np.hanning(len(lsf)); lsf /= lsf.sum() * d
F = np.abs(np.fft.rfft(np.fft.ifftshift(lsf))) * d; f = np.fft.rfftfreq(len(lsf), d)      # cycles per pixel
use = (f > 0) & (F > 0.03) & (f < f[np.argmax(F < 0.03)] if (F < 0.03).any() else True)
(f0, pw), _ = curve_fit(lambda x, f0, pw: np.exp(-(x / f0) ** pw), f[use], F[use], p0=(0.05 * 2 / K, 1.7), bounds=([1e-3, 1.0], [1.0, 2.5]))
# the 2-D blur: the fitted curve turned about the origin, transformed back
N = int(64 * K) | 1; fy, fx = np.meshgrid(np.fft.fftfreq(N), np.fft.fftfreq(N), indexing="ij")
psf = np.real(np.fft.fftshift(np.fft.ifft2(np.exp(-(np.hypot(fx, fy) / f0) ** pw)))); psf = np.clip(psf, 0, None); psf /= psf.sum()
prof = psf[N // 2, N // 2:]; fwhm = 2 * np.interp(0.5 * prof[0], prof[::-1], np.arange(len(prof))[::-1])
gauss_f0 = None
np.savez(sys.argv[3], psf=psf.astype(np.float32), f0=f0, power=pw, esf=esf, rs=rs, mtf_f=f, mtf=F)
e10 = float(np.interp(0.9, esf[::-1], rs[::-1])); e90 = float(np.interp(0.1, esf[::-1], rs[::-1]))
out = dict(limb_profiles=len(profs), arc_deg=[round(float(np.degrees(a0)), 1), round(float(np.degrees(a1)), 1)], edge_10_90_arcsec=round((e90 - e10) * ARC, 2), mtf_model="exp(-(f/f0)^p)", f0_cycles_per_px=round(float(f0), 5), p=round(float(pw), 3),
           psf_fwhm_px=round(float(fwhm), 2), psf_fwhm_arcsec=round(float(fwhm) * ARC, 2), arcsec_per_px=round(ARC, 4),
           mtf_at={"%.1f arcsec" % per: round(float(np.exp(-((ARC / per) / f0) ** pw)), 4) for per in (8, 5, 4, 3, 2.5, 2)})
json.dump(out, open(sys.argv[3].replace(".npz", ".json"), "w"), indent=1); print(json.dumps(out))
