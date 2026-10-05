"""Colour and stretch. Everything here is a fixed formula applied to every pixel alike."""
import numpy as np, cv2

def rgb_from_planes(planes, wb_r, wb_b):
    """planes: (4, h, w) R, G1, G2, B in raw units -> (h, w, 3) RGB with the camera's white balance."""
    return np.dstack([planes[0] * wb_r, (planes[1] + planes[2]) / 2, planes[3] * wb_b]).astype(np.float32)

def srgb_oetf(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)

def asinh_stretch(rgb, white, soft, pedestal):
    """Arcsinh stretch that keeps each pixel's R:G:B ratio (no saturation change):
    I = max(R, G, B) + pedestal;  gain = asinh(I / soft) / asinh(white / soft) / I;
    out_linear = (RGB + pedestal) * gain, clipped to 0..1;  then the sRGB transfer curve; 8 bit."""
    v = rgb.astype(np.float64) + pedestal
    I = v.max(axis=2)
    x = I / soft
    with np.errstate(divide='ignore', invalid='ignore'):
        gain = np.where(np.abs(x) < 1e-6, 1.0 / soft, np.arcsinh(x) / I) / np.arcsinh(white / soft)
    out = v * gain[:, :, None]
    return (srgb_oetf(out) * 255 + 0.5).astype(np.uint8)
