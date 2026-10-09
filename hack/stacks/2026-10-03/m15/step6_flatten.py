"""Step 6: the sky left after the per-frame constant is a shallow dome (vignetted sky glow). Fit a smooth
2-D polynomial to block sky means of each stacked plane and subtract it. Blocks within CLUSTER_SKY_RADIUS of
the cluster centre and near bright stars take no part in the fit: under the cluster the surface is the
polynomial carried across from the sky around it. The same surface is subtracted from the single reference
frame."""
import json, os, sys, numpy as np, cv2
from common import *
ORDER = int(sys.argv[1]) if len(sys.argv) > 1 else 2
TAG = 'nodust_' if os.environ.get('M15_NODUST') == '1' else ''
BLK = 128
st = np.load(W(TAG + 'stack_planes.npy')); sg = np.load(W(TAG + 'single_planes.npy')); s5 = json.load(open(W(TAG + 'step5.json')))
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
x0, y0 = s5['origin_sensor_xy']; hh, ww = st.shape[1:]
stars = json.load(open(W('step2_stars.json'))); ref = [r for r in stars if r['stamp'] == REF_STAMP][0]['stars']
cl = np.array(s1[REF_STAMP]['cluster_sensor_xy']) - [x0, y0]
ny, nx = hh // BLK, ww // BLK
bx = (np.arange(nx) + 0.5) * BLK; by_ = (np.arange(ny) + 0.5) * BLK
BX, BY = np.meshgrid(bx, by_)
ok = np.hypot(BX - cl[0], BY - cl[1]) > CLUSTER_SKY_RADIUS + BLK * 0.71
for s in ref:
    if s['flux'] < 50000 and not s['saturated']: continue
    sx, sy = 2 * s['x'] + 0.5 - x0, 2 * s['y'] + 0.5 - y0
    rad = 400 if (s['saturated'] or s['flux'] > 5e5) else 200
    ok &= np.hypot(BX - sx, BY - sy) > rad
print('blocks', ny * nx, 'usable', int(ok.sum()), 'cluster at grid', cl.round(1))
def terms(X, Y, order):
    u = (X - ww / 2) / (ww / 2); v = (Y - hh / 2) / (hh / 2)
    return np.stack([u ** i * v ** j for i in range(order + 1) for j in range(order + 1 - i)], -1)
rec = []
gy, gx = np.mgrid[0:hh, 0:ww].astype(np.float32)
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
    rec.append(dict(plane=PLANE_NAMES[p], order=ORDER, block_px=BLK, blocks_usable=int(ok.sum()), blocks_used=int(keep.sum()), coefficients=[float(c) for c in coef], surface_min=float(surf.min()), surface_max=float(surf.max()),
                    surface_at_cluster=float(surf[int(cl[1]), int(cl[0])]), block_resid_rms=float(np.sqrt((r[keep] ** 2).mean()))))
    print({k_: (round(v_, 3) if isinstance(v_, float) else v_) for k_, v_ in rec[-1].items() if k_ != 'coefficients'})
    cr = resid_map.copy(); cr[~ok] = np.nan
    q = cr[:ny // 4 * 4, :nx // 4 * 4].reshape(ny // 4, 4, nx // 4, 4)
    with np.errstate(all='ignore'): print(np.round(np.nanmean(np.nanmean(q, 3), 1), 2))
    if p == 1:
        np.save(W(TAG + 'resid_blocks_G1.npy'), resid_map)
        # ring means of the residual around the cluster, to see how far cluster light reaches
        rb = np.hypot(BX - cl[0], BY - cl[1])
        for a, b_ in ((700, 900), (900, 1100), (1100, 1250), (1250, 1500), (1500, 1800), (1800, 2200), (2200, 2800)):
            m = (rb >= a) & (rb < b_)
            print('   G1 residual in ring %4d-%4d px (%.1f-%.1f arcmin): median %+.2f DN over %d blocks' % (a, b_, a * SCALE / 60, b_ * SCALE / 60, np.median(resid_map[m]), m.sum()))
np.save(W(TAG + 'stack_flat.npy'), flat); np.save(W(TAG + 'single_flat.npy'), flat_s)
json.dump(dict(order=ORDER, terms='u^i v^j, i+j<=order, u=(x-w/2)/(w/2), v=(y-h/2)/(h/2) on the stacked area', cluster_excluded_radius_px=CLUSTER_SKY_RADIUS, cluster_centre_on_grid=cl.tolist(), planes=rec), open(W(TAG + 'step6.json'), 'w'), indent=1)
