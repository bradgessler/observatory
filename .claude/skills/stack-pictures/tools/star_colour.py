"""Star colours calibrated against a catalogue: the per-channel scale (white balance) that makes the stars in a stack the
colour the catalogue says they are.

What it does, on a LINEAR stack in camera RGB (R, mean of G1 and G2, B; sky at zero; any white balance already in it
given as `wb`), with its plate solution:
  1. catalogue: Gaia DR3 stars in the field (catalogue.gaia_field, cached), moved to the night by their proper motions,
     placed on the stack with the plate solution (wcs_tan).
  2. measure: each star's centroid on green (it must sit within MAX_OFFSET px of where the catalogue puts it), then
     aperture photometry in R, G and B (radius R_AP px, sky from the median of an annulus R_IN..R_OUT px, its error from
     the annulus scatter). Left out: stars near the edge or in a masked place (the target), stars with a Gaia neighbour
     that would put more than 2% of its light in the aperture, stars that came near the sensor's ceiling in a frame
     (peak, back in RAW DN, plus the sky over 60% of the ceiling), stars under SNR_MIN in any colour, BP - RP outside
     COLOUR_RANGE or with a doubtful BP/RP (excess factor over 1.3 + 0.06 (BP - RP)^2).
  3. expected colour: BP - RP -> temperature (Mucciarelli & Bellazzini 2020, dwarfs: theta = 5040 / T = 0.4929 +
     0.5092 C - 0.0353 C^2) -> a black body through the CIE 1931 colour matching functions (the multi-lobe fits of
     Wyman, Sloan & Shirley 2013) -> linear sRGB, set so that a star of the Sun's colour (BP - RP = 0.82) is white. The
     reference white is the Sun's colour (G2V), the astronomers' usual choice; a black body is close to a star's colour
     in these broad bands, and nearly exact near the pivot, where most stars and the fit's weight are.
  4. fit: the measured camera RGB of each star times (kR, 1, kB), through the camera's own matrix (as render.py does:
     linear sRGB = RGB_CAM (k * c)), must give the expected ratios R/G and B/G (in log). Weighted by the photometric
     errors (floor 0.02), robust (soft L1), refitted after a 3-sigma clip (sigma at least 0.03), on the stars of BP - RP 0.55 to 1.15 (near
     the Sun's colour, where the model is closest; every star is reported). Only these two numbers: no colour term
     unless the data clearly need one (the residual against BP - RP is reported, not applied).
  5. checks: the scatter before and after; the colour of Sun-like stars (BP - RP 0.72 to 0.92) before and after; the
     residual against BP - RP (a colour term) and against distance from the sensor centre (a colour error in the flat).

Apply: multiply the stack's camera R by kR and B by kB (on top of `wb`) before the matrix and the stretch, i.e. in the
linear stack, before finishing. Nothing else changes.

Inputs:  img (h, w, 3) float linear camera RGB, sky at zero; wb (3) already applied; a TanSip; rgb_xyz_matrix from a RAW
         of the run; optional mask (h, w) bool of places to avoid; sensor_xy(x, y) -> sensor px (for the radial check);
         raw_sky_dn (3) for the ceiling test; the night's date as a year (proper motions).
Outputs: a dict (JSON-able): factors, numbers, and every star used with its measured and expected colour.
Recipe entries: colour_calibration{catalogue{...}, reference_white, model, aperture, rules, candidates, used, clipped,
         factors{R, G, B}, white_balance_before, white_balance_after, residual_rms_mag{before, after},
         sun_like_stars{before, after}, colour_term, radial_term, stars[...]}.

CLI:  python star_colour.py --tif stack.tif --pedestal 1000 --wcs stack.wcs --raw <a RAW of the run> --wb 2.8993 1 1.3482
          [--mask-ellipse x y a b angle] [--year 2026.78] [--out colour.json]"""
import argparse, json, os, sys
import numpy as np
from scipy.optimize import least_squares

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalogue as catm
from wcs_tan import TanSip

R_AP, R_IN, R_OUT = 10.0, 16.0, 26.0
MAX_OFFSET = 2.5
SNR_MIN = 20.0
CLIP_FLOOR = 0.03            # the 3-sigma clip never cuts closer than 3 x this (log units, about 0.03 mag): a few stars that agree well must not clip each other
COLOUR_RANGE = (0.3, 2.0)
FIT_RANGE = (0.55, 1.15)     # the scale is fitted on stars near the Sun's colour, where the black-body model is closest; all stars are reported
SUN_BP_RP = 0.82
CEILING = 15488.0
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
RGB_FROM_XYZ = np.linalg.inv(XYZ_RGB)


def camera_matrix(rgb_xyz):
    """As render.py: linear sRGB from white-balanced camera RGB, rows so that white stays white."""
    cr = np.array(rgb_xyz)[:3] @ XYZ_RGB
    return np.linalg.inv(cr / cr.sum(1)[:, None])


def _g(lam, mu, s1, s2):
    s = np.where(lam < mu, s1, s2)
    return np.exp(-0.5 * ((lam - mu) / s) ** 2)


def cmf(lam):
    """CIE 1931 2-degree colour matching functions, multi-lobe Gaussian fits (Wyman, Sloan & Shirley 2013)."""
    x = 1.056 * _g(lam, 599.8, 37.9, 31.0) + 0.362 * _g(lam, 442.0, 16.0, 26.7) - 0.065 * _g(lam, 501.1, 20.4, 26.2)
    y = 0.821 * _g(lam, 568.8, 46.9, 40.5) + 0.286 * _g(lam, 530.9, 16.3, 31.1)
    z = 1.217 * _g(lam, 437.0, 11.8, 36.0) + 0.681 * _g(lam, 459.0, 26.0, 13.8)
    return x, y, z


def teff_of(bp_rp):
    c = np.asarray(bp_rp, float)
    return 5040.0 / (0.4929 + 0.5092 * c - 0.0353 * c ** 2)


def srgb_of_teff(T):
    lam = np.arange(380.0, 781.0, 2.0)
    x, y, z = cmf(lam)
    T = np.atleast_1d(T)[:, None]
    B = 1.0 / (lam[None] ** 5 * (np.exp(1.4388e7 / (lam[None] * T)) - 1))
    XYZ = np.stack([(B * x).sum(1), (B * y).sum(1), (B * z).sum(1)], 1)
    return XYZ @ RGB_FROM_XYZ.T


def expected_srgb(bp_rp):
    """Linear sRGB of a star of this BP - RP, white (1, 1, 1) for the Sun's colour."""
    e = srgb_of_teff(teff_of(bp_rp)); sun = srgb_of_teff(teff_of(SUN_BP_RP))[0]
    return e / sun


def _phot(img, x, y):
    """Centroid (green) and aperture fluxes of a star near (x, y). None if it cannot be measured."""
    h, w, _ = img.shape; r = int(R_OUT) + 3
    xi, yi = int(round(x)), int(round(y))
    if xi < r or yi < r or xi >= w - r or yi >= h - r: return None
    cut = img[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float64)
    if not np.isfinite(cut).all(): return None
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1].astype(float)
    for _ in range(3):
        d = np.hypot(xx - (x - xi), yy - (y - yi))
        ann = (d >= R_IN) & (d <= R_OUT)
        g = cut[..., 1] - np.median(cut[..., 1][ann]); core = d <= 5
        wgt = np.clip(g[core], 0, None)
        if wgt.sum() <= 0: return None
        x = xi + (wgt * xx[core]).sum() / wgt.sum(); y = yi + (wgt * yy[core]).sum() / wgt.sum()
    d = np.hypot(xx - (x - xi), yy - (y - yi)); ann = (d >= R_IN) & (d <= R_OUT); ap = d <= R_AP
    flux, err, peak = [], [], []
    for c in range(3):
        a = cut[..., c][ann]; sky = np.median(a); s = 1.4826 * np.median(np.abs(a - sky))
        f = float((cut[..., c][ap] - sky).sum()); flux.append(f); err.append(float(s * np.sqrt(ap.sum() * (1 + np.pi / 2 * ap.sum() / ann.sum()))))
        peak.append(float((cut[..., c][d <= 2] - sky).max()))
    return dict(x=float(x), y=float(y), flux=flux, err=err, peak=peak)


def measure(img, wcs, cat, mask=None, year=2026.78, wb=(1, 1, 1), raw_sky_dn=(0, 0, 0)):
    ra, dec = catm.at_epoch(cat, year)
    px, py = wcs.world2pix(ra, dec)
    h, w, _ = img.shape
    inside = (px > R_OUT + 3) & (py > R_OUT + 3) & (px < w - R_OUT - 4) & (py < h - R_OUT - 4)
    gflux = 10 ** (-0.4 * (cat['g'] - 15))
    stars, why = [], dict(edge_or_mask=0, neighbour=0, colour=0, bp_rp_doubtful=0, not_measured=0, offset=0, ceiling=0, snr=0, negative=0)
    idx = np.nonzero(inside)[0]
    for i in idx:
        if mask is not None and mask[int(round(py[i])), int(round(px[i]))]: why['edge_or_mask'] += 1; continue
        c = cat['bp_rp'][i]
        if not np.isfinite(c) or not (COLOUR_RANGE[0] <= c <= COLOUR_RANGE[1]): why['colour'] += 1; continue
        ex = cat['bp_rp_excess'][i]
        if np.isfinite(ex) and ex > 1.3 + 0.06 * c ** 2: why['bp_rp_doubtful'] += 1; continue
        dn = np.hypot(px - px[i], py - py[i]); near = (dn < R_AP + 8) & (dn > 0)
        if near.any() and gflux[near].sum() > 0.02 * gflux[i]: why['neighbour'] += 1; continue
        m = _phot(img, px[i], py[i])
        if m is None: why['not_measured'] += 1; continue
        if np.hypot(m['x'] - px[i], m['y'] - py[i]) > MAX_OFFSET: why['offset'] += 1; continue
        if max(m['peak'][k] / wb[k] + raw_sky_dn[k] for k in range(3)) > 0.6 * CEILING: why['ceiling'] += 1; continue
        if min(m['flux'][k] / max(m['err'][k], 1e-9) for k in range(3)) < SNR_MIN: why['snr'] += 1; continue
        if min(m['flux']) <= 0: why['negative'] += 1; continue
        m.update(source=int(cat['source'][i]), g=float(cat['g'][i]), bp_rp=float(c), catalogue_xy=[float(px[i]), float(py[i])])
        stars.append(m)
    return stars, dict(in_field=int(inside.sum()), left_out=why)


def _resid(k, C, E, M):
    S = (C * np.array([k[0], 1.0, k[1]])[None]) @ M.T
    S = np.clip(S, 1e-9, None)
    return np.stack([np.log(S[:, 0] / S[:, 1]) - np.log(E[:, 0] / E[:, 1]), np.log(S[:, 2] / S[:, 1]) - np.log(E[:, 2] / E[:, 1])], 1)


def fit(stars, M, sensor_xy=None):
    C = np.array([s['flux'] for s in stars]); Er = np.array([s['err'] for s in stars])
    bp = np.array([s['bp_rp'] for s in stars]); E = expected_srgb(bp)
    sig = np.sqrt((Er[:, [0, 2]] / C[:, [0, 2]]) ** 2 + (Er[:, [1]] / C[:, [1]]) ** 2 + 0.02 ** 2)
    infit = (bp >= FIT_RANGE[0]) & (bp <= FIT_RANGE[1])
    keep = infit.copy(); k = np.array([1.0, 1.0])
    for _ in range(4):
        r = least_squares(lambda k_: (_resid(k_, C[keep], E[keep], M) / sig[keep]).ravel(), k, loss='soft_l1', f_scale=1.0)
        k = r.x
        res = _resid(k, C, E, M); rs = np.abs(res - np.median(res[keep], 0)) / np.maximum(1.4826 * np.median(np.abs(res[keep] - np.median(res[keep], 0)), 0), CLIP_FLOOR)
        nk = (rs < 3).all(1) & infit
        if (nk == keep).all(): break
        keep = nk
    # uncertainty of k from the Jacobian of the final fit (on the stars kept), scaled by the residual scatter
    J = r.jac; cov = np.linalg.pinv(J.T @ J) * max(1.0, float(np.sum(r.fun ** 2) / max(len(r.fun) - 2, 1)))
    before = _resid([1.0, 1.0], C, E, M); after = _resid(k, C, E, M)
    mag = 1.0857
    def stats(res, sel):
        return dict(median_mag_R_over_G=round(mag * float(np.median(res[sel, 0])), 4), median_mag_B_over_G=round(mag * float(np.median(res[sel, 1])), 4),
                    rms_mag_R_over_G=round(mag * float(np.std(res[sel, 0])), 4), rms_mag_B_over_G=round(mag * float(np.std(res[sel, 1])), 4),
                    robust_rms_mag_R_over_G=round(mag * 1.4826 * float(np.median(np.abs(res[sel, 0] - np.median(res[sel, 0])))), 4),
                    robust_rms_mag_B_over_G=round(mag * 1.4826 * float(np.median(np.abs(res[sel, 1] - np.median(res[sel, 1])))), 4))
    sun = keep & (bp >= 0.72) & (bp <= 0.92)
    good = (rs < 3).all(1)                                   # every measured star not clipped (also outside the fit range)
    def sun_colour(kk):
        S = (C[sun] * np.array([kk[0], 1.0, kk[1]])[None]) @ M.T
        return dict(stars=int(sun.sum()), median_srgb_R_over_G=round(float(np.median(S[:, 0] / S[:, 1])), 4), median_srgb_B_over_G=round(float(np.median(S[:, 2] / S[:, 1])), 4))
    # colour term and radial term: straight lines through the residuals after the fit
    def line(x, y):
        A = np.stack([np.ones(len(x)), x], 1); co, *_ = np.linalg.lstsq(A, y, rcond=None); rr = y - A @ co
        se = float(np.sqrt(np.sum(rr ** 2) / max(len(x) - 2, 1) / np.sum((x - x.mean()) ** 2)))
        return dict(slope_mag=round(mag * float(co[1]), 4), slope_error_mag=round(mag * se, 4), significance_sigma=round(abs(float(co[1])) / max(se, 1e-12), 1))
    ct = dict(per='mag of residual per mag of BP - RP, all measured stars %.1f to %.1f not clipped' % COLOUR_RANGE, stars=int(good.sum()), R_over_G=line(bp[good] - SUN_BP_RP, after[good, 0]), B_over_G=line(bp[good] - SUN_BP_RP, after[good, 1]))
    out = dict(factors=dict(R=float(k[0]), G=1.0, B=float(k[1])), factor_errors=dict(R=float(np.sqrt(cov[0, 0])), B=float(np.sqrt(cov[1, 1]))),
               candidates=len(stars), in_fit_range=int(infit.sum()), used=int(keep.sum()), clipped=int((infit & ~keep).sum()), fit_range_bp_rp=list(FIT_RANGE),
               residual_before=stats(before, keep), residual_after=stats(after, keep),
               residual_all_stars_before=stats(before, good), residual_all_stars_after=stats(after, good),
               sun_like_stars=dict(rule='BP - RP 0.72 to 0.92, linear sRGB through the camera matrix; white is 1, 1', before=sun_colour([1.0, 1.0]), after=sun_colour(k)),
               colour_term=ct)
    if sensor_xy is not None:
        sx, sy = sensor_xy(np.array([s['x'] for s in stars]), np.array([s['y'] for s in stars]))
        rad = np.hypot(sx - 3011.5, sy - 2011.5) / 1000.0
        out['radial_term'] = dict(per='mag of residual per 1000 sensor px from the sensor centre (stars of the fit)', R_over_G=line(rad[keep], after[keep, 0]), B_over_G=line(rad[keep], after[keep, 1]))
    for i, s in enumerate(stars):
        s.update(used=bool(keep[i]), expected_srgb=[round(float(v), 4) for v in E[i]], resid_mag_before=[round(mag * float(v), 4) for v in before[i]], resid_mag_after=[round(mag * float(v), 4) for v in after[i]])
    return out


def calibrate(img, wcs, rgb_xyz, wb, centre_radec, radius_deg, mask=None, year=2026.78, sensor_xy=None, raw_sky_dn=(0, 0, 0), gmax=17.0, offline=False):
    cat, crec = catm.gaia_field(centre_radec[0], centre_radec[1], radius_deg, gmax, offline=offline)
    M = camera_matrix(rgb_xyz)
    stars, sel = measure(img, wcs, cat, mask, year, wb, raw_sky_dn)
    if len(stars) < 10: raise SystemExit('only %d stars could be measured: no calibration' % len(stars))
    res = fit(stars, M, sensor_xy)
    offs = np.array([[s['x'] - s['catalogue_xy'][0], s['y'] - s['catalogue_xy'][1]] for s in stars])
    res.update(catalogue=crec, reference_white='the Sun\'s colour (Gaia BP - RP %.2f) is white' % SUN_BP_RP,
               model='BP - RP -> T (Mucciarelli & Bellazzini 2020, dwarfs) -> black body -> CIE 1931 (Wyman et al. 2013 fits) -> linear sRGB; measured: camera RGB x (kR, 1, kB) -> render.py camera matrix -> linear sRGB',
               aperture=dict(radius_px=R_AP, annulus_px=[R_IN, R_OUT], centroid_max_offset_px=MAX_OFFSET, snr_min=SNR_MIN, colour_range_bp_rp=list(COLOUR_RANGE), ceiling_rule='peak / wb + sky (RAW DN) under 60%% of %.0f' % CEILING),
               selection=sel, white_balance_before=[float(v) for v in wb], white_balance_after=[float(wb[0] * res['factors']['R']), float(wb[1]), float(wb[2] * res['factors']['B'])],
               catalogue_to_stack_offset_px=dict(median=np.median(offs, 0).round(3).tolist(), rms=float(np.sqrt((offs ** 2).sum(1).mean()))), epoch_year=year, stars=stars)
    return res


def summary(res):
    f = res['factors']; b, a = res['residual_before'], res['residual_after']; sb, sa = res['sun_like_stars']['before'], res['sun_like_stars']['after']
    return ('kR %.4f +- %.4f, kB %.4f +- %.4f from %d stars (%d clipped of %d measured); R/G residual median %+.3f -> %+.3f mag, rms %.3f -> %.3f; B/G median %+.3f -> %+.3f, rms %.3f -> %.3f; '
            'Sun-like stars (%d) sRGB R/G %.3f -> %.3f, B/G %.3f -> %.3f; colour term R/G %+.3f +- %.3f, B/G %+.3f +- %.3f mag/mag' % (
                f['R'], res['factor_errors']['R'], f['B'], res['factor_errors']['B'], res['used'], res['clipped'], res['candidates'],
                b['median_mag_R_over_G'], a['median_mag_R_over_G'], b['rms_mag_R_over_G'], a['rms_mag_R_over_G'], b['median_mag_B_over_G'], a['median_mag_B_over_G'], b['rms_mag_B_over_G'], a['rms_mag_B_over_G'],
                sa['stars'], sb['median_srgb_R_over_G'], sa['median_srgb_R_over_G'], sb['median_srgb_B_over_G'], sa['median_srgb_B_over_G'],
                res['colour_term']['R_over_G']['slope_mag'], res['colour_term']['R_over_G']['slope_error_mag'], res['colour_term']['B_over_G']['slope_mag'], res['colour_term']['B_over_G']['slope_error_mag']))


if __name__ == '__main__':
    import tifffile, rawpy
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tif', required=True); ap.add_argument('--pedestal', type=float, default=0.0); ap.add_argument('--wcs', required=True)
    ap.add_argument('--raw', required=True); ap.add_argument('--wb', type=float, nargs=3, required=True)
    ap.add_argument('--mask-ellipse', type=float, nargs=5, action='append', default=[]); ap.add_argument('--year', type=float, default=2026.78)
    ap.add_argument('--radius', type=float, default=0.42); ap.add_argument('--gmax', type=float, default=17.0); ap.add_argument('--offline', action='store_true')
    ap.add_argument('--out')
    a = ap.parse_args()
    img = tifffile.imread(a.tif).astype(np.float32) - a.pedestal
    wcs = TanSip(a.wcs); h, w, _ = img.shape
    with rawpy.imread(a.raw) as r: rgb_xyz = np.array(r.rgb_xyz_matrix).tolist()
    mask = np.zeros((h, w), bool)
    if a.mask_ellipse:
        yy, xx = np.mgrid[0:h, 0:w]
        for x0, y0, sa, sb, ang in a.mask_ellipse:
            t = np.radians(ang); u = (xx - x0) * np.cos(t) + (yy - y0) * np.sin(t); v = -(xx - x0) * np.sin(t) + (yy - y0) * np.cos(t)
            mask |= (u / sa) ** 2 + (v / sb) ** 2 <= 1
    ra0, dec0 = wcs.pix2world(w / 2, h / 2)
    res = calibrate(img, wcs, rgb_xyz, a.wb, (float(ra0), float(dec0)), a.radius, mask, a.year, gmax=a.gmax, offline=a.offline)
    print(summary(res))
    if a.out: json.dump(res, open(a.out, 'w'), indent=1)
