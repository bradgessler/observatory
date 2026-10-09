"""Step 12d (a measurement, only with M45_MASTER_FLAT): the mosaic made with the master flat against the first run's
(before-flats/ beside the results), and the stacks at fixed places on the sensor.

1. The mosaic: 64 px block medians (of the 1.55 arcsec picture grid) of after - before per colour; the pixel scatter
   of both in the darkest clear blocks (the same blocks); the coverage.
2. Colour of the dark sky: the block medians of R - G and B - G where the mosaic is dark (green under 3 DN) and no
   cloud stack contributes: their spread over the field, before and after (0 everywhere if the three colours' zeros
   agreed everywhere).
3. Sensor dust in the stacks (needs M45_BEFORE_WORK, a work folder of the same steps run without the master flat):
   at the dust shadows of 3% and deeper in the master flat (blobs of 80 plane px or more, outside the hair's box,
   80 px from the edge), in every stack: median of green inside over the median in a ring 5 to 15 px outside,
   minus 1; per place the median over the stacks that are faint there; then mean and rms over the places."""
import json, os, sys, warnings
import numpy as np, cv2, tifffile
from c import *
warnings.simplefilter('ignore')
DEST = OUT; BEF = os.path.join(NIGHT, 'm45', 'before-flats')
new = tifffile.imread(os.path.join(DEST, 'm45-mosaic-linear.tif')); old = tifffile.imread(os.path.join(BEF, 'm45-mosaic-linear.tif'))
cn = tifffile.imread(os.path.join(DEST, 'm45-mosaic-coverage.tif')); co = tifffile.imread(os.path.join(BEF, 'm45-mosaic-coverage.tif'))
assert new.shape == old.shape
new = np.where((cn > 0)[..., None], new, np.nan); old = np.where((co > 0)[..., None], old, np.nan)
BS = 64; ny, nx = new.shape[0] // BS, new.shape[1] // BS
def blocks(a):
    b = a[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS, -1).transpose(0, 2, 1, 3, 4).reshape(ny, nx, BS * BS, -1)
    m = np.nanmedian(b, axis=2); s = 1.4826 * np.nanmedian(np.abs(b - m[:, :, None]), axis=2); f = np.isfinite(b[..., 0]).mean(2)
    m[f < 0.95] = np.nan; s[f < 0.95] = np.nan
    return m, s
bo, so = blocks(old); bn, sn = blocks(new)
cloudshare = np.load(W('mosaic_fine_cloudshare.npy'))[80:80 + 2 * new.shape[0], 80:80 + 2 * new.shape[1]] if os.path.exists(W('mosaic_fine_cloudshare.npy')) else None
clear = np.ones((ny, nx), bool)
if cloudshare is not None:
    cs = cloudshare[:2 * ny * BS, :2 * nx * BS].reshape(ny, 2 * BS, nx, 2 * BS).max((1, 3)); clear = cs == 0
out = dict(mosaic={}, dark_sky_colour={}, dust_in_stacks=None)
d = bn - bo; ok = np.isfinite(d[..., 1]) & clear
out['mosaic']['after_minus_before_block_medians_dn'] = {c_: dict(blocks=int(ok.sum()), median=float(np.median(d[..., i][ok])), rms_about_median=float(np.std(d[..., i][ok] - np.median(d[..., i][ok]))), p02=float(np.percentile(d[..., i][ok], 2)), p98=float(np.percentile(d[..., i][ok], 98))) for i, c_ in enumerate('RGB')}
dark = ok & (bo[..., 1] < np.nanpercentile(bo[..., 1][ok], 25))
out['mosaic']['pixel_scatter_in_the_darkest_quarter_of_clear_blocks_dn'] = dict(before={c_: float(np.median(so[..., i][dark])) for i, c_ in enumerate('RGB')}, after={c_: float(np.median(sn[..., i][dark])) for i, c_ in enumerate('RGB')})
out['mosaic']['pixels_with_data'] = dict(before=int((co > 0).sum()), after=int((cn > 0).sum()))
print('after - before, 64 px block medians where no cloud stack contributes:', {k: (round(v['median'], 2), round(v['rms_about_median'], 2), round(v['p02'], 1), round(v['p98'], 1)) for k, v in out['mosaic']['after_minus_before_block_medians_dn'].items()})
print('pixel scatter in the darkest quarter of clear blocks (R, G, B): before %s after %s; pixels with data %d -> %d' % ([round(v, 2) for v in out['mosaic']['pixel_scatter_in_the_darkest_quarter_of_clear_blocks_dn']['before'].values()], [round(v, 2) for v in out['mosaic']['pixel_scatter_in_the_darkest_quarter_of_clear_blocks_dn']['after'].values()], (co > 0).sum(), (cn > 0).sum()))
for run, b in (('before', bo), ('after', bn)):
    m = clear & np.isfinite(b[..., 1]) & (b[..., 1] < 3)
    rg = b[..., 0][m] - b[..., 1][m]; bg = b[..., 2][m] - b[..., 1][m]
    out['dark_sky_colour'][run] = dict(blocks=int(m.sum()), red_minus_green_dn=dict(median=float(np.median(rg)), robust_rms=float(1.4826 * np.median(np.abs(rg - np.median(rg)))), p05=float(np.percentile(rg, 5)), p95=float(np.percentile(rg, 95))),
                                       blue_minus_green_dn=dict(median=float(np.median(bg)), robust_rms=float(1.4826 * np.median(np.abs(bg - np.median(bg)))), p05=float(np.percentile(bg, 5)), p95=float(np.percentile(bg, 95))),
                                       green_dn=dict(robust_rms=float(1.4826 * np.median(np.abs(b[..., 1][m] - np.median(b[..., 1][m])))), p05=float(np.percentile(b[..., 1][m], 5)), p95=float(np.percentile(b[..., 1][m], 95))))
    print('%-6s dark clear sky (%d blocks): R - G median %+.2f, spread %.2f (5..95%%: %+.1f..%+.1f); B - G median %+.2f, spread %.2f (%+.1f..%+.1f); green spread %.2f (%+.1f..%+.1f)' % (run, m.sum(), np.median(rg), out['dark_sky_colour'][run]['red_minus_green_dn']['robust_rms'], np.percentile(rg, 5), np.percentile(rg, 95), np.median(bg), out['dark_sky_colour'][run]['blue_minus_green_dn']['robust_rms'], np.percentile(bg, 5), np.percentile(bg, 95), out['dark_sky_colour'][run]['green_dn']['robust_rms'], np.percentile(b[..., 1][m], 5), np.percentile(b[..., 1][m], 95)))
BW = os.environ.get('M45_BEFORE_WORK')
if BW and MASTER_FLAT:
    MF = np.load(MASTER_FLAT)
    def wide(a):
        small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
        low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
        return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
    g = (MF[1] + MF[2]) / 2; D = cv2.GaussianBlur(g / wide(g), (0, 0), 2.5)
    okm = np.ones((H2, W2), bool); hx0, hy0, hx1, hy1 = [v // 2 for v in HAIR_BOX]; okm[max(hy0 - 60, 0):hy1 + 60, hx0 - 60:hx1 + 60] = False; okm[:80] = False; okm[-80:] = False; okm[:, :80] = False; okm[:, -80:] = False
    n, lab, st, cen = cv2.connectedComponentsWithStats(((D < 0.97) & okm).astype(np.uint8), connectivity=8); places = []
    for i in range(1, n):
        if st[i, 4] < 80: continue
        x0, y0, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]; mg = 20; sl = (slice(max(y0 - mg, 0), y0 + h + mg), slice(max(x0 - mg, 0), x0 + w + mg)); b = lab[sl] == i
        ring = cv2.dilate(b.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))).astype(bool) & ~cv2.dilate(b.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))).astype(bool)
        places.append((sl, b, ring, [round(2 * float(cen[i][0])), round(2 * float(cen[i][1]))], float(np.median(D[sl][b]))))
    res = {}
    for run, wdir in (('before', BW), ('after', WORK)):
        rows = []
        stk = {k: np.load(os.path.join(wdir, k + '_planes.npy'))[1:3].mean(0) for k in PANELS}; lev = {k: float(np.nanmedian(stk[k][::8, ::8])) for k in PANELS}
        for sl, b, ring, cxy, depth in places:
            vals = []; dn = []
            for k in PANELS:
                a = stk[k][sl]; f = np.isfinite(a)
                if (f & b).sum() < 0.75 * b.sum() or (f & ring).sum() < 0.75 * ring.sum(): continue
                inside = float(np.median(a[f & b])); outside = float(np.median(a[f & ring]))
                if outside > 2.5 * lev[k]: continue                    # a bright star's glare there: skip this stack
                vals.append(inside / outside - 1); dn.append(inside - outside)
            if len(vals) >= 5: rows.append(dict(centre_sensor_xy=cxy, flat_value=depth, stacks=len(vals), contrast=float(np.median(vals)), contrast_dn=float(np.median(dn))))
        c = np.array([r['contrast'] for r in rows]); dnn = np.array([r['contrast_dn'] for r in rows])
        res[run] = dict(places=len(rows), mean_percent=float(100 * c.mean()), rms_percent=float(100 * np.sqrt((c ** 2).mean())), mean_dn=float(dnn.mean()), rms_dn=float(np.sqrt((dnn ** 2).mean())), worst_dn=float(dnn[np.argmax(np.abs(dnn))]), sky_level_dn_median=float(np.median(list(lev.values()))))
        print('%-6s dust places %d: the stacks hold there, mean %+.2f%% rms %.2f%%; in DN: mean %+.3f rms %.3f worst %+.2f (sky %.0f DN)' % (run, len(rows), 100 * c.mean(), 100 * np.sqrt((c ** 2).mean()), dnn.mean(), np.sqrt((dnn ** 2).mean()), dnn[np.argmax(np.abs(dnn))], res[run]['sky_level_dn_median']))
        fl = {k: np.load(os.path.join(wdir, k + '_flag.npy')) for k in PANELS}
        res[run]['flagged_fraction_per_stack'] = {k: float((fl[k] == 2).mean()) for k in PANELS}; res[run]['no_data_fraction_per_stack'] = {k: float((fl[k] == 0).mean()) for k in PANELS}
        res[run]['stack_noise_g1_dn'] = {k: json.load(open(os.path.join(wdir, 'p6_%s.json' % k)))['noise_of_stack_dn_per_half_grid_px']['G1'] for k in PANELS}
    out['dust_in_stacks'] = res
    print('flagged (quarter weight) per stack: before %.3f..%.3f, after %.4f..%.4f; stack noise G1 before %s after %s' % (min(res['before']['flagged_fraction_per_stack'].values()), max(res['before']['flagged_fraction_per_stack'].values()), min(res['after']['flagged_fraction_per_stack'].values()), max(res['after']['flagged_fraction_per_stack'].values()),
          [round(v, 2) for v in res['before']['stack_noise_g1_dn'].values()], [round(v, 2) for v in res['after']['stack_noise_g1_dn'].values()]))
json.dump(out, open(W('p12d_before_after.json'), 'w'), indent=1)
