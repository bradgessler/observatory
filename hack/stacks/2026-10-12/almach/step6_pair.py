"""Step 6: measure the pair. Separation and position angle of the companion from the primary, and the colour of each star.

  separation and angle   two-star model (primary: an elliptical Gaussian with its own angle; companion: a circular Gaussian; one
                         flat sky level) fitted by least squares, (a) to each of the 13 frames' own luminance (R + G1 + G2 + B per 2 x 2
                         cell, no shifting, no resampling: the frame as the sensor saw it, cell scale), and (b) to the stack's luminance
                         (sensor scale). The 13 frame fits give a scatter, so a standard error on the mean (1/60 s freezes the speckle,
                         so single frames wander by a fraction of a pixel); the stack fit is the number quoted if the two agree.
  to the sky             the solved centring frame (step 5) gives the matrix from picture pixels to east and north on the sky at Almach;
                         position angle = angle of the companion measured from north through east.
  colour                 aperture photometry of each star on the stack, per plane (R, G, B), in the camera's own white-balanced units
                         (daylight multipliers from the RAW), sky taken from a ring far from the pair. Also per frame for the companion,
                         to see whether its blueness is in every frame or comes from one. The primary's red halo spills into the
                         companion's aperture (it makes the companion look less blue than it is); said in the recipe."""
import numpy as np, cv2
from scipy.optimize import least_squares
from common import *


def two_star(p, xx, yy):
    bg, a, x, y, sx, sy, th, b, u, v, s = p
    c, s_ = np.cos(th), np.sin(th); dx, dy = xx - x, yy - y; r1 = c * dx + s_ * dy; r2 = -s_ * dx + c * dy
    return bg + a * np.exp(-0.5 * ((r1 / sx) ** 2 + (r2 / sy) ** 2)) + b * np.exp(-0.5 * (((xx - u) ** 2 + (yy - v) ** 2) / s ** 2))


def fit_pair(img, x0, y0, guess_vec, half):
    """img: 2-D luminance; x0, y0: primary near; guess_vec: companion offset guess (pixels of this image). Returns dict with positions, in this image's pixels."""
    ys, xs = np.mgrid[int(y0) - half:int(y0) + half + 1, int(x0) - half:int(x0) + half + 1]
    cut = img[ys[0, 0]:ys[-1, 0] + 1, xs[0, 0]:xs[0, -1] + 1]
    xx, yy = xs.astype(float), ys.astype(float)
    # the stars' peaks: take the maximum near the guesses
    p0 = [float(np.median(cut)), float(cut.max()), x0, y0, half / 5, half / 5, 0.0, float(cut.max()) / 12, x0 + guess_vec[0], y0 + guess_vec[1], half / 5]
    lo = [-np.inf, 0, x0 - half / 3, y0 - half / 3, 0.8, 0.8, -np.pi, 0, x0 + guess_vec[0] - half / 3, y0 + guess_vec[1] - half / 3, 0.8]
    hi = [np.inf, np.inf, x0 + half / 3, y0 + half / 3, half / 1.5, half / 1.5, np.pi, np.inf, x0 + guess_vec[0] + half / 3, y0 + guess_vec[1] + half / 3, half / 1.5]
    f = least_squares(lambda p: (two_star(p, xx, yy) - cut).ravel(), p0, bounds=(lo, hi), x_scale='jac')
    bg, a, x, y, sx, sy, th, b, u, v, s = f.x
    return dict(primary=(x, y), companion=(u, v), amp_primary=a, amp_companion=b, sigma_primary=(sx, sy), sigma_companion=s, flux_ratio=(a * sx * sy) / (b * s * s), rms=float(np.sqrt(np.mean(f.fun ** 2))))


def aperture(plane, cx, cy, r, ring):
    yy, xx = np.mgrid[0:plane.shape[0], 0:plane.shape[1]]; d2 = (xx - cx) ** 2 + (yy - cy) ** 2
    sky = float(np.median(plane[(d2 >= ring[0] ** 2) & (d2 <= ring[1] ** 2)]))
    m = d2 <= r * r
    return float((plane[m] - sky).sum())


if __name__ == '__main__':
    A = np.load(W('crops.npy')); reg = jload('step3_register.json')['frames']; sol = jload('step5_solve.json'); wbd = jload('step2_prepare.json')['daylight_wb']
    M = np.array(sol['matrix_east_north_arcsec_per_cell'])                  # east, north arcsec per CELL px step in (x, y)
    to_sky = lambda dx_cell, dy_cell: (M @ np.array([dx_cell, dy_cell]))   # (east", north")
    rows = []
    for k in range(len(A)):
        lum = A[k].sum(0); px, py = reg[k]['cell_xy']; cx, cy = reg[k]['companion_cell_xy']
        f = fit_pair(lum, px, py, (cx - px, cy - py), 20)
        d = np.array(f['companion']) - np.array(f['primary']); e, n = to_sky(*d)
        rows.append(dict(i=k, file=reg[k]['file'], vec_cell=d.tolist(), sep_arcsec=float(np.hypot(e, n)), pa_deg=float(np.degrees(np.arctan2(e, n)) % 360), flux_ratio=f['flux_ratio'], rms=f['rms']))
        print('frame %2d %s: separation %.2f"  PA %.1f deg  flux A/B %.1f' % (k, reg[k]['file'][9:15], rows[-1]['sep_arcsec'], rows[-1]['pa_deg'], f['flux_ratio']))
    sep = np.array([r['sep_arcsec'] for r in rows]); pa = np.array([r['pa_deg'] for r in rows]); fr = np.array([r['flux_ratio'] for r in rows])
    print('frames: separation %.2f +- %.2f" (sd %.2f, n=%d), PA %.1f +- %.1f deg (sd %.1f)' % (sep.mean(), sep.std(ddof=1) / np.sqrt(len(sep)), sep.std(ddof=1), len(sep), pa.mean(), pa.std(ddof=1) / np.sqrt(len(pa)), pa.std(ddof=1)))
    # the stack
    d = np.load(W('stack.npz')); st = d['planes']; ref = d['ref']
    lum = (st[0] + 2 * st[1] + st[2]) / 4
    # the stack is at sensor scale: matrix per sensor px = M / 2
    f = fit_pair(lum, ref[0], ref[1], (-22, 12), 40)
    dv = np.array(f['companion']) - np.array(f['primary']); e, n = (M / 2) @ dv
    stack_sep = float(np.hypot(e, n)); stack_pa = float(np.degrees(np.arctan2(e, n)) % 360)
    print('stack: companion at (%.2f, %.2f) sensor px from the primary: separation %.2f"  PA %.1f deg  flux ratio A/B %.1f (%.2f mag)' % (dv[0], dv[1], stack_sep, stack_pa, f['flux_ratio'], 2.5 * np.log10(f['flux_ratio'])))
    # colour by aperture photometry on the stack (white-balanced planes)
    wb = np.array([wbd[0], 1.0, wbd[2]]); pa_xy = np.array(f['primary']); pb_xy = np.array(f['companion'])
    cols = {}
    for name, (cx_, cy_) in (('primary', pa_xy), ('companion', pb_xy)):
        fl = [aperture(st[c] * wb[c], cx_, cy_, 11, (90, 130)) for c in range(3)]
        cols[name] = dict(R=fl[0], G=fl[1], B=fl[2], R_over_G=fl[0] / fl[1], B_over_G=fl[2] / fl[1])
        print('%-9s white-balanced flux R %.0f G %.0f B %.0f   R/G %.2f  B/G %.2f' % (name, *fl, fl[0] / fl[1], fl[2] / fl[1]))
    # does the companion's colour hold in every frame? aperture photometry per frame on each frame's own planes (cell scale), white balanced
    per = []
    for k in range(len(A)):
        px, py = reg[k]['cell_xy']; cx, cy = reg[k]['companion_cell_xy']
        fa = [aperture(A[k, [0], :, :][0] * wb[0], px, py, 5.5, (45, 65)), aperture(0.5 * (A[k, 1] + A[k, 2]), px, py, 5.5, (45, 65)), aperture(A[k, 3] * wb[2], px, py, 5.5, (45, 65))]
        fb = [aperture(A[k, [0], :, :][0] * wb[0], cx, cy, 5.5, (45, 65)), aperture(0.5 * (A[k, 1] + A[k, 2]), cx, cy, 5.5, (45, 65)), aperture(A[k, 3] * wb[2], cx, cy, 5.5, (45, 65))]
        per.append(dict(file=reg[k]['file'], primary_R_G=fa[0] / fa[1], primary_B_G=fa[2] / fa[1], companion_R_G=fb[0] / fb[1], companion_B_G=fb[2] / fb[1]))
    a_rg = np.array([p['primary_R_G'] for p in per]); a_bg = np.array([p['primary_B_G'] for p in per]); b_rg = np.array([p['companion_R_G'] for p in per]); b_bg = np.array([p['companion_B_G'] for p in per])
    print('per frame: primary R/G %.2f (sd %.2f) B/G %.2f (sd %.2f) | companion R/G %.2f (sd %.2f) B/G %.2f (sd %.2f); companion bluer than primary (B/G - R/G larger) in %d of %d frames' % (
        a_rg.mean(), a_rg.std(), a_bg.mean(), a_bg.std(), b_rg.mean(), b_rg.std(), b_bg.mean(), b_bg.std(), int(((b_bg - b_rg) > (a_bg - a_rg)).sum()), len(per)))
    out = dict(method=__doc__.strip(), per_frame=rows,
               frames_mean=dict(separation_arcsec=float(sep.mean()), separation_se=float(sep.std(ddof=1) / np.sqrt(len(sep))), separation_sd=float(sep.std(ddof=1)),
                                position_angle_deg=float(pa.mean()), position_angle_se=float(pa.std(ddof=1) / np.sqrt(len(pa))), position_angle_sd=float(pa.std(ddof=1)), flux_ratio_mean=float(fr.mean())),
               stack_fit=dict(separation_arcsec=stack_sep, position_angle_deg=stack_pa, offset_sensor_px=dv.tolist(), flux_ratio_primary_over_companion=f['flux_ratio'], magnitude_difference=float(2.5 * np.log10(f['flux_ratio'])),
                              primary_xy_sensor_px=pa_xy.tolist(), companion_xy_sensor_px=pb_xy.tolist(), sigma_primary_px=f['sigma_primary'], sigma_companion_px=f['sigma_companion']),
               colour_on_stack=cols, colour_per_frame=per,
               colour_per_frame_summary=dict(primary_R_G=[float(a_rg.mean()), float(a_rg.std())], primary_B_G=[float(a_bg.mean()), float(a_bg.std())], companion_R_G=[float(b_rg.mean()), float(b_rg.std())], companion_B_G=[float(b_bg.mean()), float(b_bg.std())]),
               plate_scale_arcsec_per_sensor_px=sol['pixscale_arcsec_per_sensor_px'], catalogue=CATALOGUE)
    jdump(out, 'step6_pair.json')
