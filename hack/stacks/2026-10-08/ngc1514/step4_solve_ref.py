"""Step 4: is it the thing? Plate-solve the reference frame alone (before any stacking) with astrometry.net and find
NGC 1514's catalogue position in it, so that the steps after this one know where the nebula is (local transparency,
the sky ring) without judging by eye.

The reference frame's green planes (hot pixels already repaired in step 1), 3 x 3 median, 2 x 2 mean (1.55 arcsec per px,
as the box solves), a smooth background from 8 x 8 block means taken off; image2xy finds the sources; solve-field with
this machine's Tycho-2 / 2MASS index files, hinted with NGC 1514's position (2 degree radius), scale 1.40 to 1.70 arcsec
per px. The catalogue position goes through the WCS (wcs-rd2xy) to sensor px of the RAW (raw_image_visible, sensor
orientation, EXIF orientation ignored): sensor = 4 * (FITS x - 1) + 1.5 for the 2 x 2 mean of the plane grid.
The brightest thing within 15 arcsec of that position should be the 9.4 mag central star: it is found and measured.
Adapted from this night's m76/step1_solve.py."""
import os, re, subprocess
import numpy as np, cv2
from common import *
import fitsmin
from step2_stars import measure

CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')


def wcs_rd2xy(wcs, ra, dec):
    r = subprocess.run(['wcs-rd2xy', '-w', wcs, '-r', '%.6f' % ra, '-d', '%.6f' % dec], capture_output=True, text=True, check=True)
    m = re.search(r'pixel \(([-\d.e+]+), ([-\d.e+]+)\)', r.stdout)
    return float(m.group(1)), float(m.group(2))


def wcs_xy2rd(wcs, x, y):
    r = subprocess.run(['wcs-xy2rd', '-w', wcs, '-x', '%.4f' % x, '-y', '%.4f' % y], capture_output=True, text=True, check=True)
    m = re.search(r'RA,Dec \(([-\d.e+]+), ([-\d.e+]+)\)', r.stdout)
    return float(m.group(1)), float(m.group(2))


def wcsinfo(wcs):
    r = subprocess.run(['wcsinfo', wcs], capture_output=True, text=True, check=True)
    d = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(' ')
        try: d[k] = float(v)
        except ValueError: d[k] = v.strip()
    return d


if __name__ == '__main__':
    REF = jload('step3_transforms.json')['reference']
    P = np.load(os.path.join(WORK, 'planes', REF + '.npy'))
    G = cv2.medianBlur(((P[1] + P[2]) / 2).astype(np.float32), 3)
    Gb = G.reshape(h2 // 2, 2, w2 // 2, 2).mean((1, 3)); BH, BW = Gb.shape
    bg = cv2.blur(cv2.medianBlur(cv2.resize(Gb, (BW // 8, BH // 8), interpolation=cv2.INTER_AREA), 5), (9, 9))
    D = Gb - cv2.resize(bg, (BW, BH), interpolation=cv2.INTER_LINEAR)
    sc = 20000.0 / max(float(np.percentile(D, 99.99)), 1.0)
    SOLVE = W_('solve'); os.makedirs(SOLVE, exist_ok=True); base = os.path.join(SOLVE, 'ref_' + REF)
    for ext in ('.wcs', '.corr', '.xy', '.axy', '.fits', '.solved', '.match', '.rdls'):
        if os.path.exists(base + ext): os.remove(base + ext)
    fitsmin.write_image(base + '.fits', np.clip(D * sc + 1000, 0, 32000))
    subprocess.run(['image2xy', '-O', '-p', '8', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(BW), '--height', str(BH),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '1.40', '--scale-high', '1.70',
           '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '2', '--cpulimit', '60', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none',
           '--solved', 'none', '--index-xyls', 'none', '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(base + '.log', 'w').write(r.stdout + r.stderr)
    assert os.path.exists(base + '.wcs'), 'no solve:\n' + r.stdout[-3000:]
    info = wcsinfo(base + '.wcs'); co = fitsmin.read_bintable(base + '.corr')
    fx, fy = wcs_rd2xy(base + '.wcs', TARGET['ra_deg'], TARGET['dec_deg'])
    px, py = 2 * (fx - 1) + 0.5, 2 * (fy - 1) + 0.5            # plane grid
    sx, sy = 2 * px + 0.5, 2 * py + 0.5                         # sensor
    r0 = wcs_xy2rd(base + '.wcs', fx, fy); r1 = wcs_xy2rd(base + '.wcs', fx + 100, fy); r2 = wcs_xy2rd(base + '.wcs', fx, fy + 100)
    cosd = np.cos(np.radians(r0[1]))
    J = np.array([[(r1[0] - r0[0]) * cosd, (r2[0] - r0[0]) * cosd], [r1[1] - r0[1], r2[1] - r0[1]]]) * 3600 / 100   # arcsec (east, north) per binned px (x, y)
    Ji = np.linalg.inv(J); north = Ji @ np.array([0, 1.0]); east = Ji @ np.array([1.0, 0]); north /= np.hypot(*north); east /= np.hypot(*east)
    north_angle = float(np.degrees(np.arctan2(north[0], -north[1])))
    mirrored = bool(east[0] * north[1] - east[1] * north[0] < 0)
    # the central star: the brightest star within 15 arcsec of the catalogue position, on the plane grid
    Gp = (P[1] + P[2]) / 2
    best = None
    for dy in range(-10, 11, 2):
        for dx in range(-10, 11, 2):
            m = measure(Gp, px + dx, py + dy)
            if m and np.hypot(m['x'] - px, m['y'] - py) < 15 / (2 * SCALE_GUESS) and (best is None or m['flux'] > best['flux']): best = m
    cs = dict(plane_px=[best['x'], best['y']], sensor_px=[2 * best['x'] + 0.5, 2 * best['y'] + 0.5], flux_dn_green=best['flux'], peak_dn_green=best['peak'],
              offset_from_catalogue_arcsec=float(np.hypot(best['x'] - px, best['y'] - py) * info['pixscale'] / 2),
              planes_peak_dn=[float(P[k, int(round(best['y'])) - 3:int(round(best['y'])) + 4, int(round(best['x'])) - 3:int(round(best['x'])) + 4].max()) for k in range(4)])
    out = dict(reference=REF, solved=True, index_stars_matched=int(len(co['field_x'])), centre_ra_dec=[info.get('ra_center'), info.get('dec_center')],
               pixscale_arcsec_per_binned_px=info.get('pixscale'), pixscale_arcsec_per_sensor_px=info.get('pixscale') / 4, field_deg=[info.get('fieldw'), info.get('fieldh')],
               orientation_deg_astrometry_net=info.get('orientation'), parity=info.get('parity'),
               target=TARGET, target_plane_px=[px, py], target_sensor_px=[sx, sy], target_in_frame=bool(0 <= sx < W and 0 <= sy < H),
               north_on_screen_deg_clockwise_from_up=north_angle, east_vector=east.tolist(), north_vector=north.tolist(), mirrored=mirrored,
               focal_length_mm=float(206.265 * (23.5e3 / 6000) / (info.get('pixscale') / 4)), central_star=cs)
    jsave(out, 'step4_solve_ref.json')
    print(json.dumps(out, indent=1))
