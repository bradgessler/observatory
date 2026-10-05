"""The field's turning, measured from Titan: short frames stacked in groups by time (lined up on the planet), Titan's direction from Saturn in each group."""
import sys, os, json
import numpy as np, cv2
from scipy.optimize import curve_fit
sys.argv = [sys.argv[0], "planet", "x"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
from concurrent.futures import ProcessPoolExecutor
R = 330
def wide(f):
    pl, _ = sat.planes("planet/" + f["name"]); g = sum(p[3] for p in pl if p[0] == "G") / 2
    w = cv2.warpAffine(g, np.float32([[1, 0, R - f["x"]], [0, 1, R - f["y"]]]), (2 * R, 2 * R), flags=cv2.INTER_LANCZOS4, borderValue=float("nan")); return w - np.nanmedian(w)
if __name__ == "__main__":
    g = sorted([f for f in json.load(open("grades.json")) if f["ok"]], key=lambda f: f["name"])
    minute = lambda f: int(f["name"][9:11]) * 60 + int(f["name"][11:13]) + int(f["name"][13:15]) / 60
    with ProcessPoolExecutor(8) as ex: ws = list(ex.map(wide, g))
    f2 = lambda X, a, x0, y0, s, c: a * np.exp(-((X[0] - x0) ** 2 + (X[1] - y0) ** 2) / (2 * s * s)) + c
    rows = []; N = 12
    for i in range(0, len(g) - N + 1, N):
        st = np.nanmean(ws[i:i + N], 0); st = np.nan_to_num(st); sm = cv2.GaussianBlur(st, (0, 0), 2.5)
        yy, xx = np.mgrid[0:2 * R, 0:2 * R]; d = np.hypot(xx - R, yy - R); sm[(d < 235) | (d > 285) | (xx > R)] = 0
        my, mx = np.unravel_index(np.argmax(sm), sm.shape); r = 10
        if my < r or mx < r or my > 2 * R - r - 1 or mx > 2 * R - r - 1: continue
        p = st[my - r:my + r + 1, mx - r:mx + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
        try: (a, x0, y0, s, c), _ = curve_fit(f2, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 3.0, 0), maxfev=4000)
        except Exception: continue
        tx, ty = mx + x0 - R, my + y0 - R; t = np.mean([minute(f) for f in g[i:i + N]])
        rows.append((t, np.degrees(np.arctan2(ty, tx)), np.hypot(tx, ty) * 0.791, 2.355 * abs(s) * 0.791))
        print("  05:%04.1f  Titan at %.2f deg, %.1f arcsec from Saturn, FWHM %.1f arcsec" % (t - 300, rows[-1][1], rows[-1][2], rows[-1][3]))
    rows = np.array(rows); k = np.polyfit(rows[:, 0], rows[:, 1], 1); res = rows[:, 1] - np.polyval(k, rows[:, 0])
    print("Titan's direction turns %.4f deg per minute (scatter about the line %.2f deg); at 05:13.8 (the moon frames) it would be %.2f deg, at 05:30 %.2f deg" % (k[0], res.std(), np.polyval(k, 313.8), np.polyval(k, 330)))
    json.dump(dict(deg_per_minute=float(k[0]), deg_at_0530=float(np.polyval(k, 330)), scatter_deg=float(res.std()), groups=[dict(minute_after_05=round(float(r[0] - 300), 2), titan_deg=round(float(r[1]), 3), arcsec=round(float(r[2]), 2)) for r in rows]), open("rotation.json", "w"), indent=1)
