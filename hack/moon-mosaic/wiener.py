"""Restore the contrast the blur took, as far as the data allows, in one step (a Wiener filter).

Two measured curves decide everything, and neither is a guess about the Moon:
  the blur's spectrum MTF(f), from the Moon's sunlit limb in this stack (psf.py): how much contrast
  survives at each fineness. The larger of the measurement and its fitted curve is used, so the
  filter never boosts by more than the limb itself shows was lost;
  the signal fraction S(f) = 2c / (1 + c), from how well two stacks of separate halves of the
  frames agree at each fineness (frc.py): the share of what the stack shows there that is real.
At each fineness the filter multiplies by S(f) / MTF(f): undo the blur, times the share that is
signal. Where the halves agree, contrast is restored in full; where they stop agreeing the filter
lets go, and past that it passes nothing new. Brightness (R + 2G + B) is filtered and each colour
scaled by the same ratio.

Usage: wiener.py stack.npz measured.json psf.npz frc.npz outdir stem [--crop x y w h] [--strength s]
"""
import sys, os, json, numpy as np, cv2, tifffile
args = sys.argv[1:]; crop = None; strength = 1.0
if "--strength" in args:
    i = args.index("--strength"); strength = float(args[i + 1]); args = args[:i] + args[i + 2:]
if "--crop" in args:
    i = args.index("--crop"); crop = tuple(int(v) for v in args[i + 1:i + 5]); args = args[:i]
stack, measured, psf_path, frc_path, outdir, stem = args[:6]
img = np.load(stack)["img"].astype(np.float32); m = json.load(open(measured)); pz = np.load(psf_path); f0, pw = float(pz["f0"]), float(pz["power"])
h, w = img.shape[:2]
for c, key in ((0, "red_shift_px"), (2, "blue_shift_px")):
    dx, dy = m[key]
    img[:, :, c] = cv2.warpAffine(img[:, :, c], np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), flags=cv2.INTER_LANCZOS4)
img = np.clip(img, 0, None); white = float(np.percentile(img[img.sum(2) > 0], 99.9))
L = (img[:, :, 0] + 2 * img[:, :, 1] + img[:, :, 2]) / 4

# -- the two curves ---------------------------------------------------------------------------------
fz = np.load(frc_path); f = fz["f"]; frac = fz["signal_fraction"]
mf, mm = pz["mtf_f"], pz["mtf"]; mm = np.convolve(np.pad(mm, 2, mode="edge"), np.ones(5) / 5, "valid")
mtf = np.maximum(np.exp(-(np.maximum(f, 1e-6) / f0) ** pw), np.interp(f, mf, mm))
gain = 1 + strength * (frac / np.maximum(mtf, 1e-4) - 1); gain[0] = 1
gain[frac <= 0] = np.minimum(gain[frac <= 0], 0) if strength >= 1 else gain[frac <= 0]
gain = np.maximum(gain, 0)
arc = m["arcsec_per_px"]
report = {"%.1f arcsec" % per: dict(blur_keeps=round(float(np.interp(arc / per, f, mtf)), 4), signal_fraction=round(float(np.interp(arc / per, f, frac)), 3), gain=round(float(np.interp(arc / per, f, gain)), 2))
          for per in (10, 6, 4, 3.5, 3, 2.7, 2.5, 2.3, 2.1, 1.9)}
print(json.dumps(dict(peak_gain=round(float(gain.max()), 1), at=report)))

# -- apply ------------------------------------------------------------------------------------------
if crop:
    x, y, cw, ch = crop; img = img[y:y + ch, x:x + cw]; L = L[y:y + ch, x:x + cw]
pad = 128; Lp = cv2.copyMakeBorder(L, pad, pad, pad, pad, cv2.BORDER_REFLECT)
fy, fx = np.meshgrid(np.fft.fftfreq(Lp.shape[0]), np.fft.rfftfreq(Lp.shape[1]), indexing="ij")
G = np.interp(np.hypot(fx, fy), f, gain, right=0).astype(np.float32)
Ls = np.fft.irfft2(np.fft.rfft2(Lp) * G, s=Lp.shape)[pad:-pad, pad:-pad].astype(np.float32)
# At the Moon's edge any such filter rings: a dark line just outside, a bright rim just inside.
# Neither is real. Within LIMB px of the fitted limb the restored brightness is held between the
# darkest and brightest original pixels REACH px around it; the hold fades out over the zone's edge.
LIMB, REACH = 30 * m["arcsec_per_px"] ** -1 * 0.3955, 16 * m["arcsec_per_px"] ** -1 * 0.3955
cxm, cym = m["moon_centre_px"]; ox, oy = (crop[0], crop[1]) if crop else (0, 0)
yy, xx = np.indices(L.shape, dtype=np.float32); dist = np.abs(np.hypot(xx + ox - cxm, yy + oy - cym) - m["moon_radius_px"])
hold = np.clip((LIMB - dist) / (LIMB / 3), 0, 1)
ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(REACH) + 1, 2 * int(REACH) + 1))
held = np.clip(Ls, cv2.erode(L, ker), cv2.dilate(L, ker))
Ls = hold * held + (1 - hold) * Ls
ratio = np.clip(Ls / np.maximum(L, 1e-6), 0, 8); out = img * ratio[:, :, None] * (L[:, :, None] > 0)
white = max(white, float(np.percentile(out[out.sum(2) > 0], 99.97))) if not crop else white   # the restored highlights kept below white
os.makedirs(outdir, exist_ok=True)
v = np.clip(out / white, 0, 1) ** (1 / 2.2)
if crop:
    cv2.imwrite(os.path.join(outdir, stem + ".png"), (v[:, :, ::-1] * 255 + 0.5).astype(np.uint8))
else:
    cv2.imwrite(os.path.join(outdir, stem + ".jpg"), (v[:, :, ::-1] * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 94])
    tifffile.imwrite(os.path.join(outdir, stem + ".tif"), np.clip(out * 65535, 0, 65535).astype(np.uint16), photometric="rgb", compression="zlib")
    json.dump(dict(method="Wiener filter on brightness (R+2G+B)/4, colours scaled by the same ratio", strength=strength,
                   blur=json.load(open(psf_path.replace(".npz", ".json"))), halves_agree=json.load(open(frc_path.replace(".npz", ".json"))), gain_at=report,
                   limb_hold=dict(zone_px=round(float(LIMB), 1), reach_px=round(float(REACH), 1), note="within the zone the restored brightness stays between the darkest and brightest original pixels within reach"),
                   colour_planes=dict(red_moved_px=[-q for q in m["red_shift_px"]], blue_moved_px=[-q for q in m["blue_shift_px"]]),
                   tone_curve_for_jpeg=dict(white=white, gamma=2.2), size=[w, h], arcsec_per_px=m["arcsec_per_px"]), open(os.path.join(outdir, stem + ".json"), "w"), indent=1)
print("saved", stem)
