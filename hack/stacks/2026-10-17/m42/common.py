"""MESSIER 42, THE ORION NEBULA (with M43), night of 17/18 October 2026 (frames of 18 October UTC). A copy of
hack/stacks/2026-10-17/m33 (tonight's calibrated pipeline: the 13 October hybrid flat, dust measured on the run's own
dithered sky against the stack itself, Gaia star colours, darks.subtract that changes nothing without darks and says
so; every frame first placed by its own plate solve, then rotation + shift on the stars) with the combine of
hack/stacks/2026-10-17/m27 (proper coaddition, tools/coadd.py, the old sigma-clipped weighted mean made from the same
cube as a control) and the long + short join of hack/stacks/2026-10-03/m42 (s9_hdr.py).

The runs (characters 10-15 of the file name, inclusive; the RAW's own EXIF decides the exposure):
  pre    08:57 to 08:59 UTC: 30 s at ISO 1600 before the firmware flash (one frame); kept if it passes the rules
  long   09:02 to 11:56 UTC: 30 s at ISO 1600, dithered every 3 frames in a sunflower spiral up to 1.5 arcmin
         (sidecar `dither`), the first few after 09:02 small probe steps (and four frames before the first dither)
  short  11:56 to 12:17 UTC: 2 s at ISO 400 for the bright core (the Trapezium region), dithered as well
Centring frames (2 s at ISO 6400) are left out by their exposure.

What is different from M33:
  * two exposures. The long and the short frames are found, measured, registered (onto ONE reference: a long frame)
    and selected each against their own kind; stacked separately on the same canvas with the same flat; then joined
    (step 8b) where any long frame came within 7 percent of the sensor's ceiling. Expected ratio 30 s x ISO 1600 over
    2 s x ISO 400 = 60, measured on the nebula and on unclipped stars.
  * the target's place is the Trapezium (theta1 Orionis C); the "object mask" is a circle of OBJ_R_ARCMIN round it (the
    bright Huygens region), which keeps the PSF stars, the dust search and the colour calibration off the bright core.
    M42's glow fills the frame: the stack's zero is the faintest part of the field, not the true sky.
  * dust halves: the first and the second half of the long run in time (dither positions and the field's rotation
    differ between them).

Plane geometry as in the template: RAW colour planes, no demosaic, R, G1, G2, B; plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). One picture pixel per colour cell (0.776 arcsec). Every image
is read from the RAW's own grid (rawpy raw_image_visible), never the JPEG's EXIF orientation.

The RAWs are read in place and never written; nothing is cached per frame. Every knob is an environment variable
(M42_*); with none set the scripts reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M42_NIGHT', '~/.observatory/nights/2026-10-17-a6000'))   # work space only (not git)
STILLS = os.path.expanduser(os.environ.get('M42_STILLS', '~/.observatory/stills/2026-10-18'))   # read only: tonight's RAWs (UTC date folder)
SCR_ = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('M42_OUT', os.path.join(NIGHT, 'm42'))
FINAL = os.environ.get('M42_FINAL', os.path.join(SCR_, 'final'))
NAME = os.environ.get('M42_NAME', 'm42')
TOOLS = os.path.abspath(os.path.join(SCR_, '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
import sys as _sys
if TOOLS not in _sys.path: _sys.path.insert(0, TOOLS)
DARKS_DIR = os.environ.get('M42_DARKS_DIR', os.path.join(NIGHT, 'darks'))
WORK = os.environ.get('M42_WORK', os.path.join(OUT, 'work'))
SCR = SCR_
TURNS = [('pre', STILLS, '20261018', '085700', '085959'), ('long', STILLS, '20261018', '090200', '115640'), ('short', STILLS, '20261018', '115641', '121700')]
KIND_OF = {'pre': 'long', 'long': 'long', 'short': 'short'}
EXPECT = {'long': (30.0, 1600), 'short': (2.0, 400)}          # exposure s, ISO by kind (the RAW's own EXIF must say this)
POINTING_RADIUS_DEG = 0.5                                    # a frame belongs to the run if its plate solve is this close to the Trapezium
TARGET = dict(name='M42', ra_deg=83.818583, dec_deg=-5.389694)   # theta1 Orionis C, the brightest star of the Trapezium, J2000 (05h 35m 16.46s, -05d 23' 22.9")
GALAXY_PA_DEG = 0.0                                          # (the template's name) the object mask is a circle: no position angle
OBJ_R_ARCMIN = float(os.environ.get('M42_OBJ_R_ARCMIN', '7.0'))   # the bright Huygens region and the Orion Bar, round the Trapezium
EXPOSURE_S, ISO = EXPECT['long']
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]
H, Wd = 4024, 6024
h2, w2 = H // 2, Wd // 2
CENTRE = np.array([3011.5, 2011.5])
SCALE = 0.388
CEILING_RAW = 16000
NEAR_CEILING = 0.93                                          # "within 7 percent of clipping": above black, 0.93 x (16000 - 512) = 14404 DN
WORKERS = int(os.environ.get('M42_WORKERS', '8'))
REF_STAMP = os.environ.get('M42_REF', '20261018-102251')      # a long frame mid-run, dither k=28 (0.6 arcmin from the spiral's centre), 72 s after its move
CANVAS_PAD = int(os.environ.get('M42_CANVAS_PAD', '400'))     # plane px each side of the reference grid before the cut to where frames are
FLAT_SOURCE = os.environ.get('M42_FLAT_SOURCE', 'hybrid13')
FLAT_DIRS = dict(hybrid13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-hybrid-m77'),
                 twilight13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-twilight'))
FLAT_DIR = os.environ.get('M42_FLAT_DIR', FLAT_DIRS[FLAT_SOURCE])   # read only
COLOUR_CAL = os.environ.get('M42_COLOUR_CAL', '1') == '1'


def kind_of_stamp(stamp):
    t = turn_of(stamp)
    return KIND_OF.get(t) if t else None


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


def turn_of(stamp):
    for name, folder, date, t0, t1 in TURNS:
        if stamp[:8] == date and t0 <= stamp[9:15] <= t1: return name
    return None


def frame_list():
    """Frames in the turns' windows, with the sidecar's facts and the frame's own plate solve."""
    out = []
    for turn, folder, date, t0, t1 in TURNS:
        for f in sorted(glob.glob(os.path.join(folder, date + '-??????-*.ARW'))):
            b = os.path.basename(f); stamp = b[9:15]
            if not (t0 <= stamp <= t1):
                continue
            j = json.load(open(f[:-4] + '.json'))
            cam = j.get('camera') or {}; pt = j.get('pointing') or {}; ms = j.get('measured') or {}
            sv = f[:-4] + '.solve.json'
            sol = (json.load(open(sv)).get('solution') or {}) if os.path.exists(sv) else {}
            src = sol if sol.get('ra_deg') is not None else {}
            sep = None
            if src.get('ra_deg') is not None:
                sep = float(np.hypot((src['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), src['dec_deg'] - TARGET['dec_deg']))
            out.append(dict(path=f, name=b, stamp=b[:15], turn=turn, kind=KIND_OF[turn], night='18oct', seq=j.get('seq'), sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
                            t=(j.get('time') or {}).get('shutter_pressed'), pointing_from_target_deg=sep, ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                            since_slew_s=(j.get('settle') or {}).get('since_slew_s'), box_star_size_arcsec=(ms.get('star_size') or {}).get('arcsec'),
                            had_plate_solve=bool(sol.get('ra_deg') is not None), solve_centre_ra_dec=[sol.get('ra_deg'), sol.get('dec_deg')] if sol else None, solve_rotation_deg=sol.get('rotation_deg'),
                            solve_parity=sol.get('parity'), settling=j.get('settling'), dither=j.get('dither'),
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
    planes, meta['dark'] = darks.subtract(planes, *EXPECT[kind_of_stamp(os.path.basename(path)[:15]) or 'long'], DARKS_DIR)      # no master dark: unchanged, and says so
    return planes, ceil, meta


_HOT = {}


def _hot(path):
    """The fixed hot-pixel map of the frame's kind (step 1 makes one for the long and one for the short frames)."""
    n = kind_of_stamp(os.path.basename(path)[:15]) or 'long'
    if n not in _HOT: _HOT[n] = np.load(W('hotmap_%s.npy' % n))
    return _HOT[n]


def load_clean(path, sigmas=None):
    """load_planes + the hot-pixel repair of step 1 (fixed map from work/hotmap.npy, transient spikes per frame), done
    on the fly: nothing is cached. Returns planes, the count of transient pixels replaced per plane, meta."""
    import cv2
    HOT = _hot(path)
    P, ceil, meta = load_planes(path)
    trans = []
    for p in range(4):
        med3 = cv2.medianBlur(P[p], 3)
        if sigmas is None:
            d = (P[p] - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
        else:
            s = sigmas[p]
        spike = ((P[p] - med3) > 8 * s + 0.5 * np.clip(med3, 0, None)) & ~HOT[p]
        trans.append(int(spike.sum()))
        bad = HOT[p] | spike
        P[p][bad] = med3[bad]
    meta['transient_replaced'] = trans
    return P, meta


def load_clean_plane(path, p, near=None):
    """One colour plane of a RAW, black subtracted, hot pixels repaired as in load_clean (fixed map + transient spikes).
    near=True also returns the plane's pixels within 7 percent of the ceiling (NEAR_CEILING, above black, before any
    repair): the long/short join's rule."""
    import cv2
    HOT = _hot(path)
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible; pat = r.raw_pattern; black = r.black_level_per_channel
        ox, oy = OFFS[p]
        P = raw16[oy::2, ox::2].astype(np.float32) - np.float32(black[pat[oy, ox]])
    nearc = (P >= np.float32(NEAR_CEILING * (CEILING_RAW - black[pat[oy, ox]]))) & ~HOT[p] if near else None   # a fixed hot pixel is not light
    import darks
    mpath = darks.master_for(*EXPECT[kind_of_stamp(os.path.basename(path)[:15]) or 'long'], DARKS_DIR)
    if mpath: P = P - np.load(mpath)[PLANE_NAMES[p]].astype(np.float32)
    med3 = cv2.medianBlur(P, 3)
    d = (P - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
    bad = HOT[p] | ((P - med3) > 8 * s + 0.5 * np.clip(med3, 0, None))
    P[bad] = med3[bad]
    return (P, nearc) if near else P


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
