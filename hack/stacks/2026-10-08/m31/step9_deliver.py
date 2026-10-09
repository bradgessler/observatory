"""Step 9: crop, zero, colour, the 16-bit linear stack, the stretch, the finish, the pictures, and the numbers.

Crop: the largest rectangle in which every pixel is covered by at least 80% of the used frames.
Zero: THE ABSOLUTE ZERO IS UNKNOWN: the galaxy fills the frame and the sky under it cannot be measured. One constant
per colour plane is subtracted so that the darkest part of the field sits at zero: the median of each plane over
the pixels where the smoothed green (1/8 scale, Gaussian sigma 4 there = 64 sensor px) is in its lowest 1%, at least
EDGE_KEEP plane px inside the crop (the flat is least sure at the very edge). The same pixels for all four planes, so
that region is neutral by construction. How much galaxy is still in it is estimated (not subtracted) from the
galaxy's own fall-off along the minor axis.
Colour: G = mean of G1 and G2; R and B times the camera's as-shot white balance from the RAWs (median over the used
frames). No colour matrix.
Linear stack (m31-stack.tif): R, G, B white balanced, DN above the zero region + PEDESTAL, 16-bit, the crop above.
Stretch (after hack/stacks/2026-10-03/m31/render.py): arcsinh on brightness (green) about the zero level,
f = (asinh(v / soft) - asinh(-floor / soft)) / (asinh(white / soft) - asinh(-floor / soft)), v clipped to -floor..white,
so that noise below the zero is kept down to -floor (about 3 sigma of the stack) instead of being cut at the zero
(cut pixels would be exact black, which the finish tool reads as 'no data'); colour ratios kept, taken from a copy
blurred with a Gaussian of CHROMA_SIGMA plane px, ratio_c = (C_c + colour_pedestal) / (C_g + colour_pedestal); then the
sRGB transfer curve; 16-bit. The white point is set
so that the brightest smoothed pixel of the nucleus lands at a fraction of white chosen from CORE_AT_LIST (the first that
leaves the nucleus at 250 of 255 or less after the finish): the core is NOT clipped (the RAWs
never came near the sensor's ceiling there, step 2), stars brighter than that are.
Finish: finish16.py (the finish-pictures tool, reading 16 bits) with FINISH below. Native scale (one pixel per 2 x 2
colour cell, 0.776 arcsec) and a 1600 px wide copy (area average down). JPEGs written by Pillow with no metadata."""
import json, os, sys, subprocess, datetime
import numpy as np, cv2, tifffile
from PIL import Image
from common import *
import measure, render9

VER = os.environ.get('M31_VERSION', 'F')
COVER_MIN_FRACTION = 0.80
EDGE_KEEP = 100
PEDESTAL = 1000.0
CHROMA_SIGMA = 2.0                       # plane px (4 sensor px, as on 3 October)
STRETCH = dict(soft=float(os.environ.get('M31_SOFT', '45')), floor=float(os.environ.get('M31_FLOOR', '20')), colour_pedestal=float(os.environ.get('M31_CPED', '10')))
CORE_AT_LIST = [float(v) for v in os.environ.get('M31_CORE_AT', '0.85 0.82 0.79 0.76 0.73 0.70 0.67').split()]
# soft 45 as on 3 October: soft 25 (tried first) compressed the bulge into its glow and showed more grain in the faint
# parts. The finish options were chosen by looking and by skycheck.py (darkest 0-10% and 10-40% within about 1 of neutral, as the 3 October core):
# neutral band 0-40 left the 10-40% band at R-G +1.9, 10-50 at +1.1, 20-60 at +0.5 (the faint glow grows warmer as it
# brightens, so the band that is made grey has to reach into it)
FINISH = os.environ.get('M31_FINISH', '--neutral --neutral-band 20 60 --grey-below 3 10 --black-pct 2 --black 0.03 --white-abs 1.0 --gamma 1.2 --curve 0.45 --sat 1.2 --quiet 2.5 14 48 --chroma-blur 5').split()
DEST = os.environ.get('M31_DEST', OUT)
os.makedirs(DEST, exist_ok=True)

sel = jload('step7_select.json'); USE = sel['used']; USED = [u['stamp'] for u in USE]; N = len(USED)
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
s2 = {f['stamp']: f for f in jload('step2.json')['frames']}
Q = jload('step5_quality.json'); q = {o['stamp']: o for o in Q['quality']}
T4 = jload('step4_transforms.json'); tr = {o['stamp']: o for o in T4['transforms']}
s8 = jload('step8_%s.json' % VER)
DARK = jload('step2.json')['dark_corner']


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
    return int(x0), int(y0), int(x1), int(y1)


st = np.load(W('%s_mean.npy' % VER)); cover = np.load(W('%s_cover.npy' % VER)); used = np.load(W('%s_used.npy' % VER))[1]
rect = cover_rect(cover, int(np.ceil(COVER_MIN_FRACTION * N))); x0, y0, x1, y1 = rect
c = st[:, y0:y1, x0:x1].copy(); h, w = c.shape[1:]
print('crop (plane px) x %d..%d y %d..%d = %d x %d (sensor %d x %d)' % (x0, x1, y0, y1, w, h, 2 * w, 2 * h), flush=True)

# ---------------- zero ----------------
G = (c[1] + c[2]) / 2
small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
sm = cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 4)
okz = np.zeros_like(sm, bool); e = EDGE_KEEP // 8; okz[e:-e, e:-e] = True
thr = np.percentile(sm[okz], 1.0)
dark = cv2.resize(((sm <= thr) & okz).astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
lev = [float(clipped_stats(c[p][dark][::2])[0]) for p in range(4)]
dy, dx = np.nonzero(dark); zc = (float(np.median(dx)), float(np.median(dy)))
print('zero region: %d px, centre (crop px) %s; levels R G1 G2 B %s' % (dark.sum(), np.round(zc).astype(int).tolist(), np.round(lev, 2).tolist()), flush=True)
c -= np.array(lev, np.float32)[:, None, None]

# ---------------- nucleus ----------------
nref = np.array(s1[REF_STAMP]['nucleus_sensor_xy']); npx = (nref - 0.5) / 2 - np.array([x0, y0])
G = (c[1] + c[2]) / 2
r_ = 60; ax, ay = int(round(npx[0])), int(round(npx[1]))
box = cv2.GaussianBlur(cv2.medianBlur(G[ay - r_:ay + r_, ax - r_:ax + r_], 5), (0, 0), 1.5)
yy, xx = np.unravel_index(np.argmax(box), box.shape); nuc = (ax - r_ + xx, ay - r_ + yy)
gnuc = float(box.max())
# sub-pixel: centroid of the top of the smoothed peak
t = box[max(yy - 4, 0):yy + 5, max(xx - 4, 0):xx + 5]; t = np.clip(t - 0.8 * t.max(), 0, None); Yt, Xt = np.mgrid[0:t.shape[0], 0:t.shape[1]]
nuc_sub = (ax - r_ + max(xx - 4, 0) + float((t * Xt).sum() / t.sum()), ay - r_ + max(yy - 4, 0) + float((t * Yt).sum() / t.sum()))
print('nucleus at crop px (%.2f, %.2f); smoothed green peak %.0f DN above the zero' % (*nuc_sub, gnuc), flush=True)

# ---------------- colour, linear TIFF ----------------
wb = np.median(np.array([s1[s]['wb'] for s in USED]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
rgb = np.dstack([c[0] * wb_r, (c[1] + c[2]) / 2, c[3] * wb_b]).astype(np.float32)
t16 = np.clip(np.round(rgb + PEDESTAL), 0, 65535).astype(np.uint16)
tifffile.imwrite(os.path.join(DEST, 'm31-stack.tif'), t16, photometric='rgb', compression='zlib', metadata=None)
clip16 = int((rgb + PEDESTAL >= 65535).any(2).sum())
print('m31-stack.tif written: %d x %d, white balance R x %.4f B x %.4f, pixels at 65535 in any channel %d' % (w, h, wb_r, wb_b, clip16), flush=True)

# ---------------- stretch and finish (render9.py) ----------------
fin16, fin8, stretch_rec, core = render9.picture(rgb, nuc_sub, gnuc, W('m31-finished'), FINISH, CORE_AT_LIST, STRETCH['soft'], STRETCH['floor'], STRETCH['colour_pedestal'], CHROMA_SIGMA, log=lambda m: print(m, flush=True))
STRETCH.update(stretch_rec); stem = W('m31-finished')
p1, p2, sky = render9.save_jpegs(fin16, DEST, 'm31')
print(sky, flush=True)
print('core in the finished picture:', core, flush=True)

# ---------------- numbers ----------------
def cs(a): return clipped_stats(a)[1]
pair = np.load(W('%s_pairdiff.npy' % VER))[:, y0:y1, x0:x1]; odd = np.load(W('%s_odd.npy' % VER))[:, y0:y1, x0:x1]; even = np.load(W('%s_even.npy' % VER))[:, y0:y1, x0:x1]
hd = (odd - even) / 2
usedc = used[y0:y1, x0:x1]; coverc = cover[y0:y1, x0:x1]
# the faintest clean 250 x 250 patch near the zero region, all frames in it
best = None
for py in range(0, h - 250, 25):
    for px in range(0, w - 250, 25):
        if coverc[py:py + 250, px:px + 250].min() < N: continue
        lv = float(np.median(G[py:py + 250:3, px:px + 250:3]))
        if best is None or lv < best[0]: best = (lv, px, py)
lvp, px, py = best; P = (slice(py, py + 250), slice(px, px + 250))
def to_rgb(a): return [a[0] * wb_r, (a[1] + a[2]) / 2, a[3] * wb_b]
one = [cs(v[P]) for v in to_rgb(pair)]; stk = [cs(v[P]) for v in to_rgb(hd)]
one_p = [cs(pair[p][P]) for p in range(4)]; stk_p = [cs(hd[p][P]) for p in range(4)]
noise = dict(where='250 x 250 px (colour-cell grid; 500 x 500 sensor px) patch, crop px x %d..%d y %d..%d: the faintest place covered by all %d frames; galaxy there %.1f DN (green) above the zero region' % (px, px + 250, py, py + 250, N, lvp),
             how='3-sigma clipped standard deviation. One frame: two neighbouring frames (%s, %s) through the whole pipeline, their difference / sqrt 2 (sky and galaxy cancel). Stack: (stack of the odd frames - stack of the even frames) / 2.' % tuple(s8['pair']),
             one_frame_planes=dict(zip(PLANE_NAMES, [round(v, 2) for v in one_p])), stack_planes=dict(zip(PLANE_NAMES, [round(v, 2) for v in stk_p])),
             one_frame_white_balanced=dict(zip('RGB', [round(v, 2) for v in one])), stack_white_balanced=dict(zip('RGB', [round(v, 2) for v in stk])),
             improvement=dict(zip('RGB', [round(a / b, 2) for a, b in zip(one, stk)])), ideal_sqrt_of_summed_weights=round(float(np.sqrt(sum(u['weight'] for u in USE))), 2),
             raw_plane_single_frame_dn=dict(zip(PLANE_NAMES, [round(s1[REF_STAMP]['corners'][DARK]['std'][p], 1) for p in range(4)])),
             raw_plane_note='reference frame, darkest corner, colour-plane pixels straight from the RAW (no resampling, no flat)')
print('noise', json.dumps(noise), flush=True)
del pair, odd, even, hd
# stars in the stack (green), the quality stars of step 5
rows = []
for xy in Q['star_xy'].values():
    sx, sy = (xy[0] - 0.5) / 2 - x0, (xy[1] - 0.5) / 2 - y0
    a = measure.star(np.ascontiguousarray(rgb[:, :, 1]), sx, sy, ap=14, sw=5.0, ann=(19, 27))
    if a and a['fwhm']: rows.append(a)
ecoh = np.mean([(r_['sig_major'] ** 2 - r_['sig_minor'] ** 2) / (r_['sig_major'] ** 2 + r_['sig_minor'] ** 2) * np.exp(2j * np.radians(r_['theta'])) for r_ in rows])
PX = 2 * SCALE
stars = dict(stars=len(rows), half_flux_diameter_arcsec=round(float(np.median([r_['hfd'] for r_ in rows])) * PX, 2), fwhm_arcsec=round(float(np.median([r_['fwhm'] for r_ in rows])) * PX, 2),
             fwhm_px=round(float(np.median([r_['fwhm'] for r_ in rows])), 2), elongation=round(float(np.median([r_['elong'] for r_ in rows])), 3), common_direction_ellipticity=round(float(abs(ecoh)), 3),
             single_frames_used=dict(half_flux_diameter_arcsec_median=round(float(np.median([q[s]['hfd_arcsec'] for s in USED])), 2), best=round(min(q[s]['hfd_arcsec'] for s in USED), 2), worst=round(max(q[s]['hfd_arcsec'] for s in USED), 2),
                                     elongation_median=round(float(np.median([q[s]['elong_median'] for s in USED])), 3)),
             note='half-flux diameter in a 14 px (colour-cell grid) aperture; FWHM from the ring-median profile; the box measured 5.6 arcsec on its 960 px JPEG copy')
print('stars', json.dumps(stars), flush=True)
# motion
def tsec(s): return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
lst = [tr[s] for s in USED]; sh = np.array([o['shift_at_centre_px'] for o in lst]); rot = np.array([o['rotation_deg'] for o in lst])
series = [tr[s] for s in USED if s >= '20261009-062555']; shs = np.array([o['shift_at_centre_px'] for o in series]); rots = np.array([o['rotation_deg'] for o in series])
span = tsec(s1[series[-1]['stamp']]['t']) - tsec(s1[series[0]['stamp']]['t'])
motion = dict(rotation_range_used_deg=[round(float(rot.min()), 4), round(float(rot.max()), 4)], series_first_last=[series[0]['stamp'], series[-1]['stamp']], series_minutes=round(span / 60, 2),
              series_rotation_deg=round(float(abs(rots[-1] - rots[0])), 3), rotation_deg_per_minute=round(float(abs(rots[-1] - rots[0]) / span * 60), 4),
              series_drift_net_px=round(float(np.hypot(*(shs[-1] - shs[0]))), 1), series_drift_path_px=round(float(np.hypot(*np.diff(shs, axis=0).T).sum()), 1),
              shift_range_used_x_px=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], shift_range_used_y_px=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)],
              corner_smear_if_not_rotated_px=round(float(np.radians(abs(rot.max() - rot.min())) * np.hypot(3012, 2012)), 1),
              registration_wrms_px=[round(min(o['wrms_px'] for o in lst if o['stamp'] != REF_STAMP), 3), round(max(o['wrms_px'] for o in lst), 3)],
              scale_if_left_free=[round(min(o['similarity_scale'] for o in lst), 5), round(max(o['similarity_scale'] for o in lst), 5)])
print('motion', json.dumps(motion), flush=True)
# clipping in the RAWs at the nucleus
nmax = {s: max(s2[s]['nucleus_max_dn_above_black_repaired'][1:3]) for s in USED}
clip = dict(ceiling='raw values of 16000 or more (black 512: about 15,500 DN above black)', nucleus_region='within 200 sensor px of the nucleus, hot pixels and spikes left out',
            pixels_at_ceiling_near_nucleus_used_frames=int(sum(sum(s2[s]['ceiling_pixels_near_nucleus']) for s in USED)),
            brightest_green_pixel_near_nucleus_dn=dict(median=float(np.median(list(nmax.values()))), highest=float(max(nmax.values()))), fraction_of_ceiling=round(float(max(nmax.values())) / 15500, 2),
            stack_nucleus_smoothed_green_dn=round(gnuc, 1), core_in_finished_picture=core,
            stars_at_ceiling='green pixels at the ceiling over the whole frame (bright stars): %d to %d per plane per used frame' % (min(s2[s]['ceiling_pixels_whole_frame'][1] for s in USED), max(s2[s]['ceiling_pixels_whole_frame'][1] for s in USED)))
# the glow, 244 px blocks (488 sensor px), DN above the zero, white balanced
b = 244; ny, nx = h // b, w // b
bm = lambda a: np.median(a[:ny * b, :nx * b].reshape(ny, b, nx, b).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
gb, rb_, bb_ = [bm(rgb[:, :, k_]).astype(np.float64) for k_ in (1, 0, 2)]
glow = dict(block_px=b, green_dn=np.round(gb, 1).tolist(), red_minus_green_dn=np.round(rb_ - gb, 1).tolist(), blue_minus_green_dn=np.round(bb_ - gb, 1).tolist())
# the galaxy still in the zero region: fall-off along the minor axis, from the shape of the glow
mask = (cv2.GaussianBlur(G, (0, 0), 8) > np.percentile(G, 70)).astype(np.float32)
Yg, Xg = np.mgrid[0:h, 0:w]; m0 = mask.sum(); cx_, cy_ = nuc_sub
mxx = (mask * (Xg - cx_) ** 2).sum() / m0; myy = (mask * (Yg - cy_) ** 2).sum() / m0; mxy = (mask * (Xg - cx_) * (Yg - cy_)).sum() / m0
pa_major = 0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy)); axis_ratio = float(np.sqrt((mxx + myy - np.hypot(mxx - myy, 2 * mxy)) / (mxx + myy + np.hypot(mxx - myy, 2 * mxy))))
ang = np.degrees(np.arctan2(Yg - cy_, Xg - cx_)); rad = np.hypot(Xg - cx_, Yg - cy_)
Gs = cv2.medianBlur(G, 5)
prof = []
zr = float(np.hypot(zc[0] - cx_, zc[1] - cy_)); za = float(np.degrees(np.arctan2(zc[1] - cy_, zc[0] - cx_)))
for side in (pa_major + 90, pa_major - 90):
    dang = np.abs((ang - side + 180) % 360 - 180) < 12
    row = []
    for r0 in range(200, 2000, 50):
        m = dang & (rad >= r0) & (rad < r0 + 50)
        if m.sum() > 300: row.append((r0 + 25, float(np.median(Gs[m]))))
    prof.append(row)
from scipy.optimize import curve_fit
fit = None
try:
    pts = [p_ for row in prof for p_ in row if 500 <= p_[0] <= 1700]
    rr_, vv = np.array([p_[0] for p_ in pts], float), np.array([p_[1] for p_ in pts], float)
    po, pc = curve_fit(lambda r, A, hh, Z: A * np.exp(-r / hh) - Z, rr_, vv, p0=[200, 300, 2], maxfev=20000)
    fit = dict(model='green(r) = A exp(-r / h) - Z along the minor axis (both sides, 24 degree wedges, 5x5 median, r 500 to 1700 px of the colour-cell grid); Z = the galaxy still in the zero region if the glow kept falling that way',
               A_dn=round(float(po[0]), 1), h_px=round(float(po[1]), 1), h_arcmin=round(float(po[1]) * PX / 60, 2), Z_dn=round(float(po[2]), 2), Z_error_dn=round(float(np.sqrt(pc[2, 2])), 2),
               rms_dn=round(float(np.sqrt(np.mean((vv - (po[0] * np.exp(-rr_ / po[1]) - po[2])) ** 2))), 2))
except Exception as ex:
    fit = dict(failed=str(ex))
zero_unc = dict(zero_region_distance_from_nucleus_px=round(zr, 0), zero_region_distance_arcmin=round(zr * PX / 60, 1), zero_region_direction_deg_from_crop_x=round(za, 1),
                major_axis_angle_deg_from_crop_x=round(float(pa_major), 1), glow_axis_ratio=round(axis_ratio, 3), minor_axis_profiles_green_dn=[[[int(a_), round(v_, 2)] for a_, v_ in row] for row in prof], exponential_fit=fit,
                green_sky_level_at_zero_region_dn=round((lev[1] + lev[2]) / 2, 1))
print('zero uncertainty', json.dumps({k: v for k, v in zero_unc.items() if k != 'minor_axis_profiles_green_dn'}), flush=True)
jdump(dict(version=VER, rect_plane_px=rect, size_px=[w, h], zero=dict(levels_subtracted_dn=dict(zip(PLANE_NAMES, [round(v, 3) for v in lev])), region_px=int(dark.sum()), region_centre_crop_px=[round(v) for v in zc],
                                                                     uncertainty=zero_unc),
           nucleus_crop_px=[round(v, 2) for v in nuc_sub], nucleus_green_dn=gnuc, wb=dict(R=wb_r, B=wb_b, raw=[float(v) for v in wb]), pedestal=PEDESTAL, tiff_pixels_at_65535=clip16,
           stretch=STRETCH, finish=FINISH, finish_record=json.load(open(stem + '.json')), skycheck=sky.strip().split('\n'),
           numbers=dict(noise=noise, stars_in_the_stack=stars, motion=motion, raw_clipping=clip, glow_blocks=glow)), 'step9.json')
