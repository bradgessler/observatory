"""A check on the blur finish2.py measures: Titan (or any moon) laid onto the same fine grid, by the same resampling, as the planet itself
(saturn2.py's tile(): each colour plane read at its own place, turned back about the planet, red and blue slid by the planet's own amounts),
then fitted with an elliptical Gaussian on brightness and on green. finish2.py measures Titan in a half-size green stack, where the two
green photosites are averaged; with a blur of 2.5 arcsec that averaging is no longer negligible, so this says how much it matters.
No pixel from here goes into any picture.
Usage: titanfine.py <folder> <stem> <arcsec from Saturn (0.791 per half px)> <direction deg> [label]"""
import sys, os, json
import numpy as np, cv2
from scipy.optimize import curve_fit
from concurrent.futures import ProcessPoolExecutor
folder, stem, DIST, DIR = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]); label = sys.argv[5] if len(sys.argv) > 5 else "titan"
rec = json.load(open(stem + ".json")); tb = rec.get("turned_back") or {}; RATE = tb.get("deg_per_minute", 0.0); REF = tb.get("reference_minute_of_day_utc", 0.0)
_argv = sys.argv; sys.argv = [sys.argv[0], folder, "x"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
sys.argv = _argv            # the worker processes read the same arguments
UP = sat.UP; H = 12; N = 2 * H * UP; FINE = 0.3955 / 3
minute = lambda name: int(name[9:11]) * 60 + int(name[11:13]) + int(name[13:15]) / 60
def one(name):
    f = sat.find(os.path.join(folder, name)); pl, wb = sat.planes(f["path"]); fx, fy = f["x"], f["y"]
    tx, ty = DIST / 0.791 * np.cos(np.radians(DIR)), DIST / 0.791 * np.sin(np.radians(DIR))
    X = (np.arange(N, dtype=np.float32) + 0.5) / UP - 0.5 - H; u, v = np.meshgrid(X + np.float32(tx), X + np.float32(ty))
    d = np.radians(RATE * (minute(name) - REF)); c_, s_ = np.float32(np.cos(d)), np.float32(np.sin(d)); mx, my = np.float32(fx) + u * c_ - v * s_, np.float32(fy) + u * s_ + v * c_
    acc = np.zeros((N, N, 3), np.float32); w = np.zeros(3, np.float32)
    for colour, x, y, p in pl:
        c = "RGB".index(colour); acc[:, :, c] += cv2.remap(p, mx - (x - 0.5) / 2, my - (y - 0.5) / 2, cv2.INTER_LANCZOS4) * wb[c]; w[c] += 1
    return acc / w
def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
if __name__ == "__main__":
    with ProcessPoolExecutor(8) as ex: tiles = list(ex.map(one, rec["used"]))
    st = np.mean(tiles, 0); moved = rec["colours_moved_native_px"]
    for c, k in ((0, "red"), (2, "blue")):
        dx, dy = moved[k][0] * 3, moved[k][1] * 3; st[:, :, c] = cv2.warpAffine(st[:, :, c], np.float32([[1, 0, -dx], [0, 1, -dy]]), (N, N), flags=cv2.INTER_LANCZOS4)
    np.save(stem + "-%s-fine.npy" % label, st); out = {}
    for what, img in (("brightness", st.sum(2) / 3), ("green", st[:, :, 1])):
        img = img - np.median(img[:10]); my_, mx_ = np.unravel_index(np.argmax(cv2.GaussianBlur(img, (0, 0), 3)), img.shape); r = min(54, mx_, my_, N - 1 - mx_, N - 1 - my_)
        p = img[my_ - r:my_ + r + 1, mx_ - r:mx_ + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
        (a, x0, y0, s1, s2, th, c), cov = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 9.0, 7.0, 2.4, 0), maxfev=20000); s1, s2 = abs(s1), abs(s2); e = np.sqrt(np.diag(cov))
        if s2 > s1: s1, s2, th = s2, s1, th + np.pi / 2; e[3], e[4] = e[4], e[3]
        out[what] = dict(fwhm_arcsec=[round(2.355 * s1 * FINE, 3), round(2.355 * s2 * FINE, 3)], err=[round(2.355 * e[3] * FINE, 3), round(2.355 * e[4] * FINE, 3)], long_axis_deg=round(float(np.degrees(th) % 180), 1), peak=float(a), centre_off_fine_px=[round(float(mx_ + x0 - N / 2 + 0.5), 2), round(float(my_ + y0 - N / 2 + 0.5), 2)])
        print("%s %s on the fine grid, %s: %.2f (+-%.2f) x %.2f (+-%.2f) arcsec, long axis %.0f deg; peak %.5f" % (label, stem, what, out[what]["fwhm_arcsec"][0], out[what]["err"][0], out[what]["fwhm_arcsec"][1], out[what]["err"][1], out[what]["long_axis_deg"], a))
    json.dump(out, open(stem + "-%s-fine.json" % label, "w"), indent=1)
    v = st.sum(2); v = np.clip((v - np.median(v)) / (v.max() - np.median(v)), 0, 1) ** 0.5; cv2.imwrite(stem + "-%s-fine.png" % label, cv2.resize((v * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
