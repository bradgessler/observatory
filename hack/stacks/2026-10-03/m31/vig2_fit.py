"""Vignetting, part 2: fit a smooth, radially symmetric, centred profile to the sky flats of part 1 and look
at how far the data really is radially symmetric and centred.
Model for a block at sensor (x, y), r = distance from the sensor centre, rho = r / 3000:
    F = k * (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) * (1 + gx (x - xc)/3000 + gy (y - yc)/3000)
The gradient factor is the sky's own slope across the field (or a decentred vignette; the two cannot be told
apart from one sky): it is fitted so that it does not bias the radial part, and it is NOT applied to the M31 frames.
Also fitted, as checks: the same without the gradient, and with a free centre."""
import json, numpy as np
from common import *
from scipy.optimize import least_squares
d = np.load(W('vig_skyflats.npz')); BS = int(d['bs'])
def table(key, p):
    v = d[key]; ny, nx = v.shape; ox, oy = OFFS[p]
    Y, X = np.mgrid[0:ny, 0:nx]
    x = 2 * (X * BS + (BS - 1) / 2) + ox; y = 2 * (Y * BS + (BS - 1) / 2) + oy
    m = np.isfinite(v)
    return x[m], y[m], v[m]
def radial(c, rho): return 1 + c[0] * rho ** 2 + c[1] * rho ** 4 + c[2] * rho ** 6
def fit(x, y, v, gradient=True, free_centre=False, robust=True):
    def model(q, x, y):
        cx, cy = (CENTRE[0] + q[6], CENTRE[1] + q[7]) if free_centre else CENTRE
        rho = np.hypot(x - cx, y - cy) / 3000
        g = (1 + q[4] * (x - CENTRE[0]) / 3000 + q[5] * (y - CENTRE[1]) / 3000) if gradient else 1.0
        return q[0] * radial(q[1:4], rho) * g
    q0 = np.array([np.median(v), -0.2, 0, 0, 0, 0, 0, 0], float)
    keep = np.ones(len(v), bool)
    for _ in range(4):
        r = least_squares(lambda q: model(q, x[keep], y[keep]) - v[keep], q0, x_scale=[1, 1, 1, 1, 0.1, 0.1, 300, 300])
        q0 = r.x; res = v - model(q0, x, y); s = 1.4826 * np.median(np.abs(res[keep] - np.median(res[keep])))
        if robust: keep = np.abs(res) < 3 * s
    return q0, float(np.sqrt((res[keep] ** 2).mean())), res, keep
RR = np.array([0, 500, 1000, 1500, 2000, 2500, 3000, 3300, 3600])
rep = {}
for run in ('m15', 'ngc', 'cloud'):
    for p in range(4):
        key = run + '_' + PLANE_NAMES[p]
        x, y, v = table(key, p)
        r = np.hypot(x - CENTRE[0], y - CENTRE[1])
        qg, rms_g, res_g, keep = fit(x, y, v, True)
        qn, rms_n, _, _ = fit(x, y, v, False)
        qc, rms_c, _, _ = fit(x, y, v, True, True)
        prof = radial(qg[1:4], RR / 3000)
        print('%s sky %.1f DN: blocks %d (r %.0f..%.0f)  radial+gradient: a = %s  gradient = (%+.4f, %+.4f) per 3000 px  rms %.4f | no gradient: a = %s rms %.4f | free centre: offset (%+.0f, %+.0f) px a = %s rms %.4f' % (
            key, float(d[run + '_sky_' + PLANE_NAMES[p]]), len(v), r.min(), r.max(), np.round(qg[1:4], 4).tolist(), qg[4], qg[5], rms_g, np.round(qn[1:4], 4).tolist(), rms_n, qc[6], qc[7], np.round(qc[1:4], 4).tolist(), rms_c))
        print('      V(r) at r = %s px: %s' % (RR.tolist(), np.round(prof, 4).tolist()))
        # measured ring medians of the data with the fitted gradient divided out, against the fit
        g = 1 + qg[4] * (x - CENTRE[0]) / 3000 + qg[5] * (y - CENTRE[1]) / 3000
        ring = []
        for a, b in zip(range(0, 3600, 300), range(300, 3900, 300)):
            m = (r >= a) & (r < b)
            if m.sum() > 20: ring.append((a, b, int(m.sum()), float(np.median(v[m] / g[m] / qg[0])), float(radial(qg[1:4], (a + b) / 2 / 3000))))
        print('      rings (r0, r1, blocks, measured, fit):', ' '.join('%d-%d:%d:%.4f/%.4f' % t for t in ring))
        rep[key] = dict(sky_dn=float(d[run + '_sky_' + PLANE_NAMES[p]]), blocks=int(len(v)), a=qg[1:4].tolist(), k=float(qg[0]), gradient_per_3000px=[float(qg[4]), float(qg[5])], rms=rms_g,
                        no_gradient=dict(a=qn[1:4].tolist(), rms=rms_n), free_centre=dict(offset_px=[float(qc[6]), float(qc[7])], a=qc[1:4].tolist(), rms=rms_c),
                        V_at_r=dict(zip([str(v_) for v_ in RR.tolist()], [float(v_) for v_ in prof])), rings=ring)
json.dump(rep, open(W('vig_fit.json'), 'w'), indent=1)
