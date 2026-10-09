"""Shared pieces for the M76 stack (night of 8 October 2026). Adapted from ../../2026-10-03/ngc7662/common.py.
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). The stack is made on the reference frame's colour-cell
grid: output pixel (X, Y) is the centre of the reference frame's 2 x 2 cell, sensor (2X + 0.5, 2Y + 0.5)."""
import glob, json, os
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-08-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.path.join(NIGHT, 'm76')
WORK = os.environ.get('M76_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
T0, T1 = '054550', '060100'          # the run, UTC time stamps in the file names (inclusive)
DAY = '20261009'
REF_STAMP = os.environ.get('M76_REF', '20261009-055305')   # chosen from step 3's log: the middle frame of the run, among the sharpest (HFD 5.6 plane px)
TARGET = dict(name='M76 (NGC 650/651), the Little Dumbbell Nebula', ra_deg=25.5821, dec_deg=51.5753, size_arcmin=[2.7, 1.8])
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]   # (ox, oy) of R, G1, G2, B in the RGGB cell
H, Wd = 4024, 6024                     # sensor (raw_image_visible)
PH, PW = H // 2, Wd // 2               # one colour plane
SCALE_SENSOR = 0.3858                  # arcsec per sensor px; replaced by the plate solution in the recipe (step 6)
os.makedirs(WORK, exist_ok=True)


def W(name):
    return os.path.join(WORK, name)


def frame_list():
    """Frames in the time window, with the sidecar's camera, mount and flags."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DAY + '-*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), settling=j.get('settling'), cloud=j.get('cloud'),
                        since_slew_s=(j.get('settle') or {}).get('since_slew_s'), transparency_box=j.get('transparency'),
                        pointing_ra_dec=[(j.get('pointing') or {}).get('ra_deg'), (j.get('pointing') or {}).get('dec_deg')],
                        alt_deg=(j.get('pointing') or {}).get('alt_deg'),
                        box_star_size_arcsec=((j.get('measured') or {}).get('star_size') or {}).get('arcsec'),
                        sha256={x['format']: x['sha256'] for x in j.get('files', [])}))
    return out


def raw_meta(path):
    """Exposure and ISO from the RAW itself (the sidecar can be wrong when settings changed): rawpy has no EXIF
    reader, so read the two EXIF tags from the TIFF structure of the ARW directly."""
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
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = [float(v) for v in r.camera_whitebalance]
        flip = int(r.sizes.flip)
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]], (desc, pat.tolist())
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in OFFS])
    rawmax = float(raw.max())
    return planes, dict(black=black.tolist(), white=white, wb=wb, flip=flip, rawmax=rawmax)


def clipped_stats(v, k=3.0, iters=6):
    v = np.asarray(v, np.float64); v = v[np.isfinite(v)]
    lo, hi = -np.inf, np.inf
    m = s = 0.0; w = v
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w))


def mask_circle(shape, cx, cy, r):
    h, w = shape
    yy, xx = np.ogrid[0:h, 0:w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
