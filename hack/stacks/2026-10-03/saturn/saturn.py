"""Saturn from many short RAW frames: find it in each, grade the frames, line them up to a fraction
of a pixel, and average the sharpest onto a grid three times finer than the sensor's.

No demosaicing: each of a frame's four colour planes (R, G, G, B) is laid onto the fine grid at its
own place in the 2x2 colour cell and at that frame's own offset, so the frames, each landing at a
different fraction of a pixel, fill the fine grid in between them. Red and blue are then slid onto
green (the air spreads colours like a weak prism, more the lower the planet is). Nothing here
predicts a pixel: every output pixel is an average of measured ones.

Usage: saturn.py <folder of .ARW> <out stem> [keep fraction, default 0.5]
"""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
import rawpy

SRC, STEM = sys.argv[1], sys.argv[2]
KEEP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
HALF = 48          # half-size pixels kept each side of the planet (96 native px)
UP = 6             # fine grid: 6 per half-size pixel = 3 per native pixel


def planes(path):
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32); pat, desc = r.raw_pattern, r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32); white = float(r.white_level); wb = np.array(r.camera_whitebalance[:3], np.float32)
    out = []
    for y in (0, 1):
        for x in (0, 1):
            out.append((desc[pat[y, x]], x, y, (raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]])))
    return out, wb / wb[1]


def find(path):
    """Where the planet is (half-size px, to a fraction), how bright, and how sharp this frame is."""
    try:
        pl, wb = planes(path)
    except Exception as e:
        return dict(path=path, ok=False, why=str(e))
    g = (pl[1][3] + pl[2][3]) / 2 if pl[1][0] == "G" else sum(p[3] for p in pl if p[0] == "G") / 2
    sm = cv2.GaussianBlur(g, (0, 0), 4)
    cy, cx = np.unravel_index(np.argmax(sm), sm.shape); peak = float(sm[cy, cx])
    h, w = g.shape
    if peak < 0.02 or cx < HALF + 8 or cy < HALF + 8 or cx > w - HALF - 8 or cy > h - HALF - 8:
        return dict(path=path, ok=False, why="no planet in the frame" if peak < 0.02 else "planet at the edge")
    t = g[cy - HALF:cy + HALF, cx - HALF:cx + HALF]
    bgd = float(np.median(g[::16, ::16])); t0 = np.clip(t - bgd, 0, None)
    yy, xx = np.mgrid[0:2 * HALF, 0:2 * HALF]; m = t0 > 0.25 * t0.max()
    fx = float((xx * t0 * m).sum() / (t0 * m).sum()) + cx - HALF; fy = float((yy * t0 * m).sum() / (t0 * m).sum()) + cy - HALF
    # sharpness: how much of the light sits in fine detail (gradient energy over the planet, per unit light)
    gx_, gy_ = np.gradient(cv2.GaussianBlur(t0, (0, 0), 0.8)); sharp = float(((gx_ ** 2 + gy_ ** 2) * m).sum() / (t0 * m).sum() ** 2 * 1e4)
    return dict(path=path, ok=True, x=fx, y=fy, peak=float(t.max()), flux=float(t0[m].sum()), sharp=sharp, clipped=int((t >= 0.98).sum()))


def tile(args):
    """One frame's planet on the fine grid, each colour plane read at its own place: (rgb sum, weight)."""
    path, fx, fy = args
    pl, wb = planes(path); n = 2 * HALF * UP
    acc = np.zeros((n, n, 3), np.float32); wsum = np.zeros((n, n, 3), np.float32)
    # fine pixel (X, Y) sits at half-size coordinate fx - HALF + (X + 0.5) / UP - 0.5
    X = (np.arange(n, dtype=np.float32) + 0.5) / UP - 0.5
    mx, my = np.meshgrid(X + np.float32(fx - HALF), X + np.float32(fy - HALF))
    for colour, x, y, p in pl:
        c = "RGB".index(colour)
        v = cv2.remap(p, mx - (x - 0.5) / 2, my - (y - 0.5) / 2, cv2.INTER_LANCZOS4)
        acc[:, :, c] += v * wb[c]; wsum[:, :, c] += 1
    return acc / wsum


def shift_to(ref, img):
    """How far img sits from ref, to a fraction of a fine pixel (phase correlation on brightness)."""
    win = cv2.createHanningWindow(ref.shape[::-1], cv2.CV_32F)
    (dx, dy), _ = cv2.phaseCorrelate(ref.astype(np.float32), img.astype(np.float32), win)
    return dx, dy


if __name__ == "__main__":
    files = sorted(glob.glob(os.path.join(SRC, "*.ARW")))
    with ProcessPoolExecutor(8) as ex:
        found = list(ex.map(find, files))
    good = [f for f in found if f["ok"] and f["clipped"] == 0]
    bad = [f for f in found if not f["ok"]]; clipped = [f for f in found if f["ok"] and f["clipped"] > 0]
    # the same exposure only: a frame far brighter or dimmer than the rest is another setting, or cloud
    med = np.median([f["flux"] for f in good]); good = [f for f in good if 0.6 * med < f["flux"] < 1.6 * med]
    good.sort(key=lambda f: -f["sharp"])
    keep = good[:max(int(round(KEEP * len(good))), min(len(good), 4))]
    print("%d frames: %d usable (%d without the planet, %d clipped, %d another exposure); the sharpest %d kept" % (len(files), len(good), len(bad), len(clipped), len(found) - len(bad) - len(clipped) - len(good), len(keep)))
    with ProcessPoolExecutor(8) as ex:
        tiles = list(ex.map(tile, [(f["path"], f["x"], f["y"]) for f in keep]))
    # the centroid put them within a pixel; phase correlation against the running mean does the rest, twice
    lum = [t.sum(2) for t in tiles]; ref = np.mean(lum, 0); shifts = [(0.0, 0.0)] * len(tiles)
    for _ in range(2):
        shifts = [shift_to(ref, l) for l in lum]
        moved = [cv2.warpAffine(t, np.float32([[1, 0, -dx], [0, 1, -dy]]), t.shape[1::-1], flags=cv2.INTER_LANCZOS4) for t, (dx, dy) in zip(tiles, shifts)]
        ref = np.mean([m.sum(2) for m in moved], 0)
    stack = np.mean(moved, 0)
    # the colours onto green
    disp = {}
    for c, name in ((0, "red"), (2, "blue")):
        dx, dy = shift_to(stack[:, :, 1], stack[:, :, c]); disp[name] = [round(dx / 3, 2), round(dy / 3, 2)]
        stack[:, :, c] = cv2.warpAffine(stack[:, :, c], np.float32([[1, 0, -dx], [0, 1, -dy]]), stack.shape[1::-1], flags=cv2.INTER_LANCZOS4)
    np.save(STEM + ".npy", stack)
    white = np.percentile(stack, 99.9)
    cv2.imwrite(STEM + ".png", (np.clip(stack[:, :, ::-1] / white, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8))
    rms = float(np.sqrt(np.mean([dx * dx + dy * dy for dx, dy in shifts])) / 3)
    json.dump(dict(frames=len(files), usable=len(good), kept=len(keep), keep=KEEP, fine_grid_per_native_px=3, residual_shift_native_px_rms=rms, colours_moved_native_px=disp,
                   used=[os.path.basename(f["path"]) for f in keep], sharpness=dict(best=keep[0]["sharp"], worst_kept=keep[-1]["sharp"], worst=good[-1]["sharp"] if good else None),
                   discarded=dict(no_planet=[os.path.basename(f["path"]) for f in bad], clipped=[os.path.basename(f["path"]) for f in clipped])), open(STEM + ".json", "w"), indent=1)
    print("sharpness: best %.2f, worst kept %.2f, worst %.2f; frames agreed to %.2f native px after the centroid; red moved %s, blue %s native px" % (keep[0]["sharp"], keep[-1]["sharp"], good[-1]["sharp"], rms, disp["red"], disp["blue"]))
