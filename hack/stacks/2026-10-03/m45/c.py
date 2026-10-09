"""Shared pieces for the M45 nine-panel mosaic. Adapted from the night's M31 pipeline (m31/scripts/common.py and
the M31 mosaic's mcommon.py, m3_stars.py): same conventions.
RAW colour planes, no demosaic. Plane order everywhere: R, G1, G2, B. Plane pixel (X, Y) of a plane with cell
offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). A panel's stack lives on the HALF grid of its reference
frame: half-grid pixel (X, Y) is centred on sensor pixel (2X + 0.5, 2Y + 0.5) (0.7754 arcsec per pixel)."""
import glob, json, os, datetime
import numpy as np, rawpy, cv2

NIGHT = os.path.expanduser('~/.observatory/nights/2026-10-03-a6000')
STILLS = os.path.join(NIGHT, 'stills')
OUT = os.environ.get('M45_OUT', os.path.join(NIGHT, 'm45'))          # M45_OUT: another destination for the deliverables (a dry run)
SCR = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get('M45_WORK', os.path.join(os.path.dirname(SCR), 'work'))
# M45_MASTER_FLAT (the rerun of 2026-10-04): a master flat from real flat frames, .npy float32 (4, 2012, 3012), planes R, G1, G2, B,
# each 1 at the sensor centre. Step 2c then checks it against this hour and writes the flat that step 6 divides by. Without it
# everything runs as in the first run (the M31 core run's cloud-glow flat and dust map).
MASTER_FLAT = os.environ.get('M45_MASTER_FLAT')
PAD = os.path.dirname(os.path.dirname(SCR))
# Calibration of the night's M31 core run (flat as arrays, dust map, hot map): read only. The kept copy lies beside
# the M31 mosaic; the core run's own scratch is the fallback.
_KEPT = os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-from-core-run')
CORE_WORK = _KEPT if os.path.exists(os.path.join(_KEPT, 'flat2d.npy')) else os.path.join(PAD, 'm31', 'work')
HAIR_BOX = (3560, 0, 4200, 560)             # sensor px x0, y0, x1, y1: where the hair was during the night; the dust map is not trusted there
os.makedirs(WORK, exist_ok=True)
T0, T1 = '102500', '111400'                  # UTC window of the mosaic run (HHMMSS)
EXPOSURE_S, ISO = 10.0, 1600
PLANE_NAMES = ['R', 'G1', 'G2', 'B']
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) for R, G1, G2, B
SCALE = 0.3877                               # arcsec per sensor pixel (given, plate solve at 1025; re-measured per panel)
HS = 2 * SCALE
BLACK = 512.0
CEILING_RAW = 16000                          # raw value at or above which a pixel is at the sensor's ceiling
SAT_PLANE = CEILING_RAW - 512 - 1500         # a star whose brightest plane pixel is above this is treated as saturated
H, Wd = 4024, 6024
H2, W2 = H // 2, Wd // 2
CENTRE = np.array([3011.5, 2011.5])          # sensor centre, sensor px
CORNER = (slice(20, 320), slice(20, 320))    # plane px: the top-left 600 x 600 sensor px
RA0, DEC0 = 56.75, 24.20                     # mosaic centre, J2000 (given)
# the plan: name, offset of the aim point in arcmin (east, north) of the mosaic centre, in the order taken
PLAN = [('c', 0.0, 0.0), ('p00a', 18.91, 32.14), ('p10', -9.00, 18.61), ('p20', -36.91, 5.08), ('p21', -27.91, -13.53), ('p11', 0.0, 0.0),
        ('p01', 27.91, 13.53), ('p02', 36.91, -5.08), ('p12', 9.00, -18.61), ('p22', -18.91, -32.14), ('p00', 18.91, 32.14)]
PANELS = [p[0] for p in PLAN]
CLOUD = ('p20', 'p02')        # the two stacks taken through passing cloud (transparency 0.83 and 0.69 of the clearest stack, 3 frames each)
NAMED = dict(Alcyone=(56.871, 24.105), Atlas=(57.291, 24.053), Pleione=(57.297, 24.137), Electra=(56.219, 24.113), Maia=(56.457, 24.368),
             Merope=(56.582, 23.948), Taygeta=(56.302, 24.467), Celaeno=(56.201, 24.289), Asterope=(56.477, 24.554))


def W(name):
    return os.path.join(WORK, name)


def tsec(iso):
    return datetime.datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()


def frame_list():
    """Every still in the time window, with the sidecar's exposure, ISO, time and the mount's pointing."""
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-1[01]*.ARW'))):
        b = os.path.basename(f); stamp = b[9:15]
        if not (T0 <= stamp <= T1):
            continue
        j = json.load(open(f[:-4] + '.json'))
        cam = j.get('camera') or {}; pt = j.get('pointing') or {}
        sha = {x['format']: x['sha256'] for x in j.get('files', [])}
        out.append(dict(path=f, name=b, stamp=b[:15], exposure_s=cam.get('exposure_s'), iso=cam.get('iso'),
                        t=(j.get('time') or {}).get('shutter_pressed'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'),
                        ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), arw_sha256=sha.get('arw')))
    return out


def load_planes(path):
    """Black-subtracted colour planes, plus a boolean cube of pixels at the sensor's ceiling."""
    with rawpy.imread(path) as r:
        raw16 = r.raw_image_visible.copy()
        pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = [float(v) for v in r.camera_whitebalance]
        flip = int(r.sizes.flip)
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]], (desc, pat.tolist())
    assert raw16.shape == (H, Wd), raw16.shape
    raw = raw16.astype(np.float32)
    planes = np.stack([raw[oy::2, ox::2] - black[pat[oy, ox]] for ox, oy in OFFS])
    ceil = np.stack([raw16[oy::2, ox::2] >= CEILING_RAW for ox, oy in OFFS])
    return planes, ceil, dict(black=black.tolist(), white=white, wb=wb, flip=flip, rawmax=float(raw16.max()))


def clipped_stats(v, k=3.0, iters=6):
    v = v[np.isfinite(v)]
    if v.size == 0: return float('nan'), float('nan'), float('nan')
    lo, hi = -np.inf, np.inf
    m = s = 0.0; w = v
    for _ in range(iters):
        w = v[(v > lo) & (v < hi)]
        if w.size == 0: break
        m = float(w.mean()); s = float(w.std())
        lo, hi = m - k * s, m + k * s
    return m, s, float(np.median(w)) if w.size else m


def gnomonic(ra, dec, ra0=RA0, dec0=DEC0):
    """Tangent-plane coordinates (xi east, eta north), in arcsec, of (ra, dec) degrees about (ra0, dec0)."""
    ra, dec = np.radians(ra), np.radians(dec); a0, d0 = np.radians(ra0), np.radians(dec0)
    c = np.sin(d0) * np.sin(dec) + np.cos(d0) * np.cos(dec) * np.cos(ra - a0)
    xi = np.cos(dec) * np.sin(ra - a0) / c
    eta = (np.cos(d0) * np.sin(dec) - np.sin(d0) * np.cos(dec) * np.cos(ra - a0)) / c
    return np.degrees(xi) * 3600, np.degrees(eta) * 3600


def ungnomonic(xi, eta, ra0=RA0, dec0=DEC0):
    xi, eta = np.radians(np.asarray(xi) / 3600), np.radians(np.asarray(eta) / 3600); a0, d0 = np.radians(ra0), np.radians(dec0)
    den = np.cos(d0) - eta * np.sin(d0)
    ra = a0 + np.arctan2(xi, den)
    dec = np.arctan2((np.sin(d0) + eta * np.cos(d0)) * np.cos(ra - a0), den)
    return np.degrees(ra), np.degrees(dec)


# ---------------------------------------------------------------- stars (from the M31 mosaic's m3_stars.py)
AP = 14      # aperture radius, plane px (28 sensor px)
SW = 5.0     # Gaussian window sigma for centroids, plane px


def smooth_light(G):
    """The smooth light (sky, glare, nebulosity, cloud glow): shrunk 8x, 5x5 median, Gaussian sigma 2, grown back."""
    small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 2)
    return cv2.resize(small, (G.shape[1], G.shape[0]), interpolation=cv2.INTER_CUBIC)


def measure(G, x, y, sw=SW, ap=AP):
    """Windowed centroid (iterated), aperture flux, second moments in the aperture. G has the smooth light removed."""
    h, w = G.shape
    for _ in range(12):
        xi, yi = int(round(x)), int(round(y)); r = int(3 * sw) + 2
        if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
        t = G[yi - r:yi + r + 1, xi - r:xi + r + 1]
        yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
        wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sw * sw)) * np.clip(t, 0, None)
        s = wgt.sum()
        if s <= 0: return None
        nx = x + 2 * ((wgt * (xx - x)).sum() / s); ny = y + 2 * ((wgt * (yy - y)).sum() / s)
        d = np.hypot(nx - x, ny - y); x, y = nx, ny
        if d < 0.002: break
    xi, yi = int(round(x)), int(round(y)); r = 28
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
    t = G[yi - r:yi + r + 1, xi - r:xi + r + 1]
    if not np.isfinite(t).all(): return None
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
    rr = np.hypot(xx - x, yy - y)
    ann = t[(rr > 19) & (rr < 27)]
    lb = float(np.median(ann))
    a = rr <= ap; v = (t - lb) * a
    flux = float(v.sum())
    if flux <= 0: return None
    mx = (v * (xx - x)).sum() / flux; my = (v * (yy - y)).sum() / flux
    mxx = (v * (xx - x - mx) ** 2).sum() / flux; myy = (v * (yy - y - my) ** 2).sum() / flux; mxy = (v * (xx - x - mx) * (yy - y - my)).sum() / flux
    tr, det = mxx + myy, mxx * myy - mxy * mxy
    disc = max(tr * tr / 4 - det, 0) ** 0.5
    l1, l2 = tr / 2 + disc, tr / 2 - disc
    order = np.argsort(rr[a]); cum = np.cumsum((t - lb)[a][order]); hfr = float(rr[a][order][min(np.searchsorted(cum, flux / 2), a.sum() - 1)]) if cum[-1] > 0 else None
    return dict(x=float(x), y=float(y), flux=flux, peak=float(t[a].max() - lb), local_bg=lb,
                sig_major=float(max(l1, 0) ** 0.5), sig_minor=float(max(l2, 1e-9) ** 0.5), elong=float((max(l1, 1e-9) / max(l2, 1e-9)) ** 0.5),
                theta=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))), hfr=hfr)


def detect_image(G, P=None, nsig=6.0, ceil=None):
    """Stars of a green half-grid image G (holes already filled). P: the four planes (for the ceiling test)."""
    bg = smooth_light(G); D = G - bg
    bs = 64; h, w = G.shape; ny, nx = h // bs, w // bs
    Db = D[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1)
    Lb = bg[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).mean((1, 3)).ravel()
    fin = np.isfinite(Db).all(1) & np.isfinite(Lb)
    Db = Db[fin]; Lb = Lb[fin]
    med = np.median(Db, axis=1); sd = 1.4826 * np.median(np.abs(Db - med[:, None]), axis=1)
    A = np.stack([np.ones_like(Lb), Lb], 1); keep = np.ones(len(Lb), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], sd[keep] ** 2, rcond=None); r = sd ** 2 - A @ co; s = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * s
    var = np.maximum(co[0] + co[1] * np.maximum(bg, 0), max(0.05 * float(np.median(sd)) ** 2, 1e-6))
    sm = cv2.GaussianBlur(D, (0, 0), 2.5)
    z = sm / np.sqrt(var)
    m, s, _ = clipped_stats(z[::2, ::2])
    lab_n, lab, stats, cent = cv2.connectedComponentsWithStats((z > m + nsig * s).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, lab_n):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(D, float(cent[i][0]), float(cent[i][1]))
        if r is None: continue
        if np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        r['area'] = int(stats[i, cv2.CC_STAT_AREA])
        xi, yi = int(round(r['x'])), int(round(r['y']))
        if P is not None:
            cut = P[:, yi - AP:yi + AP + 1, xi - AP:xi + AP + 1]
            r['plane_max'] = [float(c.max()) for c in cut]
        r['level'] = float(bg[yi, xi])
        stars.append(r)
    stars.sort(key=lambda s_: -s_['flux']); keep_ = []
    for s_ in stars:
        if all(np.hypot(s_['x'] - k['x'], s_['y'] - k['y']) > 6 for k in keep_): keep_.append(s_)
    xy = np.array([[k['x'], k['y']] for k in keep_]).reshape(-1, 2)
    for i, k in enumerate(keep_):
        d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9; k['nearest'] = float(2 * d.min()) if len(keep_) > 1 else 1e6               # sensor px
        if P is not None: k['saturated'] = bool(max(k['plane_max']) >= SAT_PLANE)
    return keep_, dict(a=float(co[0]), b=float(co[1])), float(s)


def nat(s):
    """Half-grid star position -> sensor px."""
    return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])


def small_flat():
    """The sensor's small-scale flat (dust shadows) and the dust mask, on the half grid: the M31 core run's
    dustratio.npy and dustmask.npy, with the ratio set to 1 (nothing divided) in the box the hair moved in: the
    hair is found afresh in every panel and its circle is left out (steps 2b, 6)."""
    ratio = np.load(os.path.join(CORE_WORK, 'dustratio.npy')).astype(np.float32); mask = np.load(os.path.join(CORE_WORK, 'dustmask.npy'))
    x0, y0, x1, y1 = [v // 2 for v in HAIR_BOX]
    ratio[y0:y1, x0:x1] = 1.0
    return np.clip(ratio, 0.5, 1.05), mask


def stack_flats():
    """What step 6 divides every frame by, what it flags, and where it takes no data.
    Returns (flat (4, H2, W2), flagged (H2, W2) float32: sensor pixels whose data count a quarter and are kept out of the
    background fit, nodata (H2, W2) float32 or None: sensor pixels from which nothing is taken, like the hair's circle).
    First run: the M31 core run's smooth cloud-glow flat x its dust map; flagged = its dust mask.
    With M45_MASTER_FLAT: the files of step 2c: the master flat (and, inside the few patches where this hour's response
    differs from it, this hour's own); flagged = those patches; nodata = the hair's place in the flat (at dawn)."""
    if MASTER_FLAT:
        return np.load(W('flat_master_hour.npy')), np.load(W('leaveout_master.npy')).astype(np.float32), np.load(W('nodata_master.npy')).astype(np.float32)
    small, dm = small_flat()
    return np.load(os.path.join(CORE_WORK, 'flat2d.npy')) * small[None], dm.astype(np.float32), None


# ---------------------------------------------------------------- hot pixels
_HOT = None
NOISE_GAIN = 10.0     # DN^2 of shot noise per DN of level (0.1 e-/DN at ISO 1600; checked in step 2)


def repaired(path, corner_std):
    """Planes with fixed hot pixels (step 2's map) and single-frame spikes replaced by the 3x3 median of the same plane.
    corner_std: the frame's own noise per plane (step 1). Returns planes, ceiling cube (pixels at the sensor's ceiling
    that are NOT repaired hot pixels or spikes: saturated stars), meta, number of spikes."""
    global _HOT
    if _HOT is None: _HOT = np.load(W('hotmap.npy'))
    P4, ceil, meta = load_planes(path); trans = 0
    for p in range(4):
        P = P4[p]
        med3 = cv2.medianBlur(P, 3)
        s = np.sqrt(corner_std[p] ** 2 + NOISE_GAIN * np.clip(med3, 0, None))
        spike = (P - med3) > (8 * s + 0.5 * np.clip(med3, 0, None))
        spike &= ~_HOT[p]
        trans += int(spike.sum())
        bad = _HOT[p] | spike
        P[bad] = med3[bad]
        ceil[p] &= ~bad               # a hot pixel or a spike at the ceiling is not a saturated star
    return P4, ceil, meta, trans
