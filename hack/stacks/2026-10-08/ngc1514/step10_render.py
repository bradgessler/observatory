"""Step 10: from the stack to pictures, every step one fixed formula applied to every pixel alike.

1. ngc1514-stack.tif: the whole area that every used frame covers, linear, 16-bit RGB: R, mean of G1 and G2, B, times
   the camera's own daylight white balance (from the RAW; no colour matrix), times a scale, plus a pedestal.
   Orientation as the reference frame's sensor; step 8's sky map applies (offset given in the recipe).
2. The crop around NGC 1514: centred on the central star (step 8), turned by whole quarter turns (no resampling) to
   bring north nearest to up.
   a. sky: one plane per colour (3 numbers) fitted to the sky in the crop farther than SKY_EXCLUDE_PX from the central
      star (101 arcsec; the shell's light has faded to the sky's level by about 95 arcsec, step 9), stars masked,
      3-sigma clipped, and subtracted. Nothing is fitted where the nebula is.
   b. colour: the camera's own matrix (rgb_xyz_matrix in the RAW, through sRGB primaries, rows normalised so that
      daylight white stays white), applied to the white-balanced camera RGB: linear sRGB.
   c. a Gaussian of BLUR_SIGMA px over the whole crop: the stars are about 6.3 px across (half-flux diameter 4.9
      arcsec), so this widens them by a few percent and removes pixel-to-pixel noise finer than the telescope and air
      can deliver.
   d. colour noise: where the picture is faint (luminance below 30 DN, fading out by 120 DN) each pixel keeps its own
      luminance and takes its colour difference (RGB - Y) from a copy blurred by CHROMA_SIGMA px that leaves star cores
      out. Without this the camera matrix turns the red plane's noise into coloured grain, and the levels' clip at
      black then tints the sky red. Luminance is not changed by it. Where the sensor clipped (the central star's core
      in green and blue) the colour is unknown and is shown as white (colour difference set to zero).
   e. stretch: arcsinh of the luminance, with the same gain for R, G and B of a pixel (colour ratios kept):
      out = OFFSET + (1 - OFFSET) * RGB * asinh(Y / SOFT) / (Y * asinh(WHITE / SOFT)), Y = 0.2126 R + 0.7152 G + 0.0722 B.
      WHITE = the central star's clipped core (99.9th percentile of Y within 60 px), so the star is the only thing at
      white; SOFT is near the shell's own level (about 13 DN in green), so the shell sits in the middle of the curve and
      the star's 2000-times-brighter core is compressed into the top: a stretch, not a mask. OFFSET keeps the sky's
      noise above zero for the levels that follow (nothing is written as 0, which finish.py reads as "no data"). Written as 16-bit PNGs for finish.py.
   The reference frame alone goes through the same steps (same plane, same numbers) for the comparison.
Adapted from this night's m57/step8_render.py."""
import json, os
import numpy as np, cv2, tifffile
from common import *

CROP_W, CROP_H = int(os.environ.get('N1514_CROP_W', 600)), int(os.environ.get('N1514_CROP_H', 400))   # final picture, px
SKY_EXCLUDE_PX = 130
BLUR_SIGMA = float(os.environ.get('N1514_BLUR', 1.0))
SOFT = float(os.environ.get('N1514_SOFT', 15.0))
OFFSET = 0.20
CHROMA_SIGMA = float(os.environ.get('N1514_CHROMA', 8.0))   # px of the native grid
CHROMA_Y0, CHROMA_Y1 = 30.0, 120.0
TIF_PEDESTAL = 1000.0
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
LUMA = np.array([0.2126, 0.7152, 0.0722])

st = np.load(W_('stack_mean.npy')); sg = np.load(W_('single_planes.npy')); cover = np.load(W_('cover.npy'))
s7 = jload('step7.json'); s8 = jload('step8_solve.json'); N = len(s7['frames'])
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
tifffile.imwrite(os.path.join(OUT, 'ngc1514-stack.tif'), tif, photometric='rgb', compression='zlib', metadata=None, software=False)
tif_info = dict(area_stack_px=dict(x0=int(x0), y0=int(y0), width=int(x1 - x0), height=int(y1 - y0)), pedestal=TIF_PEDESTAL, scale=TIF_SCALE,
                value='tif = round(linear * scale + pedestal); linear = DN of the 14-bit RAW scale per 15 s frame at the clearest frame\'s transparency, times the daylight white balance; sky in a ring 3.2 to 9 arcmin around NGC 1514 at 0',
                clipped_low=int((tif == 0).sum()), clipped_high=int((tif == 65535).sum()))
print('tif', tif.shape, 'scale', TIF_SCALE, 'area', tif_info['area_stack_px'], flush=True)
del lin, tif

# ---- 2. the crop
north = s8['north_is_deg_clockwise_from_up']
K = int(np.round(north / 90.0)) % 4                        # np.rot90 k: counter-clockwise quarter turns; north goes from a to a - 90 k
north_after = (north - 90 * K + 180) % 360 - 180
pc = np.array(s8['central_star_centroid']['stack_px']); cx, cy = int(round(pc[0])), int(round(pc[1]))
cw, ch = (CROP_H, CROP_W) if K % 2 else (CROP_W, CROP_H)  # size in stack px before the turn
cy0, cx0 = cy - ch // 2, cx - cw // 2
assert full[cy0:cy0 + ch, cx0:cx0 + cw].all()
yy, xx = np.mgrid[cy0:cy0 + ch, cx0:cx0 + cw]
ref = [r for r in jload('step2_stars.json') if r['stamp'] == s7['reference']][0]['stars']
smask = np.zeros((h2, w2), np.uint8)
for s in ref:
    if np.hypot(s['x'] - pc[0], s['y'] - pc[1]) < 5: continue      # the central star itself is not masked
    cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
RRc = np.hypot(xx - pc[0], yy - pc[1])
SKYM = (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0) & (RRc > SKY_EXCLUDE_PX)
U, V = (xx - pc[0]) / 100.0, (yy - pc[1]) / 100.0


def plane_fit(img):
    co_all = []
    for k in range(3):
        v = img[..., k][SKYM]; X = np.column_stack([np.ones(SKYM.sum()), U[SKYM], V[SKYM]]); keep = np.ones(len(v), bool)
        for _ in range(6):
            co, *_ = np.linalg.lstsq(X[keep], v[keep], rcond=None); res = v - X @ co; keep = np.abs(res) < 3 * res[keep].std()
        co_all.append(co.tolist())
    return co_all


def render(P, planes_fit=None, blur=BLUR_SIGMA):
    a = cam_rgb(P)[cy0:cy0 + ch, cx0:cx0 + cw]
    co = planes_fit or plane_fit(a)
    for k in range(3): a[..., k] -= co[k][0] + co[k][1] * U + co[k][2] * V
    a = a @ RGB_CAM.T
    if blur: a = cv2.GaussianBlur(a, (0, 0), blur)
    if CHROMA_SIGMA:
        # colour noise: each pixel keeps its own luminance Y and takes its colour difference D = RGB - Y from a
        # copy blurred by CHROMA_SIGMA px, where the blur leaves out pixels brighter than CHROMA_Y1 (star cores, so
        # their colour does not bleed out) and counts the rest equally (normalised convolution). Applied where the
        # picture is faint: full below CHROMA_Y0 DN of luminance (smoothed over 2 px), fading out by CHROMA_Y1, so
        # stars keep their own colour. Luminance is untouched: 0.2126 D_R + 0.7152 D_G + 0.0722 D_B = 0 for any D.
        sig = CHROMA_SIGMA
        Y = a @ LUMA; Ys = cv2.GaussianBlur(Y, (0, 0), 2.0)
        m = (Ys < CHROMA_Y1).astype(np.float64)
        D = a - Y[..., None]
        Ds = cv2.GaussianBlur(D * m[..., None], (0, 0), sig) / np.maximum(cv2.GaussianBlur(m, (0, 0), sig), 1e-6)[..., None]
        w = np.clip((CHROMA_Y1 - Ys) / (CHROMA_Y1 - CHROMA_Y0), 0, 1)[..., None]
        a = Y[..., None] + w * Ds + (1 - w) * D
    # where the sensor clipped (any colour plane within 20% of the ceiling, grown by 2 px, edge softened over 1.5 px),
    # the true colour is unknown: the colour difference is set to zero there, so a clipped core is white, not the
    # yellow that an unclipped red over a clipped green and blue would make. Luminance is not changed.
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
WHITE = float(np.percentile((A @ LUMA)[RRc < 60], 99.9))
B, _ = render(sg, CO)                                       # the reference frame alone: same sky planes, same numbers
for name, img in (('ngc1514-stretched', A), ('single-stretched', B)):
    o = np.rot90(stretch(img, WHITE), K)
    cv2.imwrite(W_(name + '.png'), (o[..., ::-1] * 65535 + 0.5).astype(np.uint16))
# where the central star lands in the picture (after the turn)
mx, my = pc[0] - cx0, pc[1] - cy0
w_, h_ = cw, ch
for _ in range(K): mx, my, w_, h_ = my, w_ - 1 - mx, h_, w_      # np.rot90 (k = 1): pixel (x, y) of a w-wide image goes to (y, w - 1 - x)
# the shell's level in the stretched picture, for the record (green-weighted luminance at 20 to 45 arcsec)
Ysh = float(np.median((A @ LUMA)[(RRc > 26) & (RRc < 58) & (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0)]))
info = dict(crop_stack_px=dict(x0=int(cx0), y0=int(cy0), width=int(cw), height=int(ch)), quarter_turns_counter_clockwise=K, north_deg_clockwise_from_up_before=north, north_deg_clockwise_from_up_after=north_after,
            east_deg_clockwise_from_up_after=(north_after - 90 + 180) % 360 - 180, picture_size=[CROP_W, CROP_H], central_star_in_picture_px=[float(mx), float(my)],
            field_arcmin=[round(CROP_W * float(np.mean(s8['scale_arcsec_per_px'])) / 60, 2), round(CROP_H * float(np.mean(s8['scale_arcsec_per_px'])) / 60, 2)],
            sky_planes_dn=dict(zip('RGB', CO)), sky_plane_terms='DN = c0 + c1 * (x - x_star) / 100 + c2 * (y - y_star) / 100, stack px, white-balanced camera RGB', sky_exclude_px=SKY_EXCLUDE_PX, sky_pixels=int(SKYM.sum()),
            sky_ramp_across_crop_dn={c: float(abs(CO[k][1]) * cw / 100 + abs(CO[k][2]) * ch / 100) for k, c in enumerate('RGB')},
            white_balance_daylight=wb.tolist(), rgb_cam=RGB_CAM.tolist(), blur_sigma_px=BLUR_SIGMA, stretch=dict(white=WHITE, soft=SOFT, offset=OFFSET, shell_luminance_dn=Ysh,
            shell_out=float(OFFSET + (1 - OFFSET) * np.arcsinh(Ysh / SOFT) / np.arcsinh(WHITE / SOFT))),
            chroma=dict(sigma_px=CHROMA_SIGMA, faded_between_dn=[CHROMA_Y0, CHROMA_Y1], formula="RGB' = Y + w Ds + (1 - w) D; D = RGB - Y; Ds = G(D m) / G(m), G = Gaussian of sigma_px, m = 1 where Y (2 px smoothed) < Y1; w = clip((Y1 - Ys) / (Y1 - Y0), 0, 1)"),
            clipped_cores='colour difference set to 0 where any plane >= 0.8 x the ceiling (grown 2 px, softened 1.5 px)', tif=tif_info)
jsave(info, 'step10.json')
print(json.dumps({k: v for k, v in info.items() if k not in ('rgb_cam', 'tif')}, indent=1))
