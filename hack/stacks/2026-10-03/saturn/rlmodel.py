"""When would the finishing step draw a rim of its own? rlcheck.py's model planet (psfmodel.py's Saturn of known shape, with the sizes and
brightnesses fitted to this stack), blurred by exactly the blur that is divided out, given the stack's grain, and put through the same
Richardson-Lucy. The same rim measure as rounds.py (the globe brightening outward before the limb, away from the ring line), for each number
of rounds and several noise seeds. On the true planet nothing brightens outward, so any rise here is the method's.
A check, not a picture: no pixel of the model goes into any output.
Usage: rlmodel.py <stem> [rounds ...]"""
import sys, json
import numpy as np, cv2
import psfmodel as pm
from rounds import kernel, rim_of
from metrics import measure
FINE = pm.FINE; stem = sys.argv[1]; rounds = [int(a) for a in sys.argv[2:]] or [0, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20]
rec = json.load(open(stem + ".json")); fin = rec["finish"]; f1, f2 = fin["psf_fwhm_arcsec"]; th = np.radians(fin["psf_long_axis_deg_in_picture"]); stack = np.load(stem + ".npy").astype(np.float32)
m, _ = measure(stack[:, :, 1]); ang = np.radians(m["ring_line_deg"]); _, grain, _ = rim_of(stack.sum(2) / 3, stack[:, :, 1])
pmod = json.load(open("stacks/psfmodel.json"))[stem.split("/")[-1]]; rb = pmod["ring_brightness"]; Re = pmod["globe_equatorial_radius_arcsec"]
yy, xx = np.mgrid[0:360, 0:560]; U = (xx - 280) * FINE; V = (yy - 180) * FINE
truth = pm.model([0.01, 0.01, Re, pmod["limb_darkening"], rb["B"], rb["A"], rb["C"], 1.0, 0, 0], U, V, -1 if pmod["near_side"] == "-v" else 1)
Km = kernel(f1, f2, th - ang); seen = cv2.filter2D(truth, -1, Km, borderType=cv2.BORDER_REFLECT_101)                 # the model's ring line is level
Rp = Re * np.sqrt((1 - 0.098) ** 2 * (1 - pm.SINB ** 2) + pm.SINB ** 2); rho = np.hypot(U / Re, V / Rp); wedge = np.abs(V) > 3.6; edges = np.arange(0.4, 0.95, 0.05)
def rim(img):
    p = [float(img[(rho >= a) & (rho < a + 0.05) & wedge].mean()) for a in edges]; return max(max(max(p[i + 1:]) - p[i] for i in range(len(p) - 1)), 0.0), p
b = lambda a: cv2.filter2D(a, -1, Km, borderType=cv2.BORDER_REFLECT_101); out = {}
print("blur %.2f x %.2f arcsec; grain %.4f; the true model: rim %.3f; blurred: rim %.3f" % (f1, f2, grain, rim(truth)[0], rim(seen)[0]))
res = {r: [] for r in rounds}
for seed in range(6):
    rng = np.random.default_rng(seed); noise = cv2.GaussianBlur(rng.normal(0, 1, seen.shape).astype(np.float32), (0, 0), 1.5); noise *= grain / noise.std()
    L = np.maximum(seen + (noise * np.sqrt(np.clip(seen, 0.02, None)) if seed else 0), 1e-7).astype(np.float32); est = L.copy(); done = 0      # seed 0: no noise
    for r in rounds:
        while done < r: est *= b(L / np.maximum(b(est), 1e-7)); done += 1
        res[r].append(rim(est)[0])
for r in rounds: print("%2d rounds: rim on the model planet %.3f without noise; with the stack's grain %.3f (%.3f to %.3f over 5 seeds)" % (r, res[r][0], np.mean(res[r][1:]), min(res[r][1:]), max(res[r][1:])))
json.dump({str(r): dict(no_noise=round(res[r][0], 4), with_grain_mean=round(float(np.mean(res[r][1:])), 4), with_grain_max=round(max(res[r][1:]), 4)) for r in rounds}, open(stem + "-rlmodel.json", "w"), indent=1)
