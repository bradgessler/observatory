"""Step 8b: join the long stack (30 s ISO 1600, the proper coadd of step 8) and the short stack (2 s ISO 400), in linear
light, per colour plane, on the canvas. As hack/stacks/2026-10-03/m42/s9_hdr.py, with this run's numbers.

SCALE. Expected: 30 s x ISO 1600 over 2 s x ISO 400 = 15 x 4 = 60 (each stack is in the units of one frame of its kind
at that kind's median transparency, so a change of the sky between the runs shows here as well). Measured two ways:
  nebula  per plane, both stacks blurred with a Gaussian of sigma 4 px (normalised where data is missing, so their
          different star widths play no part), pixels at least 12 px from any pixel that came near the ceiling in any
          long frame and 16 px from any detected star, where at least half the short frames have data, long level
          between 800 and 6000 DN above the zero; long = a x short + b by least squares with 3-sigma rejection (b takes
          up the two stacks' zeros, set in different frames). Checked in three brightness bins. ONE factor a (the mean of
          the four planes weighted by their errors) is applied to all planes; each plane keeps its own b.
  stars   the check the skill quotes (41.0 against 40 on 3 October): aperture fluxes (radius 12 px, annulus 20 to 28 px
          median off) of the reference frame's stars that never came near the ceiling in any long frame, in green, both
          stacks; the median ratio and its spread. If the two ways disagree, something else is wrong.

STAR WIDTH. The short stack's stars may be sharper or softer than the long stack's (2 s against 30 s of tracking).
The Gaussian blur sigma (0 to 2 px in 0.1 steps) at which the short stack's unclipped stars reach the long stack's
peak (median over stars, green) is found; if the short stars are already as wide or wider (ratio at 0 under 1), no
blur. Not applied within 12 px of pixels that were near the ceiling even in 2 s (the Trapezium's stars).

BLEND. w = the short stack's share at a pixel:
  by the rule (the skill's): every pixel that came within 7 percent of the ceiling in ANY colour plane of ANY long frame
      (step 8) gets the short stack: w = 1. The mask is grown by one colour cell (3 x 3) and its edge softened outward
      by a Gaussian of 0.8 px.
  by signal, so there is no step at the mask's edge: L = the brightest of the four planes as the sensor saw it (the
      flat put back, the zero put back), from the long stack or the scaled short stack, whichever is higher; w rises
      smoothly (smoothstep) from 0 at L = L_LO (10,000 DN) to 1 at L_HI (14,000 DN; the ceiling is 15,488 above black).
  w is the larger of the two; where fewer than SHORT_MIN_FRAC of the short frames have data, w = 0.
  hdr = (1 - w) x long + w x (a x short' + b), short' the short stack after the width match.
RIM. The short stack is far noisier per pixel. Where it has to be used although its own signal is low (the rim of the
mask), its value is taken from a Gaussian-blurred copy (sigma 2 px), mixed in by its own signal-to-noise: fully blurred
below 5 sigma, sharp above 20 sigma. The Trapezium and the bright core are far above that.
WHITE. Where even the short frames came near the ceiling (any plane, any frame; grown 1 px), the colour is not known:
marked (work/white.npy) so that render.py shows those pixels white and never a colour made by the white balance.

Writes work/stack_mean.npy (the joined stack, what steps 9 to 11 finish), stack_odd/even.npy (the long halves; the
half-stack test of step 11 keeps away from where w > 0), w.npy, white.npy, step8b_join.json."""
import json, os
import numpy as np, cv2
from common import *
import canvas as CV

L_LO, L_HI = 10000.0, 14000.0
SHORT_MIN_FRAC = 0.5
EXPECTED = (30.0 * 1600) / (2.0 * 400)


def nblur(a, sigma):
    ok = np.isfinite(a)
    den = np.maximum(cv2.GaussianBlur(ok.astype(np.float32), (0, 0), sigma), 1e-4)
    return cv2.GaussianBlur(np.where(ok, a, 0).astype(np.float32), (0, 0), sigma) / den


def smoothstep(x, a, c):
    t = np.clip((x - a) / (c - a), 0, 1); return t * t * (3 - 2 * t)


def ap_flux(img, x, y, r=12, r0=20, r1=28):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - r1:yi + r1 + 1, xi - r1:xi + r1 + 1]
    if t.shape != (2 * r1 + 1, 2 * r1 + 1) or not np.isfinite(t).all(): return None
    yy, xx = np.mgrid[-r1:r1 + 1, -r1:r1 + 1]; rr = np.hypot(xx + xi - x, yy + yi - y)
    bg = np.median(t[(rr > r0) & (rr < r1)]); return float((t[rr <= r] - bg).sum())


def peak_of(img, x, y, r=3, R=20):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - R:yi + R + 1, xi - R:xi + R + 1]
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx, yy)
    return float(t[R - r:R + r + 1, R - r:R + r + 1].max() - np.median(t[(rr > 14) & (rr < 19)]))


if __name__ == '__main__':
    X0, Y0, HC, WC = CV.load()
    D = np.load(W('long_deliver.npy')); S_ = np.load(W('short_mean.npy'))
    near_l = np.load(W('long_near.npy')); near_s = np.load(W('short_near.npy')); scov = np.load(W('short_cover.npy'))
    s8 = jload('step8_stack.json'); NS = len(s8['short_frames'])
    stars = [s for s in json.load(open(W('step2_stars.json'))) if s['stamp'] == REF_STAMP][0]['stars']
    FLATG = np.load(W('flat_long.npy'))
    fy, fx = np.clip(np.mgrid[0:HC, 0:WC][0] + Y0, 0, h2 - 1), np.clip(np.mgrid[0:HC, 0:WC][1] + X0, 0, w2 - 1)
    flatc = FLATG[:, fy, fx]; del fy, fx
    zero_l = np.median(np.array(list(s8['constants'].values())), 0); zero_s = np.median(np.array(list(s8['short_constants'].values())), 0)
    have_s = scov >= SHORT_MIN_FRAC * NS
    far_clip = ~cv2.dilate(near_l.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(bool)
    sm = np.zeros((HC, WC), np.uint8)
    for s in stars: cv2.circle(sm, (int(round(s['x'] - X0)), int(round(s['y'] - Y0))), 16, 1, -1)
    far_star = sm == 0
    okb = cv2.erode((have_s & np.isfinite(D).all(0)).astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    fits = []
    for p in range(4):
        Db = nblur(D[p], 4.0); Sb = nblur(S_[p], 4.0)
        m = okb & far_clip & far_star & (Db > 800) & (Db < 6000)
        x = Sb[m][::7]; y = Db[m][::7]; keep = np.ones(len(x), bool)
        for _ in range(5):
            A = np.column_stack([x[keep], np.ones(keep.sum())]); co, *_ = np.linalg.lstsq(A, y[keep], rcond=None)
            r = y - (co[0] * x + co[1]); sd = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3 * sd
        n_ind = max(keep.sum() * 7 / 200.0, 3)
        sx = x[keep] - x[keep].mean(); err = float(sd / np.sqrt((sx ** 2).sum()) * np.sqrt(keep.sum() / n_ind))
        bins = []
        for lo, hi in ((800, 1500), (1500, 3000), (3000, 6000)):
            mb = keep & (y >= lo) & (y < hi)
            if mb.sum() > 50:
                bins.append(dict(long_level_dn=[lo, hi], pixels=int(mb.sum()), ratio_with_the_common_offset=float(np.median((y[mb] - co[1]) / x[mb]))))
        fits.append(dict(plane=PLANE_NAMES[p], a=float(co[0]), a_error=err, b=float(co[1]), pixels=int(keep.sum()), scatter_dn=float(sd), bins=bins))
        print('%-2s long = %.3f (+-%.3f) x short %+.1f   [%d px, scatter %.1f DN]  bins: %s' % (PLANE_NAMES[p], co[0], err, co[1], keep.sum(), sd, ['%d..%d: %.2f (%d px)' % (*b['long_level_dn'], b['ratio_with_the_common_offset'], b['pixels']) for b in bins]), flush=True)
    a_all = np.array([f['a'] for f in fits]); e_all = np.array([f['a_error'] for f in fits])
    a = float((a_all / e_all ** 2).sum() / (1 / e_all ** 2).sum())
    bs = []
    for p in range(4):
        Db = nblur(D[p], 4.0); Sb = nblur(S_[p], 4.0); m = okb & far_clip & far_star & (Db > 800) & (Db < 6000)
        bs.append(float(np.median((Db[m] - a * Sb[m])[::7])))
    print('nebula: factor applied to all planes %.3f (expected %.0f: measured / expected = %.4f); offsets b %s' % (a, EXPECTED, a / EXPECTED, np.round(bs, 1).tolist()), flush=True)
    # ---- the stars' check: aperture fluxes of stars that never came near the ceiling in a long frame
    Gl = 0.5 * (D[1] + D[2]); Gs_ = 0.5 * (S_[1] + S_[2])
    clip_far = cv2.dilate(near_l.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    rat = []
    for s in stars:
        x, y = s['x'] - X0, s['y'] - Y0
        if not (40 < x < WC - 40 and 40 < y < HC - 40) or clip_far[int(round(y)), int(round(x))] or s['nearest'] < 60 or not have_s[int(round(y)), int(round(x))]: continue
        fl, fs = ap_flux(Gl, x, y), ap_flux(Gs_, x, y)
        if fl and fs and fl > 30000 and fs > 0: rat.append(dict(xy=[round(x, 1), round(y, 1)], long=fl, short=fs, ratio=fl / fs))
    rr = np.array([r['ratio'] for r in rat])
    big = np.array([r['long'] for r in rat]) > np.median([r['long'] for r in rat])
    star_check = dict(stars=len(rat), median_ratio=float(np.median(rr)), spread=float(1.4826 * np.median(np.abs(rr - np.median(rr)))), error_of_median=float(1.2533 * 1.4826 * np.median(np.abs(rr - np.median(rr))) / np.sqrt(len(rr))),
                      brighter_half_median=float(np.median(rr[big])), fainter_half_median=float(np.median(rr[~big])), rows=rat)
    print('stars: long / short aperture flux, %d unclipped stars: median %.2f (spread %.2f, error of the median %.2f; brighter half %.2f, fainter half %.2f) against %.0f expected and %.2f from the nebula' % (
        len(rat), star_check['median_ratio'], star_check['spread'], star_check['error_of_median'], star_check['brighter_half_median'], star_check['fainter_half_median'], EXPECTED, a), flush=True)
    # ---- star width
    msel = [s for s in stars if 40 < s['x'] - X0 < WC - 40 and 40 < s['y'] - Y0 < HC - 40 and not clip_far[int(round(s['y'] - Y0)), int(round(s['x'] - X0))] and s['nearest'] > 60 and s['hfr'] and s['hfr'] < 5.0
            and have_s[int(round(s['y'] - Y0)), int(round(s['x'] - X0))] and peak_of(np.nan_to_num(Gl), s['x'] - X0, s['y'] - Y0) > 1500]
    grid = [round(0.1 * i, 1) for i in range(21)]; curve = []
    for sg in grid:
        Sb_ = a * (np.nan_to_num(Gs_) if sg == 0 else cv2.GaussianBlur(np.nan_to_num(Gs_), (0, 0), sg))
        r_ = [peak_of(Sb_, s['x'] - X0, s['y'] - Y0) / peak_of(np.nan_to_num(Gl), s['x'] - X0, s['y'] - Y0) for s in msel]
        curve.append(float(np.median(r_)))
    if curve[0] <= 1.0: match = 0.0
    else:
        i = next((k for k in range(1, len(curve)) if curve[k] <= 1.0), len(curve) - 1)
        match = float(grid[i - 1] + (grid[i] - grid[i - 1]) * (curve[i - 1] - 1.0) / max(curve[i - 1] - curve[i], 1e-9)) if curve[i] <= 1.0 else grid[-1]
    print('star width: peak(short x a, blurred) / peak(long) by blur sigma %s over %d stars -> blur %.2f px' % (dict(zip(grid[::2], np.round(curve[::2], 3))), len(msel), match), flush=True)
    sharp_zone = cv2.dilate(near_s.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(np.float32)
    sharp_zone = cv2.GaussianBlur(sharp_zone, (0, 0), 2.0)
    # ---- the blend
    near_g = cv2.dilate(near_l.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
    w_rule = np.maximum(near_g, cv2.GaussianBlur(near_g, (0, 0), 0.8))
    Ssc = np.empty_like(S_)
    noise_s = [float(v) for v in s8['noise_faint_region_dn']['short']]
    for p in range(4):
        sp = np.nan_to_num(S_[p])
        if match > 0: sp = sharp_zone * sp + (1 - sharp_zone) * cv2.GaussianBlur(sp, (0, 0), match)
        sb = cv2.GaussianBlur(sp, (0, 0), 2.0)
        snr = sp / max(noise_s[p], 1e-3); mix = smoothstep(snr, 5.0, 20.0)
        Ssc[p] = a * (mix * sp + (1 - mix) * sb) + bs[p]
    Lsens = np.maximum(np.nan_to_num(D), Ssc) + zero_l[:, None, None]
    Lsens = (Lsens * flatc).max(0)
    w = np.maximum(w_rule, smoothstep(Lsens, L_LO, L_HI)).astype(np.float32)
    w[~have_s] = 0.0
    hdr = ((1 - w)[None] * np.nan_to_num(D) + w[None] * Ssc).astype(np.float32)
    hdr[:, ~np.isfinite(D).all(0) & (w == 0)] = np.nan
    white = cv2.dilate(near_s.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) | (near_l & ~have_s)
    np.save(W('stack_mean.npy'), hdr); np.save(W('w.npy'), w); np.save(W('white.npy'), white)
    for h in ('odd', 'even'): np.save(W('stack_%s.npy' % h), np.load(W('long_deliver_%s.npy' % h)))
    out = dict(expected=EXPECTED, nebula_fits=fits, factor_applied=a, factor_over_expected=a / EXPECTED, offsets_b=bs, star_check={k: v for k, v in star_check.items() if k != 'rows'}, star_rows=rat[:200],
               star_width=dict(stars=len(msel), grid=grid, peak_ratio=curve, blur_applied_px=match),
               blend=dict(L_LO=L_LO, L_HI=L_HI, short_min_frac=SHORT_MIN_FRAC, pixels_w_gt_0=int((w > 0).sum()), pixels_w_eq_1=int((w >= 0.999).sum()), pixels_rule=int(near_l.sum()), white_pixels=int(white.sum()),
                          w_gt_0_arcmin2=float((w > 0).sum() * (0.7765 / 60) ** 2), rim='short value blurred (sigma 2) below 5 sigma of its own noise, sharp above 20'),
               noise_short_faint_region_dn=noise_s)
    jdump(out, 'step8b_join.json')
    print('blend: short stack used at %d px (%.2f arcmin^2), fully at %d; %d px where even the short frames came near the ceiling (shown white)' % (out['blend']['pixels_w_gt_0'], out['blend']['w_gt_0_arcmin2'], out['blend']['pixels_w_eq_1'], out['blend']['white_pixels']))
