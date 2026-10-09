"""How neutral is the dark sky of a picture? Median R, G, B of its darkest parts (two bands), and of the whole.
Usage: skycheck.py picture.png [more.png ...]"""
import sys, numpy as np, cv2
for f in sys.argv[1:]:
    im = cv2.imread(f, cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32); have = im.max(2) > 0
    Y = im @ np.array([0.2126, 0.7152, 0.0722], np.float32); out = []
    for lo, hi in ((0, 10), (10, 40)):
        a, b = np.percentile(Y[have], [lo, hi]); m = have & (Y >= a) & (Y <= b)
        r, g, bl = [float(np.mean(im[..., c][m])) for c in range(3)]
        out.append("darkest %2d-%2d%%: R %5.1f G %5.1f B %5.1f (R-G %+5.1f, B-G %+5.1f)" % (lo, hi, r, g, bl, r - g, bl - g))
    print("%-28s %s | %s" % (f.split("/")[-1], out[0], out[1]))
