"""Step 7: plate-solve the ref-grid stack (astrometry.net: image2xy + solve-field on the green planes, 2 x 2 mean,
against the Tycho-2 / 2MASS index files on this machine), find M76's catalogue position (J2000 RA 25.5821,
Dec +51.5753) in it, check the nebula is there, and lay out the north-up crop grid that step 6 restacks onto:
north up, east left, the stack's own pixel scale (0.776 arcsec), centred on the catalogue position.
Also measures where stars sit in red and blue against green (the air is a slight prism at 57 to 59 degrees
altitude): step 6 samples the red and blue planes that much further along when it makes the north-up grid, so the
colours line up without a further resampling."""
import json, os, subprocess, sys
import numpy as np, cv2
from common import *
import fitsmin
from step1_solve import wcs_rd2xy, wcs_xy2rd, wcsinfo, CFG
from step3_stars import measure

CROP_W, CROP_H = int(os.environ.get('M76_GRID_W', 1000)), int(os.environ.get('M76_GRID_H', 800))   # output px of the north-up grid (restacked; the picture is cropped from it)

st = np.load(W('ref_stack.npy')); s6 = json.load(open(W('step6_ref.json')))
x0, y0 = s6['grid']['origin_sensor_xy']; ww, hh = s6['grid']['size']
G = (st[1] + st[2]) / 2
Gb = G[:hh // 2 * 2, :ww // 2 * 2].reshape(hh // 2, 2, ww // 2, 2).mean((1, 3)); BH, BW = Gb.shape
bg = cv2.blur(cv2.medianBlur(cv2.resize(Gb, (BW // 8, BH // 8), interpolation=cv2.INTER_AREA), 5), (9, 9))
D = Gb - cv2.resize(bg, (BW, BH), interpolation=cv2.INTER_LINEAR)
sc = 20000.0 / max(float(np.percentile(D, 99.99)), 1.0)
base = W('solve_stack')
for ext in ('.wcs', '.corr', '.xy', '.axy', '.fits'):
    if os.path.exists(base + ext): os.remove(base + ext)
fitsmin.write_image(base + '.fits', np.clip(D * sc + 1000, 0, 32000))
subprocess.run(['image2xy', '-O', '-p', '8', '-o', base + '.xy', base + '.fits'], check=True, capture_output=True)
cmd = ['solve-field', '--config', CFG, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(BW), '--height', str(BH),
       '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '1.40', '--scale-high', '1.70',
       '--ra', '%.4f' % TARGET['ra_deg'], '--dec', '%.4f' % TARGET['dec_deg'], '--radius', '2', '--cpulimit', '120', '--tweak-order', '2', '-N', 'none', '--rdls', 'none', '--match', 'none',
       '--solved', 'none', '--index-xyls', 'none', '--corr', base + '.corr', '--wcs', base + '.wcs', base + '.xy']
r = subprocess.run(cmd, capture_output=True, text=True)
assert os.path.exists(base + '.wcs'), r.stdout[-1500:]
info = wcsinfo(base + '.wcs'); co = fitsmin.read_bintable(base + '.corr')
fx, fy = wcs_rd2xy(base + '.wcs', TARGET['ra_deg'], TARGET['dec_deg'])
u0, v0 = 2 * (fx - 1) + 0.5, 2 * (fy - 1) + 0.5                      # stack (ref grid) pixel
# local map (east, north arcsec) per stack pixel at the target
r0 = wcs_xy2rd(base + '.wcs', fx, fy); r1 = wcs_xy2rd(base + '.wcs', fx + 50, fy); r2 = wcs_xy2rd(base + '.wcs', fx, fy + 50)
cosd = np.cos(np.radians(r0[1]))
J = np.array([[(r1[0] - r0[0]) * cosd, (r2[0] - r0[0]) * cosd], [r1[1] - r0[1], r2[1] - r0[1]]]) * 3600 / 50 / 2   # arcsec per stack px
sv = np.linalg.svd(J, compute_uv=False); scale = float(np.sqrt(sv[0] * sv[1]))
Ji = np.linalg.inv(J)
north = Ji @ np.array([0, 1.0]); east = Ji @ np.array([1.0, 0])
north_angle = float(np.degrees(np.arctan2(north[0], -north[1])))
mirrored = bool(east[0] * north[1] - east[1] * north[0] < 0)
# catalogue matches: how well does the solution fit (arcsec), from the solver's own list
res = []
for i in range(len(co['field_x'])):
    rr = wcs_xy2rd(base + '.wcs', float(co['field_x'][i]), float(co['field_y'][i]))
    res.append(np.hypot((rr[0] - co['index_ra'][i]) * np.cos(np.radians(rr[1])), rr[1] - co['index_dec'][i]) * 3600)
# is the nebula there? brightness of the stack around the catalogue position against the sky
yy, xx = np.mgrid[0:hh, 0:ww]
rr = np.hypot(xx - u0, yy - v0)
sky_m, sky_s, _ = clipped_stats(G[(rr > 300) & (rr < 500)])
core = float(np.mean(G[rr < 40])); ring = float(np.mean(G[(rr > 150) & (rr < 200)]))
# brightest smoothed point within 3 arcmin: where the nebula's light peaks against the catalogue position
sm = cv2.GaussianBlur(G, (0, 0), 6); box = (slice(int(v0) - 230, int(v0) + 230), slice(int(u0) - 230, int(u0) + 230))
sub = sm[box]; sub_r = rr[box]; sub = np.where(sub_r < 230, sub, -1e9)
py, px = np.unravel_index(np.argmax(sub), sub.shape)
peak_uv = [float(px + box[1].start), float(py + box[0].start)]
# the north-up grid: output (i, j) -> stack (u, v) = (u0, v0) + Ji @ (east, north), east = -(i - ic) s, north = -(j - jc) s
ic, jc = (CROP_W - 1) / 2, (CROP_H - 1) / 2
M = Ji @ np.diag([-scale, -scale])                # d(u, v) / d(i, j)
off = np.array([u0, v0]) - M @ np.array([ic, jc])
A_stack = np.hstack([M, off[:, None]])            # (u, v) = A_stack @ (i, j, 1)
A_ref = np.array([[2.0, 0, 0.5 + x0], [0, 2.0, 0.5 + y0]]) @ np.vstack([A_stack, [0, 0, 1]])   # ref sensor
corners = [A_stack @ np.array([i, j, 1.0]) for i, j in ((0, 0), (CROP_W - 1, 0), (0, CROP_H - 1), (CROP_W - 1, CROP_H - 1))]
inside = all(5 <= c[0] <= ww - 6 and 5 <= c[1] <= hh - 6 for c in corners)
assert inside, ('north-up grid leaves the stack', corners)
out = dict(solve=dict(index_stars_matched=int(len(co['field_x'])), match_rms_arcsec=float(np.sqrt(np.mean(np.square(res)))), centre_ra_dec=[info.get('ra_center'), info.get('dec_center')],
                      pixscale_arcsec_per_stack_px=scale, focal_length_mm=float(206.265 * 3.917 / (scale / 2)), field_arcmin=[ww * scale / 60, hh * scale / 60], orientation_deg_astrometry_net=info.get('orientation'), parity=info.get('parity'),
                      north_on_screen_deg_clockwise_from_up=north_angle, mirrored=mirrored, wcs_file='solve_stack.wcs (2 x 2 binned stack: stack px = 2 (FITS px - 1) + 0.5)'),
           target=dict(TARGET, stack_px=[u0, v0], ref_sensor_px=[2 * u0 + 0.5 + x0, 2 * v0 + 0.5 + y0], green_mean_within_15arcsec_dn=core, green_mean_r58_78arcsec_dn=ring, sky_mean_dn=sky_m, sky_sigma_per_px_dn=sky_s,
                       brightest_smoothed_point_within_3arcmin_stack_px=peak_uv, brightest_point_offset_arcsec=float(np.hypot(peak_uv[0] - u0, peak_uv[1] - v0) * scale)),
           out_to_stack=A_stack.tolist(), out_to_ref_sensor=A_ref[:2].tolist(), size=[CROP_W, CROP_H], centre_out_px=[ic, jc], pixscale_arcsec=scale,
           layout='north up, east left; output px (i, j) -> stack px (u, v) = out_to_stack @ (i, j, 1); centre of the grid = M76 catalogue position')
# red and blue against green: isolated, unsaturated stars with a good signal, away from the nebula
sky_p = [clipped_stats(st[p][::3, ::3])[0] for p in range(4)]
smg = cv2.GaussianBlur(G, (0, 0), 2.5); m_, s_, _ = clipped_stats(smg[::2, ::2])
nlab, lab, stats, cent = cv2.connectedComponentsWithStats((smg > m_ + 8 * s_).astype(np.uint8))
cx_ = cent[1:, 0]; cy_ = cent[1:, 1]
rows = []
for i in range(1, nlab):
    if stats[i, 4] < 10: continue
    x, y = cent[i]
    if np.hypot(x - u0, y - v0) < 250 or x < 40 or y < 40 or x > ww - 40 or y > hh - 40: continue
    if np.sort(np.hypot(cx_ - x, cy_ - y))[1] < 30: continue                      # a neighbour within 30 px
    g = measure(G - (sky_p[1] + sky_p[2]) / 2, x, y)
    if g is None or g['flux'] < 15000 or max(st[p][int(round(g['y'])) - 3:int(round(g['y'])) + 4, int(round(g['x'])) - 3:int(round(g['x'])) + 4].max() for p in range(4)) > 12000: continue
    rr_ = measure(st[0] - sky_p[0], g['x'], g['y']); bb_ = measure(st[3] - sky_p[3], g['x'], g['y'])
    if rr_ is None or bb_ is None: continue
    rows.append([g['x'], g['y'], rr_['x'] - g['x'], rr_['y'] - g['y'], bb_['x'] - g['x'], bb_['y'] - g['y'], g['flux']])
rows = np.array(rows)
d = np.median(rows[:, 2:6], 0); sc_ = 1.4826 * np.median(np.abs(rows[:, 2:6] - d), 0) / np.sqrt(len(rows))
out['colour_offsets'] = dict(stars=int(len(rows)), red_minus_green_stack_px=d[:2].tolist(), blue_minus_green_stack_px=d[2:].tolist(), standard_error_px=sc_.tolist(),
                             red_minus_green_ref_sensor_px=(2 * d[:2]).tolist(), blue_minus_green_ref_sensor_px=(2 * d[2:]).tolist(),
                             how='Gaussian-windowed centroids (step 3) of %d isolated unsaturated stars, each colour plane of the ref stack against the green mean; median' % len(rows))
print('colour offsets, stack px: R-G %+.3f %+.3f, B-G %+.3f %+.3f (standard error %.3f %.3f %.3f %.3f) from %d stars' % (*d, *sc_, len(rows)))
json.dump(out, open(W('step7_grid.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k in ('solve', 'target')}, indent=1))
print('north-up grid corners in the stack:', np.round(corners, 1).tolist())
