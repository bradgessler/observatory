"""Shared pieces for the M57 (Ring Nebula) stack of 8/9 October 2026. RAW colour planes, no demosaic.

Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell offset (ox, oy) sits at sensor pixel
(2X + ox, 2Y + oy). The stack is made on the reference frame's grid of 2 x 2 colour cells: output pixel (X, Y) is the
centre of the reference frame's cell, sensor (2X + 0.5, 2Y + 0.5). One picture pixel per colour cell, nothing enlarged.
Adapted from hack/stacks/2026-10-03/ngc7662/common.py."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('M57_NIGHT', '~/.observatory/nights/2026-10-08-a6000'))
STILLS = os.path.join(NIGHT, 'stills')                       # read only
OUT = os.environ.get('M57_OUT', os.path.join(NIGHT, 'm57'))
WORK = os.environ.get('M57_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
T0, T1 = '060250', '062200'                                  # characters 10-15 of the file name, inclusive
TARGET = dict(name='M57', ra_deg=283.3962, dec_deg=33.0292)
NEB_REF_GUESS = (2867.0, 1861.0)                             # sensor px of the nebula's centre in the reference frame, by eye (step 7 measures it)
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]                       # (ox, oy) of R, G1, G2, B in the 2 x 2 cell
H, W = 4024, 6024                                            # sensor (raw_image_visible)
h2, w2 = H // 2, W // 2                                      # one colour plane, one cell grid
SAT_DN = 16372 - 512 - 40                                    # black-subtracted level treated as clipped (sensor max 16372)
WORKERS = int(os.environ.get('M57_WORKERS', '4'))


def W_(name):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def frame_list():
    """Frames in the time window, with the sidecar's exposure, ISO and flags."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '????????-??????-*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), settling=j.get('settling'), cloud_flag=j.get('cloud'),
                        box_transparency=j.get('transparency'), since_slew_s=(j.get('settle') or {}).get('since_slew_s'),
                        arw_sha256={x['format']: x['sha256'] for x in j.get('files', [])}.get('arw')))
    return out


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


def jload(name):
    return json.load(open(W_(name)))


def jsave(obj, name):
    json.dump(obj, open(W_(name), 'w'), indent=1)
