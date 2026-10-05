"""The hair on the sensor: where its shadow is in ONE frame, from that frame alone.
It sits near the top edge, right of centre, and creeps (it moved and turned between the M31 runs and these), so
no fixed map can be trusted for it. In each frame: the green planes, divided by the smooth flat, blurred (sigma 3
plane px), over their own grey closing (ellipse 61 px: the local upper envelope, which fills in any dark feature
narrower than 61 px and leaves stars and smooth nebula alone). The hair is the largest connected patch below
0.86 of that envelope inside the search zone (HAIR_BOX), 300 to 8000 plane px in area. Its mask is that patch
(to 0.93 of the envelope) grown by 30 plane px (60 sensor px): the pixels left out of the average."""
import numpy as np, cv2
from common import *

X0, Y0, X1, Y1 = [v // 2 for v in HAIR_BOX]
K61 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))
GROW = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61))


def hair_ratio(P, flat_smooth):
    G = ((P[1] / flat_smooth[1] + P[2] / flat_smooth[2]) / 2)[Y0:Y1 + 80, X0 - 80:X1 + 80]
    sm = cv2.GaussianBlur(G, (0, 0), 3)
    env = cv2.morphologyEx(sm, cv2.MORPH_CLOSE, K61, borderType=cv2.BORDER_REPLICATE)
    return (sm / np.maximum(env, 1e-3))[:Y1 - Y0, 80:80 + X1 - X0]


def find_hair(P, flat_smooth):
    """Returns (mask over the whole plane grid, info) or (None, None) when no hair-like shadow is found."""
    r = hair_ratio(P, flat_smooth)
    n, lab, stats, cent = cv2.connectedComponentsWithStats((r < 0.86).astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        if 300 <= stats[i, 4] <= 8000 and (best is None or stats[i, 4] > stats[best, 4]): best = i
    if best is None: return None, None
    core = lab == best
    # the same patch out to 0.93 of the envelope (its soft edge), then grown
    n2, lab2 = cv2.connectedComponents((r < 0.93).astype(np.uint8), connectivity=8)
    ids = np.unique(lab2[core]); soft = np.isin(lab2, ids[ids > 0])
    if soft.sum() > 6 * core.sum(): soft = core            # the soft edge ran into something else (a dark lane): keep the core only
    m = np.zeros((H2, W2), np.uint8); m[Y0:Y1, X0:X1] = soft
    m = cv2.dilate(m, GROW).astype(bool)
    ys, xs = np.nonzero(core)
    info = dict(centre_sensor_xy=[round(2 * float(cent[best][0] + X0) + 0.5), round(2 * float(cent[best][1] + Y0) + 0.5)], area_plane_px=int(stats[best, 4]), deepest=float(r[core].min()),
                bbox_sensor=[int(2 * (xs.min() + X0)), int(2 * (ys.min() + Y0)), int(2 * (xs.max() + X0)), int(2 * (ys.max() + Y0))], masked_plane_px=int(m.sum()))
    return m, info
