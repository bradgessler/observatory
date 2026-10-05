"""Step 4b: shadows on the sensor. No flat field was taken, so they are measured in the run's own sky and
divided out (the frame's pixels, sky included, divided by the shadow's measured transmission).

Fixed dust: the median of all frames WITHOUT registration of the green planes (stars drift, the sky and the
dust stay; sky level put back), 5x5 median, Gaussian blur, divided by its own large-scale version (1/8
size, two 5x5 medians, 41x41 box). Where that ratio (blur sigma 4) is below DUST_RATIO in blobs of at least
MIN_BLOB plane px, outside the cluster zone (there the unregistered median is cluster light, not sky), grown
by DUST_GROW plane px, the ratio (blur sigma 3, never above 1) is the divisor. Everywhere else the divisor is
exactly 1. A first pass with a 0.95 threshold left the many small ring-shaped dust shadows (3 to 6% deep,
about 90 sensor px across) as faint streaks about 1 DN deep along the drift; 0.97 takes them too.

The moving shadow: one hair-like shadow (about 220 x 80 sensor px, up to 31% deep) crept across the sensor
during the run, so it is not in a fixed place. Its place in every frame is measured (centroid of the sky
deficit, then a least-squares match to the template), the frames are lined up on it and their median, each
divided by a plane fitted to the sky around it, is its transmission (stars move through it and drop out of
the median). Each frame is divided by that template placed where the shadow was in that frame.

First tried: leaving shadowed sensor pixels out of the average instead. The shadows are wider than the drift
of the sky across them, so 6209 sky pixels were never seen clean and 59542 had fewer than 8 clean frames;
dividing keeps every frame everywhere. The same divisor is used for all four colour planes."""
import json, numpy as np, cv2
from common import *
DUST_RATIO, DUST_GROW, MIN_BLOB, CLUSTER_ZONE = 0.97, 6, 100, 800     # ratio, plane px, plane px, sensor px
BAR = RUNS[RUN].get('bar_window')                                      # plane px: x0, y0, x1, y1 of the window the moving shadow stays in
s1 = json.load(open(W('step1.json'))); frames = s1['frames']
skyg = {f['stamp']: (f['bg'][1]['clipped_mean'] + f['bg'][2]['clipped_mean']) / 2 for f in frames}

# ---- fixed dust ----
G = np.stack([np.load(W('planes/' + f['stamp'] + '.npy'), mmap_mode='r')[1:3].mean(0) for f in frames])
Mg = np.median(G, axis=0)
sky = float(np.median(list(skyg.values())))
base = cv2.medianBlur(Mg.astype(np.float32), 5) + sky
def ratio_of(sig):
    Fs = cv2.GaussianBlur(base, (0, 0), sig)
    small = cv2.resize(Fs, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small.astype(np.float32), 5), 5), (41, 41))
    return Fs / cv2.resize(low, (Fs.shape[1], Fs.shape[0]), interpolation=cv2.INTER_CUBIC)
ratio, ratio_div = ratio_of(4), ratio_of(3)
cls = np.array([f['cluster_sensor_xy'] for f in frames])
h, w = ratio.shape; yy, xx = np.mgrid[0:h, 0:w]
zone = np.zeros((h, w), bool)
for c in cls: zone |= np.hypot(2 * xx + 0.5 - c[0], 2 * yy + 0.5 - c[1]) < CLUSTER_ZONE
m = (ratio < DUST_RATIO) & ~zone
if BAR: m[BAR[1]:BAR[3], BAR[0]:BAR[2]] = False
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
mask = np.zeros((h, w), bool); blobs = []
for i in range(1, n):
    if stats[i, 4] < MIN_BLOB: continue
    mask |= lab == i
    blobs.append(dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5, 1), round(2 * float(cent[i][1]) + 0.5, 1)], plane_px=int(stats[i, 4]), deepest_ratio=round(float(ratio[lab == i].min()), 3)))
mask = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DUST_GROW + 1, 2 * DUST_GROW + 1))).astype(bool)
if BAR: mask[BAR[1]:BAR[3], BAR[0]:BAR[2]] = False
div = np.where(mask, np.minimum(ratio_div, 1.0), 1.0).astype(np.float32)
np.save(W('dustdiv.npy'), div)
blobs.sort(key=lambda b: -b['plane_px'])
print('fixed dust: %d patches, %d plane px (%.3f%% of the plane), divisor min %.3f' % (len(blobs), mask.sum(), 100 * mask.mean(), div.min()))
rec = dict(fixed=dict(ratio_threshold=DUST_RATIO, grow_plane_px=DUST_GROW, min_blob_plane_px=MIN_BLOB, cluster_zone_sensor_px=CLUSTER_ZONE, sky_dn=sky, corrected_plane_px=int(mask.sum()), corrected_fraction=float(mask.mean()),
                      smallest_divisor=float(div.min()), frames_in_median=len(frames), patches=blobs), moving=None)

# ---- the moving shadow ----
if BAR:
    bx0, by0, bx1, by1 = BAR; wh, ww_ = by1 - by0, bx1 - bx0
    wy, wx = np.mgrid[0:wh, 0:ww_].astype(np.float64)
    win = G[:, by0:by1, bx0:bx1].astype(np.float64)
    def normalise(g, sk, centre):
        """Window divided by a plane fitted (clipped) to the sky more than 75 plane px from the shadow's centre."""
        v = g + sk
        far = np.hypot((wx - centre[0]) * 0.55, wy - centre[1]) > 75          # an ellipse 136 x 75 around the shadow
        A = np.stack([np.ones(far.sum()), wx[far], wy[far]], 1); b = v[far]; keep = np.ones(len(b), bool)
        for _ in range(4):
            co, *_ = np.linalg.lstsq(A[keep], b[keep], rcond=None); r = b - A @ co; s = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 2.5 * s
        return v / (co[0] + co[1] * wx + co[2] * wy)
    # 1. first place: centroid of the deficit deeper than 6% in a sigma-4 blur
    cen = []
    for i, f in enumerate(frames):
        g = cv2.GaussianBlur(win[i], (0, 0), 4) / skyg[f['stamp']]
        d = np.clip(-g - 0.06, 0, None); cen.append([(d * wx).sum() / d.sum(), (d * wy).sum() / d.sum()])
    cen = np.array(cen); c0 = np.median(cen, axis=0)
    def template(cen):
        al = []
        for i, f in enumerate(frames):
            nrm = normalise(win[i], skyg[f['stamp']], cen[i])
            Mx = np.float32([[1, 0, c0[0] - cen[i][0]], [0, 1, c0[1] - cen[i][1]]])
            al.append(cv2.warpAffine(nrm.astype(np.float32), Mx, (ww_, wh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan')))
        return np.nanmedian(np.stack(al), axis=0)
    T = template(cen)
    # 2. refine each frame's place against the template (sum of squared differences of sigma-3 blurs, 0.5 px steps, +-6 px)
    Ts = cv2.GaussianBlur(np.nan_to_num(T, nan=1.0).astype(np.float32), (0, 0), 3)
    zone_b = cv2.dilate((Ts < 0.97).astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)
    ref2 = []
    for i, f in enumerate(frames):
        nrm = cv2.GaussianBlur(normalise(win[i], skyg[f['stamp']], cen[i]).astype(np.float32), (0, 0), 3)
        best = (1e18, 0.0, 0.0)
        for dy in np.arange(-6, 6.01, 0.5):
            for dx in np.arange(-6, 6.01, 0.5):
                Mx = np.float32([[1, 0, c0[0] - cen[i][0] - dx], [0, 1, c0[1] - cen[i][1] - dy]])
                a = cv2.warpAffine(nrm, Mx, (ww_, wh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                e = float(((a - Ts)[zone_b] ** 2).sum())
                if e < best[0]: best = (e, dx, dy)
        ref2.append([cen[i][0] + best[1], cen[i][1] + best[2]])
    cen2 = np.array(ref2)
    T = template(cen2)
    T = cv2.GaussianBlur(cv2.medianBlur(np.nan_to_num(T, nan=1.0).astype(np.float32), 3), (0, 0), 1.5)
    depth = np.clip(1 - T, 0, None)
    wgt = np.clip((cv2.GaussianBlur(depth, (0, 0), 3) - 0.01) / 0.02, 0, 1)     # nothing where the shadow is under 1%, all of it above 3%
    # keep only the one connected shadow that contains the deepest point
    nn, lab2, st2, _ = cv2.connectedComponentsWithStats((wgt > 0).astype(np.uint8), connectivity=8)
    yy_, xx_ = np.unravel_index(np.argmax(depth), depth.shape); wgt *= (lab2 == lab2[yy_, xx_])
    Tf = (1 - wgt * depth).astype(np.float32)
    np.save(W('bar_template.npy'), Tf)
    places = {}
    for i, f in enumerate(frames):
        places[f['stamp']] = dict(dx=float(cen2[i][0] - c0[0]), dy=float(cen2[i][1] - c0[1]), sensor_xy=[round(2 * (bx0 + cen2[i][0]) + 0.5, 1), round(2 * (by0 + cen2[i][1]) + 0.5, 1)])
    json.dump(dict(window=BAR, c0=c0.tolist(), places=places), open(W('bar_places.json'), 'w'), indent=1)
    trk = np.array([p['sensor_xy'] for p in places.values()])
    print('moving shadow: deepest transmission %.3f, %d plane px below 0.97; moved from (%.0f, %.0f) to (%.0f, %.0f) sensor px = %.0f px' % (Tf.min(), int((Tf < 0.97).sum()), trk[0, 0], trk[0, 1], trk[-1, 0], trk[-1, 1], np.hypot(*(trk[-1] - trk[0]))))
    print('   refinement moved the places by (median, max) %.2f %.2f plane px' % (np.median(np.hypot(*(cen2 - cen).T)), np.max(np.hypot(*(cen2 - cen).T))))
    rec['moving'] = dict(window_plane_px=BAR, deepest_transmission=float(Tf.min()), plane_px_below_0_97=int((Tf < 0.97).sum()), size_sensor_px='about 220 x 80', place_per_frame_sensor_xy={k: v['sensor_xy'] for k, v in places.items()},
                         moved_sensor_px=float(np.hypot(*(trk[-1] - trk[0]))), frames_in_median=len(frames))
    cv2.imwrite(W('v_bar_template.png'), (np.clip((np.hstack([np.nan_to_num(template(cen2), nan=1.0), Tf]) - 0.6) / 0.5, 0, 1) * 255).astype(np.uint8))
json.dump(rec, open(W('step4b_dust.json'), 'w'), indent=1)
