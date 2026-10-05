"""How much of what the finishing step adds is noise? The kept frames are split into two halves (alternate frames by rank), each half
stacked on its own (saturn2.py), and each put through the same Richardson-Lucy with the same blur. What the two halves share is the planet;
what differs between them is noise. For each number of rounds: the noise on the globe and in the gap (half the difference of the halves,
as a fraction of the globe's brightness, for the full stack: divided by sqrt 2 again), and the gap contrast of the mean.
Usage: halves.py <stem of the full stack, finished> <N kept> <turn> <reference minute> [rounds ...]"""
import sys, os, json, subprocess
import numpy as np, cv2
from metrics import measure
from rounds import kernel
stem, TURN, REF = sys.argv[1], sys.argv[2], sys.argv[3]; rounds = [int(a) for a in sys.argv[4:]] or [0, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20]
rec = json.load(open(stem + ".json")); used = rec["used"]; fin = rec["finish"]; f1, f2 = fin["psf_fwhm_arcsec"]; th = np.radians(fin["psf_long_axis_deg_in_picture"])
ST = os.path.realpath("planet"); halves = []
for h in (0, 1):
    d = "%s-half%d" % (stem, h); os.makedirs(d, exist_ok=True)
    for n in used[h::2]:
        if not os.path.lexists(os.path.join(d, n)): os.symlink(os.path.realpath(os.path.join("planet", n)), os.path.join(d, n))
    if not os.path.exists(d + "-stack.npy"): subprocess.run([sys.executable, "saturn2.py", d, d + "-stack", "99", TURN, REF], check=True, capture_output=True)
    halves.append(np.load(d + "-stack.npy").astype(np.float32))
A, B = halves
# the halves were each centred on their own mean: slide B onto A (least squares on smoothed green)
from scipy.optimize import minimize
def ls(ref, img):
    a = cv2.GaussianBlur(ref, (0, 0), 3); b0 = cv2.GaussianBlur(img, (0, 0), 3); h, w = a.shape; sl = (slice(60, h - 60), slice(60, w - 60))
    def cost(p):
        b = cv2.warpAffine(b0, np.float32([[1, 0, -p[0]], [0, 1, -p[1]]]), (w, h), flags=cv2.INTER_LINEAR); k = (a[sl] * b[sl]).sum() / (b[sl] ** 2).sum(); return float(((a[sl] - k * b[sl]) ** 2).sum())
    r = minimize(cost, (0.0, 0.0), method="Nelder-Mead", options=dict(xatol=0.01, fatol=1e-14, initial_simplex=np.array([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]))); return r.x
dx, dy = ls(A[:, :, 1], B[:, :, 1]); B = cv2.warpAffine(B, np.float32([[1, 0, -dx], [0, 1, -dy]]), B.shape[1::-1], flags=cv2.INTER_LANCZOS4); B *= A.sum() / B.sum()
print("half B slid (%.2f, %.2f) fine px onto half A" % (dx, dy))
FINE = 0.3955 / 3; full = np.load(stem + ".npy").astype(np.float32); m, _ = measure(full[:, :, 1]); cx, cy = m["centre"]; ang = np.radians(m["ring_line_deg"]); n = full.shape[0]; yy, xx = np.mgrid[0:n, 0:n]
u = (xx - cx) * np.cos(ang) + (yy - cy) * np.sin(ang); v = -(xx - cx) * np.sin(ang) + (yy - cy) * np.cos(ang); Re = 9.84 / FINE; rho = np.hypot(u / Re, v / (Re * 0.903))
globe_mask = rho < 0.6; ring_mask = (np.abs(u) > 14 / FINE) & (np.abs(u) < 20 / FINE) & (np.abs(v) < 1.0 / FINE); sky_mask = np.hypot(u, v) > 32 / FINE
K = kernel(f1, f2, th); b = lambda a: cv2.filter2D(a, -1, K, borderType=cv2.BORDER_REFLECT_101)
LA, LB = [np.maximum(s.sum(2) / 3, 1e-7).astype(np.float32) for s in (A, B)]; eA, eB = LA.copy(), LB.copy(); done = 0; out = {}
bg = float(np.median(full.sum(2)[:60, :60]) / 3); globe = float((full.sum(2) / 3)[rho < 0.15].mean() - bg)
for r in rounds:
    while done < r: eA *= b(LA / np.maximum(b(eA), 1e-7)); eB *= b(LB / np.maximum(b(eB), 1e-7)); done += 1
    diff = (eA - eB) / 2; mean = (eA + eB) / 2; mm, _ = measure(mean)
    hp = lambda img: img - cv2.GaussianBlur(img, (0, 0), 5)
    row = dict(noise_on_globe=float(diff[globe_mask].std() / globe / np.sqrt(1)), noise_on_ring=float(diff[ring_mask].std() / globe), noise_in_sky=float(diff[sky_mask].std() / globe),
               fine_structure_on_globe_of_mean=float(hp(mean)[globe_mask].std() / globe), fine_noise_on_globe=float(hp(diff)[globe_mask].std() / globe), gap_contrast_of_mean=mm["gap_contrast"], ansa_width=mm["ansa_width_fwhm_arcsec"])
    out[r] = row
    print("%2d rounds: noise on the globe %.4f (fine scale %.4f), on the ring %.4f, in the sky %.4f of the globe; fine structure on the globe in the mean %.4f; gap contrast %.3f, ansa %.2f\"" % (r, row["noise_on_globe"], row["fine_noise_on_globe"], row["noise_on_ring"], row["noise_in_sky"], row["fine_structure_on_globe_of_mean"], row["gap_contrast_of_mean"], row["ansa_width"]))
json.dump(dict(note="noise = half the difference of the two half stacks after the same rounds: the noise of their mean, which is about the full stack's", rounds=out), open(stem + "-halves.json", "w"), indent=1)
