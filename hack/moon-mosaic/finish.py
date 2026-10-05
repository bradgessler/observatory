"""The stack made into files, each with its recipe.

  1. Colour planes lined up: red and blue shifted by the fraction of a pixel measure.py found.
  2. Saved as it is: linear 16-bit TIFF (1.0 = the sensor's ceiling) and a JPEG to look at.
  3. Optionally deconvolved (Richardson-Lucy, the standard iterative method): the blur measured from
     the Moon's own limb is divided back out, N rounds. It adds nothing that isn't in the data; it
     trades noise for contrast at fine scales, which is why it needs the stack's low noise.
     Saved beside the plain one, named for what was done.

Usage: finish.py stack-keep30.npz measured.json outdir [--stem name] [iterations ...]
"""
import sys, os, json, numpy as np, cv2, tifffile
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
img = np.clip(img, 0, None)
white = float(np.percentile(img[img.sum(2) > 0], 99.9))


def save(a, stem):
    tifffile.imwrite(os.path.join(outdir, stem + ".tif"), np.clip(a * 65535, 0, 65535).astype(np.uint16), photometric="rgb", compression="zlib")
    v = np.clip(a / white, 0, 1) ** (1 / 2.2)
    cv2.imwrite(os.path.join(outdir, stem + ".jpg"), (v[:, :, ::-1] * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 93])


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
    save(np.dstack([richardson_lucy(np.maximum(img[:, :, c], 1e-6), sigma, n) for c in range(3)]) * (img.sum(2, keepdims=True) > 0), stem)
    made.append(stem)
json.dump(dict(colour_planes=dict(red_moved_px=[-v for v in m["red_shift_px"]], blue_moved_px=[-v for v in m["blue_shift_px"]], resampling="Lanczos-4"),
               tone_curve_for_jpeg=dict(white=white, gamma=2.2, note="the TIFF is linear: 65535 = the sensor's ceiling"),
               deconvolution=dict(method="Richardson-Lucy", psf="Gaussian", sigma_px=sigma, measured_from="the sunlit limb of this stack (%d profiles)" % m["limb_profiles"], rounds=rounds),
               measured=m, files=made, scale_arcsec_per_px=m.get("arcsec_per_px", 0.791), size=[w, h]), open(os.path.join(outdir, "finish-%s.json" % STEM), "w"), indent=1)
print("saved", made, "in", outdir)
