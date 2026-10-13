"""Shared pieces for the NGC 1535 stack of 12/13 October 2026 ("Cleopatra's Eye", a planetary nebula in Eridanus: a
bright blue-green inner disc about 20 arcsec across with its central star, inside a fainter shell about 50 arcsec
across): Sony a6000 on the 8SE (2,08x mm, f/10), 4 s at ISO 1600, EQ6-R on a tripod with the polar axis 5 degrees off
the pole, tracking on a pointing model (so the field turns). Two runs of frames: the telescope's computer was restarted
at about 09:44 UTC and the hold re-centred the field afterwards. About 37 degrees up in the south: the air is a prism.
Adapted from hack/stacks/2026-10-12/m77 (tonight's conventions, nothing cached per frame) and from
hack/stacks/2026-10-08/m57 and ngc1514 (a small planetary nebula at the stack's own scale).

RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset
(ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). The stack is made on the reference frame's grid of 2 x 2 colour cells:
output pixel (X, Y) is the centre of the reference frame's cell, sensor (2X + 0.5, 2Y + 0.5). One picture pixel per
colour cell (0.776 arcsec), nothing enlarged.

The RAWs are read in place and never written; nothing is cached per frame (the disk is tight). Every knob is an
environment variable; with none set the scripts reproduce the delivered run."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('N1535_NIGHT', '~/.observatory/nights/2026-10-12-a6000'))
STILLS = NIGHT                                                # read only: tonight the frames sit in the night's folder itself
OUT = os.environ.get('N1535_OUT', os.path.join(NIGHT, 'ngc1535'))
WORK = os.environ.get('N1535_WORK', os.path.join(OUT, 'work'))
FINAL = os.environ.get('N1535_FINAL', os.path.join(NIGHT, 'final'))
SCR = os.path.dirname(os.path.abspath(__file__))
DATE = '20261013'
T0, T1 = '093530', '095300'                                  # characters 10-15 of the file name, inclusive
POINTING_RADIUS_DEG = 0.5                                    # a frame belongs to the run if the sidecar's pointing is this close
TARGET = dict(name='NGC 1535', ra_deg=63.56567, dec_deg=-12.73944)   # central star, J2000 (04h 14m 15.76s, -12d 44' 22.0")
INNER_DIAMETER_ARCSEC, OUTER_DIAMETER_ARCSEC = 20.0, 50.0    # catalogue sizes of the bright disc and the faint shell
EXPOSURE_S, ISO = 4.0, 1600
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, Wd = 4024, 6024                                           # sensor (raw_image_visible)
h2, w2 = H // 2, Wd // 2                                     # one colour plane = the output grid
CENTRE = np.array([3011.5, 2011.5])                          # sensor centre, sensor px
SCALE = 0.388                                                # arcsec per sensor px (2,084 mm, 3.92 um); the stack's own solve refines it
CEILING_RAW = 16000                                          # raw values at or above this are at the sensor's ceiling (black 512)
WORKERS = int(os.environ.get('N1535_WORKERS', '4'))          # other stacks share the Mac tonight
FLAT_DIR = os.environ.get('N1535_FLAT_DIR', os.path.join(NIGHT, 'flat'))   # the night's flat (made by the NGC 891 stack): read only


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
    """Frames in the time window, with the sidecar's facts (pointing, time since the last slew, how far each axis of
    the mount turned between shutter open and close)."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (t0 <= stamp <= t1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}; ms = j.get('measured') or {}; mt = j.get('mount') or {}
        sep = None
        if pt.get('ra_deg') is not None:
            sep = float(np.hypot((pt['ra_deg'] - TARGET['ra_deg']) * np.cos(np.radians(TARGET['dec_deg'])), pt['dec_deg'] - TARGET['dec_deg']))
        try:
            turn = [float((mt['end'][a]['deg'] - mt['start'][a]['deg']) * 3600) for a in ('ra', 'dec')]
        except (KeyError, TypeError):
            turn = None
        out.append(dict(path=f, name=b, stamp=b[:15], seq=j.get('seq'), sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), pointing_from_target_deg=sep, ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        since_slew_s=(j.get('settle') or {}).get('since_slew_s'), box_star_size_arcsec=(ms.get('star_size') or {}).get('arcsec'),
                        mount_axes_turned_arcsec=turn,
                        arw_sha256={x['format']: x['sha256'] for x in j.get('files', [])}.get('arw')))
    return out


def load_raw16(path):
    """The four colour planes as the camera wrote them (uint16, black not subtracted), and facts from the RAW."""
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible.copy()
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        meta = dict(black=black.tolist(), white=float(r.white_level), wb=[float(v) for v in r.camera_whitebalance],
                    wb_daylight=[float(v) for v in r.daylight_whitebalance], flip=int(r.sizes.flip), rawmax=float(raw16.max()),
                    rgb_xyz_matrix=np.array(r.rgb_xyz_matrix).tolist())
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]] and raw16.shape == (H, Wd), (desc, pat.tolist(), raw16.shape)
    assert all(b == 512 for b in black), black
    return np.stack([raw16[oy::2, ox::2] for ox, oy in OFFS]), meta


def load_planes(path):
    """Black-subtracted colour planes (4, 2012, 3012) float32, a boolean cube of pixels at the sensor's ceiling, facts."""
    P16, meta = load_raw16(path)
    return P16.astype(np.float32) - 512.0, P16 >= CEILING_RAW, meta


_HOT = None


def load_clean(path):
    """load_planes + the hot-pixel repair of step 1 (fixed map from work/hotmap.npy, transient spikes per frame), done
    on the fly: nothing is cached. Returns planes, meta (with the count of transient pixels replaced per plane)."""
    import cv2
    global _HOT
    if _HOT is None: _HOT = np.load(W('hotmap.npy'))
    P, ceil, meta = load_planes(path)
    trans = []
    for p in range(4):
        med3 = cv2.medianBlur(P[p], 3)
        d = (P[p] - med3)[::3, ::3]; s = float(1.4826 * np.median(np.abs(d - np.median(d))))
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
        ox, oy = OFFS[p]
        P = r.raw_image_visible[oy::2, ox::2].astype(np.float32) - 512.0
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


def rigid(A, B, w):
    """Weighted least-squares rotation R and shift t with B ~ R A + t."""
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    Hm = ((A - ca) * w[:, None]).T @ (B - cb)
    U, S_, Vt = np.linalg.svd(Hm); d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, d]) @ U.T
    return R, cb - R @ ca


def jdump(obj, name):
    json.dump(obj, open(W(name), 'w'), indent=1)


def jload(name):
    return json.load(open(W(name)))
