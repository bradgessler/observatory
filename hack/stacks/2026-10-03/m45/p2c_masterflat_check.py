"""Step 2c (only with M45_MASTER_FLAT): is the master flat's dust the dust of THIS hour (1025..1114 UTC; the flat is
from 1348..1407 UTC), and where must its pixels be treated apart?
Per stack (eleven pointings): the sum of ALL its 10 s frames (hot pixels and spikes repaired; green, each plane over
the master flat) over the sum's own wide smooth part (8x shrink, 5x5 median twice, 31-block box blur), blurred
(Gaussian sigma 2.5 and 4 plane px). Per sensor pixel the MEDIAN OVER THE ELEVEN STACKS: what every pointing shows at
one place on the sensor is the sensor (this hour's response over the master flat; 1 where the flat is right); the
stars, their glare and the nebulosity sit elsewhere in every stack and drop out.
These frames are faint (30 to 130 DN of sky under 25 DN of read noise), so this map is noisy: about 1% per pixel at
sigma 2.5. Two tests, therefore:
  known  the patches the M31 runs of this night found (where the dawn flat was not the response of 0736..0846 or of
         0915..1023 UTC; their lists are read from the kept files): the mean of this hour's map inside each. A patch is
         taken as wrong for this hour too if that mean is more than 1% and more than 4 sigma from 1.
  blind  anywhere else: the sigma 2.5 map more than max(2%, 4.5 sigma) from 1, or the sigma 4 map more than
         max(1.4%, 4.5 sigma), in blobs of 60 plane px or more, grown by 6 px.
Not judged: the box the hair moves in (each stack's own hair circle is cut out in step 6).

Written: leaveout_master.npy (the patches: step 6 flags them 2, a quarter of the weight, kept out of the background
fit), flat_master_hour.npy (the master flat, and inside the patches the master flat x this hour's measured response,
faded in over 4 px), nodata_master.npy (the hair's place AT DAWN, top edge, plane x 1830..1950, y 0..60, where the
master flat was patched with its own smooth part and still dips by 5 to 9%: no data from there, like the hair's
own circle)."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from c import *
MF = np.load(MASTER_FLAT).astype(np.float32); assert MF.shape == (4, H2, W2)
F = json.load(open(W('p1.json')))['frames']
M31R = os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-rerun'); M31C = os.path.join(NIGHT, 'm31', 'calibration-rerun')
def wide(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
def green(fr):
    P, ceil, meta, tr = repaired(fr['path'], [c_['clipped_std'] for c_ in fr['corner']])
    return ((P[1] / MF[1] + P[2] / MF[2]) / 2).astype(np.float32)
maps25 = []; maps4 = []; info = {}
for k in PANELS:
    fr = [f for f in F if f['panel'] == k]
    with ThreadPoolExecutor(7) as ex: S_ = np.sum(list(ex.map(green, fr)), axis=0).astype(np.float32)
    q = S_ / wide(S_)
    maps25.append(cv2.GaussianBlur(q, (0, 0), 2.5)); maps4.append(cv2.GaussianBlur(q, (0, 0), 4.0))
    info[k] = dict(frames=len(fr), summed_level_green_dn=float(np.median(S_[::8, ::8])))
    print('%-5s %2d frames, summed sky %.0f DN' % (k, len(fr), info[k]['summed_level_green_dn']), flush=True)
r25 = np.median(np.stack(maps25), axis=0); r4 = np.median(np.stack(maps4), axis=0)
hx0, hy0, hx1, hy1 = [v // 2 for v in HAIR_BOX]; hb = np.zeros((H2, W2), bool); hb[hy0:hy1, hx0:hx1] = True
quiet = ~hb; quiet[:60] = False; quiet[-60:] = False; quiet[:, :60] = False; quiet[:, -60:] = False
n25 = float(1.4826 * np.median(np.abs(r25[quiet][::5] - 1))); n4 = float(1.4826 * np.median(np.abs(r4[quiet][::5] - 1)))
# ---- known patches of the M31 hours ----
known = np.zeros((H2, W2), bool); cands = []
for src, f in (('M31 mosaic hour 0915-1023', os.path.join(M31R, 'leaveout_master.npy')), ('M31 core hour 0736-0846', os.path.join(M31C, 'f3_leaveout.npy'))):
    if not os.path.exists(f): continue
    m_ = np.load(f) & ~hb; n, lab, st, cen = cv2.connectedComponentsWithStats(m_.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        if st[i, 4] < 60: continue
        b = lab == i; mean = float(r25[b].mean()); sig = n25 * np.sqrt(39.3 / st[i, 4])          # a sigma 2.5 blur averages over about 39 px
        wrong = abs(mean - 1) > max(0.01, 4 * sig)
        cands.append(dict(found_in=src, centre_sensor_xy=[round(2 * float(cen[i][0]) + 0.5), round(2 * float(cen[i][1]) + 0.5)], plane_px=int(st[i, 4]), this_hour_over_master_mean=round(mean, 4), sigma=round(float(sig), 4), wrong_for_this_hour=bool(wrong)))
        if wrong: known |= b
# ---- blind ----
t25 = max(0.02, 4.5 * n25); t4 = max(0.014, 4.5 * n4)
m = ((np.abs(r25 - 1) > t25) | (np.abs(r4 - 1) > t4)) & ~hb
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
ids = np.array([i for i in range(1, n) if stats[i, 4] >= 60]); blind = np.isin(lab, ids) if len(ids) else np.zeros((H2, W2), bool)
blobs = sorted([dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5), round(2 * float(cent[i][1]) + 0.5)], plane_px=int(stats[i, 4]), extreme=round(float(r25[lab == i][np.argmax(np.abs(r25[lab == i] - 1))]), 3),
                     stacks_beyond_1pct_the_same_way=int(sum((np.median(mp[lab == i]) - 1) * (np.median(r25[lab == i]) - 1) > 0 and abs(np.median(mp[lab == i]) - 1) > 0.01 for mp in maps25))) for i in ids], key=lambda b: -b['plane_px'])
dawn = np.zeros((H2, W2), bool); dawn[0:60, 1830:1950] = True
grown = (cv2.dilate(blind.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool) | known) & ~hb
np.save(W('leaveout_master.npy'), grown); np.save(W('mismatch_master.npy'), r25.astype(np.float32)); np.save(W('nodata_master.npy'), dawn)
t = np.clip(cv2.distanceTransform(grown.astype(np.uint8), cv2.DIST_L2, 5) / 4.0, 0, 1).astype(np.float32)
r_adj = cv2.GaussianBlur(r25, (0, 0), 3.0)                    # this hour's map is noisy: a further blur before it is used inside the patches
adj = (1.0 + (r_adj - 1.0) * t).astype(np.float32)
np.save(W('flat_master_hour.npy'), (MF * adj[None]).astype(np.float32))
g = (MF[1] + MF[2]) / 2; tw = cv2.GaussianBlur(g / wide(g), (0, 0), 2.5); now = r25 * tw
out = dict(master_flat=MASTER_FLAT, stacks=info, ratio_noise_sigma_2_5=n25, ratio_noise_sigma_4=n4, thresholds=dict(sigma_2_5=t25, sigma_4=t4, min_blob_plane_px=60, grow_plane_px=6, known_patch='more than 1% and more than 4 sigma from 1'),
           known_patches_tested=cands, known_patches_wrong_for_this_hour=int(sum(c['wrong_for_this_hour'] for c in cands)), blind_patches=blobs, marked_fraction_of_sensor=float(grown.mean()), before_flagged_fraction_of_sensor_dust_mask=float(small_flat()[1].mean()),
           adjustment_inside_the_marks=dict(min=float(adj.min()), max=float(adj.max()), pixels=int((adj != 1).sum())), no_data_zone_plane_px=[1830, 0, 1950, 60], dust_depth_agreement={})
for nm, thr in (('2pct', 0.98), ('3pct', 0.97), ('5pct', 0.95)):
    mm = quiet & (tw < thr); x = 1 - tw[mm]; y = 1 - now[mm]
    out['dust_depth_agreement']['master_flat_shadow_deeper_than_' + nm] = dict(plane_px=int(mm.sum()), master_depth_mean=float(x.mean()), this_hour_depth_mean=float(y.mean()), slope_this_hour_over_master=float((x * y).sum() / (x * x).sum()), correlation=float(np.corrcoef(x, y)[0, 1]),
                                                                              left_after_dividing_by_the_master_mean=float((r25[mm] - 1).mean()), left_rms=float((r25[mm] - 1).std()))
    print('master flat shadow deeper than %s: %d px; depth master %.4f, this hour %.4f; slope %.3f, correlation %.3f; left after the master flat: mean %+.4f rms %.4f' % (nm, mm.sum(), x.mean(), y.mean(), out['dust_depth_agreement']['master_flat_shadow_deeper_than_' + nm]['slope_this_hour_over_master'], np.corrcoef(x, y)[0, 1], (r25[mm] - 1).mean(), (r25[mm] - 1).std()))
print('ratio noise %.4f (sigma 2.5), %.4f (sigma 4); thresholds %.3f, %.3f; blind: %d patches; known patches tested %d, wrong for this hour %d; %.3f%% of the sensor marked (the first run flagged %.2f%%)' % (n25, n4, t25, t4, len(blobs), len(cands), out['known_patches_wrong_for_this_hour'], 100 * grown.mean(), 100 * out['before_flagged_fraction_of_sensor_dust_mask']))
for c in sorted(cands, key=lambda c: -abs(c['this_hour_over_master_mean'] - 1))[:10]: print('   known', c)
for b in blobs[:10]: print('   blind', b)
json.dump(out, open(W('p2c_masterflat_check.json'), 'w'), indent=1)
v = np.clip((cv2.resize(r25, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA) - 0.94) / 0.12, 0, 1); v8 = (v * 255).astype(np.uint8); ov = cv2.cvtColor(v8, cv2.COLOR_GRAY2BGR)
mk = cv2.resize(grown.astype(np.uint8), (v8.shape[1], v8.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool); e = mk & ~cv2.erode(mk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool); ov[e] = (0, 200, 255)
cv2.imwrite(W('v_p2c_leaveout.png'), ov)
