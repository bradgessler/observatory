"""From stacked colour planes to a picture. Every step is one fixed formula applied to every pixel alike (Gaussian filters,
a pointwise curve, a matrix); nothing is generated, learned or drawn. Used by step 9 (the picture) and step 10 (the
deconvolved version), so both go through exactly the same finish.

  1. colour: R, G = mean of G1 and G2, B, times the camera's own daylight white balance (from the RAW, through LibRaw),
     then the camera's own colour matrix (rgb_xyz_matrix in the RAW, through the sRGB primaries, rows normalised so
     that daylight white stays white, as dcraw does): linear sRGB.
  2. brightness and colour, each at the resolution it can carry:
     L  = the four planes weighted by their inverse noise variance (white-balanced units), so the noisy red plane
          (little red sky light, one pixel in four, x 2.9 white balance) does not dominate; Gaussian of LUM_BLUR px
          (the stars are about 5 px across, half-flux diameter, so this widens them by about 10% and removes pixel
          noise finer than the telescope and air delivered).
     Stars that touched the sensor's ceiling (any plane above 85% of it): their cores have no true colour, so the
          pixels within CEIL_GROW px of them are left out of the colour average and shown white.
     C  = the linear sRGB after a Gaussian of CHROMA_BLUR px; its colour ratios C / L(C) are used.
     out = L x (w C / L(C) + (1 - w)), w = smoothstep of L(C) from COLOUR_FROM to COLOUR_FULL DN, and w = 0 on stars
          that touched the sensor's ceiling. Where the galaxy is faint its colour is set by how the sky and the flat were
          handled (the sky in the frames is 4 to 20 times brighter than the galaxy's outer light, and a 2 to 3% colour
          error in the flat moves R/G by 0.2 there), so it is shown grey; colour is shown where the light is bright
          enough to carry it: the nucleus, the brighter HII regions and clusters, the stars.
  3. stretch: arcsinh of L with the same gain for R, G and B of a pixel (colour ratios kept):
     v = PEDESTAL + (1 - PEDESTAL) x out x asinh(max(L - BLACK, 0) / SOFT) / (L x asinh(WHITE / SOFT)), clipped 0..1,
     then the sRGB transfer curve. BLACK sits just above the zero of the faint region (where the galaxy is faintest),
     so the darkest sky shows as near-black, neutral by construction (each colour's zero is measured on the same pixels).
  4. quiet sky: brightness (CIELAB L*) smoothed with a Gaussian of QUIET_SIGMA px where the picture is dark (fully below
     L* QUIET_FROM, not at all above QUIET_TO, judged on a blurred copy so stars keep their edges). Less faint detail,
     less grain, by choice.
  5. saturation: CIELAB chroma times SATURATION, faded out in the darkest parts and on near-white star cores."""
import numpy as np, cv2

XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
CEILING = 15488.0          # 16000 - 512: the raw ceiling above black

PARAMS = dict(LUM_BLUR=1.0, CHROMA_BLUR=4.0, COLOUR_FROM=20.0, COLOUR_FULL=60.0, BLACK=4.0, SOFT=35.0, WHITE=1500.0, PEDESTAL=0.002,
              QUIET_SIGMA=2.0, QUIET_FROM=8.0, QUIET_TO=40.0, SATURATION=1.1, SAT_SHADOW=(8.0, 22.0), CEIL_GROW=8)


def camera_matrix(rgb_xyz_matrix):
    cr = np.array(rgb_xyz_matrix)[:3] @ XYZ_RGB
    pre_mul = 1.0 / cr.sum(1)
    return np.linalg.inv(cr / cr.sum(1)[:, None]), pre_mul / pre_mul[1]


def lum_weights(plane_noise, wb):
    wbp = np.array([wb[0], 1.0, 1.0, wb[2]])
    w = 1.0 / (np.asarray(plane_noise) * wbp) ** 2
    return w / w.sum(), wbp


def smoothstep(x, a, c):
    t = np.clip((x - a) / max(c - a, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def finish(st, flat, wb, rgb_cam, plane_noise, P=PARAMS, lum_override=None):
    """st: (4, h, w) stacked planes (DN, faint region at 0); flat: (h, w) the flat they were divided by (for the ceiling
    test); returns float RGB 0..1 (sRGB-encoded) and the numbers that describe it."""
    wl, wbp = lum_weights(plane_noise, wb)
    L = sum(wl[k] * st[k] * wbp[k] for k in range(4)).astype(np.float32) if lum_override is None else lum_override.astype(np.float32)
    if P['LUM_BLUR'] > 0: L = cv2.GaussianBlur(L, (0, 0), P['LUM_BLUR'])
    cam = np.dstack([st[0] * wb[0], 0.5 * (st[1] + st[2]), st[3] * wb[2]]).astype(np.float32)
    # stars that touched the sensor's ceiling: their cores have no true colour (one plane clipped), so they are left out
    # of the colour average (normalised Gaussian) and shown white, fading back to colour over a few px around them
    ceil = ((st * flat[None]).max(0) > 0.85 * CEILING).astype(np.uint8)
    core = cv2.dilate(ceil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * P['CEIL_GROW'] + 1, 2 * P['CEIL_GROW'] + 1))).astype(np.float32)
    keep = 1 - core
    Cc = cv2.GaussianBlur(cam * keep[..., None], (0, 0), P['CHROMA_BLUR']) / np.maximum(cv2.GaussianBlur(keep, (0, 0), P['CHROMA_BLUR']), 1e-3)[..., None]
    Lc = wl[0] * Cc[..., 0] + (wl[1] + wl[2]) * Cc[..., 1] + wl[3] * Cc[..., 2]
    sC = Cc @ rgb_cam.T.astype(np.float32)
    w = smoothstep(Lc, P['COLOUR_FROM'], P['COLOUR_FULL'])
    satm = np.clip(cv2.GaussianBlur(core, (0, 0), 2.0) * 2, 0, 1)
    w = w * (1 - satm)
    cr = w[..., None] * (sC / np.maximum(Lc, 1e-3)[..., None]) + (1 - w[..., None])
    Ls = np.arcsinh(np.clip(L - P['BLACK'], 0, None) / P['SOFT']) / np.arcsinh(P['WHITE'] / P['SOFT'])
    out = np.clip(P['PEDESTAL'] + (1 - P['PEDESTAL']) * Ls[..., None] * cr, 0, 1)
    out = np.where(out <= 0.0031308, 12.92 * out, 1.055 * np.power(out, 1 / 2.4) - 0.055).astype(np.float32)
    lab = cv2.cvtColor(out, cv2.COLOR_RGB2Lab); Lab_L = lab[..., 0]
    if P['QUIET_SIGMA'] > 0:
        dark = 1 - smoothstep(cv2.GaussianBlur(Lab_L, (0, 0), max(P['QUIET_SIGMA'], 2.0) * 1.5), P['QUIET_FROM'], P['QUIET_TO'])
        lab[..., 0] = dark * cv2.GaussianBlur(Lab_L, (0, 0), P['QUIET_SIGMA']) + (1 - dark) * Lab_L; Lab_L = lab[..., 0]
    k = 1 + (P['SATURATION'] - 1) * smoothstep(Lab_L, *P['SAT_SHADOW']) * (1 - smoothstep(Lab_L, 93.0, 99.5))
    lab[..., 1] *= k; lab[..., 2] *= k
    rgb = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), 0, 1)
    info = dict(luminance_weights=dict(zip(['R', 'G1', 'G2', 'B'], [round(float(v), 4) for v in wl])), colour_shown_fraction=float((w > 0.5).mean()),
                ceiling_pixels=int(ceil.sum()), white_clipped_pct=float((rgb.min(2) >= 254.5 / 255).mean() * 100), black_clipped_pct=float((rgb.max(2) <= 0.5 / 255).mean() * 100))
    return rgb, info, L


def skycheck(rgb8):
    """As .claude/skills/finish-pictures/tools/skycheck.py: mean R, G, B of the darkest 10% and the next 30%."""
    im = rgb8.astype(np.float32); Y = im @ np.array([0.2126, 0.7152, 0.0722], np.float32); out = {}
    for lo, hi in ((0, 10), (10, 40)):
        a, b = np.percentile(Y, [lo, hi]); m = (Y >= a) & (Y <= b)
        out['darkest_%d_%d_pct' % (lo, hi)] = [round(float(np.mean(im[..., c][m])), 2) for c in range(3)]
    return out


def save_jpeg(rgb, path, quality=92):
    """8-bit sRGB JPEG with no metadata (no EXIF, no ICC, no comment)."""
    from PIL import Image
    im = Image.fromarray((np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8), 'RGB')
    im.save(path, quality=quality, subsampling=0, optimize=True)
    return im.size
