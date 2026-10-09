"""The planet before and after the refocus, side by side: the earlier run's plain stack on the left, this run's on the right.
Both are plain stacks of the 16 sharpest frames (saturn2.py, nothing divided out), on the same fine grid (3 per sensor pixel), each turned
north up by its own measured angle about the planet's middle (one Lanczos resampling), the sky's level taken off (the median of the
tile's corners, per colour), and shown at ONE stretch: the same white level and the same gamma for both, so a difference in brightness
or in sharpness between the two halves is a difference in the data. No words on it.
Usage: beforeafter.py <earlier stack.npy> <its north-up deg> <new stack.npy> <its north-up deg> <out.png>"""
import sys, json
import numpy as np, cv2
from metrics import measure
old, rot_old, new, rot_new, out = sys.argv[1], float(sys.argv[2]), sys.argv[3], float(sys.argv[4]), sys.argv[5]
HW, HH = 230, 150                                    # half-size of each panel, fine px: 60.6 x 39.5 arcsec
def panel(path, rot):
    s = np.load(path).astype(np.float32); n = s.shape[0]
    bg = np.array([np.median(np.concatenate([s[:70, :70, c].ravel(), s[:70, -70:, c].ravel(), s[-70:, :70, c].ravel(), s[-70:, -70:, c].ravel()])) for c in range(3)], np.float32)
    cx, cy = measure(s[:, :, 1])[0]["centre"]; M = cv2.getRotationMatrix2D((cx, cy), rot, 1.0); M[0, 2] += HW - 0.5 - cx; M[1, 2] += HH - 0.5 - cy
    return cv2.warpAffine(s - bg, M, (2 * HW, 2 * HH), flags=cv2.INTER_LANCZOS4), [float(cx), float(cy)], [float(b) for b in bg]
a, ca, ba = panel(old, rot_old); b, cb, bb = panel(new, rot_new)
white = float(max(np.percentile(a, 99.9), np.percentile(b, 99.9))); enc = lambda x: (np.clip(x / white, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)
gap = np.zeros((2 * HH, 12, 3), np.uint8); img = np.hstack([enc(a), gap, enc(b)]); cv2.imwrite(out, img[:, :, ::-1])
json.dump(dict(script="beforeafter.py", left=dict(stack=old, north_up_rotation_deg=rot_old, centre_fine_px=ca, sky_taken_off=ba), right=dict(stack=new, north_up_rotation_deg=rot_new, centre_fine_px=cb, sky_taken_off=bb),
               white_level_for_both=white, gamma=2.2, panel_px=[2 * HW, 2 * HH], gap_px=12, fine_px_per_sensor_px=3, size=[img.shape[1], img.shape[0]],
               globe_middle_green=dict(left=float(np.median(a[HH - 15:HH + 15, HW - 15:HW + 15, 1])), right=float(np.median(b[HH - 15:HH + 15, HW - 15:HW + 15, 1])))), open(out.replace(".png", ".json"), "w"), indent=1)
print(out, img.shape, "one white level %.4f for both" % white)
