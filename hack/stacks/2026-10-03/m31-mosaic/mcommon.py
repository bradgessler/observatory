"""Shared pieces for the M31 six-panel mosaic (adapted from ../../scripts/common.py, the core stack's pipeline).
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). A panel's stack lives on the HALF grid of its reference
frame: half-grid pixel (X, Y) is centred on sensor pixel (2X + 0.5, 2Y + 0.5) (0.776 arcsec per pixel)."""
import glob, json, os
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
CORE_DIR = os.path.join(NIGHT, 'm31')
OUT = os.path.join(CORE_DIR, 'mosaic')
SCR = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('M31M_WORK', os.path.join(os.path.dirname(SCR), 'work'))
# working files of the core run that this pipeline reads (never writes): flat2d.npy, dustmask.npy, dustratio.npy,
# hotmap.npy, step1.json, vignette.json. M31_CORE_WORK if set; else the core run's own work folder beside this one
# (where it was when the mosaic was made); else the copies kept with the results in calibration-from-core-run/.
_cw = os.path.join(os.path.dirname(os.path.dirname(SCR)), 'm31', 'work')
CORE_WORK = os.environ.get('M31_CORE_WORK', _cw if os.path.exists(os.path.join(_cw, 'flat2d.npy')) else os.path.join(OUT, 'calibration-from-core-run'))
os.makedirs(WORK, exist_ok=True)
T0, T1 = '091500', '102259'                  # UTC window of the mosaic run (HHMMSS)
EXPOSURE_S, ISO = 30.0, 3200
CORE_EXPOSURE_S = 20.0
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) for R, G1, G2, B
SCALE = 0.3881                               # arcsec per sensor pixel (plate solve of the 0915 frame)
CEILING_RAW = 16000
H, Wd = 4024, 6024
H2, W2 = H // 2, Wd // 2
CENTRE = np.array([3011.5, 2011.5])          # sensor centre, sensor px
CORNER = (slice(20, 320), slice(20, 320))    # plane px: the top-left 600 x 600 sensor px
NUC_RA, NUC_DEC = 10.6847, 41.2690           # the nucleus, J2000, degrees (given)
CORE_RADIUS = 400                            # sensor px: no registration or quality stars this close to the nucleus
# panels in the order taken: name, offset of the aim point in arcmin (east, north) of the nucleus
PANELS = [('centre', 0.0, 0.0), ('p00', 19.7, 26.2), ('p10', -5.9, 8.5), ('p20', -31.4, -9.1), ('p21', -19.7, -26.2), ('p11', 5.9, -8.5), ('p01', 31.4, 9.1)]
# the hair on the sensor (it moves; the core run's map cannot be trusted for it): a generous box, sensor px x0, y0, x1, y1
HAIR_BOX = (3560, 0, 4200, 560)


def W(name):
    return os.path.join(WORK, name)


def CW(name):
    return os.path.join(CORE_WORK, name)


def frame_list():
    """Every still in the time window, with the sidecar's exposure, ISO, time and the mount's pointing."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-09*.ARW')) + glob.glob(os.path.join(STILLS, '20261004-10*.ARW'))):
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
    if v.size == 0: return float('nan'), float('nan'), float('nan')
    lo, hi = -np.inf, np.inf
    m = s = 0.0; w = v
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        if w.size == 0: break
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w)) if w.size else m


def radius_plane(p):
    ox, oy = OFFS[p]
    yy, xx = np.mgrid[0:H2, 0:W2].astype(np.float32)
    return np.hypot(2 * xx + ox - CENTRE[0], 2 * yy + oy - CENTRE[1])


def tsec(iso):
    import datetime
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def gnomonic(ra, dec, ra0=NUC_RA, dec0=NUC_DEC):
    """Tangent-plane coordinates (xi east, eta north), in arcsec, of (ra, dec) degrees about (ra0, dec0)."""
    ra, dec = np.radians(ra), np.radians(dec); a0, d0 = np.radians(ra0), np.radians(dec0)
    c = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(ra - a0)
    xi = np.cos(dec) * np.sin(ra - a0) / c
    eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(ra - a0)) / c
    return np.degrees(xi) * 3600, np.degrees(eta) * 3600


def ungnomonic(xi, eta, ra0=NUC_RA, dec0=NUC_DEC):
    xi, eta = np.radians(np.asarray(xi) / 3600), np.radians(np.asarray(eta) / 3600); a0, d0 = np.radians(ra0), np.radians(dec0)
    den = np.cos(d0) - eta * np.sin(d0)
    ra = a0 + np.arctan2(xi, den)
    dec = np.arctan2((np.sin(d0) + eta * np.cos(d0)) * np.cos(ra - a0), den)
    return np.degrees(ra), np.degrees(dec)
