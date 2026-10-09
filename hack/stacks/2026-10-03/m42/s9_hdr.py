"""Step 9: the high-dynamic-range blend of the deep stack (20 s ISO 3200) and the short stack (2 s ISO 800),
in linear light, per colour plane, on the deep stack's grid.

SCALE. Expected: 20 s x ISO 3200 against 2 s x ISO 800 = 10 x 4 = 40. Measured, per colour plane, from the
nebula where both stacks see it well and neither is near the ceiling: both stacks blurred with a Gaussian of
sigma 4 px (so that their different star widths play no part), pixels more than 12 px from any pixel that was
near the ceiling in any deep frame and more than 16 px from any detected star, deep level between 800 and 6000 DN
above the sky; straight line deep = a x short + b by least squares with 3-sigma rejection (b takes up the
difference of the two skies and of the camera's black level, which shifts by a few DN from frame to frame and
plane to plane at ISO 800). Checked in three brightness bins (is it one straight line?) and against the
aperture fluxes of stars that are unsaturated in both. ONE factor a (the weighted mean of the four planes) is
applied to all planes; each plane keeps its own b.

BLEND. w = the share of the short stack at a pixel:
  by signal: L = the brightest of the four planes at that pixel, as the sensor saw it (flat put back, sky in),
      from the deep stack or the scaled short stack, whichever is higher (the deep stack reads low where it
      clipped); w rises smoothly (smoothstep) from 0 at L = 10000 DN to 1 at L = 14000 DN (the ceiling is 15500).
  by the rule: every pixel that was within the margin of the ceiling (14400 DN, 7% under it) in ANY colour plane of ANY deep
      frame (the mask of step 7, already grown by one colour cell) gets the short stack whatever L says: w = 1.
  w is the larger of the two; the mask's edge is softened outward by a Gaussian of 0.8 px. Where the short
  stack has no data, w = 0. (The mask is NOT grown further: a first version grew it by 3 px, which put the
  short stack, whose pixel noise is 125 DN in these units against the deep stack's 12, into the faint sky right
  beside every bright star, as dark and bright specks.)
  hdr = (1 - w) x deep + w x (a x short + b)

RIM. The short stack is ten times noisier per pixel than the deep one (about 120 DN in these units against 12).
Where it has to be used although the light is faint (the rim of the any-frame mask, which is wider than a star
because each 20 s frame trails the star its own way), its value is taken from a Gaussian-blurred copy (sigma
2 px), mixed in by its own signal-to-noise: fully blurred below 5 sigma, sharp above 20 sigma. The star cores
and the Trapezium are far above that and are not touched.

STAR WIDTH. The short stack's stars are sharper than the deep stack's (2 s against 20 s of tracking drift). Before
it is blended in, the short stack is blurred by a Gaussian of 1.05 px, the width at which its unsaturated stars
reach the deep stars' peak, so that a replaced star core fits the deep star round it; EXCEPT within 12 px of
pixels that were at the ceiling even in 2 s (the Trapezium and the few brightest stars), where it stays sharp.
(Without this the replaced cores of middling stars came out as small green or blue dots with dark rings: the
short stack's sharper core, with the air's colour dispersion in it, set into the wider deep star.)

WHITE. Where even the short frames were within the margin of the ceiling (any plane, any frame), or the deep
frames were and there is no short data, the colour of the pixel is not known: those pixels are marked (soft
mask), and when the white balance is applied they are given equal R, G and B (the largest of the three), so a
clipped star core is white and never a colour made by the white balance."""
import json
import numpy as np, cv2
from common import *

L_LO, L_HI = 10000.0, 14000.0
D = np.load(W('deep_planes.npy')); S_ = np.load(W('short_planes.npy'))
dclip = np.load(W('deep_clip.npy')) > 0; sclip = np.load(W('short_clip.npy')) > 0
FR = np.load(W('deep_flatref.npy'))
stars = json.load(open(W('s8_stars_deep.json')))['stars']
s7d = json.load(open(W('s7_deep.json'))); s7s = json.load(open(W('s7_short.json')))
skyd = s7d['level_in_faintest_quarter_dn']


def nblur(a, ok, sigma):
    den = np.maximum(cv2.GaussianBlur(ok.astype(np.float32), (0, 0), sigma), 1e-4)
    return cv2.GaussianBlur(np.where(ok, a, 0).astype(np.float32), (0, 0), sigma) / den, den


far_clip = ~cv2.dilate(dclip.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(bool)
starmask = np.zeros((H2, W2), np.uint8)
for s in stars: cv2.circle(starmask, (int(round(s['x'])), int(round(s['y']))), 16, 1, -1)
far_star = starmask == 0
fits = []; SB = []
for p in range(4):
    ok = np.isfinite(D[p]) & np.isfinite(S_[p])
    Db, dd = nblur(D[p], ok, 4.0); Sb, _ = nblur(S_[p], ok, 4.0)
    okb = cv2.erode(ok.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    lev = Db - skyd[PLANE_NAMES[p]]
    m = okb & far_clip & far_star & (lev > 800) & (lev < 6000)
    x = Sb[m][::7]; y = Db[m][::7]; keep = np.ones(len(x), bool)
    for _ in range(5):
        A = np.column_stack([x[keep], np.ones(keep.sum())]); co, *_ = np.linalg.lstsq(A, y[keep], rcond=None)
        r = y - (co[0] * x + co[1]); sd = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3 * sd
    # the slope's error: pixels of a sigma-4 blur are correlated over about 4 pi sigma^2 = 200 px; every 7th pixel was taken
    n_ind = max(keep.sum() * 7 / 200.0, 3)
    sx = x[keep] - x[keep].mean(); err = float(sd / np.sqrt((sx ** 2).sum()) * np.sqrt(keep.sum() / n_ind))
    bins = []
    for lo, hi in ((800, 1500), (1500, 3000), (3000, 6000)):
        mb = keep & (y - skyd[PLANE_NAMES[p]] >= lo) & (y - skyd[PLANE_NAMES[p]] < hi)
        if mb.sum() > 50:
            Ab = np.column_stack([x[mb], np.ones(mb.sum())]); cb, *_ = np.linalg.lstsq(Ab, y[mb], rcond=None)
            bins.append(dict(deep_level_dn=[lo, hi], pixels=int(mb.sum()), slope=float(cb[0]), ratio_with_the_common_offset=float(np.median((y[mb] - co[1]) / x[mb]))))
    fits.append(dict(plane=PLANE_NAMES[p], a=float(co[0]), a_error=err, b=float(co[1]), pixels=int(keep.sum()), scatter_dn=float(sd), bins=bins))
    print('%-2s deep = %.3f (+-%.3f) x short %+.1f   [%d px, scatter %.1f DN]  bins: %s' % (PLANE_NAMES[p], co[0], err, co[1], keep.sum(), sd, ['%d..%d: %.2f (%d px)' % (*b['deep_level_dn'], b['ratio_with_the_common_offset'], b['pixels']) for b in bins]))
a_all = np.array([f['a'] for f in fits]); e_all = np.array([f['a_error'] for f in fits])
a = float((a_all / e_all ** 2).sum() / (1 / e_all ** 2).sum())
# with the common factor, each plane's offset again
bs = []
for p in range(4):
    ok = np.isfinite(D[p]) & np.isfinite(S_[p])
    Db, _ = nblur(D[p], ok, 4.0); Sb, _ = nblur(S_[p], ok, 4.0)
    okb = cv2.erode(ok.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
    lev = Db - skyd[PLANE_NAMES[p]]
    m = okb & far_clip & far_star & (lev > 800) & (lev < 6000)
    bs.append(float(np.median((Db[m] - a * Sb[m])[::7])))
print('factor applied to all planes: %.3f (expected 40: measured / expected = %.4f); offsets b: %s' % (a, a / 40.0, np.round(bs, 1).tolist()))

# ---- star width: the short stack's stars are sharper than the deep stack's (2 s against 20 s of tracking drift) ----
# Stars that never came near the ceiling in the deep frames: peak of the short stack (x a), blurred by a Gaussian of sigma s,
# over the peak of the deep stack, median over the stars, per plane; MATCH_SIGMA is the s at which that ratio is 1.
MATCH_SIGMA = 1.05
clip_far = cv2.dilate(dclip.astype(np.uint8), np.ones((25, 25), np.uint8)).astype(bool)
def peak_of(img, s, r=3, R=20):
    xi, yi = int(round(s['x'])), int(round(s['y'])); t = img[yi - R:yi + R + 1, xi - R:xi + R + 1]
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx, yy)
    return float(t[R - r:R + r + 1, R - r:R + r + 1].max() - np.median(t[(rr > 14) & (rr < 19)]))
msel = [s for s in stars if 40 < s['x'] < W2 - 40 and 40 < s['y'] < H2 - 40 and not clip_far[int(round(s['y'])), int(round(s['x']))] and s['nearest'] > 60 and s['hfr'] and s['hfr'] < 4.5 and s['peak'] > 2500]
width_match = dict(stars=len(msel), sigma_applied_px=MATCH_SIGMA, peak_short_over_deep={})
for p in range(4):
    row = {}
    for sg in (0.0, 0.5, 1.0, MATCH_SIGMA, 1.5, 2.0):
        Sb_ = a * (np.nan_to_num(S_[p]) if sg == 0 else cv2.GaussianBlur(np.nan_to_num(S_[p]), (0, 0), sg))
        r_ = [peak_of(Sb_, s) / peak_of(D[p], s) for s in msel if np.isfinite(peak_of(D[p], s)) and peak_of(D[p], s) > 300]
        row['%.2f' % sg] = float(np.median(r_)) if r_ else None
    width_match['peak_short_over_deep'][PLANE_NAMES[p]] = row
print('star width: peak(short blurred) / peak(deep), by blur sigma:', width_match)

# ---- stars that are unsaturated in both: aperture fluxes (green) ----
Gd = (D[1] + D[2]) / 2; Gs = (S_[1] + S_[2]) / 2
def ap_flux(img, x, y, ap=14):
    xi, yi = int(round(x)), int(round(y)); r = 28; h, w = img.shape
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return None
    t = img[yi - r:yi + r + 1, xi - r:xi + r + 1]
    if not np.isfinite(t).all(): return None
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]; rr = np.hypot(xx - x, yy - y)
    return float((t[rr <= ap] - np.median(t[(rr > 19) & (rr < 27)])).sum())
rat = []
clipd = cv2.dilate(dclip.astype(np.uint8), np.ones((29, 29), np.uint8)).astype(bool)
for s in stars:
    xi, yi = int(round(s['x'])), int(round(s['y']))
    if clipd[yi, xi] or s['nearest'] < 60 or s['flux'] < 150000: continue
    fd, fs = ap_flux(Gd, s['x'], s['y']), ap_flux(Gs, s['x'], s['y'])
    if fd and fs and fs > 0 and fd > 0: rat.append((fd / fs, fd))
rat = np.array(rat)
star_ratio = dict(stars=int(len(rat)), median=float(np.median(rat[:, 0])) if len(rat) else None, error=float(1.4826 * np.median(np.abs(rat[:, 0] - np.median(rat[:, 0]))) / np.sqrt(len(rat))) if len(rat) > 2 else None,
                  flux_weighted=float(rat[:, 1].sum() / (rat[:, 1] / rat[:, 0]).sum()) if len(rat) else None)
print('stars unsaturated in both (green aperture flux, deep / short):', star_ratio)

# ---- the blend ----
okS = np.isfinite(S_).all(0); okD = np.isfinite(D).all(0)
Ss = np.stack([a * S_[p] + bs[p] for p in range(4)])
# the short stack's pixel noise in these units, and its faint rim: the any-frame mask is wider than a star (each 20 s frame
# trails the star a few px its own way), so at the mask's rim the short stack must be used where its own signal is only a few
# hundred DN against a noise of about 120. There it is taken from a Gaussian-blurred copy (sigma 2 px), mixed by signal-to-noise:
# blurred below 5 sigma, sharp above 20 sigma. A plain local average of measured pixels; the star cores are far above this.
RIM_SIGMA, RIM_LO, RIM_HI = 2.0, 5.0, 20.0
noise_s = [a * s7s['noise_of_stack_dn_per_half_grid_px'][n_] for n_ in PLANE_NAMES]
rim_px = 0
for p in range(4):
    bl, _ = nblur(np.nan_to_num(Ss[p], nan=0.0), okS_ := np.isfinite(Ss[p]), RIM_SIGMA)
    t_ = np.clip((bl / noise_s[p] - RIM_LO) / (RIM_HI - RIM_LO), 0, 1)
    Ss[p] = np.where(okS_, t_ * Ss[p] + (1 - t_) * bl, np.nan).astype(np.float32)
# MATCHING THE STAR WIDTH. A replaced star core has to fit the deep star round it. Unblurred, the short stack's stars are 1.5 to
# 1.7 times taller and narrower than the deep stack's, and in 2 s the colours of a star sit side by side (the air's dispersion at
# 43 degrees altitude, about an arcsecond between red and blue): a sharp short core set into a deep star came out as a small
# green or blue dot with a dark ring round it, and held light that the deep star's wings hold again. So the short stack is
# blurred by a Gaussian of MATCH_SIGMA px (the width at which its unsaturated stars have the deep stars' peak), EXCEPT near pixels
# that were at the ceiling even in the short frames (the Trapezium and the few brightest stars; within 12 px, softened): there the
# short stack is used far out into the star's wings, nothing has to fit, and its sharpness is what separates the Trapezium.
near_white = cv2.dilate(sclip.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
keep_sharp = np.clip(cv2.GaussianBlur(near_white.astype(np.float32), (0, 0), 3.0), 0, 1)
for p in range(4):
    okS_ = np.isfinite(Ss[p]); bl, _ = nblur(np.nan_to_num(Ss[p], nan=0.0), okS_, MATCH_SIGMA)
    Ss[p] = np.where(okS_, keep_sharp * Ss[p] + (1 - keep_sharp) * bl, np.nan).astype(np.float32)
with np.errstate(invalid='ignore'):
    Lraw = np.fmax(np.nanmax(np.where(okD, D * FR, np.nan), axis=0), np.nanmax(np.where(okS, Ss * FR, np.nan), axis=0))
Ls, _ = nblur(np.nan_to_num(Lraw, nan=0.0), np.isfinite(Lraw), 1.0)
t = np.clip((Ls - L_LO) / (L_HI - L_LO), 0, 1); w_sig = t * t * (3 - 2 * t)
w = np.maximum(w_sig, dclip.astype(np.float32))
w = np.maximum(w, cv2.GaussianBlur(w, (0, 0), 0.8))          # the edge of the rule's mask softened by under a pixel, outward only
w[~okS] = 0.0
w = w.astype(np.float32)
hdr = np.where(okD[None], (1 - w)[None] * D + w[None] * np.where(okS[None], Ss, 0), np.nan).astype(np.float32)
only_short = ~okD & okS & (w_sig > 0.5)          # deep has no data but the short stack shows something bright: take the short stack there
hdr[:, only_short] = Ss[:, only_short]
# the white mask
white = (sclip & (w > 0)) | (dclip & ~okS)
white = cv2.dilate(white.astype(np.uint8), np.ones((3, 3), np.uint8))
white_soft = np.clip(cv2.GaussianBlur(white.astype(np.float32), (0, 0), 1.0) * 1.5, 0, 1); white_soft[white > 0] = 1.0
np.save(W('hdr_planes.npy'), hdr); np.save(W('hdr_w.npy'), w); np.save(W('hdr_white.npy'), white_soft.astype(np.float32))
n, lab, stats, cent = cv2.connectedComponentsWithStats((w > 0.5).astype(np.uint8), connectivity=8)
comp = sorted([dict(centre_half_px=[round(float(cent[i][0]), 1), round(float(cent[i][1]), 1)], pixels=int(stats[i, 4])) for i in range(1, n)], key=lambda d: -d['pixels'])
out = dict(expected_factor=40.0, per_plane=fits, factor_applied=a, measured_over_expected=a / 40.0, offsets_b_dn=dict(zip(PLANE_NAMES, bs)), stars_check=star_ratio,
           star_width_match=dict(width_match, kept_sharp_within_px_of_short_ceiling=12, pixels_kept_sharp=int((keep_sharp > 0.5).sum())),
           short_stack_rim=dict(noise_dn_in_deep_units=dict(zip(PLANE_NAMES, noise_s)), blur_sigma_px=RIM_SIGMA, blurred_below_snr=RIM_LO, sharp_above_snr=RIM_HI),
           blend=dict(signal_lo_dn=L_LO, signal_hi_dn=L_HI, near_ceiling_dn=NEAR_CEILING, ceiling_dn=CEILING_RAW - BLACK, mask_grown_px='one colour cell (step 7)', soft_sigma_px=0.8),
           pixels=dict(deep_near_ceiling_in_any_plane_of_any_frame=int(dclip.sum()), short_share_above_half=int((w > 0.5).sum()), short_share_above_zero=int((w > 0.001).sum()), short_share_one=int((w >= 0.999).sum()),
                       white_marked=int((white > 0).sum()), short_near_ceiling=int(sclip.sum()), deep_near_ceiling_without_short_data=int((dclip & ~okS).sum()), taken_from_short_where_deep_has_no_data=int(only_short.sum())),
           regions_with_short_share_above_half=len(comp), largest=comp[:12],
           brightest_values_dn=dict(deep_stack_max=float(np.nanmax(D)), hdr_max=float(np.nanmax(hdr)), hdr_green_p9999=float(np.nanpercentile((hdr[1] + hdr[2]) / 2, 99.99))))
json.dump(out, open(W('s9_hdr.json'), 'w'), indent=1)
print(json.dumps({k: out[k] for k in ('pixels', 'regions_with_short_share_above_half', 'brightest_values_dn')}))
print('largest', comp[:6])
