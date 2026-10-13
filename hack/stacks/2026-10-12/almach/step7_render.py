"""Step 7: from the stacked planes to a stretched, north-up, 16-bit picture for finish16.py (the finish-pictures tool).
Every step is one fixed formula applied to every pixel alike; nothing is generated, learned or drawn.

  1. turn: one Lanczos resample turns the stack so that north is up and east is to the left (the sky as you see it), about the middle
     of the pair, by the angle plate solving gave (step 5). Same pixel size as the sensor (0.388 arcsec): not enlarged. The planes
     are resampled as they are (linear), and the picture is cut to a CROP x CROP square round the pair.
  2. colour: R, G (G1 and G2 together), B times the camera's own daylight white balance (from the RAW, through LibRaw), then the camera's own
     colour matrix (rgb_xyz_matrix in the RAW, through the sRGB primaries, rows normalised so daylight white stays white, as dcraw does):
     linear sRGB. No star-colour calibration was done; the recipe says how far white stars are from white.
  3. brightness and colour at the resolution each can carry: L = the three planes weighted by their inverse noise variance, blurred by
     LUM_BLUR px (the drop grid leaves a faint pixel-scale grain, and the stars are 8 px across); colour = the linear sRGB divided by its own
     luminance after a Gaussian of CHROMA_BLUR px weighted by brightness (so a bright star's colour is not diluted by the sky around it),
     shown only where the light can carry it (smoothstep of L from COLOUR_FROM to COLOUR_FULL DN, grey below).
  4. stretch: arcsinh of L, the same gain for R, G and B of a pixel (colour ratios kept): v = PEDESTAL + (1 - PEDESTAL) x Ls x colour ratios,
     then the sRGB transfer curve, written as 16 bits. The floor is not cut at zero (finish16.py sets the black point afterwards).
Hooks (environment): ALMACH_CROP, ALMACH_LUM_BLUR, ALMACH_CHROMA_BLUR, ALMACH_SOFT, ALMACH_WHITE, ALMACH_COLOUR_FROM, ALMACH_COLOUR_FULL."""
import numpy as np, cv2
from common import *

CROP_PX = int(os.environ.get('ALMACH_CROP', '640'))
LUM_BLUR = float(os.environ.get('ALMACH_LUM_BLUR', '0.8'))
CHROMA_BLUR = float(os.environ.get('ALMACH_CHROMA_BLUR', '1.5'))
SOFT = float(os.environ.get('ALMACH_SOFT', '60'))
WHITE = float(os.environ.get("ALMACH_WHITE", "14000"))
COLOUR_FROM = float(os.environ.get('ALMACH_COLOUR_FROM', '25'))
COLOUR_FULL = float(os.environ.get('ALMACH_COLOUR_FULL', '90'))
PEDESTAL = 0.03
XYZ_RGB = np.array([[0.412453, 0.357580, 0.180423], [0.212671, 0.715160, 0.072169], [0.019334, 0.119193, 0.950227]])


def camera_matrix(rgb_xyz):
    cr = np.array(rgb_xyz)[:3] @ XYZ_RGB
    return np.linalg.inv(cr / cr.sum(1)[:, None])


def smoothstep(x, a, c):
    t = np.clip((x - a) / max(c - a, 1e-6), 0, 1); return t * t * (3 - 2 * t)


if __name__ == '__main__':
    d = np.load(W('stack.npz')); st = d['planes']; sol = jload('step5_solve.json'); s2 = jload('step2_prepare.json'); s6 = jload('step6_pair.json')
    a = np.array(s6['stack_fit']['primary_xy_sensor_px']); b = np.array(s6['stack_fit']['companion_xy_sensor_px']); mid = (a + b) / 2
    north = sol['north_on_picture_deg_clockwise_from_up']                  # north is this far clockwise from up on the stack (negative: anticlockwise)
    # to put north up we turn the picture by -north clockwise, i.e. anticlockwise on the screen by -north... see the check below
    M = cv2.getRotationMatrix2D((float(mid[0]), float(mid[1])), north, 1.0)   # cv2: positive = anticlockwise: rotating by `north` (= -56 -> clockwise 56) puts north up
    M[0, 2] += (CROP_PX - 1) / 2 - mid[0]; M[1, 2] += (CROP_PX - 1) / 2 - mid[1]
    pl = np.stack([cv2.warpAffine(p.astype(np.float32), M, (CROP_PX, CROP_PX), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT) for p in st])
    # check: where do the stars land, and does the companion sit at the measured position angle (from north through east = to the left)?
    pa_new = M @ np.array([a[0], a[1], 1.0]); pb_new = M @ np.array([b[0], b[1], 1.0]); v = pb_new - pa_new
    pa_check = float(np.degrees(np.arctan2(-v[0], -v[1])) % 360)           # east is left: angle from up towards left
    print('after the turn: primary at (%.1f, %.1f), companion at (%.1f, %.1f); companion PA read off the picture (north up, east left) %.1f deg (measured %.1f)' % (*pa_new, *pb_new, pa_check, s6['stack_fit']['position_angle_deg']))
    wbd = s2['daylight_wb']; wb = np.array([wbd[0], 1.0, wbd[2]]); rgb_cam = camera_matrix(s2['rgb_xyz_matrix'])
    noise = np.array([s2['noise_sigma_dn']['R'], 0.5 * (s2['noise_sigma_dn']['G1'] + s2['noise_sigma_dn']['G2']) / np.sqrt(2), s2['noise_sigma_dn']['B']])
    wl = 1 / (noise * wb) ** 2; wl = wl / wl.sum()
    cam = np.dstack([pl[0] * wb[0], pl[1] * wb[1], pl[2] * wb[2]]).astype(np.float32)
    L = sum(wl[k] * cam[..., k] for k in range(3)).astype(np.float32); Lb = cv2.GaussianBlur(L, (0, 0), LUM_BLUR) if LUM_BLUR > 0 else L
    # colour: brightness-weighted Gaussian of each channel over the weighted Gaussian of the weights
    wgt = np.clip(L, 1.0, None); Cc = np.dstack([cv2.GaussianBlur(cam[..., k] * wgt, (0, 0), CHROMA_BLUR) / cv2.GaussianBlur(wgt, (0, 0), CHROMA_BLUR) for k in range(3)])
    sC = Cc @ rgb_cam.T.astype(np.float32); Lc = (sC * np.array([0.2126, 0.7152, 0.0722], np.float32)).sum(2)
    wcol = smoothstep(Lc, COLOUR_FROM, COLOUR_FULL)
    cr = wcol[..., None] * (sC / np.maximum(Lc, 1e-3)[..., None]) + (1 - wcol[..., None])
    Ls = np.arcsinh(Lb / SOFT) / np.arcsinh(WHITE / SOFT)
    out = np.clip(PEDESTAL + (1 - PEDESTAL) * Ls[..., None] * cr, 1.0 / 65535, 1)
    out = np.where(out <= 0.0031308, 12.92 * out, 1.055 * np.power(out, 1 / 2.4) - 0.055).astype(np.float32)
    cv2.imwrite(W('almach-stretched.png'), (out[..., ::-1] * 65535 + 0.5).astype(np.uint16))
    np.save(W('almach-linear.npy'), pl.astype(np.float32))
    jdump(dict(crop_px=CROP_PX, north_clockwise_from_up_on_stack_deg=north, affine_stack_to_picture=M.tolist(), primary_xy_picture=pa_new.tolist(), companion_xy_picture=pb_new.tolist(),
               companion_position_angle_read_off_picture_deg=pa_check, luminance_weights=dict(zip(['R', 'G', 'B'], wl.round(4).tolist())), wb_daylight=wbd, camera_to_srgb=rgb_cam.tolist(),
               parameters=dict(LUM_BLUR=LUM_BLUR, CHROMA_BLUR=CHROMA_BLUR, SOFT=SOFT, WHITE=WHITE, COLOUR_FROM=COLOUR_FROM, COLOUR_FULL=COLOUR_FULL, PEDESTAL=PEDESTAL),
               colour_shown_fraction=float((wcol > 0.5).mean())), 'step7_render.json')
