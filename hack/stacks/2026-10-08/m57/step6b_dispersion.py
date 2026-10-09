"""Step 6b: the air is a prism. At 35 to 39 degrees altitude, blue starlight is lifted more than red, so in the stack
each colour's image of a star sits a little apart (measured: red and blue about 0.8 px, 0.6 arcsec, apart). Measured
here on the stack's own stars (green above 20 x the noise, not clipped; centroids as in step 2 on each colour after the
smooth light is taken off), and folded into the resampling of the red and blue planes (step 6's warp, one interpolation,
nothing extra): red and blue are put where green is. Then the offsets are measured again (they should be about 0)."""
import numpy as np, cv2
from common import *
import step6_stack as S6
from step2_stars import measure

def offsets(st, ok):
    BLK = 64; bh, bw = h2 // BLK, w2 // BLK
    def flat(G):
        G = np.where(ok, G, 0).astype(np.float32)
        b = np.median(G[:bh * BLK, :bw * BLK].reshape(bh, BLK, bw, BLK), axis=(1, 3)).astype(np.float32)
        return G - cv2.resize(cv2.medianBlur(b, 3), (w2, h2), interpolation=cv2.INTER_LINEAR)
    D = [flat(st[0]), flat((st[1] + st[2]) / 2), flat(st[3])]
    sm = cv2.GaussianBlur(D[1], (0, 0), 2.5); m, s, _ = clipped_stats(sm[ok][::7])
    n_, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m + 20 * s).astype(np.uint8), connectivity=8)
    rows = []
    for i in range(1, n_):
        if stats[i, cv2.CC_STAT_AREA] < 10: continue
        r = [measure(d, float(cent[i][0]), float(cent[i][1])) for d in D]
        if any(v is None for v in r) or r[1]['peak'] > 3000 or r[1]['flux'] < 20000: continue
        rows.append([r[0]['x'] - r[1]['x'], r[0]['y'] - r[1]['y'], r[2]['x'] - r[1]['x'], r[2]['y'] - r[1]['y']])
    rows = np.array(rows); med = np.median(rows, axis=0); sc = 1.4826 * np.median(np.abs(rows - med), axis=0) / np.sqrt(len(rows))
    return dict(stars=len(rows), red_minus_green_px=med[:2].tolist(), blue_minus_green_px=med[2:].tolist(), standard_error_px=sc.tolist())

if __name__ == '__main__':
    cover = np.load(W_('cover.npy')); ok = cover == S6.N
    st = np.load(W_('stack_mean.npy'))
    before = offsets(st, ok); print('before', before, flush=True)
    s6 = jload('step6.json')
    prev = s6.get('colour_offsets', {}).get('applied_px', {'R': [0.0, 0.0], 'B': [0.0, 0.0]})   # if 6b already ran on this stack, add to it
    S6.DISP = {0: tuple(np.add(prev['R'], before['red_minus_green_px'])), 3: tuple(np.add(prev['B'], before['blue_minus_green_px']))}
    store = {k: np.load(W_('stack_%s.npy' % k)) for k in ('mean', 'used', 'odd', 'even')}; single = np.load(W_('single_planes.npy'))
    for p in (0, 3):
        out, single[p], cov, const, inf = S6.stack_plane(p)
        for k in store: store[k][p] = out[k]
        s6['planes'][p] = inf
        for i, s in enumerate(S6.stamps): s6['constants_dn'][s][PLANE_NAMES[p]] = round(float(const[i]), 3)
    for k, v in store.items(): np.save(W_('stack_%s.npy' % k), v)
    np.save(W_('single_planes.npy'), single)
    after = offsets(store['mean'], ok); print('after', after)
    s6['colour_offsets'] = dict(why='atmospheric dispersion: each colour\'s star images sit apart; red and blue resampled onto green', before=before, applied_px={'R': [float(v) for v in S6.DISP[0]], 'B': [float(v) for v in S6.DISP[3]]}, after=after)
    jsave(s6, 'step6.json')
