"""Shared pieces for the Messier 78 stack of 12/13 October 2026 (NGC 2068, a reflection nebula in Orion, about 8 x 6
arcmin: dust lit by the two 10th magnitude stars HD 38563 A and B, cut on its north-west side by a dark lane, with the
smaller NGC 2071 a quarter of a degree to the north-north-east): Sony a6000 on the 8SE (2,08x mm, f/10), 15 s at
ISO 3200, EQ6-R on a tripod set down with the polar axis 5 degrees off the pole, tracking on a pointing model (so the
field turns), unguided. Adapted from hack/stacks/2026-10-12/m1 (same night, telescope, camera and settings, the run
just before this one).

What is different from tonight's M1:
  * the target is larger and has no hard edge: a reflection nebula fades into the dust around it, and the frame is only
    39 x 26 arcmin. The sky level is the question. The object mask (step 6) is a circle of 7 arcmin radius on M78 (it
    holds NGC 2067 too), one of 4 arcmin on NGC 2071 and one of 3 arcmin on NGC 2064; the sky constant, the flat
    check and the picture's sky plane all keep outside it.
  * it was 43 to 46 degrees up: air dispersion is larger than on M1 (60 degrees) and is measured and taken out (step 8).
  * step 11 is M78's own: the glow round the two stars, the dark lane, how far the nebula reaches, its colour against
    the colour of the field's stars (is the blue measured?), NGC 2071, each proved on the odd and the even half stacks.
  * the flat is the night's flat in <night>/flat/ (built from the NGC 891 run), read in step 7 and checked there against
    this run's own open sky, dust it leaves measured and divided out.

RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset
(ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). The stack is made on the reference frame's grid of 2 x 2 colour cells:
output pixel (X, Y) is the centre of the reference frame's cell, sensor (2X + 0.5, 2Y + 0.5). One picture pixel per
colour cell (0.776 arcsec), nothing enlarged.

The RAWs are read in place and never written; nothing is cached per frame (the disk is tight). Every knob is an
environment variable; with none set the scripts reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M78_NIGHT', '~/.observatory/nights/2026-10-12-a6000'))
STILLS = NIGHT                                                # read only: tonight the frames sit in the night's folder itself
OUT = os.environ.get('M78_OUT', os.path.join(NIGHT, 'm78'))
WORK = os.environ.get('M78_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
DATE = '20261013'
T0, T1 = '102400', '105100'                                  # characters 10-15 of the file name, inclusive: the run, with the two 2 s centring pictures before it (step 1 leaves those out by the RAW's own EXIF)
POINTING_RADIUS_DEG = 0.6                                    # a frame belongs to the run if the sidecar's pointing is this close to M78 (the model read 0.32 deg off all run)
TARGET = dict(name='M78', ra_deg=86.690833, dec_deg=0.079167)     # NGC 2068, J2000 (05h 46m 45.8s, +00d 04' 45"): the bright northern part of the nebula, by the two stars
EXTRA = [dict(name='NGC 2071', ra_deg=86.779167, dec_deg=0.294167, radius_arcmin=4.0, dust_blind_px=170),     # 05h 47m 07s, +00d 17' 39": a smaller reflection nebula 14 arcmin north-north-east, at the frame's edge
         dict(name='NGC 2064', ra_deg=86.576667, dec_deg=0.005833, radius_arcmin=3.0, dust_blind_px=130)]     # 05h 46m 18.4s, +00d 00' 21": a faint patch of the same cloud 8 arcmin west-south-west, just outside M78's circle (seen in the reference frame)
GALAXY_PA_DEG = 0.0                                         # the object mask is a circle; kept for solvelib's ellipse
GALAXY_SIZE_ARCMIN = (8.0, 6.0)                              # catalogue size of the nebula, major x minor
EXPOSURE_S, ISO = 15.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, Wd = 4024, 6024                                           # sensor (raw_image_visible)
h2, w2 = H // 2, Wd // 2                                     # one colour plane = the output grid
CENTRE = np.array([3011.5, 2011.5])                          # sensor centre, sensor px
SCALE = 0.388                                                # arcsec per sensor px (2,084 mm, 3.92 um); the stack's own solve refines it
CEILING_RAW = 16000                                          # raw values at or above this are at the sensor's ceiling (black 512)
WORKERS = int(os.environ.get('M78_WORKERS', '4'))            # other stacks share the Mac tonight
REF_STAMP = os.environ.get('M78_REF', '20261013-103904')      # a sharp frame near the middle of the run, so the turn is shared out to both sides

FLAT_DIR = os.environ.get('M78_FLAT_DIR', os.path.join(NIGHT, 'flat'))   # the night's flat (made by the NGC 891 stack): read only


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
                        t=(j.get('time') or {}).get('shutter_pressed'), pointing_from_target_deg=sep, ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
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
    full size (bilinear). Follows the nebula's glow and the sky; stars, being smaller than a few blocks, drop out."""
    import cv2
    h, w = G.shape; ny, nx = h // block, w // block
    b = np.median(G[:ny * block, :nx * block].reshape(ny, block, nx, block).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2).astype(np.float32)
    b = cv2.medianBlur(b, k)
    return cv2.resize(b, (w, h), interpolation=cv2.INTER_LINEAR)


def jdump(obj, name):
    json.dump(obj, open(W(name), 'w'), indent=1)


def jload(name):
    return json.load(open(W(name)))
