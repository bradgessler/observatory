"""Step 10: from the stack to pictures, every step one fixed formula applied to every pixel alike.

1. m1-stack.tif: the whole area that every used frame covers, linear, 16-bit RGB: R, mean of G1 and G2, B, times the
   camera's own daylight white balance (from the RAW; no colour matrix), times a scale, plus a pedestal. Orientation as
   the reference frame's sensor; step 8's sky map applies (offset given in the recipe).
2. The crop around M1: centred on M1's catalogue position (step 8), turned by whole quarter turns (no resampling) to
   bring north nearest to up.
   a. sky: one plane per colour (3 numbers) fitted to the sky AROUND the crop, well away from the nebula: stack pixels
      within SKY_BOX of M1 whose elliptical radius (step 9's shape: long axis at PA 127 deg, axis ratio 0.79) is
      SKY_EXCLUDE_PX or more along the long axis (3.4 arcmin; the nebula meets the sky's level at 230 px, 3.0 arcmin,
      step 9), stars masked, 3-sigma clipped, and subtracted. Nothing is fitted where the nebula is. This is the only
      surface anywhere in the pipeline, and it is in the picture only (the stack has one constant per colour per frame).
   b. colour: the camera's own matrix (rgb_xyz_matrix in the RAW, through sRGB primaries, rows normalised so that
      daylight white stays white), applied to the white-balanced camera RGB: linear sRGB.
   c. a Gaussian of BLUR_SIGMA px over the whole crop: the stars are about 7 px across (half-flux diameter 5.5 arcsec),
      so this widens them by about 10% and removes pixel-to-pixel noise finer than the telescope and air can deliver.
      Where the picture is faint (luminance below 60 DN, fading out by 150) and off the stars, a Gaussian of FAINT_BLUR
      px instead (6 px, 11 arcsec across, twice the seeing): step 9 found nothing in the nebula finer than about 25
      arcsec that repeats between the half stacks, so this takes away grain, not detail. Stars (a mask from the stack)
      keep the 1.5 px blur and their size.
   d. colour noise: where the picture is faint (luminance below 30 DN, fading out by 120 DN) each pixel keeps its own
      luminance and takes its colour difference (RGB - Y) from a copy blurred by CHROMA_SIGMA px that leaves star cores
      out. Without this the camera matrix turns the red plane's noise into coloured grain. Luminance is not changed by
      it. Where the sensor clipped the colour is unknown and is shown as white (no star clipped in these frames).
   e. stretch: arcsinh of the luminance, with the same gain for R, G and B of a pixel (colour ratios kept):
      out = OFFSET + (1 - OFFSET) * RGB * asinh(Y / SOFT) / (Y * asinh(WHITE / SOFT)), Y = 0.2126 R + 0.7152 G + 0.0722 B.
      WHITE = the 99.98th percentile of Y in the crop (the cores of the brightest stars); SOFT is near the nebula's
      own level (about 30 to 45 DN of luminance in its middle), so the oval sits in the middle of the curve. OFFSET keeps
      the sky's noise above zero for the levels that follow. Written as 16-bit PNGs for finish.py.
   The reference frame alone goes through the same steps (same plane, same numbers) for the comparison.
Adapted from this night's ngc1514/step10_render.py: the crop is centred on the catalogue position, the sky plane is
fitted around the crop outside an ellipse, the blur is 1.5 px (6 px where faint, off the stars), colour where faint comes
from a 32 px blur (stars keep their own, smoothed 6 px), and white comes from the stars."""
import json, os
import numpy as np, cv2, tifffile
from common import *

CROP_W, CROP_H = int(os.environ.get('M1_CROP_W', 800)), int(os.environ.get('M1_CROP_H', 600))   # final picture, px (after the turn)
SKY_EXCLUDE_PX = 260
SKY_BOX = (560, 460)                                          # half-size of the sky-fit window, stack px (x, y), larger than the crop
BLUR_SIGMA = float(os.environ.get('M1_BLUR', 1.5))
FAINT_BLUR = float(os.environ.get('M1_FAINT_BLUR', 6.0))     # px, where the picture is faint (4 was tried: grain read as texture)
FAINT_Y0, FAINT_Y1 = 60.0, 150.0
SOFT = float(os.environ.get('M1_SOFT', 30.0))
WHITE_PCT = 99.98
OFFSET = 0.20
CHROMA_SIGMA = float(os.environ.get('M1_CHROMA', 32.0))    # px of the native grid
CHROMA_Y0, CHROMA_Y1 = 30.0, 120.0
STAR_CHROMA = 6.0                                            # px: a star's own colour difference, lightly smoothed
TIF_PEDESTAL = 4000.0                                         # the sky in the vignetted corners sits up to a few hundred DN below the ring around M1
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
LUMA = np.array([0.2126, 0.7152, 0.0722])

st = np.load(W_('stack_mean.npy')); sg = np.load(W_('single_planes.npy')); cover = np.load(W_('cover.npy'))
s7 = jload('step7.json'); s8 = jload('step8_solve.json'); s9 = jload('step9_measure.json'); N = len(s7['frames'])
f0 = jload('step1.json')['frames'][0]
wb = np.array(f0['wb_daylight'][:3]) / f0['wb_daylight'][1]
cam_xyz = np.array(f0['rgb_xyz_matrix'])[:3]; cr = cam_xyz @ XYZ_RGB; RGB_CAM = np.linalg.inv(cr / cr.sum(1)[:, None])


def cam_rgb(P):
    return np.dstack([P[0] * wb[0], (P[1] + P[2]) / 2, P[3] * wb[2]]).astype(np.float64)


# ---- 1. the linear stack as a 16-bit TIF over the area every frame covers
full = cover == N
rows = np.where(full.mean(1) > 0)[0]; y0, y1 = rows[0], rows[-1] + 1; x0, x1 = 0, w2
while not full[y0:y1, x0:x1].all():          # trim the side with the most uncovered pixels until none is left
    sides = dict(top=(~full[y0, x0:x1]).sum(), bottom=(~full[y1 - 1, x0:x1]).sum(), left=(~full[y0:y1, x0]).sum(), right=(~full[y0:y1, x1 - 1]).sum())
    k = max(sides, key=sides.get)
    if k == 'top': y0 += 1
    elif k == 'bottom': y1 -= 1
    elif k == 'left': x0 += 1
    else: x1 -= 1
lin = cam_rgb(st)[y0:y1, x0:x1]
hi = float(np.nanmax(lin)); TIF_SCALE = float(np.floor((65000 - TIF_PEDESTAL) / hi * 100) / 100)
tif = np.clip(np.round(lin * TIF_SCALE + TIF_PEDESTAL), 0, 65535).astype(np.uint16)
os.makedirs(OUT, exist_ok=True)
tifffile.imwrite(os.path.join(OUT, 'm1-stack.tif'), tif, photometric='rgb', compression='zlib', metadata=None, software=False)
tif_info = dict(area_stack_px=dict(x0=int(x0), y0=int(y0), width=int(x1 - x0), height=int(y1 - y0)), pedestal=TIF_PEDESTAL, scale=TIF_SCALE,
                value='tif = round(linear * scale + pedestal); linear = DN of the 14-bit RAW scale per 15 s frame at the clearest frame\'s transparency at M1, times the daylight white balance; sky in a ring 6 to 11 arcmin around M1 at 0 in each frame',
                clipped_low=int((tif == 0).sum()), clipped_high=int((tif == 65535).sum()))
print('tif', tif.shape, 'scale', TIF_SCALE, 'area', tif_info['area_stack_px'], 'clipped low/high', tif_info['clipped_low'], tif_info['clipped_high'], flush=True)
del lin, tif

# ---- 2. the crop
north = s8['north_is_deg_clockwise_from_up']
K = int(np.round(north / 90.0)) % 4                        # np.rot90 k: counter-clockwise quarter turns; north goes from a to a - 90 k
north_after = (north - 90 * K + 180) % 360 - 180
pc = np.array(s8['target_catalogue']['stack_px']); cx, cy = int(round(pc[0])), int(round(pc[1]))
cw, ch = (CROP_H, CROP_W) if K % 2 else (CROP_W, CROP_H)  # size in stack px before the turn
cy0, cx0 = cy - ch // 2, cx - cw // 2
assert full[cy0:cy0 + ch, cx0:cx0 + cw].all()
ref = [r for r in jload('step2_stars.json') if r['stamp'] == s7['reference']][0]['stars']
smask = np.zeros((h2, w2), np.uint8)
for s in ref:
    cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
th = np.radians(s9['shape']['long_axis_image_deg']); AXR = s9['shape']['axis_ratio']
def ell_r(xx, yy):
    return np.hypot((xx - pc[0]) * np.cos(th) + (yy - pc[1]) * np.sin(th), (-(xx - pc[0]) * np.sin(th) + (yy - pc[1]) * np.cos(th)) / AXR)
# the sky-fit window (around and beyond the crop)
fy0, fy1, fx0, fx1 = cy - SKY_BOX[1], cy + SKY_BOX[1], cx - SKY_BOX[0], cx + SKY_BOX[0]
assert full[fy0:fy1, fx0:fx1].all()
fyy, fxx = np.mgrid[fy0:fy1, fx0:fx1]
FSKY = (smask[fy0:fy1, fx0:fx1] == 0) & (ell_r(fxx, fyy) >= SKY_EXCLUDE_PX)
FU, FV = (fxx - pc[0]) / 100.0, (fyy - pc[1]) / 100.0
yy, xx = np.mgrid[cy0:cy0 + ch, cx0:cx0 + cw]
U, V = (xx - pc[0]) / 100.0, (yy - pc[1]) / 100.0


def plane_fit(P):
    a = cam_rgb(P[:, fy0:fy1, fx0:fx1]); co_all = []
    for k in range(3):
        v = a[..., k][FSKY]; X = np.column_stack([np.ones(FSKY.sum()), FU[FSKY], FV[FSKY]]); keep = np.ones(len(v), bool)
        for _ in range(6):
            co, *_ = np.linalg.lstsq(X[keep], v[keep], rcond=None); res = v - X @ co; keep = np.abs(res) < 3 * res[keep].std()
        co_all.append(co.tolist())
    return co_all


# stars in the crop, found on the STACK's green (difference of Gaussians 1.5 - 6 px above 5 sigma, as step 9), a circle
# of 1 + sqrt(area) px each (about the star's own visible size), edge softened by a 1.5 px Gaussian: on them the wide
# blur does not apply and the colour is the star's own (its colour difference smoothed by STAR_CHROMA px only), so every
# star keeps its size and colour. The same mask serves the single frame.
_G = np.nan_to_num((st[1] + st[2]) / 2)[cy0 - 32:cy0 + ch + 32, cx0 - 32:cx0 + cw + 32].astype(np.float32)
_dog = cv2.GaussianBlur(_G, (0, 0), 1.5) - cv2.GaussianBlur(_G, (0, 0), 6.0)
_sd = clipped_stats(_dog[::3, ::3])[1]
_n, _lab, _stats, _cent = cv2.connectedComponentsWithStats((_dog > 5 * _sd).astype(np.uint8), connectivity=8)
_sm = np.zeros(_G.shape, np.uint8); N_STARS_MASKED = 0
for i in range(1, _n):
    if _stats[i, cv2.CC_STAT_AREA] < 3: continue
    cv2.circle(_sm, (int(round(_cent[i][0])), int(round(_cent[i][1]))), int(round(1 + np.sqrt(_stats[i, cv2.CC_STAT_AREA]))), 1, -1); N_STARS_MASKED += 1
STAR = np.clip(cv2.GaussianBlur(_sm.astype(np.float64), (0, 0), 1.5), 0, 1)[32:-32, 32:-32]
del _G, _dog, _lab


def render(P, planes_fit=None, blur=BLUR_SIGMA):
    co = planes_fit or plane_fit(P)
    a = cam_rgb(P[:, cy0:cy0 + ch, cx0:cx0 + cw])
    for k in range(3): a[..., k] -= co[k][0] + co[k][1] * U + co[k][2] * V
    a = a @ RGB_CAM.T
    if blur:
        a1 = cv2.GaussianBlur(a, (0, 0), blur)
        if FAINT_BLUR:
            # where the picture is faint (luminance, smoothed over 3 px, below FAINT_Y0 DN, fading out by FAINT_Y1) and off
            # the stars, a wider Gaussian of FAINT_BLUR px instead: step 9 found nothing real finer than 25 arcsec.
            # Stars keep the 1.5 px blur. The same weights for R, G and B.
            a3 = cv2.GaussianBlur(a, (0, 0), FAINT_BLUR)
            Ys = cv2.GaussianBlur(a1 @ LUMA, (0, 0), 3.0)
            wf = (np.clip((FAINT_Y1 - Ys) / (FAINT_Y1 - FAINT_Y0), 0, 1) * (1 - STAR))[..., None]
            a = wf * a3 + (1 - wf) * a1
        else:
            a = a1
    if CHROMA_SIGMA:
        # colour noise: each pixel keeps its own luminance Y and takes its colour difference D = RGB - Y from a
        # copy blurred by CHROMA_SIGMA px, where the blur leaves out pixels brighter than CHROMA_Y1 (star cores, so
        # their colour does not bleed out) and counts the rest equally (normalised convolution). Applied where the
        # picture is faint: full below CHROMA_Y0 DN of luminance (smoothed over 2 px), fading out by CHROMA_Y1, so
        # stars keep their own colour. Luminance is untouched: 0.2126 D_R + 0.7152 D_G + 0.0722 D_B = 0 for any D.
        sig = CHROMA_SIGMA
        Y = a @ LUMA; Ys = cv2.GaussianBlur(Y, (0, 0), 2.0)
        m = (Ys < CHROMA_Y1).astype(np.float64) * (1 - STAR)
        D = a - Y[..., None]
        Ds = cv2.GaussianBlur(D * m[..., None], (0, 0), sig) / np.maximum(cv2.GaussianBlur(m, (0, 0), sig), 1e-6)[..., None]
        w = np.clip((CHROMA_Y1 - Ys) / (CHROMA_Y1 - CHROMA_Y0), 0, 1)[..., None]
        Do = cv2.GaussianBlur(D, (0, 0), STAR_CHROMA)
        a = Y[..., None] + STAR[..., None] * Do + (1 - STAR[..., None]) * (w * Ds + (1 - w) * D)
    clip = (P[:, cy0:cy0 + ch, cx0:cx0 + cw].max(0) >= 0.8 * SAT_DN).astype(np.uint8)
    clip = cv2.GaussianBlur(cv2.dilate(clip, np.ones((5, 5), np.uint8)).astype(np.float64), (0, 0), 1.5)
    Y = a @ LUMA
    a = Y[..., None] + (a - Y[..., None]) * (1 - np.clip(clip, 0, 1))[..., None]
    return a, co


def stretch(a, white):
    Y = a @ LUMA
    with np.errstate(divide='ignore', invalid='ignore'):
        g = np.where(np.abs(Y) < 1e-9, 1.0 / SOFT, np.arcsinh(Y / SOFT) / Y) / np.arcsinh(white / SOFT)
    out = OFFSET + (1 - OFFSET) * a * g[..., None]
    return np.clip(out, 1 / 65535, 1)          # never 0: finish.py reads 0 in all three colours as "no data"


A, CO = render(st)
WHITE = float(np.percentile(A @ LUMA, WHITE_PCT))
B, _ = render(sg, CO)                                       # the reference frame alone: same sky planes, same numbers
for name, img in (('m1-stretched', A), ('single-stretched', B)):
    o = np.rot90(stretch(img, WHITE), K)
    cv2.imwrite(W_(name + '.png'), (o[..., ::-1] * 65535 + 0.5).astype(np.uint16))
# where M1's catalogue position lands in the picture (after the turn)
mx, my = pc[0] - cx0, pc[1] - cy0
w_, h_ = cw, ch
for _ in range(K): mx, my, w_, h_ = my, w_ - 1 - mx, h_, w_      # np.rot90 (k = 1): pixel (x, y) of a w-wide image goes to (y, w - 1 - x)
ER = ell_r(xx, yy)
Ycore = float(np.median((A @ LUMA)[(ER < 100) & (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0)]))
Yrim = float(np.median((A @ LUMA)[(ER >= 150) & (ER < 220) & (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0)]))
sky_left = [float(np.mean((A[..., k])[(ER >= SKY_EXCLUDE_PX) & (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0)])) for k in range(3)]
def outv(Y): return float(OFFSET + (1 - OFFSET) * np.arcsinh(Y / SOFT) / np.arcsinh(WHITE / SOFT))
info = dict(crop_stack_px=dict(x0=int(cx0), y0=int(cy0), width=int(cw), height=int(ch)), quarter_turns_counter_clockwise=K, north_deg_clockwise_from_up_before=north, north_deg_clockwise_from_up_after=north_after,
            east_deg_clockwise_from_up_after=(north_after - 90 + 180) % 360 - 180, picture_size=[CROP_W, CROP_H], m1_catalogue_in_picture_px=[float(mx), float(my)],
            field_arcmin=[round(CROP_W * float(np.mean(s8['scale_arcsec_per_px'])) / 60, 2), round(CROP_H * float(np.mean(s8['scale_arcsec_per_px'])) / 60, 2)],
            sky_planes_dn=dict(zip('RGB', CO)), sky_plane_terms='DN = c0 + c1 * (x - x_M1) / 100 + c2 * (y - y_M1) / 100, stack px, white-balanced camera RGB',
            sky_fit_window_stack_px=dict(x0=int(fx0), y0=int(fy0), width=int(fx1 - fx0), height=int(fy1 - fy0)), sky_exclude_elliptical_px=SKY_EXCLUDE_PX, sky_pixels=int(FSKY.sum()),
            sky_ramp_across_crop_dn={c: float(abs(CO[k][1]) * cw / 100 + abs(CO[k][2]) * ch / 100) for k, c in enumerate('RGB')},
            sky_left_in_crop_outside_ellipse_linear_srgb=sky_left,
            white_balance_daylight=wb.tolist(), rgb_cam=RGB_CAM.tolist(), blur_sigma_px=BLUR_SIGMA,
            stars_masked=N_STARS_MASKED, star_mask='difference of Gaussians (1.5 - 6 px) on the stack green above 5 sigma, circles of 1 + sqrt(area) px, softened by 1.5 px: there no wide blur, and the star\'s own colour difference smoothed by %.0f px' % STAR_CHROMA,
            faint_blur=dict(sigma_px=FAINT_BLUR, faded_between_dn=[FAINT_Y0, FAINT_Y1], formula="RGB' = w G(RGB, faint) + (1 - w) G(RGB, blur); w = clip((Y1 - Ys) / (Y1 - Y0), 0, 1) (1 - S), Ys = G(Y of the 1.5 px blur, 3 px), S = the star mask"),
            stretch=dict(white=WHITE, white_from='%.2fth percentile of luminance in the crop' % WHITE_PCT, soft=SOFT, offset=OFFSET, core_luminance_dn=Ycore, core_out=outv(Ycore), rim_luminance_dn=Yrim, rim_out=outv(Yrim)),
            chroma=dict(sigma_px=CHROMA_SIGMA, faded_between_dn=[CHROMA_Y0, CHROMA_Y1], formula="RGB' = Y + S G(D, star_px) + (1 - S) (w Ds + (1 - w) D); D = RGB - Y; Ds = G(D m) / G(m), G = Gaussian of sigma_px, m = (1 - S) where Y (2 px smoothed) < Y1; w = clip((Y1 - Ys) / (Y1 - Y0), 0, 1); S = the star mask", star_px=STAR_CHROMA),
            clipped_cores='colour difference set to 0 where any plane >= 0.8 x the ceiling (grown 2 px, softened 1.5 px); no star reached it', tif=tif_info)
jsave(info, 'step10.json')
print(json.dumps({k: v for k, v in info.items() if k not in ('rgb_cam', 'tif')}, indent=1))
