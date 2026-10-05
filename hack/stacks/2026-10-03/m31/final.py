"""The finished planes of a version, the well-covered rectangle, and the level taken off each plane.

Version B's (and C's) finished planes: the combine with the dust-shadowed sensor pixels left out, except where fewer than
12 clean frames exist (the core of a big shadow that the field did not move far enough to clear): there the
combine with the dust left in is blended in, fully below 4 clean frames. Those pixels still carry the shadow.

The level taken off: the galaxy fills the frame, so there is no sky to measure. One constant per plane is
subtracted so that the darkest part of the well-covered field sits at zero: the median of each plane over the
pixels where the smoothed green (5x5 median at 1/8 scale, Gaussian sigma 4 there = 32 px) is below its 1st percentile, tracks of sensor dust shadows left out.
The same pixels for all four planes, so that region is neutral by construction. The galaxy is NOT zero
there: the absolute zero is unknown."""
import json, numpy as np, cv2
from common import *
COVER_MIN_FRACTION = 0.80
BLEND_LO, BLEND_HI = 4, 12
CLEAN_MIN = 30          # of 38: a pixel with at least this many frames used counts as clear of dust tracks
EDGE_SHADE = 450        # sensor px at the top and bottom of the sensor where the cloud-glow flat shows 2 to 4% of edge shading that a radial profile does not remove

def final_planes(ver):
    st = np.load(W('%s_mean.npy' % ver))
    if ver in ('B', 'C'):
        li = np.load(W('%s_mean_dust_left_in.npy' % ver)); used = np.load(W('%s_used.npy' % ver)).astype(np.float32)
        wgt = np.clip((used - BLEND_LO) / float(BLEND_HI - BLEND_LO), 0, 1)
        st = np.where(np.isfinite(st), st, li) * wgt + li * (1 - wgt)
    return st

def cover_rect(ver, nframes):
    """The largest-ish axis-aligned rectangle in which every pixel is covered by at least 80% of the frames."""
    inside = np.load(W('%s_cover.npy' % ver)) >= int(np.ceil(COVER_MIN_FRACTION * nframes))
    ys, xs = np.nonzero(inside); x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    while True:
        sub = inside[y0:y1, x0:x1]
        if sub.all(): break
        fr = [(~sub[0, :]).mean(), (~sub[-1, :]).mean(), (~sub[:, 0]).mean(), (~sub[:, -1]).mean()]
        i = int(np.argmax(fr))
        if i == 0: y0 += 1
        elif i == 1: y1 -= 1
        elif i == 2: x0 += 1
        else: x1 -= 1
    x0 += x0 % 2; y0 += y0 % 2; x1 -= (x1 - x0) % 2; y1 -= (y1 - y0) % 2       # even size, so it halves cleanly
    return int(x0), int(y0), int(x1), int(y1)

def zero_levels(planes_crop, clean_crop, not_edge=None):
    """planes_crop: (4, h, w) of the well-covered rectangle; clean_crop: bool, True where the pixel is not on the
    track of a sensor dust shadow (at least CLEAN_MIN frames used in version B's dust-left-out combine).
    not_edge: bool, False in the strips at the top and bottom of the reference sensor (edge shading), which are
    not allowed to set the zero. Returns the four levels, the mask of the darkest region and its centre."""
    G = (planes_crop[1] + planes_crop[2]) / 2
    small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 4)
    ok = cv2.resize(clean_crop.astype(np.float32), None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA) > 0.999
    ok = cv2.erode(ok.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)          # and 8 px clear of any track
    if not_edge is not None: ok &= cv2.resize(not_edge.astype(np.uint8), (ok.shape[1], ok.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    thr = np.percentile(sm[ok], 1.0)
    dark = cv2.resize(((sm <= thr) & ok).astype(np.uint8), (G.shape[1], G.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    lev = []
    for p in range(4):
        v = planes_crop[p][dark]
        lev.append(clipped_stats(v[::3])[0])
    ys, xs = np.nonzero(dark)
    return lev, dark, (float(np.median(xs)), float(np.median(ys)))

def clean_mask(rect):
    x0, y0, x1, y1 = rect
    return np.load(W('B_used.npy'))[1][y0:y1, x0:x1] >= CLEAN_MIN

def not_edge_mask(rect):
    x0, y0, x1, y1 = rect
    m = np.zeros((H, Wd), bool); m[EDGE_SHADE:H - EDGE_SHADE] = True
    return m[y0:y1, x0:x1]
