"""Vignetting, part 3: a third, independent flat from the M31 run itself, with no assumption about the galaxy.
The 'bright sky' frames are cloud: the stars lose light exactly as the sky brightens (step 5). A clouded frame is
    P_i = T_i * (galaxy + sky) * V  +  glow_i * V
with T_i the measured fraction of starlight that got through. The nearest clear frame gives (galaxy + sky) * V,
so  P_i - T_i * P_clear = glow_i * V : the cloud's glow, which lights the aperture evenly, seen through the
vignetting. Each such difference is divided by its own median, and the median over the clouded frames is taken in
SENSOR coordinates (no registration; what is left of the stars moves and drops out). Within 400 px of the
nucleus the galaxy does not cancel well enough (it shifts between the two frames) and is masked."""
import json, numpy as np, cv2
from common import *
BS = 16
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
q = {o['stamp']: o for o in json.load(open(W('step5_quality.json')))['quality']}
stamps = sorted(s1)
clear = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= 0.97]
cloud = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] <= 0.40 and s1[s]['corner_green'] >= 180]
print('clear frames', len(clear), 'clouded frames used', len(cloud))
def tsec(s): return int(s[9:11]) * 3600 + int(s[11:13]) * 60 + int(s[13:15])
h, w = 2012, 3012; yy, xx = np.mgrid[0:h, 0:w]
acc = {p: [] for p in range(4)}; glows = []
mask = np.ones((h, w), bool)
for s in cloud:
    j = min(clear, key=lambda c: abs(tsec(c) - tsec(s)))
    Pi = np.load(W('planes/' + s + '.npy'), mmap_mode='r'); Pj = np.load(W('planes/' + j + '.npy'), mmap_mode='r')
    T = q[s]['flux_rel']
    for nuc in (s1[j]['nucleus_sensor_xy'],):
        mask &= np.hypot(2 * xx + 0.5 - nuc[0], 2 * yy + 0.5 - nuc[1]) > 400
    g = []
    for p in range(4):
        D = np.asarray(Pi[p]) - T * np.asarray(Pj[p])
        m = float(np.median(D[::4, ::4])); g.append(m)
        acc[p].append((D / m).astype(np.float32))
    glows.append(g)
    print(s, 'T %.3f' % T, 'clear', j[9:], 'glow median R G1 G2 B', np.round(g, 1).tolist(), flush=True)
out = {}
for p in range(4):
    F = np.median(np.stack(acc[p]), axis=0); acc[p] = None
    Fm = np.where(mask, F, np.nan); ny, nx = h // BS, w // BS
    Fb = Fm[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(Fb).sum(2); v = np.nanmedian(Fb, axis=2)
    v[n < BS * BS // 2] = np.nan
    out['cloud_' + PLANE_NAMES[p]] = v; out['cloud_sky_' + PLANE_NAMES[p]] = np.array(float(np.median([g[p] for g in glows])))
    if p == 1: np.save(W('cloudflat_G1.npy'), F.astype(np.float32))
d = dict(np.load(W('vig_skyflats.npz'))); d.update(out)
np.savez(W('vig_skyflats.npz'), **d)
json.dump(dict(clear=clear, cloud=cloud, glow=dict(zip(cloud, glows))), open(W('vig_cloud.json'), 'w'), indent=1)
