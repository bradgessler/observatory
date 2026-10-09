"""Each 2 s frame: how much light got through (cloud), and how wide the points are. Rhea, Titan, the 8th-magnitude star and Iapetus are
found near where the first-pass field has them (Saturn-relative, half-size px), fitted with an elliptical Gaussian (green), and their
light summed in a 6 half-px aperture above a ring of sky 9 to 14 half px out. Clipped pixels are counted."""
import json, os, glob, numpy as np, cv2
from scipy.optimize import curve_fit
from longgrade import green, f3
lg = {r["frame"]: r for r in json.load(open("longgrades.json"))}
pts = json.load(open("moonfield/pass1.json"))["points"]; R = 760
want = {"Rhea": 82.2, "Titan": 206.6, "star8": 606.4, "Iapetus?": 591.4, "star475": 475.4, "star617": 616.7, "star182": 182.5}
ref = {k: min(pts, key=lambda q: abs(q["arcsec"] - v)) for k, v in want.items()}
out = []
for path in sorted(glob.glob("long/*.ARW")):
    name = os.path.basename(path); r = lg[name]; g = green(path); fx, fy = r["x"] / 2, r["y"] / 2; row = dict(frame=name, sky=float(np.median(g[::8, ::8])))
    for k, q in ref.items():
        ex, ey = fx + q["x"] - R, fy + q["y"] - R; ix, iy = int(round(ex)), int(round(ey))
        if not (40 < ix < g.shape[1] - 40 and 40 < iy < g.shape[0] - 40): continue
        win = cv2.GaussianBlur(g, (0, 0), 1.5)[iy - 12:iy + 13, ix - 12:ix + 13]; py, px = np.unravel_index(np.argmax(win), win.shape); tx, ty = ix - 12 + px, iy - 12 + py
        rr = 14; p = g[ty - rr:ty + rr + 1, tx - rr:tx + rr + 1]; gy, gx = np.mgrid[-rr:rr + 1, -rr:rr + 1]; d = np.hypot(gx, gy)
        bg = float(np.median(p[(d >= 9) & (d <= 14)])); sd = 1.4826 * float(np.median(np.abs(p[(d >= 9) & (d <= 14)] - bg))); flux = float((p[d <= 6] - bg).sum()); nap = int((d <= 6).sum())
        try:
            (a, x0, y0, s1, s2, th, c), _ = curve_fit(f3, (gx.ravel(), gy.ravel()), (p - bg).ravel(), p0=(p.max() - bg, 0, 0, 2.0, 1.6, 1.5, 0), maxfev=20000); s1, s2 = sorted((abs(s1), abs(s2)), reverse=True)
            fw = (round(2.355 * s1 * 0.791, 2), round(2.355 * s2 * 0.791, 2)); pos = (round(tx + x0 - fx, 2), round(ty + y0 - fy, 2))
        except Exception: fw = None; pos = None
        row[k] = dict(flux=round(flux, 4), snr=round(flux / (sd * np.sqrt(nap)), 1), peak=round(float(p.max()), 3), clipped=int((p >= 0.98).sum()), fwhm_arcsec=fw, from_saturn_half_px=pos)
    out.append(row)
json.dump(out, open("longphot.json", "w"), indent=1)
keys = list(want)
for k in keys:
    best = max((r[k]["flux"] for r in out if k in r), default=1)
    print(k)
    for r in out:
        if k in r: q = r[k]; print("   %s flux %7.3f (%.2f of the most) snr %6.1f peak %.3f clipped %2d  %s arcsec  at %s" % (r["frame"][9:15], q["flux"], q["flux"] / best, q["snr"], q["peak"], q["clipped"], q["fwhm_arcsec"], q["from_saturn_half_px"]))
