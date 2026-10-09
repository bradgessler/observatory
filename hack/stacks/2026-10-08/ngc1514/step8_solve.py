"""Step 8: is it the thing? Where the stack lies on the sky, and where NGC 1514's catalogue position falls in it.

Stars on the stack's green (the smooth light taken off as in step 2), written as a FITS image for astrometry.net:
image2xy finds the sources, solve-field matches them to the 2MASS (4204-4207) and Tycho-2 (4107-4113) index files on
this machine, hinted with NGC 1514's position (2 degree radius) and a pixel scale of 0.70 to 0.85 arcsec. From the solver's
list of matched catalogue stars, each star gets this pipeline's own centroid, and a straight-line map (six numbers)
from stack pixels to the tangent plane about NGC 1514's catalogue position (xi east, eta north, arcsec) is fitted with
3-sigma rejection (a second-order one as a check). The catalogue position of NGC 1514 is put through it and compared with the
centroid of the central star (a 9.4 mag star at the catalogue position; the shell is too faint to centroid). Pixel scale, focal length, which way north is and the image's parity come from it.
Copied from this night's m57/step7_solve.py (adapted there from 2026-10-03/m45/p7_solve.py; fitsmin.py is copied
from there: no astropy here). Changes: the target, and the light centroid is the central star's."""
import os, subprocess
import numpy as np, cv2
from common import *
import fitsmin
from step2_stars import measure

SOLVE = W_('solve'); os.makedirs(SOLVE, exist_ok=True)
ADIR = os.path.expanduser('~/.observatory/astrometry')
CFG = os.path.join(SOLVE, 'ngc1514.cfg')
RA0, DEC0 = TARGET['ra_deg'], TARGET['dec_deg']
PIXEL_UM = 23.5e3 / 6000 * 2                     # one colour cell (2 sensor px); sensor 23.5 mm over 6000 px


def gnomonic(ra, dec, ra0=RA0, dec0=DEC0):
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


if __name__ == '__main__':
    open(CFG, 'w').write('inparallel\ncpulimit 120\nadd_path %s\n' % ADIR + ''.join('index %s\n' % f for f in sorted(os.listdir(ADIR))
                                                                               if f.startswith(('index-4204-', 'index-4205-', 'index-4206-', 'index-4207-', 'index-4107', 'index-4108', 'index-4109', 'index-4110', 'index-4111', 'index-4112', 'index-4113'))))
    st = np.load(W_('stack_mean.npy')); cover = np.load(W_('cover.npy')); N = len(jload('step7.json')['frames'])
    G = (st[1] + st[2]) / 2; ok = cover == N
    G = np.where(ok, G, 0).astype(np.float32)
    BLK = 64; bh, bw = h2 // BLK, w2 // BLK
    blocks = np.median(G[:bh * BLK, :bw * BLK].reshape(bh, BLK, bw, BLK), axis=(1, 3)).astype(np.float32)
    D = G - cv2.resize(cv2.medianBlur(blocks, 3), (w2, h2), interpolation=cv2.INTER_LINEAR)
    D[~ok] = 0
    # own stars on the stack (for centroids)
    sm = cv2.GaussianBlur(D, (0, 0), 2.5); m, s, _ = clipped_stats(sm[ok][::7])
    n_, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m + 8 * s).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, n_):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(D, float(cent[i][0]), float(cent[i][1]))
        if r is None or np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        stars.append(r)
    print('stars on the stack (8 sigma):', len(stars))
    base = os.path.join(SOLVE, 'stack')
    for ext in ('.wcs', '.corr', '.xy', '.fits', '.axy', '.solved', '.match', '.rdls'):
        if os.path.exists(base + ext): os.remove(base + ext)
    sc = 20000.0 / max(float(np.percentile(D[ok], 99.99)), 1.0)
    fitsmin.write_image(base + '.fits', np.clip(D * sc + 1000, 0, 32000))
    subprocess.run(['image2xy', '-O', '-p', '10', '-w', '3', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w2), '--height', str(h2),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '0.70', '--scale-high', '0.85',
           '--ra', '%.4f' % RA0, '--dec', '%.4f' % DEC0, '--radius', '2', '--cpulimit', '120', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none',
           '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(SOLVE, 'solve-field.log'), 'w').write(r.stdout + r.stderr)
    assert os.path.exists(base + '.wcs'), 'no solve:\n' + r.stdout[-3000:] + r.stderr[-2000:]
    hd = fitsmin.read_header(base + '.wcs'); co = fitsmin.read_bintable(base + '.corr')
    fx = co['field_x'] - 1; fy = co['field_y'] - 1                    # FITS pixel (1, 1) is array [0, 0]
    sxy = np.array([[s_['x'], s_['y']] for s_ in stars]); sfl = np.array([s_['flux'] for s_ in stars])
    rows = []
    for i in range(len(fx)):
        d = np.hypot(sxy[:, 0] - fx[i], sxy[:, 1] - fy[i]); j = int(np.argmin(d))
        if d[j] < 3.0: rows.append((sxy[j, 0], sxy[j, 1], float(co['index_ra'][i]), float(co['index_dec'][i]), sfl[j]))
    rows = np.array(rows)
    xi, eta = gnomonic(rows[:, 2], rows[:, 3])
    def fit(order):
        x = (rows[:, 0] - w2 / 2) / 1000; y = (rows[:, 1] - h2 / 2) / 1000
        T = [np.ones(len(x)), x, y] + ([x * x, x * y, y * y] if order == 2 else [])
        A = np.column_stack(T); keep = np.ones(len(rows), bool)
        for _ in range(5):
            cx, *_ = np.linalg.lstsq(A[keep], xi[keep], rcond=None); cy, *_ = np.linalg.lstsq(A[keep], eta[keep], rcond=None)
            res = np.hypot(xi - A @ cx, eta - A @ cy); sd = 1.4826 * np.median(res[keep]); keep = res < 3 * max(sd, 0.05)
        return cx, cy, keep, float(np.sqrt(np.mean(res[keep] ** 2)))
    cx, cy, keep, rms1 = fit(1); _, _, keep2, rms2 = fit(2)
    M = np.array([[cx[1] / 1000, cx[2] / 1000], [cy[1] / 1000, cy[2] / 1000]])     # arcsec per pixel: d(xi, eta) / d(x, y)
    off = np.array([cx[0], cy[0]])
    # NGC 1514's catalogue position (xi = eta = 0) in stack pixels
    pc = np.linalg.solve(M, -off) + np.array([w2 / 2, h2 / 2])
    sc_x = float(np.hypot(*M[:, 0])); sc_y = float(np.hypot(*M[:, 1])); det = float(np.linalg.det(M))
    north_dir = np.linalg.solve(M, [0, 1.0]); east_dir = np.linalg.solve(M, [1.0, 0])
    north_angle = float(np.degrees(np.arctan2(north_dir[0], -north_dir[1])))     # degrees from image up (towards -y), clockwise
    # the central star: windowed centroid on the stack's red plane (green and blue touch the sensor ceiling at its core)
    cs = measure(st[0], pc[0], pc[1]); cxy = np.array([cs['x'], cs['y']])
    # the shell's own light: centroid of the smoothed green between 12 and 90 px from the star (stars masked), as a check
    yy, xx = np.mgrid[0:h2, 0:w2]
    starm = np.zeros((h2, w2), np.uint8)
    for s_ in stars:
        if np.hypot(s_['x'] - pc[0], s_['y'] - pc[1]) > 20 and s_['flux'] > 2000:
            cv2.circle(starm, (int(round(s_['x'])), int(round(s_['y']))), 10, 1, -1)
    starm = starm.astype(bool); Gs = cv2.GaussianBlur(G, (0, 0), 3)
    rr = np.hypot(xx - cxy[0], yy - cxy[1]); a = (rr > 12) & (rr < 90) & ~starm
    wgt = np.clip(Gs[a], 0, None); shell_c = np.array([(wgt * xx[a]).sum() / wgt.sum(), (wgt * yy[a]).sum() / wgt.sum()])
    d_shell = M @ (shell_c - pc)
    d_arcsec = M @ (cxy - pc)
    ra_c, dec_c = ungnomonic(*off)                                       # the stack's centre pixel maps to (cx[0], cy[0])
    focal_mm = PIXEL_UM * 1e-3 / np.radians(np.sqrt(abs(det)) / 3600)
    out = dict(solver=dict(config_indexes='2MASS 4204-4207 and Tycho-2 4107-4113', wcs_crval=[hd.get('CRVAL1'), hd.get('CRVAL2')], wcs_crpix=[hd.get('CRPIX1'), hd.get('CRPIX2')],
                           wcs_cd=[hd.get('CD1_1'), hd.get('CD1_2'), hd.get('CD2_1'), hd.get('CD2_2')], catalogue_matches=int(len(fx))),
               stars_on_stack=len(stars), matched_with_own_centroid=int(len(rows)), used_in_fit=int(keep.sum()), fit_rms_arcsec=rms1, second_order_fit_rms_arcsec=rms2,
               tangent_point=dict(ra=RA0, dec=DEC0), affine_xi_eta_arcsec=dict(cx=cx.tolist(), cy=cy.tolist(), x_y_are='(x - %d) / 1000, (y - %d) / 1000 in stack pixels' % (w2 / 2, h2 / 2)),
               scale_arcsec_per_px=[sc_x, sc_y], scale_arcsec_per_sensor_px=(sc_x + sc_y) / 4, focal_length_mm=float(focal_mm), parity='normal, as the sky looks (det > 0 with x right and y down)' if det > 0 else 'mirror image (det < 0)',
               north_is_deg_clockwise_from_up=north_angle, north_direction_px=(north_dir / np.hypot(*north_dir)).tolist(), east_direction_px=(east_dir / np.hypot(*east_dir)).tolist(),
               stack_centre_ra_dec=[float(ra_c), float(dec_c)],
               target_catalogue=dict(ra=RA0, dec=DEC0, stack_px=pc.tolist(), sensor_px_of_reference=[2 * pc[0] + 0.5, 2 * pc[1] + 0.5]),
               central_star_centroid=dict(stack_px=cxy.tolist(), plane='R', offset_from_catalogue_arcsec_east_north=d_arcsec.tolist(), offset_arcsec=float(np.hypot(*d_arcsec))),
               shell_light_centroid=dict(stack_px=shell_c.tolist(), ring_px=[12, 90], offset_from_catalogue_arcsec_east_north=d_shell.tolist(), offset_arcsec=float(np.hypot(*d_shell))),
               catalogue=[dict(x=float(r_[0]), y=float(r_[1]), ra=float(r_[2]), dec=float(r_[3]), used=bool(k_)) for r_, k_ in zip(rows, keep)])
    jsave(out, 'step8_solve.json')
    print('catalogue matches %d, with own centroid %d, used %d; rms %.2f arcsec (2nd order %.2f)' % (len(fx), len(rows), keep.sum(), rms1, rms2))
    print('scale %.4f / %.4f arcsec per stack px (%.4f per sensor px); focal length %.0f mm; parity %s; north is %.1f deg clockwise from up' % (sc_x, sc_y, (sc_x + sc_y) / 4, focal_mm, out['parity'], north_angle))
    print('NGC 1514 catalogue at stack px (%.1f, %.1f); the central star at (%.1f, %.1f): %.2f arcsec away (%+.2f E, %+.2f N); the shell\'s light centred %.1f arcsec away (%+.1f E, %+.1f N)' % (*pc, *cxy, np.hypot(*d_arcsec), *d_arcsec, np.hypot(*d_shell), *d_shell))
    print('stack centre RA %.4f Dec %.4f' % (ra_c, dec_c))
