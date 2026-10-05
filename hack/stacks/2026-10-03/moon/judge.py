"""Which choice of frames makes the better stack? (kept from the experiment; rewritten for this night)

For each choice (KEEP share of the sharpest frames per patch, CLEAR cloud limit) the half-size stack
is made from all frames and from two separate halves of them. Printed per choice, for the northern
part of the mosaic (clear frames) and the southern (frames through cloud) separately:
  detail   power in the fine-detail band (1.0-2.5 cells) of the full stack, relative to keep 100%
  agree    how well the two halves agree in that band (correlation): what both show is real
  res      where the halves' agreement falls to 1/2 and to 1/7 (Fourier ring correlation), arcsec
Usage: judge.py <raw dir> keep:clear[:atleast] ..."""
import os, subprocess, sys, json, numpy as np, cv2
import moonlib
SRC = sys.argv[1]; PY = sys.executable; HERE = os.path.dirname(os.path.abspath(__file__))
ARC = moonlib.ARCSEC_PER_PX
def lum(i): return (i[:, :, 0] + 2 * i[:, :, 1] + i[:, :, 2]) / 4
def band(a): return cv2.GaussianBlur(a, (0, 0), 1.0) - cv2.GaussianBlur(a, (0, 0), 2.5)
def frc(a, b, rows):
    N = 256; win = np.hanning(N)[:, None] * np.hanning(N)[None, :]
    yy, xx = np.indices((N, N)); rr = np.hypot(yy - N // 2, xx - N // 2).astype(int).ravel()
    ab = np.zeros(rr.max() + 1); aa = np.zeros_like(ab); bb = np.zeros_like(ab); tiles = 0
    floor = 0.25 * np.median(a[a > 0.05])
    for y in range(rows[0], rows[1] - N, N // 2):
        for x in range(0, a.shape[1] - N, N // 2):
            ta, tb = a[y:y + N, x:x + N], b[y:y + N, x:x + N]
            if ta.min() > floor and tb.min() > floor:
                fa = np.fft.fftshift(np.fft.fft2((ta / ta.mean() - 1) * win)); fb = np.fft.fftshift(np.fft.fft2((tb / tb.mean() - 1) * win))
                ab += np.bincount(rr, (fa * np.conj(fb)).real.ravel()); aa += np.bincount(rr, (np.abs(fa) ** 2).ravel()); bb += np.bincount(rr, (np.abs(fb) ** 2).ravel()); tiles += 1
    c = (ab / np.sqrt(aa * bb + 1e-30))[:N // 2]; f = np.arange(N // 2) / N
    cs = np.convolve(np.pad(c, 2, mode="edge"), np.ones(5) / 5, "valid")
    cross = lambda lv: ARC / f[int(np.argmax(cs[2:] < lv)) + 2]
    return cross(0.5), cross(1 / 7), tiles
base = None
for spec in sys.argv[2:]:
    p = spec.split(":"); keep, clear = p[0], p[1]; atl = p[2] if len(p) > 2 else "6"; mink = int(p[3]) if len(p) > 3 else 4
    env = dict(os.environ, MOON_CLEAR=clear, MOON_ATLEAST=atl, MOON_TAG="-judge", MOON_MINK=str(mink))
    subprocess.run([PY, "stack.py", SRC, "combine", keep], env=env, stdout=subprocess.DEVNULL, check=True)
    for h in "ab":
        subprocess.run([PY, "stack.py", SRC, "combine", keep], env=dict(env, MOON_HALF=h, MOON_MINK=str(max(mink // 2, 1)), MOON_ATLEAST=str(max(int(atl) // 2, 1))), stdout=subprocess.DEVNULL, check=True)
    tag = "keep%02d-judge" % round(float(keep) * 100)
    F = np.load("stack-%s.npz" % tag); A = lum(np.load("stack-%s-half-a.npz" % tag)["img"]); B = lum(np.load("stack-%s-half-b.npz" % tag)["img"]); L = lum(F["img"]); depth = F["depth"]
    H = L.shape[0]; SPLIT = int(os.environ.get("MOON_SPLIT", H // 2)); out = []
    for name, rows in (("north", (0, SPLIT)), ("south", (SPLIT, H))):
        sl = slice(*rows); l, a, b = L[sl], A[sl], B[sl]
        lit = cv2.erode((cv2.GaussianBlur(l, (0, 0), 6) > 0.08).astype(np.uint8), np.ones((49, 49), np.uint8)) > 0
        m = cv2.GaussianBlur(l, (0, 0), 12) + 1e-4
        d = float((band(l / m) ** 2)[lit].mean()); ba, bb_ = band(a / m)[lit], band(b / m)[lit]
        agree = float((ba * bb_).mean() / np.sqrt((ba ** 2).mean() * (bb_ ** 2).mean()))
        r5, r7, tiles = frc(A, B, rows)
        out.append((name, d, agree, r5, r7, tiles, float(np.median(depth[sl][lit]))))
    if base is None:
        base = [o[1] for o in out]
    print("keep %s clear %s at least %s min %d:  " % (keep, clear, atl, mink) + "   ".join("%s: detail %.3f agree %.3f res %.2f / %.2f arcsec (%d tiles, %d frames deep)" % (o[0], o[1] / bb0, o[2], o[3], o[4], o[5], o[6]) for o, bb0 in zip(out, base)), flush=True)
    for h in ("", "-half-a", "-half-b"):
        os.remove("stack-%s%s.npz" % (tag, h))
