"""Step 6: the flat field, measured from tonight's own sky. There are no flat frames, and M33 fills its frames, so their
sky cannot show the optics' fall-off without assuming the galaxy's shape. But the same camera on the same telescope
shot two small objects on open sky at the same exposure and ISO, one run before M33 and one after:
    M57      0602-0621 UTC (a small planetary nebula in a rich Milky Way field)
    NGC 1514 0738-0752 UTC (a small planetary nebula, open sky)
That sky, seen through the optics, is a sky flat. Two runs that bracket M33 in time are the check that nothing in the
light path (focus, dust) changed in between.

Per frame and colour plane: hot pixels (step 1's map) and everything brighter than the smooth sky (stars and the
nebula: green above the frame's smooth level by 2.5 sigma after a 1.5 px blur, grown by 6 plane px; above 40 sigma
grown by 24) are left out; the plane is divided by its own clipped sky level in the central 600 x 600 plane px;
8 x 8 plane-px block medians. Per run: the median of those over the frames, WITHOUT registration (the stars are
masked in each frame anyway).

1. Vignetting. Fit per run and colour (as hack/stacks/2026-10-03/m31/vig2_fit.py): block value at sensor (x, y),
   rho = r / 3000, r = distance from the sensor centre,
       F = k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) (1 + gx (x - xc) / 3000 + gy (y - yc) / 3000)
   The linear factor is that sky's own slope across the field (light pollution, altitude); it is fitted so that it
   does not bias the radial part and it is NOT applied to M33. Joint fit to both runs (each with its own k and slope).
   ONE profile is applied to all four colour planes: the mean of the G1 and G2 fits. The sky of these runs is faint
   (red 16 and 38 DN, blue 28 and 78 DN, green 49 and 122 DN), the red and blue fits disagree between the runs by up to
   18% and 4% at the corners, and a per-colour profile would paint a colour gradient into M33's outskirts; the two green
   fits agree within 3%. The per-colour fits are recorded.

2. Dust. What is left after the fit (flat / fitted model, green, the two green planes averaged) holds the dust
   shadows: donuts about 45 plane px across. The remainder is smoothed (normalised Gaussian, sigma 1 block, so masked
   blocks do not count) and divided by its own 31-block median (the small scale). A shadow is corrected only where
   BOTH runs, each on its own, put it deeper than DUST_MIN, the blob is at least 12 blocks and the two runs measure
   its depth alike (each at least 3%, within 2.5% of each other). Each such shadow is then modelled finely: a dust
   shadow at f/10 is round (the out-of-focus image of the aperture), here a flat-bottomed disc about 25 plane px in
   radius with a soft edge. From 2 x 2 bins of the normalised green of every frame of each run (median over frames,
   relative to a ring 60..76 plane px out, the two runs averaged) a round shadow is fitted by least squares:
   1 - depth / (1 + exp((r - radius) / edge)), centre free. The flat is multiplied by that model near each shadow;
   everywhere else the dust map is exactly 1 (no flat noise is put into the picture). The same (geometric) shadow map
   is used for all four planes. Checks: the depth refitted to each run alone, and to M33's own unregistered median.

Writes flat.npy (2012, 3012): divide every M33 plane by it (on that plane's own pixels). 1 at the sensor centre."""
import os, glob, json, warnings
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from scipy.optimize import least_squares
from scipy.ndimage import median_filter, minimum_filter
from common import *

warnings.filterwarnings('ignore', 'All-NaN slice'); warnings.filterwarnings('ignore', 'Mean of empty slice')
BS = 8
ny, nx = h2 // BS, w2 // BS
LARGE = 31                                                     # blocks
DUST_MIN = float(os.environ.get('M33_DUST_MIN', '0.975'))      # a shadow at least 2.5% deep in each run on its own
SHADOW_BLOCKS = 12
R_REF, R_OUT = 30, 38                                          # 2 x 2 bins: a shadow's profile reaches to R_REF (60 plane px), its reference ring is R_REF..R_OUT


def frames_of(run):
    a, b = FLAT_RUNS[run]; out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))):
        s = os.path.basename(f)[9:15]
        if not (a <= s <= b): continue
        if raw_exif(f) == (EXPOSURE_S, ISO): out.append(f)
    return out


def blocks_of(path):
    hot = np.load(W('hotmap.npy'))
    P, ceil, meta = load_planes(path)
    G = (P[1] + P[2]) / 2
    sm = smooth_level(G, 16, 5); D = cv2.GaussianBlur(G - sm, (0, 0), 1.5)
    s = 1.4826 * np.median(np.abs(D[::3, ::3] - np.median(D[::3, ::3])))
    m1 = cv2.dilate((D > 2.5 * s).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    m2 = cv2.dilate((D > 40 * s).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49)))
    mask = (m1 | m2).astype(bool)
    out = np.full((4, ny, nx), np.nan, np.float32); lev = []
    c = (slice(h2 // 2 - 300, h2 // 2 + 300), slice(w2 // 2 - 300, w2 // 2 + 300))
    for p in range(4):
        bad = mask | hot[p]
        v = P[p][c][~bad[c]]; L = clipped_stats(v)[0]; lev.append(L)
        Q = np.where(bad, np.nan, P[p] / L)[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
        good = np.isfinite(Q).sum(2)
        b = np.nanmedian(Q, axis=2); b[good < BS * BS // 4] = np.nan
        out[p] = b
    g = np.where(mask[None] | hot[1:3], np.nan, P[1:3] / np.array(lev[1:3], np.float32)[:, None, None])
    g2 = np.nanmean(g.reshape(2, h2 // 2, 2, w2 // 2, 2).transpose(1, 3, 0, 2, 4).reshape(h2 // 2, w2 // 2, 8), axis=2).astype(np.float32)
    return out, lev, float(mask.mean()), g2


def block_xy(p):
    ox, oy = OFFS[p]
    Y, X = np.mgrid[0:ny, 0:nx]
    return 2 * (X * BS + (BS - 1) / 2) + ox, 2 * (Y * BS + (BS - 1) / 2) + oy


def radial(c, rho): return 1 + c[0] * rho ** 2 + c[1] * rho ** 4 + c[2] * rho ** 6


def model(q, x, y, i):
    k, gx, gy = q[3 + 3 * i:6 + 3 * i]
    rho = np.hypot(x - CENTRE[0], y - CENTRE[1]) / 3000
    return k * radial(q[:3], rho) * (1 + gx * (x - CENTRE[0]) / 3000 + gy * (y - CENTRE[1]) / 3000)


def joint_fit(tabs):
    """tabs: list of (x, y, v) per run. Shared radial (a2, a4, a6); per run k, gx, gy. Robust (3 sigma, 4 rounds)."""
    q0 = np.array([-0.2, 0, 0] + sum([[float(np.median(t[2])), 0, 0] for t in tabs], []))
    keeps = [np.ones(len(t[2]), bool) for t in tabs]
    for _ in range(4):
        def resid(q): return np.concatenate([model(q, t[0][kk], t[1][kk], i) - t[2][kk] for i, (t, kk) in enumerate(zip(tabs, keeps))])
        q0 = least_squares(resid, q0).x
        for i, t in enumerate(tabs):
            r = t[2] - model(q0, t[0], t[1], i); s = 1.4826 * np.median(np.abs(r[keeps[i]] - np.median(r[keeps[i]]))); keeps[i] = np.abs(r) < 3 * s
    rms = [float(np.sqrt(np.mean((t[2] - model(q0, t[0], t[1], i))[keeps[i]] ** 2))) for i, t in enumerate(tabs)]
    return q0, rms, [int(k.sum()) for k in keeps]


def tab(v, p):
    x, y = block_xy(p); m = np.isfinite(v)
    return x[m], y[m], v[m]


def nsmooth(R, s=1.0):
    """Normalised Gaussian: missing blocks do not count."""
    m = np.isfinite(R).astype(np.float32); f = np.where(np.isfinite(R), R, 0).astype(np.float32)
    return cv2.GaussianBlur(f, (0, 0), s) / np.maximum(cv2.GaussianBlur(m, (0, 0), s), 1e-3)


def small_scale(S):
    return S / median_filter(S, size=LARGE, mode='nearest')


if __name__ == '__main__':
    runs = {}
    for run in FLAT_RUNS:
        fs = frames_of(run)
        with ProcessPoolExecutor(WORKERS) as ex:
            res = list(ex.map(blocks_of, fs))
        stack = np.stack([r[0] for r in res])
        runs[run] = dict(files=[os.path.basename(f) for f in fs], levels=[r[1] for r in res], masked_fraction=[r[2] for r in res], flat=np.nanmedian(stack, axis=0),
                         hires=np.nanmedian(np.stack([r[3] for r in res]), axis=0))
        print(run, len(fs), 'frames; sky level (central, DN) R G1 G2 B median', np.round(np.median([r[1] for r in res], axis=0), 1).tolist(), 'masked %.1f%%' % (100 * np.median([r[2] for r in res])), flush=True)
        del res, stack
    names = list(runs)
    np.savez(W('vig_skyflats.npz'), bs=BS, **{n: runs[n]['flat'] for n in names})
    rec = dict(block_px=BS, runs={n: dict(files=runs[n]['files'], sky_level_dn_median=np.median(runs[n]['levels'], axis=0).tolist(), masked_fraction_median=float(np.median(runs[n]['masked_fraction']))) for n in names}, planes={})
    rr = np.linspace(0, 3700, 38)
    fits = {}
    for p in range(4):
        q, rms, used = joint_fit([tab(runs[n]['flat'][p], p) for n in names])
        alone = [joint_fit([tab(runs[n]['flat'][p], p)])[0] for n in names]
        fits[p] = q
        pa = [radial(a[:3], rr / 3000) for a in alone]
        rec['planes'][PLANE_NAMES[p]] = dict(radial_a2_a4_a6=q[:3].tolist(), per_run={n: dict(k=float(q[3 + 3 * i]), gx=float(q[4 + 3 * i]), gy=float(q[5 + 3 * i]), fit_rms=rms[i], blocks_used=used[i]) for i, n in enumerate(names)},
                                             each_run_alone_a2_a4_a6={n: alone[i][:3].tolist() for i, n in enumerate(names)}, profile=radial(q[:3], rr / 3000).tolist(),
                                             profile_each_run={n: pa[i].tolist() for i, n in enumerate(names)}, corner_value=float(radial(q[:3], np.hypot(*CENTRE) / 3000)),
                                             runs_alone_differ_max=float(np.max(np.abs(pa[0] - pa[1]))))
        print(PLANE_NAMES[p], 'radial', np.round(q[:3], 4).tolist(), 'corner %.3f' % rec['planes'][PLANE_NAMES[p]]['corner_value'], 'runs alone differ by up to %.3f' % rec['planes'][PLANE_NAMES[p]]['runs_alone_differ_max'],
              '| sky slopes', {n: (round(float(q[4 + 3 * i]), 4), round(float(q[5 + 3 * i]), 4)) for i, n in enumerate(names)}, 'fit rms', np.round(rms, 4).tolist(), flush=True)
    # 1. the one profile: mean of the two green fits
    prof = lambda r: 0.5 * (radial(fits[1][:3], r / 3000) + radial(fits[2][:3], r / 3000))
    rec['profile_r_sensor_px'] = rr.tolist(); rec['profile_applied'] = prof(rr).tolist(); rec['profile_applied_corner'] = float(prof(np.hypot(*CENTRE)))
    # 2. dust, from the green remainder of each run
    smalls = {}
    for i, n in enumerate(names):
        R = []
        for p in (1, 2):
            x, y = block_xy(p); R.append(runs[n]['flat'][p] / model(fits[p], x, y, i))
        R = 0.5 * (R[0] + R[1])
        smalls[n] = small_scale(nsmooth(R, 1.0))
    a, b = smalls[names[0]], smalls[names[1]]
    inner = np.zeros((ny, nx), bool); inner[3:-3, 3:-3] = True
    cand = (a < DUST_MIN) & (b < DUST_MIN) & inner
    # a shadow is a donut about 45 plane px across (6 blocks): keep only blobs of at least SHADOW_BLOCKS blocks whose
    # depth both runs measure alike (each at least 3%, within 2.5% of each other); small or disagreeing blobs are noise
    lab_n, lab = cv2.connectedComponents(cand.astype(np.uint8))
    both = np.zeros_like(cand)
    for k in range(1, lab_n):
        sel = lab == k; yb, xb = np.argwhere(sel)[int(np.argmin((0.5 * (a + b))[sel]))]
        da, db = 1 - a[yb, xb], 1 - b[yb, xb]
        if sel.sum() >= SHADOW_BLOCKS and min(da, db) >= 0.03 and abs(da - db) <= 0.025: both |= sel
    mean = 0.5 * (a + b)
    # the check: M33's own frames, green, unregistered median, same blocks and smoothing
    M = np.load(W('unreg_median_G1.npy'))
    Mb = np.median(M[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    m33 = small_scale(nsmooth(Mb, 1.0))
    lab_n, lab = cv2.connectedComponents(both.astype(np.uint8))
    hi = {n: runs[n]['hires'] for n in names}; hm = np.where(np.isfinite(M), M, np.nan)
    Mh = np.nanmedian(hm.reshape(h2 // 2, 2, w2 // 2, 2).transpose(0, 2, 1, 3).reshape(h2 // 2, w2 // 2, 4), axis=2)
    yy0, xx0 = np.mgrid[-R_OUT:R_OUT + 1, -R_OUT:R_OUT + 1]
    def cut(img, xi, yi):
        """Cutout around bin (xi, yi), NaN where it runs off the sensor."""
        H2, W2 = img.shape; out = np.full(xx0.shape, np.nan, np.float32)
        a0, a1, b0_, b1_ = max(yi - R_OUT, 0), min(yi + R_OUT + 1, H2), max(xi - R_OUT, 0), min(xi + R_OUT + 1, W2)
        out[a0 - (yi - R_OUT):a1 - (yi - R_OUT), b0_ - (xi - R_OUT):b1_ - (xi - R_OUT)] = img[a0:a1, b0_:b1_]
        return out
    def disc(q, X, Y):
        """A round shadow: 1 - A inside radius r0, a logistic edge of width w, 1 far out. q = A, r0, w, cx, cy (bins)."""
        r = np.hypot(X - q[3], Y - q[4])
        return 1 - q[0] / (1 + np.exp((r - q[1]) / max(q[2], 0.3)))
    def fit_disc(t, X, Y, q0, free_centre=True):
        m = np.isfinite(t)
        f = (lambda q: disc(q, X[m], Y[m]) - t[m]) if free_centre else (lambda q: disc(np.r_[q, q0[3:]], X[m], Y[m]) - t[m])
        x0_ = q0 if free_centre else q0[:3]
        lo = [-0.3, 3, 0.3, q0[3] - 8, q0[4] - 8][:len(x0_)]; hi_ = [0.5, 28, 8, q0[3] + 8, q0[4] + 8][:len(x0_)]
        q = least_squares(f, x0_, bounds=(lo, hi_)).x
        return q if free_centre else np.r_[q, q0[3:]]
    dust_full = np.ones((h2, w2), np.float32); shadows = []
    Yp, Xp = np.mgrid[0:h2, 0:w2]
    for k in range(1, lab_n):
        sel = lab == k; yx = np.argwhere(sel); yb, xb = yx[int(np.argmin(mean[sel]))]
        xi, yi = int((xb * BS + 4) / 2), int((yb * BS + 4) / 2)                 # 2 x 2 bins
        X, Y = xx0 + xi, yy0 + yi
        ring = np.hypot(xx0, yy0) >= R_REF
        cuts = {n: cut(hi[n], xi, yi) for n in names}
        for n in names: cuts[n] = cuts[n] / np.nanmedian(cuts[n][ring])
        t = np.nanmean(np.stack([cuts[n] for n in names]), axis=0)
        q = fit_disc(t, X, Y, np.array([0.08, 12.0, 2.0, xi + 0.5, yi + 0.5]))
        qr = {n: fit_disc(cuts[n], X, Y, q, free_centre=False) for n in names}
        tm = cut(Mh, xi, yi); tm = tm / np.nanmedian(tm[ring]); qm = fit_disc(tm, X, Y, q, free_centre=False)
        rp = np.hypot(Xp / 2.0 + 0.25 - q[3], Yp / 2.0 + 0.25 - q[4])        # plane pixel centres in bins
        near = rp < q[1] + 10 * q[2] + 4
        dust_full[near] *= disc(q, Xp[near] / 2.0 + 0.25, Yp[near] / 2.0 + 0.25).astype(np.float32)
        resid = t - disc(q, X, Y)
        shadows.append(dict(plane_px=[round(2 * q[3], 1), round(2 * q[4], 1)], blocks=int(sel.sum()), depth=round(float(q[0]), 4), radius_plane_px=round(float(2 * q[1]), 1), edge_plane_px=round(float(2 * q[2]), 1),
                            depth_m57=round(float(qr[names[0]][0]), 4), depth_ngc1514=round(float(qr[names[1]][0]), 4), depth_in_m33_frames=round(float(qm[0]), 4),
                            fit_rms=round(float(np.sqrt(np.nanmean(resid ** 2))), 4), at_sensor_edge=bool(np.isnan(cuts[names[0]]).all(0).any() or np.isnan(cuts[names[0]]).all(1).any())))
    shadows.sort(key=lambda s: -s['depth'])
    diff = (a - b)[inner]
    rec['dust'] = dict(min_depth_each_run=1 - DUST_MIN, shadows_corrected=len(shadows), deepest_applied=float(1 - dust_full.min()),
                       runs_robust_rms_difference_blocks=float(1.4826 * np.median(np.abs(diff - np.median(diff)))), shadows=shadows,
                       how='found on 8 px blocks (green remainder, normalised Gaussian sigma 1 block, over its 31-block median; both runs alone deeper than the limit, blob >= 12 blocks, depths alike); '
                           'each kept shadow is then modelled at 2 x 2 plane px: per run the median over frames of the normalised green, divided by its median in a ring %d..%d plane px from the blob, '
                           'the two runs averaged, and a round shadow fitted to it by least squares: 1 - depth / (1 + exp((r - radius) / edge)), centre free (5 numbers). The flat is multiplied by that '
                           'model near each shadow and is exactly 1 elsewhere. Depth refitted to each run alone and to M33\'s own unregistered median with the same centre, radius and edge, as checks.' % (2 * R_REF, 2 * R_OUT))
    print('dust: %d shadows corrected; deepest applied %.3f' % (len(shadows), rec['dust']['deepest_applied']))
    for s_ in shadows: print('   shadow at plane px', s_['plane_px'], 'depth %.3f radius %.1f edge %.1f plane px | each run: M57 %.3f NGC 1514 %.3f | in the M33 frames %.3f | fit rms %.4f%s' % (s_['depth'], s_['radius_plane_px'], s_['edge_plane_px'], s_['depth_m57'], s_['depth_ngc1514'], s_['depth_in_m33_frames'], s_['fit_rms'], ' (at the sensor edge)' if s_['at_sensor_edge'] else ''))
    v = lambda z: (np.clip((z - 0.90) / 0.12, 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(W('v_dust_maps.png'), np.vstack([np.hstack([v(a), v(b)]), np.hstack([v(cv2.resize(dust_full, (nx, ny), interpolation=cv2.INTER_AREA)), v(m33)])]))
    rad_full = prof(np.hypot(*np.meshgrid(2 * np.arange(w2) + 0.5 - CENTRE[0], 2 * np.arange(h2) + 0.5 - CENTRE[1]))).astype(np.float32)
    flat = rad_full * dust_full
    np.save(W('flat.npy'), flat)
    rec['applied'] = 'flat = one radial profile (mean of the green fits, both runs jointly) x the dust map (only the shadows both runs see); the same for all four planes, evaluated at cell centres; the large-scale remainder and the sky slopes are NOT applied'
    rec['flat_range'] = [float(flat.min()), float(flat.max())]
    jdump(rec, 'step6_vignette.json')
    print('flat range %.3f..%.3f; profile at the corners %.3f' % (flat.min(), flat.max(), rec['profile_applied_corner']))
