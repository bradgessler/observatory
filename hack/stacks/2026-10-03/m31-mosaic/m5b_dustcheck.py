"""Mosaic step 5b: does the core run's dust map still hold an hour or two later, and where is the hair now?
The heavily clouded frames of the mosaic run (transparency below 0.33 or not measurable) are mostly cloud glow.
Each is divided by the core run's smooth flat and by its own smooth light (8x shrink, 5x5 median twice, 31-block box blur = 250 plane px, as the core run's
dust step does); the median over those frames, in SENSOR coordinates, is the small-scale flat (dust shadows) of
this hour: stars and the galaxy sit at different places in different panels and drop out. Compared with the core
run's dust ratio map (dustratio.npy) inside the core's dust mask and inside the hair box.

Also written: smallflat_mosaic.npy, the small-scale flat that step 6 divides every frame by. Outside the dust
masks the two independent maps (core run: 36 clouded frames; this hour: 19) share a real pattern of about 0.25%
(correlation 0.27 per pixel, 0.64 after a 12 px blur): faint dust rings under the mask's threshold and pixel-scale
flat structure. On the core's dark sky that was under 1 DN and smeared by the field's motion; on a moonlit sky of
250 to 500 DN, in panels where the field hardly moves, a 1.4% ring is 4 to 7 DN, as deep as the outer disc.
smallflat = the noise-weighted mean of the two maps (this hour's alone inside the zone near the core run's nucleus
where the core map is blind), blurred by a further 3 plane px outside the masks, kept sharp inside them, held to
0.5..1.05, and set to 1 (nothing divided) wherever either map shows the hair, because the hair moves.

Written: dustratio_mosaic.npy (this hour's small-scale flat, Gaussian sigma 2.5 plane px) and dustmask_mosaic.npy =
the core run's mask OR this hour's shadows (same thresholds as the core: below 0.980, or a sigma-4 copy below
0.986, blobs of 60 plane px or more, grown by 6 px), and hairmask.npy = the hair's shadow at its place in the
core run and at its place in this hour, grown by 40 plane px."""
import json, numpy as np, cv2
from mcommon import *
sel = json.load(open(W('m5_select.json')))
FLAT = np.load(CW('flat2d.npy')); DUST = np.load(CW('dustmask.npy')); RATIO = np.load(CW('dustratio.npy'))
cl = []
for name in sel:
    for r in sel[name]['quality']:
        if (r['flux_rel'] is None or r['flux_rel'] < 0.33) and r['corner_green'] > 430: cl.append((r['stamp'], name, r['flux_rel'], r['corner_green']))
print(len(cl), 'heavily clouded frames:', [(s[9:], n, None if t is None else round(t, 2), round(c)) for s, n, t, c in cl])
acc = []
for s, n, t, c in cl:
    P = np.load(W('planes/' + s + '.npy'), mmap_mode='r')
    G = (P[1] / FLAT[1] + P[2] / FLAT[2]) / 2
    small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    acc.append((G / cv2.resize(low, (W2, H2), interpolation=cv2.INTER_CUBIC)).astype(np.float32))
M = np.median(np.stack(acc), axis=0); del acc
Ms = cv2.GaussianBlur(M, (0, 0), 2.5)
np.save(W('dustratio_mosaic.npy'), Ms)
noise = float(1.4826 * np.median(np.abs(Ms[900:1100, 300:500] - np.median(Ms[900:1100, 300:500]))))
inm = DUST; a = RATIO[inm][::7]; b = Ms[inm][::7]
deep = (RATIO < 0.97) & DUST
print('ratio noise %.4f; inside the core dust mask: core ratio median %.4f, this hour %.4f; correlation of depth (1 - ratio) %.3f; slope this/core %.3f (pixels where the core map is deeper than 3%%: core %.4f now %.4f)' % (
    noise, np.median(a), np.median(b), np.corrcoef(1 - a, 1 - b)[0, 1], float(((1 - a) * (1 - b)).sum() / ((1 - a) ** 2).sum()), np.median(RATIO[deep]), np.median(Ms[deep])))
# this hour's mask, by the core's rule
m = (Ms < 0.98) | (cv2.GaussianBlur(M, (0, 0), 4.0) < 0.986)
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
now = np.isin(lab, np.array([i for i in range(1, n) if stats[i, 4] >= 60]))
now = cv2.dilate(now.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool)
union = DUST | now
np.save(W('dustmask_mosaic.npy'), union)
hx0, hy0, hx1, hy1 = [v // 2 for v in HAIR_BOX]
hair = np.zeros_like(union); hair[hy0:hy1, hx0:hx1] = ((RATIO < 0.95) | (Ms < 0.95))[hy0:hy1, hx0:hx1]
hair = cv2.dilate(hair.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81))).astype(bool)
np.save(W('hairmask.npy'), hair)
ys, xs = np.nonzero(hair)
print('core mask %.2f%% of the sensor, this hour %.2f%%, union %.2f%%; of the core mask %.0f%% is also marked now; hair mask: sensor x %d..%d, y %d..%d (%.2f%%)' % (100 * DUST.mean(), 100 * now.mean(), 100 * union.mean(), 100 * (DUST & now).sum() / DUST.sum(), 2 * xs.min(), 2 * xs.max(), 2 * ys.min(), 2 * ys.max(), 100 * hair.mean()))
new = now & ~DUST
n, lab, stats, cent = cv2.connectedComponentsWithStats(new.astype(np.uint8), connectivity=8)
blobs = sorted([dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5), round(2 * float(cent[i][1]) + 0.5)], plane_px=int(stats[i, 4]), deepest=round(float(Ms[lab == i].min()), 3)) for i in range(1, n) if stats[i, 4] >= 60], key=lambda d: -d['plane_px'])
print('shadows deeper than 1.4%% outside the core mask: %d patches, %.2f%% of the sensor; largest:' % (len(blobs), 100 * sum(b['plane_px'] for b in blobs) / new.size)); [print('   ', b) for b in blobs[:15]]
x0, y0, x1, y1 = [v // 2 for v in HAIR_BOX]
for nm, arr in (('core map', RATIO), ('this hour', Ms)):
    sub = arr[y0:y1, x0:x1]; yy, xx = np.unravel_index(np.argmin(cv2.GaussianBlur(sub, (0, 0), 4)), sub.shape)
    ys, xs = np.nonzero(sub < 0.95)
    print('hair box, %s: deepest %.3f at sensor (%d, %d); area below 0.95: %d plane px, bbox sensor x %s y %s' % (nm, sub.min(), 2 * (xx + x0), 2 * (yy + y0), len(xs), (2 * (xs.min() + x0), 2 * (xs.max() + x0)) if len(xs) else None, (2 * (ys.min() + y0), 2 * (ys.max() + y0)) if len(ys) else None))
v = np.clip((np.hstack([RATIO[0:400, 1600:2300], Ms[0:400, 1600:2300]]) - 0.80) / 0.25, 0, 1)
cv2.imwrite(W('v_hair_core_vs_now.png'), (v * 255).astype(np.uint8))
v = np.clip((np.vstack([cv2.resize(RATIO, None, fx=0.33, fy=0.33, interpolation=cv2.INTER_AREA), cv2.resize(Ms, None, fx=0.33, fy=0.33, interpolation=cv2.INTER_AREA)]) - 0.90) / 0.13, 0, 1)
cv2.imwrite(W('v_dust_core_vs_now.png'), (v * 255).astype(np.uint8))
# the small-scale flat for step 6
s1c = {f['stamp']: f for f in json.load(open(CW('step1.json')))['frames']}; vigc = json.load(open(CW('vignette.json')))
yy, xx = np.mgrid[0:H2, 0:W2]; blind = np.zeros((H2, W2), bool)
for fr in vigc['frames']:
    nuc = s1c[fr['clear']]['nucleus_sensor_xy']; blind |= np.hypot(2 * xx + 0.5 - nuc[0], 2 * yy + 0.5 - nuc[1]) < 480
quiet = ~union & ~hair & ~blind; quiet[:60] = False; quiet[-60:] = False; quiet[:, :60] = False; quiet[:, -60:] = False
sc_ = float(1.4826 * np.median(np.abs(RATIO[quiet][::5] - np.median(RATIO[quiet][::5])))); sn_ = float(1.4826 * np.median(np.abs(Ms[quiet][::5] - np.median(Ms[quiet][::5]))))
corr_px = float(np.corrcoef(RATIO[quiet][::5], Ms[quiet][::5])[0, 1]); corr_12 = float(np.corrcoef(cv2.GaussianBlur(RATIO, (0, 0), 12)[quiet][::5], cv2.GaussianBlur(Ms, (0, 0), 12)[quiet][::5])[0, 1])
wc, wn = 1 / sc_ ** 2, 1 / sn_ ** 2
comb = np.where(blind, Ms, (wc * RATIO + wn * Ms) / (wc + wn)).astype(np.float32)
small = np.clip(np.where(union, comb, cv2.GaussianBlur(comb, (0, 0), 3.0)), 0.5, 1.05).astype(np.float32)
small[hair] = 1.0                           # the hair moves: nothing is divided where either map shows it; each frame's own hair is cut out in step 6
np.save(W('smallflat_mosaic.npy'), small)
print('small-scale flat: scatter outside the masks core map %.4f, this hour %.4f; correlation %.2f per pixel, %.2f after a 12 px blur; weights core %.2f, this hour %.2f; result outside the masks: scatter %.4f, min %.3f max %.3f' % (
    sc_, sn_, corr_px, corr_12, wc / (wc + wn), wn / (wc + wn), float(1.4826 * np.median(np.abs(small[quiet][::5] - 1))), float(small[quiet].min()), float(small[quiet].max())))
json.dump(dict(frames=[c[0] for c in cl], ratio_noise=noise, small_scale_flat=dict(scatter_core_map=sc_, scatter_this_hour=sn_, correlation_per_pixel=corr_px, correlation_after_12px_blur=corr_12, weight_core=wc / (wc + wn), weight_this_hour=wn / (wc + wn)), correlation_inside_core_mask=float(np.corrcoef(1 - a, 1 - b)[0, 1]), new_patches=blobs[:40]), open(W('m5b_dustcheck.json'), 'w'), indent=1)
