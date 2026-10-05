"""The stack made into files, each with its recipe.

  1. Colour planes lined up: red and blue shifted by the fraction of a pixel measure.py found.
  2. Saved as it is: a linear 16-bit TIFF, and a PNG and a JPEG to look at (one tone curve: white
     at the 99.9th percentile of the lit ground, gamma 2.2; black stays black). No text, no marks.
  3. Optionally deconvolved (Richardson-Lucy, the standard iterative method): the blur measured from
     the Moon's own limb is divided back out, N rounds. Saved beside the plain one, named for what
     was done. (Not delivered this night: the Wiener filter of wiener.py is the restored picture.)

In the TIFF 65535 = half the sensor's ceiling (the working numbers are 4x the sensor's, moonlib.GAIN,
and are halved on the way out so that nothing is clipped); the sky is at 0 (each frame's sky level
and cloud glow were taken off).

Usage: finish.py stack.npz measured.json outdir [--stem name] [iterations ...]
"""
import sys, os, json, numpy as np, cv2, tifffile
import moonlib
z = np.load(sys.argv[1]); img = z["img"].astype(np.float32); depth = z["depth"]
m = json.load(open(sys.argv[2])); outdir = sys.argv[3]
STEM = "moon-mosaic"
args = sys.argv[4:]
if args and args[0] == "--stem":
    STEM, args = args[1], args[2:]
rounds = [int(v) for v in args]
os.makedirs(outdir, exist_ok=True)
h, w = img.shape[:2]

for c, key in ((0, "red_shift_px"), (2, "blue_shift_px")):
    dx, dy = m[key]   # how far this plane sits from green; moved back by that much
    img[:, :, c] = cv2.warpAffine(img[:, :, c], np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), flags=cv2.INTER_LANCZOS4)
img = np.clip(img, 0, None) * (depth[:, :, None] > 0)
lit = cv2.GaussianBlur(img[:, :, 1], (0, 0), 3) > 0.05
white = float(np.percentile(img[lit], 99.9))


def save(a, stem, tif=True):
    if tif:
        tifffile.imwrite(os.path.join(outdir, stem + "-linear.tif"), np.clip(a * (2.0 / moonlib.GAIN) * 65535 + 0.5, 0, 65535).astype(np.uint16), photometric="rgb", compression="zlib")
    v = (np.clip(a / white, 0, 1) ** (1 / 2.2))[:, :, ::-1]
    v8 = (v * 255 + 0.5).astype(np.uint8)
    cv2.imwrite(os.path.join(outdir, stem + ".png"), v8, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    cv2.imwrite(os.path.join(outdir, stem + ".jpg"), v8, [cv2.IMWRITE_JPEG_QUALITY, 92])


def richardson_lucy(a, sigma, n):
    est = a.copy()
    for _ in range(n):
        blurred = cv2.GaussianBlur(est, (0, 0), sigma)
        est *= cv2.GaussianBlur(a / np.maximum(blurred, 1e-6), (0, 0), sigma)
    return est


save(img, STEM)
made = [STEM]
sigma = m["blur_sigma_px"]
for n in rounds:
    stem = "%s-deconvolved-%d-rounds" % (STEM, n)
    save(np.dstack([richardson_lucy(np.maximum(img[:, :, c], 1e-6), sigma, n) for c in range(3)]) * (img.sum(2, keepdims=True) > 0), stem, tif=False)
    made.append(stem)
json.dump(dict(colour_planes=dict(red_moved_px=[-v for v in m["red_shift_px"]], blue_moved_px=[-v for v in m["blue_shift_px"]], resampling="Lanczos-4"),
               tone_curve_for_png_and_jpeg=dict(white=white, gamma=2.2, black=0.0, note="white is the 99.9th percentile of the lit ground"),
               linear_tif=dict(scale="65535 = half the sensor's ceiling", sky="0: each frame's sky level and cloud glow taken off",
                               clipped_at_65535_pct=float(100 * (img * 2.0 / moonlib.GAIN > 1).mean()), brightest_share_of_sensor_ceiling=float(img.max() / moonlib.GAIN)),
               no_data="black (0): %.1f%% of the picture has no frame over it" % (100 * float((depth <= 0).mean())),
               deconvolution=dict(method="Richardson-Lucy", psf="Gaussian", sigma_px=sigma, measured_from="the sunlit limb of this stack (%d profiles)" % m["limb_profiles"], rounds=rounds),
               measured=m, files=made, scale_arcsec_per_px=m.get("arcsec_per_px"), size=[w, h]), open(os.path.join(outdir, "finish-%s.json" % STEM), "w"), indent=1)
print("saved", made, "in", outdir, " white %.3f  brightest %.3f of the sensor's ceiling" % (white, img.max() / moonlib.GAIN))
