"""Each 2 s frame that has Saturn in it: is Titan a round point or a trail? Titan is found 205 arcsec from the blown-out planet
on the ring line (158 deg in the picture), and an elliptical Gaussian is fitted to it."""
import json, os, sys, glob
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2, rawpy
from scipy.optimize import curve_fit
TITAN_DEG = 154.4   # sharp run, 2026-10-04 08:47-09:09 UTC: where rottitan.py found Titan (it was 158.2 at 05:14)
def green(path):
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32); pat = r.raw_pattern; desc = r.color_desc.decode(); black = np.array(r.black_level_per_channel, np.float32); white = float(r.white_level)
    return sum((raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]]) for y in (0, 1) for x in (0, 1) if desc[pat[y, x]] == "G") / 2
def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
def grade(path):
    g = green(path); name = os.path.basename(path); sm = cv2.GaussianBlur(g, (0, 0), 6); cy, cx = np.unravel_index(np.argmax(sm), sm.shape)
    if sm[cy, cx] < 0.3: return dict(frame=name, saturn=False)
    y0, x0 = max(cy - 60, 0), max(cx - 60, 0); t = sm[y0:cy + 60, x0:cx + 60]; m = t > 0.5 * t.max(); yy, xx = np.mgrid[0:t.shape[0], 0:t.shape[1]]
    fx = float((xx * m).sum() / m.sum()) + x0; fy = float((yy * m).sum() / m.sum()) + y0
    out = dict(frame=name, saturn=True, x=round(fx * 2, 1), y=round(fy * 2, 1), blob_area=int(m.sum()))
    # Titan: 205 arcsec = 259 half px away at about 158 deg; look within 30 half px of there for the brightest point
    ex, ey = fx + 260 * np.cos(np.radians(TITAN_DEG)), fy + 260 * np.sin(np.radians(TITAN_DEG)); h, w = g.shape
    if not (40 < ex < w - 40 and 40 < ey < h - 40): out["titan"] = None; return out
    ix, iy = int(round(ex)), int(round(ey)); win = cv2.GaussianBlur(g, (0, 0), 2)[iy - 30:iy + 31, ix - 30:ix + 31]; py, px = np.unravel_index(np.argmax(win), win.shape); tx, ty = ix - 30 + px, iy - 30 + py
    r = 16; p = g[ty - r:ty + r + 1, tx - r:tx + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]; p = p - np.median(g[ty - 40:ty + 40, tx - 40:tx + 40])
    try:
        (a, x0_, y0_, s1, s2, th, c), _ = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 4.0, 3.0, 1.5, 0), maxfev=20000)
    except Exception as e: out["titan"] = None; return out
    s1, s2 = abs(s1), abs(s2)
    if s2 > s1: s1, s2, th = s2, s1, th + np.pi / 2
    out["titan"] = dict(long_arcsec=round(2.355 * s1 * 0.791, 2), short_arcsec=round(2.355 * s2 * 0.791, 2), long_axis_deg=round(float(np.degrees(th) % 180), 0), peak=round(float(a), 4),
                        from_saturn_arcsec=round(float(np.hypot(tx + x0_ - fx, ty + y0_ - fy) * 0.791), 1), at_deg=round(float(np.degrees(np.arctan2(ty + y0_ - fy, tx + x0_ - fx))), 2))
    return out
if __name__ == "__main__":
    files = sorted(glob.glob("long/*.ARW"))
    with ProcessPoolExecutor(8) as ex: res = list(ex.map(grade, files))
    json.dump(res, open("longgrades.json", "w"), indent=1)
    for r in res:
        if not r["saturn"]: continue
        t = r.get("titan"); print(r["frame"][9:15], r["frame"][16:24], "Saturn at (%6.1f, %6.1f) blob %d" % (r["x"], r["y"], r["blob_area"]), ("Titan %.1f x %.1f arcsec, long axis %3.0f deg, peak %.3f, %.1f arcsec from Saturn at %.2f deg" % (t["long_arcsec"], t["short_arcsec"], t["long_axis_deg"], t["peak"], t["from_saturn_arcsec"], t["at_deg"])) if t else "Titan not measured")
    print(sum(1 for r in res if not r["saturn"]), "frames without Saturn")
