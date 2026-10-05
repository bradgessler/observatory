"""Step 11: bring every stack onto the one mosaic grid (tangent plane about the Trapezium, north up, east left,
0.776 arcsec per pixel), in the deep stack's units, with a noise weight and a feather for each (method of the
M31 mosaic run, m9_resample.py).

Per stack: planes -> R, G = mean of G1 and G2, B (no white balance yet), x the stack's photometric multiplier
(step 10, the green one for all three colours), resampled with the affine map of step 10 (Lanczos-4, about 1:1:
only a turn of about 24 degrees). The centred image is the HDR blend of step 9 (deep + short).

Noise weight (one map per stack, the same for all three colours so that weights cannot tint anything): the
inverse variance of green in one mosaic pixel, in deep units: variance = (multiplier x K)^2 / (summed frame
weights at the pixel x flat^2), K measured from the stack's half-stacks; the vignetting correction makes the
corners noisier and that is in it. Pixels from a stack's second combine (flag 2) count a quarter.
Feather: distance to the nearest pixel without data (frame edge, hair hole), ramp of 200 px for the panels
(smoothstep) and 300 px, fourth power, for the deep centred stack (it is 2 to 16 times heavier than a panel; a
plain ramp would hand over within the last few px and leave a hard change of grain). A panel's last 39 px before
any hole or edge (feather under 0.10) are left out: there the frames of a set do not all overlap.

White marks: the step-9 mask of the centred image, and for the panels every pixel that was near the ceiling in
any plane of any frame (grown by 2 px, softened), are resampled too. A panel's clipped pixel gets a thousandth
of its weight, so that where another stack has real data there, that is what shows."""
import json, os
import numpy as np, cv2
from common import *

PL = json.load(open(W('s10_place.json'))); grid = PL['grid']; PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['trapezium_pixel']
MULT = PL['photometric_multipliers']['G']
RAMP = dict(deep=300.0); POWER4 = ('deep',)
os.makedirs(W('grid'), exist_ok=True)


def to_mosaic(M):
    M = np.array(M); A = -M / PS; A[0, 2] += X0; A[1, 2] += Y0
    return A


def load(k):
    src = 'hdr' if k == 'deep' else k
    P = np.load(W(src + '_planes.npy')); flag = np.load(W(k + '_flag.npy')); ws = np.load(W(k + '_wsum.npy')); fr = np.load(W(k + '_flatref.npy')); d = np.load(W(k + '_dAB.npy'))
    m = MULT[k]
    rgb = np.dstack([P[0], (P[1] + P[2]) / 2, P[3]]).astype(np.float32) * np.float32(m)
    fl = (fr[1] + fr[2]) / 2
    valid = (flag > 0) & np.isfinite(rgb).all(2)
    dg = (d[1] + d[2]) / 2
    full = (flag == 1) & (ws >= 0.9 * ws.max()) & np.isfinite(dg)
    G = rgb[:, :, 1]; sm = cv2.blur(np.nan_to_num(G, nan=float(np.nanmedian(G))), (65, 65))
    faint = full & (sm <= np.percentile(sm[full], 25))
    K = clipped_stats((dg * np.sqrt(ws) * fl)[faint][::3])[1]
    invvar = np.where(valid, ws * fl ** 2 / (K * m) ** 2, 0).astype(np.float32)
    q = np.where(flag == 2, 0.25, 1.0).astype(np.float32)
    if k == 'deep':
        white = np.load(W('hdr_white.npy'))
    else:
        c = cv2.dilate((np.load(W(k + '_clip.npy')) > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        white = np.clip(cv2.GaussianBlur(c.astype(np.float32), (0, 0), 1.0) * 1.5, 0, 1); white[c > 0] = 1.0
    return rgb, valid, invvar, q, white.astype(np.float32), dict(K=float(K), multiplier=m, noise_green_dn_deep_units_at_full_coverage_centre=float(K * m / np.sqrt(ws.max())))


out = {}
for k in PL['images']:
    rgb, valid, invvar, q, white, info = load(k)
    h, w = valid.shape
    ramp = RAMP.get(k, 200.0)
    dist = cv2.distanceTransform(np.pad(valid, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    t = np.clip(dist / ramp, 0, 1)
    feather = (t ** 4 if k in POWER4 else t * t * (3 - 2 * t)).astype(np.float32)
    A = to_mosaic(PL['affine_to_tangent_plane_arcsec'][k])
    c = (A @ np.array([[-0.5, -0.5, 1], [w - 0.5, -0.5, 1], [w - 0.5, h - 0.5, 1], [-0.5, h - 0.5, 1]]).T).T
    bx0, by0 = int(np.floor(c[:, 0].min())) - 2, int(np.floor(c[:, 1].min())) - 2; bx1, by1 = int(np.ceil(c[:, 0].max())) + 3, int(np.ceil(c[:, 1].max())) + 3
    bx0, by0 = max(bx0, 0), max(by0, 0); bx1, by1 = min(bx1, grid['width']), min(by1, grid['height'])
    Ab = A.copy(); Ab[0, 2] -= bx0; Ab[1, 2] -= by0
    size = (bx1 - bx0, by1 - by0)
    src = np.where(valid[:, :, None], rgb, np.nan).astype(np.float32)
    img = cv2.warpAffine(src, Ab, size, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=(np.nan, np.nan, np.nan))
    wv = cv2.warpAffine(invvar, Ab, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    fe = cv2.warpAffine(feather, Ab, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    qq = cv2.warpAffine(q, Ab, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=1)
    wh = cv2.warpAffine(white, Ab, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    ok = np.isfinite(img).all(2)
    if k not in POWER4: ok &= fe >= 0.10
    else: ok &= fe > 0
    img[~ok] = np.nan
    wv[~ok] = 0; fe[~ok] = 0
    np.save(W('grid/%s_rgb.npy' % k), img); np.save(W('grid/%s_invvar.npy' % k), wv); np.save(W('grid/%s_feather.npy' % k), fe); np.save(W('grid/%s_q.npy' % k), qq); np.save(W('grid/%s_white.npy' % k), wh)
    inner = fe > 0.99
    out[k] = dict(bbox=[bx0, by0, bx1, by1], to_mosaic_pixels=A.tolist(), feather_ramp_px=ramp, pixels_with_data=int(ok.sum()), area_sq_arcmin=float(ok.sum() * PS * PS / 3600),
                  noise_green_per_mosaic_px_deep_units=dict(median=float(1 / np.sqrt(np.median(wv[ok]))), best=float(1 / np.sqrt(wv[ok].max())), median_inside_the_feather=float(1 / np.sqrt(np.median(wv[inner]))) if inner.any() else None), **info)
    print('%-7s bbox %s  data %.0f sq arcmin; green noise per mosaic px in deep units: median %.1f, best %.1f DN (multiplier %.4f)' % (k, out[k]['bbox'], out[k]['area_sq_arcmin'], out[k]['noise_green_per_mosaic_px_deep_units']['median'], out[k]['noise_green_per_mosaic_px_deep_units']['best'], info['multiplier']), flush=True)
json.dump(out, open(W('s11_resample.json'), 'w'), indent=1)
