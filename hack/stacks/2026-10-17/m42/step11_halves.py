"""Step 11: is the faint outer structure real? M42's glow fills the field, so there is no blank sky to compare with; the
test is between two independent stacks: the odd and the even long frames, each proper-coadded and taken to one common
PSF in step 8. Tiles that touch the part where the short stack was joined in (step 8b, w > 0) are left out: there the
long frames clipped and both halves read the ceiling.

Each half's green, stars taken out (every source of the reference frame masked and filled with the smooth light, then a
5 x 5 median on a 2 x 2 binned copy), then band-passed to the scale of arms and
clusters (Gaussian SIG_LO px minus Gaussian SIG_HI px). In tiles of TILE arcmin across the picture: the correlation of
the two halves' band-passed light, and the same with one half turned by 180 degrees about the tile's centre (the null:
noise and leftover stars agree with nothing). A tile passes if its correlation is above the null's mean + 5 x the
null's spread over all tiles. The tiles are binned by distance from the Trapezium: the outer loops are the far ones. The
faintest tiles (the lowest third of the stack's smoothed green) are reported on their own: that is the faint outer light."""
import json, os
import numpy as np, cv2
from common import *

SIG_LO, SIG_HI = 3.0, 20.0
TILE = float(os.environ.get('M42_TILE_ARCMIN', '3.0'))

if __name__ == '__main__':
    s9 = jload('step9_solve.json'); c = s9['crop_on_canvas']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
    cx, cy = s9['catalogue']['Trapezium']['pixel']; wj = np.load(W('w.npy'))[y0:y1, x0:x1] > 0; G0 = np.nan_to_num(np.load(W('stack_mean.npy'))[1:3, y0:y1, x0:x1].mean(0))
    G0s = cv2.GaussianBlur(smooth_level(G0, 16, 5), (0, 0), 16); px = s9['pixscale_arcsec'] / 60
    # stars out: every source of the reference frame's list (step 2) masked (radius by its flux; 6 arcsec stars are wider
    # than the 5 x 5 median on the 2 x 2 binned grid, which alone let them through) and filled with the image's own smooth
    # light (16 px block medians), then the median as before
    import canvas as CV
    X0c, Y0c, _, _ = CV.load(); sm = np.zeros((y1 - y0, x1 - x0), np.uint8)
    for st in [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF_STAMP][0]['stars']:
        rr = 30 if st['saturated'] else int(np.clip(8 + 9 * np.log10(max(st['flux'], 1e3) / 1e4), 6, 30))
        cv2.circle(sm, (int(round(st['x'] - X0c - x0)), int(round(st['y'] - Y0c - y0))), rr, 1, -1)
    sm = sm > 0
    STAR_MASK_FRACTION = float(sm.mean())
    def bp(name):
        a = np.nan_to_num(np.load(W('stack_%s.npy' % name))[1:3, y0:y1, x0:x1].mean(0))
        a = np.where(sm, smooth_level(a, 16, 5), a)
        b = cv2.resize(a, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        b = cv2.medianBlur(b.astype(np.float32), 5)
        return cv2.GaussianBlur(b, (0, 0), SIG_LO / 2) - cv2.GaussianBlur(b, (0, 0), SIG_HI / 2)
    out = {}
    for pair in (('odd', 'even'),):
        if not all(os.path.exists(W('stack_%s.npy' % n)) for n in pair): continue
        A, B = bp(pair[0]), bp(pair[1]); t = int(round(TILE / px / 2)); rows = []
        for ty in range(0, A.shape[0] - t + 1, t):
            for tx in range(0, A.shape[1] - t + 1, t):
                if wj[2 * ty:2 * (ty + t), 2 * tx:2 * (tx + t)].any(): continue
                a = A[ty:ty + t, tx:tx + t].ravel(); b = B[ty:ty + t, tx:tx + t]; br = b[::-1, ::-1].ravel(); b = b.ravel()
                r = float(np.corrcoef(a, b)[0, 1]); r0 = float(np.corrcoef(a, br)[0, 1])
                d = np.hypot((tx + t / 2) * 2 - cx, (ty + t / 2) * 2 - cy) * px
                rows.append(dict(tile_px=[2 * tx, 2 * ty], from_trapezium_arcmin=round(float(d), 1), level_dn=round(float(np.median(G0s[2 * ty:2 * (ty + t), 2 * tx:2 * (tx + t)])), 1), corr=round(r, 3), null=round(r0, 3), rms_dn=round(float(np.std(a)), 2)))
        nul = np.array([r['null'] for r in rows]); lim = float(nul.mean() + 5 * nul.std())
        for r in rows: r['passes'] = r['corr'] > lim
        bins = []
        lv = np.array([r['level_dn'] for r in rows]); lo3 = float(np.percentile(lv, 100 / 3.0))
        fs = [r for r in rows if r['level_dn'] <= lo3]
        faintest = dict(level_max_dn=lo3, tiles=len(fs), passing=sum(r['passes'] for r in fs), median_corr=round(float(np.median([r['corr'] for r in fs])), 3))
        for a_, b_ in ((0, 6), (6, 10), (10, 14), (14, 18), (18, 30)):
            sel = [r for r in rows if a_ <= r['from_trapezium_arcmin'] < b_]
            if sel: bins.append(dict(arcmin=[a_, b_], tiles=len(sel), passing=sum(r['passes'] for r in sel), median_corr=round(float(np.median([r['corr'] for r in sel])), 3)))
        out['%s_vs_%s' % pair] = dict(star_mask_fraction=STAR_MASK_FRACTION, limit=lim, null_mean=float(nul.mean()), null_spread=float(nul.std()), tiles=len(rows), passing=sum(r['passes'] for r in rows), by_distance=bins, faintest_third=faintest, rows=rows)
        print('%s vs %s: %d of %d tiles (%.0f arcmin) repeat (corr > %.3f, null %.3f +- %.3f)' % (*pair, out['%s_vs_%s' % pair]['passing'], len(rows), TILE, lim, nul.mean(), nul.std()))
        print('   the faintest third of the tiles (smoothed green <= %.1f DN): %d of %d pass, median correlation %.2f' % (lo3, faintest['passing'], faintest['tiles'], faintest['median_corr']))
        for b in bins: print('   %2d-%2d arcmin from the Trapezium: %d of %d tiles pass, median correlation %.2f' % (*b['arcmin'], b['passing'], b['tiles'], b['median_corr']))
    out['what'] = __doc__.split('\n\n')[1]
    jdump(out, 'step11_halves.json')
