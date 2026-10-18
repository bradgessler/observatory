"""Step 11: is the faint outer structure real? M33 fills the field, so there is no blank sky to compare with; the test
is between two independent stacks (the odd and the even frames, combined with the same keep mask in step 8).

Each half's green, stars taken out by a 9 x 9 median on a 2 x 2 binned copy, then band-passed to the scale of arms and
clusters (Gaussian SIG_LO px minus Gaussian SIG_HI px). In tiles of TILE arcmin across the picture: the correlation of
the two halves' band-passed light, and the same with one half turned by 180 degrees about the tile's centre (the null:
noise and leftover stars agree with nothing). A tile passes if its correlation is above the null's mean + 5 x the
null's spread over all tiles. The tiles are binned by distance from the nucleus: the outer arms are the far ones. Also
the same between tonight's frames alone and 13 October's alone (two nights, two flats' dust corrections: what does not
repeat across nights is not drawn as structure)."""
import json, os
import numpy as np, cv2
from common import *

SIG_LO, SIG_HI = 3.0, 20.0
TILE = float(os.environ.get('M33_TILE_ARCMIN', '3.0'))

if __name__ == '__main__':
    s9 = jload('step9_solve.json'); c = s9['crop_on_canvas']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
    cx, cy = s9['catalogue']['M33']['pixel']; px = s9['pixscale_arcsec'] / 60
    def bp(name):
        a = np.load(W('stack_%s.npy' % name))[1:3, y0:y1, x0:x1].mean(0)
        b = cv2.resize(np.nan_to_num(a), None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        b = cv2.medianBlur(b.astype(np.float32), 5)
        return cv2.GaussianBlur(b, (0, 0), SIG_LO / 2) - cv2.GaussianBlur(b, (0, 0), SIG_HI / 2)
    out = {}
    for pair in (('odd', 'even'), ('tonight', 'oct13')):
        if not all(os.path.exists(W('stack_%s.npy' % n)) for n in pair): continue
        A, B = bp(pair[0]), bp(pair[1]); t = int(round(TILE / px / 2)); rows = []
        for ty in range(0, A.shape[0] - t + 1, t):
            for tx in range(0, A.shape[1] - t + 1, t):
                a = A[ty:ty + t, tx:tx + t].ravel(); b = B[ty:ty + t, tx:tx + t]; br = b[::-1, ::-1].ravel(); b = b.ravel()
                r = float(np.corrcoef(a, b)[0, 1]); r0 = float(np.corrcoef(a, br)[0, 1])
                d = np.hypot((tx + t / 2) * 2 - cx, (ty + t / 2) * 2 - cy) * px
                rows.append(dict(tile_px=[2 * tx, 2 * ty], from_nucleus_arcmin=round(float(d), 1), corr=round(r, 3), null=round(r0, 3), rms_dn=round(float(np.std(a)), 2)))
        nul = np.array([r['null'] for r in rows]); lim = float(nul.mean() + 5 * nul.std())
        for r in rows: r['passes'] = r['corr'] > lim
        bins = []
        for a_, b_ in ((0, 6), (6, 10), (10, 14), (14, 18), (18, 30)):
            sel = [r for r in rows if a_ <= r['from_nucleus_arcmin'] < b_]
            if sel: bins.append(dict(arcmin=[a_, b_], tiles=len(sel), passing=sum(r['passes'] for r in sel), median_corr=round(float(np.median([r['corr'] for r in sel])), 3)))
        out['%s_vs_%s' % pair] = dict(limit=lim, null_mean=float(nul.mean()), null_spread=float(nul.std()), tiles=len(rows), passing=sum(r['passes'] for r in rows), by_distance=bins, rows=rows)
        print('%s vs %s: %d of %d tiles (%.0f arcmin) repeat (corr > %.3f, null %.3f +- %.3f)' % (*pair, out['%s_vs_%s' % pair]['passing'], len(rows), TILE, lim, nul.mean(), nul.std()))
        for b in bins: print('   %2d-%2d arcmin from the nucleus: %d of %d tiles pass, median correlation %.2f' % (*b['arcmin'], b['passing'], b['tiles'], b['median_corr']))
    out['what'] = __doc__.split('\n\n')[1]
    jdump(out, 'step11_halves.json')
