"""Step 7: the night's flat, from this run's own open sky. There are no flat frames and no twilight flats; NGC 891 is
the first target tonight that leaves open sky around it at 15 s and ISO 3200 (sky about 20, 76, 76, 48 DN in R, G1,
G2, B; the galaxy was 85 degrees up, so the sky itself is as even as it gets). That sky, seen through the optics, is a
sky flat. Method of hack/stacks/2026-10-08/m33/step6_vignette.py, with one run instead of two.

Per frame and colour plane (every 15 s ISO 3200 frame of the run, smeared or not: the sky does not care): hot pixels
(step 1's map), everything brighter than the smooth sky (stars: green above the frame's smooth level by 2.5 sigma
after a 1.5 px blur, grown by 6 plane px; above 40 sigma grown by 24) and the galaxy itself (a tight ellipse: the
catalogue's place and angle, semi-axes TIGHT arcmin, moved with the frame's registration shift, grown by 8 px) are left
out; the plane is divided by its own clipped sky level in the central 900 x 900 plane px outside that; 8 x 8 plane-px
block medians. Then the median of those over the frames, WITHOUT registration (the stars are masked in each frame
anyway, and the field wandered by 50 plane px). For the vignetting fit the blocks inside the generous ellipse of step 6
(grown by the field's wander) are left out as well: the galaxy's faint outer light must not shape the profile. The
dust search keeps them (it works on the small scale, over a 31-block median, which the smooth outer light passes).

1. Vignetting, per colour (multiplicative). Block value at sensor (x, y), rho = r / 3000, r from the sensor centre:
       F = k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) (1 + gx (x - xc) / 3000 + gy (y - yc) / 3000)
   The linear factor is this sky's own slope across the field; it is fitted so that it does not bias the radial part
   and it is NOT part of the flat. Robust fit (3 sigma, 4 rounds). Each of R, G1, G2, B gets its own profile:
   that is what makes each colour's sky level in the flat-fielded frames.
   The plain radial fit leaves a pattern in tonight's sky (the middle and the ends of the short side 3 to 5% below
   the model, the ends of the long side above it: rms 1.8%): the light falls off faster along the sensor's short side
   than along its long side. So rho^2 = (dx^2 + e dy^2) / 3000^2 with e fitted per colour (ELLIPTICAL; about 1.7 in
   green): one more number, and the remainder drops to 0.6% rms. That is the flat. The plain radial fit (e = 1) is
   kept beside it for the comparison with 8 October.
   The comparison: the 8 October profile (two open-sky runs, mean of its green fits, used for all four planes by
   tonight's M33 stack), and each half of tonight's run fitted alone.

2. Dust. What is left after the fit (median flat / fitted model, the two green planes averaged) holds the dust
   shadows. Found as on 8 October and in tonight's M33 stack: the remainder smoothed (normalised Gaussian, 1 block) and
   divided by its own 31-block median, for the two halves of the run each alone (frames before and after SPLIT: the
   field moved 50 plane px between them, the dust stayed). A shadow is corrected only where BOTH halves put it deeper
   than DUST_MIN, the blob is at least 12 blocks and the halves measure its depth alike (each at least 3%, within
   2.5% of each other), or, when a shadow was already listed at that place (within 30 plane px) on 8 October or by
   tonight's M33 stack, at least 6 blocks and each half at least 2.5% deep: a third sighting. Each such shadow is modelled as a round disc with a soft edge
   (1 - depth / (1 + exp((r - radius) / edge)), centre free), fitted to the two halves' mean at 2 x 2 plane px. The
   flat is multiplied by that model near each shadow and is exactly 1 elsewhere; the same shadow map for all planes.
   That list (13 shadows) is the comparison with 8 October and with tonight's M33 stack. It is NOT enough for a
   picture of open sky: the first stack showed a dozen dark streaks, 10 px wide and 80 long, where smaller or
   shallower shadows (rings 30 to 50 px across, 3 to 5% deep, too few 8 px blocks for the rule above) had been dragged
   along the field's wander. So the dust map that is applied is MEASURED, not modelled (DUST_MEASURED): the median over
   all frames of the normalised green at 2 x 2 plane px, over the fitted profile, smoothed (normalised Gaussian, sigma
   DUST_SIGMA bins) and divided by its own large scale (normalised Gaussian, sigma 25 bins); the same for each half.
   Where all three (all frames, early half, late half) are below DUST_T (2% deep: 2.5 sigma of a half's map) over at least 20 bins, and no star or galaxy hid the sky in more
   than 4 frames of 10, grown by 6 bins and feathered
   (Gaussian sigma 2 bins), the flat is multiplied by the all-frames map (never above 1); everywhere else the dust map
   is exactly 1. The 13 modelled shadows are inside it. The same map for all four planes.
   Shadows under the galaxy itself (the tight ellipse) cannot be seen in these frames and are NOT in this flat; listed
   shadows of 8 October and of tonight's M33 stack that this flat does not carry are written beside ours.

Writes work/flat.npy (4, 2012, 3012) float32: divide plane p by flat[p] (on that plane's own pixels). 1 at the sensor
centre. And for the other targets of the night, FLAT_DIR (the night's flat/ folder): flat_planes.npz (float16,
compressed: R, G1, G2, B), flat.json (every number of the model, so it can be rebuilt without the arrays), README.txt
and a small picture of the remainder."""
import os, json, warnings
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from scipy.optimize import least_squares
from scipy.ndimage import median_filter
from common import *
import solvelib

warnings.filterwarnings('ignore', 'All-NaN slice'); warnings.filterwarnings('ignore', 'Mean of empty slice')
BS = 8
ny, nx = h2 // BS, w2 // BS
LARGE = 31
DUST_MIN = float(os.environ.get('N891_DUST_MIN', '0.975'))
SHADOW_BLOCKS = 12
R_REF, R_OUT = 30, 38
DUST_MEASURED = os.environ.get('N891_DUST_MEASURED', '1') == '1'
DUST_SIGMA = float(os.environ.get('N891_DUST_SIGMA', '3.0'))   # bins of 2 x 2 plane px
DUST_T = float(os.environ.get('N891_DUST_T', '0.98'))
SPLIT = os.environ.get('N891_FLAT_SPLIT', '20261013-090030')
ELL = jload('step6_solve_ref.json')['galaxy_ellipse']
TIGHT = (float(os.environ.get('N891_TIGHT_A', '7.0')), float(os.environ.get('N891_TIGHT_B', '1.0')))   # arcmin, semi-axes of the galaxy itself
ELL_TIGHT = dict(ELL, semi_major_px=TIGHT[0] * 60 / jload('step6_solve_ref.json')['pixscale_arcsec'], semi_minor_px=TIGHT[1] * 60 / jload('step6_solve_ref.json')['pixscale_arcsec'])
TR = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
ELLIPTICAL = os.environ.get('N891_FLAT_ELLIPTICAL', '1') == '1'   # the fall-off is not the same along the sensor's long and short sides: rho^2 = (dx^2 + e dy^2) / 3000^2, e fitted per colour


def blocks_of(fr):
    hot = np.load(W('hotmap.npy'))
    P, ceil, meta = load_planes(fr['path'])
    G = (P[1] + P[2]) / 2
    sm = smooth_level(G, 16, 5); D = cv2.GaussianBlur(G - sm, (0, 0), 1.5)
    s = 1.4826 * np.median(np.abs(D[::3, ::3] - np.median(D[::3, ::3])))
    m1 = cv2.dilate((D > 2.5 * s).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
    m2 = cv2.dilate((D > 40 * s).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49)))
    sh = np.array(TR[fr['stamp']]['shift_at_centre_px']) / 2            # the galaxy on this frame: the reference place + the frame's shift (plane px)
    gal = solvelib.ellipse_mask(ELL_TIGHT, (h2, w2), shift=sh, grow=8.0)
    mask = (m1 | m2).astype(bool) | gal
    out = np.full((4, ny, nx), np.nan, np.float32); lev = []
    c = (slice(h2 // 2 - 450, h2 // 2 + 450), slice(w2 // 2 - 450, w2 // 2 + 450))
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


def rho_of(x, y, e=1.0):
    return np.sqrt((x - CENTRE[0]) ** 2 + e * (y - CENTRE[1]) ** 2) / 3000


def model(q, x, y):
    return q[3] * radial(q[:3], rho_of(x, y, q[6])) * (1 + q[4] * (x - CENTRE[0]) / 3000 + q[5] * (y - CENTRE[1]) / 3000)


def fit(v, p, free_e=ELLIPTICAL):
    """Robust fit of one plane's block flat: a2, a4, a6, k, gx, gy, e (e = 1 when not free); rms of the blocks kept; how many."""
    x, y = block_xy(p); m = np.isfinite(v); x, y, v = x[m], y[m], v[m]
    q = np.array([-0.3, 0.0, 0.0, float(np.median(v)), 0.0, 0.0, 1.0]); keep = np.ones(len(v), bool)
    full = (lambda z: z) if free_e else (lambda z: np.r_[z, 1.0])
    for _ in range(4):
        q = full(least_squares(lambda q_: model(full(q_), x[keep], y[keep]) - v[keep], q if free_e else q[:6]).x)
        r = v - model(q, x, y); s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3 * s
    return q, float(np.sqrt(np.mean((v - model(q, x, y))[keep] ** 2))), int(keep.sum())


def nsmooth(R, s=1.0):
    m = np.isfinite(R).astype(np.float32); f = np.where(np.isfinite(R), R, 0).astype(np.float32)
    return cv2.GaussianBlur(f, (0, 0), s) / np.maximum(cv2.GaussianBlur(m, (0, 0), s), 1e-3)


def small_scale(S):
    return S / median_filter(S, size=LARGE, mode='nearest')


if __name__ == '__main__':
    old = json.load(open(FLAT_FROM))
    cG1, cG2 = old['planes']['G1']['radial_a2_a4_a6'], old['planes']['G2']['radial_a2_a4_a6']
    prof8 = lambda r: 0.5 * (radial(cG1, r / 3000) + radial(cG2, r / 3000))
    frames = [f for f in jload('step1.json')['frames'] if not TR[f['stamp']].get('failed')]
    halves = dict(early=[f for f in frames if f['stamp'] < SPLIT], late=[f for f in frames if f['stamp'] >= SPLIT])
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(blocks_of, frames))
    idx = {n: [i for i, f in enumerate(frames) if f in fs] for n, fs in halves.items()}
    cube = np.stack([r[0] for r in res]); hires = np.stack([r[3] for r in res]); levels = np.array([r[1] for r in res])
    allflat_dust = np.nanmedian(cube, axis=0)
    runs = {n: dict(flat=np.nanmedian(cube[i], axis=0), hires=np.nanmedian(hires[i], axis=0)) for n, i in idx.items()}
    hires_all = np.nanmedian(hires, axis=0); hires_count = np.isfinite(hires).sum(0)
    wander = float(np.max(np.abs([TR[f['stamp']]['shift_at_centre_px'] for f in frames])) / 2)
    wide = cv2.resize(solvelib.ellipse_mask(ELL, (h2, w2), grow=wander + 8).astype(np.uint8), (nx, ny), interpolation=cv2.INTER_AREA) > 0       # blocks the generous ellipse touches in any frame
    allflat = np.where(wide[None], np.nan, allflat_dust)
    for n in list(runs): runs[n]['fitflat'] = np.where(wide[None], np.nan, runs[n]['flat'])
    masked = float(np.median([r[2] for r in res]))
    print('%d frames (%d early, %d late); sky level (central, DN) R G1 G2 B median %s, range %s .. %s; masked %.1f%% of each frame' % (
        len(frames), len(idx['early']), len(idx['late']), np.round(np.median(levels, axis=0), 1).tolist(), np.round(levels.min(0), 1).tolist(), np.round(levels.max(0), 1).tolist(), 100 * masked), flush=True)
    del cube, hires, res
    names = list(runs)
    rr = np.linspace(0, 3600, 37); rc = float(np.hypot(*CENTRE))
    rec = dict(made_from=dict(target='NGC 891 run', frames=[f['name'] for f in frames], exposure_s=EXPOSURE_S, iso=ISO, sky_level_dn_median=dict(zip(PLANE_NAMES, np.median(levels, axis=0).round(2).tolist())),
                              altitude_deg=[frames[0].get('alt_deg'), frames[-1].get('alt_deg')], masked_fraction_median=masked, galaxy_ellipse_left_out_of_the_vignetting_fit=ELL, galaxy_ellipse_left_out_of_everything=ELL_TIGHT, wander_plane_px=wander, split_at=SPLIT,
                              halves={n: [frames[i]['name'] for i in ii] for n, ii in idx.items()}),
               block_px=BS, formula='flat = (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) x dust, with applied_a2_a4_a6 and rho = sqrt(dx^2 + applied_e x dy^2) / 3000, (dx, dy) = sensor px from the sensor centre (3011.5, 2011.5); plane pixel (X, Y) of a plane with cell offset (ox, oy) is sensor pixel (2X + ox, 2Y + oy); offsets R (0,0), G1 (1,0), G2 (0,1), B (1,1)',
               planes={}, profile_r_sensor_px=rr.tolist())
    fits = {}; fits_r = {}
    for p in range(4):
        q, rms, used = fit(allflat[p], p)
        qr, rms_r, _ = fit(allflat[p], p, free_e=False)                 # the plain radial fit: what 8 October fitted, for the comparison
        alone = {n: fit(runs[n]['fitflat'][p], p, free_e=False)[0] for n in names}
        fits[p] = q; fits_r[p] = qr
        pr = radial(qr[:3], rr / 3000); pa = {n: radial(alone[n][:3], rr / 3000) for n in names}
        rec['planes'][PLANE_NAMES[p]] = dict(applied_a2_a4_a6=q[:3].tolist(), applied_e=float(q[6]), k=float(q[3]), sky_slope_gx_gy_not_applied=[float(q[4]), float(q[5])], fit_rms=rms, blocks_used=used,
                                             applied_at_long_edge_short_edge_corner=[float(radial(q[:3], rho_of(2 * CENTRE[0], CENTRE[1], q[6]))), float(radial(q[:3], rho_of(CENTRE[0], 2 * CENTRE[1], q[6]))), float(radial(q[:3], rho_of(0, 0, q[6])))],
                                             radial_only_a2_a4_a6=qr[:3].tolist(), radial_only_fit_rms=rms_r,
                                             profile=pr.tolist(), corner_value=float(radial(qr[:3], rc / 3000)), each_half_alone_a2_a4_a6={n: alone[n][:3].tolist() for n in names},
                                             halves_alone_differ_max=float(np.max(np.abs(pa[names[0]] - pa[names[1]]))),
                                             minus_8_october_green_profile=(pr - prof8(rr)).tolist(), minus_8_october_max_abs=float(np.max(np.abs(pr - prof8(rr)))),
                                             minus_8_october_at_corner=float(radial(qr[:3], rc / 3000) - prof8(rc)))
        print('%-2s applied %s e %.3f (ends of the long side %.3f, of the short side %.3f, corner %.3f) fit rms %.4f | radial only %s corner %.3f | sky slope gx %.4f gy %.4f (not applied) | fit rms %.4f | halves alone differ by up to %.3f | radial only against 8 October green: max %.3f, at the corner %+.3f' % (
            PLANE_NAMES[p], np.round(q[:3], 4).tolist(), q[6], *rec['planes'][PLANE_NAMES[p]]['applied_at_long_edge_short_edge_corner'], rms, np.round(qr[:3], 4).tolist(), rec['planes'][PLANE_NAMES[p]]['corner_value'], q[4], q[5], rms_r, rec['planes'][PLANE_NAMES[p]]['halves_alone_differ_max'],
            rec['planes'][PLANE_NAMES[p]]['minus_8_october_max_abs'], rec['planes'][PLANE_NAMES[p]]['minus_8_october_at_corner']), flush=True)
    gmean = 0.5 * (radial(fits_r[1][:3], rr / 3000) + radial(fits_r[2][:3], rr / 3000))
    rec['against_8_october'] = dict(source=FLAT_FROM, what='the 8 October radial profile (two open-sky runs, joint fit, mean of the G1 and G2 fits) that tonight\'s M33 stack applied to all four planes',
                                    profile_8_october=prof8(rr).tolist(), tonight_green_mean=gmean.tolist(), green_mean_minus_8_october=(gmean - prof8(rr)).tolist(),
                                    green_max_abs_difference=float(np.max(np.abs(gmean - prof8(rr)))), green_rms_difference_inside_2000px=float(np.sqrt(np.mean((gmean - prof8(rr))[rr <= 2000] ** 2))),
                                    corner_8_october=float(prof8(rc)), corner_tonight_green=float(0.5 * (radial(fits_r[1][:3], rc / 3000) + radial(fits_r[2][:3], rc / 3000))))
    print('green (mean of G1, G2) against 8 October: max difference %.3f over the sensor, rms %.4f inside 2000 px; corner %.3f tonight, %.3f on 8 October' % (
        rec['against_8_october']['green_max_abs_difference'], rec['against_8_october']['green_rms_difference_inside_2000px'], rec['against_8_october']['corner_tonight_green'], rec['against_8_october']['corner_8_october']))
    # the large-scale remainder (flat / model), green: what a radial profile does not describe
    rec['large_scale_remainder_green'] = {}
    for label, ff in (('applied_model', fits), ('radial_only', fits_r)):
        rem = []
        for p in (1, 2):
            x, y = block_xy(p); rem.append(allflat_dust[p] / model(ff[p], x, y))
        rem = 0.5 * (rem[0] + rem[1])
        big = median_filter(nsmooth(rem, 2.0), size=LARGE, mode='nearest'); okb = np.isfinite(rem) & ~wide
        rec['large_scale_remainder_green'][label] = dict(what='median flat / fitted model (profile x sky slope), 31-block median, outside the galaxy\'s generous ellipse: not applied', rms=float(np.std(big[okb])), min=float(big[okb].min()), max=float(big[okb].max()))
        print('large-scale remainder (green, not applied), %s: rms %.4f, range %.3f..%.3f' % (label, np.std(big[okb]), big[okb].min(), big[okb].max()))
        if label == 'applied_model': remG = rem
    okb = np.isfinite(remG)
    # ---- dust: the small scale of each half (green)
    M33F = os.path.join(NIGHT, 'm33', 'work', 'step6_flat.json')
    M33S = json.load(open(M33F))['dust']['shadows'] if os.path.exists(M33F) else []
    smalls = {}
    for n in names:
        R = []
        for p in (1, 2):
            x, y = block_xy(p); R.append(runs[n]['flat'][p] / model(fits[p], x, y))
        smalls[n] = small_scale(nsmooth(0.5 * (R[0] + R[1]), 1.0))
    a, b = smalls[names[0]], smalls[names[1]]
    seen = np.isfinite(runs[names[0]]['flat'][1]) & np.isfinite(runs[names[1]]['flat'][1])
    seen_wide = cv2.erode(seen.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    inner = np.zeros((ny, nx), bool); inner[3:-3, 3:-3] = True
    cand = (a < DUST_MIN) & (b < DUST_MIN) & inner & seen_wide
    lab_n, lab = cv2.connectedComponents(cand.astype(np.uint8))
    both = np.zeros_like(cand); turned_down = []
    for k in range(1, lab_n):
        sel = lab == k; yb, xb = np.argwhere(sel)[int(np.argmin((0.5 * (a + b))[sel]))]
        da, db = 1 - a[yb, xb], 1 - b[yb, xb]
        pos_ = [xb * BS + 4, yb * BS + 4]
        known = any(np.hypot(pos_[0] - o['plane_px'][0], pos_[1] - o['plane_px'][1]) < 30 for o in list(old['dust']['shadows']) + M33S)
        if sel.sum() >= SHADOW_BLOCKS and min(da, db) >= 0.03 and abs(da - db) <= 0.025: both |= sel
        elif known and sel.sum() >= 6 and min(da, db) >= 0.025 and abs(da - db) <= 0.025: both |= sel
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
    m33s = M33S; seen_m33 = set()
    def nearest(pos, lst):
        if not lst: return None, None
        d = [(float(np.hypot(pos[0] - o['plane_px'][0], pos[1] - o['plane_px'][1])), i) for i, o in enumerate(lst)]
        dmin, i = min(d)
        return (i, dmin) if dmin < 30 else (None, None)
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
        i8, d8 = nearest(pos, olds); im, dm = nearest(pos, m33s)
        if i8 is not None: seen_old.add(i8)
        if im is not None: seen_m33.add(im)
        shadows.append(dict(plane_px=pos, blocks=int(sel.sum()), depth=round(float(q[0]), 4), radius_plane_px=round(float(2 * q[1]), 1), edge_plane_px=round(float(2 * q[2]), 1),
                            centre_bins=[float(q[3]), float(q[4])], radius_bins=float(q[1]), edge_bins=float(q[2]), depth_exact=float(q[0]),
                            depth_early=round(float(qr[names[0]][0]), 4), depth_late=round(float(qr[names[1]][0]), 4), fit_rms=round(float(np.sqrt(np.nanmean(resid ** 2))), 4),
                            on_8_october=dict(plane_px=olds[i8]['plane_px'], depth=olds[i8]['depth'], moved_px=round(d8, 1)) if i8 is not None else None,
                            in_tonights_m33_stack=dict(plane_px=m33s[im]['plane_px'], depth=m33s[im]['depth'], moved_px=round(dm, 1)) if im is not None else None))
    shadows.sort(key=lambda s: -s['depth'])
    dust_modelled = dust_full
    if DUST_MEASURED:
        yb_, xb_ = np.mgrid[0:h2 // 2, 0:w2 // 2]
        mod = 0.5 * (model(np.r_[fits[1][:3], 1.0, fits[1][4:]], 4 * xb_ + 2.0, 4 * yb_ + 1.5) + model(np.r_[fits[2][:3], 1.0, fits[2][4:]], 4 * xb_ + 1.0, 4 * yb_ + 2.5))
        def small(hm):
            s_ = nsmooth(hm / mod, DUST_SIGMA)
            return s_ / np.maximum(nsmooth(np.where(np.isfinite(hm), s_, np.nan), 25.0), 1e-3)
        Sa, Se, Sl = small(hires_all), small(hi[names[0]]), small(hi[names[1]])
        have = np.isfinite(hires_all) & np.isfinite(hi[names[0]]) & np.isfinite(hi[names[1]]) & (hires_count >= 0.6 * len(frames))   # not where a star or the galaxy hid the sky in 4 frames of 10
        core = (Sa < DUST_T) & (Se < DUST_T) & (Sl < DUST_T) & have
        nlab, lab_, stats_, _ = cv2.connectedComponentsWithStats(core.astype(np.uint8), connectivity=8)
        core = np.isin(lab_, [i for i in range(1, nlab) if stats_[i, cv2.CC_STAT_AREA] >= 20])           # at least 20 bins (80 plane px) of agreed shadow
        wgt = cv2.GaussianBlur(cv2.dilate(core.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(np.float32), (0, 0), 2.0)
        dm = 1 + (np.minimum(np.where(have, Sa, 1.0), 1.0) - 1) * wgt
        dust_full = cv2.resize(dm.astype(np.float32), (w2, h2), interpolation=cv2.INTER_LINEAR)
        nl2 = cv2.connectedComponents(core.astype(np.uint8))[0] - 1
        rec['dust_measured'] = dict(sigma_bins=DUST_SIGMA, threshold=DUST_T, shadows=int(nl2), area_fraction=float((wgt > 0.5).mean()), deepest=float(1 - dm.min()), not_searched_fraction=float(1 - have.mean()),
                                    modelled_shadows_inside=int(sum(1 for s_ in shadows if wgt[int(np.clip(s_['centre_bins'][1], 0, h2 // 2 - 1)), int(np.clip(s_['centre_bins'][0], 0, w2 // 2 - 1))] > 0.5)),
                                    noise_of_the_map='%.4f rms (the early and the late half differ by that / 2 where no shadow is)' % float(1.4826 * np.median(np.abs((Se - Sl)[have] - np.median((Se - Sl)[have]))) / 2))
        print('measured dust map: %d shadows, %.2f%% of the sensor, deepest %.3f; %d of the %d modelled shadows are inside it; map noise %s' % (nl2, 100 * rec['dust_measured']['area_fraction'], rec['dust_measured']['deepest'], rec['dust_measured']['modelled_shadows_inside'], len(shadows), rec['dust_measured']['noise_of_the_map']))
        cv2.imwrite(W('v_dust_measured.png'), np.hstack([(np.clip((np.nan_to_num(Sa, nan=1.0) - 0.90) / 0.12, 0, 1) * 255).astype(np.uint8), (np.clip((dm - 0.90) / 0.12, 0, 1) * 255).astype(np.uint8)]))
    def here(o):
        xb, yb = min(int(o['plane_px'][0] // BS), nx - 1), min(int(o['plane_px'][1] // BS), ny - 1)
        return dict(plane_px=o['plane_px'], depth_there=o['depth'], under_the_galaxy=bool(not seen_wide[yb, xb]), small_scale_here_early=round(float(a[yb, xb]), 4), small_scale_here_late=round(float(b[yb, xb]), 4))
    not8 = [here(o) for i, o in enumerate(olds) if i not in seen_old]; notm = [here(o) for i, o in enumerate(m33s) if i not in seen_m33]
    diff = (a - b)[inner & seen_wide]
    rec['dust'] = dict(min_depth_each_half=1 - DUST_MIN, shadows_corrected=len(shadows), deepest_applied=float(1 - dust_modelled.min()), halves_robust_rms_difference_blocks=float(1.4826 * np.median(np.abs(diff - np.median(diff)))),
                       model='near each shadow the flat is multiplied by 1 - depth_exact / (1 + exp((r - radius_bins) / edge_bins)), r = distance (in 2 x 2 plane-px bins: X / 2 + 0.25, Y / 2 + 0.25) from centre_bins, within radius_bins + 10 edge_bins + 4 bins; 1 elsewhere',
                       shadows=shadows, of_8_october_not_in_this_flat=not8, of_tonights_m33_stack_not_in_this_flat=notm, candidates_turned_down=turned_down,
                       blind_area='%.1f%% of the sensor could not be searched for the modelled shadows (8 px blocks where the galaxy or a star\'s surroundings hid the sky in either half)' % (100 * (1 - seen_wide[inner].mean())))
    print('dust, modelled: %d shadows; deepest applied %.3f; the two halves differ by %.4f rms on blocks; not searchable: %.1f%% of the sensor' % (len(shadows), rec['dust']['deepest_applied'], rec['dust']['halves_robust_rms_difference_blocks'], 100 * (1 - seen_wide[inner].mean())))
    for s_ in shadows: print('   shadow at plane px', s_['plane_px'], 'depth %.3f radius %.1f edge %.1f | early %.3f late %.3f | fit rms %.4f | 8 October:' % (s_['depth'], s_['radius_plane_px'], s_['edge_plane_px'], s_['depth_early'], s_['depth_late'], s_['fit_rms']), s_['on_8_october'], '| M33 tonight:', s_['in_tonights_m33_stack'])
    for g in not8: print('   8 October shadow not in this flat:', g)
    for g in notm: print('   shadow of tonight\'s M33 stack not in this flat:', g)
    for g in turned_down: print('   candidate turned down (too small or the halves disagree):', g)
    v = lambda z: (np.clip((np.nan_to_num(z, nan=1.0) - 0.90) / 0.12, 0, 1) * 255).astype(np.uint8)
    view = np.vstack([np.hstack([v(a), v(b)]), np.hstack([v(cv2.resize(dust_full, (nx, ny), interpolation=cv2.INTER_AREA)), v(np.where(okb, remG, np.nan))])])
    cv2.imwrite(W('v_dust_maps.png'), view)
    # ---- the flat, per plane, each on its own pixel positions
    flat = np.empty((4, h2, w2), np.float32)
    for p in range(4):
        ox, oy = OFFS[p]
        flat[p] = radial(fits[p][:3], rho_of(2 * Xp + ox, 2 * Yp + oy, fits[p][6])).astype(np.float32) * dust_full
    np.save(W('flat.npy'), flat)
    rec['applied'] = 'flat[p] = that colour\'s own profile (elliptical: rho^2 = (dx^2 + e dy^2) / 3000^2) x the dust map (only the shadows both halves see); the sky slope and the large-scale remainder are NOT applied'
    rec['flat_range'] = {PLANE_NAMES[p]: [float(flat[p].min()), float(flat[p].max())] for p in range(4)}
    jdump(rec, 'step7_flat.json')
    # ---- for the other targets of the night
    os.makedirs(FLAT_DIR, exist_ok=True)
    np.savez_compressed(os.path.join(FLAT_DIR, 'flat_planes.npz'), **{PLANE_NAMES[p]: flat[p].astype(np.float16) for p in range(4)})
    json.dump(rec, open(os.path.join(FLAT_DIR, 'flat.json'), 'w'), indent=1)
    cv2.imwrite(os.path.join(FLAT_DIR, 'v_flat_check.png'), view)
    P_ = rec['planes']; A8 = rec['against_8_october']
    at = lambda r: int(np.argmin(np.abs(rr - r)))
    lines = [
        'The flat of the night of 12/13 October 2026 (Sony a6000 on the 8SE at f/10, 15 s, ISO 3200)',
        '',
        'Use:   import numpy as np; F = np.load("flat_planes.npz")   # keys R, G1, G2, B, each (2012, 3012) float16',
        '       plane = raw_image_visible[oy::2, ox::2] - 512;  plane / F[name]',
        '       cell offsets (ox, oy): R (0,0), G1 (1,0), G2 (0,1), B (1,1). 1.0 at the sensor centre. Multiplicative, per colour.',
        '       flat.json holds every number (radial coefficients per colour, each dust shadow), so the arrays can be rebuilt.',
        '',
        'How it was made (hack/stacks/2026-10-12/ngc891/step7_flat.py in the observatory repository):',
        '  A sky flat from the %d frames of the NGC 891 run, %s to %s UTC, %.0f s at ISO %d, the galaxy %s degrees up.' % (len(frames), frames[0]['t'][11:19], frames[-1]['t'][11:19], EXPOSURE_S, ISO, ' to '.join('%.0f' % v for v in rec['made_from']['altitude_deg'] if v is not None) or 'about 85'),
        '  Sky level %s DN (R, G1, G2, B) above black. Files: %s ... %s.' % (', '.join('%.0f' % v for v in np.median(levels, axis=0)), frames[0]['name'], frames[-1]['name']),
        '  Per frame and colour plane: hot pixels, stars (2.5 sigma above the smooth sky, grown) and the galaxy left out (for the vignetting fit an ellipse of',
        '  %.1f x %.1f arcmin semi-axes at its plate-solved place, for the dust search %.1f x %.1f); divided by the frame\'s own central sky level;' % (*jload('step6_solve_ref.json')['mask_semi_axes_arcmin'], *TIGHT),
        '  8 x 8 px block medians; the median over the frames without registration.',
        '  Vignetting: per colour, k (1 + a2 rho^2 + a4 rho^4 + a6 rho^6) x (a linear sky slope), rho = sqrt(dx^2 + e dy^2) / 3000 sensor px',
        '  (e lets the fall-off differ between the sensor\'s long and short sides; e = 1 is a plain radial profile);',
        '  only that profile is in the flat. Dust: the green remainder at 2 x 2 px, smoothed (Gaussian 6 px), over its own large scale;',
        '  where all frames, the first half and the second half each show a shadow deeper than 2% (the field moved 50 px between',
        '  the halves, the dust did not) the flat carries the measured shadow; it is exactly the profile everywhere else.',
        '',
        'Numbers:',
    ] + ['  %-2s  a2 a4 a6 = %+.4f %+.4f %+.4f  e = %.3f   flat at the ends of the long side %.3f, of the short side %.3f, corner %.3f   fit rms %.4f   sky slope (not applied) %+.4f %+.4f' % (
            n, *P_[n]['applied_a2_a4_a6'], P_[n]['applied_e'], *P_[n]['applied_at_long_edge_short_edge_corner'], P_[n]['fit_rms'], *P_[n]['sky_slope_gx_gy_not_applied']) for n in PLANE_NAMES] + [
        '  Dust: a measured map (not a model): %d shadows, %.1f%% of the sensor, the deepest %.1f%%; exactly 1 elsewhere. Not searched: %.1f%% of the sensor (under the galaxy, and where a star hid the sky in 4 frames of 10).' % (rec['dust_measured']['shadows'], 100 * rec['dust_measured']['area_fraction'], 100 * rec['dust_measured']['deepest'], 100 * rec['dust_measured']['not_searched_fraction']) if DUST_MEASURED else '  Dust: %d modelled shadows.' % len(shadows),
        '  The 13 largest are also fitted as discs and compared with 8 October and tonight\'s M33 stack in flat.json (dust.shadows).',
        '',
        'Against the 8 October radial profile (the one tonight\'s M33 stack used for all four planes; mean of that night\'s green fits).',
        'For this comparison tonight\'s frames were also fitted with a plain radial profile (e = 1), as 8 October was:',
        '  r (sensor px)      ' + ''.join('%8d' % r for r in (500, 1000, 1500, 2000, 2500, 3000, 3600)),
        '  8 October          ' + ''.join('%8.3f' % prof8(r) for r in (500, 1000, 1500, 2000, 2500, 3000, 3600)),
        '  tonight, green     ' + ''.join('%8.3f' % gmean[at(r)] for r in (500, 1000, 1500, 2000, 2500, 3000, 3600)),
    ] + ['  tonight, %-2s        ' % n + ''.join('%8.3f' % P_[n]['profile'][at(r)] for r in (500, 1000, 1500, 2000, 2500, 3000, 3600)) for n in PLANE_NAMES] + [
        '  Green agrees with 8 October within %.3f everywhere on the sensor (rms %.4f inside r = 2000 px); corner %.3f tonight against %.3f.' % (A8['green_max_abs_difference'], A8['green_rms_difference_inside_2000px'], A8['corner_tonight_green'], A8['corner_8_october']),
        '  Red and blue against the 8 October green profile: max %.3f and %.3f (corner %+.3f and %+.3f).' % (P_['R']['minus_8_october_max_abs'], P_['B']['minus_8_october_max_abs'], P_['R']['minus_8_october_at_corner'], P_['B']['minus_8_october_at_corner']),
        '',
        '  The plain radial profile does not describe this sensor well: against tonight\'s sky it leaves a pattern of %.1f%% rms (%.3f to %.3f:' % (100 * rec['large_scale_remainder_green']['radial_only']['rms'], rec['large_scale_remainder_green']['radial_only']['min'], rec['large_scale_remainder_green']['radial_only']['max']),
        '  the middle and the ends of the short side low, the ends of the long side high). With e free the remainder is %.1f%% rms (%.3f to %.3f).' % (100 * rec['large_scale_remainder_green']['applied_model']['rms'], rec['large_scale_remainder_green']['applied_model']['min'], rec['large_scale_remainder_green']['applied_model']['max']),
        '  So a stack flat-fielded with the 8 October profile carries that pattern times its sky (for a sky of 80 DN, up to about 4 DN).',
        '',
        'Know before using:',
        '  * Red is the weak plane: its sky is %.0f DN, under 2 electrons a pixel. Its plain radial profile is steeper than green\'s (corner %.2f against %.2f),' % (np.median(levels, axis=0)[0], P_['R']['corner_value'], A8['corner_tonight_green']),
        '    as on 8 October (corner 0.49 and 0.63 for red skies of 16 and 38 DN). Three skies, three red profiles, steeper the fainter the sky: that is what a',
        '    constant of about -6 DN in the red plane would do (black level 512 a little too high for red), not the optics. Not proven: there are no darks.',
        '  * One sky only (one run), so a per-colour difference between the profiles may partly be an additive term (a black-level',
        '    error of 1 DN is 5% of the red sky) and not the optics. Per colour is what makes each colour\'s sky level here.',
        '    If a target\'s colours tilt towards the corners, use the green profile for all four planes: 0.5 x (G1 + G2).',
        '  * Dust under the galaxy (the middle of the sensor) could not be seen: shadows that tonight\'s M33 stack or 8 October',
        '    found and this flat does not carry are listed in flat.json (dust.of_tonights_m33_stack_not_in_this_flat, dust.of_8_october_not_in_this_flat).',
        '  * Dust moves: check a shadow against your own frames before trusting it (flat.json has place, depth and radius of each).',
        '  * v_flat_check.png: top, the small-scale green remainder of the early and the late half (0.90 black to 1.02 white, 8 px blocks);',
        '    bottom left the dust map applied, bottom right the whole remainder (median flat / fitted model; the galaxy\'s ellipse is blank).',
    ]
    open(os.path.join(FLAT_DIR, 'README.txt'), 'w').write('\n'.join(lines) + '\n')
    print('flat range', {k: [round(x, 3) for x in v_] for k, v_ in rec['flat_range'].items()}, '| written to', FLAT_DIR, '(%.1f MB)' % (os.path.getsize(os.path.join(FLAT_DIR, 'flat_planes.npz')) / 1e6))
