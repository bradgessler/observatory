#!/usr/bin/env python3
"""Is that dark spot dust? Compare the same sensor pixels in two different targets.

Dust sits on the sensor, so it is in the same place in every picture wherever the telescope points; anything in
the sky moves. Give two sets of JPEGs from two different targets (same camera, same night). Each set is median
stacked in sensor orientation (EXIF ignored), stars and the object hidden, divided by its own smoothed glow; a
spot is dust only where it is dark in both maps. Prints the spots (sensor pixel, size, depth) and writes a
picture with each spot cropped from both stacks side by side, to show anyone.

    dustcheck.py "<glob of target A JPEGs>" "<glob of target B JPEGs>" out.png [--scale 0.388] [--at x,y ...]

--at checks given sensor pixels instead of finding spots (a spot someone saw on the camera's screen).
17 October 2026: Brad saw dark blotches on the screen during M33; this, done by hand with M27's frames, proved
them dust (and the box's sensor map now runs the same rule, `Controller.StillCamera.SensorMap`).
Deterministic: medians and fixed thresholds only; it reads the pictures and never writes them.
"""
import argparse, glob, sys, warnings
import numpy as np, cv2

ap = argparse.ArgumentParser()
ap.add_argument("a"); ap.add_argument("b"); ap.add_argument("out")
ap.add_argument("--scale", type=float, default=0.388, help="arcsec per full-resolution pixel")
ap.add_argument("--max", type=int, default=16, help="pictures per target")
ap.add_argument("--dim", type=float, default=0.03, help="pixels darker than this fraction make up a spot")
ap.add_argument("--min-depth", type=float, default=0.05, help="report spots at least this deep (the noise of a 16-picture median is about 3 percent)")
ap.add_argument("--at", nargs="*", default=[], help="sensor pixels x,y to check instead of finding spots")
args = ap.parse_args()

SHRINK = 4
warnings.filterwarnings("ignore", message="All-NaN slice")

def load(pattern):
    files = sorted(glob.glob(pattern))[: args.max]
    if len(files) < 3:
        sys.exit(f"need at least 3 pictures for {pattern!r}, found {len(files)}")
    full, small = [], []
    for f in files:
        g = cv2.imread(f, cv2.IMREAD_GRAYSCALE | cv2.IMREAD_IGNORE_ORIENTATION).astype(np.float32)
        full.append(g)
        s = cv2.resize(g, (g.shape[1] // SHRINK, g.shape[0] // SHRINK), interpolation=cv2.INTER_AREA)
        sky = np.median(s)
        s = s / max(sky, 1)
        s[s > 1.25 + 3 / max(sky, 1)] = np.nan  # stars and the object's bright parts are not the sensor
        small.append(s)
    return files, np.median(np.stack(full), axis=0), np.nanmedian(np.stack(small), axis=0)

def relative(med, r=12):
    filled = np.where(np.isnan(med), np.nanmedian(med), med).astype(np.float32)
    glow = cv2.blur(filled, (2 * r + 1, 2 * r + 1))
    rel = med / glow
    rel[:r, :] = rel[-r:, :] = rel[:, :r] = rel[:, -r:] = np.nan  # the frame's border is not judged
    return rel

fa, full_a, small_a = load(args.a)
fb, full_b, small_b = load(args.b)
both = np.fmax(relative(small_a), relative(small_b))  # dark only where dark in both

if args.at:
    spots = [tuple(int(v) for v in p.split(",")) + (None, None) for p in args.at]
else:
    dark = (np.nan_to_num(both, nan=1.0) < 1 - args.dim).astype(np.uint8)
    # one speck of dust can break into pieces at the threshold (17 October: the crescent came out as three)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(dark)
    spots = []
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        if area < 8:  # smaller is the noise of a few pictures' median
            continue
        depth = 1 - np.nanmin(np.where(lab == i, both, np.nan))
        if depth >= args.min_depth:
            spots.append((int(cen[i][0] * SHRINK), int(cen[i][1] * SHRINK), 2 * np.sqrt(area / np.pi) * SHRINK * args.scale, depth))
    spots.sort(key=lambda s: -s[2])

print(f"{len(fa)} pictures of A, {len(fb)} of B; {len(spots)} spots dark in both")
for x, y, d, depth in spots[:20]:
    print(f"  sensor ({x}, {y})" + (f"  {d:.0f} arcsec across, {depth * 100:.1f}% deep" if d else ""))

R, T = 330, 330
rows = []
for x, y, *_ in spots[:6]:
    cells = []
    for full in (full_a, full_b):
        pad = np.pad(full, R, mode="edge")
        c = pad[y : y + 2 * R, x : x + 2 * R]
        m = np.median(c)
        v = np.clip((c - (m - 6)) / 14, 0, 1)
        cells.append(cv2.resize((v * 255).astype(np.uint8), (T, T)))
    rows.append(np.hstack([cells[0], np.full((T, 8), 255, np.uint8), cells[1]]))
if rows:
    grid = []
    for r in rows:
        grid += [r, np.full((8, 2 * T + 8), 255, np.uint8)]
    cv2.imwrite(args.out, np.vstack(grid[:-1]))
    print(f"wrote {args.out}: each row one spot, target A on the left, B on the right")
