"""Step 8: from the stack to pictures, every step one fixed formula applied to every pixel alike.

1. m57-stack.tif: the whole area that every used frame covers, linear, 16-bit RGB: R, mean of G1 and G2, B, times the
   camera's own daylight white balance (from the RAW; no colour matrix), plus a pedestal, times a scale. Orientation
   as the reference frame's sensor; step 7's sky map applies (offset given in the recipe).
2. The crop around M57: centred on the catalogue position from the plate solve (step 7), turned by whole quarter turns
   (no resampling) to bring north nearest to up.
   a. sky: the stack's sky has a straight ramp across the crop (light pollution: 13 to 16 DN in each colour across
      9 arcmin, ten times the faint light around the ring). One plane per colour (3 numbers) is fitted to the sky in the
      crop farther than SKY_EXCLUDE_PX from the nebula's centre (2.6 arcmin; M57's faint outer halo reaches about 1.9),
      stars masked, 3-sigma clipped, and subtracted. Nothing is fitted where the nebula is; inside that circle the plane
      is the straight-line continuation of the sky around it.
   b. colour: the camera's own matrix (rgb_xyz_matrix in the RAW, through sRGB primaries, rows normalised so that daylight
      white stays white), applied to the white-balanced camera RGB: linear sRGB.
   c. brightness and colour at the resolution each can carry: the luminance Y (0.2126 R + 0.7152 G + 0.0722 B) after a
      Gaussian of BLUR_SIGMA px (the stars are about 7 px across, half-flux diameter, so this widens them by a few percent
      and removes pixel-to-pixel noise finer than the telescope and air deliver); the colour after a Gaussian of
      CHROMA_SIGMA px (the red channel is 3.5 x noisier than green: one red pixel in four, and little sky light in red):
      out = Y_b * (w * RGB_c / Y_c + (1 - w)), w = smoothstep of Y_c / sigma from CHROMA_SNR[0] to CHROMA_SNR[1]
      (sigma = the sky noise of Y_c): where the smoothed light stands well above the noise this is Y_b with the colour
      ratios of RGB_c; in the dark sky, where colour is only noise, it is grey. The luminance of out is exactly Y_b.
      Linear filters, the same everywhere, like the chroma subsampling of a JPEG.
   d. stretch: arcsinh of the luminance, with the same gain for R, G and B of a pixel (colour ratios kept):
      out = OFFSET + (1 - OFFSET) * RGB * asinh(Y / SOFT) / (Y * asinh(WHITE / SOFT)), Y = 0.2126 R + 0.7152 G + 0.0722 B,
      WHITE = the 99.9th percentile of Y inside the ring (r < 60 px); OFFSET keeps the sky's noise above zero for the
      levels that follow. Written as a 16-bit PNG for finish.py.
   The reference frame alone goes through the same steps (same plane fit, same numbers) for the comparison."""
import json, os
import numpy as np, cv2, tifffile
from common import *

CROP_W, CROP_H = int(os.environ.get('M57_CROP_W', 720)), int(os.environ.get('M57_CROP_H', 480))   # final picture, px
SKY_EXCLUDE_PX = 200
BLUR_SIGMA = float(os.environ.get('M57_BLUR', 1.0))
CHROMA_SIGMA = float(os.environ.get('M57_CHROMA', 3.5))
CHROMA_SNR = tuple(float(v) for v in os.environ.get("M57_CHROMA_SNR", "4 12").split())
SOFT = float(os.environ.get('M57_SOFT', 40.0))
OFFSET = 0.10
TIF_PEDESTAL = 1000.0
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
LUMA = np.array([0.2126, 0.7152, 0.0722])

st = np.load(W_('stack_mean.npy')); sg = np.load(W_('single_planes.npy')); cover = np.load(W_('cover.npy'))
s6 = jload('step6.json'); s7 = jload('step7_solve.json'); N = len(s6['frames'])
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
tifffile.imwrite(os.path.join(OUT, 'm57-stack.tif'), tif, photometric='rgb', compression='zlib', metadata=None, software=False)
tif_info = dict(area_stack_px=dict(x0=int(x0), y0=int(y0), width=int(x1 - x0), height=int(y1 - y0)), pedestal=TIF_PEDESTAL, scale=TIF_SCALE,
                value='tif = round(linear * scale + pedestal); linear = DN of the 14-bit RAW scale per 15 s frame at the clearest frame\'s transparency, sky near M57 at 0',
                clipped_low=int((tif == 0).sum()), clipped_high=int((tif == 65535).sum()))
print('tif', tif.shape, 'scale', TIF_SCALE, 'area', tif_info['area_stack_px'])

# ---- 2. the crop
north = s7['north_is_deg_clockwise_from_up']
K = int(np.round(north / 90.0)) % 4                        # np.rot90 k: counter-clockwise quarter turns; north goes from a to a - 90 k
north_after = (north - 90 * K + 180) % 360 - 180
pc = np.array(s7['m57_catalogue']['stack_px']); cx, cy = int(round(pc[0])), int(round(pc[1]))
cw, ch = (CROP_H, CROP_W) if K % 2 else (CROP_W, CROP_H)  # size in stack px before the turn
cy0, cx0 = cy - ch // 2, cx - cw // 2
assert full[cy0:cy0 + ch, cx0:cx0 + cw].all()
yy, xx = np.mgrid[cy0:cy0 + ch, cx0:cx0 + cw]
ref = [r for r in jload('step2_stars.json') if r['stamp'] == s6['reference']][0]['stars']
smask = np.zeros((h2, w2), np.uint8)
for s in ref: cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
SKYM = (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0) & (np.hypot(xx - pc[0], yy - pc[1]) > SKY_EXCLUDE_PX)
U, V = (xx - pc[0]) / 100.0, (yy - pc[1]) / 100.0


def plane_fit(img):
    co_all = []
    for k in range(3):
        v = img[..., k][SKYM]; X = np.column_stack([np.ones(SKYM.sum()), U[SKYM], V[SKYM]]); keep = np.ones(len(v), bool)
        for _ in range(6):
            co, *_ = np.linalg.lstsq(X[keep], v[keep], rcond=None); res = v - X @ co; keep = np.abs(res) < 3 * res[keep].std()
        co_all.append(co.tolist())
    return co_all


def render(P, planes_fit=None):
    a = cam_rgb(P)[cy0:cy0 + ch, cx0:cx0 + cw]
    co = planes_fit or plane_fit(a)
    for k in range(3): a[..., k] -= co[k][0] + co[k][1] * U + co[k][2] * V
    a = a @ RGB_CAM.T
    Yb = cv2.GaussianBlur(a, (0, 0), BLUR_SIGMA) @ LUMA if BLUR_SIGMA else a @ LUMA
    C = cv2.GaussianBlur(a, (0, 0), CHROMA_SIGMA); Yc = C @ LUMA
    sig = clipped_stats(Yc[SKYM])[1]
    t = np.clip((Yc / sig - CHROMA_SNR[0]) / (CHROMA_SNR[1] - CHROMA_SNR[0]), 0, 1); wgt = t * t * (3 - 2 * t)
    ratio = C / np.where(Yc > 0, Yc, 1.0)[..., None]
    return Yb[..., None] * (wgt[..., None] * ratio + (1 - wgt[..., None])), co, sig


def stretch(a, white):
    Y = a @ LUMA
    with np.errstate(divide='ignore', invalid='ignore'):
        g = np.where(np.abs(Y) < 1e-9, 1.0 / SOFT, np.arcsinh(Y / SOFT) / Y) / np.arcsinh(white / SOFT)
    out = OFFSET + (1 - OFFSET) * a * g[..., None]
    return np.clip(out, 0, 1)


A, CO, KA = render(st)
rr = np.hypot(xx - pc[0], yy - pc[1])
WHITE = float(np.percentile((A @ LUMA)[rr < 60], 99.9))
B, _, KB = render(sg, CO)                                       # the reference frame alone: same sky planes, same numbers
for name, img in (('m57-stretched', A), ('single-stretched', B)):
    o = np.rot90(stretch(img, WHITE), K)
    cv2.imwrite(W_(name + '.png'), (o[..., ::-1] * 65535 + 0.5).astype(np.uint16))
np.save(W_('crop_linear_srgb.npy'), np.rot90(A, K).astype(np.float32)); np.save(W_('crop_single_linear_srgb.npy'), np.rot90(B, K).astype(np.float32))
# where M57's catalogue position lands in the picture (after the turn)
mx, my = pc[0] - cx0, pc[1] - cy0
w_, h_ = cw, ch
for _ in range(K): mx, my, w_, h_ = my, w_ - 1 - mx, h_, w_      # np.rot90 (k = 1): pixel (x, y) of a w-wide image goes to (y, w - 1 - x)
info = dict(crop_stack_px=dict(x0=int(cx0), y0=int(cy0), width=int(cw), height=int(ch)), quarter_turns_counter_clockwise=K, north_deg_clockwise_from_up_before=north, north_deg_clockwise_from_up_after=north_after,
            east_deg_clockwise_from_up_after=(north_after - 90 + 180) % 360 - 180, picture_size=[CROP_W, CROP_H], m57_catalogue_in_picture_px=[float(mx), float(my)],
            sky_planes_dn=dict(zip('RGB', CO)), sky_plane_terms='DN = c0 + c1 * (x - x_M57) / 100 + c2 * (y - y_M57) / 100, stack px, white-balanced camera RGB', sky_exclude_px=SKY_EXCLUDE_PX, sky_pixels=int(SKYM.sum()),
            sky_ramp_across_crop_dn={c: float(abs(CO[k][1]) * cw / 100 + abs(CO[k][2]) * ch / 100) for k, c in enumerate('RGB')},
            white_balance_daylight=wb.tolist(), rgb_cam=RGB_CAM.tolist(), blur_sigma_px=BLUR_SIGMA, chroma_sigma_px=CHROMA_SIGMA, chroma_snr=list(CHROMA_SNR), chroma_sky_sigma_dn=dict(stack=KA, single=KB), stretch=dict(white=WHITE, soft=SOFT, offset=OFFSET), tif=tif_info)
jsave(info, 'step8.json')
print(json.dumps({k: v for k, v in info.items() if k not in ('rgb_cam', 'tif')}, indent=1))
