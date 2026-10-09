"""Step 2: hot pixels (same rule as the night's M31 run, rebuilt for these 10 s ISO 1600 frames), and a check of
the sensor's dust shadows against the M31 run's maps.
Fixed hot pixels: the per-plane median, WITHOUT registration, of all frames (each minus its own plane median);
they come from eleven pointings, so no star survives the median. A pixel is hot if it stands above the 5x5 median
of that by more than max(6 sigma, 25% of the level) AND above its highest neighbour by half that.
Dust check: the median over all frames of plane / flat / the frame's level is a flat of the sensor's small-scale
shadows as they were during THIS hour (the sky is the lamp; stars, glare and nebulosity fall on different pixels
in different panels and drop out of the median). Its green, in 4 x 4 blocks, over its own wide blur, is compared
with the M31 core run's dust map (taken three hours earlier) where that map shows a shadow: if the dust has not
moved the two agree (slope 1, high correlation) and their ratio shows nothing but the hair."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from c import *

F = json.load(open(W('p1.json')))['frames']
NB = np.ones((3, 3), np.uint8); NB[1, 1] = 0


def load(fr):
    return load_planes(fr['path'])[0]


if __name__ == '__main__':
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(load, F))
    hot = np.zeros(res[0].shape, bool); hot_stats = []
    core_hot = np.load(os.path.join(CORE_WORK, 'hotmap.npy'))
    FLAT = np.load(os.path.join(CORE_WORK, 'flat2d.npy'))
    sflat = np.zeros(res[0].shape, np.float32)
    for p in range(4):
        sub = np.stack([res[i][p] - np.float32(F[i]['median_plane'][p]) for i in range(len(F))])
        M = np.median(sub, axis=0)
        L = cv2.medianBlur(M, 5); E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        alone = (M - cv2.dilate(M, NB)) > 0.5 * thr
        hot[p] = (E > thr) & alone
        hot_stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean()),
                              also_in_m31_core_map=int((hot[p] & core_hot[p]).sum()), m31_core_map=int(core_hot[p].sum())))
        print(hot_stats[-1], flush=True)
        # sky flat of this hour: frame / flat / level, median over frames (levels from a clipped mean of the flat-fielded plane)
        for i in range(len(F)):
            v = sub[i] + np.float32(F[i]['median_plane'][p]); v /= FLAT[p]
            lv = clipped_stats(v[::8, ::8], k=2.5)[0]
            sub[i] = v / np.float32(lv)
        sflat[p] = np.median(sub, axis=0); del sub
    np.save(W('hotmap.npy'), hot)
    # ---- the dust check ----
    SMALL, DMASK = small_flat()
    G = (sflat[1] + sflat[2]) / 2
    small = cv2.GaussianBlur(cv2.resize(G, None, fx=1 / 4, fy=1 / 4, interpolation=cv2.INTER_AREA), (0, 0), 1.5)
    big = cv2.GaussianBlur(cv2.medianBlur(cv2.resize(G, None, fx=1 / 16, fy=1 / 16, interpolation=cv2.INTER_AREA), 5), (0, 0), 4); big = cv2.resize(big, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_CUBIC)
    r = small / big
    s2 = cv2.GaussianBlur(cv2.resize(SMALL, None, fx=1 / 4, fy=1 / 4, interpolation=cv2.INTER_AREA), (0, 0), 1.5)
    hb = np.zeros(r.shape, bool); hb[HAIR_BOX[1] // 8:HAIR_BOX[3] // 8, HAIR_BOX[0] // 8:HAIR_BOX[2] // 8] = True
    deep = (s2 < 0.97) & ~hb; x = s2[deep] - 1; y = r[deep] - 1
    left = (r / s2)[deep]
    check = dict(blocks_where_the_core_map_is_under_0_97=int(deep.sum()), slope_of_this_hour_against_the_core_map=float((x * y).sum() / (x * x).sum()), correlation=float(np.corrcoef(x, y)[0, 1]),
                 shadow_depth_core_map_mean=float(1 - s2[deep].mean()), left_after_dividing_mean=float(left.mean()), left_after_dividing_rms=float(left.std()), scatter_of_this_hours_flat_outside_shadows=float(np.std(r[(s2 > 0.995) & ~hb])))
    print('dust check:', check)
    cv2.imwrite(W('v_skyflat_small.png'), (np.clip((r - 0.9) / 0.2, 0, 1) * 255).astype(np.uint8)); cv2.imwrite(W('v_skyflat_over_coremap.png'), (np.clip((r / s2 - 0.9) / 0.2, 0, 1) * 255).astype(np.uint8))
    json.dump(dict(frames=len(F), hot=hot_stats, dust_check=check), open(W('p2.json'), 'w'), indent=1)
