"""Richardson-Lucy with a measured star image as the blur. Plain multiplicative RL, fixed number of rounds,
no regularisation, no learned parts. The blur is the median of several isolated, unsaturated stars of the same
stack, each centred to a fraction of a pixel and scaled to unit flux."""
import numpy as np, cv2
from scipy.signal import fftconvolve


def psf_from_stars(img, xy, radius=32, ring=(40, 56)):
    """img: one channel of the stack (sky near 0). xy: star positions (already centroided). Returns the PSF
    (2*radius+1 square, sum 1) and how many stars went in."""
    cuts = []
    R = ring[1] + 4
    for x, y in xy:
        xi, yi = int(round(x)), int(round(y))
        if xi - R < 0 or yi - R < 0 or xi + R + 1 > img.shape[1] or yi + R + 1 > img.shape[0]: continue
        t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64)
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
        t = t - np.median(t[(rr >= ring[0]) & (rr < ring[1])])
        Mx = np.float32([[1, 0, -(x - xi)], [0, 1, -(y - yi)]])
        t = cv2.warpAffine(t.astype(np.float32), Mx, (2 * R + 1, 2 * R + 1), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        c = t[R - radius:R + radius + 1, R - radius:R + radius + 1].astype(np.float64)
        cuts.append(c / c.sum())
    p = np.median(np.stack(cuts), axis=0)
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    p = np.clip(p, 0, None) * (np.hypot(xx, yy) <= radius)
    return p / p.sum(), len(cuts)

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
