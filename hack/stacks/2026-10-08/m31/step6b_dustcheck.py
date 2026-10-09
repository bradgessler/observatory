"""Step 6b: check the dust of step 6 against the hour. A dust shadow is fixed on the sensor; the M76 and M57 runs see it
on open sky, the M31 frames see it on the galaxy. For every clear shadow in step 6's map (connected blocks below
1 - 5 sigma of the smoothed map, more than 600 sensor px from the nucleus in every M31 frame, so that the galaxy's
own slope under a shadow is gentle): depth = median of the blocks in its core (within 0.7 of its equivalent radius)
over the median of a ring round it (1.8 to 2.8 radii, other shadows left out), in sensor coordinates, for:
the M76 run's block map, the M57 run's block map, and each used M31 frame's 8 x 8 block medians (green, black
subtracted, the frame's dark-corner level ADDED BACK is not needed: the planes are only black subtracted). The M31
depth is the median over its frames. If the three agree, step 8 may divide the shadows out; the ratio M31 / M76+M57
is written, so that a systematic difference is seen, not hidden."""
import numpy as np, cv2
from common import *

BS = 8
d = np.load(W('dust_blocks.npz')); Ds = d['Ds']; sD = float(d['sigma_Ds'])
sk = np.load(W('vig_skyflats.npz')) if os.path.exists(W('vig_skyflats.npz')) else None
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
ny, nx = Ds.shape
Y, X = np.mgrid[0:ny, 0:nx]
bx, by = 2 * (X * BS + (BS - 1) / 2) + 0.5, 2 * (Y * BS + (BS - 1) / 2) + 0.5
lab_n, lab, st, cen = cv2.connectedComponentsWithStats((Ds < 1 - 5 * sD).astype(np.uint8), connectivity=8)
anydust = Ds < 1 - 3 * sD
nuc = np.array([s1[s]['nucleus_sensor_xy'] for s in s1 if s >= '20261009-062555'])
spots = []
for i in range(1, lab_n):
    a = st[i, cv2.CC_STAT_AREA]
    if a < 3: continue
    cx, cy = cen[i]; req = max(np.sqrt(a / np.pi), 1.0)
    sx, sy = 2 * (cx * BS + (BS - 1) / 2) + 0.5, 2 * (cy * BS + (BS - 1) / 2) + 0.5
    if np.min(np.hypot(nuc[:, 0] - sx, nuc[:, 1] - sy)) < 600: continue
    if cx < 3 * req or cy < 3 * req or cx > nx - 3 * req or cy > ny - 3 * req: continue
    r = np.hypot(X - cx, Y - cy)
    core = r <= 0.7 * req; ring = (r >= 1.8 * req) & (r <= 2.8 * req) & ~anydust
    if core.sum() < 1 or ring.sum() < 8: continue
    spots.append(dict(block_xy=[float(cx), float(cy)], sensor_xy=[float(sx), float(sy)], radius_sensor_px=float(2 * BS * req), core=core, ring=ring))
print('shadows to check:', len(spots))

def depth(B, s):
    return float(np.nanmedian(B[s['core']]) / np.nanmedian(B[s['ring']]))

tabs = np.load(W('runs_blocks.npz'))
for s in spots:
    s['m76'] = depth(np.nanmean(tabs['m76'][1:3], 0), s); s['m57'] = depth(np.nanmean(tabs['m57'][1:3], 0), s); s['map'] = depth(Ds, s)
used = [k for k in sorted(s1) if k >= '20261009-062555'] + ['20261009-062444']
per = {i: [] for i in range(len(spots))}
for stamp in used:
    P = np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')
    G = (np.asarray(P[1]) + np.asarray(P[2])) / 2
    B = np.median(G[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    for i, s in enumerate(spots): per[i].append(depth(B, s))
out = []
for i, s in enumerate(spots):
    m31 = float(np.median(per[i])); m31_err = float(1.2533 * np.std(per[i]) / np.sqrt(len(per[i])))
    out.append(dict(sensor_xy=[round(v) for v in s['sensor_xy']], radius_sensor_px=round(s['radius_sensor_px']), depth_m76=round(s['m76'], 4), depth_m57=round(s['m57'], 4),
                    depth_combined_map=round(s['map'], 4), depth_m31_frames=round(m31, 4), depth_m31_error=round(m31_err, 4)))
    print(out[-1])
loss = lambda k: np.array([1 - o[k] for o in out])
lm, l76, l57, l31 = loss('depth_combined_map'), loss('depth_m76'), loss('depth_m57'), loss('depth_m31_frames')
deep = lm > 0.04
ratio = float(np.median(l31[deep] / lm[deep])) if deep.any() else None
ratio76 = float(np.median(l76[deep] / lm[deep])) if deep.any() else None
ratio57 = float(np.median(l57[deep] / lm[deep])) if deep.any() else None
print('shadows deeper than 4%% in the map: %d; light lost, median ratio to the map: M31 frames %.3f, M76 %.3f, M57 %.3f' % (deep.sum(), ratio, ratio76, ratio57))
jdump(dict(method=__doc__, shadows=out, deeper_than_4pct=int(deep.sum()), loss_ratio_m31_over_map=ratio, loss_ratio_m76_over_map=ratio76, loss_ratio_m57_over_map=ratio57), 'step6b_dustcheck.json')

# ---------------- the dust model step 8 divides by ----------------
# A block is in a CONFIRMED shadow when the combined smoothed map is below 1 - 4 sigma AND each run on its own (its
# high-pass ratio smoothed by one block) is below 1 - 2.5 of its own sigma: the shadow was seen independently on two
# different skies. Those regions are grown by one block and feathered (Gaussian, 1 block); inside, the model is the
# combined map; outside it is exactly 1. Single-run 'shadows' (noise, a star's ring, an edge) are not divided out.
def run_hp(run):
    with np.errstate(all='ignore'):
        B = np.nanmean(tabs[run][1:3], 0)
    valid = np.isfinite(B)
    for _ in range(4):
        num = cv2.GaussianBlur(np.where(valid, B, 0).astype(np.float32), (0, 0), 6, borderType=cv2.BORDER_REFLECT)
        den = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), 6, borderType=cv2.BORDER_REFLECT)
        S = num / np.maximum(den, 1e-6); r = B / S - 1
        s = 1.4826 * np.nanmedian(np.abs(r[valid] - np.nanmedian(r[valid])))
        bad = ~(np.abs(np.nan_to_num(r, nan=0.0)) < 2.5 * s) | ~np.isfinite(B)
        valid = np.isfinite(B) & ~cv2.dilate(bad.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    hp_ = cv2.GaussianBlur(np.nan_to_num(B / S, nan=1.0).astype(np.float32), (0, 0), 1.0)
    return hp_, float(1.4826 * np.median(np.abs(hp_ - np.median(hp_))))
h76, s76 = run_hp('m76'); h57, s57 = run_hp('m57')
conf = (Ds < 1 - 4 * sD) & (h76 < 1 - 2.5 * s76) & (h57 < 1 - 2.5 * s57)
lab_n2, lab2, st2, _ = cv2.connectedComponentsWithStats(conf.astype(np.uint8), connectivity=8)
keep = np.zeros_like(conf)
for i in range(1, lab_n2):
    if st2[i, cv2.CC_STAT_AREA] >= 2: keep |= lab2 == i          # a single block alone is not a shadow
region = cv2.dilate(keep.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(np.float32)
wgt = np.clip(cv2.GaussianBlur(region, (0, 0), 1.0) * 1.5, 0, 1)
model = (1 - wgt) * 1.0 + wgt * np.minimum(Ds, 1.0)
np.savez(W('dust_model.npz'), bs=BS, model=model.astype(np.float32), confirmed=keep)
nshadow = int(cv2.connectedComponents(keep.astype(np.uint8))[0] - 1)
print('confirmed shadow blocks %d in %d shadows; deepest model value %.3f; model below 0.97 over %.2f%% of the sensor' % (keep.sum(), nshadow, model.min(), 100 * (model < 0.97).mean()))
J = jload('step6b_dustcheck.json'); J['dust_model'] = dict(rule='combined map below 1 - 4 sigma AND each run alone below 1 - 2.5 sigma; groups of 2+ blocks; grown 1 block, feathered', blocks=int(keep.sum()), shadows=nshadow,
                                                        deepest=round(float(model.min()), 3), fraction_below_097=round(float((model < 0.97).mean()), 4), sigma_m76=round(s76, 4), sigma_m57=round(s57, 4), sigma_combined=round(sD, 4))
jdump(J, 'step6b_dustcheck.json')
cv2.imwrite(W('dust_model.png'), cv2.resize((np.clip((model - 0.85) / 0.15, 0, 1) * 255).astype(np.uint8), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
