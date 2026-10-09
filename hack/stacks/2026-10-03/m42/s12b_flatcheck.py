"""Step 12b: a check of the flat's large-scale shape from the sky itself (nothing is changed by it).

Two stacks that share a patch of sky see it through different parts of the sensor. If the flat is right and
everything in a frame came through the optics, their faint ground differs there by a constant. If part of a frame's
level did NOT come through the optics like the sky (a black level a few DN off, or light scattered inside the
tube), dividing by the flat turns that part, d, into d / flat: a bowl. So for every 64 px block that two stacks
share, away from the bright nebula:   a - b = constant_a - constant_b + d_a / flat_a - d_b / flat_b
and d is found by least squares (per colour; the four stacks taken under a clear sky only), once as ONE d for all
stacks and once as a d per stack. A d that is not zero says: the faint ground of a stack is off by d x (1 / flat -
1) toward its corners (flat is about 0.8 at the edges and 0.71 at the corners, so by a quarter to 0.4 of d).
This is reported, and NOT applied: it is one number per colour that cannot be told apart, from these frames,
from an error of the flat's own shape or from glare of the bright core, and it would be a second background term."""
import json, itertools, warnings
import numpy as np, cv2
from common import *
warnings.simplefilter('ignore')
PL = json.load(open(W('s10_place.json'))); R9 = json.load(open(W('s11_resample.json'))); grid = PL['grid']; BS = 64
IMAGES = PL['images']; MULT = PL['photometric_multipliers']['G']
z = np.load(W('s12_blocks.npz')); tabs = {k: (z[k + '_T'], z[k + '_N']) for k in IMAGES}
NBX, NBY = grid['width'] // BS + 1, grid['height'] // BS + 1
PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['trapezium_pixel']
CLEAR = [k for k in IMAGES if k in ('deep', 'p00', 'p10', 'stray1')]


def to_mosaic(M):
    M = np.array(M); A = -M / PS; A[0, 2] += X0; A[1, 2] += Y0; return A


INV = {}
for k in CLEAR:
    fr = np.load(W(k + '_flatref.npy')); f3 = np.dstack([fr[0], (fr[1] + fr[2]) / 2, fr[3]])
    A = to_mosaic(PL['affine_to_tangent_plane_arcsec'][k]); x0, y0, x1, y1 = R9[k]['bbox']
    Ab = A.copy(); Ab[0, 2] -= x0; Ab[1, 2] -= y0
    w = cv2.warpAffine((1.0 / f3).astype(np.float32), Ab, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(np.nan,) * 3)
    T = np.full((NBY, NBX, 3), np.nan, np.float32)
    for by in range(y0 // BS, (y1 - 1) // BS + 1):
        for bx in range(x0 // BS, (x1 - 1) // BS + 1):
            ya, yb = max(by * BS - y0, 0), min((by + 1) * BS - y0, y1 - y0); xa, xb = max(bx * BS - x0, 0), min((bx + 1) * BS - x0, x1 - x0)
            if ya >= yb or xa >= xb: continue
            T[by, bx] = np.nanmedian(w[ya:yb, xa:xb].reshape(-1, 3), axis=0)
    INV[k] = T * MULT[k]
BY, BX = np.mgrid[0:NBY, 0:NBX]; XC = (BX + 0.5) * BS; YC = (BY + 0.5) * BS
RC = np.hypot(XC - X0, YC - Y0) * PS / 60
floor_g = float(np.nanpercentile(tabs['deep'][0][:, :, 1], 2))
n_p = len(CLEAR) - 1
out = dict(stacks=CLEAR, flat=json.load(open(W('s6_flat.json')))['source'])
for c, cn in enumerate('RGB'):
    rows, rhs, wts = [], [], []
    for a, b in itertools.combinations(CLEAR, 2):
        Ta, Na = tabs[a]; Tb, Nb = tabs[b]
        ok = np.isfinite(Ta[:, :, c]) & np.isfinite(Tb[:, :, c]) & np.isfinite(INV[a][:, :, c]) & np.isfinite(INV[b][:, :, c]) & (RC > 6)
        for by, bx in zip(*np.nonzero(ok)):
            g = max(float(min(Ta[by, bx, 1], Tb[by, bx, 1]) - floor_g), 0.0)
            if g > 300: continue
            r = np.zeros(n_p + len(CLEAR) + 1)
            if a != 'deep': r[CLEAR.index(a) - 1] = 1
            if b != 'deep': r[CLEAR.index(b) - 1] = -1
            r[n_p + CLEAR.index(a)] = INV[a][by, bx, c]; r[n_p + CLEAR.index(b)] = -INV[b][by, bx, c]
            r[-1] = INV[a][by, bx, c] - INV[b][by, bx, c]
            rows.append(r); rhs.append(float(Ta[by, bx, c] - Tb[by, bx, c])); wts.append(1.0 / (Na[by, bx] ** 2 + Nb[by, bx] ** 2 + 1) / (1 + (g / 150.0) ** 2))
    A = np.array(rows); d = np.array(rhs); sw = np.sqrt(np.array(wts)); res_ = {}
    for nm, cols in (('constants_only', list(range(n_p))), ('one_pedestal', list(range(n_p)) + [A.shape[1] - 1]), ('a_pedestal_per_stack', list(range(n_p + len(CLEAR))))):
        Ac = A[:, cols]; keep = np.ones(len(d), bool)
        for _ in range(5):
            sol, *_ = np.linalg.lstsq(Ac[keep] * sw[keep, None], d[keep] * sw[keep], rcond=None); res = d - Ac @ sol; zz = res * sw; keep = np.abs(zz) < 3 * 1.4826 * np.median(np.abs(zz[keep]))
        Aw = Ac[keep] * sw[keep, None]; err = np.sqrt(np.diag(np.linalg.pinv(Aw.T @ Aw) * (1.4826 * np.median(np.abs(zz[keep]))) ** 2))
        res_[nm] = (sol, err, float(np.sqrt(np.mean(res ** 2))))
    out[cn] = dict(blocks=int(len(d)), rms_dn=dict(constants_only=res_['constants_only'][2], one_pedestal=res_['one_pedestal'][2], a_pedestal_per_stack=res_['a_pedestal_per_stack'][2]),
                   one_pedestal_dn=dict(d=float(res_['one_pedestal'][0][-1]), error=float(res_['one_pedestal'][1][-1])),
                   pedestal_per_stack_dn={k: dict(d=float(res_['a_pedestal_per_stack'][0][n_p + i]), error=float(res_['a_pedestal_per_stack'][1][n_p + i])) for i, k in enumerate(CLEAR)})
    print('%s: %d blocks; rms constants only %.2f DN, one pedestal %.2f (d = %+.1f +- %.1f DN), a pedestal per stack %.2f (%s)' % (cn, len(d), res_['constants_only'][2], res_['one_pedestal'][2], res_['one_pedestal'][0][-1], res_['one_pedestal'][1][-1], res_['a_pedestal_per_stack'][2],
          ', '.join('%s %+.1f' % (k, res_['a_pedestal_per_stack'][0][n_p + i]) for i, k in enumerate(CLEAR))))
json.dump(out, open(W('s12b_flatcheck.json'), 'w'), indent=1)
