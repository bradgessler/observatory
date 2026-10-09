"""Level a tilted mosaic and crop it to a clean rectangle.

A mosaic placed north-up comes out as a tilted patch of sky on a black canvas. This turns the picture so the patch's
long side is level (one Lanczos resampling), then crops to the largest upright rectangle that holds only measured sky.
Nothing is filled in: pixels with no data stay outside the crop, or stay black if --keep-holes lets small gaps in.

Usage: level.py <picture.png> <out stem> [--keep-holes N] [--coverage map.tif]
  N: gaps up to N pixels across may stay inside the crop; the coverage map says where the mosaic has data
"""
import sys, json
import numpy as np, cv2

src, stem = sys.argv[1], sys.argv[2]
keep = int(sys.argv[sys.argv.index("--keep-holes") + 1]) if "--keep-holes" in sys.argv else 0
im = cv2.imread(src, cv2.IMREAD_COLOR)
# where there is sky: from the mosaic's own coverage map when given (a sky stretched to true black looks like "no data"),
# else from the pixels that are not exactly black
if "--coverage" in sys.argv:
    cov = cv2.imread(sys.argv[sys.argv.index("--coverage") + 1], cv2.IMREAD_UNCHANGED)
    cov = cov if cov.ndim == 2 else cov.max(2)
    data = (cv2.resize((cov > 0).astype(np.uint8), (im.shape[1], im.shape[0]), interpolation=cv2.INTER_NEAREST) > 0).astype(np.uint8)
else:
    data = (im.max(2) > 0).astype(np.uint8)
data = cv2.morphologyEx(data, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))          # single dark pixels of sky are not gaps
n, lab, stats, _ = cv2.connectedComponentsWithStats(data, 8)
main = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)       # the mosaic itself, not stray specks
(cx, cy), (w, h), ang = cv2.minAreaRect(cv2.findContours(main, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0])
if w < h: ang += 90                                                                # long side level
ang = (ang + 90) % 180 - 90                                                        # the smaller turn
H, W = im.shape[:2]; M = cv2.getRotationMatrix2D((W / 2, H / 2), ang, 1.0)
c, s = abs(M[0, 0]), abs(M[0, 1]); W2, H2 = int(H * s + W * c), int(H * c + W * s); M[0, 2] += W2 / 2 - W / 2; M[1, 2] += H2 / 2 - H / 2
out = cv2.warpAffine(im, M, (W2, H2), flags=cv2.INTER_LANCZOS4, borderValue=0)
mask = cv2.warpAffine(main, M, (W2, H2), flags=cv2.INTER_NEAREST, borderValue=0)
if keep:                                                                           # small gaps may stay, as black
    holes = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (keep, keep))) - mask
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(holes, 8)
    edge = cv2.erode(cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((keep * 3, keep * 3), np.uint8)), np.ones((keep, keep), np.uint8))
    for i in range(1, n2):
        if (edge[lab2 == i] > 0).all(): mask[lab2 == i] = 1                        # only gaps well inside the patch
mask = cv2.erode(mask, np.ones((7, 7), np.uint8))                                  # resampled edge pixels are part sky, part nothing
# the largest upright rectangle of data: maximal rectangle in a binary grid, on 4x4 blocks
B = 4; hb, wb = mask.shape[0] // B, mask.shape[1] // B
g = mask[:hb * B, :wb * B].reshape(hb, B, wb, B).min(axis=(1, 3))
best = (0, 0, 0, 0, 0); heights = np.zeros(wb, np.int32)
for y in range(hb):
    heights = np.where(g[y] > 0, heights + 1, 0); stack = []
    for x in range(wb + 1):
        hgt = heights[x] if x < wb else 0; start = x
        while stack and stack[-1][1] >= hgt:
            sx, sh = stack.pop(); area = sh * (x - sx)
            if area > best[0]: best = (area, sx, y - sh + 1, x - sx, sh)
            start = sx
        stack.append((start, hgt))
_, x0, y0, cw, ch = best; x0, y0, cw, ch = x0 * B, y0 * B, cw * B, ch * B
crop = out[y0:y0 + ch, x0:x0 + cw]
cv2.imwrite(stem + ".png", crop); cv2.imwrite(stem + ".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
left_black = float((crop.max(2) == 0).mean() * 100)
json.dump(dict(what="levelled and cropped", source=src, turned_deg_counterclockwise=round(float(ang), 3),
               note="the source was north up, east left; in this picture north is %.1f deg %s of up" % (abs(ang), "counter-clockwise (left)" if ang > 0 else "clockwise (right)"),
               resampling="one Lanczos-4 rotation", crop_px=[int(x0), int(y0), int(cw), int(ch)], size=[int(cw), int(ch)],
               source_px_to_this_px=[[float(M[0, 0]), float(M[0, 1]), float(M[0, 2] - x0)], [float(M[1, 0]), float(M[1, 1]), float(M[1, 2] - y0)]],
               kept_of_data_pct=round(100.0 * cw * ch / max(int(main.sum()), 1), 1), gaps_allowed_px=keep, black_inside_pct=round(left_black, 3)), open(stem + ".json", "w"), indent=1)
print("%s: turned %.1f deg, cropped to %d x %d (%.0f%% of the data kept), black inside %.2f%%" % (stem.split("/")[-1], ang, cw, ch, 100.0 * cw * ch / max(int(main.sum()), 1), left_black))
