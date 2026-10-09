"""Shared pieces for the M42 pictures (adapted from ../m31/mosaic/scripts/mcommon.py, the M31 mosaic pipeline).
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). A stack lives on the HALF grid of its reference frame:
half-grid pixel (X, Y) is centred on sensor pixel (2X + 0.5, 2Y + 0.5) (0.776 arcsec per pixel).
Nothing here is generative or learned: array arithmetic, medians, Gaussian and Lanczos filters only."""
import glob, json, os, datetime
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.path.join(NIGHT, 'm42')
SCR = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('M42_WORK', os.path.join(os.path.dirname(SCR), 'work'))
CLOUD_CAL = os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-from-core-run')     # tonight's cloud-glow flat and dust map (M31 core run)
os.makedirs(WORK, exist_ok=True)
T0, T1 = '111400', '131000'                  # UTC window searched for M42 frames (HHMMSS)
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) for R, G1, G2, B
SCALE = 0.3880                               # arcsec per sensor pixel (plate solve at 1154)
HS = 2 * SCALE                               # arcsec per half-grid pixel
BLACK = 512.0
CEILING_RAW = 16000                          # raw values at or above this are at the sensor's ceiling (the top codes scatter 16084..16596)
NEAR_CEILING = 14400.0                       # DN above black: a pixel this high in any plane of any frame is 'within a margin of clipping'.
                                             # 7% under the ceiling (15488): three times a pixel's own photon noise there (470 DN), so a pixel that
                                             # never reaches it in any frame clips in none. (A first version used 12000: it handed three dozen
                                             # middling stars, valid in every deep frame, to the short stack, whose sharper and colour-dispersed
                                             # star images do not fit the deep ones: green and blue star cores. The margin is a choice; this one
                                             # keeps the short stack to where the long frames really are at their limit.)
H, Wd = 4024, 6024
H2, W2 = H // 2, Wd // 2
CENTRE = np.array([3011.5, 2011.5])          # sensor centre, sensor px
CORNER = (slice(20, 320), slice(20, 320))    # plane px: the top-left 600 x 600 sensor px
TRAP_RA, TRAP_DEC = 83.8221, -5.3911         # the Trapezium, J2000, degrees (given)
CORE_RADIUS = 300                            # sensor px: no registration or quality stars this close to the brightest nebula
# the sets, in the order taken. Panels: offset of the aim point in arcmin (east, north) of the Trapezium (given)
PANELS = [('p00', 9.93, 15.78), ('p10', -18.40, 3.10), ('p11', -9.93, -15.78), ('p01', 18.40, -3.10)]
DEEP_SETS = ['deep']
EXPO = dict(deep=(20.0, 3200), short=(2.0, 800))
# the hair on the sensor (it creeps): the zone searched for it, sensor px x0, y0, x1, y1
HAIR_BOX = (3200, 0, 4400, 700)


def W(name):
    return os.path.join(WORK, name)


def tsec(iso):
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def exif_settings(jpg):
    """Exposure time and ISO as the CAMERA wrote them into the JPEG that came with the RAW (the sidecar holds what
    the box had asked for, which can be one frame out of step when a setting is changed between frames)."""
    from PIL import Image
    try:
        ifd = Image.open(jpg).getexif().get_ifd(0x8769)
        return float(ifd.get(0x829A)), int(ifd.get(0x8827))
    except Exception:
        return None, None


def frame_list():
    """Every RAW still in the time window, with the sidecar's settings, time and mount pointing, and the camera's own EXIF settings."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-1[1-3]*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1) or not os.path.exists(f[:-4] + '.json'):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}
        sha = {x['format']: x['sha256'] for x in j.get('files', [])}
        e_exp, e_iso = exif_settings(f[:-4] + '.JPG')
        out.append(dict(path=f, name=b, stamp=b[:15], sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'), exif_exposure_s=e_exp, exif_iso=e_iso,
                        exposure_s=e_exp if e_exp is not None else cam.get('exposure_s'), iso=e_iso if e_iso is not None else cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), arw_sha256=sha.get('arw'), bytes=os.path.getsize(f)))
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


NB8 = np.ones((3, 3), np.uint8); NB8[1, 1] = 0


def repair(planes, hot, corner):
    """Hot pixels and single-frame spikes -> the 3x3 median of the same colour plane. Returns the number of spikes.
    corner: per plane (clipped mean, clipped std) of the frame's top-left corner, for the noise scale.
    A pixel at or near the ceiling is never 'repaired' (a flat-topped star is not a spike)."""
    trans = 0
    for p in range(4):
        P = planes[p]
        med3 = cv2.medianBlur(P, 3)
        s0 = max(corner[p][1], 1.0); l0 = max(corner[p][0], 1.0)
        s = s0 * np.sqrt(np.maximum(med3, l0) / l0)
        spike = (P - med3) > (8 * s + 0.5 * np.clip(med3, 0, None))
        spike &= ~hot[p]
        trans += int(spike.sum())
        bad = hot[p] | spike
        P[bad] = med3[bad]
    return trans


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


def gnomonic(ra, dec, ra0=TRAP_RA, dec0=TRAP_DEC):
    """Tangent-plane coordinates (xi east, eta north), in arcsec, of (ra, dec) degrees about (ra0, dec0)."""
    ra, dec = np.radians(ra), np.radians(dec); a0, d0 = np.radians(ra0), np.radians(dec0)
    c = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(ra - a0)
    xi = np.cos(dec) * np.sin(ra - a0) / c
    eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(ra - a0)) / c
    return np.degrees(xi) * 3600, np.degrees(eta) * 3600


def ungnomonic(xi, eta, ra0=TRAP_RA, dec0=TRAP_DEC):
    xi, eta = np.radians(np.asarray(xi) / 3600), np.radians(np.asarray(eta) / 3600); a0, d0 = np.radians(ra0), np.radians(dec0)
    den = np.cos(d0) - eta * np.sin(d0)
    ra = a0 + np.arctan2(xi, den)
    dec = np.arctan2((np.sin(d0) + eta * np.cos(d0)) * np.cos(ra - a0), den)
    return np.degrees(ra), np.degrees(dec)


def blocks_median(a, bs):
    """Medians of bs x bs blocks, NaN left out; blocks with under half their pixels are NaN."""
    h, w = a.shape; ny, nx = h // bs, w // bs
    b = a[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(b).sum(2); v = np.nanmedian(b, axis=2)
    v[n < bs * bs // 2] = np.nan
    return v
