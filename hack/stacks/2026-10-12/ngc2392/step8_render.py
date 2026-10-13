"""Step 8: from the stack to pictures, every step one fixed formula applied to every pixel alike. As last week's
m57/step8_render.py (the same kind of object at the same scale).

1. ngc2392-stack.tif: the whole area that every used frame covers, linear, 16-bit RGB: R, mean of G1 and G2, B, times
   the camera's own daylight white balance (from the RAW; no colour matrix), times a scale, plus a pedestal.
   Orientation as the reference frame's sensor; step 7's plate solution applies (offset given in the recipe).
2. The crop around NGC 2392: CROP_W x CROP_H stack pixels centred on the central star (step 7), turned by whole quarter
   turns (no resampling) to bring north nearest to up. One picture pixel is one 2 x 2 colour cell of the sensor
   (0.777 arcsec): nothing is enlarged, nothing is resampled after the stack.
   a. sky: one plane per colour (3 numbers) fitted to the sky in the crop farther than SKY_EXCLUDE_PX from the central
      star (62 arcsec; the outer disc's light has ended by 34, step 7), stars masked, 3-sigma clipped, and subtracted.
      Nothing is fitted where the nebula is. This plane is in the picture only, not in the stack.
   b. colour: the camera's own matrix (rgb_xyz_matrix in the RAW, through sRGB primaries, rows normalised so that
      daylight white stays white), applied to the white-balanced camera RGB: linear sRGB.
   c. brightness and colour at the resolution each can carry: the luminance Y (0.2126 R + 0.7152 G + 0.0722 B) after a
      Gaussian of BLUR_SIGMA px (1.5 here; the stars are 6.5 px across at half flux, so this widens them by about 14%
      in the picture, not in the stack, and removes pixel-to-pixel noise finer than the telescope and air delivered); the colour after a Gaussian of
      CHROMA_SIGMA px: out = Y_b * (w * RGB_c / Y_c + (1 - w)), w = smoothstep of Y_c / sigma from CHROMA_SNR[0] to
      CHROMA_SNR[1] (sigma = the sky noise of Y_c): where the smoothed light stands well above the noise this is Y_b
      with the colour ratios of RGB_c; in the dark sky, where colour is only noise, it is grey.
   d. stretch: arcsinh of the luminance, with the same gain for R, G and B of a pixel (colour ratios kept):
      out = OFFSET + (1 - OFFSET) * RGB * asinh(Y / SOFT) / (Y * TOP). TOP is set so that the BRIGHTEST COLOUR CHANNEL
      of the nebula's middle (99.9th percentile within 20 px of the central star) lands at TOP_AT of full scale (the
      8th magnitude star 1.7 arcmin north is five times brighter than that and its core goes to full scale): the
      disc is nearly pure green and blue, so a white point set on its luminance would push green and blue past full
      scale and flatten the middle of the disc, central star included, to one tone (the first render did exactly that).
      SOFT is near the shell's level (7 to 17 DN; the disc is 90 to 250): the shell sits low on the curve and the disc
      keeps its contrast: a stretch, not a mask.
      OFFSET keeps the sky's noise above zero for the levels that follow; nothing is written as 0 (finish16.py reads 0
      as "no data"). Written as a 16-bit PNG for finish16.py."""
import json, os
import numpy as np, cv2, tifffile
from common import *

CROP_W, CROP_H = int(os.environ.get('N2392_CROP_W', 720)), int(os.environ.get('N2392_CROP_H', 480))   # final picture, px
SKY_EXCLUDE_PX = 80
BLUR_SIGMA = float(os.environ.get('N2392_BLUR', 1.5))   # NGC 1535 used 1.0 on 30 clear frames; here 21 frames through thickening cloud: at 1.0 and 1.25 the outer disc's edge broke into scallops of grain at full size (both were tried and looked at)
CHROMA_SIGMA = float(os.environ.get('N2392_CHROMA', 3.5))
CHROMA_SNR = tuple(float(v) for v in os.environ.get('N2392_CHROMA_SNR', '4 12').split())
SOFT = float(os.environ.get('N2392_SOFT', 12.0))
OFFSET = 0.10
TOP_AT = 0.97                  # the nebula's brightest colour channel lands at this fraction of full scale (above the offset)
TIF_PEDESTAL = 1000.0
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])
LUMA = np.array([0.2126, 0.7152, 0.0722])

st = np.load(W('stack_mean.npy')); cover = np.load(W('cover.npy'))
s6 = jload('step6_stack.json'); s7 = jload('step7_measure.json'); N = len(s6['frames'])
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
hi = float(np.nanmax(lin)); TIF_SCALE = float(min(16.0, np.floor((65000 - TIF_PEDESTAL) / hi * 100) / 100))
tif = np.clip(np.round(lin * TIF_SCALE + TIF_PEDESTAL), 0, 65535).astype(np.uint16)
tifffile.imwrite(os.path.join(OUT, 'ngc2392-stack.tif'), tif, photometric='rgb', compression='zlib', metadata=None, software=False)
tif_info = dict(area_stack_px=dict(x0=int(x0), y0=int(y0), width=int(x1 - x0), height=int(y1 - y0)), pedestal=TIF_PEDESTAL, scale=TIF_SCALE,
                value='tif = round(linear * scale + pedestal); linear = DN of the 14-bit RAW scale per 4 s frame at ISO 1600 at the clearest frame\'s transparency, flat-fielded, the sky near the nebula at 0; R and B times the daylight white balance',
                nebula_centre_in_tif_px=[s7['solve']['nebula_light_centre_px'][0] - int(x0), s7['solve']['nebula_light_centre_px'][1] - int(y0)],
                clipped_low=int((tif == 0).sum()), clipped_high=int((tif == 65535).sum()), highest_linear_dn=hi)
print('tif', tif.shape, 'scale', TIF_SCALE, 'area', tif_info['area_stack_px'], 'highest', round(hi, 1))

# ---- 2. the crop
north = s7['solve']['north_angle_from_up_deg_clockwise']
K = int(np.round(north / 90.0)) % 4                        # np.rot90 k: counter-clockwise quarter turns; north goes from a to a - 90 k
north_after = (north - 90 * K + 180) % 360 - 180
pc = np.array(s7['solve']['nebula_light_centre_px']); cx, cy = int(round(pc[0])), int(round(pc[1]))
cw, ch = (CROP_H, CROP_W) if K % 2 else (CROP_W, CROP_H)  # size in stack px before the turn
cy0, cx0 = cy - ch // 2, cx - cw // 2
assert full[cy0:cy0 + ch, cx0:cx0 + cw].all()
yy, xx = np.mgrid[cy0:cy0 + ch, cx0:cx0 + cw]
ref = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == s6['reference']][0]['stars']
smask = np.zeros((h2, w2), np.uint8)
for s in ref: cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
rr = np.hypot(xx - pc[0], yy - pc[1])
SKYM = (smask[cy0:cy0 + ch, cx0:cx0 + cw] == 0) & (rr > SKY_EXCLUDE_PX)
U, V = (xx - pc[0]) / 100.0, (yy - pc[1]) / 100.0


def plane_fit(img):
    co_all = []
    for k in range(3):
        v = img[..., k][SKYM]; X = np.column_stack([np.ones(SKYM.sum()), U[SKYM], V[SKYM]]); keep = np.ones(len(v), bool)
        for _ in range(6):
            co, *_ = np.linalg.lstsq(X[keep], v[keep], rcond=None); res = v - X @ co; keep = np.abs(res) < 3 * res[keep].std()
        co_all.append(co.tolist())
    return co_all


a = cam_rgb(st)[cy0:cy0 + ch, cx0:cx0 + cw]
CO = plane_fit(a)
for k in range(3): a[..., k] -= CO[k][0] + CO[k][1] * U + CO[k][2] * V
a = a @ RGB_CAM.T
Yb = cv2.GaussianBlur(a, (0, 0), BLUR_SIGMA) @ LUMA if BLUR_SIGMA else a @ LUMA
C = cv2.GaussianBlur(a, (0, 0), CHROMA_SIGMA); Yc = C @ LUMA
sig = clipped_stats(Yc[SKYM])[1]; sigY = clipped_stats(Yb[SKYM])[1]
t = np.clip((Yc / sig - CHROMA_SNR[0]) / (CHROMA_SNR[1] - CHROMA_SNR[0]), 0, 1); wgt = t * t * (3 - 2 * t)
ratio = C / np.where(Yc > 0, Yc, 1.0)[..., None]
A = Yb[..., None] * (wgt[..., None] * ratio + (1 - wgt[..., None]))
Y = A @ LUMA
with np.errstate(divide='ignore', invalid='ignore'):
    g0 = np.where(np.abs(Y) < 1e-9, 1.0 / SOFT, np.arcsinh(Y / SOFT) / Y)
TOP = float(np.percentile((A.max(2) * g0)[rr < 20], 99.9)) / TOP_AT          # the nebula's brightest colour channel, stretched
WHITE = float(SOFT * np.sinh(TOP))                                           # the luminance (DN) that would reach full scale
g = g0 / TOP
o = np.rot90(np.clip(OFFSET + (1 - OFFSET) * A * g[..., None], 1.0 / 65535, 1), K)
cv2.imwrite(W('ngc2392-stretched.png'), (np.ascontiguousarray(o[..., ::-1]) * 65535 + 0.5).astype(np.uint16))
mx, my = pc[0] - cx0, pc[1] - cy0
w_, h_ = cw, ch
for _ in range(K): mx, my, w_, h_ = my, w_ - 1 - mx, h_, w_      # np.rot90 (k = 1): pixel (x, y) of a w-wide image goes to (y, w - 1 - x)
mean_col = (C[rr < 12].mean(0) / C[rr < 12].mean(0).max()).tolist(); shell_col = (C[(rr > 18) & (rr < 28)].mean(0) / C[(rr > 18) & (rr < 28)].mean(0).max()).tolist()
info = dict(crop_stack_px=dict(x0=int(cx0), y0=int(cy0), width=int(cw), height=int(ch)), quarter_turns_counter_clockwise=K, north_deg_clockwise_from_up_before=north, north_deg_clockwise_from_up_after=north_after,
            east_deg_clockwise_from_up_after=(north_after - 90 + 180) % 360 - 180, picture_size=[CROP_W, CROP_H], picture_scale_arcsec_per_px=s7['solve']['pixscale_arcsec'],
            picture_field_arcmin=[CROP_W * s7['solve']['pixscale_arcsec'] / 60, CROP_H * s7['solve']['pixscale_arcsec'] / 60], nebula_centre_in_picture_px=[float(mx), float(my)],
            sky_planes_dn=dict(zip('RGB', CO)), sky_plane_terms='DN = c0 + c1 * (x - x_nebula) / 100 + c2 * (y - y_nebula) / 100, stack px, white-balanced camera RGB', sky_exclude_px=SKY_EXCLUDE_PX, sky_pixels=int(SKYM.sum()),
            sky_ramp_across_crop_dn={c: float(abs(CO[k][1]) * cw / 100 + abs(CO[k][2]) * ch / 100) for k, c in enumerate('RGB')},
            white_balance_daylight=wb.tolist(), rgb_cam=RGB_CAM.tolist(), blur_sigma_px=BLUR_SIGMA, chroma_sigma_px=CHROMA_SIGMA, chroma_snr=list(CHROMA_SNR), chroma_sky_sigma_dn=sig, luminance_sky_sigma_dn=sigY,
            stretch=dict(white=WHITE, soft=SOFT, offset=OFFSET, top=TOP, top_at=TOP_AT, highest_channel_value=float(o.max())), linear_srgb_colour_of_the_disc_r_lt_12px=mean_col, linear_srgb_colour_of_the_shell_18_28px=shell_col,
            pixels_at_floor=int((o.max(2) <= 1.0 / 65535).sum()), pixels_at_white=int((o.min(2) >= 1).sum()), tif=tif_info)
jdump(info, 'step8_render.json')
print(json.dumps({k: v for k, v in info.items() if k not in ('rgb_cam', 'tif')}, indent=1))
