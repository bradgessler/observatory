"""Shared pieces for the M1 (Crab Nebula) stack of 8/9 October 2026. RAW colour planes, no demosaic.

Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset (ox, oy) sits at sensor pixel
(2X + ox, 2Y + oy). The stack is made on the reference frame's grid of 2 x 2 colour cells: output pixel (X, Y) is the
centre of the reference frame's cell, sensor (2X + 0.5, 2Y + 0.5). One picture pixel per colour cell, nothing enlarged.
Copied from this night's ngc1514/common.py (itself from m57 and 2026-10-03/ngc7662); target, window and hook names changed.

Hooks (environment variables; with none set the pipeline reproduces the delivered run):
  M1_WORK, M1_OUT         work and delivery folders
  M1_WORKERS              processes / threads (default 4: other targets are being stacked on this machine)
  M1_REF                  reference frame stamp (default: the on-target frame with the most stars, step 3)
  M1_DETECT_SIGMA         star detection threshold in step 2 (default 4.5: a bright sky and f/10 leave few stars)"""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M1_NIGHT', '~/.observatory/nights/2026-10-08-a6000'))
STILLS = os.path.join(NIGHT, 'stills')                       # read only
OUT = os.environ.get('M1_OUT', os.path.join(NIGHT, 'm1'))
WORK = os.environ.get('M1_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
T0, T1 = '075300', '081500'                                  # characters 10-15 of the file name, inclusive (as asked)
TARGET = dict(name='M1 (Crab Nebula)', ra_deg=83.6331, dec_deg=22.0145, size_arcmin=[6.0, 4.0], note='supernova remnant of the explosion seen in 1054; the J2000 position given is the Crab pulsar (about V 16.5), at the centre')
ON_TARGET_DEG = 0.5                                          # a frame whose sidecar pointing is further than this from M1 is another target
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, W = 4024, 6024                                            # sensor (raw_image_visible)
h2, w2 = H // 2, W // 2                                      # one colour plane, one cell grid
SAT_DN = 16372 - 512 - 40                                    # black-subtracted level treated as clipped (as m57)
SCALE_GUESS = 0.3858                                         # arcsec per sensor px (this night's solves); step 4 measures it
WORKERS = int(os.environ.get('M1_WORKERS', '4'))


def W_(name):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def ang_sep(ra1, dec1, ra2, dec2):
    a1, d1, a2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    return float(np.degrees(np.arccos(np.clip(np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(a1 - a2), -1, 1))))


def frame_list():
    """Every frame in the time window, with the sidecar's exposure, ISO, pointing, flags and the box's own solve."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '????????-??????-*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}
        sp = f[:-4] + '.solve.json'; box_solve = None
        if os.path.exists(sp):
            sj = json.load(open(sp)); so = sj.get('solution') or {}
            box_solve = dict(state=sj.get('state'), ra_deg=so.get('ra_deg'), dec_deg=so.get('dec_deg'), rotation_deg=so.get('rotation_deg'))
        ra, dec = pt.get('ra_deg'), pt.get('dec_deg')
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), settling=j.get('settling'), cloud_flag=j.get('cloud'),
                        box_transparency=j.get('transparency'), since_slew_s=(j.get('settle') or {}).get('since_slew_s'),
                        box_star_size_arcsec=((j.get('measured') or {}).get('star_size') or {}).get('arcsec'),
                        pointing_ra_dec=[ra, dec], box_solve=box_solve,
                        off_target_deg=ang_sep(ra, dec, TARGET['ra_deg'], TARGET['dec_deg']) if ra is not None else None,
                        arw_sha256={x['format']: x['sha256'] for x in j.get('files', [])}.get('arw')))
    return out


def raw_meta(path):
    """Exposure and ISO from the RAW itself (the sidecar can be wrong when settings changed). From m76/common.py."""
    import struct
    b = open(path, 'rb').read(1 << 20)
    e = '<' if b[:2] == b'II' else '>'
    def ifd(off):
        n = struct.unpack(e + 'H', b[off:off + 2])[0]; tags = {}
        for i in range(n):
            t, ty, cnt, val = struct.unpack(e + 'HHI4s', b[off + 2 + 12 * i: off + 14 + 12 * i]); tags[t] = (ty, cnt, val)
        return tags
    t0 = ifd(struct.unpack(e + 'I', b[4:8])[0])
    exif = ifd(struct.unpack(e + 'I', t0[0x8769][2])[0])
    ty, cnt, val = exif[0x829A]; o = struct.unpack(e + 'I', val)[0]; num, den = struct.unpack(e + 'II', b[o:o + 8])
    iso = struct.unpack(e + 'H', exif[0x8827][2][:2])[0]
    return dict(exposure_s=num / den, iso=int(iso))


def load_planes(path):
    """Four colour planes, black subtracted, float32 (4, 2012, 3012)."""
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        meta = dict(black=black.tolist(), white=float(r.white_level), wb_as_shot=[float(v) for v in r.camera_whitebalance],
                    wb_daylight=[float(v) for v in r.daylight_whitebalance], flip=int(r.sizes.flip), rawmax=float(raw.max()),
                    rgb_xyz_matrix=np.array(r.rgb_xyz_matrix).tolist())
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]] and raw.shape == (H, W), (desc, pat.tolist(), raw.shape)
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in OFFS])
    return planes, meta


def clipped_stats(v, k=3.0, iters=6):
    v = np.asarray(v, np.float64).ravel(); v = v[np.isfinite(v)]
    lo, hi = -np.inf, np.inf
    m = s = 0.0; w = v
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w))


def rigid(A, B, w):
    """Weighted least-squares rotation R and shift t with B ~ R A + t."""
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    Hm = ((A - ca) * w[:, None]).T @ (B - cb)
    U, S_, Vt = np.linalg.svd(Hm); d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, d]) @ U.T
    return R, cb - R @ ca


UC = np.array([3012.0, 2012.0]); US = 3000.0


def poly_apply(o, A):
    """Step 3's transform (reference sensor px -> this frame's sensor px), 2nd-order polynomial in u, v."""
    u = (np.asarray(A, float) - UC) / US
    X = np.column_stack([np.ones(len(u)), u[:, 0], u[:, 1], u[:, 0] ** 2, u[:, 0] * u[:, 1], u[:, 1] ** 2])
    return np.column_stack([X @ np.array(o['cx']), X @ np.array(o['cy'])])


def jload(name):
    return json.load(open(W_(name)))


def jsave(obj, name):
    json.dump(obj, open(W_(name), 'w'), indent=1)
