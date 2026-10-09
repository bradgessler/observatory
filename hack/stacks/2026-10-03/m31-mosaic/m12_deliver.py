"""Mosaic step 12: the files.

  m31-mosaic.png / .jpg           the six panels and the deep core stack, north up, east left, 1.552 arcsec/px
  m31-mosaic-centre.png / .jpg    the same from the core stack and the two centre panels only, cropped to their data
  m31-mosaic-linear.tif           the six-panel mosaic, linear, 32-bit float RGB, 0.776 arcsec/px, not smoothed
  m31-mosaic-coverage.tif         8-bit: which images contribute to each pixel (bits), same grid as the linear file
  m31-mosaic-weight.tif           32-bit float: inverse variance of green per pixel (1 / DN^2); 0 = no data
  m31-mosaic-diagnostic.png       footprints and seams: where two images share sky, their difference, exaggerated

Scale of the pictures: 2 x 2 block mean of the working grid = 1.552 arcsec/px. The stars are 4.1 arcsec wide in
the core and 4.5 to 5.5 in the panels, so 1.55 arcsec still samples them (2.6 px) and loses nothing the data
resolves, while it halves the grain; the panels would bear a coarser scale still (they are 2.5 to 10 times
noisier than the core), the core a finer one (its own pictures are at 0.776): this is the scale both can share.

Pictures: mrender.py. First the grain is evened out (adaptive_smooth: a Gaussian whose width follows the expected
noise, none in the core), then the core run's arcsinh curve with a pedestal of 10 DN, colour ratios from a copy
blurred by 4 px, colour pedestal 25 DN where the core carries the weight and 300 DN where only panels do.
Nothing is drawn on any picture. No data = black. JPEG quality 92, 4:4:4, no metadata; PNG 8-bit RGB, no metadata.

The diagnostic (1/8 of the working grid, 6.2 arcsec/px):
  - where two or more images have data: mid grey (128) = they agree; brighter = the LIGHTER-weighted image of the
    two heaviest is brighter than the heaviest, darker = fainter; 8 grey levels per DN of green, so black and white
    are -16 and +16 DN. Backgrounds of step 10 already taken off; 8 x 8 px medians, then a Gaussian of 3 px.
  - where only one image has data: a flat dim colour that names it (core: grey; (0,0) red, (1,0) yellow,
    (2,0) green, (2,1) cyan, (1,1) blue, (0,1) magenta), so each footprint can be traced.
  - no data: black."""
import json, os, sys
import numpy as np, cv2, tifffile
from PIL import Image
from mcommon import *
from mrender import *
import m11_combine as C11

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
STRETCH = dict(white=14000.0, soft=45.0, pedestal=10.0, chroma_sigma=4.0)
COLOUR_PEDESTAL = dict(core=25.0, panels=300.0)
GRAIN = dict(target_dn=2.5, sigma_max_px=3.0, noise_of_2x2_mean_over_working_noise=0.6)
PL = json.load(open(W('m8_place.json'))); R9 = json.load(open(W('m9_resample.json'))); grid = PL['grid']; PS = grid['pixel_scale_arcsec']
X0, Y0 = grid['nucleus_pixel']


def save(img8, stem):
    im = Image.fromarray(img8, 'RGB')
    im.save(os.path.join(DEST, stem + '.png'), optimize=True)
    im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)


def picture(name, stem, crop=False):
    m = np.load(W(name + '_rgb.npy')); nz = np.load(W(name + '_noise.npy')); cs = np.load(W(name + '_coreshare.npy')).astype(np.float32) / 255
    m[nz <= 0] = np.nan
    x0 = y0 = 0; y1, x1 = nz.shape
    if crop:
        ys, xs = np.nonzero(nz > 0); mg = 64
        x0 = max((xs.min() - mg) // 4 * 4, 0); y0 = max((ys.min() - mg) // 4 * 4, 0); x1 = min(-(-(xs.max() + mg) // 4) * 4, x1); y1 = min(-(-(ys.max() + mg) // 4) * 4, y1)
        m = m[y0:y1, x0:x1]; nz = nz[y0:y1, x0:x1]; cs = cs[y0:y1, x0:x1]
    b = bin2(m); n2 = np.nan_to_num(bin2(np.where(nz > 0, nz, np.nan)), nan=0.0) * GRAIN['noise_of_2x2_mean_over_working_noise']; c2 = bin2(cs)
    del m
    sm, sig, after = adaptive_smooth(b, n2, GRAIN['target_dn'], GRAIN['sigma_max_px'])
    cp = COLOUR_PEDESTAL['core'] * c2 + COLOUR_PEDESTAL['panels'] * (1 - c2)
    img = stretch(sm, cp, **STRETCH)
    save(img, stem)
    ok = np.isfinite(b).all(2)
    info = dict(images=C11.SETS[name], size_px=[int(img.shape[1]), int(img.shape[0])], pixel_scale_arcsec=2 * PS, field_arcmin=[round(img.shape[1] * 2 * PS / 60, 1), round(img.shape[0] * 2 * PS / 60, 1)],
                nucleus_at_px=[round((X0 - x0) / 2, 1), round((Y0 - y0) / 2, 1)], crop_of_working_grid_px=[int(x0), int(y0), int(x1), int(y1)],
                pixels_with_data=int(ok.sum()), fraction_of_picture_with_data=float(ok.mean()), pixels_at_255_in_any_channel=int((img == 255).any(2).sum()),
                median_8bit_where_data=[int(v) for v in np.median(img[ok][::7], axis=0)],
                smoothing_sigma_px=dict(none_fraction=float((sig[ok] == 0).mean()), median_where_applied=float(np.median(sig[ok & (sig > 0)])) if (ok & (sig > 0)).any() else 0.0, max=float(sig[ok].max())))
    print(stem, info, flush=True)
    return info


outs = {}
outs['m31-mosaic.png / .jpg'] = picture('six', 'm31-mosaic')
outs['m31-mosaic-centre.png / .jpg'] = picture('centre', 'm31-mosaic-centre', crop=True)

# ---------------- linear file, coverage, weight ----------------
m = np.load(W('six_rgb.npy')); nz = np.load(W('six_noise.npy')); cov = np.load(W('six_cover.npy'))
has = nz > 0
lin = np.where(has[:, :, None], m, 0).astype(np.float32)
wgt = np.where(has, 1.0 / np.maximum(nz, 1e-6) ** 2, 0).astype(np.float32)
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'm31-mosaic-linear.tif'), lin, photometric='rgb', compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm31-mosaic-coverage.tif'), cov, compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm31-mosaic-weight.tif'), wgt, compression='zlib', metadata=None)
outs['m31-mosaic-linear.tif'] = dict(what='the six-panel mosaic: linear, 32-bit float RGB, the core run\'s as-shot white balance, backgrounds of step 10 and the zero taken off, not stretched, not smoothed',
                                     units='DN of the 14-bit RAW scale per 20 s frame under the core run\'s clear sky (the units of m31-core-cloudflat-linear.tif)', size_px=[int(lin.shape[1]), int(lin.shape[0])], pixel_scale_arcsec=PS,
                                     nucleus_at_px=[X0, Y0], orientation='north up, east left; tangent plane about RA %.4f Dec %+.4f: pixel (X, Y) is at xi = (%.1f - X) x %.3f arcsec east, eta = (%.1f - Y) x %.3f arcsec north' % (NUC_RA, NUC_DEC, X0, PS, Y0, PS),
                                     no_data='0 in all three colours; the coverage and weight files say where (0 there too)', compression='zlib, lossless')
outs['m31-mosaic-coverage.tif'] = dict(what='8-bit bit mask, same grid: 1 core stack, 2 panel (0,0), 4 (1,0), 8 (2,0), 16 (2,1), 32 (1,1), 64 (0,1); 128 = every sample at this pixel came from a dust-divided combine', values_present=sorted(int(v) for v in np.unique(cov)))
outs['m31-mosaic-weight.tif'] = dict(what='32-bit float, same grid: inverse variance of green in one pixel, 1 / DN^2 (expected noise = 1 / sqrt(weight)); 0 = no data. Checked against the scatter of the mosaic itself: within 9% in every panel.',
                                     noise_green_dn=dict(min=float(nz[has].min()), median=float(np.median(nz[has][::7])), max=float(np.percentile(nz[has][::7], 99.5))))
del lin, wgt

# ---------------- the diagnostic ----------------
F = 8; Hm, Wm = grid['height'], grid['width']; hs, ws = Hm // F, Wm // F
names = PL['images']
G = np.full((len(names), hs, ws), np.nan, np.float32); WT = np.zeros((len(names), hs, ws), np.float32)
for i, k in enumerate(names):
    x0, y0, x1, y1 = R9[k]['bbox']
    rgb = np.load(W('grid/%s_rgb.npy' % k)); iv = np.load(W('grid/%s_invvar.npy' % k)); fe = np.load(W('grid/%s_feather.npy' % k)); q = np.load(W('grid/%s_q.npy' % k))
    g = rgb[:, :, 1].copy(); bg = C11.background(k, g.shape, x0, y0)
    if bg is not None: g -= bg[:, :, 1]
    ok = np.isfinite(rgb).all(2) & (iv > 0) & (fe > 0)
    full = np.full((Hm, Wm), np.nan, np.float32); full[y0:y1, x0:x1] = np.where(ok, g, np.nan)
    wfull = np.zeros((Hm, Wm), np.float32); wfull[y0:y1, x0:x1] = np.where(ok, fe * iv * q, 0)
    blk = full[:hs * F, :ws * F].reshape(hs, F, ws, F).transpose(0, 2, 1, 3).reshape(hs, ws, -1)
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter('ignore'); med = np.nanmedian(blk, axis=2)
    med[np.isfinite(blk).mean(2) < 0.5] = np.nan
    G[i] = med; WT[i] = wfull[:hs * F, :ws * F].reshape(hs, F, ws, F).mean((1, 3)); WT[i][~np.isfinite(med)] = 0
    del rgb, iv, fe, q, full, wfull, blk
n_img = (WT > 0).sum(0)
order = np.argsort(-WT, axis=0); first = order[0]; second = order[1]
gf = np.take_along_axis(np.nan_to_num(G, nan=0.0), first[None], 0)[0]; gs = np.take_along_axis(np.nan_to_num(G, nan=0.0), second[None], 0)[0]
two = n_img >= 2
D = np.where(two, gs - gf, 0).astype(np.float32)
Ds = nblur(D, two, 3.0)
GAIN = 8.0
grey = np.clip(128 + GAIN * Ds, 0, 255)
TONE = dict(core=(70, 70, 70), p00=(110, 40, 40), p10=(100, 95, 30), p20=(40, 105, 40), p21=(30, 100, 100), p11=(45, 55, 125), p01=(105, 40, 105))
diag = np.zeros((hs, ws, 3), np.uint8)
diag[two] = np.repeat(grey[two][:, None], 3, 1).astype(np.uint8)
one = n_img == 1
for i, k in enumerate(names): diag[one & (first == i)] = TONE[k]
Image.fromarray(diag, 'RGB').save(os.path.join(DEST, 'm31-mosaic-diagnostic.png'), optimize=True)
absd = np.abs(Ds[two])
outs['m31-mosaic-diagnostic.png'] = dict(size_px=[ws, hs], pixel_scale_arcsec=F * PS, gain_grey_levels_per_dn=GAIN, mid_grey=128, black_white_dn=[-128 / GAIN, 127 / GAIN],
                                         meaning='overlaps: (lighter-weighted of the two heaviest images) minus (heaviest), green, after the backgrounds of step 10; single coverage: a flat tone per image; no data: black',
                                         tones_rgb=TONE, overlap_fraction_of_data=float(two.sum() / max((n_img > 0).sum(), 1)),
                                         difference_in_overlaps_dn=dict(median_abs=float(np.median(absd)), p90_abs=float(np.percentile(absd, 90)), p99_abs=float(np.percentile(absd, 99)), fraction_beyond_5dn=float((absd > 5).mean()), fraction_beyond_10dn=float((absd > 10).mean())))
print('diagnostic', outs['m31-mosaic-diagnostic.png']['difference_in_overlaps_dn'], flush=True)
json.dump(dict(outputs=outs, stretch=STRETCH, colour_pedestal=COLOUR_PEDESTAL, grain=GRAIN, destination=DEST), open(W('m12_deliver.json'), 'w'), indent=1)
