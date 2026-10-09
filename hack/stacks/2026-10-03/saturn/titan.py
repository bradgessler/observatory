"""Titan in the short frames: a wide stack of the kept frames lined up on the planet (as satfinish.py does), then Titan's shape,
measured three ways: satfinish's round Gaussian fit, an elliptical Gaussian fit, and the half-maximum width read straight off the profile.
Usage: titan.py <folder> <stem> [turn, deg per minute] [reference minute of the day]
With a turn rate, each frame is turned back about the planet by rate x (its time - reference) before it is added."""
import sys, os, json
import numpy as np, cv2
from scipy.optimize import curve_fit
folder, stem = sys.argv[1], sys.argv[2]; RATE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0; REF = float(sys.argv[4]) if len(sys.argv) > 4 else 330.0
minute = lambda name: int(name[9:11]) * 60 + int(name[11:13]) + int(name[13:15]) / 60
sys.argv = [sys.argv[0], folder, "x"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
rec = json.load(open(stem + ".json")); R = 330; acc = np.zeros((2 * R, 2 * R), np.float64); n = 0
for name in rec["used"]:
    f = sat.find(os.path.join(folder, name))
    pl, _ = sat.planes(f["path"]); g = sum(p[3] for p in pl if p[0] == "G") / 2
    d = np.radians(RATE * (minute(name) - REF)); c_, s_ = np.cos(d), np.sin(d)
    acc += cv2.warpAffine(g, np.float32([[c_, s_, R - (c_ * f["x"] + s_ * f["y"])], [-s_, c_, R - (-s_ * f["x"] + c_ * f["y"])]]), (2 * R, 2 * R), flags=cv2.INTER_LANCZOS4); n += 1
wide = (acc / n).astype(np.float32); wide -= np.median(wide); np.save(stem + "-wide.npy", wide)
yy, xx = np.mgrid[0:2 * R, 0:2 * R]; away = np.hypot(xx - R, yy - R) > 70; noise = 1.4826 * np.median(np.abs(wide[away]))
sm = cv2.GaussianBlur(wide, (0, 0), 1.5); sm[~away] = 0; my, mx = np.unravel_index(np.argmax(sm), sm.shape)
print("brightest point away from the planet: %.0f arcsec from Saturn at %.1f deg, %.0f sigma" % (np.hypot(mx - R, my - R) * 0.791, np.degrees(np.arctan2(my - R, mx - R)), sm[my, mx] / (noise / 3)))
for r in (9, 14):
    p = wide[my - r:my + r + 1, mx - r:mx + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
    f2 = lambda X, a, x0, y0, s, c: a * np.exp(-((X[0] - x0) ** 2 + (X[1] - y0) ** 2) / (2 * s * s)) + c
    (a, x0, y0, s, c), _ = curve_fit(f2, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 2.0, 0), maxfev=4000)
    def f3(X, a, x0, y0, s1, s2, th, c):
        u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
        return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
    (a3, x3, y3, s1, s2, th, c3), _ = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 3.0, 2.5, 0.3, 0), maxfev=20000)
    if abs(s2) > abs(s1): s1, s2, th = s2, s1, th + np.pi / 2
    print("  window +-%d half px: round Gaussian FWHM %.2f arcsec (peak %.5f, floor %.5f); elliptical %.2f x %.2f arcsec, long axis at %.0f deg" % (r, 2.355 * abs(s) * 0.791, a, c, 2.355 * abs(s1) * 0.791, 2.355 * abs(s2) * 0.791, np.degrees(th) % 180))
# straight off the profile: ring means around the fitted centre
r = 14; cy, cx = my + y0, mx + x0; d = np.hypot(xx - cx, yy - cy); prof = [float(wide[(d >= k - 0.5) & (d < k + 0.5)].mean()) for k in range(0, 15)]
floor = float(np.median(wide[(d > 16) & (d < 28)])); pk = prof[0] - floor; q = [(v - floor) / pk for v in prof]
half = next(k - 1 + (q[k - 1] - 0.5) / (q[k - 1] - q[k]) for k in range(1, 15) if q[k] < 0.5)
print("  radial profile (peak 1):", " ".join("%.2f" % v for v in q)); print("  half maximum at radius %.2f half px: FWHM %.2f arcsec (noise per pixel %.3f of Titan's peak)" % (half, 2 * half * 0.791, noise / pk))
t = wide[my - 24:my + 25, mx - 24:mx + 25]; cv2.imwrite(stem + "-titan.png", cv2.resize((np.clip(t / t.max(), 0, 1) ** 0.5 * 255).astype(np.uint8), None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST))
