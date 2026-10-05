"""What does the finishing step do to a Saturn whose true shape is known? A check on the method, not a picture: the model planet
(psfmodel.py's, with the fitted sizes and brightnesses) is blurred by the measured blur, given the stack's grain, and put through
the same Richardson-Lucy. Where the result departs from the truth in a way the real result also shows, that feature is the method's.
Also on the real stack: the globe's brightness ring by ring (elliptical rings about the centre), plain against deconvolved, for several rounds.
Usage: rlcheck.py <stem>"""
import sys, json
import numpy as np, cv2
import psfmodel as pm
from metrics import measure, sample
FINE = pm.FINE
stem = sys.argv[1]; rec = json.load(open(stem + ".json")); fin = rec["finish"]; stack = np.load(stem + ".npy").astype(np.float32)
f1, f2 = fin["psf_fwhm_arcsec"]; th = np.radians(fin["psf_long_axis_deg_in_picture"])
def kernel(f1, f2, th):
    k1, k2 = f1 / 2.355 / FINE, f2 / 2.355 / FINE; h = int(np.ceil(4 * k1)); ky, kx = np.mgrid[-h:h + 1, -h:h + 1]; u = kx * np.cos(th) + ky * np.sin(th); v = -kx * np.sin(th) + ky * np.cos(th)
    K = np.exp(-u * u / (2 * k1 * k1) - v * v / (2 * k2 * k2)).astype(np.float32); return K / K.sum()
def rl(L, K, rounds):
    L = np.maximum(L, 1e-7).astype(np.float32); est = L.copy(); b = lambda a: cv2.filter2D(a, -1, K, borderType=cv2.BORDER_REFLECT_101)
    for _ in range(rounds): est *= b(L / np.maximum(b(est), 1e-7))
    return est
# ---- the real stack: grain on the globe, and the globe ring by ring ----
L = stack.sum(2) / 3; m, _ = measure(stack[:, :, 1]); cx, cy = m["centre"]; ang = np.radians(m["ring_line_deg"]); n = L.shape[0]; yy, xx = np.mgrid[0:n, 0:n]
u = (xx - cx) * np.cos(ang) + (yy - cy) * np.sin(ang); v = -(xx - cx) * np.sin(ang) + (yy - cy) * np.cos(ang)
Re = 9.84 / FINE; Rp = Re * 0.903; rho = np.hypot(u / Re, v / Rp); bg = np.median(L[:60, :60]); globe = float(L[rho < 0.15].mean() - bg)
grain = float((L - cv2.GaussianBlur(L, (0, 0), 5))[rho < 0.6].std() / globe)
K = kernel(f1, f2, th); print("blur %.2f x %.2f arcsec at %.0f deg; grain on the globe in the plain stack %.4f of its brightness" % (f1, f2, np.degrees(th), grain))
off_ring = np.abs(v) > 3.2 / FINE                       # away from the ring line, where the globe alone is seen
edges = np.arange(0, 1.8, 0.1)
def rings(img):
    return [float(img[(rho >= a) & (rho < a + 0.1) & (off_ring | (rho < 0.3))].mean() - bg) / globe for a in edges]
print("the globe ring by ring, away from the ring line (fraction of the radius: brightness, centre = about 1)")
print("  radius   " + " ".join("%5.1f" % a for a in edges + 0.05)); print("  plain    " + " ".join("%5.3f" % x for x in rings(L)))
res = {}
for r in (4, 8, 12, 20, 30):
    e = rl(L, K, r); p = rings(e); res[r] = p; g = float((e - cv2.GaussianBlur(e, (0, 0), 5))[rho < 0.6].std() / globe)
    inner = max(p[:9]); out = p[10:]; dark = min(out[i] - max(out[i + 1:]) for i in range(len(out) - 1))
    print("  %2d rounds " % r + " ".join("%5.3f" % x for x in p) + "   brightest ring inside the globe %.3f at %.2f R; sky dips below what lies further out by %.4f; grain %.4f" % (inner, edges[int(np.argmax(p[:9]))] + 0.05, max(0, -dark), g))
# ---- the model planet through the same steps ----
pmod = json.load(open("stacks/psfmodel.json")).get(stem.split("/")[-1]); 
if pmod:
    yy2, xx2 = np.mgrid[0:360, 0:560]; U = (xx2 - 280) * FINE; V = (yy2 - 180) * FINE; rb = pmod["ring_brightness"]
    par = [0.01, 0.01, pmod["globe_equatorial_radius_arcsec"], pmod["limb_darkening"], rb["B"], rb["A"], rb["C"], 1.0, 0, 0]
    truth = pm.model(par, U, V, -1 if pmod["near_side"] == "-v" else 1); Km = kernel(f1, f2, th - ang)      # the model's ring line is level
    seen = cv2.filter2D(truth, -1, Km, borderType=cv2.BORDER_REFLECT_101); rng = np.random.default_rng(7)
    noise = cv2.GaussianBlur(rng.normal(0, 1, seen.shape).astype(np.float32), (0, 0), 1.5); noise *= grain / noise.std(); seen_n = seen + noise * np.sqrt(np.clip(seen, 0.02, None))
    row = lambda img: " ".join("%5.3f" % float(img[178:183, 280 + int(a / FINE)].mean()) for a in (0, 2, 4, 6, 8, 9, 10, 12, 14, 16, 18, 20, 22, 24))
    col = lambda img: " ".join("%5.3f" % float(img[180 + int(a / FINE), 278:283].mean()) for a in (3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14))
    print("model planet, along the ring line at 0 2 4 6 8 9 10 12 14 16 18 20 22 24 arcsec:"); print("  truth      " + row(truth)); print("  blurred    " + row(seen))
    for r in (4, 8, 12, 20, 30): print("  %2d rounds  " % r + row(rl(seen_n, Km, r)))
    print("model planet, along the polar axis at 3 4 5 6 7 8 9 10 11 12 14 arcsec:"); print("  truth      " + col(truth)); print("  blurred    " + col(seen))
    for r in (4, 8, 12, 20, 30): print("  %2d rounds  " % r + col(rl(seen_n, Km, r)))
