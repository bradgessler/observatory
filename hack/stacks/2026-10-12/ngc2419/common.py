"""Shared pieces for the NGC 2419 stack of 12/13 October 2026 (a globular cluster in Lynx, the "Intergalactic
Wanderer": a small, faint, round haze 4 to 6 arcmin across, about 300,000 light years out in the Milky Way's halo, with
two bright 7th to 8th magnitude field stars in a line to its west): Sony a6000 on the 8SE (2,08x mm, f/10), 15 s at
ISO 3200, EQ6-R on a tripod set down with the polar axis 5 degrees off the pole, tracking on a pointing model (so the
field turns), unguided. Adapted from hack/stacks/2026-10-12/m78 (same night, telescope, camera and settings); the last
run of the night.

What is different from tonight's M78:
  * the target is a small round haze of unresolved stars on open sky, and beside it stand two stars that touch the
    sensor's ceiling. They clip, they are not repaired, and their glare is kept out of the sky: the object mask (step 6)
    is a circle of 4 arcmin radius on the cluster's catalogue place and one of 2 arcmin on each of the two stars
    (EXTRA below); the sky constant, the flat check and the picture's sky plane all keep outside it.
  * it was 55 to 60 degrees up: air dispersion is small; it is measured on the stack's stars and taken out (step 8).
  * the sky had cleared after cloud in the run before: step 4 measures star brightness frame by frame, step 5 selects on
    it, step 11 says what it did over the run.
  * step 11 is NGC 2419's own: the haze's width above the sky and its profile in the odd and the even half stacks, whether
    any point inside it repeats between the halves (its brightest stars are about 17th magnitude), and its colour.
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

NIGHT = os.path.expanduser(os.environ.get('N2419_NIGHT', '~/.observatory/nights/2026-10-12-a6000'))
STILLS = NIGHT                                                # read only: tonight the frames sit in the night's folder itself
OUT = os.environ.get('N2419_OUT', os.path.join(NIGHT, 'ngc2419'))
WORK = os.environ.get('N2419_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
DATE = '20261013'
T0, T1 = '113200', '115330'                                  # characters 10-15 of the file name, inclusive: the run, with the two 2 s centring pictures before it (step 1 leaves those out by the RAW's own EXIF)
POINTING_RADIUS_DEG = 0.6                                    # a frame belongs to the run if the sidecar's pointing is this close to NGC 2419 (the model read 0.24 deg off all run)
TARGET = dict(name='NGC 2419', ra_deg=114.535292, dec_deg=38.882444)   # J2000 (07h 38m 08.47s, +38d 52' 56.8"): the cluster's centre
EXTRA = [dict(name='bright star A', ra_deg=114.45086, dec_deg=38.87864, radius_arcmin=2.0, dust_blind_px=150),   # 07h 37m 48.2s, +38d 52' 43": 4.0 arcmin west of the cluster; its place measured by this run's own plate solve of the reference frame (step 6), no star catalogue was read. HD 60771 (magnitude 7.2) by its place: an inference
         dict(name='bright star B', ra_deg=114.35780, dec_deg=38.86815, radius_arcmin=2.0, dust_blind_px=150)]   # 07h 37m 25.9s, +38d 52' 05": 8.3 arcmin west, in line with A and the cluster; measured the same way. Both touch the sensor's ceiling in every frame: they clip, and nothing repairs them
GALAXY_PA_DEG = 0.0                                         # the object mask is a circle; kept for solvelib's ellipse
GALAXY_SIZE_ARCMIN = (4.6, 4.6)                              # catalogue size of the cluster (round)
EXPOSURE_S, ISO = 15.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, Wd = 4024, 6024                                           # sensor (raw_image_visible)
h2, w2 = H // 2, Wd // 2                                     # one colour plane = the output grid
CENTRE = np.array([3011.5, 2011.5])                          # sensor centre, sensor px
SCALE = 0.388                                                # arcsec per sensor px (2,084 mm, 3.92 um); the stack's own solve refines it
CEILING_RAW = 16000                                          # raw values at or above this are at the sensor's ceiling (black 512)
WORKERS = int(os.environ.get('N2419_WORKERS', '4'))            # other stacks share the Mac tonight
REF_STAMP = os.environ.get('N2419_REF', '20261013-114318')      # a sharp frame near the middle of the run, so the turn is shared out to both sides

FLAT_DIR = os.environ.get('N2419_FLAT_DIR', os.path.join(NIGHT, 'flat'))   # the night's flat (made by the NGC 891 stack): read only


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
