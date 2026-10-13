"""Plate solving with the local astrometry.net (Tycho-2 index files), shared by step 6 (the reference frame, before
anything is stacked: is it the thing, and where is it on the sensor?) and step 9 (the stack).

An image goes to a 16-bit FITS (rows top to bottom as in the array, so FITS pixel (x, y) = array [y - 1, x - 1]);
image2xy finds the sources; solve-field matches them (scale 0.72 to 0.84 arcsec per pixel, within 1 degree of the
target). wcs-rd2xy and wcs-xy2rd turn catalogue positions into pixels and back."""
import os, subprocess
import numpy as np
from common import *
import fitsmin

SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)
CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')


def rd2xy(stem, ra, dec):
    r = subprocess.run(['wcs-rd2xy', '-w', os.path.join(SOLVE, stem + '.wcs'), '-r', '%.6f' % ra, '-d', '%.6f' % dec], capture_output=True, text=True, check=True).stdout
    a = r.split('pixel (')[1].split(')')[0].split(',')
    return float(a[0]) - 1, float(a[1]) - 1                 # array col, row


def xy2rd(stem, x, y):
    r = subprocess.run(['wcs-xy2rd', '-w', os.path.join(SOLVE, stem + '.wcs'), '-x', '%.3f' % (x + 1), '-y', '%.3f' % (y + 1)], capture_output=True, text=True, check=True).stdout
    a = r.split('RA,Dec (')[1].split(')')[0].split(',')
    return float(a[0]), float(a[1])


def solve(G, stem):
    """Solve a 2-D image (one pixel per colour cell). Returns the numbers of the solution; raises SystemExit if none."""
    h, w = G.shape
    f = lambda ext: os.path.join(SOLVE, stem + ext)
    if os.path.exists(f('.wcs')): os.remove(f('.wcs'))
    fitsmin.write_image(f('.fits'), np.nan_to_num(G) + 100)
    subprocess.run(['image2xy', '-O', '-p', '8', '-w', '3', '-o', f('.xy'), f('.fits')], check=True, capture_output=True)
    cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w), '--height', str(h),
           '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '0.72', '--scale-high', '0.84',
           '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '1', '--cpulimit', '120', '--tweak-order', '2',
           '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none',
           '--corr', f('.corr'), '--wcs', f('.wcs'), f('.xy')]
    r = subprocess.run(cmd, capture_output=True, text=True)
    open(f('.solve-field.log'), 'w').write(r.stdout + r.stderr)
    os.remove(f('.fits'))
    if not os.path.exists(f('.wcs')):
        print(r.stdout[-3000:], r.stderr[-2000:]); raise SystemExit('not solved')
    info = subprocess.run(['wcsinfo', f('.wcs')], capture_output=True, text=True, check=True).stdout
    wi = {}
    for line in info.splitlines():
        k, _, v = line.partition(' ')
        try: wi[k] = float(v)
        except ValueError: wi[k] = v.strip()
    hd = fitsmin.read_header(f('.wcs'))
    cx, cy = w / 2, h / 2; ra0, de0 = xy2rd(stem, cx, cy)
    nx_, ny_ = rd2xy(stem, ra0, de0 + 0.02); ex_, ey_ = rd2xy(stem, ra0 + 0.02 / np.cos(np.radians(de0)), de0)
    north = np.degrees(np.arctan2(nx_ - cx, -(ny_ - cy)))          # angle of north from 'up', clockwise positive
    east = np.degrees(np.arctan2(ex_ - cx, -(ey_ - cy)))
    turn = (east - north + 540) % 360 - 180                         # -90: east is 90 deg anticlockwise of north = the sky as seen (not mirrored)
    corners = {k: xy2rd(stem, *v) for k, v in dict(top_left=(0, 0), top_right=(w - 1, 0), bottom_left=(0, h - 1), bottom_right=(w - 1, h - 1), centre=(cx, cy)).items()}
    return dict(solved=True, pixscale_arcsec=wi.get('pixscale'), field_arcmin=[w * wi.get('pixscale') / 60, h * wi.get('pixscale') / 60], centre_ra_dec=[ra0, de0],
                orientation_wcsinfo=wi.get('orientation'), parity=wi.get('parity'), north_angle_from_up_deg_clockwise=float(north), east_angle_from_up_deg_clockwise=float(east),
                mirrored=bool(turn > 0), corners_ra_dec=corners, focal_length_mm=float(3.92e-3 * 2 / (wi.get('pixscale') / 206264.806)),
                wcs_header={k: hd[k] for k in hd if k[:2] in ('CR', 'CD', 'CT', 'A_', 'B_', 'AP', 'BP', 'IM', 'NA') or k in ('A_ORDER', 'B_ORDER')})


def galaxy_ellipse(stem, scale_arcsec, semi_major_arcmin, semi_minor_arcmin):
    """The galaxy's catalogue place and position angle as an ellipse on the image: centre (px), semi-axes (px), and the
    angle of the major axis from the image's +x towards +y (degrees)."""
    cx, cy = rd2xy(stem, TARGET['ra_deg'], TARGET['dec_deg'])
    pa = np.radians(GALAXY_PA_DEG); d = 0.05                      # a point 3 arcmin along the major axis (north through east)
    ex, ey = rd2xy(stem, TARGET['ra_deg'] + d * np.sin(pa) / np.cos(np.radians(TARGET['dec_deg'])), TARGET['dec_deg'] + d * np.cos(pa))
    ang = float(np.degrees(np.arctan2(ey - cy, ex - cx)))
    return dict(centre_px=[float(cx), float(cy)], semi_major_px=float(semi_major_arcmin * 60 / scale_arcsec), semi_minor_px=float(semi_minor_arcmin * 60 / scale_arcsec), major_axis_angle_deg=ang)


def ellipse_mask(e, shape, shift=(0.0, 0.0), grow=0.0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    a = np.radians(e['major_axis_angle_deg']); dx = xx - (e['centre_px'][0] + shift[0]); dy = yy - (e['centre_px'][1] + shift[1])
    u = dx * np.cos(a) + dy * np.sin(a); v = -dx * np.sin(a) + dy * np.cos(a)
    return (u / (e['semi_major_px'] + grow)) ** 2 + (v / (e['semi_minor_px'] + grow)) ** 2 <= 1


def place_px(stem, ra, dec):
    """A catalogue place on the solved image: array col, row."""
    return rd2xy(stem, ra, dec)


def object_mask(s6, shape, shift=(0.0, 0.0), grow=0.0):
    """Everything that is not sky by the catalogue (step 6): M78's circle and the circles of the other catalogued
    nebulae in the frame, on the reference grid, moved by shift (plane px) and grown by grow px."""
    m = ellipse_mask(s6['galaxy_ellipse'], shape, shift=shift, grow=grow)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    for e in s6.get('extra_masks', []):
        m |= np.hypot(xx - (e['centre_px'][0] + shift[0]), yy - (e['centre_px'][1] + shift[1])) <= e['radius_px'] + grow
    return m
