"""How wide are the points in a moon field? Elliptical Gaussian fits (green) to named points. moonwidths.py with the points given on the
command line (they are at different distances in each run), widths in true arcsec, and a note when a point has a blown-out pixel.
Usage: moonwidths3.py <stem> <arcsec per sensor px> label=arcsec(0.791 unit) ...   writes <stem>-widths.json"""
import sys, json, numpy as np
from scipy.optimize import curve_fit
def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
stem, pp = sys.argv[1], float(sys.argv[2]); want = [(a.split("=")[0], float(a.split("=")[1])) for a in sys.argv[3:]]
pts = json.load(open(stem + ".json"))["points"]; f = np.load(stem + ".npy")[..., 1]; raw = np.load(stem + "-glare.npy")[..., 1]; noise = 1.4826 * np.median(np.abs(f[f != 0])); out = {}
print("%s: noise %.5f" % (stem, noise))
for label, arc in want:
    c = [q for q in pts if abs(q["arcsec"] - arc) < 2.5]
    if not c: print("   %-9s %6.1f not found" % (label, arc)); continue
    q = max(c, key=lambda q: q["flux"]); x, y = int(round(q["x"])), int(round(q["y"])); r = 14
    if min(x, y) < r or max(x, y) >= f.shape[0] - r: print("   %-9s %6.1f too near the edge of the field to fit" % (label, arc)); continue
    p = f[y - r:y + r + 1, x - r:x + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
    (A, x0, y0, s1, s2, th, c0), cov = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 3.5 if p.max() < 0 else 2.5, 2.0, 1.0, 0), maxfev=20000)
    s1, s2 = abs(s1), abs(s2); e = np.sqrt(np.diag(cov))
    if s2 > s1: s1, s2, th = s2, s1, th + np.pi / 2; e[3], e[4] = e[4], e[3]
    blown = bool(raw[y - 4:y + 5, x - 4:x + 5].max() >= 0.9)
    out[label] = dict(fwhm_arcsec=[round(2.355 * s1 * 2 * pp, 2), round(2.355 * s2 * 2 * pp, 2)], error_arcsec=[round(2.355 * e[3] * 2 * pp, 2), round(2.355 * e[4] * 2 * pp, 2)], long_axis_deg_in_frame=round(float(np.degrees(th) % 180), 0), peak=round(float(A), 4), peak_over_noise=round(float(A / noise)), blown_out=blown)
    print("   %-9s %6.1f  %.2f (+-%.2f) x %.2f (+-%.2f) arcsec, long axis %3.0f deg, peak %.4f = %.0f x noise%s" % (label, q["arcsec"], *[v for pair in zip(out[label]["fwhm_arcsec"], out[label]["error_arcsec"]) for v in pair], out[label]["long_axis_deg_in_frame"], A, A / noise, "  (blown out: the top is clipped, so it reads wide)" if blown else ""))
json.dump(out, open(stem + "-widths.json", "w"), indent=1)
