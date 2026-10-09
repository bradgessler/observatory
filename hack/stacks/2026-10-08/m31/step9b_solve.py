"""Step 9b: is it the thing, and where does it lie? A plate solution of the delivered stack with astrometry.net.
Stars are found on the stack's green with the galaxy's smooth light taken off (as step 3), by image2xy; solve-field
is hinted with M31's position and the colour-cell scale, against this machine's index files
(~/.observatory/astrometry). From the solution (wcs-rd2xy, which applies the fitted distortion): where M31's
catalogue nucleus (J2000 RA 10.6847, Dec +41.2690) falls, against the nucleus measured in the stack (step 9); whether
M32 (RA 10.6742, Dec +40.8652) is inside the picture; the scale, which way north is, and the field.
Pixel coordinates: the delivered pictures (crop of step 9, colour-cell grid), x right, y down, 0-based."""
import os, subprocess, re, json
import numpy as np, cv2, tifffile
from common import *
import fitsmin

S9 = jload('step9.json')
SOLVE = W('solve'); os.makedirs(SOLVE, exist_ok=True)
CFG = os.path.expanduser('~/.observatory/astrometry/astrometry.cfg')
M32 = dict(name='M32', ra_deg=10.6742, dec_deg=40.8652)

t = tifffile.imread(os.path.join(OUT, 'm31-stack.tif')).astype(np.float32) - S9['pedestal']
G = t[:, :, 1]; h, w = G.shape
small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
smooth = cv2.resize(cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 2), (w, h), interpolation=cv2.INTER_CUBIC)
D = G - smooth
sc = 20000.0 / max(float(np.percentile(D, 99.99)), 1.0)
base = os.path.join(SOLVE, 'm31')
for ext in ('.wcs', '.corr', '.xy', '.axy', '.fits'):
    if os.path.exists(base + ext): os.remove(base + ext)
fitsmin.write_image(base + '.fits', np.clip(D * sc + 1000, 0, 32000))
subprocess.run(['image2xy', '-O', '-p', '8', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
px = 2 * SCALE
cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w), '--height', str(h),
       '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '%.3f' % (0.95 * px), '--scale-high', '%.3f' % (1.05 * px),
       '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '1', '--cpulimit', '120', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none',
       '--solved', 'none', '--index-xyls', 'none', '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
r = subprocess.run(cmd, capture_output=True, text=True)
if not os.path.exists(base + '.wcs'):
    print('NO SOLVE'); print(r.stdout[-3000:], r.stderr[-2000:]); jdump(dict(solved=False, stdout=r.stdout[-3000:]), 'step9b_solve.json'); raise SystemExit(1)


def rd2xy(ra, dec):
    o = subprocess.run(['wcs-rd2xy', '-w', base + '.wcs', '-r', '%.7f' % ra, '-d', '%.7f' % dec], capture_output=True, text=True).stdout
    m = re.search(r'pixel \(([-\d.eE+]+), ([-\d.eE+]+)\)', o)
    return float(m.group(1)) - 1, float(m.group(2)) - 1          # FITS 1-based -> 0-based


def xy2rd(x, y):
    o = subprocess.run(['wcs-xy2rd', '-w', base + '.wcs', '-x', '%.4f' % (x + 1), '-y', '%.4f' % (y + 1)], capture_output=True, text=True).stdout
    m = re.search(r'RA,Dec \(([-\d.eE+]+), ([-\d.eE+]+)\)', o)
    return float(m.group(1)), float(m.group(2))


info = subprocess.run(['wcsinfo', base + '.wcs'], capture_output=True, text=True).stdout
kv = dict(l.split(None, 1) for l in info.strip().split('\n') if len(l.split(None, 1)) == 2)
co = fitsmin.read_bintable(base + '.corr')
nx_, ny_ = rd2xy(TARGET['ra_deg'], TARGET['dec_deg'])
mx, my = S9['nucleus_crop_px']
off_px = (mx - nx_, my - ny_); off_as = float(np.hypot(*off_px) * px)
m32 = rd2xy(M32['ra_deg'], M32['dec_deg'])
inside = 0 <= m32[0] < w and 0 <= m32[1] < h
# north and east as directions in the picture
cra, cdec = xy2rd(w / 2 - 0.5, h / 2 - 0.5)
n1 = rd2xy(cra, cdec + 0.05); e1 = rd2xy(cra + 0.05 / np.cos(np.radians(cdec)), cdec)
c0 = rd2xy(cra, cdec)
north = np.degrees(np.arctan2(-(n1[1] - c0[1]), n1[0] - c0[0])); east = np.degrees(np.arctan2(-(e1[1] - c0[1]), e1[0] - c0[0]))
corners = [xy2rd(x, y) for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
dist_m32_edge_arcmin = None
if not inside:
    dx = max(0 - m32[0], 0, m32[0] - (w - 1)); dy = max(0 - m32[1], 0, m32[1] - (h - 1)); dist_m32_edge_arcmin = float(np.hypot(dx, dy) * px / 60)
out = dict(solved=True, catalogue_stars_matched=int(len(co['field_x'])), pixel_scale_arcsec=float(kv.get('pixscale', 'nan')), field_arcmin=[w * float(kv.get('pixscale', 'nan')) / 60, h * float(kv.get('pixscale', 'nan')) / 60],
           centre_ra_dec_deg=[cra, cdec], parity=kv.get('parity'), orientation_deg=float(kv.get('orientation', 'nan')),
           north_points_deg_ccw_from_right=float(north), east_points_deg_ccw_from_right=float(east), corners_ra_dec_deg=dict(zip(['top_left', 'top_right', 'bottom_left', 'bottom_right'], corners)),
           m31_catalogue_nucleus_at_px=[nx_, ny_], measured_nucleus_px=[mx, my], measured_minus_catalogue_px=list(off_px), measured_minus_catalogue_arcsec=off_as,
           m32_at_px=list(m32), m32_inside_picture=bool(inside), m32_outside_by_arcmin=dist_m32_edge_arcmin, focal_length_mm_from_scale=float(3.92e-3 * 2 / (float(kv.get('pixscale', 'nan')) / 206265)))
jdump(out, 'step9b_solve.json')
print(json.dumps(out, indent=1))
