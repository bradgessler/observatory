"""Step 5: which way is north? The 1/60 s frames hold too few stars to solve, so one of the centring pictures of the same field
(15 s, ISO 3200, 08:35:56, DSC00909: the telescope had not been moved since) is plate-solved with astrometry.net (the local Tycho-2
index files), on its green planes (G1 and G2 averaged, 0.776 arcsec per cell). That gives: Almach where the catalogue says
it is (a check that the thing in the frame is the thing), the plate scale, and the rotation of the sensor on the sky, so a
direction measured on the sensor (the companion from the primary) can be turned into a position angle. Mirror check: the solve
says whether east lies anticlockwise of north on the picture (the sky as you see it) or clockwise (a mirror)."""
import subprocess
import numpy as np, cv2, rawpy
import fitsmin
from common import *

CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')
CENTRING = os.environ.get('ALMACH_CENTRING', '20261013-083556-DSC00909.ARW')
SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def xy2rd(wcs, x, y):
    r = run(['wcs-xy2rd', '-w', wcs, '-x', '%.4f' % (x + 1), '-y', '%.4f' % (y + 1)]); a = r.split('RA,Dec (')[1].split(')')[0].split(','); return float(a[0]), float(a[1])


def rd2xy(wcs, ra, dec):
    r = run(['wcs-rd2xy', '-w', wcs, '-r', '%.6f' % ra, '-d', '%.6f' % dec]); a = r.split('pixel (')[1].split(')')[0].split(','); return float(a[0]) - 1, float(a[1]) - 1


if __name__ == '__main__':
    raw = rawpy.imread(os.path.join(NIGHT, CENTRING)).raw_image_visible.astype(np.float32) - BLACK
    a = raw[:raw.shape[0] // 2 * 2, :raw.shape[1] // 2 * 2]; P = planes(a)
    G = 0.5 * (P[1] + P[2]); h, w = G.shape
    fitsmin.write_image(os.path.join(SOLVE, 'centring.fits'), np.clip(G, -300, 30000) + 300)
    run(['image2xy', '-O', '-p', '8', '-w', '3', '-o', os.path.join(SOLVE, 'centring.xy'), os.path.join(SOLVE, 'centring.fits')])
    wcs = os.path.join(SOLVE, 'centring.wcs')
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w), '--height', str(h),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '0.70', '--scale-high', '0.86',
           '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '1.5', '--cpulimit', '90', '--tweak-order', '2',
           '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none', '--corr', 'none', '--wcs', wcs, os.path.join(SOLVE, 'centring.xy')]
    r = subprocess.run(cmd, capture_output=True, text=True); open(os.path.join(SOLVE, 'solve-field.log'), 'w').write(r.stdout + r.stderr)
    if not os.path.exists(wcs): print(r.stdout[-2500:], r.stderr[-1500:]); raise SystemExit('not solved')
    wi = {}
    for line in run(['wcsinfo', wcs]).splitlines():
        k, _, v = line.partition(' ')
        try: wi[k] = float(v)
        except ValueError: wi[k] = v.strip()
    cx, cy = w / 2, h / 2; ra0, de0 = xy2rd(wcs, cx, cy)
    # unit steps on the picture (x right, y down) -> arcsec east, north (small steps near the star)
    ax, ay = rd2xy(wcs, TARGET['ra_deg'], TARGET['dec_deg'])
    def east_north(x, y, dx, dy):
        r0, d0 = xy2rd(wcs, x, y); r1, d1 = xy2rd(wcs, x + dx, y + dy)
        return ((r1 - r0 + 180) % 360 - 180) * np.cos(np.radians(d0)) * 3600, (d1 - d0) * 3600
    ex, nx = east_north(ax, ay, 10, 0); ey, ny = east_north(ax, ay, 0, 10)
    M = np.array([[ex, ey], [nx, ny]]) / 10                  # (east, north) arcsec per cell px step in (x, y)
    det = float(np.linalg.det(M))
    # direction of north on the picture: solve M [dx, dy] = [0, 1]
    n_dir = np.linalg.solve(M, [0, 1]); e_dir = np.linalg.solve(M, [1, 0])
    ang = lambda v: float(np.degrees(np.arctan2(v[0], -v[1])))   # clockwise from up on the picture
    out = dict(centring_frame=CENTRING, solved=True, pixscale_arcsec_per_cell=wi.get('pixscale'), pixscale_arcsec_per_sensor_px=wi.get('pixscale') / 2,
               centre_ra_dec=[ra0, de0], almach_catalogue_at_cell_xy=[ax, ay], matrix_east_north_arcsec_per_cell=M.tolist(),
               north_on_picture_deg_clockwise_from_up=ang(n_dir), east_on_picture_deg_clockwise_from_up=ang(e_dir), determinant=det,
               wcs_file=wcs)
    # a picture is not mirrored when going from north to east is anticlockwise as seen on the screen (x right, y down)
    cross = n_dir[0] * e_dir[1] - n_dir[1] * e_dir[0]        # >0: clockwise on a y-down screen
    out['east_is'] = 'clockwise of north on the picture (mirrored sky)' if cross > 0 else 'anticlockwise of north on the picture (the sky as seen, not mirrored)'
    # the brightest thing at the catalogue position
    Gs = cv2.GaussianBlur(G, (0, 0), 2); xi, yi = int(round(ax)), int(round(ay)); R = 20
    cut = Gs[yi - R:yi + R + 1, xi - R:xi + R + 1]; j = np.unravel_index(cut.argmax(), cut.shape)
    out['brightest_within_20_cells_of_catalogue'] = dict(cell_xy=[xi - R + int(j[1]), yi - R + int(j[0])], offset_arcsec=float(np.hypot(j[1] - R - (ax - xi), j[0] - R - (ay - yi)) * wi.get('pixscale')), peak_dn=float(cut.max()))
    print('solved: %.4f arcsec/cell (%.4f /sensor px); Almach catalogue spot at cell (%.1f, %.1f), brightest thing within 20 cells %.1f arcsec away; north is %.1f deg clockwise from up, east %.1f: %s' % (
        wi.get('pixscale'), wi.get('pixscale') / 2, ax, ay, out['brightest_within_20_cells_of_catalogue']['offset_arcsec'], out['north_on_picture_deg_clockwise_from_up'], out['east_on_picture_deg_clockwise_from_up'], out['east_is']))
    jdump(out, 'step5_solve.json')
