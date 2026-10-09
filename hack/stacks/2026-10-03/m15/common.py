"""Shared pieces for the M15 stack (adapted from the NGC 7662 pipeline of the same night).
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with
cell offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy).
Two runs share the code: M15_RUN=sharp (after the refocus, the delivered stack) and M15_RUN=soft
(before the refocus, only for the comparison). Each has its own work folder beside the scripts."""
import glob, json, os
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.path.join(NIGHT, 'm15')
SCR = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get('M15_RUN', 'sharp')
RUNS = dict(sharp=dict(t0='071900', t1='073459', ref='20261004-072729', bar_window=(1750, 20, 2210, 340)),
            soft=dict(t0='065900', t1='070659', ref='20261004-070331'))
T0, T1, REF_STAMP = RUNS[RUN]['t0'], RUNS[RUN]['t1'], RUNS[RUN]['ref']
WORK = os.path.join(SCR, RUN)
os.makedirs(WORK, exist_ok=True)
EXPOSURE_S, ISO = 15.0, 1600
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) for R, G1, G2, B
SCALE = 0.388                                # arcsec per sensor pixel
CEILING_RAW = 16000                          # raw values at or above this are at the sensor's ceiling (the clipped clump sits at 16116..16596)
CLUSTER_SKY_RADIUS = 1250                    # sensor px (8.1 arcmin): nothing inside this counts as sky
BRIGHT_SKY_RADIUS = 300                      # sensor px around the saturated field star
CORE_RADIUS = 450                            # sensor px (2.9 arcmin): no registration or quality stars inside this


def W(name):
    return os.path.join(WORK, name)


def frame_list():
    """Frames in the time window, with the sidecar's exposure and ISO."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-0[67]*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), alt_deg=(j.get('pointing') or {}).get('alt_deg')))
    return out


def load_planes(path):
    """Black-subtracted colour planes, plus a boolean cube of pixels at the sensor's ceiling."""
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible.copy()
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = [float(v) for v in r.camera_whitebalance]
        flip = int(r.sizes.flip)
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]], (desc, pat.tolist())
    assert raw16.shape == (4024, 6024), raw16.shape
    raw = raw16.astype(np.float32)
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in OFFS])
    ceil = np.stack([raw16[oy::2, ox::2] >= CEILING_RAW for ox, oy in OFFS])
    return planes, ceil, dict(black=black.tolist(), white=white, wb=wb, flip=flip, rawmax=float(raw16.max()))


def clipped_stats(v, k=3.0, iters=6):
    v = v[np.isfinite(v)]
    lo, hi = -np.inf, np.inf
    m = s = 0.0
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w))


def find_cluster(G):
    """Where the cluster is in one frame (plane px of the green mean). The frame's median is removed, values
    are capped at 300 DN so that one bright star cannot outweigh thousands of faint ones, then a wide
    Gaussian (sigma 40 plane px); the maximum is the cluster. Refined on a sigma-6 blur of the 3x3 median."""
    c = np.clip(G - np.median(G[::4, ::4]), 0, 300)
    sm = cv2.GaussianBlur(c, (0, 0), 40)
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    sm2 = cv2.GaussianBlur(cv2.medianBlur(G, 3), (0, 0), 6)
    y0, x0 = max(y - 150, 0), max(x - 150, 0)
    box = sm2[y0:y + 150, x0:x + 150]; yy, xx = np.unravel_index(np.argmax(box), box.shape)
    return float(x0 + xx), float(y0 + yy)


def find_bright(G, cluster_xy):
    """The saturated field star: the maximum of a sigma-4 blur outside the cluster (plane px)."""
    sm = cv2.GaussianBlur(G, (0, 0), 4)
    h, w = G.shape; yy, xx = np.mgrid[0:h, 0:w]
    sm[np.hypot(xx - cluster_xy[0], yy - cluster_xy[1]) < CLUSTER_SKY_RADIUS / 2] = -1e9
    y, x = np.unravel_index(np.argmax(sm), sm.shape)
    return float(x), float(y)


def sky_mask(shape, cluster_xy, bright_xy):
    """True where the sky is measured (plane coordinates): outside the cluster and the saturated star."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.hypot(xx - cluster_xy[0], yy - cluster_xy[1]) > CLUSTER_SKY_RADIUS / 2
    m &= np.hypot(xx - bright_xy[0], yy - bright_xy[1]) > BRIGHT_SKY_RADIUS / 2
    return m
