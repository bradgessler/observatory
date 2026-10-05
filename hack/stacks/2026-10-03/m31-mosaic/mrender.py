"""Colour and stretch for the mosaic. The curve is the core run's (render.py: arcsinh on brightness, colour
ratios kept, sRGB transfer curve, 8 bit); two things are added for a picture whose depth changes by a factor of ten
from place to place. Everything is a fixed formula applied to every pixel alike; nothing is drawn.

  brightness L = green.
  curve       f = asinh((min(L, white) + pedestal) / soft) / asinh((white + pedestal) / soft)
  colour      ratio_c = (C_c + cp) / (C_G + cp), C = the picture blurred with a Gaussian (chroma_sigma px, holes
              left out of the blur), cp = the COLOUR PEDESTAL, a map: cp_core where the deep core stack
              carries the weight, cp_panels where only panels do, blended by the core's share of the weight.
              In the core run cp was the brightness pedestal. A panel's zero, though, is known per colour only
              to 10 to 20 DN in red and 5 to 10 in blue (step 10), which at 10 DN of galaxy would paint whole
              panels pink or teal. With cp_panels of 300 DN the panels come out in neutral grey, except
              where the light is far brighter than that uncertainty (stars, M32, the bulge). No saturation is
              added anywhere; where the colour cannot be known it is not shown.
  out_c = ratio_c x f, clipped 0..1, sRGB curve, 8 bit. Pixels without data are black (0, 0, 0).

  grain       (adaptive_smooth, used for the pictures only, never for the linear file) where the expected noise of
              a pixel is above a target, the picture is first blurred with a Gaussian whose width grows with the
              noise: sigma = noise / (2 sqrt(pi) x target) px, the width that brings white noise down to the
              target, at most sigma_max; below 0.45 px nothing is done (the core is left as it is). It is a plain
              local average of measured pixels (holes left out), made by blending fixed-width blurs. It trades
              sharpness for grain exactly where the data is thin: stars in the noisiest panel come out wider."""
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


def stretch(rgb, cp, white, soft, pedestal, chroma_sigma):
    """rgb: (h, w, 3) float, NaN = no data; cp: (h, w) the colour pedestal in DN."""
    ok = np.isfinite(rgb).all(2)
    v = np.where(ok[:, :, None], rgb, 0).astype(np.float32)
    L = v[:, :, 1]
    C = nblur(v, ok, chroma_sigma)
    cp = np.asarray(cp, np.float32)
    den = np.maximum(C[:, :, 1] + cp, 0.25 * cp)
    ratio = np.maximum(C + cp[:, :, None], 0) / den[:, :, None]
    f = np.arcsinh((np.clip(L, -pedestal, white).astype(np.float64) + pedestal) / soft) / np.arcsinh((white + pedestal) / soft)
    out = (srgb_oetf(ratio * f[:, :, None]) * 255 + 0.5).astype(np.uint8)
    out[~ok] = 0
    return out


def adaptive_smooth(rgb, noise, target, sigma_max, levels=(0.0, 0.4, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0)):
    """Returns the smoothed picture, the sigma map (px) and the expected noise after smoothing."""
    ok = np.isfinite(rgb).all(2)
    sig = np.clip(noise / (2 * np.sqrt(np.pi) * target), 0, sigma_max).astype(np.float32)
    sig[sig < 0.45] = 0
    sig = cv2.dilate(sig, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))            # small noisy islands get their width too
    sig = nblur(sig, ok, 4.0).astype(np.float32); sig[sig < 0.15] = 0                     # the width itself changes smoothly
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
