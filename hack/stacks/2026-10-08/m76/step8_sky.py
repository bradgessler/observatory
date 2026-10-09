"""Step 8: the sky left in the stack after the per-frame constants. There were no flats, so the sky glow comes
through the telescope's vignetting as a dome, brightest near the optical axis, about 3.5 DN (green) across the
picture's area round M76. A per-frame constant cannot remove a dome, and a surface fitted round the object would be
free to take the object's faint light. So the dome is measured from the whole 38 x 25 arcmin stack, outside 4.3
arcmin of M76 and away from every star: sky(x, y) = a + gx x + gy y + b r^2 + c r^4 + d r^6, r the distance from a
fitted optical centre (vignetting is round about the axis; the plane is the sky's own slope). Fitted per colour to
3-sigma-clipped medians of 40 x 40 px blocks, robustly (soft L1, then blocks off by more than 4 sigma left out:
dust shadows). Under M76 the model is set by the same radius from the optical centre at all the other position
angles, never by the object. This changes no stack: the model is evaluated on the north-up grid and step 10
subtracts it from the picture only (m76-stack.tif keeps the per-frame constants alone)."""
import json, os
import numpy as np, cv2
from scipy.optimize import least_squares
from common import *

MASK_R = 330          # stack px (4.3 arcmin) round the catalogue position left out of the fit
B = 40
st = np.load(W('ref_stack.npy')); g7 = json.load(open(W('step7_grid.json'))); s6 = json.load(open(W('step6_ref.json'))); s2 = json.load(open(W('step2.json')))
f2 = {f['stamp']: f for f in s2['frames']}
wb = np.median(np.array([f2[s]['wb'] for s in s6['used']]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
hh, ww = st.shape[1:]
u0, v0 = g7['target']['stack_px']
CH = [st[0] * wb_r, (st[1] + st[2]) / 2, st[3] * wb_b]
G = CH[1]
yy, xx = np.mgrid[0:hh, 0:ww]
sm = cv2.GaussianBlur(G, (0, 0), 2.0); m0, s0, _ = clipped_stats(sm[::3, ::3])
bgL = cv2.resize(cv2.medianBlur(cv2.resize(G, (ww // 16, hh // 16), interpolation=cv2.INTER_AREA), 5), (ww, hh))
star = cv2.dilate(((sm - bgL) > 3.5 * s0).astype(np.uint8), np.ones((13, 13), np.uint8)).astype(bool)
mask = ~star & (np.hypot(xx - u0, yy - v0) > MASK_R)
bl = []
for j in range(0, hh - B + 1, B):
    for i in range(0, ww - B + 1, B):
        m = mask[j:j + B, i:i + B]
        if m.mean() > 0.6:
            bl.append([i + B / 2, j + B / 2] + [clipped_stats(P[j:j + B, i:i + B][m])[2] for P in CH])
bl = np.array(bl); X, Y = bl[:, 0], bl[:, 1]


def model(p, X, Y):
    a, gx, gy, xc, yc, b, c, d = p
    r2 = ((X - xc) ** 2 + (Y - yc) ** 2) / 1500.0 ** 2
    return a + gx * (X - ww / 2) / 1000 + gy * (Y - hh / 2) / 1000 + b * r2 + c * r2 ** 2 + d * r2 ** 3


fits = {}
for k, nm in enumerate('RGB'):
    z = bl[:, 2 + k]; p0 = [float(z.max()), 0, 0, ww / 2, hh / 2, -10, 0, 0]; w = np.ones(len(z))
    for it in range(4):
        r = least_squares(lambda p: (model(p, X, Y) - z) * w, p0, loss='soft_l1', f_scale=1.0)
        res = z - model(r.x, X, Y); s = 1.4826 * np.median(np.abs(res)); w = (np.abs(res) < 4 * s).astype(float); p0 = r.x
    near = np.hypot(X - u0, Y - v0) < 700
    ang = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    pm = float(model(r.x, np.array([u0]), np.array([v0]))[0])
    rings = {str(R): dict(mean_below_centre=pm - float(model(r.x, u0 + R * np.cos(ang), v0 + R * np.sin(ang)).mean()), range=float(np.ptp(model(r.x, u0 + R * np.cos(ang), v0 + R * np.sin(ang))))) for R in (100, 200, 330)}
    fits[nm] = dict(params=dict(zip(['a', 'gx_per_1000px', 'gy_per_1000px', 'xc', 'yc', 'b_r2', 'c_r4', 'd_r6'], [float(v) for v in r.x])), r_unit_px=1500.0, x_y_origin='stack px, gx gy about the stack centre',
                    blocks_used=int(w.sum()), blocks=int(len(z)), resid_robust_sigma_dn=float(s), resid_rms_330_700px_from_m76=float(res[near & (w > 0)].std()), resid_mean_330_700px_from_m76=float(res[near & (w > 0)].mean()),
                    model_at_m76_dn=pm, rings_round_m76=rings)
    print(nm, json.dumps(fits[nm]))
    # residual map near M76 (blocks), for the log
    if nm == 'G':
        print('green residual blocks within 700 px of M76 (DN):')
        for yb in range(int(v0) - 700, int(v0) + 701, 120):
            line = []
            for xb in range(int(u0) - 700, int(u0) + 701, 120):
                d = np.hypot(X - xb, Y - yb); j = int(np.argmin(d))
                line.append('%+5.1f' % res[j] if d[j] < 40 else '   . ')
            print('   ' + ' '.join(line))
# the model on the north-up grid (white-balanced R, G, B, DN)
A = np.array(g7['out_to_stack']); gw, gh = g7['size']
gy_, gx_ = np.mgrid[0:gh, 0:gw].astype(np.float64)
U = A[0, 0] * gx_ + A[0, 1] * gy_ + A[0, 2]; V = A[1, 0] * gx_ + A[1, 1] * gy_ + A[1, 2]
north_sky = np.stack([model(list(fits[nm]['params'].values()), U, V) for nm in 'RGB']).astype(np.float32)
np.save(W('north_sky.npy'), north_sky)
json.dump(dict(model='a + gx (x - w/2)/1000 + gy (y - h/2)/1000 + b r2 + c r2^2 + d r2^3, r2 = ((x - xc)^2 + (y - yc)^2) / 1500^2, stack px, white-balanced DN', mask_radius_stack_px=MASK_R, block_px=B,
               white_balance=dict(R=wb_r, B=wb_b), fits=fits, north_grid_range_dn={nm: [float(north_sky[k].min()), float(north_sky[k].max())] for k, nm in enumerate('RGB')}), open(W('step8_sky.json'), 'w'), indent=1)
