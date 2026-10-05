"""Shared pieces for the NGC 7662 stack. RAW colour planes, no demosaic.
Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset (ox, oy)
sits at sensor pixel (2X + ox, 2Y + oy)."""
import glob, json, os
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.path.join(NIGHT, 'ngc7662')
SCR = os.path.dirname(os.path.abspath(__file__))
T0, T1 = '063334', '064316'
REF_STAMP = '20261004-063850'
NEB_REF = (3466.0, 2270.0)      # sensor px in the reference frame (given)
STAR_REF = (2316.0, 2812.0)
PLANE_NAMES = ['R', 'G1', 'G2', 'B']


def frame_list():
    """Frames in the time window, with the sidecar's exposure and ISO."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-06*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed')))
    return out


def load_planes(path):
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = [float(v) for v in r.camera_whitebalance]
        flip = int(r.sizes.flip)
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]], (desc, pat.tolist())
    # (ox, oy) for R, G1, G2, B
    offs = [(0, 0), (1, 0), (0, 1), (1, 1)]
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in offs])
    rawmax = float(raw.max())
    return planes, dict(black=black.tolist(), white=white, wb=wb, flip=flip, rawmax=rawmax, offs=offs)


def clipped_stats(v, k=3.0, iters=6):
    v = v[np.isfinite(v)]
    lo, hi = -np.inf, np.inf
    m = s = 0.0
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w))


def sky_mask(shape, centres, radius_native=260):
    """True where the sky is measured: away from the nebula and the bright star (plane coordinates)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.ones(shape, bool)
    for cx, cy in centres:
        m &= (xx - cx / 2) ** 2 + (yy - cy / 2) ** 2 > (radius_native / 2) ** 2
    return m
