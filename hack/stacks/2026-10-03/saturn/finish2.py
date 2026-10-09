"""Finish the Saturn stack, as satfinish.py does: measure the blur from Titan (a true point of light, seen through the same air in
the same frames), and divide it back out of the planet (Richardson-Lucy on brightness; colours scaled by the same ratio).
The plain stack is kept beside it.

finish2.py is satfinish.py with these changes, made for the restack of 2026-10-04:
  1. The wide stack that shows Titan is turned back frame by frame for the field's turning, by the same rate and reference the
     planet stack used (read from its recipe). Without that Titan, 205 arcsec out, is smeared sideways by about 4 arcsec and the
     blur reads 5.6 arcsec; with it, 4.7.
  2. Titan is fitted with an elliptical Gaussian as well as the round one, and the elliptical one is the blur divided out: tonight
     the blur is longer one way (about 5.1 x 4.1 arcsec), and the planet's own shape says the same (psfmodel.py).
     --round uses the round fit instead, as satfinish.py did.
  3. Default 8 rounds (30 drew a false ring). The deconvolved brightness is saved as numbers (.npy) beside the PNG, so it can be measured.

Usage: finish2.py <folder of .ARW> <stem from saturn2.py> [rounds, default 8] [--round] [--suffix name]
"""
import sys, os, json
import numpy as np, cv2
from scipy.optimize import curve_fit
argv = sys.argv[:]; flags = [a for a in argv[1:] if a.startswith("--")]
suffix = argv[argv.index("--suffix") + 1] if "--suffix" in argv else ""
pos = [a for i, a in enumerate(argv[1:], 1) if not a.startswith("--") and argv[i - 1] != "--suffix"]
folder, stem = pos[0], pos[1]; rounds = int(pos[2]) if len(pos) > 2 else 8; ROUND = "--round" in flags
sys.argv = [argv[0], folder, "x"]; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
rec = json.load(open(stem + ".json")); stack = np.load(stem + ".npy")
tb = rec.get("turned_back") or {}; RATE = tb.get("deg_per_minute", 0.0); REF = tb.get("reference_minute_of_day_utc", 0.0)
minute = lambda name: int(name[9:11]) * 60 + int(name[11:13]) + int(name[13:15]) / 60
# -- a wide, plain stack of the same frames (green, half-size pixels), lined up on the planet and turned back about it ---------
R = 330; acc = np.zeros((2 * R, 2 * R), np.float64); n = 0
for name in rec["used"]:
    f = sat.find(os.path.join(folder, name))
    if not f["ok"]: continue
    pl, _ = sat.planes(f["path"]); g = sum(p[3] for p in pl if p[0] == "G") / 2
    d = np.radians(RATE * (minute(name) - REF)); c_, s_ = np.cos(d), np.sin(d)
    M = np.float32([[c_, s_, R - (c_ * f["x"] + s_ * f["y"])], [-s_, c_, R - (-s_ * f["x"] + c_ * f["y"])]])
    acc += cv2.warpAffine(g, M, (2 * R, 2 * R), flags=cv2.INTER_LANCZOS4); n += 1
wide = (acc / n).astype(np.float32); wide -= np.median(wide)
yy, xx = np.mgrid[0:2 * R, 0:2 * R]; away = np.hypot(xx - R, yy - R) > 70
noise = 1.4826 * np.median(np.abs(wide[away])); sm = cv2.GaussianBlur(wide, (0, 0), 1.5); sm[~away] = 0
f2 = lambda X, a, x0, y0, s, c: a * np.exp(-((X[0] - x0) ** 2 + (X[1] - y0) ** 2) / (2 * s * s)) + c
def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
# A moon is as wide as the air and the optics make any point: several pixels. A hot pixel is one.
# Try the brightest points away from the planet, brightest first, and take the first that is wide.
psf = None; work = sm.copy(); r = 9; tried = []
for _ in range(25):
    my, mx = np.unravel_index(np.argmax(work), work.shape); snr = float(work[my, mx] / (noise / 3))
    if snr < 6: break
    work[max(my - 12, 0):my + 13, max(mx - 12, 0):mx + 13] = 0
    if my < r or mx < r or my >= 2 * R - r or mx >= 2 * R - r: continue
    p = wide[my - r:my + r + 1, mx - r:mx + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
    try:
        (a, x0, y0, s_, c), _ = curve_fit(f2, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 2.0, 0), maxfev=4000)
    except Exception: continue
    tried.append((round(float(np.hypot(mx - R, my - R) * 0.791)), round(snr), round(float(2.355 * abs(s_) * 0.791), 1)))
    if 1.2 <= abs(s_) <= 6 and abs(x0) < 3 and abs(y0) < 3:
        (a3, x3, y3, s1, s2, th, c3), cov = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(a, x0, y0, abs(s_) * 1.1, abs(s_) * 0.9, 2.7, c), maxfev=20000)
        s1, s2 = abs(s1), abs(s2); err = np.sqrt(np.diag(cov))
        if s2 > s1: s1, s2, th = s2, s1, th + np.pi / 2; err[3], err[4] = err[4], err[3]
        psf = dict(round_sigma=abs(s_), s1=s1, s2=s2, th=float(th % np.pi), snr=snr, arcsec=float(np.hypot(mx - R, my - R) * 0.791), at_deg=float(np.degrees(np.arctan2(my + y0 - R, mx + x0 - R))),
                   err=[float(2.355 * err[3] * 0.791), float(2.355 * err[4] * 0.791), float(np.degrees(err[5]))])
        print("a moon %.0f arcsec from Saturn at %.1f deg, %.0f sigma in the stack: round FWHM %.2f arcsec; elliptical %.2f (+-%.2f) x %.2f (+-%.2f) arcsec, long axis at %.0f (+-%.0f) deg" % (psf["arcsec"], psf["at_deg"], snr, 2.355 * abs(s_) * 0.791, 2.355 * s1 * 0.791, psf["err"][0], 2.355 * s2 * 0.791, psf["err"][1], np.degrees(psf["th"]), psf["err"][2])); break
print("points tried (arcsec from Saturn, sigma, FWHM arcsec):", tried)
if psf is None: sys.exit("no moon found in these frames: give the earlier blur by hand")
# -- the blur on the fine grid -------------------------------------------------------------------------------------------------
if ROUND: k1 = k2 = psf["round_sigma"] * sat.UP; th = 0.0
else: k1, k2, th = psf["s1"] * sat.UP, psf["s2"] * sat.UP, psf["th"]
h = int(np.ceil(4 * k1)); ky, kx = np.mgrid[-h:h + 1, -h:h + 1]; u = kx * np.cos(th) + ky * np.sin(th); v = -kx * np.sin(th) + ky * np.cos(th)
K = np.exp(-u * u / (2 * k1 * k1) - v * v / (2 * k2 * k2)).astype(np.float32); K /= K.sum()
blur = lambda a: cv2.filter2D(a, -1, K, borderType=cv2.BORDER_REFLECT_101)          # the kernel is the same turned half round, so it serves both steps
# -- Richardson-Lucy on the fine grid -------------------------------------------------------------------------------------------
L = np.maximum(stack.sum(2) / 3, 1e-7).astype(np.float32); est = L.copy()
for _ in range(rounds):
    est *= blur(L / np.maximum(blur(est), 1e-7))
out = stack * (est / L)[:, :, None]
def save(a, path):
    white = np.percentile(a, 99.95); v_ = np.clip(a / white, 0, 1) ** (1 / 2.2)
    cv2.imwrite(path, (v_[:, :, ::-1] * 255 + 0.5).astype(np.uint8))
o = stem + suffix
save(stack, o + "-plain.png"); save(out, o + "-deconvolved.png"); np.save(o + "-deconvolved.npy", out.astype(np.float32))
rec["finish"] = dict(script="finish2.py", psf=("round Gaussian" if ROUND else "elliptical Gaussian") + ", fitted to Titan in the same frames (turned back for the field's turning)",
                     psf_fwhm_arcsec=[round(2.355 * k1 / sat.UP * 0.791, 2), round(2.355 * k2 / sat.UP * 0.791, 2)], psf_long_axis_deg_in_picture=round(float(np.degrees(th)), 1),
                     titan=dict(arcsec_from_saturn=round(psf["arcsec"], 1), direction_deg=round(psf["at_deg"], 2), sigma_in_stack=round(psf["snr"], 1), round_fit_fwhm_arcsec=round(2.355 * psf["round_sigma"] * 0.791, 2),
                                elliptical_fit_fwhm_arcsec=[round(2.355 * psf["s1"] * 0.791, 2), round(2.355 * psf["s2"] * 0.791, 2)], elliptical_fit_error_arcsec=[round(psf["err"][0], 2), round(psf["err"][1], 2)], long_axis_deg=round(float(np.degrees(psf["th"])), 1)),
                     method="Richardson-Lucy on brightness; colours scaled by the same ratio", rounds=rounds)
json.dump(rec, open(o + ".json", "w"), indent=1)
print("saved", o + "-plain.png", o + "-deconvolved.png")
