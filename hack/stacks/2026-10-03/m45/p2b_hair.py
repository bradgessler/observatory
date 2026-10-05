"""Step 2b: where the hair on the sensor was during each panel. Per panel: the median over its frames of
green / flat / small-scale flat / frame level, in a box at the top of the sensor; smoothed (Gaussian sigma 4 plane px)
and divided by its own wide median; the hair is the connected blob that is under 0.94 of its surroundings AND under
0.97 of the frame's sky level (so the dark ring this ratio draws round a bright star is not taken for it), of at
least 1500 plane px, nearest to where the hair was in the whole hour's sky flat (plane px 1855, 105)."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from c import *

F = json.load(open(W('p1.json')))['frames']
FLAT = np.load(os.path.join(CORE_WORK, 'flat2d.npy')); SMALL, _ = small_flat()
X0, Y0, X1, Y1 = 1500, 0, 2300, 420


def load(fr):
    P = load_planes(fr['path'])[0]
    G = ((P[1] / FLAT[1] + P[2] / FLAT[2]) / 2)[Y0:Y1, X0:X1]
    return G / max(float(np.median(G)), 1.0)

out = {}; tiles = []
for name in PANELS:
    fr = [f for f in F if f['panel'] == name]
    with ThreadPoolExecutor(7) as ex: g = list(ex.map(load, fr))
    M = np.median(np.stack(g), axis=0)
    Md = M / SMALL[Y0:Y1, X0:X1]
    sub = cv2.GaussianBlur(Md, (0, 0), 4)
    wide = cv2.medianBlur(cv2.resize(sub, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), 5)
    wide = cv2.resize(cv2.GaussianBlur(wide, (0, 0), 8), (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_CUBIC)
    rel = sub / wide
    n, lab, stats, cent = cv2.connectedComponentsWithStats(((rel < 0.94) & (sub < 0.97 * np.median(sub))).astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        if stats[i, 4] >= 1500 and (best is None or np.hypot(cent[i][0] + X0 - 1855, cent[i][1] + Y0 - 105) < np.hypot(cent[best][0] + X0 - 1855, cent[best][1] + Y0 - 105)): best = i
    if best is None:
        out[name] = None; print(name, 'no hair found; minimum of the smoothed ratio %.3f' % rel.min())
    else:
        ys, xs = np.nonzero(lab == best); w = 1 - rel[ys, xs]
        cx, cy = float((xs * w).sum() / w.sum()), float((ys * w).sum() / w.sum())
        mxx = (w * (xs - cx) ** 2).sum() / w.sum(); myy = (w * (ys - cy) ** 2).sum() / w.sum(); mxy = (w * (xs - cx) * (ys - cy)).sum() / w.sum()
        ang = 0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))
        out[name] = dict(centre_plane_px=[cx + X0, cy + Y0], centre_sensor_px=[2 * (cx + X0) + 0.5, 2 * (cy + Y0) + 0.5], area_plane_px=int(stats[best, 4]), deepest=float(rel[lab == best].min()), angle_deg=float(ang),
                         extent_plane_px=[int(xs.min() + X0), int(ys.min() + Y0), int(xs.max() + X0), int(ys.max() + Y0)], t=float(np.mean([tsec(f['t']) for f in fr])))
        print(name, 'hair centre plane px (%.0f, %.0f), area %d, deepest %.3f, angle %.0f deg, extent %s' % (cx + X0, cy + Y0, stats[best, 4], rel[lab == best].min(), ang, out[name]['extent_plane_px']))
    tiles.append((np.clip((rel - 0.8) / 0.3, 0, 1) * 255).astype(np.uint8))
json.dump(out, open(W('p2b_hair.json'), 'w'), indent=1)
sheet = np.vstack([np.hstack(tiles[0:4]), np.hstack(tiles[4:8]), np.hstack(tiles[8:11] + [np.zeros_like(tiles[0])])])
cv2.imwrite(W('v_hair.png'), cv2.resize(sheet, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))
