"""Step 1: is it the thing? Plate-solve single frames (green planes, before any stacking) with astrometry.net and
find M76's catalogue position in each. Solved: the first frame of the run, the reference frame, the last frame of
the run, and the frame flagged settling. Each is solved from its green planes, 3 x 3 median (hot pixels), 2 x 2 mean. Writes solve_<stamp>.{fits,xy,wcs,corr} and step1_solve.json in the work
folder. Positions are given in SENSOR pixels of the RAW (raw_image_visible, sensor orientation, EXIF orientation
ignored): sensor = 2 * plane + 0.5 for the averaged green planes."""
import json, os, re, subprocess
import numpy as np, cv2
from common import *
import fitsmin

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


def solve(stamp, ra0, dec0, radius=2.0):
    fr = [f for f in frame_list() if f['stamp'] == stamp][0]
    P, meta = load_planes(fr['path'])
    G = cv2.medianBlur((P[1] + P[2]) / 2, 3)            # 3 x 3 median: single hot pixels are not stars
    G = G.reshape(PH // 2, 2, PW // 2, 2).mean((1, 3))   # 2 x 2 mean: 1.55 arcsec per px, as the box solves
    BH, BW = G.shape
    bg = cv2.blur(cv2.medianBlur(cv2.resize(G, (BW // 8, BH // 8), interpolation=cv2.INTER_AREA), 5), (9, 9))
    D = G - cv2.resize(bg, (BW, BH), interpolation=cv2.INTER_LINEAR)
    sc = 20000.0 / max(float(np.percentile(D, 99.99)), 1.0)
    base = W('solve_' + stamp)
    for ext in ('.wcs', '.corr', '.xy', '.axy', '.fits', '.solved', '.match', '.rdls'):
        if os.path.exists(base + ext): os.remove(base + ext)
    fitsmin.write_image(base + '.fits', np.clip(D * sc + 1000, 0, 32000))
    subprocess.run(['image2xy', '-O', '-p', '8', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(BW), '--height', str(BH),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '1.40', '--scale-high', '1.70',
           '--ra', '%.4f' % ra0, '--dec', '%.4f' % dec0, '--radius', str(radius), '--cpulimit', '60', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none',
           '--solved', 'none', '--index-xyls', 'none', '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(base + '.wcs'):
        print(stamp, 'NO SOLVE', r.stdout[-600:])
        return dict(stamp=stamp, solved=False, hint_ra_dec=[ra0, dec0], solver_tail=r.stdout[-600:])
    info = wcsinfo(base + '.wcs')
    co = fitsmin.read_bintable(base + '.corr')
    fx, fy = wcs_rd2xy(base + '.wcs', TARGET['ra_deg'], TARGET['dec_deg'])          # FITS pixels, 1-based, on the 2 x 2 binned plane grid
    px, py = 2 * (fx - 1) + 0.5, 2 * (fy - 1) + 0.5                                 # plane grid
    inside = 0 <= px < PW and 0 <= py < PH
    # which way north and east point on the image (x right, y down): from the WCS at the target
    r0 = wcs_xy2rd(base + '.wcs', fx, fy); r1 = wcs_xy2rd(base + '.wcs', fx + 100, fy); r2 = wcs_xy2rd(base + '.wcs', fx, fy + 100)
    cosd = np.cos(np.radians(r0[1]))
    J = np.array([[(r1[0] - r0[0]) * cosd, (r2[0] - r0[0]) * cosd], [r1[1] - r0[1], r2[1] - r0[1]]]) * 3600 / 100   # arcsec (east, north) per px (x, y)
    Ji = np.linalg.inv(J)
    north = Ji @ np.array([0, 1.0]); east = Ji @ np.array([1.0, 0])
    north /= np.hypot(*north); east /= np.hypot(*east)
    north_angle = float(np.degrees(np.arctan2(north[0], -north[1])))      # 0 = up, +90 = right (clockwise on screen)
    mirrored = bool(east[0] * north[1] - east[1] * north[0] < 0)          # a true sky view (seen from below) has east 90 deg counter-clockwise of north on screen
    out = dict(stamp=stamp, solved=True, hint_ra_dec=[ra0, dec0], index_stars_matched=int(len(co['field_x'])),
               centre_ra_dec=[info.get('ra_center'), info.get('dec_center')], pixscale_arcsec_per_plane_px=info.get('pixscale') / 2,
               pixscale_arcsec_per_sensor_px=info.get('pixscale', 0) / 4, field_deg=[info.get('fieldw'), info.get('fieldh')], orientation_deg_astrometry_net=info.get('orientation'),
               parity=info.get('parity'), target_plane_px=[px, py], target_sensor_px=[2 * px + 0.5, 2 * py + 0.5], target_in_frame=inside,
               north_on_screen_deg_clockwise_from_up=north_angle, east_vector=east.tolist(), north_vector=north.tolist(), mirrored=mirrored,
               focal_length_mm=float(206.265 * 3.917 / (info.get('pixscale', 1) / 4)))
    print(json.dumps(out))
    return out


if __name__ == '__main__':
    fl = {f['stamp']: f for f in frame_list()}
    stamps = sorted(fl)
    res = []
    for s in (stamps[0], REF_STAMP, stamps[-2], stamps[-1]):
        ra, dec = fl[s]['pointing_ra_dec']
        res.append(solve(s, ra if ra is not None else TARGET['ra_deg'], dec if dec is not None else TARGET['dec_deg']))
        if not res[-1]['solved'] and s == stamps[-1]:
            res.append(dict(res.pop(), note='flagged settling in its sidecar; the box was pointing at RA %.2f Dec %.2f (M57), not M76' % tuple(fl[s]['pointing_ra_dec'])))
    json.dump(res, open(W('step1_solve.json'), 'w'), indent=1)
