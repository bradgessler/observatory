"""Rerun step f5b: the black smudge the hair leaves in the picture, before and after. Green of the linear files in the
hair zone, 5x5 median then Gaussian sigma 6 px, minus the level of its surroundings: the largest patch more than
5, 10, 20 DN low, and the deepest value."""
import json, os, sys
import numpy as np, tifffile, cv2
from common import *
x0, y0 = 108, 110; sl = (slice(0, 700), slice(3300, 4500))
files = dict(B_before=os.path.join(OUT, 'before-flats', 'm31-core-linear.tif'), C_before=os.path.join(OUT, 'before-flats', 'm31-core-cloudflat-linear.tif'), F_after=sys.argv[1])
out = {}
for nm, p in files.items():
    t = tifffile.imread(p)[:, :, 1][sl]; sm = cv2.GaussianBlur(cv2.medianBlur(t, 5), (0, 0), 6)
    bg = float(np.median(np.concatenate([sm[400:700, 100:1100].ravel(), sm[0:400, 0:150].ravel(), sm[0:400, 1050:1200].ravel()]))); d = sm - bg
    out[nm] = dict(deepest_dn=float(d.min()), surroundings_dn=bg)
    for thr in (5, 10, 20):
        n, lab, st, cen = cv2.connectedComponentsWithStats((d < -thr).astype(np.uint8), connectivity=8)
        big = max(range(1, n), key=lambda i: st[i, 4]) if n > 1 else None
        out[nm]['more_than_%d_dn_low' % thr] = dict(sensor_px=int(st[big, 4]) if big else 0, size=[int(st[big, 2]), int(st[big, 3])] if big else [0, 0], centre_sensor_xy=[round(float(cen[big][0]) + 3300 + x0), round(float(cen[big][1]) + y0)] if big else None)
    print(nm, json.dumps(out[nm]))
json.dump(out, open(W('f5b_smudge.json'), 'w'), indent=1)
