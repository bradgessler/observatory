"""Step 7: where each panel stack lies on the sky (adapted from the M31 mosaic's m7_solve.py).
For each panel: stars with the detector of step 3 on the stack's green (holes filled with the local smooth light
for the detection only; stars with a pixel at the ceiling are flagged); a plate solution with astrometry.net
(image2xy + solve-field, hinted with the planned centre and a 2 degree radius, against this machine's 2MASS index
files of the 4204 series only: they hold about 150 stars per panel, where the Tycho-2 files the night's config
tries first hold about 15, nearly all of them saturated here), from which the list of matched catalogue stars is taken; each matched star gets this pipeline's
own centroid; then a straight-line (affine, six numbers) fit from the panel's half-grid pixels to the mosaic's
tangent plane (gnomonic projection about RA 56.75 Dec +24.20, xi east, eta north, arcsec). Step 8 refines these
fits with the stars the panels share in their overlaps.
The catalogue positions are of epoch 1998 to 2000; the cluster's own stars have moved about 1.3 arcsec since
(49 mas a year), the field stars behind them have not: the absolute placement is good to about an arcsecond."""
import json, os, subprocess, sys
import numpy as np, cv2
from c import *
import fitsmin

SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)
ADIR = os.path.expanduser('~/.observatory/astrometry')
CFG = os.path.join(SOLVE, 'cfg4204.cfg')
open(CFG, 'w').write('inparallel\ncpulimit 60\nadd_path %s\n' % ADIR + ''.join('index %s\n' % f for f in sorted(os.listdir(ADIR)) if f.startswith('index-4204-')))


def solve(name, ra0, dec0):
    P = np.load(W(name + '_planes.npy')); G = (P[1] + P[2]) / 2; ok = np.isfinite(G); sat = np.load(W(name + '_sat.npy'))
    h, w = G.shape
    fill = cv2.blur(np.where(ok, G, 0).astype(np.float32), (201, 201)) / np.maximum(cv2.blur(ok.astype(np.float32), (201, 201)), 1e-3)
    Gf = np.where(ok, G, fill).astype(np.float32)
    Pf = np.where(np.isfinite(P), P, 0)
    stars, nm, zs = detect_image(Gf, Pf)
    near_hole = cv2.dilate((~ok).astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
    satd = cv2.dilate(sat.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    stars = [s for s in stars if not near_hole[int(round(s['y'])), int(round(s['x']))]]
    for s in stars: s['saturated'] = bool(s['saturated'] or satd[int(round(s['y'])), int(round(s['x']))])
    D = Gf - smooth_light(Gf)
    small = cv2.resize(D, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    small = cv2.medianBlur(small, 3)
    sc = 20000.0 / max(float(np.percentile(small, 99.99)), 1.0)
    base = os.path.join(SOLVE, name)
    for ext in ('.wcs', '.corr', '.xy', '.axy', '.fits'):
        if os.path.exists(base + ext): os.remove(base + ext)
    fitsmin.write_image(base + '.fits', np.clip(small * sc + 1000, 0, 32000))
    subprocess.run(['image2xy', '-O', '-p', '10', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w // 2), '--height', str(h // 2),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'degwidth', '--scale-low', '0.5', '--scale-high', '0.8',
           '--ra', '%.4f' % ra0, '--dec', '%.4f' % dec0, '--radius', '2', '--cpulimit', '60', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none',
           '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(base + '.wcs'):
        print(name, 'NO SOLVE'); print(r.stdout[-2000:], r.stderr[-2000:]); return None
    hd = fitsmin.read_header(base + '.wcs'); co = fitsmin.read_bintable(base + '.corr')
    fx = 2 * (co['field_x'] - 1) + 0.5; fy = 2 * (co['field_y'] - 1) + 0.5
    sxy = np.array([[s['x'], s['y']] for s in stars]); sfl = np.array([s['flux'] for s in stars]); ssat = np.array([s['saturated'] for s in stars])
    rows = []
    for i in range(len(fx)):
        d = np.hypot(sxy[:, 0] - fx[i], sxy[:, 1] - fy[i]); j = int(np.argmin(d))
        if d[j] < 3.0 and not ssat[j]: rows.append((sxy[j, 0], sxy[j, 1], float(co['index_ra'][i]), float(co['index_dec'][i]), sfl[j]))
    rows = np.array(rows)
    xi, eta = gnomonic(rows[:, 2], rows[:, 3])
    A = np.column_stack([rows[:, 0], rows[:, 1], np.ones(len(rows))]); keep = np.ones(len(rows), bool)
    for _ in range(4):
        cx, *_ = np.linalg.lstsq(A[keep], xi[keep], rcond=None); cy, *_ = np.linalg.lstsq(A[keep], eta[keep], rcond=None)
        res = np.hypot(xi - A @ cx, eta - A @ cy); sd = 1.4826 * np.median(res[keep]); keep = res < 3 * max(sd, 0.05)
    M = np.array([cx, cy])          # (xi, eta) = M @ (x, y, 1)
    sc_x = float(np.hypot(M[0, 0], M[1, 0])); sc_y = float(np.hypot(M[0, 1], M[1, 1]))
    cen = M @ np.array([w / 2 - 0.5, h / 2 - 0.5, 1.0]); cra, cdec = ungnomonic(cen[0], cen[1])
    out = dict(name=name, size=[w, h], stars_detected=len(stars), stars_saturated=int(ssat.sum()), catalogue_matches=int(len(fx)), with_own_centroid=int(len(rows)), used_in_fit=int(keep.sum()),
               fit_rms_arcsec=float(np.sqrt(np.mean(res[keep] ** 2))), affine_to_tangent_plane_arcsec=M.tolist(), scale_arcsec_per_half_px=[sc_x, sc_y],
               centre_offset_arcmin_east_north=[float(cen[0] / 60), float(cen[1] / 60)], centre_ra_dec=[float(cra), float(cdec)],
               x_axis_arcmin_per_6000_sensor_px_east_north=[float(M[0, 0] * 3000 / 60), float(M[1, 0] * 3000 / 60)], y_axis_arcmin_per_4000_sensor_px_east_north=[float(M[0, 1] * 2000 / 60), float(M[1, 1] * 2000 / 60)],
               rotation_deg_of_x_axis_south_of_west=float(np.degrees(np.arctan2(-M[1, 0], -M[0, 0]))),
               solver_wcs=dict(crval=[hd.get('CRVAL1'), hd.get('CRVAL2')], crpix=[hd.get('CRPIX1'), hd.get('CRPIX2')], cd=[hd.get('CD1_1'), hd.get('CD1_2'), hd.get('CD2_1'), hd.get('CD2_2')]),
               catalogue=[dict(x=float(r_[0]), y=float(r_[1]), ra=float(r_[2]), dec=float(r_[3]), used=bool(k_)) for r_, k_ in zip(rows, keep)])
    json.dump(dict(stars=[dict(x=s['x'], y=s['y'], flux=s['flux'], peak=s['peak'], hfr=s['hfr'], elong=s['elong'], nearest=s['nearest'], level=s['level'], saturated=s['saturated'], plane_max=s['plane_max']) for s in stars]), open(W('p7_stars_%s.json' % name), 'w'))
    print('%-5s stars %4d (%d saturated); catalogue matches %3d, fitted %3d, rms %.2f arcsec; scale %.4f / %.4f arcsec per half px; centre %+.2f E %+.2f N arcmin; 6000 px right = %+.2f E %+.2f N; 4000 px down = %+.2f E %+.2f N arcmin; x axis %.2f deg S of W' % (
        name, len(stars), ssat.sum(), len(fx), keep.sum(), out['fit_rms_arcsec'], sc_x, sc_y, *out['centre_offset_arcmin_east_north'], *out['x_axis_arcmin_per_6000_sensor_px_east_north'], *out['y_axis_arcmin_per_4000_sensor_px_east_north'], out['rotation_deg_of_x_axis_south_of_west']), flush=True)
    return out


if __name__ == '__main__':
    res = {}
    for name, e, n in PLAN:
        ra0, dec0 = ungnomonic(e * 60, n * 60)
        res[name] = solve(name, float(ra0), float(dec0))
    json.dump(res, open(W('p7_solve.json'), 'w'), indent=1)
    print('plan against plate solution (arcmin east, north of the mosaic centre):')
    for name, e, n in PLAN:
        if res[name]: c_ = res[name]['centre_offset_arcmin_east_north']; print('   %-5s plan %+6.1f %+6.1f  solved %+6.2f %+6.2f  off by %.2f arcmin' % (name, e, n, c_[0], c_[1], np.hypot(c_[0] - e, c_[1] - n)))
