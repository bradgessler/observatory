"""A master flat from twilight flats: frames of blank sky at dusk or dawn, the telescope parked or not tracking.

What it does, per colour plane of the RAW (R, G1, G2, B; black subtracted; no demosaic):
  1. picks the frames: the night's index.jsonl rows at the given ISO taken after the given UTC time, then by the RAW
     itself (its own EXIF ISO; the clipped mean green level in the middle of the sensor inside LEVEL, so neither the
     dark early frames nor anything near the sensor's ceiling is used). Every frame left out is listed with why.
  2. masks the stars of each frame (rawplanes.star_mask on the green: compact light above the smooth level, grown; the
     same mask for all four planes) and divides each plane by its own clipped mean level in the middle of the sensor
     (the central 256 x 256 plane px): each frame is normalised.
  3. the per-pixel MEDIAN over the frames of what is left: the stars, which move between frames (tracking off), drop
     out; the sky's own gradient, which changes as the Sun rises, is averaged down.
  4. single pixels far from their 5 x 5 neighbourhood in the master (hot or dead in the flat frames: more than 8 sigma
     AND more than 3%) are replaced by that neighbourhood's median; the count is recorded.
  5. each plane is divided by its clipped mean in the central 128 x 128 plane px: 1 at the sensor centre.
Then it describes the master, without changing it:
  * large scale: 16 px clipped block means; the fall-off at the corners and the ends of each side (64 px boxes);
    two fits per plane, k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6), rho^2 = ((x - xc)^2 + e (y - yc)^2) / 3000^2:
    'centred' (xc, yc at the sensor centre, times a plane 1 + gx dx/3000 + gy dy/3000, as the night flats were fitted)
    and 'free centre' (xc, yc fitted, no plane), which says where the light is centred on the sensor.
  * small scale: the master over its own large scale (16 px block means, a 9 x 9 block median, bilinear back), green
    (mean of G1 and G2) at 2 x 2 plane px, Gaussian of 2 bins: the dust shadows (each connected place deeper than
    DUST_T over at least DUST_MIN_BINS bins): place, size, depth.
  * if --compare is given (another flat directory in the same format, e.g. the night's flat/): the ratio of the two
    on large and small scales, and the other flat's listed shadows found (or not) in this one.

Inputs:  --night <folder with index.jsonl and the RAWs> (read only), --out <folder>, --iso, --after HH:MM (UTC),
         --level LO HI (green DN above black at the sensor centre), --workers N, --compare <flat folder>.
Outputs in --out:
  flat_planes.npz       R, G1, G2, B float32 (2012 x 3012), the master as measured, 1 at the sensor centre.
  flat_planes.fits      the same as FITS: IMAGETYP 'MASTER FLAT', NCOMBINE, ISOSPEED, dates, each input's name and
                        SHA-256 (tools/master_fits.py); flat.json then also has schema observatory.master/1, inputs, fits.
                        Divide plane p by it (plane p's own pixels). Same layout as the night flats under <night>/flat/.
  smallscale_planes.npz R, G1, G2, B float32: the master over its own large scale (dust and pixel response only, 1 on
                        average). compose(large, small) multiplies it onto another flat's large scale (the 'hybrid').
  flat.json             the recipe: the frames used and left out (and why), their levels, every number above, the
                        dust list, the comparison. Keys made_from, formula and dust.shadows are what the pipelines'
                        step 7 already read from a night flat.
  README.txt            how it was made and the numbers, in words.
  v_twilight_flat.png   top: green master (0.55 black to 1.05 white); bottom: green small scale (0.94 to 1.02).
Recipe entries written (flat.json): made_from{target, frames, exposure_s, iso, sky_level_dn_median, levels_per_frame,
  left_out}, method, formula, pixel_defects_replaced, planes{<p>: corners, ends, centred_fit, free_centre_fit},
  dust{shadows, count, area_fraction, deepest, threshold}, compare{...}, made_utc, tool, versions.

Library use from a pipeline:  F = twilight_flat.load(dir)  -> (4, 2012, 3012) float32;
                              F = twilight_flat.compose(large, twilight_flat.load(dir, 'smallscale_planes.npz'))."""
import argparse, datetime, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawplanes as rp

LEVEL = (800.0, 8000.0)
NORM_BOX = 128          # frames are normalised on 256 x 256 plane px (NORM_BOX each side of the centre)
CENTRE_BOX = 64         # the master is set to 1 on 128 x 128 plane px at the centre
DUST_T, DUST_MIN_BINS, DUST_SIGMA = 0.99, 12, 2.0
BK = 16
MIN_FRAMES = 3      # a pixel seen as sky in fewer frames than this is a hole (filled from the large scale, listed)


def load(d, name='flat_planes.npz'):
    Z = np.load(os.path.join(d, name))
    return np.stack([Z[k].astype(np.float32) for k in rp.PLANE_NAMES])


def compose(large, small):
    """A hybrid flat: another flat's large scale (4, h, w) times this flat's small scale (4, h, w)."""
    return (np.asarray(large, np.float32) * np.asarray(small, np.float32)).astype(np.float32)


def large_scale(A, bk=BK, k=9):
    """Smooth large-scale version of a 2-D flat: clipped block means, k x k block median, bilinear back to full size."""
    b = rp.block_means(A, bk)
    b = np.where(np.isfinite(b), b, np.nanmedian(b)).astype(np.float32)
    b = cv2.medianBlur(b, k) if k <= 5 else _median(b, k)
    h, w = A.shape
    out = np.empty((h, w), np.float32)
    ny, nx = b.shape
    out[:ny * bk, :nx * bk] = cv2.resize(b, (nx * bk, ny * bk), interpolation=cv2.INTER_LINEAR)
    out[ny * bk:, :] = out[ny * bk - 1:ny * bk, :]; out[:, nx * bk:] = out[:, nx * bk - 1:nx * bk]
    return out


def _median(b, k):
    from scipy.ndimage import median_filter
    return median_filter(b, size=k, mode='nearest').astype(np.float32)


def select(night, iso=100, after='13:10', level=LEVEL):
    rows = rp.index_rows(night); cands, left = [], []
    for j in rows:
        cam = j.get('camera') or {}; t = (j.get('time') or {}).get('shutter_pressed') or ''
        if cam.get('iso') != iso or t[11:16] < after: continue
        if not j['arw']:
            left.append(dict(file=[f['name'] for f in j.get('files', [])][:1], why='no RAW on this machine')); continue
        cands.append(dict(path=j['arw'], name=os.path.basename(j['arw']), t=t, sidecar_exposure_s=cam.get('exposure_s'), sidecar_iso=cam.get('iso'),
                          grey_copy_background=(j.get('measured') or {}).get('background'), tracking=((j.get('mount') or {}).get('start') or {}).get('tracking'),
                          pointing=j.get('pointing')))
    return cands, left


def _level(fr):
    e, iso = rp.raw_exif(fr['path'])
    P, meta = rp.read_planes(fr['path'])
    c = (slice(rp.H2 // 2 - NORM_BOX, rp.H2 // 2 + NORM_BOX), slice(rp.W2 // 2 - NORM_BOX, rp.W2 // 2 + NORM_BOX))
    lev = [rp.clipped_mean(P[p][c])[0] for p in range(4)]
    ceil = int((P.max(0) >= 0.95 * rp.CEILING).sum())
    return dict(exposure_s=e, iso=iso, level_dn=lev, ceiling_px=ceil, black_dn=meta['black_dn'])


def _normalised(path):
    P, meta = rp.read_planes(path)
    G = 0.5 * (P[1] + P[2])
    m = rp.star_mask(G)
    c = (slice(rp.H2 // 2 - NORM_BOX, rp.H2 // 2 + NORM_BOX), slice(rp.W2 // 2 - NORM_BOX, rp.W2 // 2 + NORM_BOX))
    out = np.empty_like(P); lev = []
    for p in range(4):
        L = rp.clipped_mean(P[p][c][~m[c]])[0]; lev.append(L)
        out[p] = np.where(m, np.nan, P[p] / np.float32(L))
    return out, lev, float(m.mean())


def _box(A, cx, cy, half=32):
    return rp.clipped_mean(A[max(cy - half, 0):cy + half, max(cx - half, 0):cx + half])[0]


def describe_plane(F, p):
    """Corners, ends of the sides (64 x 64 plane px boxes, 32 px in from the edge) and two fits of the large scale."""
    h, w = F.shape; i = 64
    pts = dict(corner_top_left=(i, i), corner_top_right=(w - i, i), corner_bottom_left=(i, h - i), corner_bottom_right=(w - i, h - i),
               long_side_left_end=(i, h // 2), long_side_right_end=(w - i, h // 2), short_side_top_end=(w // 2, i), short_side_bottom_end=(w // 2, h - i))
    vals = {k: round(float(_box(F, x, y)), 4) for k, (x, y) in pts.items()}
    b = rp.block_means(F, BK)
    ox, oy = rp.OFFS[p]; yy, xx = np.mgrid[0:b.shape[0], 0:b.shape[1]]
    X = 2 * (xx * BK + (BK - 1) / 2) + ox; Y = 2 * (yy * BK + (BK - 1) / 2) + oy
    ok = np.isfinite(b); x, y, v = X[ok], Y[ok], b[ok]

    def prof(q, x, y, xc, yc, e):
        rho2 = ((x - xc) ** 2 + e * (y - yc) ** 2) / 3000.0 ** 2
        return q[0] * (1 + q[1] * rho2 + q[2] * rho2 ** 2 + q[3] * rho2 ** 3)

    def fit(fun, q0):
        keep = np.ones(len(v), bool); q = np.array(q0, float)
        for _ in range(4):
            q = least_squares(lambda q_: fun(q_, x[keep], y[keep]) - v[keep], q).x
            r = v - fun(q, x, y); s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3.5 * s
        return q, float(np.sqrt(np.mean((v - fun(q, x, y))[keep] ** 2)))
    cen = lambda q, x, y: prof(q[:4], x, y, rp.CENTRE[0], rp.CENTRE[1], q[4]) * (1 + q[5] * (x - rp.CENTRE[0]) / 3000 + q[6] * (y - rp.CENTRE[1]) / 3000)
    fre = lambda q, x, y: prof(q[:4], x, y, q[5], q[6], q[4])
    qc, rc = fit(cen, [1, -0.3, 0, 0, 1.5, 0, 0])
    qf, rf = fit(fre, [1, -0.3, 0, 0, 1.5, rp.CENTRE[0], rp.CENTRE[1]])
    return dict(**vals, centred_fit=dict(k=qc[0], a2_a4_a6=qc[1:4].tolist(), e=qc[4], plane_gx_gy=[qc[5], qc[6]], rms=rc,
                                          what='k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) (1 + gx dx/3000 + gy dy/3000), rho centred on the sensor'),
                free_centre_fit=dict(k=qf[0], a2_a4_a6=qf[1:4].tolist(), e=qf[4], centre_sensor_px=[qf[5], qf[6]],
                                     centre_offset_from_sensor_centre_px=[qf[5] - rp.CENTRE[0], qf[6] - rp.CENTRE[1]], rms=rf,
                                     what='k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6), rho centred on (xc, yc), fitted'))


def small_scale_green(F):
    """Green small scale at 2 x 2 plane px bins, smoothed (Gaussian DUST_SIGMA bins), with the large scale divided out."""
    G = 0.5 * (F[1] / large_scale(F[1]) + F[2] / large_scale(F[2]))
    g2 = G[:rp.H2 // 2 * 2, :rp.W2 // 2 * 2].reshape(rp.H2 // 2, 2, rp.W2 // 2, 2).mean((1, 3)).astype(np.float32)
    return cv2.GaussianBlur(g2, (0, 0), DUST_SIGMA), G


def find_shadows(S, t=DUST_T, min_bins=DUST_MIN_BINS):
    n, lab, stats, cent = cv2.connectedComponentsWithStats((S < t).astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        a = int(stats[i, cv2.CC_STAT_AREA])
        if a < min_bins: continue
        m = lab == i
        out.append(dict(plane_px=[round(float(cent[i][0] * 2 + 0.5), 1), round(float(cent[i][1] * 2 + 0.5), 1)], bins=a,
                        radius_plane_px=round(float(2 * np.sqrt(a / np.pi)), 1), depth=round(float(1 - S[m].min()), 4)))
    return sorted(out, key=lambda d: -d['depth'])


def depth_at(S, x, y, r):
    """Depth of a shadow of radius r (plane px) at plane (x, y) in a 2 x 2-bin small-scale map S: 1 - min inside 0.7 r over the
    median of a ring outside it."""
    yy, xx = np.mgrid[0:S.shape[0], 0:S.shape[1]]
    d = np.hypot(xx * 2 + 0.5 - x, yy * 2 + 0.5 - y)
    inn = d <= max(0.7 * r, 4); ring = (d > r + 8) & (d < r + 30)
    if inn.sum() < 2 or ring.sum() < 8: return None
    return round(float(1 - np.min(S[inn]) / np.median(S[ring])), 4)


def build(night, out, iso=100, after='13:10', level=LEVEL, workers=4, compare=None):
    os.makedirs(out, exist_ok=True)
    cands, left = select(night, iso, after, level)
    with ProcessPoolExecutor(workers) as ex:
        levs = list(ex.map(_level, cands))
    use = []
    for fr, lv in zip(cands, levs):
        fr.update(lv); g = 0.5 * (lv['level_dn'][1] + lv['level_dn'][2])
        why = None
        if lv['iso'] != iso: why = 'ISO %d by the RAW (sidecar %s)' % (lv['iso'], fr['sidecar_iso'])
        elif g < level[0]: why = 'too dark: green %.0f DN at the centre, under %.0f (an offset of a few DN would bend the flat)' % (g, level[0])
        elif g > level[1]: why = 'too bright: green %.0f DN at the centre, over %.0f' % (g, level[1])
        elif lv['ceiling_px'] > 1000: why = '%d px at the sensor\'s ceiling' % lv['ceiling_px']
        if why: left.append(dict(file=fr['name'], why=why, level_dn=[round(v, 1) for v in lv['level_dn']]))
        else: use.append(fr)
    if len(use) < 3: raise SystemExit('only %d usable twilight frames' % len(use))
    print('%d frames used (of %d candidates):' % (len(use), len(cands)), ', '.join(f['name'][9:15] for f in use), flush=True)
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_normalised, [f['path'] for f in use]))
    masked = [r[2] for r in res]
    M = np.empty((4, rp.H2, rp.W2), np.float32); nused = None; defects = []; holes = []
    for p in range(4):
        cube = np.stack([r[0][p] for r in res])
        with np.errstate(all='ignore'):
            M[p] = np.nanmedian(cube, axis=0)
        nfr = np.isfinite(cube).sum(0)
        if p == 1: nused = nfr
        del cube
        bad = nfr < MIN_FRAMES                       # a star in (nearly) every frame: no sky seen there
        M[p][bad] = np.nan
        M[p][bad] = large_scale(M[p])[bad]           # filled with the large scale around it (block means ignore the hole)
        med5 = cv2.medianBlur(M[p], 5); E = M[p] - med5
        s = 1.4826 * np.median(np.abs(E[::3, ::3] - np.median(E[::3, ::3])))
        d = (np.abs(E) > 8 * s) & (np.abs(E) > 0.03 * med5) & ~bad
        M[p][d] = med5[d]; defects.append(int(d.sum())); holes.append(int(bad.sum()))
    del res
    c = (slice(rp.H2 // 2 - CENTRE_BOX, rp.H2 // 2 + CENTRE_BOX), slice(rp.W2 // 2 - CENTRE_BOX, rp.W2 // 2 + CENTRE_BOX))
    for p in range(4): M[p] /= np.float32(rp.clipped_mean(M[p][c])[0])
    print('pixel defects replaced per plane', defects, '; holes (sky in under %d frames) filled from the large scale' % MIN_FRAMES, holes, '; frames per pixel (green) min %d median %d' % (nused.min(), np.median(nused)), flush=True)
    planes = {rp.PLANE_NAMES[p]: describe_plane(M[p], p) for p in range(4)}
    for k, v in planes.items():
        print('%-2s corners TL %.3f TR %.3f BL %.3f BR %.3f | long side ends %.3f %.3f | short side ends %.3f %.3f | free centre at (%+.0f, %+.0f) px from the sensor centre, e %.2f, rms %.4f | centred: plane gx %+.4f gy %+.4f rms %.4f' % (
            k, v['corner_top_left'], v['corner_top_right'], v['corner_bottom_left'], v['corner_bottom_right'], v['long_side_left_end'], v['long_side_right_end'], v['short_side_top_end'], v['short_side_bottom_end'],
            *v['free_centre_fit']['centre_offset_from_sensor_centre_px'], v['free_centre_fit']['e'], v['free_centre_fit']['rms'], *v['centred_fit']['plane_gx_gy'], v['centred_fit']['rms']), flush=True)
    S2, Gs = small_scale_green(M)
    shadows = find_shadows(S2)
    small = np.stack([M[p] / large_scale(M[p]) for p in range(4)]).astype(np.float32)
    print('dust: %d shadows deeper than %.1f%% (over %d bins of 2 x 2 plane px), %.2f%% of the sensor; deepest %.1f%%' % (len(shadows), 100 * (1 - DUST_T), DUST_MIN_BINS, 100 * float((S2 < DUST_T).mean()), 100 * (shadows[0]['depth'] if shadows else 0)), flush=True)
    lv = np.array([f['level_dn'] for f in use])
    rec = dict(made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tool=os.path.abspath(__file__),
               versions=dict(numpy=np.__version__, opencv=cv2.__version__, rawpy=__import__('rawpy').__version__),
               made_from=dict(target='twilight sky', night=night, iso=iso, after_utc=after, level_window_green_dn=list(level),
                              frames=[f['name'] for f in use], times_utc=[f['t'] for f in use], exposure_s=sorted(set(f['exposure_s'] for f in use)),
                              tracking=sorted(set(str(f['tracking']) for f in use)), pointing=use[0]['pointing'],
                              levels_per_frame=[dict(file=f['name'], exposure_s=f['exposure_s'], level_dn=[round(v, 1) for v in f['level_dn']], grey_copy_background=f['grey_copy_background'], star_mask_fraction=round(m, 4)) for f, m in zip(use, masked)],
                              sky_level_dn_median=dict(zip(rp.PLANE_NAMES, np.median(lv, 0).round(1).tolist())), black_dn=use[0]['black_dn'], left_out=left),
               method=['planes black-subtracted (RAW black level), no demosaic', 'stars masked per frame (green, 4 sigma above the smooth level, grown 6 px; 40 sigma grown 24 px)',
                       'each plane / its clipped mean on the central %d x %d plane px' % (2 * NORM_BOX, 2 * NORM_BOX), 'per-pixel median over the frames',
                       'single-pixel defects (8 sigma and 3% from the 5 x 5 median) replaced', 'pixels seen as sky in fewer than %d frames filled from the large scale' % MIN_FRAMES, 'each plane / its clipped mean on the central %d x %d plane px: 1 at the sensor centre' % (2 * CENTRE_BOX, 2 * CENTRE_BOX)],
               formula='divide plane p (black subtracted, plane pixel (X, Y) = sensor (2X + ox, 2Y + oy), offsets R (0,0), G1 (1,0), G2 (0,1), B (1,1)) by flat_planes.npz[p]; a measured map, not a model',
               pixel_defects_replaced=dict(zip(rp.PLANE_NAMES, defects)), holes_filled_from_large_scale=dict(what='pixels seen as sky in fewer than %d frames (a star that hardly moved near the pole): filled with the large scale there, so they carry no dust' % MIN_FRAMES, px=dict(zip(rp.PLANE_NAMES, holes))), frames_per_pixel_green=dict(min=int(nused.min()), median=float(np.median(nused))),
               planes=planes,
               dust=dict(what='green small scale (master over its own large scale: 16 px clipped block means, 9 x 9 block median), 2 x 2 plane px bins, Gaussian %.0f bins; a shadow is a connected place below %.3f over at least %d bins' % (DUST_SIGMA, DUST_T, DUST_MIN_BINS),
                         threshold=DUST_T, count=len(shadows), area_fraction=float((S2 < DUST_T).mean()), deepest=shadows[0]['depth'] if shadows else 0.0,
                         deeper_than_2pct=sum(1 for s in shadows if s['depth'] > 0.02), deeper_than_5pct=sum(1 for s in shadows if s['depth'] > 0.05), shadows=shadows,
                         noise_of_the_map=float(1.4826 * np.median(np.abs(S2 - np.median(S2))))))
    if compare:
        rec['compare'] = compare_flats(M, S2, compare)
    np.savez_compressed(os.path.join(out, 'flat_planes.npz'), **{k: M[p] for p, k in enumerate(rp.PLANE_NAMES)})
    np.savez_compressed(os.path.join(out, 'smallscale_planes.npz'), **{k: small[p] for p, k in enumerate(rp.PLANE_NAMES)})
    import master_fits                                         # the same master as FITS (MASTER FLAT), the inputs' SHA-256 in it and in flat.json
    master_fits.write(os.path.join(out, 'flat_planes.fits'), M, 'flat', [master_fits.frame_record(f['path']) for f in use], rec, 'per-pixel median over the frames',
                      norm='1 at the sensor centre (central %d x %d plane px)' % (2 * CENTRE_BOX, 2 * CENTRE_BOX), hot_n=sum(defects), iso=iso, history=[rec['formula']] + rec['method'],
                      extra=[('OBS FLAT KIND', 'twilight', 'tracking %s' % ', '.join(rec['made_from']['tracking']))])
    json.dump(rec, open(os.path.join(out, 'flat.json'), 'w'), indent=1)
    g = 0.5 * (M[1] + M[2])
    top = np.clip((cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA) - 0.55) / 0.5, 0, 1)
    bot = np.clip((cv2.resize(S2, (top.shape[1], top.shape[0]), interpolation=cv2.INTER_AREA) - 0.94) / 0.08, 0, 1)
    cv2.imwrite(os.path.join(out, 'v_twilight_flat.png'), (np.vstack([top, np.ones((6, top.shape[1])), bot]) * 255).astype(np.uint8))
    write_readme(out, rec)
    return rec


def compare_flats(M, S2, other_dir):
    """This master M against another flat (same format) on large and small scales."""
    O = load(other_dir); oj = json.load(open(os.path.join(other_dir, 'flat.json'))) if os.path.exists(os.path.join(other_dir, 'flat.json')) else {}
    out = dict(other=other_dir, planes={})
    for p in range(4):
        R = rp.block_means(M[p], 32) / rp.block_means(O[p], 32)
        ny, nx = R.shape; yy, xx = np.mgrid[0:ny, 0:nx]
        X = (xx * 32 + 16) * 2 - rp.CENTRE[0]; Y = (yy * 32 + 16) * 2 - rp.CENTRE[1]; r = np.hypot(X, Y)
        cen = np.nanmedian(R[r < 300])
        R = R / cen
        rings = [dict(r_sensor_px=[a, b], this_over_other=round(float(np.nanmedian(R[(r >= a) & (r < b)])), 4)) for a, b in ((0, 300), (300, 600), (600, 1200), (1200, 1800), (1800, 2400), (2400, 3000), (3000, 3700))]
        halves = dict(left_half=round(float(np.nanmedian(R[X < -1500])), 4), right_half=round(float(np.nanmedian(R[X > 1500])), 4),
                      top=round(float(np.nanmedian(R[Y < -1000])), 4), bottom=round(float(np.nanmedian(R[Y > 1000])), 4))
        lo, hi = np.nanpercentile(R, [1, 99])
        out['planes'][rp.PLANE_NAMES[p]] = dict(ratio_rings=rings, ratio_sides=halves, ratio_range_1_99_pct=[float(lo), float(hi)], robust_rms=float(1.4826 * np.nanmedian(np.abs(R - np.nanmedian(R)))),
                                                what='this / other on 32 px clipped block means, set to 1 within 300 sensor px of the centre')
    # small scale: the other flat over its own large scale, the same way
    O2, _ = small_scale_green(O)
    ok = np.isfinite(O2) & np.isfinite(S2)
    a, b = S2[ok] - 1, O2[ok] - 1
    out['small_scale_correlation_green'] = float(np.corrcoef(a, b)[0, 1])
    shadows_other = find_shadows(O2)
    matched = []
    for s in shadows_other:
        x, y = s['plane_px']; d_here = depth_at(S2, x, y, s['radius_plane_px'])
        matched.append(dict(plane_px=s['plane_px'], radius_plane_px=s['radius_plane_px'], depth_in_other=s['depth'], depth_here=d_here))
    mine = find_shadows(S2)
    near = lambda s, L: any(np.hypot(s['plane_px'][0] - t['plane_px'][0], s['plane_px'][1] - t['plane_px'][1]) < 20 for t in L)
    out['dust'] = dict(other_count=len(shadows_other), this_count=len(mine), in_both_within_20px=sum(1 for s in mine if near(s, shadows_other)),
                       only_here=sum(1 for s in mine if not near(s, shadows_other)), only_in_other=sum(1 for s in shadows_other if not near(s, mine)),
                       depth_here_over_depth_in_other_median=float(np.median([m['depth_here'] / m['depth_in_other'] for m in matched if m['depth_here'] and m['depth_in_other'] > 0.03] or [np.nan])),
                       other_shadows=matched[:80])
    if oj.get('dust', {}).get('shadows'):
        out['dust']['other_fitted_shadows'] = [dict(plane_px=s['plane_px'], radius_plane_px=s['radius_plane_px'], depth_in_other=s['depth'], depth_here=depth_at(S2, s['plane_px'][0], s['plane_px'][1], s['radius_plane_px'])) for s in oj['dust']['shadows']]
    return out


def write_readme(out, rec):
    mf = rec['made_from']; L = []
    L.append('A master flat from twilight flats (made by .claude/skills/stack-pictures/tools/twilight_flat.py, %s)' % rec['made_utc'])
    L.append('')
    L.append('Use:   import numpy as np; F = np.load("flat_planes.npz")   # keys R, G1, G2, B, each (2012, 3012) float32')
    L.append('       plane = raw_image_visible[oy::2, ox::2] - black;  plane / F[name];  offsets (ox, oy): R (0,0), G1 (1,0), G2 (0,1), B (1,1)')
    L.append('       smallscale_planes.npz: the same over its own large scale (dust and pixel response only), for a hybrid with another flat\'s large scale.')
    L.append('')
    L.append('Frames: %d at ISO %d, %s to %s UTC, %s s, tracking %s; green %.0f to %.0f DN above black at the centre.' % (
        len(mf['frames']), mf['iso'], mf['times_utc'][0][11:19], mf['times_utc'][-1][11:19], '/'.join('%g' % e for e in mf['exposure_s']), '/'.join(mf['tracking']),
        min(0.5 * (f['level_dn'][1] + f['level_dn'][2]) for f in mf['levels_per_frame']), max(0.5 * (f['level_dn'][1] + f['level_dn'][2]) for f in mf['levels_per_frame'])))
    L.append('Left out: %d (%s).' % (len(mf['left_out']), '; '.join(sorted(set(l['why'].split(':')[0] for l in mf['left_out'])))))
    L.append('Method: ' + '; '.join(rec['method']) + '.')
    L.append('')
    L.append('Fall-off (64 px boxes; 1 at the sensor centre):')
    for k, v in rec['planes'].items():
        L.append('  %-2s corners TL %.3f TR %.3f BL %.3f BR %.3f   long side ends L %.3f R %.3f   short side ends T %.3f B %.3f   light centred at (%+.0f, %+.0f) sensor px from the sensor centre' % (
            k, v['corner_top_left'], v['corner_top_right'], v['corner_bottom_left'], v['corner_bottom_right'], v['long_side_left_end'], v['long_side_right_end'], v['short_side_top_end'], v['short_side_bottom_end'],
            *v['free_centre_fit']['centre_offset_from_sensor_centre_px']))
    d = rec['dust']
    L.append('Dust: %d shadows deeper than %.0f%% (%d deeper than 2%%, %d deeper than 5%%), %.2f%% of the sensor, the deepest %.1f%%; map noise %.4f.' % (
        d['count'], 100 * (1 - d['threshold']), d['deeper_than_2pct'], d['deeper_than_5pct'], 100 * d['area_fraction'], 100 * d['deepest'], d['noise_of_the_map']))
    if 'compare' in rec:
        c = rec['compare']
        L.append('')
        L.append('Against %s (this / that, 1 within 300 px of the centre):' % c['other'])
        for k, v in c['planes'].items():
            L.append('  %-2s rings %s   sides L %.3f R %.3f T %.3f B %.3f' % (k, ' '.join('%.3f' % r['this_over_other'] for r in v['ratio_rings']), v['ratio_sides']['left_half'], v['ratio_sides']['right_half'], v['ratio_sides']['top'], v['ratio_sides']['bottom']))
        L.append('  dust: %d shadows here, %d there, %d in both (within 20 px); small-scale correlation %.2f; depth here / there (shadows over 3%%) %.2f' % (
            c['dust']['this_count'], c['dust']['other_count'], c['dust']['in_both_within_20px'], c['small_scale_correlation_green'], c['dust']['depth_here_over_depth_in_other_median']))
    open(os.path.join(out, 'README.txt'), 'w').write('\n'.join(L) + '\n')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--night', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--iso', type=int, default=100); ap.add_argument('--after', default='13:10')
    ap.add_argument('--level', type=float, nargs=2, default=LEVEL); ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--compare')
    a = ap.parse_args()
    build(os.path.expanduser(a.night), os.path.expanduser(a.out), a.iso, a.after, tuple(a.level), a.workers, a.compare and os.path.expanduser(a.compare))
