"""How many rounds before the finishing step draws a ring of its own? For a stack and a blur, for each number of rounds:
  rim       how much the globe brightens outward before the limb, away from the ring line (the plain stack only ever dims outward:
            any brightening outward is a ring the method drew), as a fraction of the globe's brightness
  gap, ansa the same sharpness numbers as metrics.py, on the deconvolved brightness
  grain     pixel-to-pixel noise on the globe
Usage: rounds.py <stack.npy> <fwhm long> <fwhm short> <long axis deg> [rounds ...]"""
import sys, json
import numpy as np, cv2
from metrics import measure
FINE = 0.3955 / 3
def kernel(f1, f2, th):
    k1, k2 = f1 / 2.355 / FINE, f2 / 2.355 / FINE; h = int(np.ceil(4 * k1)); ky, kx = np.mgrid[-h:h + 1, -h:h + 1]; u = kx * np.cos(th) + ky * np.sin(th); v = -kx * np.sin(th) + ky * np.cos(th)
    K = np.exp(-u * u / (2 * k1 * k1) - v * v / (2 * k2 * k2)).astype(np.float32); return K / K.sum()
def rim_of(img, stackgreen):
    m, _ = measure(stackgreen); cx, cy = m["centre"]; ang = np.radians(m["ring_line_deg"]); n = img.shape[0]; yy, xx = np.mgrid[0:n, 0:n]
    u = (xx - cx) * np.cos(ang) + (yy - cy) * np.sin(ang); v = -(xx - cx) * np.sin(ang) + (yy - cy) * np.cos(ang)
    Re = 9.84 / FINE; Rp = Re * 0.903; rho = np.hypot(u / Re, v / Rp); bg = np.median(img[:60, :60]); globe = float(img[rho < 0.15].mean() - bg)
    wedge = np.abs(v) > 3.6 / FINE; edges = np.arange(0.4, 0.95, 0.05)
    p = [float(img[(rho >= a) & (rho < a + 0.05) & wedge].mean() - bg) / globe for a in edges]
    rise = max(max(p[i + 1:]) - p[i] for i in range(len(p) - 1)); grain = float((img - cv2.GaussianBlur(img, (0, 0), 5))[rho < 0.6].std() / globe)
    return max(rise, 0.0), grain, p
if __name__ == "__main__":
    stack = np.load(sys.argv[1]).astype(np.float32); f1, f2, th = float(sys.argv[2]), float(sys.argv[3]), np.radians(float(sys.argv[4])); rounds = [int(a) for a in sys.argv[5:]] or [0, 3, 4, 5, 6, 7, 8, 10, 12]
    K = kernel(f1, f2, th); b = lambda a: cv2.filter2D(a, -1, K, borderType=cv2.BORDER_REFLECT_101); L = np.maximum(stack.sum(2) / 3, 1e-7).astype(np.float32); est = L.copy(); done = 0
    for r in rounds:
        while done < r: est *= b(L / np.maximum(b(est), 1e-7)); done += 1
        g = stack[:, :, 1] * (est / L); m, _ = measure(g); rim, grain, p = rim_of(est, stack[:, :, 1])
        print("%2d rounds: rim %.3f  gap contrast %.3f  ansa width %.2f\"  ansa level E %.2f W %.2f  grain %.4f   globe outward: %s" % (r, rim, m["gap_contrast"], m["ansa_width_fwhm_arcsec"], m["east"].get("ansa_level", 0), m["west"].get("ansa_level", 0), grain, " ".join("%.3f" % x for x in p)))
