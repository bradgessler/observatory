"""Step 14: the files, into ~/.observatory/nights/2026-10-03-a6000/m42/.

  m42.png / .jpg               the centred HDR picture (deep stack + short stack), the well-covered field, half scale
  m42-core.png / .jpg          the Trapezium region from the short frames alone, at the sensor's own scale
  m42-mosaic.png / .jpg        the 2x2 mosaic (and the stray group) round it, north up, east left, 1.552 arcsec/px
  m42-linear.tif               the centred HDR result: linear, 32-bit float RGB, white balanced, zero taken off
  m42-coverage.tif             8-bit RGB, same grid: R = deep frames used at the pixel, G = share of the short stack
                               (0..255), B = flags (1 = white mark, 2 = second combine, 4 = near the ceiling in a deep frame)
  m42-mosaic-linear.tif        the mosaic, linear, 32-bit float RGB, white balanced, 1.552 arcsec/px (2x2 mean)
  m42-mosaic-coverage.tif      8-bit bit mask of the stacks that contribute (same grid as the mosaic pictures)
  m42-mosaic-diagnostic.png    a map (not a picture): footprints, and where two stacks share sky their difference
  extras: m42-starwhite.png / .jpg (white from the field stars), m42-colour-boost.png / .jpg (ONE global saturation
          factor, named), m42-mosaic-starwhite.jpg

Scale of m42: the HALF grid (0.776 arcsec/px), which is the grid the stacks are made on: each colour plane has
one sample per 2x2 sensor pixels, and the stars are 4.4 arcsec (5.6 half-grid px) across, so the half grid holds
everything the frames resolve, with nothing interpolated up.
Nothing is drawn on any picture. No data = black. JPEG quality 92, 4:4:4, no metadata; PNG 8-bit RGB, no metadata."""
import json, os, sys
import numpy as np, cv2, tifffile
from PIL import Image
from common import *
from render import *

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
# ---- the numbers of the pictures (all recorded in the recipe) ----
STRETCH = dict(white=40000.0, soft=5.0, pedestal=2.5, gamma=1.2, chroma_sigma=3.0)
GRAIN = dict(grain_sigma=3.0, s_lo=1.5, s_hi=8.0)
CORE_STRETCH = dict(white=650000.0, soft=120.0, pedestal=0.0, gamma=1.0, chroma_sigma=2.0)
CP_DEEP = 25.0
SAT_BOOST = 1.6
s1 = {f['stamp']: f for f in json.load(open(W('s1.json')))['frames']}; SEL = json.load(open(W('s5_select.json')))
wb = np.array([s1[u['stamp']]['wb'][:3] for u in SEL['deep']['used']]) / 1024.0
WB_R, WB_B = float(np.median(wb[:, 0])), float(np.median(wb[:, 2]))
Z = json.load(open(W('s13_mosaic.json')))['zero_taken_off_dn']; ZERO = np.array([Z['R'], Z['G'], Z['B']], np.float32)
HDR = json.load(open(W('s9_hdr.json'))); A_ = HDR['factor_applied']; B_ = HDR['offsets_b_dn']


def save(img8, stem, png=True):
    im = Image.fromarray(img8, 'RGB')
    if png: im.save(os.path.join(DEST, stem + '.png'), optimize=True)
    im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)


outs = {}
# =============== the centred picture ===============
Hh = np.load(W('hdr_planes.npy')); white = np.load(W('hdr_white.npy')); wshort = np.load(W('hdr_w.npy'))
n = np.load(W('deep_n.npy')); flag = np.load(W('deep_flag.npy')); ws = np.load(W('deep_wsum.npy')); fr = np.load(W('deep_flatref.npy')); dAB = np.load(W('deep_dAB.npy')); dclip = np.load(W('deep_clip.npy'))
rgb = np.dstack([Hh[0], (Hh[1] + Hh[2]) / 2, Hh[3]]) - ZERO
fl = (fr[1] + fr[2]) / 2; dg = (dAB[1] + dAB[2]) / 2
full = (flag == 1) & (ws >= 0.9 * ws.max()) & np.isfinite(dg)
sm = cv2.blur(np.nan_to_num(rgb[:, :, 1], nan=0.0), (65, 65)); faint = full & (sm <= np.percentile(sm[full], 25))
K = clipped_stats((dg * np.sqrt(ws) * fl)[faint][::3])[1]
noiseG = np.where(ws > 0, K / (np.sqrt(np.maximum(ws, 1e-6)) * fl), 1e3).astype(np.float32)
# the well-covered field: the rows and columns where at least 90% of the pixels have at least half of the frames
# (90, not 100: the hair's patch near the top edge, which only the frames of the shifted groups cover, stays in the picture)
thr = 0.5 * n.max(); good = n >= thr
rows = np.nonzero(good.mean(1) >= 0.90)[0]; cols = np.nonzero(good.mean(0) >= 0.90)[0]
y0, y1, x0, x1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
CROP = (slice(y0, y1), slice(x0, x1))
v = white_balance(rgb, WB_R, WB_B, white)
img = stretch(v[CROP], CP_DEEP, noise=noiseG[CROP], **STRETCH, **GRAIN)
save(img, 'm42')
okc = np.isfinite(v[CROP]).all(2)
PL = json.load(open(W('s10_place.json'))); Md = np.array(PL['affine_to_tangent_plane_arcsec']['deep'])
up = np.degrees(np.arctan2(-Md[0, 1], -Md[1, 1]))      # direction of 'up' in the picture, degrees east of north
outs['m42.png / .jpg'] = dict(what='the centred HDR picture: deep stack (20 s ISO 3200) with the short stack (2 s ISO 800) blended in where the deep frames were near the ceiling',
                              size_px=[int(img.shape[1]), int(img.shape[0])], pixel_scale_arcsec=HS, field_arcmin=[round(img.shape[1] * HS / 60, 1), round(img.shape[0] * HS / 60, 1)],
                              crop_of_stack_grid_px=[x0, y0, x1, y1], crop_rule='rows and columns in which at least 90%% of the pixels hold at least half of the %d deep frames' % int(n.max()),
                              orientation='the sensor\'s own: up is %.1f degrees %s of north, east is to the left (not mirrored)' % (abs(up), 'east' if up > 0 else 'west'),
                              frames_per_pixel=dict(min=int(n[CROP].min()), median=int(np.median(n[CROP])), max=int(n[CROP].max())), pixels_without_data=int((~okc).sum()),
                              pixels_at_255_in_all_channels=int((img == 255).all(2).sum()), median_8bit=[int(x) for x in np.median(img[okc][::7], axis=0)])
print('m42', outs['m42.png / .jpg'], flush=True)

# ---- the colour of the field stars (for the star-white extra) ----
D = np.load(W('deep_planes.npy')); stars = json.load(open(W('s8_stars_deep.json')))['stars']
clipd = cv2.dilate((dclip > 0).astype(np.uint8), np.ones((33, 33), np.uint8)).astype(bool)
Gd = (D[1] + D[2]) / 2
yy_, xx_ = np.mgrid[-28:29, -28:29]
rows_ = []
for s in stars:
    xi, yi = int(round(s['x'])), int(round(s['y']))
    if xi < 30 or yi < 30 or xi > W2 - 31 or yi > H2 - 31 or clipd[yi, xi] or s['nearest'] < 60 or s['flux'] < 20000: continue
    rr = np.hypot(xx_ - (s['x'] - xi), yy_ - (s['y'] - yi)); ap = rr <= 14; ann = (rr > 19) & (rr < 27); f = []
    for im_ in (D[0], Gd, D[3]):
        t = im_[yi - 28:yi + 29, xi - 28:xi + 29]
        if not np.isfinite(t).all(): f = None; break
        f.append(float((t[ap] - np.median(t[ann])).sum()))
    if f is None or min(f) <= 0: continue
    rows_.append(f)
rows_ = np.array(rows_); rg = rows_[:, 0] / rows_[:, 1]; bg = rows_[:, 2] / rows_[:, 1]
def cmean(x):
    keep = np.ones(len(x), bool)
    for _ in range(4): m = x[keep].mean(); sd = x[keep].std(); keep = np.abs(x - m) < 2.5 * sd
    return float(x[keep].mean()), float(x[keep].std()), int(keep.sum())
mr, sr, nr = cmean(rg); mb, sb, nb = cmean(bg)
SW_R, SW_B = 1.0 / mr, 1.0 / mb
starcol = dict(stars=int(len(rows_)), r_over_g=dict(mean=mr, std=sr, used=nr, median=float(np.median(rg))), b_over_g=dict(mean=mb, std=sb, used=nb, median=float(np.median(bg))), star_neutral_multipliers=dict(R=SW_R, B=SW_B),
               as_shot_multipliers=dict(R=WB_R, B=WB_B), colour_of_the_average_star_under_as_shot=dict(R_over_G=mr * WB_R, B_over_G=mb * WB_B))
print('field stars:', starcol, flush=True)
v2 = white_balance(rgb, SW_R, SW_B, white)
save(stretch(v2[CROP], CP_DEEP, noise=noiseG[CROP], **STRETCH, **GRAIN), 'm42-starwhite')
save(stretch(v[CROP], CP_DEEP, noise=noiseG[CROP], saturation=SAT_BOOST, **STRETCH, **GRAIN), 'm42-colour-boost')
outs['m42-starwhite.png / .jpg'] = dict(what='EXTRA: the same picture with white taken from the field stars: R x %.4f, B x %.4f (the multipliers that make the mean of %d unsaturated field stars of the deep stack neutral)' % (SW_R, SW_B, len(rows_)))
outs['m42-colour-boost.png / .jpg'] = dict(what='EXTRA: the same picture as m42 with ONE global saturation operation: every colour ratio moved away from grey by the factor %.2f in linear light (ratio -> 1 + %.2f x (ratio - 1)). m42.png is the unboosted version.' % (SAT_BOOST, SAT_BOOST), saturation_factor=SAT_BOOST)

# ---- linear file and coverage ----
lin = np.where(np.isfinite(v).all(2)[:, :, None], v, 0).astype(np.float32)
cov = np.zeros((H2, W2, 3), np.uint8); cov[:, :, 0] = n; cov[:, :, 1] = np.round(wshort * 255).astype(np.uint8)
cov[:, :, 2] = (white > 0.5) * 1 + (flag == 2) * 2 + (dclip > 0) * 4
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'm42-linear.tif'), lin, photometric='rgb', compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm42-coverage.tif'), cov, photometric='rgb', compression='zlib', metadata=None)
outs['m42-linear.tif'] = dict(what='the centred HDR result: linear, 32-bit float RGB (R, mean of the two greens, B), white balanced with the as-shot multipliers (divide R by %.4f and B by %.4f to undo), the zero of step 13 taken off, not stretched, not smoothed; white-marked pixels (ceiling even in the short frames) hold the largest of their three recorded values, unmultiplied, in all three' % (WB_R, WB_B),
                              units='DN of the 14-bit RAW scale per 20 s ISO 3200 frame under the centred run\'s clear sky, flat-fielded', size_px=[W2, H2], pixel_scale_arcsec=HS, grid='the half grid of the reference frame %s: pixel (X, Y) is centred on sensor pixel (2X + 0.5, 2Y + 0.5)' % SEL['deep']['reference'],
                              to_sky='xi (arcsec east of the Trapezium) = %.6f X %+.6f Y %+.3f; eta (arcsec north) = %.6f X %+.6f Y %+.3f; tangent plane about RA %.4f Dec %+.4f' % (*Md[0], *Md[1], TRAP_RA, TRAP_DEC),
                              no_data='0 in all three colours; m42-coverage.tif says where (R channel 0)', compression='zlib, lossless', max_value=float(lin.max()))
outs['m42-coverage.tif'] = dict(what='8-bit RGB, same grid as m42-linear.tif: R = how many deep frames were used at the pixel (0..%d); G = the short stack\'s share of the pixel, 0..255; B = flags: 1 white mark (near the ceiling even in a 2 s frame: colour unknown, value a lower limit), 2 from the second combine (flat leave-out pixels left in), 4 near the ceiling in at least one deep frame' % int(n.max()),
                                pixels=dict(no_data=int((n == 0).sum()), white_marked=int((white > 0.5).sum()), short_share_above_half=int((wshort > 0.5).sum()), near_ceiling_in_a_deep_frame=int((dclip > 0).sum())))
del lin, D, Gd

# =============== the Trapezium from the short frames ===============
C = np.load(W('core_planes.npy')); cnear = np.load(W('core_near.npy')); cj = json.load(open(W('s9b_core.json')))
crgb = np.dstack([A_ * C[0] + B_['R'], (A_ * C[1] + B_['G1'] + A_ * C[2] + B_['G2']) / 2, A_ * C[3] + B_['B']]) - ZERO
cw = cv2.dilate((cnear > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
cws = np.clip(cv2.GaussianBlur(cw.astype(np.float32), (0, 0), 1.5) * 1.5, 0, 1); cws[cw > 0] = 1
cv_ = white_balance(crgb, WB_R, WB_B, cws)
cimg = stretch(cv_, CP_DEEP, **CORE_STRETCH)
save(cimg, 'm42-core')
# the four stars: centroids of the four brightest separate peaks near the centre, their separations, and the dip between the closest pair
g = cv_[:, :, 1].copy(); gs = cv2.GaussianBlur(np.nan_to_num(g), (0, 0), 1.5)
c0 = CORE_PX_HALF = g.shape[0] // 2
sub = gs[c0 - 80:c0 + 80, c0 - 80:c0 + 80]
pk = (sub == cv2.dilate(sub, np.ones((9, 9), np.uint8))) & (sub > 0.02 * sub.max())
ys, xs = np.nonzero(pk); order = np.argsort(-sub[ys, xs])[:6]
peaks = []
for i in order:
    y_, x_ = ys[i] + c0 - 80, xs[i] + c0 - 80
    t = np.nan_to_num(g[y_ - 5:y_ + 6, x_ - 5:x_ + 6]); t = np.clip(t - np.median(g[y_ - 14:y_ + 15, x_ - 14:x_ + 15]), 0, None)
    yy2, xx2 = np.mgrid[-5:6, -5:6]; peaks.append(dict(x=float(x_ + (xx2 * t).sum() / t.sum()), y=float(y_ + (yy2 * t).sum() / t.sum()), peak_dn=float(gs[y_, x_])))
four = peaks[:4]
seps = []
for i in range(len(four)):
    for j in range(i + 1, len(four)):
        a, b = four[i], four[j]; d = np.hypot(a['x'] - b['x'], a['y'] - b['y'])
        nline = int(d) + 1; lx = np.linspace(a['x'], b['x'], nline); ly = np.linspace(a['y'], b['y'], nline)
        prof = cv2.remap(np.nan_to_num(g).astype(np.float32), lx.astype(np.float32)[None], ly.astype(np.float32)[None], cv2.INTER_LINEAR)[0]
        seps.append(dict(pair=[i, j], separation_arcsec=float(d * SCALE), lowest_between_over_fainter_peak=float(prof.min() / min(prof[0], prof[-1]))))
seps.sort(key=lambda s_: s_['separation_arcsec'])
# star width in the short stack near the Trapezium: FWHM of the faintest of the four along x and y (half-maximum crossing)
outs['m42-core.png / .jpg'] = dict(what='the Trapezium region from the 16 two-second frames alone, at the sensor\'s own scale', size_px=[int(cimg.shape[1]), int(cimg.shape[0])], pixel_scale_arcsec=SCALE, field_arcmin=round(cimg.shape[0] * SCALE / 60, 2),
                                   crop_sensor_px_of_reference_frame=cj['crop_sensor_px'], orientation=outs['m42.png / .jpg']['orientation'], stretch=CORE_STRETCH,
                                   units='the short stack x %.3f + the offsets of step 9, so the numbers are the deep stack\'s' % A_, white_marked_pixels=int(cw.sum()),
                                   trapezium=dict(peaks_found=len(peaks), four_brightest_px=four, separations=seps,
                                                  known_separations_arcsec='A-B 8.8, A-C 12.8, B-C 16.7 (approx.), C-D 13.4, A-D 21.5, B-D 19.3'))
print('core', json.dumps(outs['m42-core.png / .jpg']['trapezium']), flush=True)

# =============== the mosaic ===============
m = np.load(W('mosaic_rgb.npy')); nz = np.load(W('mosaic_noise.npy')); mw = np.load(W('mosaic_white.npy')); cpm = np.load(W('mosaic_cp.npy')); mcov = np.load(W('mosaic_cover.npy'))
grid = PL['grid']; PS = grid['pixel_scale_arcsec']; X0, Y0 = grid['trapezium_pixel']
m[nz <= 0] = np.nan
ys, xs = np.nonzero(nz > 0); mg = 48
mx0 = max((xs.min() - mg) // 4 * 4, 0); my0 = max((ys.min() - mg) // 4 * 4, 0); mx1 = min(-(-(xs.max() + mg) // 4) * 4, nz.shape[1]); my1 = min(-(-(ys.max() + mg) // 4) * 4, nz.shape[0])
m = m[my0:my1, mx0:mx1]; nz = nz[my0:my1, mx0:mx1]; mw = mw[my0:my1, mx0:mx1]; cpm = cpm[my0:my1, mx0:mx1]; mcov = mcov[my0:my1, mx0:mx1]
b = bin2(m); n2 = np.nan_to_num(bin2(np.where(nz > 0, nz, np.nan)), nan=1e3) * 0.6; w2 = np.nan_to_num(bin2(mw), nan=0.0); cp2 = np.nan_to_num(bin2(np.where(nz > 0, cpm, np.nan)), nan=300.0)
del m
# the mosaic: the same curve, with a pedestal of 14 DN instead of 2.5: the ground of the right-hand panel falls westward to 12 DN
# BELOW the zero (the zero is taken where two clear stacks overlap; the sky farther from the nebula is darker than that), and with
# the centred picture's pedestal that part would be cut to black
MOS_STRETCH = dict(STRETCH, chroma_sigma=2.5, pedestal=14.0); MOS_GRAIN = dict(grain_sigma=3.0, s_lo=1.5, s_hi=8.0)
mv = white_balance(b, WB_R, WB_B, w2)
mimg = stretch(mv, cp2, noise=n2, **MOS_STRETCH, **MOS_GRAIN)
save(mimg, 'm42-mosaic')
mv2 = white_balance(b, SW_R, SW_B, w2)
save(stretch(mv2, cp2, noise=n2, **MOS_STRETCH, **MOS_GRAIN), 'm42-mosaic-starwhite', png=False)
okm = np.isfinite(b).all(2)
cov2 = mcov[:mcov.shape[0] // 2 * 2, :mcov.shape[1] // 2 * 2].reshape(mcov.shape[0] // 2, 2, mcov.shape[1] // 2, 2)
cov2 = np.bitwise_or.reduce(np.bitwise_or.reduce(cov2, axis=3), axis=1).astype(np.uint8)
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'm42-mosaic-linear.tif'), np.where(okm[:, :, None], mv, 0).astype(np.float32), photometric='rgb', compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm42-mosaic-coverage.tif'), cov2, compression='zlib', metadata=None)
S13 = json.load(open(W('s13_mosaic.json')))
outs['m42-mosaic.png / .jpg'] = dict(what='the 2x2 mosaic and the stray group round the centred HDR picture, north up, east left', stacks=S13['stacks'], size_px=[int(mimg.shape[1]), int(mimg.shape[0])], pixel_scale_arcsec=2 * PS,
                                     field_arcmin=[round(mimg.shape[1] * 2 * PS / 60, 1), round(mimg.shape[0] * 2 * PS / 60, 1)], trapezium_at_px=[round((X0 - mx0) / 2, 1), round((Y0 - my0) / 2, 1)],
                                     crop_of_working_grid_px=[int(mx0), int(my0), int(mx1), int(my1)], scale_why='2 x 2 block mean of the 0.776 arcsec working grid: the stars are 4.4 to 5 arcsec across, so 1.55 arcsec still samples them (3 px), and the mean halves the grain of the thin panels',
                                     fraction_of_picture_with_data=float(okm.mean()), area_with_data_sq_deg=S13['area_with_data_sq_deg'], stretch=MOS_STRETCH, grain=MOS_GRAIN, colour_pedestal_dn=S13['colour_pedestal_dn'],
                                     median_8bit_where_data=[int(x) for x in np.median(mimg[okm][::7], axis=0)])
outs['m42-mosaic-linear.tif'] = dict(what='the mosaic: linear, 32-bit float RGB, as-shot white balance (R x %.4f, B x %.4f), panel backgrounds and the zero taken off, 2 x 2 block mean, not stretched, not smoothed; no data = 0' % (WB_R, WB_B), pixel_scale_arcsec=2 * PS,
                                     size_px=[int(mimg.shape[1]), int(mimg.shape[0])], to_sky='pixel (X, Y): xi = (%.1f - X) x %.3f arcsec east of the Trapezium, eta = (%.1f - Y) x %.3f arcsec north; tangent plane about RA %.4f Dec %+.4f' % ((X0 - mx0) / 2 - 0.25, 2 * PS, (Y0 - my0) / 2 - 0.25, 2 * PS, TRAP_RA, TRAP_DEC))
outs['m42-mosaic-coverage.tif'] = dict(what='8-bit bit mask, same grid as the mosaic pictures: which stacks contribute', bits=S13['bits'], note='128 = every contributing sample came from a second combine (flat leave-out pixels left in)', values_present=sorted(int(x) for x in np.unique(cov2)))
outs['m42-mosaic-starwhite.jpg'] = dict(what='EXTRA: the mosaic with white taken from the field stars (R x %.4f, B x %.4f)' % (SW_R, SW_B))
print('mosaic', outs['m42-mosaic.png / .jpg'], flush=True)
# =============== the diagnostic: footprints and seams (it is a map, not a picture of the sky) ===============
import warnings
import s13_combine as C13
R11 = json.load(open(W('s11_resample.json')))
Fd = 8; Hm, Wm = grid['height'], grid['width']; hs, ws_ = Hm // Fd, Wm // Fd
names = PL['images']
GG = np.full((len(names), hs, ws_), np.nan, np.float32); WT = np.zeros((len(names), hs, ws_), np.float32)
for i, k in enumerate(names):
    bx0, by0, bx1, by1 = R11[k]['bbox']
    rgbk = np.load(W('grid/%s_rgb.npy' % k)); iv = np.load(W('grid/%s_invvar.npy' % k)); fe = np.load(W('grid/%s_feather.npy' % k)); qk = np.load(W('grid/%s_q.npy' % k))
    gk = rgbk[:, :, 1].copy(); bgk = C13.background(k, gk.shape, bx0, by0)
    if bgk is not None: gk -= bgk[:, :, 1]
    okk = np.isfinite(rgbk).all(2) & (iv > 0) & (fe > 0)
    fullg = np.full((Hm, Wm), np.nan, np.float32); fullg[by0:by1, bx0:bx1] = np.where(okk, gk, np.nan)
    wfull = np.zeros((Hm, Wm), np.float32); wfull[by0:by1, bx0:bx1] = np.where(okk, fe * iv * qk, 0)
    blk = fullg[:hs * Fd, :ws_ * Fd].reshape(hs, Fd, ws_, Fd).transpose(0, 2, 1, 3).reshape(hs, ws_, -1)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore'); med = np.nanmedian(blk, axis=2)
    med[np.isfinite(blk).mean(2) < 0.5] = np.nan
    GG[i] = med; WT[i] = wfull[:hs * Fd, :ws_ * Fd].reshape(hs, Fd, ws_, Fd).mean((1, 3)); WT[i][~np.isfinite(med)] = 0
    del rgbk, iv, fe, qk, fullg, wfull, blk
n_img = (WT > 0).sum(0)
order = np.argsort(-WT, axis=0); first = order[0]; second = order[1]
gf = np.take_along_axis(np.nan_to_num(GG, nan=0.0), first[None], 0)[0]; gs_ = np.take_along_axis(np.nan_to_num(GG, nan=0.0), second[None], 0)[0]
two = n_img >= 2
Dd = np.where(two, gs_ - gf, 0).astype(np.float32)
Ds = nblur(Dd, two, 3.0)
GAIN = 4.0
grey = np.clip(128 + GAIN * Ds, 0, 255)
TONE = dict(deep=(70, 70, 70), p00=(110, 40, 40), p10=(100, 95, 30), p11=(45, 55, 125), p01=(105, 40, 105), stray1=(40, 105, 40))
diag = np.zeros((hs, ws_, 3), np.uint8)
diag[two] = np.repeat(grey[two][:, None], 3, 1).astype(np.uint8)
one = n_img == 1
for i, k in enumerate(names): diag[one & (first == i)] = TONE.get(k, (90, 90, 90))
Image.fromarray(diag, 'RGB').save(os.path.join(DEST, 'm42-mosaic-diagnostic.png'), optimize=True)
absd = np.abs(Ds[two])
outs['m42-mosaic-diagnostic.png'] = dict(what='NOT a picture of the sky: a map of the mosaic\'s footprints and seams. Where two or more stacks have data: mid grey (128) = they agree; brighter = the lighter-weighted of the two heaviest stacks is brighter than the heaviest, darker = fainter; %g grey levels per DN of green, so black and white are -32 and +32 DN (8 x 8 px medians, Gaussian of 3 px; panel backgrounds of step 12 already taken off). Where only one stack has data: a flat dim colour that names it. No data: black.' % GAIN,
                                         size_px=[ws_, hs], pixel_scale_arcsec=Fd * PS, gain_grey_levels_per_dn=GAIN, tones_rgb=TONE, overlap_fraction_of_data=float(two.sum() / max((n_img > 0).sum(), 1)),
                                         difference_in_overlaps_dn=dict(median_abs=float(np.median(absd)), p90_abs=float(np.percentile(absd, 90)), p99_abs=float(np.percentile(absd, 99)), fraction_beyond_5dn=float((absd > 5).mean()), fraction_beyond_10dn=float((absd > 10).mean())))
print('diagnostic', outs['m42-mosaic-diagnostic.png']['difference_in_overlaps_dn'], flush=True)
json.dump(dict(outputs=outs, stretch=STRETCH, grain=GRAIN, core_stretch=CORE_STRETCH, colour_pedestal_deep_dn=CP_DEEP, saturation_boost_of_the_extra=SAT_BOOST, white_balance=dict(as_shot=dict(R=WB_R, B=WB_B), star_white=dict(R=SW_R, B=SW_B)),
               star_colour=starcol, zero_dn=Z, noise_green_K=float(K), destination=DEST), open(W('s14_deliver.json'), 'w'), indent=1)
