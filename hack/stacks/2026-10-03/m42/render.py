"""Colour and tone for the M42 pictures. Everything here is a fixed formula applied to every pixel alike; nothing
is drawn, nothing is generated.

  white balance   R x wb_R, G = mean of G1 and G2, B x wb_B. Where the white mark is set (pixels that were at
                  the sensor's ceiling even in the shortest frames, step 9) R, G and B are all given the largest of
                  the three RECORDED values, unmultiplied: white, never a colour made by the white balance.
  brightness      L = G (green: most of the light and the least noise).
  grain           for the pictures only (never the linear file): where the light is faint against the pixel
                  noise, L is taken from a Gaussian-blurred copy; where it is bright, from the sharp picture.
                  Three copies are blended by local signal-to-noise s = (blurred L + pedestal) / noise:
                  sigma_max px below s = s_lo, sharp above s = s_hi, in between a smooth mix (through a copy of
                  half the width). A plain local average of measured pixels; it trades sharpness for grain only
                  where the picture is thin. Stars are bright and stay sharp.
  curve           E(L) = asinh((min(L, white) + pedestal) / soft) / asinh((white + pedestal) / soft), raised to
                  the power gamma (1 = none). E is the DISPLAY value (0..1) of a grey pixel.
  colour          ratio_c = (C_c + cp) / (C_G + cp), C = the white-balanced picture blurred with a Gaussian
                  (chroma_sigma px, holes left out), cp = the colour pedestal (DN; a number or a map): where the
                  light is fainter than cp the colour fades to grey, because there the zero of each colour is
                  not known well enough to show a hue. The ratios are applied in LINEAR light: the grey value E
                  is turned into linear light with the sRGB curve's inverse, multiplied by ratio_c, optionally
                  pulled toward or away from grey by ONE global saturation factor (1 = none), and turned
                  back: out_c = sRGB(ratio_c x sRGB^-1(E)).
  highlights      where a colour would pass the top of the range the WHOLE pixel is dimmed by the same factor
                  (its colour is kept; no channel is clipped on its own).
  8 bit. Pixels without data are black (0, 0, 0)."""
import numpy as np, cv2


def srgb_oetf(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def srgb_eotf(v):
    v = np.clip(v, 0, 1)
    return np.where(v <= 0.04045, v / 12.92, np.power((v + 0.055) / 1.055, 2.4))


def nblur(a, ok, sigma):
    """Gaussian blur that leaves holes out (normalised convolution)."""
    if sigma <= 0: return a
    okf = ok.astype(np.float32)
    den = np.maximum(cv2.GaussianBlur(okf, (0, 0), sigma), 1e-4)
    if a.ndim == 3: return cv2.GaussianBlur(np.where(ok[:, :, None], a, 0).astype(np.float32), (0, 0), sigma) / den[:, :, None]
    return cv2.GaussianBlur(np.where(ok, a, 0).astype(np.float32), (0, 0), sigma) / den


def bin2(a, f=2):
    """f x f block mean that leaves holes out; a block with no data stays without data."""
    h, w = a.shape[0] // f * f, a.shape[1] // f * f
    sq = a.ndim == 2
    if sq: a = a[:, :, None]
    b = a[:h, :w].reshape(h // f, f, w // f, f, a.shape[2])
    ok = np.isfinite(b).all(4, keepdims=True)
    n = ok.sum((1, 3)); s = np.where(ok, b, 0).sum((1, 3), dtype=np.float64)
    out = np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)
    return out[:, :, 0] if sq else out


def white_balance(rgb, wb_r, wb_b, white=None):
    v = rgb.astype(np.float32) * np.array([wb_r, 1.0, wb_b], np.float32)
    if white is not None:
        m = np.clip(white, 0, 1)[:, :, None]
        with np.errstate(invalid='ignore'):
            mx = np.max(rgb.astype(np.float32), axis=2, keepdims=True)       # the largest of the three as RECORDED: a clipped value is never multiplied by the white balance
        v = np.where(m > 0, (1 - m) * v + m * mx, v)
    return v


def grain(L, ok, noise, pedestal, sigma_max, s_lo, s_hi):
    """L smoothed where it is faint against the noise. noise: a number or a map (DN per pixel of L)."""
    if sigma_max <= 0: return L, np.zeros(L.shape, np.float32)
    v = np.where(ok, L, 0).astype(np.float32)
    b1 = nblur(v, ok, sigma_max); b2 = nblur(v, ok, sigma_max / 2)
    s = (np.maximum(nblur(v, ok, max(sigma_max, 2.0)), 0) + pedestal) / np.maximum(noise, 1e-3)
    t = np.clip((np.log(np.maximum(s, 1e-6)) - np.log(s_lo)) / (np.log(s_hi) - np.log(s_lo)), 0, 1)      # 0 = widest blur, 1 = sharp
    t = nblur(t.astype(np.float32), ok, 1.5)                                                               # the mix itself changes smoothly
    out = np.where(t < 0.5, b1 * (1 - 2 * t) + b2 * (2 * t), b2 * (2 - 2 * t) + v * (2 * t - 1))
    return out.astype(np.float32), (sigma_max * np.where(t < 0.5, 1 - t, 1 - t)).astype(np.float32)


def curve(L, white, soft, pedestal, gamma=1.0):
    e = np.arcsinh((np.clip(L, -pedestal, white).astype(np.float64) + pedestal) / soft) / np.arcsinh((white + pedestal) / soft)
    return np.power(np.clip(e, 0, 1), gamma)


def stretch(rgb_wb, cp, white, soft, pedestal, gamma=1.0, chroma_sigma=3.0, saturation=1.0, noise=None, grain_sigma=0.0, s_lo=1.5, s_hi=8.0):
    """rgb_wb: (h, w, 3) float, white-balanced, zero taken off, NaN = no data; cp: number or (h, w) map of the colour pedestal in DN."""
    ok = np.isfinite(rgb_wb).all(2)
    v = np.where(ok[:, :, None], rgb_wb, 0).astype(np.float32)
    L = v[:, :, 1]
    if grain_sigma > 0: L, _ = grain(L, ok, noise, pedestal, grain_sigma, s_lo, s_hi)
    C = nblur(v, ok, chroma_sigma)
    cp = np.broadcast_to(np.asarray(cp, np.float32), L.shape)
    den = np.maximum(C[:, :, 1] + cp, 0.25 * cp)
    ratio = np.maximum(C + cp[:, :, None], 0) / den[:, :, None]
    if saturation != 1.0: ratio = np.maximum(1 + saturation * (ratio - 1), 0)
    lin = ratio * srgb_eotf(curve(L, white, soft, pedestal, gamma))[:, :, None]
    mx = np.max(lin, axis=2, keepdims=True)
    lin = lin / np.maximum(mx, 1.0)
    out = (srgb_oetf(lin) * 255 + 0.5).astype(np.uint8)
    out[~ok] = 0
    return out
