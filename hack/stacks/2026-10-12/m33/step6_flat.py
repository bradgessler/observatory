"""Step 6: the flat field. Tonight there are no flat frames, no twilight flats (yet) and no open-sky run at these
settings: M33 fills its frames, and the only other 15 s ISO 3200 frames of the night are of a bright star. So:

1. Vignetting: the radial profile measured on 8 October from that night's two open-sky runs (M57 and NGC 1514, same
   telescope, camera and settings; hack/stacks/2026-10-08/m33/step6_vignette.py; it matched the 3 October twilight
   flat to 1%). The mean of its two green fits, the same for all four colour planes, read from that night's
   step6_vignette.json (FLAT_FROM). The optics are the same (the plate solve gives the same focal length), and
   M33's own frames cannot check it: the galaxy is everywhere in them. Said in the recipe.

2. Dust: dust moves between nights, so the shadows are found in TONIGHT's frames, not copied. The field wandered
   over 400 px of the sensor during the run while the dust stayed put, so the run gives two different skies behind
   the same dust: the frames before 07:57 UTC (half 'early') and after (half 'late'), every second frame of each.
   Per frame and plane, as on 8 October: hot pixels and everything brighter than the smooth light (stars; green above
   the frame's smooth level by 2.5 sigma after a 1.5 px blur, grown by 6 plane px; above 40 sigma grown by 24) left
   out, the plane divided by its own level in the central 600 x 600 plane px, 8 x 8 block medians; per half the
   median over its frames WITHOUT registration (the galaxy's own structure is smeared by the wander, the dust is not).
   The green of that, over the vignetting profile, smoothed (normalised Gaussian, 1 block) and divided by its own
   31-block median, is the small scale. A shadow is corrected only where BOTH halves, each alone, put it deeper than
   DUST_MIN, the blob is at least 12 blocks and the two halves measure its depth alike (each at least 3%, within
   2.5% of each other). Each such shadow is then modelled finely as a round disc with a soft edge
   (1 - depth / (1 + exp((r - radius) / edge)), centre free), fitted to the two halves' mean at 2 x 2 plane px.
   The flat is multiplied by that model near each shadow and is exactly 1 elsewhere. The same map for all planes.
   Each shadow is compared with the 8 October list (same place? same depth?), and the 8 October shadows that
   tonight's frames do not show are listed as gone and NOT applied.

Writes flat.npy (2012, 3012): divide every M33 plane by it (on that plane's own pixels). 1 at the sensor centre."""
import os, json, warnings
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from scipy.optimize import least_squares
from scipy.ndimage import median_filter
from common import *

warnings.filterwarnings('ignore', 'All-NaN slice'); warnings.filterwarnings('ignore', 'Mean of empty slice')
BS = 8
ny, nx = h2 // BS, w2 // BS
LARGE = 31
DUST_MIN = float(os.environ.get('M33_DUST_MIN', '0.975'))
SHADOW_BLOCKS = 12
R_REF, R_OUT = 30, 38
SPLIT = '20261013-075700'
EVERY = int(os.environ.get('M33_FLAT_EVERY', '2'))


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


def radial(c, rho): return 1 + c[0] * rho ** 2 + c[1] * rho ** 4 + c[2] * rho ** 6


def nsmooth(R, s=1.0):
    m = np.isfinite(R).astype(np.float32); f = np.where(np.isfinite(R), R, 0).astype(np.float32)
    return cv2.GaussianBlur(f, (0, 0), s) / np.maximum(cv2.GaussianBlur(m, (0, 0), s), 1e-3)


def small_scale(S):
    return S / median_filter(S, size=LARGE, mode='nearest')


if __name__ == '__main__':
    old = json.load(open(FLAT_FROM))
    cG1, cG2 = old['planes']['G1']['radial_a2_a4_a6'], old['planes']['G2']['radial_a2_a4_a6']
    prof = lambda r: 0.5 * (radial(cG1, r / 3000) + radial(cG2, r / 3000))
    frames = jload('step1.json')['frames']
    halves = dict(early=[f['path'] for f in frames if f['stamp'] < SPLIT][::EVERY], late=[f['path'] for f in frames if f['stamp'] >= SPLIT][::EVERY])
    runs = {}
    for n, fs in halves.items():
        with ProcessPoolExecutor(WORKERS) as ex:
            res = list(ex.map(blocks_of, fs))
        runs[n] = dict(files=[os.path.basename(f) for f in fs], levels=[r[1] for r in res], masked=[r[2] for r in res], flat=np.nanmedian(np.stack([r[0] for r in res]), axis=0),
                       hires=np.nanmedian(np.stack([r[3] for r in res]), axis=0))
        print(n, len(fs), 'frames; level (central, DN) R G1 G2 B median', np.round(np.median([r[1] for r in res], axis=0), 1).tolist(), 'masked %.1f%%' % (100 * np.median([r[2] for r in res])), flush=True)
        del res
    names = list(runs)
    rr = np.linspace(0, 3700, 38)
    rec = dict(block_px=BS, vignetting=dict(source=FLAT_FROM, what='radial profile of 8 October 2026 (two open-sky runs, joint fit), mean of the G1 and G2 fits, the same for all four planes',
                                            radial_a2_a4_a6=dict(G1=cG1, G2=cG2), formula='1 + a2 rho^2 + a4 rho^4 + a6 rho^6, rho = distance from the sensor centre / 3000 sensor px',
                                            profile_r_sensor_px=rr.tolist(), profile_applied=prof(rr).tolist(), corner=float(prof(np.hypot(*CENTRE))),
                                            check_tonight='none possible from M33 frames (the galaxy fills them); the same optics by plate solve'),
               halves={n: dict(files=runs[n]['files'], level_dn_median=np.median(runs[n]['levels'], axis=0).tolist()) for n in names}, split_at=SPLIT)
    # the small scale of each half (green)
    Y, X = np.mgrid[0:ny, 0:nx]
    smalls = {}
    for n in names:
        R = []
        for p in (1, 2):
            ox, oy = OFFS[p]; x = 2 * (X * BS + (BS - 1) / 2) + ox; y = 2 * (Y * BS + (BS - 1) / 2) + oy
            R.append(runs[n]['flat'][p] / prof(np.hypot(x - CENTRE[0], y - CENTRE[1])))
        smalls[n] = small_scale(nsmooth(0.5 * (R[0] + R[1]), 1.0))
    a, b = smalls[names[0]], smalls[names[1]]
    inner = np.zeros((ny, nx), bool); inner[3:-3, 3:-3] = True
    cand = (a < DUST_MIN) & (b < DUST_MIN) & inner
    lab_n, lab = cv2.connectedComponents(cand.astype(np.uint8))
    both = np.zeros_like(cand); turned_down = []
    for k in range(1, lab_n):
        sel = lab == k; yb, xb = np.argwhere(sel)[int(np.argmin((0.5 * (a + b))[sel]))]
        da, db = 1 - a[yb, xb], 1 - b[yb, xb]
        if sel.sum() >= SHADOW_BLOCKS and min(da, db) >= 0.03 and abs(da - db) <= 0.025: both |= sel
        elif sel.sum() >= 6: turned_down.append(dict(plane_px=[int(xb * BS + 4), int(yb * BS + 4)], blocks=int(sel.sum()), depth_early=round(float(da), 4), depth_late=round(float(db), 4)))
    mean = 0.5 * (a + b)
    lab_n, lab = cv2.connectedComponents(both.astype(np.uint8))
    hi = {n: runs[n]['hires'] for n in names}
    yy0, xx0 = np.mgrid[-R_OUT:R_OUT + 1, -R_OUT:R_OUT + 1]
    def cut(img, xi, yi):
        H2, W2 = img.shape; out = np.full(xx0.shape, np.nan, np.float32)
        a0, a1, b0_, b1_ = max(yi - R_OUT, 0), min(yi + R_OUT + 1, H2), max(xi - R_OUT, 0), min(xi + R_OUT + 1, W2)
        out[a0 - (yi - R_OUT):a1 - (yi - R_OUT), b0_ - (xi - R_OUT):b1_ - (xi - R_OUT)] = img[a0:a1, b0_:b1_]
        return out
    def disc(q, X_, Y_):
        r = np.hypot(X_ - q[3], Y_ - q[4])
        return 1 - q[0] / (1 + np.exp((r - q[1]) / max(q[2], 0.3)))
    def fit_disc(t, X_, Y_, q0, free_centre=True):
        m = np.isfinite(t)
        f = (lambda q: disc(q, X_[m], Y_[m]) - t[m]) if free_centre else (lambda q: disc(np.r_[q, q0[3:]], X_[m], Y_[m]) - t[m])
        x0_ = q0 if free_centre else q0[:3]
        lo = [-0.3, 3, 0.3, q0[3] - 8, q0[4] - 8][:len(x0_)]; hi_ = [0.5, 28, 8, q0[3] + 8, q0[4] + 8][:len(x0_)]
        q = least_squares(f, x0_, bounds=(lo, hi_)).x
        return q if free_centre else np.r_[q, q0[3:]]
    dust_full = np.ones((h2, w2), np.float32); shadows = []
    Yp, Xp = np.mgrid[0:h2, 0:w2]
    olds = old['dust']['shadows']; seen_old = set()
    for k in range(1, lab_n):
        sel = lab == k; yx = np.argwhere(sel); yb, xb = yx[int(np.argmin(mean[sel]))]
        xi, yi = int((xb * BS + 4) / 2), int((yb * BS + 4) / 2)
        X_, Y_ = xx0 + xi, yy0 + yi
        ring = np.hypot(xx0, yy0) >= R_REF
        cuts = {n: cut(hi[n], xi, yi) for n in names}
        for n in names: cuts[n] = cuts[n] / np.nanmedian(cuts[n][ring])
        t = np.nanmean(np.stack([cuts[n] for n in names]), axis=0)
        q = fit_disc(t, X_, Y_, np.array([0.08, 12.0, 2.0, xi + 0.5, yi + 0.5]))
        qr = {n: fit_disc(cuts[n], X_, Y_, q, free_centre=False) for n in names}
        rp = np.hypot(Xp / 2.0 + 0.25 - q[3], Yp / 2.0 + 0.25 - q[4])
        near = rp < q[1] + 10 * q[2] + 4
        dust_full[near] *= disc(q, Xp[near] / 2.0 + 0.25, Yp[near] / 2.0 + 0.25).astype(np.float32)
        resid = t - disc(q, X_, Y_)
        pos = [round(2 * q[3], 1), round(2 * q[4], 1)]
        d8 = [(float(np.hypot(pos[0] - o['plane_px'][0], pos[1] - o['plane_px'][1])), i) for i, o in enumerate(olds)]
        dmin, i8 = min(d8)
        was = None
        if dmin < 30:
            seen_old.add(i8); was = dict(plane_px=olds[i8]['plane_px'], depth=olds[i8]['depth'], moved_px=round(dmin, 1))
        shadows.append(dict(plane_px=pos, blocks=int(sel.sum()), depth=round(float(q[0]), 4), radius_plane_px=round(float(2 * q[1]), 1), edge_plane_px=round(float(2 * q[2]), 1),
                            depth_early=round(float(qr[names[0]][0]), 4), depth_late=round(float(qr[names[1]][0]), 4), fit_rms=round(float(np.sqrt(np.nanmean(resid ** 2))), 4),
                            on_8_october=was))
    shadows.sort(key=lambda s: -s['depth'])
    gone = []
    for i, o in enumerate(olds):
        if i in seen_old: continue
        xb, yb = int(o['plane_px'][0] // BS), int(o['plane_px'][1] // BS)
        gone.append(dict(plane_px=o['plane_px'], depth_on_8_october=o['depth'], small_scale_tonight_early=round(float(a[min(yb, ny - 1), min(xb, nx - 1)]), 4), small_scale_tonight_late=round(float(b[min(yb, ny - 1), min(xb, nx - 1)]), 4)))
    diff = (a - b)[inner]
    rec['dust'] = dict(min_depth_each_half=1 - DUST_MIN, shadows_corrected=len(shadows), deepest_applied=float(1 - dust_full.min()), halves_robust_rms_difference_blocks=float(1.4826 * np.median(np.abs(diff - np.median(diff)))),
                       shadows=shadows, of_8_october_not_seen_tonight_not_applied=gone, candidates_turned_down=turned_down)
    print('dust: %d shadows corrected tonight; deepest applied %.3f; the two halves differ by %.4f rms on blocks' % (len(shadows), rec['dust']['deepest_applied'], rec['dust']['halves_robust_rms_difference_blocks']))
    for s_ in shadows: print('   shadow at plane px', s_['plane_px'], 'depth %.3f radius %.1f edge %.1f | early %.3f late %.3f | fit rms %.4f | 8 October:' % (s_['depth'], s_['radius_plane_px'], s_['edge_plane_px'], s_['depth_early'], s_['depth_late'], s_['fit_rms']), s_['on_8_october'])
    for g in gone: print('   8 October shadow NOT seen tonight (not applied):', g)
    for g in turned_down: print('   candidate turned down (too small or the halves disagree):', g)
    v = lambda z: (np.clip((z - 0.90) / 0.12, 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(W('v_dust_maps.png'), np.vstack([np.hstack([v(a), v(b)]), np.hstack([v(cv2.resize(dust_full, (nx, ny), interpolation=cv2.INTER_AREA)), v(mean)])]))
    rad_full = prof(np.hypot(*np.meshgrid(2 * np.arange(w2) + 0.5 - CENTRE[0], 2 * np.arange(h2) + 0.5 - CENTRE[1]))).astype(np.float32)
    flat = rad_full * dust_full
    np.save(W('flat.npy'), flat)
    rec['applied'] = 'flat = the 8 October radial profile (mean of its green fits) x tonight\'s dust map (only the shadows both halves of tonight\'s run see); the same for all four planes, evaluated at cell centres'
    rec['flat_range'] = [float(flat.min()), float(flat.max())]
    jdump(rec, 'step6_flat.json')
    print('flat range %.3f..%.3f; profile at the corners %.3f' % (flat.min(), flat.max(), rec['vignetting']['corner']))
