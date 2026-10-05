"""Does the field turn between frames? The ring line's angle in every frame against time."""
import sys, os, json
import numpy as np, cv2
sys.argv = [sys.argv[0], "planet", "x"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
from concurrent.futures import ProcessPoolExecutor
def ang(f):
    t = sat.tile(("planet/" + f["name"], f["x"], f["y"])); g = cv2.GaussianBlur(t.sum(2), (0, 0), 6); n = g.shape[0]; yy, xx = np.mgrid[0:n, 0:n]
    g = g - np.median(g[:60]); v = np.clip(g, 0, None); m = v > 0.25 * v.max(); cx = (xx * v * m).sum() / (v * m).sum(); cy = (yy * v * m).sum() / (v * m).sum()
    w = ((v > 0.08 * v.max()) & (v < 0.5 * v.max())).astype(np.float64); dx, dy = xx - cx, yy - cy
    return float(np.degrees(0.5 * np.arctan2(2 * (w * dx * dy).sum(), (w * dx * dx).sum() - (w * dy * dy).sum())))
if __name__ == "__main__":
    g = [f for f in json.load(open("grades.json")) if f["ok"]]
    with ProcessPoolExecutor(8) as ex: a = list(ex.map(ang, g))
    t = np.array([int(f["name"][9:11]) * 60 + int(f["name"][11:13]) + int(f["name"][13:15]) / 60 for f in g]); a = np.array(a); x = np.array([f["x"] * 2 for f in g]); y = np.array([f["y"] * 2 for f in g])
    k = np.polyfit(t, a, 1); res = a - np.polyval(k, t)
    print("ring line: mean %.2f deg, scatter %.2f deg; trend %.4f deg per minute (%.2f deg over the %d minutes), scatter about the trend %.2f deg" % (a.mean(), a.std(), k[0], k[0] * (t.max() - t.min()), t.max() - t.min(), res.std()))
    for lo in range(int(t.min()), int(t.max()) + 1, 5):
        s = (t >= lo) & (t < lo + 5)
        if s.sum(): print("  05:%02d-05:%02d  %2d frames  ring line %.2f +- %.2f deg   planet at (%.0f, %.0f) native px" % (lo - 300, lo - 295, s.sum(), a[s].mean(), a[s].std() / np.sqrt(s.sum()), x[s].mean(), y[s].mean()))
    json.dump([dict(frame=f["name"], ring_line_deg=round(v, 3)) for f, v in zip(g, a)], open("ringangles.json", "w"), indent=1)
