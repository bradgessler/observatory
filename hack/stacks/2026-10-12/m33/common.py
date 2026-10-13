"""Shared pieces for the M33 (Triangulum Galaxy) stack of 12/13 October 2026: Sony a6000 on the 8SE (2,088 mm, f/10),
15 s at ISO 3200, EQ6-R on a tripod set down with the polar axis 5 degrees off the pole, tracking in both axes on a
pointing model (so the field turns). Adapted from hack/stacks/2026-10-08/m33 (same target, telescope and camera).

What is different from 8 October:
  * 104 frames instead of 24, and a tight disk: nothing is cached per frame. Every step reads the RAWs in place
    (hot pixels repaired on the fly from step 1's map); the only big files are the stack arrays of step 7.
  * until 08:19 UTC the tracking let go of both motors for about 5 s now and then (a software bug), so many frames
    are trailed: selection is by star shape (step 5).
  * no open-sky run at these settings tonight, so the flat is the 8 October one, checked against tonight's frames
    (step 6).

RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset
(ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). The stack is made on the reference frame's grid of 2 x 2 colour cells:
output pixel (X, Y) is the centre of the reference frame's cell, sensor (2X + 0.5, 2Y + 0.5). One picture pixel per
colour cell (0.776 arcsec), nothing enlarged.

The galaxy is far bigger than the frame (about 70 x 40 arcmin against a 39 x 26 arcmin field), so there is no empty
sky anywhere in it. Sky handling is at most ONE constant per colour per frame, measured where the field is faintest.
No surface is fitted over the galaxy.

The RAWs are read in place and never written. Every knob is an environment variable; with none set the scripts
reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M33_NIGHT', '~/.observatory/nights/2026-10-12-a6000'))
STILLS = NIGHT                                                # read only: tonight the frames sit in the night's folder itself
OUT = os.environ.get('M33_OUT', os.path.join(NIGHT, 'm33'))
WORK = os.environ.get('M33_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
DATE = '20261013'
T0, T1 = '072000', '083400'                                  # characters 10-15 of the file name, inclusive: the 15 s ISO 3200 run
POINTING_RADIUS_DEG = 1.5                                    # a frame belongs to the run if the sidecar's pointing is this close to M33
TARGET = dict(name='M33', ra_deg=23.4621, dec_deg=30.6599)
EXPOSURE_S, ISO = 15.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, Wd = 4024, 6024                                           # sensor (raw_image_visible)
h2, w2 = H // 2, Wd // 2                                     # one colour plane = the output grid
CENTRE = np.array([3011.5, 2011.5])                          # sensor centre, sensor px
SCALE = 0.388                                                # arcsec per sensor px (2,084 mm, 3.92 um); the stack's own solve refines it
CEILING_RAW = 16000                                          # raw values at or above this are at the sensor's ceiling (black 512)
WORKERS = int(os.environ.get('M33_WORKERS', '4'))            # other stacks share the Mac tonight
REF_STAMP = os.environ.get('M33_REF', '20261013-080020')     # a sharp frame near the middle of the run, so the turn is shared out to both sides

FLAT_FROM = os.path.expanduser('~/.observatory/nights/2026-10-08-a6000/m33/work/step6_vignette.json')   # the 8 October flat's numbers (step 6)


def W(name):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def raw_exif(path):
    """Exposure and ISO from the RAW's own EXIF (the sidecar can be wrong when settings changed)."""
    import tifffile
    with tifffile.TiffFile(path) as t:
        ex = t.pages[0].tags['ExifTag'].value
    e = ex.get('ExposureTime'); e = e[0] / e[1] if isinstance(e, tuple) else float(e)
    return float(e), int(ex.get('ISOSpeedRatings'))


def frame_list(t0=T0, t1=T1):
    """Frames in the time window, with the sidecar's facts."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (t0 <= stamp <= t1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}; ms = j.get('measured') or {}
        sv = f[:-4] + '.solve.json'
        sep = None
        if pt.get('ra_deg') is not None:
            sep = float(np.hypot((pt['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), pt['dec_deg'] - TARGET['dec_deg']))
        out.append(dict(path=f, name=b, stamp=b[:15], seq=j.get('seq'), sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), pointing_from_m33_deg=sep, ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        since_slew_s=(j.get('settle') or {}).get('since_slew_s'), box_star_size_arcsec=(ms.get('star_size') or {}).get('arcsec'),
                        had_plate_solve=os.path.exists(sv),
                        arw_sha256={x['format']: x['sha256'] for x in j.get('files', [])}.get('arw')))
    return out


def load_planes(path):
    """Black-subtracted colour planes (4, 2012, 3012) float32, a boolean cube of pixels at the sensor's ceiling, facts."""
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible.copy()
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        meta = dict(black=black.tolist(), white=float(r.white_level), wb=[float(v) for v in r.camera_whitebalance],
                    wb_daylight=[float(v) for v in r.daylight_whitebalance], flip=int(r.sizes.flip), rawmax=float(raw16.max()))
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]] and raw16.shape == (H, Wd), (desc, pat.tolist(), raw16.shape)
    raw = raw16.astype(np.float32)
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in OFFS])
    ceil = np.stack([raw16[oy::2, ox::2] >= CEILING_RAW for ox, oy in OFFS])
    return planes, ceil, meta


_HOT = None


def load_clean(path, sigmas=None):
    """load_planes + the hot-pixel repair of step 1 (fixed map from work/hotmap.npy, transient spikes per frame), done
    on the fly: nothing is cached. Returns planes, the count of transient pixels replaced per plane, meta."""
    import cv2
    global _HOT
    if _HOT is None: _HOT = np.load(W('hotmap.npy'))
    P, ceil, meta = load_planes(path)
    trans = []
    for p in range(4):
        med3 = cv2.medianBlur(P[p], 3)
        if sigmas is None:
            d = (P[p] - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
        else:
            s = sigmas[p]
        spike = ((P[p] - med3) > 8 * s + 0.5 * np.clip(med3, 0, None)) & ~_HOT[p]
        trans.append(int(spike.sum()))
        bad = _HOT[p] | spike
        P[p][bad] = med3[bad]
    meta['transient_replaced'] = trans
    return P, meta


def load_clean_plane(path, p):
    """One colour plane of a RAW, black subtracted, hot pixels repaired as in load_clean (fixed map + transient spikes)."""
    import cv2
    global _HOT
    if _HOT is None: _HOT = np.load(W('hotmap.npy'))
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible; pat = r.raw_pattern; black = r.black_level_per_channel
        ox, oy = OFFS[p]
        P = raw16[oy::2, ox::2].astype(np.float32) - np.float32(black[pat[oy, ox]])
    med3 = cv2.medianBlur(P, 3)
    d = (P - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
    bad = _HOT[p] | ((P - med3) > 8 * s + 0.5 * np.clip(med3, 0, None))
    P[bad] = med3[bad]
    return P


def path_of(stamp):
    return glob.glob(os.path.join(STILLS, stamp + '-*.ARW'))[0]


def clipped_stats(v, k=3.0, iters=6):
    v = np.asarray(v); v = v[np.isfinite(v)]
    lo, hi = -np.inf, np.inf
    m = s = 0.0; w = v
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w))


def nat(s):
    """A star measured on the plane grid (x, y) -> sensor px."""
    return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])


def radius_plane(p):
    """Distance from the sensor centre (sensor px) of every pixel of colour plane p."""
    ox, oy = OFFS[p]
    yy, xx = np.mgrid[0:h2, 0:w2].astype(np.float32)
    return np.hypot(2 * xx + ox - CENTRE[0], 2 * yy + oy - CENTRE[1])


def smooth_level(G, block=16, k=5):
    """The smooth light under the stars: block medians (block x block plane px), a k x k median of those, back to
    full size (bilinear). Follows the galaxy's glow and the sky; stars, being smaller than a few blocks, drop out."""
    import cv2
    h, w = G.shape; ny, nx = h // block, w // block
    b = np.median(G[:ny * block, :nx * block].reshape(ny, block, nx, block).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2).astype(np.float32)
    b = cv2.medianBlur(b, k)
    return cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)


def jdump(obj, name):
    json.dump(obj, open(W(name), 'w'), indent=1)


def jload(name):
    return json.load(open(W(name)))
