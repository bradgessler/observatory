"""Shared pieces for the M31 core stack (adapted from the M15 pipeline of the same night, ../m15/scripts).
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with
cell offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy)."""
import glob, json, os
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.path.join(NIGHT, 'm31')
SCR = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('M31_WORK', os.path.join(os.path.dirname(SCR), 'work'))
os.makedirs(WORK, exist_ok=True)
T0, T1 = '073600', '084659'                  # UTC window of the run (HHMMSS); the 0735 finder frames are before it
EXPOSURE_S, ISO = 20.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) for R, G1, G2, B
SCALE = 0.388                                # arcsec per sensor pixel
CEILING_RAW = 16000                          # raw values at or above this are at the sensor's ceiling
H, Wd = 4024, 6024
CENTRE = np.array([3011.5, 2011.5])          # sensor centre, sensor px
# the corner where the frame's level is measured: plane px (rows, cols) of the top-left corner, 300 x 300 plane px = 600 x 600 sensor px
CORNER = (slice(20, 320), slice(20, 320))


def W(name):
    return os.path.join(WORK, name)


def frame_list():
    """Frames in the time window, with the sidecar's exposure and ISO."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-0[78]*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}
        sha = {x['format']: x['sha256'] for x in j.get('files', [])}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), arw_sha256=sha.get('arw')))
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
    assert raw16.shape == (H, Wd), raw16.shape
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


def radius_plane(p):
    """Distance from the sensor centre (sensor px) of every pixel of colour plane p."""
    ox, oy = OFFS[p]
    yy, xx = np.mgrid[0:H // 2, 0:Wd // 2].astype(np.float32)
    return np.hypot(2 * xx + ox - CENTRE[0], 2 * yy + oy - CENTRE[1])

REF_STAMP = '20261004-081100'                # clear frame near the middle of the run, so the turn is shared out to both sides
CORE_RADIUS = 400                            # sensor px (2.6 arcmin): no registration or quality stars this close to the nucleus
