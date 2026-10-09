"""Mosaic step 9: bring every image onto the one mosaic grid (tangent plane about the nucleus, north up, east
left, 0.776 arcsec per pixel), in the core stack's units, with a noise weight and a feather for each.

Per panel: planes -> RGB (R x the core's as-shot white balance, G = mean of G1 and G2, B x white balance), x the
panel's photometric multiplier (step 8, the green one for all three colours), resampled with the affine map of
step 8 (Lanczos-4, about 1:1: only a turn of about 34 degrees). The core stack: its 2 x 2 block mean, same resampling.

Noise weight (one map per image, the same for all three colours so that weights cannot tint anything): the
inverse variance of green in one mosaic pixel, in core units. Panels: variance = (multiplier x K)^2 / (summed
frame weights at the pixel x flat^2), K measured from the panel's half-stacks; the vignetting correction makes
the corners noisier and that is in it. Core: variance = K^2 / (frames used / 38 x flat^2), K from the core
recipe's measured noise (2 x 2 binned stack, green) at the place it was measured. The core's coverage file counts
the frames used with the dust left out; where that count is under 12 the core run blended in its combine with the
dust left in (all frames, later divided by the measured transmission), so there the frame count is taken as 38
and the quality as a quarter, blended as the core run blended (fully below 4).
Quality: pixels taken from a dust-divided combine count a quarter.
The core's own sensor shadows that are still in it (the hair, and the four smudges its recipe lists: its
m31-core-sensor-dust-map.png, transmission under 0.985, grown by 20 px) get NO weight: the panels cover that sky
with other parts of the sensor.
Feather: distance to the nearest pixel without data (frame edge, hair hole), ramp of 200 px for the panels
(smoothstep) and 300 px for the core's outer edge ((d / 300)^4: the core is 10 to 100 times heavier than a panel,
and a plain ramp would hand over within the last 30 px and leave a hard change of grain; the fourth power
spreads the handover over the ramp); round the core's masked shadows a 60 px smoothstep. A panel's last 39 px before any hole or edge
(feather under 0.10) are left out altogether: there the frames of a panel do not all overlap and single pixels
have no data, which would pepper the edge."""
import json, os
import numpy as np, cv2, tifffile
from mcommon import *

PL = json.load(open(W('m8_place.json'))); grid = PL['grid']; PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['nucleus_pixel']
MULT = PL['photometric_multipliers']['G']; WB_R, WB_B = PL['white_balance']['R'], PL['white_balance']['B']
core_rec = json.load(open(os.path.join(CORE_DIR, 'm31-core-recipe.json')))
FLAT = np.load(os.environ['M31_CORE_FLAT'] if os.environ.get('M31_CORE_FLAT') else CW('flat2d.npy')); FLATG = (FLAT[1] + FLAT[2]) / 2      # M31_CORE_FLAT: the flat a re-made core stack was divided by (for its noise map only)
RAMP = dict(core=300.0); POWER4 = ('core',)
os.makedirs(W('grid'), exist_ok=True)


def to_mosaic(M):
    """2x3 matrix: image pixel (x, y, 1) -> mosaic pixel (X, Y)."""
    M = np.array(M); A = -M / PS; A[0, 2] += X0; A[1, 2] += Y0
    return A


def load(k):
    if k == 'core':
        rgb = np.load(W('core_rgb.npy'))
        cov = tifffile.imread(os.path.join(CORE_DIR, 'm31-core-coverage.tif')).astype(np.float32)
        h, w = rgb.shape[:2]; n = cov[:2 * h, :2 * w].reshape(h, 2, w, 2).min((1, 3))
        org = core_rec['outputs']['m31-core-linear.tif']['origin']        # 'pixel (0,0) is sensor pixel (108,110) of the reference frame'
        ox, oy = [int(v) for v in org.split('(')[2].split(')')[0].split(',')]
        fl = FLATG[oy // 2:oy // 2 + h, ox // 2:ox // 2 + w]
        nz = core_rec['numbers']['noise']; s0 = nz['binned_2x2']['stack_white_balanced']['G']
        # where the core's noise was measured: sensor px x 1020..1520, y 304..804
        px0, py0 = (1020 - ox) // 2, (304 - oy) // 2
        Kc = s0 * float(np.sqrt(np.median(n[py0:py0 + 250, px0:px0 + 250]) / 38.0) * np.median(fl[py0:py0 + 250, px0:px0 + 250]))
        from PIL import Image
        dm = np.array(Image.open(os.path.join(CORE_DIR, 'm31-core-sensor-dust-map.png')))[:h, :w]       # 255 = no shadow, 0 = 20% lost
        shadow = cv2.dilate(((0.8 + 0.2 * dm / 255.0) < 0.985).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))).astype(bool)
        bl = np.clip((n - 4.0) / 8.0, 0, 1)                      # 1 = the dust-left-out combine, 0 = the dust-left-in combine
        neff = bl * n + (1 - bl) * 38.0
        valid = np.isfinite(rgb).all(2) & ~shadow
        invvar = np.where(valid, (neff / 38.0) * fl ** 2 / Kc ** 2, 0).astype(np.float32)
        q = (bl + (1 - bl) * 0.25).astype(np.float32)
        return rgb, valid, invvar, q, dict(K=Kc, noise_green_measured_dn=s0, multiplier=1.0, own_shadows_given_no_weight_px=int(shadow.sum()), pixels_from_its_dust_left_in_combine=int((bl < 0.5).sum())), shadow
    shadow = None
    P = np.load(W(k + '_planes.npy')); flag = np.load(W(k + '_flag.npy')); ws = np.load(W(k + '_wsum.npy')); fr = np.load(W(k + '_flatref.npy')); d = np.load(W(k + '_dAB.npy'))
    m = MULT[k]
    rgb = np.dstack([P[0] * WB_R, (P[1] + P[2]) / 2, P[3] * WB_B]).astype(np.float32) * np.float32(m)
    fl = (fr[1] + fr[2]) / 2
    valid = (flag > 0) & np.isfinite(rgb).all(2)
    dg = (d[1] + d[2]) / 2
    full = (flag == 1) & (ws >= 0.98 * ws.max()) & np.isfinite(dg)
    G = rgb[:, :, 1]; sm = cv2.blur(np.nan_to_num(G, nan=float(np.nanmedian(G))), (65, 65))
    faint = full & (sm <= np.percentile(sm[full], 50))
    K = clipped_stats((dg * np.sqrt(ws) * fl)[faint][::3])[1]
    invvar = np.where(valid, ws * fl ** 2 / (K * m) ** 2, 0).astype(np.float32)
    q = np.where(flag == 2, 0.25, 1.0).astype(np.float32)
    return rgb, valid, invvar, q, dict(K=float(K), multiplier=m, noise_green_dn_core_units_at_full_coverage_centre=float(K * m / np.sqrt(ws.max()))), None


out = {}
for k in PL['images']:
    rgb, valid, invvar, q, info, shadow = load(k)
    h, w = valid.shape
    ramp = RAMP.get(k, 200.0)
    edge_valid = valid | shadow if shadow is not None else valid
    dist = cv2.distanceTransform(np.pad(edge_valid, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    t = np.clip(dist / ramp, 0, 1)
    feather = (t ** 4 if k in POWER4 else t * t * (3 - 2 * t)).astype(np.float32)
    if shadow is not None:
        t2 = np.clip(cv2.distanceTransform((~shadow).astype(np.uint8), cv2.DIST_L2, 5) / 60.0, 0, 1)
        feather *= (t2 * t2 * (3 - 2 * t2)).astype(np.float32)
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
    ok = np.isfinite(img).all(2)
    if k != 'core': ok &= fe >= 0.10            # the last 39 px before any hole or edge: speckled with pixels that have no frame; left out
    img[~ok] = np.nan
    wv[~ok] = 0; fe[~ok] = 0
    np.save(W('grid/%s_rgb.npy' % k), img); np.save(W('grid/%s_invvar.npy' % k), wv); np.save(W('grid/%s_feather.npy' % k), fe); np.save(W('grid/%s_q.npy' % k), qq)
    inner = fe > 0.99
    out[k] = dict(bbox=[bx0, by0, bx1, by1], to_mosaic_pixels=A.tolist(), feather_ramp_px=ramp, pixels_with_data=int(ok.sum()), area_sq_arcmin=float(ok.sum() * PS * PS / 3600),
                  noise_green_per_mosaic_px_core_units=dict(median=float(1 / np.sqrt(np.median(wv[ok]))), best=float(1 / np.sqrt(wv[ok].max())), median_inside_the_feather=float(1 / np.sqrt(np.median(wv[inner]))) if inner.any() else None), **info)
    print('%-6s bbox %s  data %.0f sq arcmin; green noise per mosaic px in core units: median %.1f, best %.1f DN (multiplier %.4f)' % (k, out[k]['bbox'], out[k]['area_sq_arcmin'], out[k]['noise_green_per_mosaic_px_core_units']['median'], out[k]['noise_green_per_mosaic_px_core_units']['best'], info['multiplier']), flush=True)
json.dump(out, open(W('m9_resample.json'), 'w'), indent=1)
