"""How fine is the real detail? Radial power spectrum of the raw green pixels on the Moon's face,
against the noise floor. Reads one ARW; changes nothing."""
import sys, numpy as np, rawpy
r = rawpy.imread(sys.argv[1])
raw = r.raw_image_visible.astype(np.float32)
pat = r.raw_pattern  # 2x2 colour indices
desc = r.color_desc.decode()
black = float(np.mean(r.black_level_per_channel)); white = float(r.white_level)
# one green pixel of each 2x2 cell: a clean half-size sampling, no interpolation
gy, gx = [(y, x) for y in (0, 1) for x in (0, 1) if desc[pat[y, x]] == "G"][0]
g = (raw[gy::2, gx::2] - black) / (white - black)
print("green plane", g.shape, "max %.3f" % g.max(), "clipped (>=0.98): %.2f%% of all, %.2f%% of lit" % (100 * (g >= 0.98).mean(), 100 * (g[g > 0.05] >= 0.98).mean()))
# the most detailed 512x512 tile that is fully lit and unclipped
N = 512; best = None
for y in range(0, g.shape[0] - N, 128):
    for x in range(0, g.shape[1] - N, 128):
        t = g[y:y + N, x:x + N]
        if t.min() > 0.03 and t.max() < 0.95:
            s = t.std() / t.mean()
            if best is None or s > best[0]: best = (s, y, x)
if best is None: sys.exit("no fully lit, unclipped tile")
_, y, x = best; t = g[y:y + N, x:x + N]; print("tile at", (x, y), "mean %.3f" % t.mean())
t = t / t.mean() - 1.0
w = np.hanning(N)[:, None] * np.hanning(N)[None, :]
P = np.abs(np.fft.fftshift(np.fft.fft2(t * w))) ** 2
yy, xx = np.indices(P.shape); rr = np.hypot(yy - N // 2, xx - N // 2).astype(int)
prof = np.bincount(rr.ravel(), P.ravel()) / np.maximum(np.bincount(rr.ravel()), 1)
floor = np.median(prof[int(N * 0.42):N // 2])  # near Nyquist: noise only if the optics blur more than that
scale = 0.3955 * 2  # arcsec per half-size pixel: 3.9 um at 2032 mm, two pixels
print("freq(cyc/px)  period(px)  period(arcsec)  power/floor")
for f in (0.02, 0.04, 0.06, 0.08, 0.10, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.48):
    k = int(f * N); print("   %.3f       %5.1f      %5.1f         %8.1f" % (f, 1 / f, scale / f, prof[k] / floor))
above = np.where(prof[2:N // 2] / floor > 2.0)[0]
kmax = above.max() + 2
print("signal stays above twice the noise floor out to %.3f cycles/px: detail as fine as %.1f half-size px = %.1f arcsec" % (kmax / N, N / kmax, scale * N / kmax))
