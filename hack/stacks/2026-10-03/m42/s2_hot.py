"""Step 2: hot-pixel maps (same rule as the M31 runs' step 2).
Fixed hot pixels, 20 s ISO 3200: the per-plane median, WITHOUT registration, of clear frames from several
pointings (the lowest-sky frames of the centred run, the stray group and the two clear panels, at most 9 from
each, each minus its sky level); stars and nebula sit at different sensor places in different pointings and
drop out of the median or are smooth. A pixel is hot if it stands above the 5x5 median of that by more than
max(6 sigma, 25% of the level) AND above its highest neighbour by half that (so a star is never taken for one).
2 s ISO 800: the same rule on the median of the 16 short frames (one pointing: the 'alone' test protects the stars).
Single-frame spikes are found when a frame is read (common.repair): above the 3x3 median by more than
8 sigma + 50% of the level. Both are replaced by the 3x3 median of the same colour plane."""
import json
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *

F = json.load(open(W('s1.json')))['frames']


def load(fr):
    return load_planes(fr['path'])[0]


def hotmap(frames, tag):
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(load, frames, chunksize=2))
    hot = np.zeros(res[0].shape, bool); stats = []
    for p in range(4):
        sub = np.stack([res[i][p] - np.float32(frames[i]['dark_block']['clipped_mean'][p]) for i in range(len(frames))])
        M = np.median(sub, axis=0); del sub
        L = cv2.medianBlur(M, 5); E = M - L
        sM = 1.4826 * np.median(np.abs(E - np.median(E)))
        thr = np.maximum(6 * sM, 0.25 * np.clip(L, 0, None))
        alone = (M - cv2.dilate(M, NB8)) > 0.5 * thr
        hot[p] = (E > thr) & alone
        stats.append(dict(plane=PLANE_NAMES[p], sigma_of_median=float(sM), fixed_hot=int(hot[p].sum()), frac=float(hot[p].mean())))
        print(tag, stats[-1], flush=True)
    np.save(W('hot_%s.npy' % tag), hot)
    return stats


if __name__ == '__main__':
    long_ = [f for f in F if f['exposure_s'] == 20.0]
    pick = []
    for st in sorted(set(f['set'] for f in long_)):
        g = sorted([f for f in long_ if f['set'] == st and f['sky_green'] < 260], key=lambda f: f['sky_green'])[:9]
        pick += g
    print('20 s hot-pixel median from %d frames: %s' % (len(pick), {st: sum(f['set'] == st for f in pick) for st in sorted(set(f['set'] for f in pick))}))
    a = hotmap(pick, 'long')
    sh = [f for f in F if f['set'] == 'short']
    b = hotmap(sh, 'short')
    cm = np.load(os.path.join(CLOUD_CAL, 'hotmap.npy')); hl = np.load(W('hot_long.npy'))
    print('of the M31 core run\'s hot pixels (same night, 0736..0846), also hot now: %.0f%%; of today\'s, in that map: %.0f%%' % (100 * (cm & hl).sum() / cm.sum(), 100 * (cm & hl).sum() / hl.sum()))
    json.dump(dict(long=dict(frames=[f['stamp'] for f in pick], hot=a), short=dict(frames=[f['stamp'] for f in sh], hot=b)), open(W('s2.json'), 'w'), indent=1)
