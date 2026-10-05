"""A second opinion on the blur, from the planet itself: Saturn's known shape (oblate globe with limb darkening; rings C, B, A and the
Cassini division at their catalogue radii, opened 7.45 deg as seen tonight) blurred by an elliptical Gaussian, fitted to the plain stack's
green plane. Free: the blur along and across the ring line, the globe's size, limb darkening, each ring's brightness, the centre.
This is a check on the Titan measurement, not a picture: nothing from this model goes into any output pixel.
Usage: psfmodel.py name=stack.npy ..."""
import sys, json
import numpy as np, cv2
from scipy.optimize import least_squares
FINE = 0.3955 / 3; SINB = 0.1297; STEP = 3                      # model grid: native pixels
def model(p, U, V, near):
    su, sv, Re, ld, bB, bA, bC, amp, du, dv = p
    u, v = U - du, V - dv
    Rp = Re * np.sqrt((1 - 0.098) ** 2 * (1 - SINB ** 2) + SINB ** 2); rho2 = (u / Re) ** 2 + (v / Rp) ** 2; on = rho2 < 1
    globe = np.where(on, 1 - ld * (1 - np.sqrt(np.clip(1 - rho2, 0, 1))), 0.0)
    r = np.hypot(u, v / SINB) / Re
    ring = np.where((r >= 1.236) & (r < 1.526), bC, 0.0) + np.where((r >= 1.526) & (r < 1.951), bB, 0.0) + np.where((r >= 2.027) & (r < 2.269), bA, 0.0)
    front = (v * near > 0)                                        # the near half of the rings passes in front of the globe
    img = np.where(on, np.where(front & (ring > 0), np.maximum(ring, globe * (ring < bB)), globe), ring)
    k = lambda s: max(s / (FINE * SUB), 0.3)
    return amp * cv2.GaussianBlur(img.astype(np.float32), (0, 0), sigmaX=k(su), sigmaY=k(sv))
SUB = 1.0                                                         # model sampled on the fine grid itself, in the ring's frame
if __name__ == "__main__":
    out = {}
    for a in sys.argv[1:]:
        name, path = a.split("=", 1); s = np.load(path).astype(np.float32); g = s[:, :, 1]; n = g.shape[0]
        bg = np.median(np.concatenate([g[:70, :70].ravel(), g[-70:, -70:].ravel()])); g = g - bg
        from metrics import measure
        m, _ = measure(s[:, :, 1]); cx, cy = m["centre"]; ang = m["ring_line_deg"]
        # turn the data so the ring line is horizontal (bilinear; the data are smooth at this scale)
        M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0); M[0, 2] += n / 2 - cx; M[1, 2] += n / 2 - cy
        d = cv2.warpAffine(g, M, (n, n), flags=cv2.INTER_LINEAR); d = d[n // 2 - 130:n // 2 + 130, n // 2 - 250:n // 2 + 250]; d = d / d[115:145, 235:265].mean()
        yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]]; U = (xx - 250) * FINE; V = (yy - 130) * FINE
        best = None
        for near in (1, -1):
            p0 = [1.9, 1.9, 9.8, 0.6, 1.0, 0.6, 0.15, 1.2, 0.0, 0.0]
            f = lambda p: (model(p, U, V, near) - d)[::STEP, ::STEP].ravel()
            r = least_squares(f, p0, bounds=([0.5, 0.5, 8.5, 0, 0.2, 0.05, 0, 0.5, -2, -2], [4, 4, 11, 1, 3, 3, 1.5, 3, 2, 2]), x_scale=[0.3, 0.3, 0.3, 0.2, 0.3, 0.3, 0.2, 0.3, 0.3, 0.3], diff_step=0.02)
            rms = float(np.sqrt(np.mean(r.fun ** 2)))
            if best is None or rms < best[0]: best = (rms, near, r.x)
        rms, near, p = best
        out[name] = dict(fwhm_along_ring_arcsec=round(2.355 * p[0], 2), fwhm_across_ring_arcsec=round(2.355 * p[1], 2), globe_equatorial_radius_arcsec=round(p[2], 2), limb_darkening=round(p[3], 2),
                         ring_brightness=dict(B=round(p[4], 2), A=round(p[5], 2), C=round(p[6], 2)), residual_rms_of_globe=round(rms, 4), near_side="+v" if near > 0 else "-v")
        print(name, json.dumps(out[name]))
        mo = model(p, U, V, near); pan = np.vstack([d, mo, np.abs(d - mo) * 5]); cv2.imwrite("stacks/psfmodel-%s.png" % name, (np.clip(pan / 1.2, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8))
    json.dump(out, open("stacks/psfmodel.json", "w"), indent=1)
