"""Mosaic step 5c (only with M31M_MASTER_FLAT): is the master flat's dust the dust of THIS hour, and which sensor
pixels must be treated apart because it is not?
The master flat was taken at dawn (1348..1407 UTC), these frames at 0915..1023 UTC. Under the Moon and the cloud
every frame of this run is a sky flat of a sort (250 to 1100 DN of sky). Per panel: the sum of ALL its 30 s frames
(used or not; green, each plane over the master flat) over the sum's own wide smooth part (8x shrink, 5x5 median
twice, 31-block box blur), blurred (Gaussian sigma 2.5 and 4 plane px). Then, per sensor pixel, the MEDIAN OVER THE
SIX PANELS: what all panels show at the same place on the sensor is the sensor (this hour's response over the
master flat, 1 where the flat is right); what one panel shows is the sky (a star, M32, the bulge) and drops out.
(A first version took the median over the 19 heavily clouded frames, as step 5b does. It marked 20 'bright'
patches of 2 to 4%, and every one was a galaxy or bright star in ONE panel: with 4 of 19 frames far too bright and
8% of noise per pixel a median still rises by 3%. Step 5b's own map of the first run has those patches too.)

Marked: the sigma 2.5 map more than 2% from 1, or the sigma 4 map more than 1.4% from 1 (the core run's dust
thresholds, both signs), blobs of 60 plane px or more, grown by 6 px. Not judged: the box the hair moves in (each
frame's own hair circle is cut out in step 6).

Written:
  leaveout_master.npy    boolean (2012, 3012): the marked patches. Step 6 (M31M_DUST_MASK) LEAVES those sensor pixels
                         OUT of the average wherever a panel has enough clean frames, and flags the rest (2).
  flat_master_hour.npy   the master flat, and inside the marked patches the master flat x this hour's measured
                         response over it (the sigma 2.5 map, faded in over 4 px from the patch edge): there the
                         flat is this hour's, as measured in this hour, which is what step 6 did before with the
                         whole dust map. Everywhere else it is the master flat untouched. Step 6: M31M_MASTER_FLAT.
  nodata_master.npy      boolean: the hair's place AT DAWN, at the top edge (plane x 1830..1950, y 0..60), where the
                         master flat was patched with its own smooth part and still dips by 5 to 9%. Step 6
                         (M31M_NODATA_MASK) takes NO data from those sensor pixels, as from the hair's own circle."""
import json, os, sys
import numpy as np, cv2
from mcommon import *
MF = np.load(os.environ['M31M_MASTER_FLAT']).astype(np.float32); assert MF.shape == (4, H2, W2)
F = json.load(open(W('m1.json')))['frames']
def wide(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
names = [p[0] for p in PANELS if p[0] != 'centre']; maps25 = []; maps4 = []; info = {}
for k in names:
    fr = [f for f in F if f['panel'] == k]; S_ = np.zeros((H2, W2), np.float64)
    for f in fr:
        P = np.load(W('planes/' + f['stamp'] + '.npy'), mmap_mode='r'); S_ += (P[1] / MF[1] + P[2] / MF[2]) / 2
    S_ = S_.astype(np.float32); q = S_ / wide(S_)
    maps25.append(cv2.GaussianBlur(q, (0, 0), 2.5)); maps4.append(cv2.GaussianBlur(q, (0, 0), 4.0))
    info[k] = dict(frames=len(fr), summed_level_green_dn=float(np.median(S_[::8, ::8])))
    print('%-4s %2d frames, summed sky %.0f DN' % (k, len(fr), info[k]['summed_level_green_dn']), flush=True)
r25 = np.median(np.stack(maps25), axis=0); r4 = np.median(np.stack(maps4), axis=0)
spread = np.stack(maps25).std(0)
hx0, hy0, hx1, hy1 = [v // 2 for v in HAIR_BOX]; hb = np.zeros((H2, W2), bool); hb[hy0:hy1, hx0:hx1] = True
quiet = ~hb; quiet[:60] = False; quiet[-60:] = False; quiet[:, :60] = False; quiet[:, -60:] = False
n25 = float(1.4826 * np.median(np.abs(r25[quiet][::5] - 1))); n4 = float(1.4826 * np.median(np.abs(r4[quiet][::5] - 1)))
m = ((np.abs(r25 - 1) > 0.02) | (np.abs(r4 - 1) > 0.014)) & ~hb
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
ids = np.array([i for i in range(1, n) if stats[i, 4] >= 60]); mask = np.isin(lab, ids) if len(ids) else np.zeros((H2, W2), bool)
blobs = []
for i in ids:
    b = lab == i; j = np.argmax(np.abs(r25[b] - 1)); per = [float(np.median(mp[b])) for mp in maps25]
    blobs.append(dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5), round(2 * float(cent[i][1]) + 0.5)], plane_px=int(stats[i, 4]), extreme=round(float(r25[b][j]), 3), median_in_each_panel=dict(zip(names, [round(v, 3) for v in per]))))
blobs.sort(key=lambda b: -b['plane_px'])
dawn = np.zeros((H2, W2), bool); dawn[0:60, 1830:1950] = True
grown = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool) & ~hb
np.save(W('leaveout_master.npy'), grown); np.save(W('mismatch_master.npy'), r25.astype(np.float32)); np.save(W('nodata_master.npy'), dawn)
t = np.clip(cv2.distanceTransform(grown.astype(np.uint8), cv2.DIST_L2, 5) / 4.0, 0, 1).astype(np.float32)
adj = (1.0 + (r25 - 1.0) * t).astype(np.float32)
np.save(W('flat_master_hour.npy'), (MF * adj[None]).astype(np.float32))
# the dust itself: depth in this hour against depth in the master flat
g = (MF[1] + MF[2]) / 2; tw = cv2.GaussianBlur(g / wide(g), (0, 0), 2.5); now = r25 * tw          # this hour's own small-scale response
out = dict(master_flat=os.environ['M31M_MASTER_FLAT'], panels=info, ratio_noise_sigma_2_5=n25, ratio_noise_sigma_4=n4, thresholds=dict(sigma_2_5=0.02, sigma_4=0.014, min_blob_plane_px=60, grow_plane_px=6),
           patches=len(blobs), marked_fraction_of_sensor=float(grown.mean()), before_marked_fraction_of_sensor_dust_masks=float(np.load(W('dustmask_mosaic.npy')).mean()),
           darker_than_the_flat_says=int(sum(b['extreme'] < 1 for b in blobs)), brighter=int(sum(b['extreme'] > 1 for b in blobs)), all_patches=blobs,
           adjustment_inside_the_marks=dict(min=float(adj.min()), max=float(adj.max()), pixels=int((adj != 1).sum())), no_data_zone_plane_px=[1830, 0, 1950, 60], dust_depth_agreement={})
for nm, thr in (('2pct', 0.98), ('3pct', 0.97), ('5pct', 0.95)):
    mm = quiet & (tw < thr); x = 1 - tw[mm]; y = 1 - now[mm]
    out['dust_depth_agreement']['master_flat_shadow_deeper_than_' + nm] = dict(plane_px=int(mm.sum()), master_depth_mean=float(x.mean()), this_hour_depth_mean=float(y.mean()), slope_this_hour_over_master=float((x * y).sum() / (x * x).sum()), correlation=float(np.corrcoef(x, y)[0, 1]),
                                                                              left_after_dividing_by_the_master_mean=float((r25[mm] - 1).mean()), left_rms=float((r25[mm] - 1).std()))
    print('master flat shadow deeper than %s: %d px; depth master %.4f, this hour %.4f; slope %.3f, correlation %.3f; left after the master flat: mean %+.4f rms %.4f' % (nm, mm.sum(), x.mean(), y.mean(), out['dust_depth_agreement']['master_flat_shadow_deeper_than_' + nm]['slope_this_hour_over_master'], np.corrcoef(x, y)[0, 1], (r25[mm] - 1).mean(), (r25[mm] - 1).std()))
print('ratio noise %.4f (sigma 2.5), %.4f (sigma 4); %d patches, %.3f%% of the sensor marked (the dust masks of the first run: %.2f%%); darker %d, brighter %d' % (n25, n4, len(blobs), 100 * grown.mean(), 100 * out['before_marked_fraction_of_sensor_dust_masks'], out['darker_than_the_flat_says'], out['brighter']))
for b in blobs[:20]: print('  ', b)
json.dump(out, open(W('m5c_masterflat_check.json'), 'w'), indent=1)
v = np.clip((cv2.resize(r25, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA) - 0.94) / 0.12, 0, 1); v8 = (v * 255).astype(np.uint8); ov = cv2.cvtColor(v8, cv2.COLOR_GRAY2BGR)
mk = cv2.resize(grown.astype(np.uint8), (v8.shape[1], v8.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool); e = mk & ~cv2.erode(mk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool); ov[e] = (0, 200, 255)
cv2.imwrite(W('v_m5c_leaveout.png'), ov)
