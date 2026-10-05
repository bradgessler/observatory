"""Rerun step f3: which sensor pixels the twilight-based flat must NOT be trusted for during the core hour.
The flat was taken at dawn (1348..1407 UTC); the core run was 0736..0846 UTC. The run's own cloud-glow flat
(cloudflat.npy, step 6: clouded frame minus transparency x clear frame, median of 36) is the sensor's response
DURING the run. Green, core-hour flat / twilight-based flat, over its own wide smooth part (8x shrink, 5x5 median
twice, 31-block box blur): 1 where the two agree. Marked: Gaussian sigma 2.5 copy more than 2% from 1, or sigma 4
copy more than 1.4% from 1 (the core run's dust thresholds, both signs), in blobs of 60 plane px or more, grown by
6 px. Not judged: within 480 px of the nucleus (the cloud flat is blind there) and the zone the hair moved in
(the hair is cut out frame by frame, step f2). Added by hand: the place of the hair AT DAWN, at the top edge
(plane x 1830..1950, y 0..60): the flat was patched there with its own smooth part, which still dips by 5 to 9%.
Marked pixels are LEFT OUT of the average (as the core run left its dust out); nothing is divided by this map."""
import json, os
import numpy as np, cv2
from common import *
HY = np.load(os.environ['M31_MASTER_FLAT']); CF = np.load(W('cloudflat.npy'))
h, w = H // 2, Wd // 2
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}; vig = json.load(open(W('vignette.json')))
yy, xx = np.mgrid[0:h, 0:w]; blind = np.zeros((h, w), bool)
for fr in vig['frames']:
    nuc = s1[fr['clear']]['nucleus_sensor_xy']; blind |= np.hypot(2 * xx + 0.5 - nuc[0], 2 * yy + 0.5 - nuc[1]) < 480
HAIR_BOX = (3200, 0, 4400, 700); hb = np.zeros((h, w), bool); hb[HAIR_BOX[1] // 2:HAIR_BOX[3] // 2, HAIR_BOX[0] // 2:HAIR_BOX[2] // 2] = True
def wide(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
q = ((CF[1] + CF[2]) / (HY[1] + HY[2])).astype(np.float32); q = q / wide(q)
r25 = cv2.GaussianBlur(q, (0, 0), 2.5); r4 = cv2.GaussianBlur(q, (0, 0), 4.0)
quiet = ~blind & ~hb; quiet[:60] = False; quiet[-60:] = False; quiet[:, :60] = False; quiet[:, -60:] = False
n25 = float(1.4826 * np.median(np.abs(r25[quiet][::5] - 1))); n4 = float(1.4826 * np.median(np.abs(r4[quiet][::5] - 1)))
m = ((np.abs(r25 - 1) > 0.02) | (np.abs(r4 - 1) > 0.014)) & ~blind & ~hb
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
ids = np.array([i for i in range(1, n) if stats[i, 4] >= 60]); mask = np.isin(lab, ids)
blobs = sorted([dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5), round(2 * float(cent[i][1]) + 0.5)], plane_px=int(stats[i, 4]), extreme=round(float(r25[lab == i][np.argmax(np.abs(r25[lab == i] - 1))]), 3)) for i in ids], key=lambda b: -b['plane_px'])
dawn = np.zeros((h, w), bool); dawn[0:60, 1830:1950] = True
grown = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool) | dawn
dev = np.where(grown, r25, 1.0).astype(np.float32)          # the measured mismatch (core-hour response / flat), for the diagnostic map only
np.save(W('f3_leaveout.npy'), grown); np.save(W('f3_mismatch.npy'), dev)
edge = np.zeros((h, w), bool); edge[:40] = True; edge[-40:] = True; edge[:, :40] = True; edge[:, -40:] = True
print('ratio noise: sigma 2.5 copy %.4f, sigma 4 copy %.4f; %d patches, %.3f%% of the sensor marked (%.3f%% within 40 plane px of the frame edge); darker than the flat says: %d patches, brighter: %d' % (n25, n4, len(blobs), 100 * grown.mean(), 100 * (grown & edge).mean(), sum(b['extreme'] < 1 for b in blobs), sum(b['extreme'] > 1 for b in blobs)))
for b in blobs[:25]: print('  ', b)
json.dump(dict(ratio_noise_sigma_2_5=n25, ratio_noise_sigma_4=n4, thresholds=dict(sigma_2_5=0.02, sigma_4=0.014, min_blob_plane_px=60, grow_plane_px=6), patches=len(blobs), marked_fraction_of_sensor=float(grown.mean()),
               dawn_hair_zone_plane_px=[1830, 0, 1950, 60], not_judged='within 480 sensor px of the nucleus; the hair zone, sensor px %s' % (HAIR_BOX,), all_patches=blobs), open(W('f3_leaveout.json'), 'w'), indent=1)
v = np.clip((cv2.resize(r25, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA) - 0.94) / 0.12, 0, 1); v8 = (v * 255).astype(np.uint8); ov = cv2.cvtColor(v8, cv2.COLOR_GRAY2BGR)
mk = cv2.resize(grown.astype(np.uint8), (v8.shape[1], v8.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool); e = mk & ~cv2.erode(mk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool); ov[e] = (0, 200, 255)
cv2.imwrite(W('v_f3_leaveout.png'), ov)
