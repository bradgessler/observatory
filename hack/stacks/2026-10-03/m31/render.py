"""Colour and stretch. Everything here is a fixed formula applied to every pixel alike."""
import numpy as np, cv2

def rgb_from_planes(planes, wb_r, wb_b):
    """planes: (4, h, w) R, G1, G2, B in raw units -> (h, w, 3) RGB with white-balance multipliers on R and B."""
    return np.dstack([planes[0] * wb_r, (planes[1] + planes[2]) / 2, planes[3] * wb_b]).astype(np.float32)

def srgb_oetf(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)

def asinh_stretch(rgb, white, soft, pedestal, chroma_sigma=0.0, lum_sigma=0.0):
    """Arcsinh curve on brightness, colour ratios kept.
    brightness L = the green channel (most of the light, least noise), optionally Gaussian-blurred (lum_sigma px);
    colour = (R, G, B) of a Gaussian-blurred copy (chroma_sigma px; 0 = none), as ratios to its own green:
        ratio_c = (C_blur + pedestal) / (G_blur + pedestal)
    curve:  f = asinh((min(L, white) + pedestal) / soft) / asinh((white + pedestal) / soft)
    out_c = ratio_c * f, clipped to 0..1, then the sRGB transfer curve, 8 bit.
    The red and blue planes are 2 to 3 times noisier than green after white balance; taking the colour from a
    copy blurred by less than a star's width keeps that noise out of the picture without touching the detail,
    which is all in L. No saturation is added: where the blurred colour is grey the pixel is grey."""
    v = rgb.astype(np.float32)
    L = v[:, :, 1] if lum_sigma <= 0 else cv2.GaussianBlur(v[:, :, 1], (0, 0), lum_sigma)
    C = v if chroma_sigma <= 0 else cv2.GaussianBlur(v, (0, 0), chroma_sigma)
    den = np.maximum(C[:, :, 1] + pedestal, 0.25 * pedestal)
    ratio = np.maximum(C + pedestal, 0) / den[:, :, None]
    f = np.arcsinh((np.clip(L, -pedestal, white).astype(np.float64) + pedestal) / soft) / np.arcsinh((white + pedestal) / soft)
    out = ratio * f[:, :, None]
    return (srgb_oetf(out) * 255 + 0.5).astype(np.uint8)
