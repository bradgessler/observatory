"""Cut a rectangle out of a picture, pixels untouched, and write down what was cut and why.

Usage: crop.py <in.png> <out stem> <x> <y> <width> <height> "<why>"
"""
import json, sys
import cv2
src, stem = sys.argv[1], sys.argv[2]; x, y, w, h = map(int, sys.argv[3:7]); why = sys.argv[7] if len(sys.argv) > 7 else ""
im = cv2.imread(src, cv2.IMREAD_UNCHANGED); H, W = im.shape[:2]; out = im[y:y + h, x:x + w]
cv2.imwrite(stem + ".png", out)
json.dump(dict(what="a crop, pixels untouched", source=src, source_px=[W, H], crop_px=[x, y, out.shape[1], out.shape[0]], why=why), open(stem + ".json", "w"), indent=1)
print("%s: %d x %d from %d x %d at (%d, %d)" % (stem, out.shape[1], out.shape[0], W, H, x, y))
