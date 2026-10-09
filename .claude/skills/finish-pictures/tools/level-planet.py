"""Turn a planet picture so its long axis (Saturn's rings) lies level, and crop round it. One Lanczos rotation.
Usage: level-planet.py <in.png> <out.png> [crop width] [crop height]"""
import sys, json
import numpy as np, cv2
im = cv2.imread(sys.argv[1], cv2.IMREAD_COLOR); cw = int(sys.argv[3]) if len(sys.argv) > 3 else 460; ch = int(sys.argv[4]) if len(sys.argv) > 4 else 260
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float64); m = g * (g > 0.12 * g.max())
yy, xx = np.mgrid[0:g.shape[0], 0:g.shape[1]]; tot = m.sum(); cx, cy = (xx * m).sum() / tot, (yy * m).sum() / tot
mu20, mu02, mu11 = ((xx - cx) ** 2 * m).sum() / tot, ((yy - cy) ** 2 * m).sum() / tot, ((xx - cx) * (yy - cy) * m).sum() / tot
ang = 0.5 * np.degrees(np.arctan2(2 * mu11, mu20 - mu02))            # the long axis, degrees clockwise from level in picture terms
M = cv2.getRotationMatrix2D((cx, cy), ang, 1.0); M[0, 2] += cw / 2 - cx; M[1, 2] += ch / 2 - cy
out = cv2.warpAffine(im, M, (cw, ch), flags=cv2.INTER_LANCZOS4, borderValue=0)
cv2.imwrite(sys.argv[2], out)
json.dump(dict(what="levelled on the long axis from brightness moments", source=sys.argv[1], turned_deg=round(float(ang), 2), centre=[round(float(cx), 1), round(float(cy), 1)], size=[cw, ch], resampling="one Lanczos-4 rotation"), open(sys.argv[2][:-4] + ".json", "w"), indent=1)
print("turned %.2f deg about (%.1f, %.1f), cropped %d x %d" % (ang, cx, cy, cw, ch))
