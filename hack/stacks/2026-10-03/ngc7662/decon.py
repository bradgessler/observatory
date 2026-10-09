"""Richardson-Lucy with a measured star image as the blur. Plain multiplicative RL, fixed number of rounds,
no regularisation, no learned parts."""
import numpy as np
from scipy.signal import fftconvolve

def psf_from_star(img, c, radius=40, bg_annulus=(60, 80)):
    """Cut the star out of one channel of the stack, centre it to the nearest pixel, subtract the local
    sky ring, zero outside the radius, clip at zero, normalise to 1."""
    cx, cy = int(round(c[0])), int(round(c[1])); R = bg_annulus[1] + 2
    t = img[cy - R:cy + R + 1, cx - R:cx + R + 1].astype(np.float64)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (c[0] - cx), yy - (c[1] - cy))
    bg = np.median(t[(rr >= bg_annulus[0]) & (rr < bg_annulus[1])])
    p = (t - bg) * (rr <= radius)
    p = np.clip(p, 0, None)[R - radius:R + radius + 1, R - radius:R + radius + 1]
    return p / p.sum(), float(bg)

def richardson_lucy(d, psf, rounds, pedestal):
    """d: one channel (sky near 0). A constant pedestal keeps values positive; it is removed at the end."""
    pad = psf.shape[0]
    x = np.pad(d.astype(np.float64) + pedestal, pad, mode='reflect')
    x = np.clip(x, 1e-3, None)
    u = x.copy(); pm = psf[::-1, ::-1]
    for _ in range(rounds):
        conv = fftconvolve(u, psf, mode='same')
        u *= fftconvolve(x / np.clip(conv, 1e-6, None), pm, mode='same')
    return (u[pad:-pad, pad:-pad] - pedestal).astype(np.float32)
