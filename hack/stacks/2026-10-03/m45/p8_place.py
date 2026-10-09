"""Step 8: place the eleven stacks (nine panels, the first try of (0,0), the centre check) on one tangent-plane
grid, and find each one's photometric scale, from stars. Adapted from the M31 mosaic's m8_place.py.

PLACING. Start: each stack's own plate solution (step 7: affine fit to the 2MASS stars astrometry.net matched).
Cross-check and refinement: the stars two stacks share in their overlap. All eleven affine maps (half-grid pixels
-> xi, eta about RA 56.75 Dec +24.20) are solved again in ONE least-squares problem with two kinds of equations:
catalogue stars (map(pixel) = catalogue position, sigma 0.5 arcsec) and shared stars (map_a(pixel_a) =
map_b(pixel_b), sigma 0.2 arcsec), 3-sigma rejection, matched within 2.5 then 1.5 arcsec. Reported per overlap:
shared stars and the rms of their disagreement with the plate solutions alone and after the joint solve.

SCALE. Panels differ in transparency. For each shared star the aperture flux (28 px sensor radius, as everywhere)
in both stacks, in R, G and B (planes multiplied by the as-shot white balance). One multiplier per stack and
colour solved over all overlaps at once in the logarithm, each star weighted by its measured signal-to-noise in
the noisier of the two (floor 2% per star), 3-sigma rejection; stars with any pixel at the ceiling are left out.
The solve fixes only ratios; the unit is set by the clearest stack (the smallest multiplier is made 1).
The GREEN multiplier is the one applied, to all three colours of a stack (thin cloud is grey, and the red and
blue star fluxes are noisier); the red and blue solutions are kept as a check."""
import json, itertools
import numpy as np, cv2
from c import *

IMAGES = PANELS
S7 = json.load(open(W('p7_solve.json'))); F1 = json.load(open(W('p1.json')))['frames']; SEL = json.load(open(W('p5_select.json')))
used_stamps = set(u['stamp'] for k in IMAGES for u in SEL[k]['used'])
wbs = np.array([f['wb'][:3] for f in F1 if f['stamp'] in used_stamps])
WB_R = float(np.median(wbs[:, 0] / wbs[:, 1])); WB_B = float(np.median(wbs[:, 2] / wbs[:, 1]))
print('as-shot white balance over the %d used frames: R x %.4f (%.0f..%.0f / 1024), B x %.4f (%.0f..%.0f / 1024)' % (len(wbs), WB_R, wbs[:, 0].min(), wbs[:, 0].max(), WB_B, wbs[:, 2].min(), wbs[:, 2].max()))
stars = {k: json.load(open(W('p7_stars_%s.json' % k)))['stars'] for k in IMAGES}
M = {k: np.array(S7[k]['affine_to_tangent_plane_arcsec']) for k in IMAGES}
size = {k: S7[k]['size'] for k in IMAGES}
xy = {k: np.array([[s['x'], s['y']] for s in stars[k]]) for k in IMAGES}
fl = {k: np.array([s['flux'] for s in stars[k]]) for k in IMAGES}
sat = {k: np.array([s['saturated'] for s in stars[k]]) for k in IMAGES}
iso = {k: np.array([s['nearest'] for s in stars[k]]) / 2 for k in IMAGES}
cat = {k: [c_ for c_ in S7[k]['catalogue'] if c_['used']] for k in IMAGES}


def proj(k, p, Mk=None):
    Mk = M[k] if Mk is None else Mk
    return np.column_stack([p, np.ones(len(p))]) @ Mk.T


def match(tol):
    pairs = {}
    for a, b in itertools.combinations(IMAGES, 2):
        pa, pb = proj(a, xy[a]), proj(b, xy[b])
        rows = []
        for i in range(len(pa)):
            if iso[a][i] < 12 or sat[a][i]: continue
            d = np.hypot(*(pb - pa[i]).T); j = int(np.argmin(d))
            if d[j] < tol and iso[b][j] >= 12 and not sat[b][j]:
                d2 = np.hypot(*(pa - pb[j]).T)
                if int(np.argmin(d2)) == i: rows.append((i, j))
        if len(rows) >= 5: pairs[(a, b)] = rows
    return pairs


def joint(pairs, sig_c=0.5, sig_s=0.2):
    idx = {k: i for i, k in enumerate(IMAGES)}; n = len(IMAGES)
    newM = {}
    rows_A, rows_bx, rows_by = [], [], []
    for k in IMAGES:
        cxi, ceta = gnomonic(np.array([c_['ra'] for c_ in cat[k]]), np.array([c_['dec'] for c_ in cat[k]]))
        for c_, x_, y_ in zip(cat[k], cxi, ceta):
            r = np.zeros(3 * n); r[3 * idx[k]:3 * idx[k] + 3] = [c_['x'], c_['y'], 1.0]
            rows_A.append(r / sig_c); rows_bx.append(x_ / sig_c); rows_by.append(y_ / sig_c)
    for (a, b), rows in pairs.items():
        for i, j in rows:
            r = np.zeros(3 * n); r[3 * idx[a]:3 * idx[a] + 3] = [xy[a][i, 0], xy[a][i, 1], 1.0]; r[3 * idx[b]:3 * idx[b] + 3] = [-xy[b][j, 0], -xy[b][j, 1], -1.0]
            rows_A.append(r / sig_s); rows_bx.append(0.0); rows_by.append(0.0)
    A = np.array(rows_A); bx = np.array(rows_bx); by = np.array(rows_by); keep = np.ones(len(A), bool)
    for _ in range(4):
        sx, *_ = np.linalg.lstsq(A[keep], bx[keep], rcond=None); sy, *_ = np.linalg.lstsq(A[keep], by[keep], rcond=None)
        res = np.hypot(A @ sx - bx, A @ sy - by); keep = res < 3.0 * max(1.0, 1.4826 * np.median(res[keep]) / 0.8326)
    for k in IMAGES: newM[k] = np.array([sx[3 * idx[k]:3 * idx[k] + 3], sy[3 * idx[k]:3 * idx[k] + 3]])
    return newM


def report(pairs, Ms):
    out = {}
    for (a, b), rows in pairs.items():
        pa = proj(a, xy[a][[i for i, j in rows]], Ms[a]); pb = proj(b, xy[b][[j for i, j in rows]], Ms[b])
        d = pa - pb; r = np.hypot(*d.T); good = r < max(3 * 1.4826 * np.median(r), 0.3)
        out['%s-%s' % (a, b)] = dict(shared_stars=len(rows), kept=int(good.sum()), rms_arcsec=float(np.sqrt(np.mean(r[good] ** 2))), median_arcsec=float(np.median(r)), mean_offset_arcsec=[float(d[good, 0].mean()), float(d[good, 1].mean())])
    return out


pairs0 = match(2.5)
before = report(pairs0, M)
M1 = joint(pairs0)
M_backup = dict(M); M.update(M1)
pairs1 = match(1.5)
M2 = joint(pairs1); M.update(M2)
pairs2 = match(1.5)
after = report(pairs2, M)
print('overlap          shared   plate solutions alone: rms (mean offset E, N)      joint solve: rms (mean offset)   [arcsec; 1 half-grid px = %.3f]' % HS)
for key in after:
    b = before.get(key); a = after[key]
    print('  %-12s %5d    %s      %.2f (%+.2f, %+.2f)  [%d stars]' % (key, b['shared_stars'] if b else 0, ('%.2f (%+.2f, %+.2f)' % (b['rms_arcsec'], *b['mean_offset_arcsec'])) if b else '   -   ', a['rms_arcsec'], *a['mean_offset_arcsec'], a['kept']))
catres = {}
for k in IMAGES:
    cxi, ceta = gnomonic(np.array([c_['ra'] for c_ in cat[k]]), np.array([c_['dec'] for c_ in cat[k]]))
    p = proj(k, np.array([[c_['x'], c_['y']] for c_ in cat[k]]))
    r = np.hypot(p[:, 0] - cxi, p[:, 1] - ceta); catres[k] = dict(stars=len(r), rms_arcsec=float(np.sqrt(np.mean(r[r < 3 * 1.4826 * np.median(r)] ** 2))))
    sc = [float(np.hypot(M[k][0, 0], M[k][1, 0])), float(np.hypot(M[k][0, 1], M[k][1, 1]))]
    sk = float(np.degrees(np.arctan2(M[k][1, 0], M[k][0, 0]) - np.arctan2(M[k][1, 1], M[k][0, 1])))
    cen = M[k] @ np.array([size[k][0] / 2 - 0.5, size[k][1] / 2 - 0.5, 1.0])
    catres[k].update(scale_arcsec_per_half_px=sc, angle_between_axes_deg=abs(sk) % 180, centre_offset_arcmin_east_north=[float(cen[0] / 60), float(cen[1] / 60)], x_axis_deg_south_of_west=float(np.degrees(np.arctan2(-M[k][1, 0], -M[k][0, 0]))))
    print('  %-5s against the catalogue after the joint solve: %3d stars, rms %.2f arcsec; scale %.4f / %.4f; angle between axes %.3f deg; centre %+.2f E %+.2f N arcmin; x axis %.2f deg south of west' % (k, len(r), catres[k]['rms_arcsec'], *sc, abs(sk) % 180, cen[0] / 60, cen[1] / 60, catres[k]['x_axis_deg_south_of_west']))

# ---------------- photometric scale ----------------
def planes_rgb(k):
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
    for c_ in range(3):
        img = ch[c_]
        for i in need: fx[i, c_], pk[i, c_] = ap_flux(img, xy[k][i, 0], xy[k][i, 1])
    flux[k] = (fx, pk)
NPIX = {}
for k in IMAGES:
    nz = json.load(open(W('p6_%s.json' % k)))['noise_of_stack_dn_per_half_grid_px']; NPIX[k] = [nz['R'] * WB_R, float(np.hypot(nz['G1'], nz['G2']) / 2), nz['B'] * WB_B]
NAP = np.pi * 14 ** 2; NANN = np.pi * (27 ** 2 - 19 ** 2)
def sig_flux(k, c_): return NPIX[k][c_] * np.sqrt(NAP * (1 + 1.57 * NAP / NANN))
REF = 'p11'
scales = {}; phot_pairs = {}
for c_, cn in enumerate('RGB'):
    others = [k for k in IMAGES if k != REF]; idx = {k: i for i, k in enumerate(others)}; rowsA, rowsb, tags, wgt = [], [], [], []
    for (a, b), rows in pairs2.items():
        for i, j in rows:
            fa, fb = flux[a][0][i, c_], flux[b][0][j, c_]; pa_, pb_ = flux[a][1][i, 1], flux[b][1][j, 1]
            if not (np.isfinite(fa) and np.isfinite(fb)) or fa <= 0 or fb <= 0: continue
            if pa_ > 12000.0 or pb_ > 12000.0: continue
            if min(flux[a][0][i, 1], flux[b][0][j, 1]) < 3000: continue           # bright enough in green in both
            sl = np.sqrt((sig_flux(a, c_) / fa) ** 2 + (sig_flux(b, c_) / fb) ** 2 + 0.02 ** 2)
            if sl > 0.25: continue
            r = np.zeros(len(idx))
            if a != REF: r[idx[a]] = 1.0
            if b != REF: r[idx[b]] = -1.0
            rowsA.append(r); rowsb.append(np.log(fb) - np.log(fa)); tags.append((a, b)); wgt.append(1.0 / sl)
    A = np.array(rowsA); bvec = np.array(rowsb); sw = np.array(wgt); keep = np.ones(len(A), bool)
    for _ in range(5):
        sol, *_ = np.linalg.lstsq(A[keep] * sw[keep, None], bvec[keep] * sw[keep], rcond=None); res = A @ sol - bvec; keep = np.abs(res * sw) < 3 * max(1.0, 1.4826 * np.median(np.abs(res[keep] * sw[keep])))
    raw = dict({REF: 1.0}, **{k: float(np.exp(sol[idx[k]])) for k in others})
    if cn == 'G': norm_key = min(raw, key=lambda k: raw[k])
    scales[cn + '_relative_to_' + REF] = raw
    pp = {}
    for (a, b) in pairs2:
        m = np.array([(ta == a and tb == b) for ta, tb in tags]) & keep
        if m.sum() < 3: continue
        direct = float(np.exp(np.sum(bvec[m] * sw[m] ** 2) / np.sum(sw[m] ** 2)))
        pp['%s-%s' % (a, b)] = dict(stars=int(m.sum()), flux_ratio_b_over_a_weighted=direct, after_scaling_weighted=float(np.exp(np.sum(-res[m] * sw[m] ** 2) / np.sum(sw[m] ** 2))), error_of_that=float(1.0 / np.sqrt(np.sum(sw[m] ** 2)) * max(1.0, 1.4826 * np.median(np.abs(res[m] * sw[m])))),
                                    scatter_per_star=float(1.4826 * np.median(np.abs(res[m] - np.median(res[m])))))
    phot_pairs[cn] = pp
    Aw = A[keep] * sw[keep, None]; cov = np.linalg.inv(Aw.T @ Aw) * max(1.0, 1.4826 * np.median(np.abs(res[keep] * sw[keep]))) ** 2
    scales[cn + '_chi'] = float(1.4826 * np.median(np.abs(res[keep] * sw[keep]))); scales[cn + '_stars'] = int(keep.sum())
    scales[cn + '_sigma_rel'] = dict({REF: 0.0}, **{k: float(np.sqrt(cov[idx[k], idx[k]])) for k in others})
# the unit: the clearest stack (smallest green multiplier) = 1, the same normalisation for the three colours
for cn in 'RGB':
    raw = scales[cn + '_relative_to_' + REF]; n0 = raw[norm_key]
    scales[cn] = {k: raw[k] / n0 for k in IMAGES}
scales['unit'] = 'the clearest stack is %s (multiplier 1); every stack x its multiplier = DN of a 10 s ISO 1600 frame at that stack\'s transparency' % norm_key
print('photometric multipliers (clearest stack %s = 1):' % norm_key)
for k in IMAGES:
    print('  %-5s R %.4f  G %.4f (+-%.4f)  B %.4f   -> transparency of the stack\'s clear frames against the clearest stack: %.3f' % (k, scales['R'][k], scales['G'][k], scales['G_sigma_rel'][k] * scales['G'][k], scales['B'][k], 1.0 / scales['G'][k]))
print('star pairs used: R %d G %d B %d; scatter in units of the expected noise: R %.2f G %.2f B %.2f' % (scales['R_stars'], scales['G_stars'], scales['B_stars'], scales['R_chi'], scales['G_chi'], scales['B_chi']))
print('per overlap: stars, flux ratio b/a measured (green), ratio left after the green multipliers in G (+- error), and in R and B with the same green multipliers')
for key, v in phot_pairs['G'].items():
    a_, b_ = key.split('-'); corr = scales['G'][b_] / scales['G'][a_]
    rr = phot_pairs['R'].get(key); bb = phot_pairs['B'].get(key)
    v['left_in_R_with_green_multiplier'] = None if rr is None else rr['flux_ratio_b_over_a_weighted'] * corr; v['left_in_B_with_green_multiplier'] = None if bb is None else bb['flux_ratio_b_over_a_weighted'] * corr
    print('  %-12s %3d  %.4f  ->  G %.4f +- %.4f   R %s  B %s   scatter per star %.3f' % (key, v['stars'], v['flux_ratio_b_over_a_weighted'], v['after_scaling_weighted'], v['error_of_that'],
          '  -   ' if rr is None else '%.4f' % v['left_in_R_with_green_multiplier'], '  -   ' if bb is None else '%.4f' % v['left_in_B_with_green_multiplier'], v['scatter_per_star']))

# ---------------- the mosaic grid ----------------
PS = round(float(np.mean([catres[k]['scale_arcsec_per_half_px'] for k in IMAGES])), 4)      # arcsec per fine-grid pixel: the half grid's own scale
corners = []
for k in IMAGES:
    w, h = size[k]; c_ = proj(k, np.array([[-0.5, -0.5], [w - 0.5, -0.5], [w - 0.5, h - 0.5], [-0.5, h - 0.5]])); corners.append(c_)
allc = np.vstack(corners)
xi_max, xi_min, eta_max, eta_min = allc[:, 0].max(), allc[:, 0].min(), allc[:, 1].max(), allc[:, 1].min()
X0 = float(np.ceil((xi_max + 30) / PS / 8) * 8); Y0 = float(np.ceil((eta_max + 30) / PS / 8) * 8)      # fine-grid pixel of the mosaic centre: X = X0 - xi / PS, Y = Y0 - eta / PS
Wm = int(np.ceil((X0 - (xi_min - 30) / PS) / 8) * 8); Hm = int(np.ceil((Y0 - (eta_min - 30) / PS) / 8) * 8)
print('fine grid: %d x %d px at %.4f arcsec/px = %.1f x %.1f arcmin; the mosaic centre at pixel (%.1f, %.1f); north up, east left' % (Wm, Hm, PS, Wm * PS / 60, Hm * PS / 60, X0, Y0))
named = {}
for nm, (ra, dec) in NAMED.items():
    xi, eta = gnomonic(ra, dec); inside = []
    for k in IMAGES:
        Minv = np.linalg.inv(np.vstack([M[k], [0, 0, 1]])); p = Minv @ np.array([xi, eta, 1.0]); w, h = size[k]
        if 0 <= p[0] < w and 0 <= p[1] < h: inside.append((k, float(p[0]), float(p[1]), float(min(p[0], p[1], w - 1 - p[0], h - 1 - p[1]))))
    named[nm] = dict(ra=ra, dec=dec, offset_arcmin_east_north=[float(xi / 60), float(eta / 60)], fine_grid_pixel=[float(X0 - xi / PS), float(Y0 - eta / PS)], in_stacks=[dict(stack=i[0], half_grid_px=[i[1], i[2]], px_from_the_edge=i[3]) for i in inside])
    print('  %-9s %+6.1f E %+6.1f N arcmin: in %s' % (nm, xi / 60, eta / 60, ', '.join('%s (%.0f px from its edge)' % (i[0], i[3]) for i in inside) or 'NO STACK'))
json.dump(dict(images=IMAGES, affine_to_tangent_plane_arcsec={k: M[k].tolist() for k in IMAGES}, affine_from_plate_solution_alone={k: M_backup[k].tolist() for k in IMAGES}, size=size,
               overlaps_plate_solutions_alone=before, overlaps_after_joint_solve=after, catalogue_after_joint_solve=catres,
               photometric_multipliers=scales, photometric_pairs=phot_pairs, white_balance=dict(R=WB_R, B=WB_B, raw_range=dict(R=[float(wbs[:, 0].min()), float(wbs[:, 0].max())], B=[float(wbs[:, 2].min()), float(wbs[:, 2].max())])),
               named_stars=named,
               grid=dict(pixel_scale_arcsec=PS, width=Wm, height=Hm, centre_pixel=[X0, Y0], tangent_point_ra_dec=[RA0, DEC0], orientation='north up, east left: X = X0 - xi / scale, Y = Y0 - eta / scale'),
               footprints_arcsec={k: corners[i].tolist() for i, k in enumerate(IMAGES)}), open(W('p8_place.json'), 'w'), indent=1)
