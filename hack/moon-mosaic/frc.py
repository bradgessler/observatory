"""How fine is the detail that is really there? Two stacks made from separate halves of the frames
are compared scale by scale (Fourier ring correlation, the resolution test of cryo-electron
microscopy). Real detail is in both halves, so at that scale they agree (correlation near 1). Noise
is different in each, so they don't (near 0). No model of the blur or of the noise is needed.

From the correlation c at each scale: the full stack's signal-to-noise there is 2c / (1 - c), and
the fraction of what it shows that is signal is 2c / (1 + c).
The resolution is quoted where c falls to 1/7 (the usual criterion) and to 1/2 (a strict one).

Usage: frc.py half-a.npz half-b.npz arcsec_per_px out.npz
"""
import sys, json, numpy as np
A = np.load(sys.argv[1])["img"]; B = np.load(sys.argv[2])["img"]; ARC = float(sys.argv[3])
lum = lambda i: (i[:, :, 0] + 2 * i[:, :, 1] + i[:, :, 2]) / 4
a, b = lum(A), lum(B); h, w = a.shape
N = 512; win = np.hanning(N)[:, None] * np.hanning(N)[None, :]
yy, xx = np.indices((N, N)); rr = np.hypot(yy - N // 2, xx - N // 2).astype(int).ravel()
ab = np.zeros(rr.max() + 1); aa = np.zeros_like(ab); bb = np.zeros_like(ab); tiles = 0
floor = 0.25 * np.median(a[a > 0.05])
for y in range(0, h - N, N // 2):
    for x in range(0, w - N, N // 2):
        ta, tb = a[y:y + N, x:x + N], b[y:y + N, x:x + N]
        if ta.min() > floor and tb.min() > floor:          # fully lit in both
            fa = np.fft.fftshift(np.fft.fft2((ta / ta.mean() - 1) * win)); fb = np.fft.fftshift(np.fft.fft2((tb / tb.mean() - 1) * win))
            ab += np.bincount(rr, (fa * np.conj(fb)).real.ravel()); aa += np.bincount(rr, (np.abs(fa) ** 2).ravel()); bb += np.bincount(rr, (np.abs(fb) ** 2).ravel()); tiles += 1
c = (ab / np.sqrt(aa * bb + 1e-30))[:N // 2]; f = np.arange(N // 2) / N
cs = np.convolve(np.pad(c, 3, mode="edge"), np.ones(7) / 7, "valid")
def crossing(level):
    k = int(np.argmax(cs[2:] < level)) + 2
    return ARC / f[k]
frac = np.clip(2 * cs / (1 + cs), 0, 1)
k0 = int(np.argmax(cs[2:] < 0.02)) + 2; frac[k0:] = 0           # past where the halves stop agreeing at all: nothing
np.savez(sys.argv[4], f=f, frc=c, frc_smooth=cs, signal_fraction=frac)
out = dict(tiles=tiles, resolution_arcsec=dict(half=round(crossing(0.5), 2), one_seventh=round(crossing(1 / 7), 2)),
           agreement_at={"%.1f arcsec" % p: round(float(np.interp(ARC / p, f, cs)), 3) for p in (10, 6, 4, 3.5, 3, 2.7, 2.5, 2.3, 2.1, 1.9, 1.7)})
json.dump(out, open(sys.argv[4].replace(".npz", ".json"), "w"), indent=1); print(json.dumps(out))
