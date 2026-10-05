"""Rerun step f2: the hair on the sensor, frame by frame (it creeps; no fixed map is ever divided out).
Every 20 s frame of the run is looked at (the clouded ones too: their bright, even glow shows the hair best).
Per frame, as in the M42 run's hair.py: the green planes over the smooth part of the flat, blurred (sigma 3 plane
px), over their own grey closing (ellipse 61 px, the local upper envelope); the hair is the largest connected patch
below 0.86 of that envelope inside the search zone, 300 to 8000 plane px; its soft edge is taken out to 0.93 (where that contour runs off into the noise, more than twice the core's area, the core grown by 6 px instead).
Kept per frame: the centre, the patch, and the ratio map (the hair's transmission as that frame shows it).
For a USED frame the mask is the union of the patches found in the frames taken within 100 s of it (itself
included), grown by 12 plane px (24 sensor px): a single clear frame is noisy (sky 100 DN, 3% after the blur), its
clouded neighbours are not. Why 12 px and not the M42 run's 30: measured in seven clouded frames (level 400 to 650 DN), the
shadow beyond the 0.93 contour is 0.951 in the first 4 plane px, 0.984 in the next 4, 0.995 in the next, and 0.998 to 1.000
from 12 px outward. The field moves only +-110 px in x and +-45 in y during the run, so every px of margin costs picture: with
30 px the black smudge the hair leaves came out twice as large as in the core run's picture (21000 against 10400 sensor px
more than 10 DN low). The transmission kept for the diagnostic map is the median of the ratio maps of the 5 nearest BRIGHT (clouded) frames."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
FLATF = os.environ['M31_MASTER_FLAT']
HAIR_BOX = (3200, 0, 4400, 700)
X0, Y0, X1, Y1 = [v // 2 for v in HAIR_BOX]
K61 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)); GROW = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))
h2, w2 = H // 2, Wd // 2
def smooth_part(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (0, 0), 2, borderType=cv2.BORDER_REPLICATE)
    return cv2.resize(small, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
FL = np.load(FLATF); FS = [smooth_part(FL[1]), smooth_part(FL[2])]
hot = np.load(os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-from-core-run', 'hotmap.npy'))

def one(fr):
    planes, ceil, meta = load_planes(fr['path'])
    for p in (1, 2):
        med3 = cv2.medianBlur(planes[p], 3); planes[p][hot[p]] = med3[hot[p]]
    G = ((planes[1] / FS[0] + planes[2] / FS[1]) / 2)[Y0:Y1 + 80, X0 - 80:X1 + 80]
    G = cv2.medianBlur(G, 3)                               # single-frame spikes
    sm = cv2.GaussianBlur(G, (0, 0), 3)
    env = cv2.morphologyEx(sm, cv2.MORPH_CLOSE, K61, borderType=cv2.BORDER_REPLICATE)
    r = (sm / np.maximum(env, 1e-3))[:Y1 - Y0, 80:80 + X1 - X0]
    n, lab, stats, cent = cv2.connectedComponentsWithStats((r < 0.86).astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        if 300 <= stats[i, 4] <= 8000 and (best is None or stats[i, 4] > stats[best, 4]): best = i
    if best is None: return fr['stamp'], None, None, r.astype(np.float32), float(np.median(sm))
    core = lab == best
    n2, lab2 = cv2.connectedComponents((r < 0.93).astype(np.uint8), connectivity=8)
    ids = np.unique(lab2[core]); soft = np.isin(lab2, ids[ids > 0])
    if soft.sum() > 2 * core.sum(): soft = cv2.dilate(core.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool)   # in a clear frame (sky 100 DN) the 0.93 contour runs off into the noise: the core grown by 6 px instead (in the clouded frames the soft edge is the core plus about that)
    ys, xs = np.nonzero(core)
    info = dict(centre_sensor_xy=[round(2 * float(cent[best][0] + X0) + 0.5), round(2 * float(cent[best][1] + Y0) + 0.5)], area_plane_px=int(stats[best, 4]), soft_area_plane_px=int(soft.sum()), deepest=float(r[core].min()),
                bbox_sensor=[int(2 * (xs.min() + X0)), int(2 * (ys.min() + Y0)), int(2 * (xs.max() + X0)), int(2 * (ys.max() + Y0))], level_dn=float(np.median(sm)))
    return fr['stamp'], info, soft, r.astype(np.float32), float(np.median(sm))

if __name__ == '__main__':
    F = json.load(open(W('step1.json')))['frames']; USED = [u['stamp'] for u in json.load(open(W('step7_select.json')))['used']]
    def tsec(s): return int(s[9:11]) * 3600 + int(s[11:13]) * 60 + int(s[13:15])
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(one, F))
    by = {r[0]: r for r in res}
    for s, info, soft, r, lv in res:
        print(s, 'used' if s in USED else '    ', 'level %6.0f' % lv, 'no hair found' if info is None else 'centre %s area %d soft %d deepest %.3f bbox %s' % (info['centre_sensor_xy'], info['area_plane_px'], info['soft_area_plane_px'], info['deepest'], info['bbox_sensor']), flush=True)
    masks = {}; trans = {}; out = {}
    for s in USED:
        near = [r for r in res if abs(tsec(r[0]) - tsec(s)) <= 100 and r[1] is not None]
        if not near: near = sorted([r for r in res if r[1] is not None], key=lambda r: abs(tsec(r[0]) - tsec(s)))[:3]
        u = np.zeros((Y1 - Y0, X1 - X0), bool)
        for r in near: u |= r[2]
        m = np.zeros((h2, w2), np.uint8); m[Y0:Y1, X0:X1] = u; m = cv2.dilate(m, GROW).astype(bool)
        # the transmission, for the diagnostic map only: from the BRIGHT (clouded) frames nearest in time (level 200 DN or more, the 5 nearest
        # within 10 minutes; in a clear frame the envelope of a noisy picture sits above its mean and the ratio reads 3 to 6% low everywhere),
        # and set to 1 in a ring 20 to 40 plane px outside the patch by dividing by its median there
        bright = sorted([r for r in res if r[1] is not None and r[4] >= 200 and abs(tsec(r[0]) - tsec(s)) <= 600], key=lambda r: abs(tsec(r[0]) - tsec(s)))[:5] or near
        rm = np.median(np.stack([r[3] for r in bright]), axis=0)
        m_wide = cv2.dilate(u.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81))).astype(bool); inner = cv2.dilate(u.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))).astype(bool); margin = m_wide & ~inner     # the ring 20 to 40 plane px outside the patch
        bias = float(np.median(rm[margin])) if margin.sum() > 200 else 1.0
        T = np.ones((h2, w2), np.float32); T[Y0:Y1, X0:X1] = np.minimum(rm / bias, 1.0); T[~m] = 1.0
        masks[s] = np.packbits(m); trans[s] = T[Y0:Y1 + 60, X0 - 60:X1 + 60].astype(np.float16)
        ys, xs = np.nonzero(m)
        out[s] = dict(own=by[s][1], frames_in_the_union=[r[0] for r in near], transmission_from=[r[0] for r in bright], envelope_bias_divided_out=bias, masked_plane_px=int(m.sum()), mask_bbox_sensor=[int(2 * xs.min()), int(2 * ys.min()), int(2 * xs.max()), int(2 * ys.max())], deepest_transmission=float(T.min()))
        print('used', s, 'union of', len(near), 'frames; mask', out[s]['masked_plane_px'], 'plane px, bbox', out[s]['mask_bbox_sensor'], 'deepest %.3f' % T.min())
    np.savez(W('f2_hair.npz'), **{'m_' + s: masks[s] for s in USED}, **{'t_' + s: trans[s] for s in USED})
    json.dump(dict(search_zone_sensor=HAIR_BOX, every_frame={r[0]: r[1] for r in res}, used=out, trans_window_plane=[X0 - 60, Y0, X1 + 60, Y1 + 60]), open(W('f2_hair.json'), 'w'), indent=1)
    # a look: the ratio map of a few frames through the hour
    pick = [res[i] for i in np.linspace(0, len(res) - 1, 12).astype(int)]
    cv2.imwrite(W('v_hair_through_the_hour.png'), (np.clip((np.vstack([np.hstack([p[3][:300, 150:550] for p in pick[0:6]]), np.hstack([p[3][:300, 150:550] for p in pick[6:12]])]) - 0.6) / 0.5, 0, 1) * 255).astype(np.uint8))
