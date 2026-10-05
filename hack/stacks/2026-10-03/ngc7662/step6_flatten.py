"""Step 6: the sky left after the per-frame constant is a shallow dome (vignetted sky glow). Fit a smooth
2-D polynomial to block sky means of each stacked plane (stars, nebula masked by clipping and by position)
and subtract it. The same surface is subtracted from the single reference frame."""
import json, os, sys, numpy as np, cv2
from common import *
ORDER = int(sys.argv[1]) if len(sys.argv) > 1 else 2
BLK = 128
st = np.load('stack_planes.npy'); sg = np.load('single_planes.npy'); s5 = json.load(open('step5.json'))
x0, y0 = s5['origin_sensor_xy']; hh, ww = st.shape[1:]
stars = json.load(open('step2_stars.json')); ref = [r for r in stars if r['stamp'] == REF_STAMP][0]['stars']
ny, nx = hh // BLK, ww // BLK
bx = (np.arange(nx) + 0.5) * BLK; by_ = (np.arange(ny) + 0.5) * BLK
BX, BY = np.meshgrid(bx, by_)
ok = np.ones((ny, nx), bool)
for s in ref:
    if s['flux'] < 20000: continue
    sx, sy = 2 * s['x'] + 0.5 - x0, 2 * s['y'] + 0.5 - y0
    rad = 400 if s['flux'] > 2e5 else 200
    ok &= np.hypot(BX - sx, BY - sy) > rad
def terms(X, Y, order):
    u = (X - ww / 2) / (ww / 2); v = (Y - hh / 2) / (hh / 2)
    return np.stack([u ** i * v ** j for i in range(order + 1) for j in range(order + 1 - i)], -1)
rec = []
gy, gx = np.mgrid[0:hh, 0:ww].astype(np.float32)
T_full = None
flat = np.empty_like(st); flat_s = np.empty_like(sg)
for p in range(4):
    blocks = st[p][:ny * BLK, :nx * BLK].reshape(ny, BLK, nx, BLK).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    bm = np.array([[clipped_stats(blocks[i, j], k=2.5)[0] for j in range(nx)] for i in range(ny)])
    A = terms(BX[ok], BY[ok], ORDER); b = bm[ok]
    keep = np.ones(len(b), bool)
    for _ in range(4):
        coef, *_ = np.linalg.lstsq(A[keep], b[keep], rcond=None)
        r = b - A @ coef; s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep])))
        keep = np.abs(r) < 3 * s
    surf = np.zeros((hh, ww), np.float32)
    u = (gx - ww / 2) / (ww / 2); v = (gy - hh / 2) / (hh / 2); k = 0
    for i in range(ORDER + 1):
        for j in range(ORDER + 1 - i):
            surf += np.float32(coef[k]) * u ** i * v ** j; k += 1
    flat[p] = st[p] - surf; flat_s[p] = sg[p] - surf
    resid_map = bm - terms(BX, BY, ORDER) @ coef
    rec.append(dict(plane=PLANE_NAMES[p], order=ORDER, block_px=BLK, blocks_used=int(keep.sum()), coefficients=[float(c) for c in coef], surface_min=float(surf.min()), surface_max=float(surf.max()),
                    surface_at_nebula=float(surf[2282 - y0, 3476 - x0]), block_resid_rms=float(np.sqrt((r[keep] ** 2).mean()))))
    print(rec[-1])
    cr = resid_map.copy(); cr[~ok] = np.nan
    # coarse view of residual, 6x6 super blocks
    q = cr[:ny // 5 * 5, :nx // 5 * 5].reshape(ny // 5, 5, nx // 5, 5)
    print(np.round(np.nanmean(np.nanmean(q, 3), 1), 2))
np.save('stack_flat.npy', flat); np.save('single_flat.npy', flat_s)
json.dump(dict(order=ORDER, terms='u^i v^j, i+j<=order, u=(x-w/2)/(w/2), v=(y-h/2)/(h/2) on the stacked area', planes=rec), open('step6.json', 'w'), indent=1)
