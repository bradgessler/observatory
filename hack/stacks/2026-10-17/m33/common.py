"""MESSIER 33, THE TRIANGULUM GALAXY, night of 17/18 October 2026 (frames of 18 October UTC) with the frames of
13 October (the night of 12/13 October, hack/stacks/2026-10-12/m33). A copy of hack/stacks/2026-10-17/m27 (the calibrated
pipeline: the 13 October hybrid flat, dust measured on the run's own sky, Gaia star colours, darks.subtract that changes
nothing without darks and says so) adapted for an object bigger than the frame and for frames from four turns:

  1a   18 Oct, about 04:24 to 05:00 UTC: held still (not dithered); the field drifts about 2.5 arcmin
  1b   18 Oct, about 05:00 to 05:22 UTC: dithered, a sunflower spiral up to 1.5 arcmin (sidecar `dither`)
  2    18 Oct, about 07:25 to 08:55 UTC, after Saturn: dithered every 3 frames, small probe steps then up to 4 arcmin
       (a sensor-map bug chose 4: it widens the combined field)
  13oct  13 Oct, 07:20 to 08:34 UTC, the frames of the 13 October M33 pipeline (its window), read from that night's folder

What is different from M27:
  * M33 is about 70 x 40 arcmin and the frame 39 x 26: there is no open sky in any frame. Sky handling is ONE constant
    per colour per frame, measured where the stack is faintest; no surface is fitted over the galaxy.
  * registration across dither offsets up to 8 arcmin and a field that turned 10 degrees between the turns (the polar
    axis was about 10 degrees off): every frame's first guess comes from its own plate solve (sidecar .solve.json; the
    sidecar pointing is the star-alignment model's, about 1 degree off), then the stars decide.
  * the stack is made on a canvas larger than the reference frame (CANVAS_PAD plane px each side, cut to where frames
    are) so the dithers widen the field.
  * dust: the frames' own sky against the stack itself (step 7), per night: each frame's green over the first stack put
    back on that frame's sensor grid (gain and offset fitted per frame, so the galaxy cancels), the median over frames
    on the sensor's grid. Dust that sits still on the sensor stays; the sky, which moved under the dithers, goes.

Plane geometry as in the template: RAW colour planes, no demosaic, R, G1, G2, B; plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). One picture pixel per colour cell (0.776 arcsec). Every image
is read from the RAW's own grid (rawpy raw_image_visible), never the JPEG's EXIF orientation.

The RAWs are read in place and never written; nothing is cached per frame. Every knob is an environment variable
(M33_*); with none set the scripts reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M33_NIGHT', '~/.observatory/nights/2026-10-17-a6000'))   # work space only (not git)
STILLS = os.path.expanduser(os.environ.get('M33_STILLS', '~/.observatory/stills/2026-10-18'))   # read only: tonight's RAWs (UTC date folder)
STILLS13 = os.path.expanduser(os.environ.get('M33_STILLS13', '~/.observatory/nights/2026-10-12-a6000'))   # read only: the 13 October RAWs
SCR_ = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('M33_OUT', os.path.join(NIGHT, 'm33'))
FINAL = os.environ.get('M33_FINAL', os.path.join(SCR_, 'final'))
NAME = os.environ.get('M33_NAME', 'm33')
TOOLS = os.path.abspath(os.path.join(SCR_, '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
import sys as _sys
if TOOLS not in _sys.path: _sys.path.insert(0, TOOLS)
DARKS_DIR = os.environ.get('M33_DARKS_DIR', os.path.join(NIGHT, 'darks'))
WORK = os.environ.get('M33_WORK', os.path.join(OUT, 'work'))
SCR = SCR_
USE_13OCT = os.environ.get('M33_USE_13OCT', '1') == '1'
# the turns: (name, folder, date, first, last) by characters 10-15 of the file name, inclusive
TURNS = [('1a', STILLS, '20261018', '042400', '045959'), ('1b', STILLS, '20261018', '050000', '052100'), ('2', STILLS, '20261018', '072500', '085600')]
if USE_13OCT: TURNS.append(('13oct', STILLS13, '20261013', '072000', '083400'))
NIGHT_OF = {'1a': '18oct', '1b': '18oct', '2': '18oct', '13oct': '13oct'}
POINTING_RADIUS_DEG = 0.5                                    # a frame belongs to the run if its plate solve is this close to M33
TARGET = dict(name='M33', ra_deg=23.462042, dec_deg=30.660222)   # NGC 598 nucleus, J2000 (01h 33m 50.9s, +30d 39' 37")
GALAXY_PA_DEG = 23.0                                        # the disc's long axis, north through east (RC3)
GALAXY_SIZE_ARCMIN = (70.8, 41.7)                            # the disc, catalogue (RC3 D25)
EXPOSURE_S, ISO = 15.0, 3200
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]
H, Wd = 4024, 6024
h2, w2 = H // 2, Wd // 2
CENTRE = np.array([3011.5, 2011.5])
SCALE = 0.388
CEILING_RAW = 16000
WORKERS = int(os.environ.get('M33_WORKERS', '6'))
REF_STAMP = os.environ.get('M33_REF', '20261018-082053')      # a frame of turn 2 near the middle of all the frames' places
CANVAS_PAD = int(os.environ.get('M33_CANVAS_PAD', '760'))     # plane px each side of the reference grid before the cut to where frames are
FLAT_SOURCE = os.environ.get('M33_FLAT_SOURCE', 'hybrid13')
FLAT_DIRS = dict(hybrid13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-hybrid-m77'),
                 twilight13=os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/flat-twilight'))
FLAT_DIR = os.environ.get('M33_FLAT_DIR', FLAT_DIRS[FLAT_SOURCE])   # read only
COLOUR_CAL = os.environ.get('M33_COLOUR_CAL', '1') == '1'


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
            out.append(dict(path=f, name=b, stamp=b[:15], turn=turn, night=NIGHT_OF[turn], seq=j.get('seq'), sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
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
    planes, meta['dark'] = darks.subtract(planes, EXPOSURE_S, ISO, DARKS_DIR)      # no master dark: unchanged, and says so
    return planes, ceil, meta


_HOT = {}


def _hot(path):
    """The fixed hot-pixel map of the night the frame is from (step 1 makes one per night)."""
    n = '13oct' if os.path.basename(path).startswith('20261013') else '18oct'
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


def load_clean_plane(path, p):
    """One colour plane of a RAW, black subtracted, hot pixels repaired as in load_clean (fixed map + transient spikes)."""
    import cv2
    HOT = _hot(path)
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible; pat = r.raw_pattern; black = r.black_level_per_channel
        ox, oy = OFFS[p]
        P = raw16[oy::2, ox::2].astype(np.float32) - np.float32(black[pat[oy, ox]])
    import darks
    mpath = darks.master_for(EXPOSURE_S, ISO, DARKS_DIR)
    if mpath: P = P - np.load(mpath)[PLANE_NAMES[p]].astype(np.float32)
    med3 = cv2.medianBlur(P, 3)
    d = (P - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
    bad = HOT[p] | ((P - med3) > 8 * s + 0.5 * np.clip(med3, 0, None))
    P[bad] = med3[bad]
    return P


def path_of(stamp):
    return glob.glob(os.path.join(STILLS13 if stamp.startswith('20261013') else STILLS, stamp + '-*.ARW'))[0]


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
