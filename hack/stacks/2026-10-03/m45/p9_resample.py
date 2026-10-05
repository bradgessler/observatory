"""Step 9: bring every stack onto the one fine grid (tangent plane about RA 56.75 Dec +24.20, north up, east left,
0.7763 arcsec per pixel: the half grid's own scale), in common units, with a noise weight and a feather for each.
Adapted from the M31 mosaic's m9_resample.py.

Per stack: planes -> RGB (R x the as-shot white balance, G = mean of G1 and G2, B x white balance), x the stack's
photometric multiplier (step 8, the green one for all three colours), resampled with the affine map of step 8
(Lanczos-4, about 1:1: only a turn of about 26 degrees and a mirror).

Noise weight (one map per stack, the same for all three colours so that weights cannot tint anything): the
inverse variance of green in one fine-grid pixel, in common units: summed frame weights at the pixel x flat^2 /
(multiplier x single-frame noise of green)^2; the vignetting correction makes the corners noisier and that is in it.
Quality: pixels under a mapped dust shadow (divided by the shadow's measured transmission) count a quarter.
Feather: distance to the nearest pixel without data (frame edge, the hair's hole): the first 40 px are left out
altogether (there the frames of a stack do not all overlap), then a smoothstep ramp over the next 200 px, so a
stack's weight reaches zero exactly where its data stop. Also carried along: which pixels were at the sensor's ceiling in any frame, and the number of frames used."""
import json, os
import numpy as np, cv2
from c import *

PL = json.load(open(W('p8_place.json'))); grid = PL['grid']; PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['centre_pixel']
MULT = PL['photometric_multipliers']['G']; WB_R, WB_B = PL['white_balance']['R'], PL['white_balance']['B']
RAMP = 200.0; CUT = 40.0
SEL = json.load(open(W('p5_select.json'))); NUSED = None; NUW = None
os.makedirs(W('grid'), exist_ok=True)


def to_grid(M, ps=PS, x0=X0, y0=Y0):
    """2x3 matrix: stack half-grid pixel (x, y, 1) -> grid pixel (X, Y) of a grid with scale ps and centre pixel (x0, y0)."""
    M = np.array(M); A = -M / ps; A[0, 2] += x0; A[1, 2] += y0
    return A


def load(k):
    global NUSED
    NUSED = np.load(W(k + '_nused.npy'))
    P = np.load(W(k + '_planes.npy')); flag = np.load(W(k + '_flag.npy')); ws = np.load(W(k + '_wsum.npy')); fl = np.load(W(k + '_flatref.npy')); sat = np.load(W(k + '_sat.npy'))
    info6 = json.load(open(W('p6_%s.json' % k)))
    m = MULT[k]
    rgb = np.dstack([P[0] * WB_R, (P[1] + P[2]) / 2, P[3] * WB_B]).astype(np.float32) * np.float32(m)
    valid = (flag > 0) & np.isfinite(rgb).all(2)
    n1 = info6['single_frame_noise_dn']; var1 = (n1[1] ** 2 + n1[2] ** 2) / 4          # green of one clear frame, one half-grid pixel, before the flat
    invvar = np.where(valid, ws * fl ** 2 / (var1 * m * m), 0).astype(np.float32)
    q = np.where(flag == 2, 0.25, 1.0).astype(np.float32)
    dist = cv2.distanceTransform(np.pad(valid, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    t = np.clip((dist - CUT) / RAMP, 0, 1)
    feather = (t * t * (3 - 2 * t)).astype(np.float32)
    USE = SEL[k]['used']; wts = np.array([u['weight'] for u in USE]); tau = float((wts / np.array([u['transparency'] for u in USE])).sum() / wts.sum())
    return rgb, valid, invvar, q, feather, sat, dict(multiplier=m, mean_inverse_transparency_of_used_frames=tau, single_frame_green_variance=var1, noise_green_dn_common_units_at_full_coverage_centre=float(np.sqrt(var1) * m / np.sqrt(ws.max())))


def warp(k, loaded, A, size, bin_check=True):
    rgb, valid, invvar, q, feather, sat, info = loaded
    src = np.where(valid[:, :, None], rgb, np.nan).astype(np.float32)
    img = cv2.warpAffine(src, A, size, flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=(np.nan, np.nan, np.nan))
    wv = cv2.warpAffine(invvar, A, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    fe = cv2.warpAffine(feather, A, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    qq = cv2.warpAffine(q, A, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=1)
    st = cv2.warpAffine(sat.astype(np.float32), A, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0) > 0.02
    ok = np.isfinite(img).all(2) & (fe > 0.001)
    img[~ok] = np.nan; wv[~ok] = 0; fe[~ok] = 0; st &= ok
    global NUW
    NUW = np.where(ok, cv2.warpAffine(NUSED, A, size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0), 0).astype(np.uint8)
    return img, wv, fe, qq, st, ok


if __name__ == '__main__':
    out = {}
    for k in PL['images']:
        loaded = load(k); h, w = loaded[1].shape
        A = to_grid(PL['affine_to_tangent_plane_arcsec'][k])
        c_ = (A @ np.array([[-0.5, -0.5, 1], [w - 0.5, -0.5, 1], [w - 0.5, h - 0.5, 1], [-0.5, h - 0.5, 1]]).T).T
        bx0, by0 = int(np.floor(c_[:, 0].min())) - 2, int(np.floor(c_[:, 1].min())) - 2; bx1, by1 = int(np.ceil(c_[:, 0].max())) + 3, int(np.ceil(c_[:, 1].max())) + 3
        bx0, by0 = max(bx0, 0), max(by0, 0); bx1, by1 = min(bx1, grid['width']), min(by1, grid['height'])
        Ab = A.copy(); Ab[0, 2] -= bx0; Ab[1, 2] -= by0
        img, wv, fe, qq, st, ok = warp(k, loaded, Ab, (bx1 - bx0, by1 - by0))
        np.save(W('grid/%s_rgb.npy' % k), img); np.save(W('grid/%s_invvar.npy' % k), wv); np.save(W('grid/%s_feather.npy' % k), fe); np.save(W('grid/%s_q.npy' % k), qq); np.save(W('grid/%s_sat.npy' % k), st); np.save(W('grid/%s_nused.npy' % k), NUW)
        inner = fe > 0.99
        out[k] = dict(bbox=[bx0, by0, bx1, by1], to_fine_grid_pixels=A.tolist(), feather_ramp_px=RAMP, pixels_with_data=int(ok.sum()), area_sq_arcmin=float(ok.sum() * PS * PS / 3600),
                      noise_green_per_fine_px_common_units=dict(median=float(1 / np.sqrt(np.median(wv[ok]))), best=float(1 / np.sqrt(wv[ok].max())), median_inside_the_feather=float(1 / np.sqrt(np.median(wv[inner])))), **loaded[6])
        print('%-5s bbox %s  data %.0f sq arcmin; green noise per fine px in common units: median %.1f, best %.1f DN (multiplier %.4f)' % (k, out[k]['bbox'], out[k]['area_sq_arcmin'], out[k]['noise_green_per_fine_px_common_units']['median'], out[k]['noise_green_per_fine_px_common_units']['best'], loaded[6]['multiplier']), flush=True)
    json.dump(out, open(W('p9_resample.json'), 'w'), indent=1)
