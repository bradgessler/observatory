"""Step 9: where sensor dust still shows in the finished picture, and how deep. A diagnostic, not a correction.

For every used frame the measured dust transmission (the cloud-glow flat's small-scale ratio inside the marked
shadows, 1 elsewhere, never above 1) is carried onto the picture's grid with that frame's registration; the
weighted mean over the frames is what a stack with the dust left in sees. In the finished planes the dust is
left out wherever at least 12 clean frames exist, so the expected shadow there is none; below 12 clean frames
the dust-left-in combine is blended in (fully below 4) and the shadow comes back in proportion.
The prediction is checked against the stack itself: (dust left in - dust left out) / level, where both exist."""
import json, numpy as np, cv2
from concurrent.futures import ThreadPoolExecutor
from common import *
from final import *
sel = json.load(open(W('step7_select.json')))['used']; tr = {o['stamp']: o for o in json.load(open(W('step4_transforms.json')))['transforms']}
ratio = np.load(W('dustratio.npy')); mask = np.load(W('dustmask.npy'))
D = np.where(mask, np.minimum(ratio, 1.0), 1.0).astype(np.float32)
gy, gx = np.mgrid[0:H, 0:Wd].astype(np.float32)
def one(u):
    R = np.array(tr[u['stamp']]['R']); t = np.array(tr[u['stamp']]['t'])
    fx = (R[0, 0] * gx + R[0, 1] * gy + t[0]).astype(np.float32); fy = (R[1, 0] * gx + R[1, 1] * gy + t[1]).astype(np.float32)
    return cv2.remap(D, (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan')), u['weight']
num = np.zeros((H, Wd), np.float64); den = np.zeros((H, Wd), np.float64)
with ThreadPoolExecutor(6) as ex:
    for d, w in ex.map(one, sel):
        ok = np.isfinite(d); num += np.where(ok, d, 0) * w; den += ok * w
left_in = (num / np.maximum(den, 1e-9)).astype(np.float32)
used = np.load(W('B_used.npy'))[1].astype(np.float32)
wgt = np.clip((used - BLEND_LO) / float(BLEND_HI - BLEND_LO), 0, 1)
pred = (1 - (1 - left_in) * (1 - wgt)).astype(np.float32)
np.save(W('dust_pred_left_in.npy'), left_in); np.save(W('dust_pred_final.npy'), pred)
# check against the stack (green, version B)
m = np.load(W('B_mean.npy'))[1:3].mean(0); li = np.load(W('B_mean_dust_left_in.npy'))[1:3].mean(0)
ok = np.isfinite(m) & np.isfinite(li) & (used >= 12)
meas = cv2.GaussianBlur(np.where(ok, li - m, 0).astype(np.float32), (0, 0), 8) / np.maximum(cv2.GaussianBlur(np.where(ok, m, 1).astype(np.float32), (0, 0), 8), 1)
prd = cv2.GaussianBlur(left_in, (0, 0), 8) - 1
sel_ = ok & (prd < -0.01) & (cv2.GaussianBlur(ok.astype(np.float32), (0, 0), 8) > 0.95)
a = prd[sel_][::11]; b = meas[sel_][::11]
slope = float((a * b).sum() / (a * a).sum()); corr = float(np.corrcoef(a, b)[0, 1])
print('prediction against the stack where the predicted shadow is deeper than 1%%: measured = %.2f x predicted, correlation %.2f, %d px' % (slope, corr, int(sel_.sum())))
# what is left in the finished picture
rect = cover_rect('B', len(sel)); x0, y0, x1, y1 = rect
p = pred[y0:y1, x0:x1]
n, lab, stats, cent = cv2.connectedComponentsWithStats((cv2.GaussianBlur(p, (0, 0), 4) < 0.985).astype(np.uint8), connectivity=8)
left = []
for i in range(1, n):
    if stats[i, 4] < 400: continue
    left.append(dict(centre_sensor_xy=[round(float(cent[i][0]) + x0), round(float(cent[i][1]) + y0)], centre_in_whole_field_picture_px=[round(float(cent[i][0]) / 2), round(float(cent[i][1]) / 2)],
                     size_sensor_px=[int(stats[i, 2]), int(stats[i, 3])], area_sensor_px=int(stats[i, 4]), deepest_transmission=round(float(p[lab == i].min()), 3)))
left.sort(key=lambda d: d['deepest_transmission'])
for d in left: print(d)
json.dump(dict(check_against_stack=dict(measured_over_predicted=slope, correlation=corr, pixels=int(sel_.sum())),
               fraction_of_field_with_shadow_deeper_than=dict(p005=float((p < 0.995).mean()), p01=float((p < 0.99).mean()), p02=float((p < 0.98).mean()), p05=float((p < 0.95).mean())),
               if_dust_had_been_left_in=dict(p005=float((left_in[y0:y1, x0:x1] < 0.995).mean()), p01=float((left_in[y0:y1, x0:x1] < 0.99).mean()), p02=float((left_in[y0:y1, x0:x1] < 0.98).mean()), p05=float((left_in[y0:y1, x0:x1] < 0.95).mean()), deepest=float(left_in[y0:y1, x0:x1].min())),
               shadows_left=left), open(W('dustmap.json'), 'w'), indent=1)
