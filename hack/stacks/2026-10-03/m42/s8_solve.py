"""Step 8: where each stack lies on the sky (method of the M31 mosaic run, m7_solve.py).
For each stack: stars with the detector of step 3 (on the green, holes filled with the local smooth light for the
detection only); a plate solution with astrometry.net (image2xy + solve-field against the Tycho-2 index files on
this machine, with a position hint of 2 degrees: nebulosity confuses the star finder), from which the list of
matched catalogue stars is taken; each matched star gets this pipeline's own centroid; then a straight-line
(affine, six numbers) fit from the stack's pixels to the tangent plane about the Trapezium (RA 83.8221,
Dec -5.3911 J2000; xi east, eta north, arcsec). Step 9 refines these fits with the stars the stacks share."""
import json, os, subprocess, sys
import numpy as np, cv2
from common import *
import fitsmin
from s3_stars import detect_image, smooth_light

CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')
SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)
SEL = json.load(open(W('s5_select.json')))
IMAGES = ['deep'] + [k for k in SEL if k not in ('deep', 'short')]


def solve(name, ra0, dec0):
    P = np.load(W(name + '_planes.npy')); G = (P[1] + P[2]) / 2; ok = np.isfinite(G)
    h, w = G.shape
    fill = cv2.blur(np.where(ok, G, 0).astype(np.float32), (201, 201)) / np.maximum(cv2.blur(ok.astype(np.float32), (201, 201)), 1e-3)
    Gf = np.where(ok, G, fill).astype(np.float32)
    stars, nm, zs = detect_image(Gf)
    near_hole = cv2.dilate((~ok).astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
    stars = [s for s in stars if not near_hole[int(round(s['y'])), int(round(s['x']))]]
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
    sxy = np.array([[s['x'], s['y']] for s in stars]); sfl = np.array([s['flux'] for s in stars])
    rows = []
    for i in range(len(fx)):
        d = np.hypot(sxy[:, 0] - fx[i], sxy[:, 1] - fy[i]); j = int(np.argmin(d))
        if d[j] < 3.0: rows.append((sxy[j, 0], sxy[j, 1], float(co['index_ra'][i]), float(co['index_dec'][i]), sfl[j]))
    rows = np.array(rows)
    xi, eta = gnomonic(rows[:, 2], rows[:, 3])
    A = np.column_stack([rows[:, 0], rows[:, 1], np.ones(len(rows))]); keep = np.ones(len(rows), bool)
    for _ in range(4):
        cx, *_ = np.linalg.lstsq(A[keep], xi[keep], rcond=None); cy, *_ = np.linalg.lstsq(A[keep], eta[keep], rcond=None)
        res = np.hypot(xi - A @ cx, eta - A @ cy); sd = 1.4826 * np.median(res[keep]); keep = res < 3 * max(sd, 0.05)
    M = np.array([cx, cy])          # (xi, eta) = M @ (x, y, 1)
    sc_x = float(np.hypot(M[0, 0], M[1, 0])); sc_y = float(np.hypot(M[0, 1], M[1, 1]))
    cen = M @ np.array([w / 2 - 0.5, h / 2 - 0.5, 1.0]); cra, cdec = ungnomonic(cen[0], cen[1])
    out = dict(name=name, size=[w, h], stars_detected=len(stars), catalogue_matches=int(len(fx)), with_own_centroid=int(len(rows)), used_in_fit=int(keep.sum()),
               fit_rms_arcsec=float(np.sqrt(np.mean(res[keep] ** 2))), affine_to_tangent_plane_arcsec=M.tolist(), scale_arcsec_per_half_px=[sc_x, sc_y],
               centre_offset_arcmin_east_north=[float(cen[0] / 60), float(cen[1] / 60)], centre_ra_dec=[float(cra), float(cdec)],
               x_axis_arcmin_per_6000_sensor_px_east_north=[float(M[0, 0] * 3000 / 60), float(M[1, 0] * 3000 / 60)], y_axis_arcmin_per_4000_sensor_px_east_north=[float(M[0, 1] * 2000 / 60), float(M[1, 1] * 2000 / 60)],
               rotation_deg_of_x_axis_from_west=float(np.degrees(np.arctan2(-M[1, 0], -M[0, 0]))),
               solver_wcs=dict(crval=[hd.get('CRVAL1'), hd.get('CRVAL2')], crpix=[hd.get('CRPIX1'), hd.get('CRPIX2')], cd=[hd.get('CD1_1'), hd.get('CD1_2'), hd.get('CD2_1'), hd.get('CD2_2')]),
               catalogue=[dict(x=float(r_[0]), y=float(r_[1]), ra=float(r_[2]), dec=float(r_[3]), used=bool(k_)) for r_, k_ in zip(rows, keep)])
    json.dump(dict(stars=[dict(x=s['x'], y=s['y'], flux=s['flux'], peak=s['peak'], hfr=s['hfr'], elong=s['elong'], nearest=s['nearest'], level=s['level']) for s in stars]), open(W('s8_stars_%s.json' % name), 'w'))
    print('%-7s stars %4d; catalogue matches %3d, fitted %3d, rms %.2f arcsec; scale %.4f / %.4f arcsec per half px; centre %+.2f E %+.2f N arcmin of the Trapezium; 6000 px right = %+.2f E %+.2f N; 4000 px down = %+.2f E %+.2f N arcmin' % (
        name, len(stars), len(fx), keep.sum(), out['fit_rms_arcsec'], sc_x, sc_y, *out['centre_offset_arcmin_east_north'], *out['x_axis_arcmin_per_6000_sensor_px_east_north'], *out['y_axis_arcmin_per_4000_sensor_px_east_north']), flush=True)
    return out


if __name__ == '__main__':
    res = {}
    plan = dict(PANELS_ := {n: (e, nn) for n, e, nn in PANELS})
    for name in IMAGES:
        e, n = plan.get(name, (0.0, 0.0))
        ra0, dec0 = ungnomonic(e * 60, n * 60)
        res[name] = solve(name, float(ra0), float(dec0))
    json.dump(res, open(W('s8_solve.json'), 'w'), indent=1)
    print('plan against plate solution (arcmin east, north of the Trapezium):')
    for name in IMAGES:
        if res[name] and name in plan: c = res[name]['centre_offset_arcmin_east_north']; e, n = plan[name]; print('   %-6s plan %+6.2f %+6.2f  solved %+6.2f %+6.2f  off by %.2f arcmin' % (name, e, n, c[0], c[1], np.hypot(c[0] - e, c[1] - n)))
        elif res[name]: c = res[name]['centre_offset_arcmin_east_north']; print('   %-6s (no plan)            solved %+6.2f %+6.2f' % (name, c[0], c[1]))
