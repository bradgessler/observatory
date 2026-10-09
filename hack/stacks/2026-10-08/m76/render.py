"""Colour and stretch. Everything here is a fixed formula applied to every pixel alike.
Adapted from ../../2026-10-03/ngc7662/render.py (16-bit output added)."""
import numpy as np


def rgb_from_planes(planes, wb_r, wb_b):
    """planes: (4, h, w) R, G1, G2, B in raw units -> (h, w, 3) RGB with the camera's white balance."""
    return np.dstack([planes[0] * wb_r, (planes[1] + planes[2]) / 2, planes[3] * wb_b]).astype(np.float32)


def srgb_oetf(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def asinh_stretch(rgb, white, soft, pedestal, bits=8):
    """Arcsinh stretch that keeps each pixel's R:G:B ratio (no saturation change):
    I = max(R, G, B) + pedestal;  gain = asinh(I / soft) / asinh(white / soft) / I;
    out_linear = (RGB + pedestal) * gain, clipped to 0..1;  then the sRGB transfer curve; 8 or 16 bit."""
    v = rgb.astype(np.float64) + pedestal
    I = v.max(axis=2)
    x = I / soft
    with np.errstate(divide='ignore', invalid='ignore'):
        gain = np.where(np.abs(x) < 1e-6, 1.0 / soft, np.arcsinh(x) / I) / np.arcsinh(white / soft)
    out = srgb_oetf(v * gain[:, :, None])
    if bits == 16:
        return np.clip(out * 65535 + 0.5, 1, 65535).astype(np.uint16)     # never 0 in all three: 0 means "no data" to finish.py
    return (out * 255 + 0.5).astype(np.uint8)


def smoothstep(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def lum_chroma_stretch(rgb, white, soft, pedestal, chroma_sigma, sky_sigma_cs, grey_lo, grey_hi, bits=16):
    """For a stack whose colour noise is far larger than its brightness noise (here red 3 x and blue 2 x green, per
    pixel). Brightness and colour are taken apart and put back together, each a fixed formula:
      Y = (R + G + B) / 3, the pixel's own brightness, never smoothed;
      colour = the R:G:B ratios of a copy blurred by a Gaussian of chroma_sigma px, faded to grey (1:1:1) where the
               blurred brightness is under grey_lo x its sky noise sky_sigma_cs (full colour above grey_hi x), because
               there the ratio is noise;
      Y' = asinh((Y + pedestal) / soft) / asinh(white / soft), clipped to 0..1;  out = Y' x colour, each channel
      clipped to 0..1; then the sRGB curve; 16 bit (never 0 in all three: 0 is "no data" to finish.py)."""
    import cv2
    rgb = rgb.astype(np.float32)
    Y = rgb.mean(axis=2)
    Cs = cv2.GaussianBlur(rgb, (0, 0), chroma_sigma); Ys = Cs.mean(axis=2)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.where(Ys[..., None] > 0, Cs / Ys[..., None], 1.0)
    t = smoothstep((Ys / sky_sigma_cs - grey_lo) / (grey_hi - grey_lo))[..., None]
    ratio = np.clip(1 + t * (ratio - 1), 0, 3)
    Yp = np.arcsinh(np.clip(Y + pedestal, 0, None) / soft) / np.arcsinh(white / soft)
    out = srgb_oetf(np.clip(Yp[..., None] * ratio, 0, 1))
    if bits == 16:
        return np.clip(out * 65535 + 0.5, 1, 65535).astype(np.uint16)
    return (out * 255 + 0.5).astype(np.uint8)
