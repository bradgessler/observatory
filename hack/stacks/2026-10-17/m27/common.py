"""MESSIER 27, THE DUMBBELL NEBULA, night of 17/18 October 2026 (frames of 18 October UTC). A copy of
hack/stacks/2026-10-12/m77-calibrated (the calibrated pipeline: a flat whose large scale comes from open sky and whose
dust is measured, star colours from Gaia, darks.subtract that changes nothing without darks and says so) with the
combine of hack/stacks/2026-10-12/ngc891-coadd (proper coaddition, keep_phase='mean', the old sigma-clipped weighted
mean made from the same cube as a control).

What is different from M77:
  * the target is a planetary nebula, about 8 x 5.6 arcmin of bright body ("apple core") inside a faint halo about
    15 arcmin across; the frame is 39 x 26 arcmin. The object mask is a circle of MASK_R arcmin round the central star
    (generous: it holds the faint outer lobes); the flat check, the sky constant and the dust search keep outside it.
  * the flat: there were no twilight flats and no darks tonight. Step 7a builds candidate flats and step 7 checks them on
    this run's own open sky (FLAT_SOURCE, below); dust that moved since 13 October is measured on this run's own sky
    (step 7, seen in the odd and in the even frames alone) and divided out.
  * unguided, not dithered: the field drifted 3.2 arcmin across the sensor over the 36 minutes (sidecar plate solves),
    which is what lets this run's own sky show dust that sits still on the sensor.
  * the camera's tilt sensor tags these frames portrait: everything here reads the RAW's own grid (rawpy
    raw_image_visible), which is the sensor's, never the JPEG's orientation.

Plane geometry as in the template: RAW colour planes, no demosaic, R, G1, G2, B; plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). One picture pixel per colour cell (0.776 arcsec).

The RAWs are read in place and never written; nothing is cached per frame. Every knob is an environment variable; with
none set the scripts reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M27_NIGHT', '~/.observatory/nights/2026-10-17-a6000'))   # work space only (not git)
STILLS = os.path.expanduser(os.environ.get('M27_STILLS', '~/.observatory/stills/2026-10-18'))   # read only: the RAWs (UTC date folder)
SCR_ = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('M27_OUT', os.path.join(NIGHT, 'm27'))          # the stack (TIF) and the full field
FINAL = os.environ.get('M27_FINAL', os.path.join(SCR_, 'final'))      # the finished pictures and recipe, beside the scripts
NAME = os.environ.get('M27_NAME', 'm27')                          # the finished picture: FINAL/NAME.png|jpg|json
TOOLS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
import sys as _sys
if TOOLS not in _sys.path: _sys.path.insert(0, TOOLS)
FLAT_SOURCE = os.environ.get('M27_FLAT_SOURCE', 'hybrid13')          # hybrid13 | twilight13 | m33 (step 7a builds m33); see step 7
COLOUR_CAL = os.environ.get('M27_COLOUR_CAL', '1') == '1'
DARKS_DIR = os.environ.get('M27_DARKS_DIR', os.path.join(NIGHT, 'darks'))
WORK = os.environ.get('M27_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
DATE = '20261018'
T0, T1 = '034600', '042230'                                  # characters 10-15 of the file name, inclusive: the 15 s ISO 3200 run on M27
POINTING_RADIUS_DEG = 0.25                                   # a frame belongs to the run if its plate solve (sidecar .solve.json) is this close to M27
TARGET = dict(name='M27', ra_deg=299.901579, dec_deg=22.721056)   # the central star of NGC 6853, J2000 (19h 59m 36.38s, +22d 43' 15.8")
GALAXY_PA_DEG = 30.0                                        # the bright body's long axis (the 'apple core' lobes run roughly NNE-SSW), north through east; only labels use it
GALAXY_SIZE_ARCMIN = (8.0, 5.6)                              # the bright body, catalogue (8.0 x 5.6 arcmin); the faint halo is about 15 arcmin across
MASK_R_ARCMIN = float(os.environ.get('M27_MASK_R', '9.0'))   # radius of the object mask: the halo and a margin
EXPOSURE_S, ISO = 15.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, Wd = 4024, 6024                                           # sensor (raw_image_visible)
h2, w2 = H // 2, Wd // 2                                     # one colour plane = the output grid
CENTRE = np.array([3011.5, 2011.5])                          # sensor centre, sensor px
SCALE = 0.388                                                # arcsec per sensor px (2,084 mm, 3.92 um); the stack's own solve refines it
CEILING_RAW = 16000                                          # raw values at or above this are at the sensor's ceiling (black 512)
WORKERS = int(os.environ.get('M27_WORKERS', '6'))            # the night's frames are still arriving on this Mac
REF_STAMP = os.environ.get('M27_REF', '20261018-040355')      # a sharp frame in the middle of the run

FLAT_DIRS = dict(hybrid13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-hybrid-m77'),   # 13 Oct: large scale from that night's open sky, dust from its twilight flats
                 twilight13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-twilight'),  # 13 Oct twilight flats as measured (the telescope parked at the pole)
                 m33=os.path.join(NIGHT, 'flat-sky-m33'))                                                 # tonight's M33 run's sky (step 7a) x the 13 Oct twilight dust
FLAT_DIR = os.environ.get('M27_FLAT_DIR', FLAT_DIRS[FLAT_SOURCE])   # read only


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
        sol = (json.load(open(sv)).get('solution') or {}) if os.path.exists(sv) else {}
        # tonight the sidecar's pointing is the star-alignment model's (about 1 degree off); the frame's own plate solve decides
        src = sol if sol.get('ra_deg') is not None else pt
        sep = None
        if src.get('ra_deg') is not None:
            sep = float(np.hypot((src['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), src['dec_deg'] - TARGET['dec_deg']))
        out.append(dict(path=f, name=b, stamp=b[:15], seq=j.get('seq'), sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), pointing_from_target_deg=sep, ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        since_slew_s=(j.get('settle') or {}).get('since_slew_s'), box_star_size_arcsec=(ms.get('star_size') or {}).get('arcsec'),
                        had_plate_solve=bool(sol), solve_centre_ra_dec=[sol.get('ra_deg'), sol.get('dec_deg')] if sol else None, solve_rotation_deg=sol.get('rotation_deg'), pointing_from='plate solve' if sol else 'sidecar pointing', settling=j.get('settling'),
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
    import darks
    planes, meta['dark'] = darks.subtract(planes, EXPOSURE_S, ISO, DARKS_DIR)      # no master dark: unchanged, and says so
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
    import darks
    mpath = darks.master_for(EXPOSURE_S, ISO, DARKS_DIR)
    if mpath: P = P - np.load(mpath)[PLANE_NAMES[p]].astype(np.float32)
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
