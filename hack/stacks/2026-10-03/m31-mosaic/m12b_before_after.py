"""Mosaic step 12b (a measurement): the mosaic with the master flat against the mosaic of the first run
(before-flats/m31-mosaic-linear.tif and -coverage.tif beside the results). Same grid, same units.

1. Colour zeros. 64 px block medians of R, G, B where NO core data is (panel data only) and the light is faint
   (green under 30 DN). The galaxy's own light has the colour of the core field's glow (red / green 1.05, blue /
   green 0.95, core recipe); what red and blue hold beyond that is zero error: R - 1.05 G and B - 0.95 G, per panel
   (blocks where that panel alone covers), median and 5 to 95%. If the panels' red and blue zeros agreed with green,
   these would be near 0 in every panel, to within the noise of a block median (given).
2. How much the picture changed: 64 px block medians of (after - before), green, where the core carries the
   weight and where only panels do.
3. Pixels that rest on dust-divided data only (bit 128 of the coverage)."""
import json, os, sys
import numpy as np, tifffile
from mcommon import *
import warnings; warnings.simplefilter('ignore')
BEF = os.path.join(OUT, 'before-flats')
old = tifffile.imread(os.path.join(BEF, 'm31-mosaic-linear.tif')); oc = tifffile.imread(os.path.join(BEF, 'm31-mosaic-coverage.tif')); ow = tifffile.imread(os.path.join(BEF, 'm31-mosaic-weight.tif'))
new = np.load(W('six_rgb.npy')); nc = np.load(W('six_cover.npy')); nn = np.load(W('six_noise.npy'))
assert old.shape == new.shape, (old.shape, new.shape)
new = np.where((nn > 0)[..., None], new, np.nan); old = np.where((ow > 0)[..., None], old, np.nan)
BIT = dict(core=1, p00=2, p10=4, p20=8, p21=16, p11=32, p01=64); BS = 64; ny, nx = new.shape[0] // BS, new.shape[1] // BS
def blk(a):
    b = a[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS, -1).transpose(0, 2, 1, 3, 4).reshape(ny, nx, BS * BS, -1)
    m = np.nanmedian(b, axis=2); m[np.isfinite(b[..., 0]).mean(2) < 0.9] = np.nan
    return m
bo, bn = blk(old), blk(new)
def cb(c): return c[BS // 2:ny * BS:BS, BS // 2:nx * BS:BS] & 127
co, cn = cb(oc), cb(nc)
out = dict(colour_zero={}, change={}, dust_divided_only={})
for run, b, c, wnoise in (('before', bo, co, np.sqrt(1 / np.maximum(ow, 1e-9))), ('after', bn, cn, nn)):
    res = {}
    for k in ('p00', 'p10', 'p20', 'p21', 'p11', 'p01'):
        m = (c == BIT[k]) & np.isfinite(b[..., 1]) & (b[..., 1] < 30)
        if m.sum() < 10: res[k] = None; continue
        r = b[..., 0][m] - 1.05 * b[..., 1][m]; bl = b[..., 2][m] - 0.95 * b[..., 1][m]
        nz = float(np.median(wnoise[BS // 2:ny * BS:BS, BS // 2:nx * BS:BS][m])) * 1.2533 / BS          # noise of a block median, green
        res[k] = dict(blocks=int(m.sum()), green_dn=dict(median=float(np.median(b[..., 1][m]))), red_minus_1_05_green_dn=dict(median=float(np.median(r)), p05=float(np.percentile(r, 5)), p95=float(np.percentile(r, 95))),
                      blue_minus_0_95_green_dn=dict(median=float(np.median(bl)), p05=float(np.percentile(bl, 5)), p95=float(np.percentile(bl, 95))), noise_of_a_block_median_dn=dict(green=nz, red=3 * nz, blue=2 * nz))
        print('%-6s %s alone, faint blocks %4d (green %.1f DN): R - 1.05 G median %+6.1f (5..95%%: %+6.1f..%+6.1f); B - 0.95 G median %+5.1f (%+5.1f..%+5.1f); block noise R %.1f B %.1f' % (run, k, m.sum(), np.median(b[..., 1][m]), np.median(r), np.percentile(r, 5), np.percentile(r, 95), np.median(bl), np.percentile(bl, 5), np.percentile(bl, 95), 3 * nz, 2 * nz))
    med_r = [v['red_minus_1_05_green_dn']['median'] for v in res.values() if v]; med_b = [v['blue_minus_0_95_green_dn']['median'] for v in res.values() if v]
    res['spread_of_the_panel_medians_dn'] = dict(red=dict(min=min(med_r), max=max(med_r), rms=float(np.std(med_r))), blue=dict(min=min(med_b), max=max(med_b), rms=float(np.std(med_b))))
    res['largest_block_departure_dn'] = dict(red=max(max(abs(v['red_minus_1_05_green_dn']['p05']), abs(v['red_minus_1_05_green_dn']['p95'])) for v in res.values() if v and 'blocks' in v), blue=max(max(abs(v['blue_minus_0_95_green_dn']['p05']), abs(v['blue_minus_0_95_green_dn']['p95'])) for v in res.values() if v and 'blocks' in v))
    out['colour_zero'][run] = res
    print('%-6s panel medians: red %+.1f..%+.1f (rms %.1f), blue %+.1f..%+.1f (rms %.1f); largest 5..95%% departure red %.1f blue %.1f DN' % (run, min(med_r), max(med_r), np.std(med_r), min(med_b), max(med_b), np.std(med_b), res['largest_block_departure_dn']['red'], res['largest_block_departure_dn']['blue']))
d = bn - bo; both = np.isfinite(d[..., 1])
for nm, m in (('where the core stack has data', both & ((cn & 1) > 0)), ('where only panels have data', both & ((cn & 1) == 0))):
    out['change'][nm] = {c_: dict(blocks=int(m.sum()), median=float(np.median(d[..., i][m])), rms=float(np.sqrt(np.mean((d[..., i][m] - np.median(d[..., i][m])) ** 2))), p05=float(np.percentile(d[..., i][m], 5)), p95=float(np.percentile(d[..., i][m], 95))) for i, c_ in enumerate('RGB')}
    print('after - before, %s: %s' % (nm, {k: (round(v['median'], 2), round(v['rms'], 2), round(v['p05'], 1), round(v['p95'], 1)) for k, v in out['change'][nm].items()}))
out['dust_divided_only'] = dict(before_pixels=int(((oc & 128) > 0).sum()), after_pixels=int(((nc & 128) > 0).sum()), before_fraction_of_data=float(((oc & 128) > 0).sum() / max((ow > 0).sum(), 1)), after_fraction_of_data=float(((nc & 128) > 0).sum() / max((nn > 0).sum(), 1)))
out['noise_green_dn'] = dict(before_median=float(np.median(np.sqrt(1 / ow[ow > 0][::7]))), after_median=float(np.median(nn[nn > 0][::7])))
print('pixels resting on dust-divided data only: before %d (%.2f%%), after %d (%.3f%%); green noise median before %.2f after %.2f DN' % (out['dust_divided_only']['before_pixels'], 100 * out['dust_divided_only']['before_fraction_of_data'], out['dust_divided_only']['after_pixels'], 100 * out['dust_divided_only']['after_fraction_of_data'], out['noise_green_dn']['before_median'], out['noise_green_dn']['after_median']))
json.dump(out, open(W('m12b_before_after.json'), 'w'), indent=1)
