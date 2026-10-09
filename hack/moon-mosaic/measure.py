"""Two measurements on the stack, read only: how far the colour planes sit apart (the air spreads
colours like a weak prism), and how blurred the picture is, from the Moon's own edge.
The sunlit limb is a true step: lit ground against black sky. How many pixels the stack takes to
go from dark to bright across it is the blur of everything: optics, focus, air, and our alignment."""
import sys, json, numpy as np, cv2
import moonlib
z = np.load(sys.argv[1]); img = z["img"]; g = img[:, :, 1]
K = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0   # pixels per working pixel (2 for the fine grid)
ARC = moonlib.ARCSEC_PER_PX / K
out = {"arcsec_per_px": round(ARC, 4)}
# -- colour planes -------------------------------------------------------------------------------
mask = (cv2.GaussianBlur(g, (0, 0), 3 * K) > 0.05).astype(np.float32)
inner = cv2.erode(mask, np.ones((int(41 * K), int(41 * K)), np.uint8))
rel = lambda p: ((moonlib.relief(p, 12.0 * K) - 1) * inner).astype(np.float32)
for name, c in (("red", 0), ("blue", 2)):
    (dx, dy), resp = cv2.phaseCorrelate(rel(g), rel(img[:, :, c]))
    out[name + "_shift_px"] = [round(dx, 3), round(dy, 3)]; out[name + "_shift_arcsec"] = round(float(np.hypot(dx, dy)) * ARC, 2)
# -- the limb --------------------------------------------------------------------------------------
lit = (cv2.GaussianBlur(g, (0, 0), 2 * K) > 0.5 * np.percentile(g[mask > 0], 50)).astype(np.uint8)
cnt = max(cv2.findContours(lit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)[:, 0, :].astype(np.float64)
# A circle through the limb, robustly: three contour points at a time, keeping the circle the most
# of the contour lies on. Only a Moon-sized circle counts (880-1010 arcsec radius), so a stretch of
# the terminator can't pass for the limb.
def circle3(p):
    A = np.c_[2 * p, np.ones(len(p))]; b = (p ** 2).sum(1); cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
    return cx, cy, np.sqrt(max(c + cx * cx + cy * cy, 0))
rng = np.random.default_rng(7); best = (0, None)
for _ in range(4000):
    tri = cnt[rng.choice(len(cnt), 3, replace=False)]
    cx, cy, r = circle3(tri)
    if not (880 <= r * ARC <= 1010):
        continue
    on = np.abs(np.hypot(cnt[:, 0] - cx, cnt[:, 1] - cy) - r) < 1.5 * K
    if on.sum() > best[0]:
        best = (int(on.sum()), on)
p = cnt[best[1]]; cx, cy, r = circle3(p)
out["limb_points"] = best[0]
out["moon_centre_px"] = [round(float(cx), 1), round(float(cy), 1)]
out["moon_radius_px"] = round(float(r), 1); out["moon_radius_arcsec"] = round(float(r) * ARC, 1)
ang = np.arctan2(p[:, 1] - cy, p[:, 0] - cx); a0, a1 = np.percentile(ang, [3, 97])
rs = np.arange(-14 * K, 14 * K + 0.01, 0.25); profs = []
for a in np.linspace(a0, a1, 1200):
    xs = (cx + (r + rs) * np.cos(a)).astype(np.float32)[None]; ys = (cy + (r + rs) * np.sin(a)).astype(np.float32)[None]
    pr = cv2.remap(g, xs, ys, cv2.INTER_CUBIC)[0]
    lo, hi = pr[-int(8 * K):].mean(), pr[:int(8 * K)].mean()
    if hi > 0.1 and hi < 0.9 and lo < 0.2 * hi:          # a clean, unclipped stretch of limb
        n = (pr - lo) / (hi - lo); k = np.argmin(np.abs(n - 0.5))
        profs.append(np.interp(rs, rs - rs[k], n))        # each profile slid to its own half-way point
esf = np.mean(profs, 0); lsf = -np.gradient(esf, rs); lsf = np.clip(lsf, 0, None); lsf /= lsf.sum()
mu = (rs * lsf).sum(); sigma = float(np.sqrt(((rs - mu) ** 2 * lsf).sum()))
half = lsf >= lsf.max() / 2; fwhm = float(rs[half].max() - rs[half].min())
r10 = float(np.interp(0.9, esf[::-1], rs[::-1])); r90 = float(np.interp(0.1, esf[::-1], rs[::-1]))
out.update(limb_profiles=len(profs), edge_10_90_px=round(r90 - r10, 2), blur_fwhm_px=round(fwhm, 2), blur_fwhm_arcsec=round(fwhm * ARC, 2),
           blur_sigma_px=round(fwhm / 2.355, 3), moment_sigma_px=round(sigma, 3))
json.dump(out, open(sys.argv[2], "w"), indent=1); print(json.dumps(out, indent=1))
