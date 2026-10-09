"""Step 8: is it the thing? Plate-solve the stack (astrometry.net, local Tycho-2 index files) and find M33's catalogue
position in it, plus a few of its catalogued HII regions as a check on what the picture shows.

The stack is first cut to the well-covered rectangle (every pixel seen by at least 80% of the used frames, even size);
that rectangle is what is delivered. The green planes' mean goes to a 16-bit FITS (rows top to bottom as in the array,
so FITS pixel (x, y) = array [y - 1, x - 1]); image2xy finds the sources; solve-field matches them (scale 0.72 to 0.84
arcsec per pixel, within 1 degree of the target). wcs-rd2xy turns catalogue positions into pixels.

Catalogue positions (J2000, degrees) used for the check: M33 nucleus (from the task), and NGC 604, NGC 595, NGC 592,
NGC 588 (bright HII regions of M33, positions rounded to about 0.2 arcmin)."""
import json, os, subprocess
import numpy as np, cv2
from common import *
import fitsmin

COVER_MIN_FRACTION = 0.80
CAT = {'M33 nucleus': (TARGET['ra_deg'], TARGET['dec_deg']), 'NGC 604': (23.6371, 30.7839), 'NGC 595': (23.3917, 30.6917),
       'NGC 592': (23.3008, 30.6469), 'NGC 588': (23.1883, 30.6483)}
SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)
CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')


def cover_rect(cover, nmin):
    inside = cover >= nmin
    ys, xs = np.nonzero(inside); x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    while True:
        sub = inside[y0:y1, x0:x1]
        if sub.all(): break
        fr = [(~sub[0, :]).mean(), (~sub[-1, :]).mean(), (~sub[:, 0]).mean(), (~sub[:, -1]).mean()]
        i = int(np.argmax(fr))
        if i == 0: y0 += 1
        elif i == 1: y1 -= 1
        elif i == 2: x0 += 1
        else: x1 -= 1
    x0 += x0 % 2; y0 += y0 % 2; x1 -= (x1 - x0) % 2; y1 -= (y1 - y0) % 2
    return int(x0), int(y0), int(x1), int(y1)


def rd2xy(ra, dec):
    r = subprocess.run(['wcs-rd2xy', '-w', os.path.join(SOLVE, 'stack.wcs'), '-r', '%.6f' % ra, '-d', '%.6f' % dec], capture_output=True, text=True, check=True).stdout
    # "RA,Dec (23.462100, 30.659900) -> pixel (1234.5, 678.9)"
    a = r.split('pixel (')[1].split(')')[0].split(',')
    return float(a[0]) - 1, float(a[1]) - 1                 # array col, row


def xy2rd(x, y):
    r = subprocess.run(['wcs-xy2rd', '-w', os.path.join(SOLVE, 'stack.wcs'), '-x', '%.3f' % (x + 1), '-y', '%.3f' % (y + 1)], capture_output=True, text=True, check=True).stdout
    a = r.split('RA,Dec (')[1].split(')')[0].split(',')
    return float(a[0]), float(a[1])


if __name__ == '__main__':
    st = np.load(W('stack_mean.npy')); cover = np.load(W('stack_cover.npy'))
    N = len(jload('step5_select.json')['used'])
    x0, y0, x1, y1 = cover_rect(cover, int(np.ceil(COVER_MIN_FRACTION * N)))
    print('well-covered rectangle (>= %d of %d frames): x %d..%d, y %d..%d -> %d x %d px' % (int(np.ceil(COVER_MIN_FRACTION * N)), N, x0, x1, y0, y1, x1 - x0, y1 - y0))
    G = np.nan_to_num((st[1] + st[2])[:, y0:y1, x0:x1].mean(0) if False else 0.5 * (st[1, y0:y1, x0:x1] + st[2, y0:y1, x0:x1]))
    h, w = G.shape
    fitsmin.write_image(os.path.join(SOLVE, 'stack.fits'), G + 100)
    subprocess.run(['image2xy', '-O', '-p', '8', '-w', '3', '-o', os.path.join(SOLVE, 'stack.xy'), os.path.join(SOLVE, 'stack.fits')], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w), '--height', str(h),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '0.72', '--scale-high', '0.84',
           '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '1', '--cpulimit', '120', '--tweak-order', '2',
           '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none',
           '--corr', os.path.join(SOLVE, 'stack.corr'), '--wcs', os.path.join(SOLVE, 'stack.wcs'), os.path.join(SOLVE, 'stack.xy')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(os.path.join(SOLVE, 'solve-field.log'), 'w').write(r.stdout + r.stderr)
    if not os.path.exists(os.path.join(SOLVE, 'stack.wcs')):
        print(r.stdout[-3000:], r.stderr[-2000:]); raise SystemExit('not solved')
    info = subprocess.run(['wcsinfo', os.path.join(SOLVE, 'stack.wcs')], capture_output=True, text=True, check=True).stdout
    wi = {}
    for line in info.splitlines():
        k, _, v = line.partition(' ')
        try: wi[k] = float(v)
        except ValueError: wi[k] = v.strip()
    hd = fitsmin.read_header(os.path.join(SOLVE, 'stack.wcs'))
    # directions on the picture (x right, y down): where north and east point from the centre
    cx, cy = w / 2, h / 2; ra0, de0 = xy2rd(cx, cy)
    nx_, ny_ = rd2xy(ra0, de0 + 0.02); ex_, ey_ = rd2xy(ra0 + 0.02 / np.cos(np.radians(de0)), de0)
    north = np.degrees(np.arctan2(nx_ - cx, -(ny_ - cy)))          # angle of north from 'up', clockwise positive
    east = np.degrees(np.arctan2(ex_ - cx, -(ey_ - cy)))
    turn = (east - north + 540) % 360 - 180                         # -90: east is 90 deg anticlockwise of north = the sky as seen (not mirrored)
    # catalogue objects in the picture, and the nucleus found in the image
    Gs = cv2.GaussianBlur(G.astype(np.float32), (0, 0), 1.5)
    found = {}
    for name, (ra, dec) in CAT.items():
        px, py = rd2xy(ra, dec)
        inside = 0 <= px < w and 0 <= py < h
        d = dict(ra_deg=ra, dec_deg=dec, pixel=[round(px, 1), round(py, 1)], inside=bool(inside))
        if inside:
            R = 12; xi, yi = int(round(px)), int(round(py))
            cut = Gs[max(yi - R, 0):yi + R + 1, max(xi - R, 0):xi + R + 1]
            j = np.unravel_index(np.argmax(cut), cut.shape); bx, by = max(xi - R, 0) + j[1], max(yi - R, 0) + j[0]
            ring = Gs[max(yi - 60, 0):yi + 61, max(xi - 60, 0):xi + 61]
            d.update(brightest_within_12px=[int(bx), int(by)], offset_arcsec=round(float(np.hypot(bx - px, by - py) * wi.get('pixscale', 0.776)), 2),
                     peak_over_surroundings_dn=round(float(Gs[by, bx] - np.median(ring)), 1))
        found[name] = d
        print('%-12s pixel (%7.1f, %7.1f) %s' % (name, px, py, ('peak at (%d, %d), %.1f arcsec away, %.0f DN above its surroundings' % (d['brightest_within_12px'][0], d['brightest_within_12px'][1], d['offset_arcsec'], d['peak_over_surroundings_dn'])) if inside else 'outside the picture'))
    corners = {k: xy2rd(*v) for k, v in dict(top_left=(0, 0), top_right=(w - 1, 0), bottom_left=(0, h - 1), bottom_right=(w - 1, h - 1), centre=(cx, cy)).items()}
    out = dict(crop_on_reference_grid=dict(x0=x0, y0=y0, x1=x1, y1=y1, width=w, height=h, cover_min_frames=int(np.ceil(COVER_MIN_FRACTION * N))),
               solved=True, pixscale_arcsec=wi.get('pixscale'), field_arcmin=[w * wi.get('pixscale') / 60, h * wi.get('pixscale') / 60], centre_ra_dec=[ra0, de0],
               orientation_wcsinfo=wi.get('orientation'), parity=wi.get('parity'), north_angle_from_up_deg_clockwise=float(north), east_angle_from_up_deg_clockwise=float(east),
               mirrored=bool(turn > 0), corners_ra_dec=corners, catalogue=found, focal_length_mm=float(3.92e-3 * 2 / (wi.get('pixscale') / 206264.806)),
               stars_matched=len(open(os.path.join(SOLVE, 'solve-field.log')).read().split('match')) - 1, wcs_header={k: hd[k] for k in hd if k[:2] in ('CR', 'CD', 'CT', 'A_', 'B_', 'AP', 'BP', 'IM', 'NA') or k in ('A_ORDER', 'B_ORDER')})
    jdump(out, 'step8_solve.json')
    print('solved: %.4f arcsec/px (focal length %.0f mm for 3.92 um pixels in 2 x 2 cells), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north is %.1f deg clockwise from up, east %.1f; %s' % (
        out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], ra0, de0, north, east, 'MIRRORED' if out['mirrored'] else 'not mirrored (the sky as seen)'))
