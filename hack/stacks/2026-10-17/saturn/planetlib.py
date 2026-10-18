"""The planet stacker of hack/stacks/2026-10-03/saturn/saturn2.py, as functions, with two changes: each frame's sky (one
constant per colour plane, the median of the whole plane) is taken off before it is laid down, and the final stack folds
each frame's registration shift into the same single Lanczos resampling that puts it on the fine grid (saturn2.py
resampled twice)."""
import cv2
from scipy.optimize import minimize
from common import *

N_FINE = 2 * HALF * 2 * UP        # fine px across the tile (HALF colour cells each side, 2 sensor px per cell, UP fine per sensor px)


def tile(args):
    """One frame's planet on the fine grid, each colour plane read at its own place in the cell: (n, n, 3) R, G, B.
    (fx, fy): the planet in colour-cell px; turn_deg: how far this frame's picture is turned from the reference;
    (sx, sy): a further shift in fine px (where the frame sits from the stack's mean), taken out in the same resampling."""
    name, fx, fy, turn_deg, sx, sy = args
    P, wb = planes(os.path.join(STILLS, name)); n = N_FINE; per = 2 * UP     # fine px per colour cell
    X = (np.arange(n, dtype=np.float64) + 0.5) / per - 0.5 - HALF           # colour-cell offset of each fine px from the planet, reference frame
    mx, my = np.meshgrid(X, X); mx = mx + sx / per; my = my + sy / per
    d = np.radians(turn_deg); c_, s_ = np.cos(d), np.sin(d)               # a point at angle a in the reference sits at a + d in this frame
    ux, uy = fx + mx * c_ - my * s_, fy + mx * s_ + my * c_
    out = np.zeros((n, n, 3), np.float32); cnt = np.zeros(3, np.float32)
    for k, (ox, oy) in enumerate(OFFS):
        c = (0, 1, 1, 2)[k]; p = P[k] - np.float32(np.median(P[k][::4, ::4]))
        # plane pixel X sits at sensor 2X + ox, i.e. colour-cell coordinate X + ox/2 - 1/4 relative to the cell's centre: read at (u - (ox - 0.5) / 2)
        v = cv2.remap(p, (ux - (ox - 0.5) / 2).astype(np.float32), (uy - (oy - 0.5) / 2).astype(np.float32), cv2.INTER_LANCZOS4)
        out[:, :, c] += v * wb[c]; cnt[c] += 1
    return out / cnt


def phase_shift(ref, img):
    win = cv2.createHanningWindow(ref.shape[::-1], cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(ref.astype(np.float32), img.astype(np.float32), win)
    return float(dx), float(dy)


def ls_shift(ref, img):
    """The shift (fine px) that makes smoothed img, scaled, closest to smoothed ref (saturn2.py)."""
    a = cv2.GaussianBlur(ref, (0, 0), 3); b0 = cv2.GaussianBlur(img, (0, 0), 3); h, w = a.shape; sl = (slice(60, h - 60), slice(60, w - 60))
    def cost(p):
        b = cv2.warpAffine(b0, np.float32([[1, 0, -p[0]], [0, 1, -p[1]]]), (w, h), flags=cv2.INTER_LINEAR)
        k = (a[sl] * b[sl]).sum() / (b[sl] ** 2).sum(); return float(((a[sl] - k * b[sl]) ** 2).sum())
    r = minimize(cost, (0.0, 0.0), method='Nelder-Mead', options=dict(xatol=0.01, fatol=1e-16, initial_simplex=np.array([(0.0, 0.0), (2.0, 0.0), (0.0, 2.0)])))
    return float(r.x[0]), float(r.x[1])


def shift(img, dx, dy): return cv2.warpAffine(img, np.float32([[1, 0, -dx], [0, 1, -dy]]), img.shape[1::-1], flags=cv2.INTER_LANCZOS4)


def turn_of(name, rate, ref_min): return rate * (minute(name) - ref_min)
