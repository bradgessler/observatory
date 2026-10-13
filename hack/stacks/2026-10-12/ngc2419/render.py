"""From stacked colour planes to a stretched 16-bit picture for finish16.py (the finish-pictures tool). Every step is one
fixed formula applied to every pixel alike (Gaussian filters, a pointwise curve, a matrix); nothing is generated,
learned or drawn. As tonight's hack/stacks/2026-10-12/m1/render.py; the numbers are NGC 2419's own.

  1. colour: R, G = mean of G1 and G2, B, times the camera's own daylight white balance (from the RAW, through LibRaw),
     then the camera's own colour matrix (rgb_xyz_matrix in the RAW, through the sRGB primaries, rows normalised so
     that daylight white stays white, as dcraw does): linear sRGB.
  2. brightness and colour, each at the resolution it can carry:
     L  = the four planes weighted by their inverse noise variance (white-balanced units); Gaussian of LUM_BLUR px
          (the stars are about 7 px across, half-flux diameter, so this widens them by a few percent and removes pixel
          noise finer than the telescope and air delivered).
     Stars that touched the sensor's ceiling (any plane above 85% of it): their cores have no true colour, so the
          pixels within CEIL_GROW px of them are left out of the colour average and shown white.
     C  = the linear sRGB after a Gaussian of CHROMA_BLUR px; its colour ratios C / L(C) are used.
          Two averages, because the nebula and the stars in it have different colours (step 11: the nebula blue :
          green 1.01, the two stars 0.83 and 0.63):
            the nebula   Gaussian of CHROMA_BLUR px (24 px, 19 arcsec) with the STARS LEFT OUT of the average (a
                         normalised convolution over the pixels outside the star discs), so no star's colour is
                         spread over the nebula;
            the stars    inside the discs of the BRIGHT stars, a Gaussian of STAR_CHROMA_BLUR px (3 px) of everything.
          The star discs: the difference of Gaussians of L (sigma 1.5 minus sigma 6 px) above STAR_K x its own robust
          sigma, each pixel grown by STAR_GROW px; a bright star is a disc whose peak is above STAR_OWN_K sigma (the
          faint ones, whose own colour over 3 px is noise, drew rainbow rims: they are left out of the nebula's
          average and take the colour around them). The edge is softened by a Gaussian of 3 px. One fixed rule for
          the whole picture. Tried first and NOT kept: one average of 32 px (tonight's M1 value), which spread the orange
          of the northern star over the nebula a minute of arc around it; and one average of 6 px, which left pink
          and blue blotches 40 arcsec wide in the nebula's body (colour noise and the stars' own haloes).
     out = L x (w C / L(C) + (1 - w)), w = smoothstep of L(C) from COLOUR_FROM to COLOUR_FULL DN, and w = 0 on stars
          that touched the sensor's ceiling. Where the nebula is faint its colour is set by how the sky and the flat
          were handled (the sky in the frames is 4 to 40 times brighter than the nebula), so it is shown grey; colour
          is shown where the light is bright enough to carry it. COLOUR_FROM and COLOUR_FULL are set from step 11's
          measure: above 20 DN of smoothed green the nebula's blue : green is 1.01 +- 0.04 (a sky-zero error of one
          blank-sky scatter), between 10 and 20 DN +- 0.08 and red : green +- 0.08, below that +- 0.17 and worse. So
          14 to 24 DN: full colour only in the bright body. (10 to 20 was tried and NOT kept: it tinted the fainter
          half of the body pink, a red : green of 1.07 +- 0.08 that is not measured.)
  3. stretch: arcsinh of L with the same gain for R, G and B of a pixel (colour ratios kept):
     v = PEDESTAL + (1 - PEDESTAL) x out x asinh((L - BLACK) / SOFT) / (L x asinh(WHITE / SOFT)), then the sRGB
     transfer curve, written as 16 bits. The floor is NOT cut at zero: the sky's noise goes below the pedestal as
     well as above it, and the black point is set afterwards by finish16.py (a hard zero here would leave exact-black
     specks that the finish tool reads as "no data").
NGC 2419 (nothing changed from tonight's M78 render; the numbers quoted above for the nebula and its two stars are
M78's): the cluster's haze is 38 DN at its centre, so with COLOUR_FROM 14 and COLOUR_FULL 24 only its inner half-arcminute
carries colour (step 11: red : green 1.10 +- 0.14, blue : green 0.81 +- 0.07, the colour of the field's stars), and
the rest of it and the sky are shown grey. The two bright stars west of it touched the sensor's ceiling in every frame:
by the rule above their cores are shown white. They are clipped, and nothing repairs them."""
import numpy as np, cv2

XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
CEILING = 15488.0          # 16000 - 512: the raw ceiling above black

import os
PARAMS = dict(LUM_BLUR=float(os.environ.get('N2419_LUM_BLUR', '1.2')), CHROMA_BLUR=float(os.environ.get('N2419_CHROMA_BLUR', '24.0')), STAR_CHROMA_BLUR=3.0, STAR_K=float(os.environ.get('N2419_STAR_K', '8')), STAR_OWN_K=float(os.environ.get('N2419_STAR_OWN_K', '80')), STAR_GROW=int(os.environ.get('N2419_STAR_GROW', '10')), COLOUR_FROM=float(os.environ.get('N2419_COLOUR_FROM', '14')), COLOUR_FULL=float(os.environ.get('N2419_COLOUR_FULL', '24')),
              BLACK=0.0, SOFT=float(os.environ.get('N2419_SOFT', '10')), WHITE=float(os.environ.get('N2419_WHITE', '2500')), PEDESTAL=float(os.environ.get('N2419_PEDESTAL', '0.10')), CEIL_GROW=8)


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


def stretched(st, flat, wb, rgb_cam, plane_noise, P=PARAMS, lum_override=None):
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
    # the star discs (difference of Gaussians of L above STAR_K robust sigma, grown)
    dog = cv2.GaussianBlur(L, (0, 0), 1.5) - cv2.GaussianBlur(L, (0, 0), 6.0)
    sd = 1.4826 * float(np.median(np.abs(dog[::3, ::3] - np.median(dog[::3, ::3]))))
    disc = cv2.dilate((dog > P['STAR_K'] * sd).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * P['STAR_GROW'] + 1, 2 * P['STAR_GROW'] + 1))).astype(np.float32)
    keep = (1 - core) * (1 - disc)
    def ratios(Cc):
        Lc = wl[0] * Cc[..., 0] + (wl[1] + wl[2]) * Cc[..., 1] + wl[3] * Cc[..., 2]
        w = smoothstep(Lc, P['COLOUR_FROM'], P['COLOUR_FULL'])
        return w[..., None] * ((Cc @ rgb_cam.T.astype(np.float32)) / np.maximum(Lc, 1e-3)[..., None]) + (1 - w[..., None]), w
    kn = cv2.GaussianBlur(keep, (0, 0), P['CHROMA_BLUR'])
    cr_neb, w_neb = ratios(cv2.GaussianBlur(cam * keep[..., None], (0, 0), P['CHROMA_BLUR']) / np.maximum(kn, 1e-3)[..., None])
    k2 = 1 - core
    cr_star, w_star = ratios(cv2.GaussianBlur(cam * k2[..., None], (0, 0), P['STAR_CHROMA_BLUR']) / np.maximum(cv2.GaussianBlur(k2, (0, 0), P['STAR_CHROMA_BLUR']), 1e-3)[..., None])
    nl, lab = cv2.connectedComponents((disc > 0).astype(np.uint8), connectivity=8)
    pk = np.zeros(nl, np.float32); np.maximum.at(pk, lab.ravel(), dog.ravel())
    own = ((pk > P['STAR_OWN_K'] * sd)[lab] & (lab > 0)).astype(np.float32)
    ms = cv2.GaussianBlur(own, (0, 0), 3.0)[..., None]
    cr = ms * cr_star + (1 - ms) * cr_neb; w = ms[..., 0] * w_star + (1 - ms[..., 0]) * w_neb
    satm = np.clip(cv2.GaussianBlur(core, (0, 0), 2.0) * 2, 0, 1)
    cr = (1 - satm[..., None]) * cr + satm[..., None]; w = w * (1 - satm)
    Ls = np.arcsinh((L - P['BLACK']) / P['SOFT']) / np.arcsinh(P['WHITE'] / P['SOFT'])
    out = np.clip(P['PEDESTAL'] + (1 - P['PEDESTAL']) * Ls[..., None] * cr, 1.0 / 65535, 1)
    out = np.where(out <= 0.0031308, 12.92 * out, 1.055 * np.power(out, 1 / 2.4) - 0.055).astype(np.float32)
    info = dict(star_discs=dict(dog_sigma_dn=round(sd, 4), discs=int(nl - 1), with_their_own_colour=int((pk[1:] > P['STAR_OWN_K'] * sd).sum()), fraction_of_picture=float(disc.mean())), luminance_weights=dict(zip(['R', 'G1', 'G2', 'B'], [round(float(v), 4) for v in wl])), colour_shown_fraction=float((w > 0.5).mean()),
                ceiling_pixels=int(ceil.sum()), at_floor_px=int((out.max(2) <= 12.92 / 65535 * 1.01).sum()), at_white_px=int((out.min(2) >= 1).sum()))
    return out, info, L


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
