"""The stack's canvas: the reference frame's grid of colour cells widened to where the frames are. Canvas pixel (X, Y)
is reference plane pixel (X + X0, Y + Y0), i.e. reference sensor (2 (X + X0) + 0.5, 2 (Y + Y0) + 0.5). step7 makes it
(work/canvas.json): the bounding box of where at least CANVAS_MIN_FRAC of the used frames have data, 8 px margin."""
import numpy as np
from common import *


def maps(R, t, X0, Y0, HC, WC, ox=0.5, oy=0.5, d=(0.0, 0.0)):
    """For every canvas pixel, where it falls on a frame's plane with cell offset (ox, oy) (0.5, 0.5 = mean green)."""
    Yc, Xc = np.mgrid[0:HC, 0:WC].astype(np.float64)
    SX, SY = 2 * (Xc + X0) + 0.5, 2 * (Yc + Y0) + 0.5
    fx = R[0, 0] * SX + R[0, 1] * SY + t[0] + d[0]; fy = R[1, 0] * SX + R[1, 1] * SY + t[1] + d[1]
    return ((fx - ox) / 2).astype(np.float32), ((fy - oy) / 2).astype(np.float32)


def back_maps(R, t, X0, Y0):
    """For every mean-green plane pixel of a frame, where it falls on the canvas."""
    Yp, Xp = np.mgrid[0:h2, 0:w2].astype(np.float64)
    s = np.stack([2 * Xp + 0.5 - t[0], 2 * Yp + 0.5 - t[1]], -1)
    r = s @ R                                     # R^T (s - t), row vectors
    return ((r[..., 0] - 0.5) / 2 - X0).astype(np.float32), ((r[..., 1] - 0.5) / 2 - Y0).astype(np.float32)


def load():
    c = jload('canvas.json'); return c['X0'], c['Y0'], c['HC'], c['WC']
