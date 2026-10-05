"""Colour and stretch for the M45 mosaic. The curve and the two helpers are the night's M31 mosaic's (mrender.py:
arcsinh on brightness, colour ratios kept, sRGB transfer curve, 8 bit, smoothing only where the data is thin);
a black point and a ceiling are added for this target. Everything is a fixed formula applied to every pixel alike;
nothing is drawn.

  ceiling     every colour is first cut at CEILING DN, below the level at which any raw pixel was at the sensor's
              ceiling. A saturated star core is then the same number in R, G and B and comes out white. Nothing is
              painted in or rebuilt.
  brightness  L = green (most of the light, least noise).
  curve       f = asinh(max(L - black, 0) / soft) / asinh((white - black) / soft). Sky at or below the black
              point is black.
  colour      ratio_c = (C_c + cp) / (C_G + cp), C = the picture blurred with a Gaussian (chroma_sigma px, holes
              left out of the blur), cp = the COLOUR PEDESTAL in DN. The zero of each colour is known only to a
              few DN (step 10: 1 to 3 DN between stacks, more in red), which at 5 DN of nebulosity would paint
              whole panels pink or teal. With the pedestal, light that is not well above that uncertainty comes
              out near grey and only light well above it shows its colour. No saturation is added anywhere;
              where the colour cannot be known it is not shown.
  out_c = ratio_c x f, clipped 0..1, sRGB curve, 8 bit. Pixels without data are black (0, 0, 0).

  grain       (adaptive_smooth, used for the pictures only, never for the linear file) where the expected noise of
              a pixel is above a target, the picture is first blurred with a Gaussian whose width grows with the
              noise: sigma = noise / (2 sqrt(pi) x target) px, the width that brings white noise down to the
              target, at most sigma_max; below 0.45 px nothing is done. It is a plain local average of measured
              pixels (holes left out), made by blending fixed-width blurs. It trades sharpness for grain exactly
              where the data is thin: stars in the two cloud panels come out wider."""
import numpy as np, cv2


def srgb_oetf(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def bin2(a, nodata_value=np.nan, f=2):
    """f x f block mean that leaves holes out; a block with no data stays without data."""
    h, w = a.shape[0] // f * f, a.shape[1] // f * f
    if a.ndim == 2: a = a[:, :, None]
    b = a[:h, :w].reshape(h // f, f, w // f, f, a.shape[2])
    ok = np.isfinite(b).all(4, keepdims=True)
    n = ok.sum((1, 3)); s = np.where(ok, b, 0).sum((1, 3), dtype=np.float64)
    out = np.where(n > 0, s / np.maximum(n, 1), nodata_value).astype(np.float32)
    return out[:, :, 0] if out.shape[2] == 1 else out


def nblur(a, ok, sigma):
    """Gaussian blur that leaves holes out (normalised convolution)."""
    if sigma <= 0: return a
    okf = ok.astype(np.float32)
    den = np.maximum(cv2.GaussianBlur(okf, (0, 0), sigma), 1e-4)
    if a.ndim == 3: return cv2.GaussianBlur(np.where(ok[:, :, None], a, 0).astype(np.float32), (0, 0), sigma) / den[:, :, None]
    return cv2.GaussianBlur(np.where(ok, a, 0).astype(np.float32), (0, 0), sigma) / den


def stretch(rgb, cp, white, soft, black, chroma_sigma, ceiling):
    """rgb: (h, w, 3) float, NaN = no data; cp: the colour pedestal in DN."""
    ok = np.isfinite(rgb).all(2)
    v = np.minimum(np.where(ok[:, :, None], rgb, 0), ceiling).astype(np.float32)
    L = v[:, :, 1]
    C = nblur(v, ok, chroma_sigma)
    den = np.maximum(C[:, :, 1] + cp, 0.25 * cp)
    ratio = np.maximum(C + cp, 0) / den[:, :, None]
    f = np.arcsinh(np.clip(L - black, 0, white - black).astype(np.float64) / soft) / np.arcsinh((white - black) / soft)
    out = (srgb_oetf(ratio * f[:, :, None]) * 255 + 0.5).astype(np.uint8)
    out[~ok] = 0
    return out


def adaptive_smooth(rgb, noise, target, sigma_max, levels=(0.0, 0.4, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0)):
    """Returns the smoothed picture, the sigma map (px) and the expected noise after smoothing."""
    ok = np.isfinite(rgb).all(2)
    sig = np.clip(np.nan_to_num(noise, nan=0.0) / (2 * np.sqrt(np.pi) * target), 0, sigma_max).astype(np.float32)
    sig[sig < 0.45] = 0
    sig = cv2.dilate(sig, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    sig = nblur(sig, ok, 4.0).astype(np.float32); sig[sig < 0.15] = 0
    lv = [l for l in levels if l <= sigma_max + 1e-6]
    v = np.where(ok[:, :, None], rgb, 0).astype(np.float32)
    out = np.zeros_like(v); prev = v; prev_l = lv[0]
    done = np.zeros(sig.shape, bool)
    for l in lv[1:]:
        cur = nblur(v, ok, l)
        m = (sig >= prev_l) & (sig <= l) & ~done
        t = ((sig - prev_l) / (l - prev_l))[:, :, None]
        out = np.where(m[:, :, None], prev * (1 - t) + cur * t, out); done |= m
        prev, prev_l = cur, l
    out = np.where((~done)[:, :, None], prev, out)
    out[~ok] = np.nan
    after = np.where(sig > 0.3, noise / np.maximum(2 * np.sqrt(np.pi) * sig, 1.0), noise)
    return out, sig, after
