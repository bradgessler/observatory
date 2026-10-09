"""Mosaic step 8: place the six panels and the core stack on one tangent-plane grid, and find each panel's
photometric scale, from stars.

PLACING. Start: each image's own plate solution (step 7: affine fit to the catalogue stars astrometry.net
matched). Cross-check and refinement: the stars two images share in their overlap. All seven affine maps (image
pixels -> xi, eta about the nucleus) are solved again in ONE least-squares problem with two kinds of equations:
catalogue stars (map(pixel) = catalogue position, sigma 0.5 arcsec) and shared stars (map_a(pixel_a) =
map_b(pixel_b), sigma 0.2 arcsec), 3-sigma rejection, matched within 2.5 then 1.5 arcsec. Reported per overlap:
shared stars and the rms of their disagreement with the plate solutions alone and after the joint solve.

SCALE. Panels differ in transparency (and are 30 s against the core's 20 s). For each shared star the aperture
flux (28 px sensor radius, as everywhere) in both images, in R, G and B (panel planes multiplied by the core's
as-shot white balance so that units agree). One multiplier per image and colour, the core held at 1, solved over
all overlaps at once in the logarithm (so that every pair counts the same way round), each star weighted by its
measured signal-to-noise in the noisier of the two images (with a floor of 2% per star), 3-sigma rejection.
The GREEN multiplier is the one applied, to all three colours of a panel (thin cloud is grey, and the red and
blue star fluxes are two to three times noisier); the red and blue solutions are kept as a check."""
import json, itertools
import numpy as np, cv2
from mcommon import *
from m3_stars import smooth_light

IMAGES = ['core', 'p00', 'p10', 'p20', 'p21', 'p11', 'p01']
HS = 2 * SCALE
S7 = json.load(open(W('m7_solve.json')))
core_rec = json.load(open(os.path.join(CORE_DIR, 'm31-core-recipe.json')))
WB_R = core_rec['steps'][[s['step'] for s in core_rec['steps']].index('colour')]['as_shot_multipliers']['R']
WB_B = core_rec['steps'][[s['step'] for s in core_rec['steps']].index('colour')]['as_shot_multipliers']['B']
stars = {k: json.load(open(W('m7_stars_%s.json' % k)))['stars'] for k in IMAGES}
M = {k: np.array(S7[k]['affine_to_tangent_plane_arcsec']) for k in IMAGES}
size = {k: S7[k]['size'] for k in IMAGES}
xy = {k: np.array([[s['x'], s['y']] for s in stars[k]]) for k in IMAGES}
fl = {k: np.array([s['flux'] for s in stars[k]]) for k in IMAGES}
iso = {k: np.array([s['nearest'] for s in stars[k]]) / 2 for k in IMAGES}          # half px to the nearest detected neighbour
cat = {k: [c for c in S7[k]['catalogue'] if c['used']] for k in IMAGES}


def proj(k, p, Mk=None):
    Mk = M[k] if Mk is None else Mk
    return np.column_stack([p, np.ones(len(p))]) @ Mk.T


def match(tol):
    pairs = {}
    for a, b in itertools.combinations(IMAGES, 2):
        pa, pb = proj(a, xy[a]), proj(b, xy[b])
        # only stars of a that fall inside b's frame and the other way round
        rows = []
        for i in range(len(pa)):
            if iso[a][i] < 12: continue
            d = np.hypot(*(pb - pa[i]).T); j = int(np.argmin(d))
            if d[j] < tol and iso[b][j] >= 12:
                d2 = np.hypot(*(pa - pb[j]).T)
                if int(np.argmin(d2)) == i: rows.append((i, j))
        if len(rows) >= 5: pairs[(a, b)] = rows
    return pairs


def joint(pairs, sig_c=0.5, sig_s=0.2):
    idx = {k: i for i, k in enumerate(IMAGES)}; n = len(IMAGES)
    newM = {}
    rows_A, rows_bx, rows_by, tags = [], [], [], []
    for k in IMAGES:
        cxi, ceta = gnomonic(np.array([c['ra'] for c in cat[k]]), np.array([c['dec'] for c in cat[k]]))
        for c, x_, y_ in zip(cat[k], cxi, ceta):
            r = np.zeros(3 * n); r[3 * idx[k]:3 * idx[k] + 3] = [c['x'], c['y'], 1.0]
            rows_A.append(r / sig_c); rows_bx.append(x_ / sig_c); rows_by.append(y_ / sig_c); tags.append(('c', k, None))
    for (a, b), rows in pairs.items():
        for i, j in rows:
            r = np.zeros(3 * n); r[3 * idx[a]:3 * idx[a] + 3] = [xy[a][i, 0], xy[a][i, 1], 1.0]; r[3 * idx[b]:3 * idx[b] + 3] = [-xy[b][j, 0], -xy[b][j, 1], -1.0]
            rows_A.append(r / sig_s); rows_bx.append(0.0); rows_by.append(0.0); tags.append(('s', a, b))
    A = np.array(rows_A); bx = np.array(rows_bx); by = np.array(rows_by); keep = np.ones(len(A), bool)
    for _ in range(4):
        sx, *_ = np.linalg.lstsq(A[keep], bx[keep], rcond=None); sy, *_ = np.linalg.lstsq(A[keep], by[keep], rcond=None)
        res = np.hypot(A @ sx - bx, A @ sy - by); keep = res < 3.0 * max(1.0, 1.4826 * np.median(res[keep]) / 0.8326)
    for k in IMAGES: newM[k] = np.array([sx[3 * idx[k]:3 * idx[k] + 3], sy[3 * idx[k]:3 * idx[k] + 3]])
    return newM


def report(pairs, Ms, label):
    out = {}
    for (a, b), rows in pairs.items():
        pa = proj(a, xy[a][[i for i, j in rows]], Ms[a]); pb = proj(b, xy[b][[j for i, j in rows]], Ms[b])
        d = pa - pb; r = np.hypot(*d.T); good = r < max(3 * 1.4826 * np.median(r), 0.3)
        out['%s-%s' % (a, b)] = dict(shared_stars=len(rows), kept=int(good.sum()), rms_arcsec=float(np.sqrt(np.mean(r[good] ** 2))), median_arcsec=float(np.median(r)), mean_offset_arcsec=[float(d[good, 0].mean()), float(d[good, 1].mean())])
    return out


pairs0 = match(2.5)
before = report(pairs0, M, 'plate solutions alone')
M1 = joint(pairs0)
M_backup = dict(M); M.update(M1)
pairs1 = match(1.5)
M2 = joint(pairs1); M.update(M2)
pairs2 = match(1.5)
after = report(pairs2, M, 'joint solve')
print('overlap                shared   plate solutions alone: rms (mean offset E, N)      joint solve: rms   [arcsec; 1 mosaic px = %.3f]' % HS)
for key in after:
    b = before.get(key); a = after[key]
    print('  %-12s %5d    %s      %.2f (%+.2f, %+.2f)  [%d stars]' % (key, b['shared_stars'] if b else 0, ('%.2f (%+.2f, %+.2f)' % (b['rms_arcsec'], *b['mean_offset_arcsec'])) if b else '   -   ', a['rms_arcsec'], *a['mean_offset_arcsec'], a['kept']))
catres = {}
for k in IMAGES:
    cxi, ceta = gnomonic(np.array([c['ra'] for c in cat[k]]), np.array([c['dec'] for c in cat[k]]))
    p = proj(k, np.array([[c['x'], c['y']] for c in cat[k]]))
    r = np.hypot(p[:, 0] - cxi, p[:, 1] - ceta); catres[k] = dict(stars=len(r), rms_arcsec=float(np.sqrt(np.mean(r[r < 3 * 1.4826 * np.median(r)] ** 2))))
    sc = [float(np.hypot(M[k][0, 0], M[k][1, 0])), float(np.hypot(M[k][0, 1], M[k][1, 1]))]
    sk = float(np.degrees(np.arctan2(M[k][1, 0], M[k][0, 0]) - np.arctan2(M[k][1, 1], M[k][0, 1])))
    cen = M[k] @ np.array([size[k][0] / 2 - 0.5, size[k][1] / 2 - 0.5, 1.0])
    print('  %-6s against the catalogue after the joint solve: %3d stars, rms %.2f arcsec; scale %.4f / %.4f; angle between axes %.3f deg; centre %+.2f E %+.2f N arcmin; x axis %.2f deg south of west' % (k, len(r), catres[k]['rms_arcsec'], *sc, abs(sk), cen[0] / 60, cen[1] / 60, np.degrees(np.arctan2(-M[k][1, 0], -M[k][0, 0]))))

# ---------------- photometric scale ----------------
def planes_rgb(k):
    if k == 'core': c = np.load(W('core_rgb.npy')); return [c[:, :, 0], c[:, :, 1], c[:, :, 2]]
    P = np.load(W(k + '_planes.npy')); return [P[0] * WB_R, (P[1] + P[2]) / 2, P[3] * WB_B]

def ap_flux(D, x, y, ap=14):
    xi, yi = int(round(x)), int(round(y)); r = 28
    h, w = D.shape
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return np.nan, np.nan
    t = D[yi - r:yi + r + 1, xi - r:xi + r + 1]
    if not np.isfinite(t).all(): return np.nan, np.nan
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]; rr = np.hypot(xx - x, yy - y)
    lb = float(np.median(t[(rr > 19) & (rr < 27)])); a = rr <= ap
    return float((t[a] - lb).sum()), float(t[a].max())

flux = {}
for k in IMAGES:
    ch = planes_rgb(k); fx = np.full((len(xy[k]), 3), np.nan); pk = np.full((len(xy[k]), 3), np.nan)
    need = sorted(set([i for (a, b), rows in pairs2.items() for i, j in rows if a == k] + [j for (a, b), rows in pairs2.items() for i, j in rows if b == k]))
    for c in range(3):
        img = ch[c]
        for i in need: fx[i, c], pk[i, c] = ap_flux(img, xy[k][i, 0], xy[k][i, 1])
    flux[k] = (fx, pk)
CEIL = dict(core=9000.0)   # peak above which a star may be flat-topped in single frames (panels: 30 s frames, scaled)
# noise of one half-grid pixel of each image, per colour in these units (for the weights): panels from step 6's half-stacks, the core from its recipe (2 x 2 binned stack)
NPIX = {}
for k in IMAGES:
    if k == 'core':
        nb = core_rec['numbers']['noise']['binned_2x2']['stack_white_balanced']; NPIX[k] = [nb['R'], nb['G'], nb['B']]
    else:
        nz = json.load(open(W('m6_%s.json' % k)))['noise_of_stack_dn_per_half_grid_px']; NPIX[k] = [nz['R'] * WB_R, float(np.hypot(nz['G1'], nz['G2']) / 2), nz['B'] * WB_B]
NAP = np.pi * 14 ** 2; NANN = np.pi * (27 ** 2 - 19 ** 2)
def sig_flux(k, c): return NPIX[k][c] * np.sqrt(NAP * (1 + 1.57 * NAP / NANN))       # aperture sum + the ring's median (1.57 = pi / 2)
scales = {}; phot_pairs = {}
for c, cn in enumerate('RGB'):
    idx = {k: i for i, k in enumerate(IMAGES[1:])}; rowsA, rowsb, tags, wgt = [], [], [], []
    for (a, b), rows in pairs2.items():
        for i, j in rows:
            fa, fb = flux[a][0][i, c], flux[b][0][j, c]; pa_, pb_ = flux[a][1][i, 1], flux[b][1][j, 1]
            if not (np.isfinite(fa) and np.isfinite(fb)) or fa <= 0 or fb <= 0: continue
            if pa_ > CEIL.get(a, 12000.0) or pb_ > CEIL.get(b, 12000.0): continue
            if min(flux[a][0][i, 1], flux[b][0][j, 1]) < 6000: continue           # bright enough in green in both
            sl = np.sqrt((sig_flux(a, c) / fa) ** 2 + (sig_flux(b, c) / fb) ** 2 + 0.02 ** 2)
            if sl > 0.25: continue
            r = np.zeros(len(idx))
            if a != 'core': r[idx[a]] = 1.0
            if b != 'core': r[idx[b]] = -1.0
            rowsA.append(r); rowsb.append(np.log(fb) - np.log(fa)); tags.append((a, b)); wgt.append(1.0 / sl)
    A = np.array(rowsA); bvec = np.array(rowsb); sw = np.array(wgt); keep = np.ones(len(A), bool)
    for _ in range(5):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], bvec[keep] * sw[keep], rcond=None); res = A @ sol - bvec; keep = np.abs(res * sw) < 3 * max(1.0, 1.4826 * np.median(np.abs(res[keep] * sw[keep])))
    scales[cn] = dict(core=1.0, **{k: float(np.exp(sol[idx[k]])) for k in IMAGES[1:]})
    # how well each pair agrees after the solve, and what the pair alone would say
    pp = {}
    for (a, b) in pairs2:
        m = np.array([(ta == a and tb == b) for ta, tb in tags]) & keep
        if m.sum() < 3: continue
        direct = float(np.exp(np.sum(bvec[m] * sw[m] ** 2) / np.sum(sw[m] ** 2)))        # f_b / f_a, weighted
        pp['%s-%s' % (a, b)] = dict(stars=int(m.sum()), flux_ratio_b_over_a_weighted=direct, after_scaling_weighted=float(np.exp(np.sum(-res[m] * sw[m] ** 2) / np.sum(sw[m] ** 2))), error_of_that=float(1.0 / np.sqrt(np.sum(sw[m] ** 2)) * max(1.0, 1.4826 * np.median(np.abs(res[m] * sw[m])))),
                                    scatter_per_star=float(1.4826 * np.median(np.abs(res[m] - np.median(res[m])))))
    phot_pairs[cn] = pp
    Aw = A[keep] * sw[keep, None]; cov = np.linalg.inv(Aw.T @ Aw) * max(1.0, 1.4826 * np.median(np.abs(res[keep] * sw[keep]))) ** 2
    scales[cn + '_chi'] = float(1.4826 * np.median(np.abs(res[keep] * sw[keep]))); scales[cn + '_stars'] = int(keep.sum())
    scales[cn + '_sigma'] = dict(core=0.0, **{k: float(np.sqrt(cov[idx[k], idx[k]]) * np.exp(sol[idx[k]])) for k in IMAGES[1:]})
print('photometric multipliers (image x multiplier = the core stack\'s units, DN of a clear 20 s frame):')
for k in IMAGES:
    print('  %-6s R %.4f (+-%.4f)  G %.4f (+-%.4f)  B %.4f (+-%.4f)   -> transparency of the panel\'s clear frames against the core\'s clear sky (green, 20 s / 30 s = 0.6667 / multiplier): %.3f' % (
        k, scales['R'][k], scales['R_sigma'][k], scales['G'][k], scales['G_sigma'][k], scales['B'][k], scales['B_sigma'][k], (CORE_EXPOSURE_S / EXPOSURE_S) / scales['G'][k] if k != 'core' else 1.0))
print('star pairs used: R %d G %d B %d; scatter in units of the expected noise: R %.2f G %.2f B %.2f' % (scales['R_stars'], scales['G_stars'], scales['B_stars'], scales['R_chi'], scales['G_chi'], scales['B_chi']))
print('per overlap: stars, flux ratio b/a measured (green), ratio left after the green multipliers in G (+- error), and in R and B with the same green multipliers')
for key, v in phot_pairs['G'].items():
    a_, b_ = key.split('-'); corr = scales['G'][b_] / scales['G'][a_]
    rr = phot_pairs['R'].get(key); bb = phot_pairs['B'].get(key)
    v['left_in_R_with_green_multiplier'] = None if rr is None else rr['flux_ratio_b_over_a_weighted'] * corr; v['left_in_B_with_green_multiplier'] = None if bb is None else bb['flux_ratio_b_over_a_weighted'] * corr
    print('  %-12s %3d  %.4f  ->  G %.4f +- %.4f   R %s  B %s   scatter per star %.3f' % (key, v['stars'], v['flux_ratio_b_over_a_weighted'], v['after_scaling_weighted'], v['error_of_that'],
          '  -   ' if rr is None else '%.4f' % v['left_in_R_with_green_multiplier'], '  -   ' if bb is None else '%.4f' % v['left_in_B_with_green_multiplier'], v['scatter_per_star']))

# ---------------- the mosaic grid ----------------
PS = 0.776      # arcsec per mosaic pixel (the half grid's own scale, 2 x 0.3881, rounded)
corners = []
for k in IMAGES:
    w, h = size[k]; c = proj(k, np.array([[-0.5, -0.5], [w - 0.5, -0.5], [w - 0.5, h - 0.5], [-0.5, h - 0.5]])); corners.append(c)
allc = np.vstack(corners)
xi_max, xi_min, eta_max, eta_min = allc[:, 0].max(), allc[:, 0].min(), allc[:, 1].max(), allc[:, 1].min()
X0 = float(np.ceil((xi_max + 30) / PS / 4) * 4); Y0 = float(np.ceil((eta_max + 30) / PS / 4) * 4)      # mosaic pixel of the nucleus: X = X0 - xi / PS, Y = Y0 - eta / PS
Wm = int(np.ceil((X0 - (xi_min - 30) / PS) / 4) * 4); Hm = int(np.ceil((Y0 - (eta_min - 30) / PS) / 4) * 4)
print('mosaic grid: %d x %d px at %.3f arcsec/px = %.1f x %.1f arcmin; the nucleus at pixel (%.1f, %.1f); north up, east left' % (Wm, Hm, PS, Wm * PS / 60, Hm * PS / 60, X0, Y0))
json.dump(dict(images=IMAGES, affine_to_tangent_plane_arcsec={k: M[k].tolist() for k in IMAGES}, affine_from_plate_solution_alone={k: M_backup[k].tolist() for k in IMAGES}, size=size,
               overlaps_plate_solutions_alone=before, overlaps_after_joint_solve=after, catalogue_after_joint_solve=catres,
               photometric_multipliers=scales, photometric_pairs=phot_pairs, white_balance=dict(R=WB_R, B=WB_B),
               grid=dict(pixel_scale_arcsec=PS, width=Wm, height=Hm, nucleus_pixel=[X0, Y0], tangent_point_ra_dec=[NUC_RA, NUC_DEC], orientation='north up, east left: X = X0 - xi / scale, Y = Y0 - eta / scale'),
               footprints_arcsec={k: corners[i].tolist() for i, k in enumerate(IMAGES)}), open(W('m8_place.json'), 'w'), indent=1)
