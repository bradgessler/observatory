"""Step 9: the deliverables, from the stack and the well-covered rectangle of step 8.

  m33-stack.tif   the stack, linear, 16-bit RGB: R, mean of G1 and G2, B, times the camera's own daylight white balance
                  (no colour matrix), plus a pedestal of TIF_PEDESTAL. 1 unit = 1 DN of the 14-bit raw scale (white-balanced)
                  for a 15 s frame at the sensor centre (the flat is 1 there). The faint region of step 7 is at the pedestal.
                  Orientation: the reference frame's sensor, as the camera saw it (not mirrored); north is given in the recipe.
  m33.jpg         the finished picture at the stack's own scale (one pixel per 2 x 2 colour cell, 0.776 arcsec), render.py.
  m33-1600.jpg    the same, 1600 px wide, by area averaging (never enlarged).
Both JPEGs carry no metadata. The reference frame alone goes through exactly the same steps for the comparison
(work/v_single_finished.jpg, not delivered). Numbers for the recipe go to work/step9_deliver.json."""
import json, os
import numpy as np, cv2, tifffile, rawpy
from common import *
import render

TIF_PEDESTAL = 1000.0
s8 = jload('step8_solve.json'); c = s8['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
st = np.load(W('stack_mean.npy'))[:, y0:y1, x0:x1]; sg = np.load(W('stack_single.npy'))[:, y0:y1, x0:x1]
od = np.load(W('stack_odd.npy'))[:, y0:y1, x0:x1]; ev = np.load(W('stack_even.npy'))[:, y0:y1, x0:x1]
flat = np.load(W('flat.npy'))[y0:y1, x0:x1]; faint = np.load(W('faint_region.npy'))[y0:y1, x0:x1]
s1 = jload('step1.json'); ref = [f for f in s1['frames'] if f['stamp'] == REF_STAMP][0]
with rawpy.imread(ref['path']) as r:
    rgb_xyz = np.array(r.rgb_xyz_matrix).tolist()
RGB_CAM, pre_mul = render.camera_matrix(rgb_xyz)
wbd = np.array(ref['wb_daylight'][:3]); wb = wbd / wbd[1]
noise = [clipped_stats(st[p][faint])[1] for p in range(4)]
noise1 = [clipped_stats(sg[p][faint])[1] for p in range(4)]
half = [clipped_stats(((od[p] - ev[p]) / 2)[faint])[1] for p in range(4)]
assert np.isfinite(st).all()

# ---- the linear TIF
cam = np.dstack([st[0] * wb[0], 0.5 * (st[1] + st[2]), st[3] * wb[2]])
t16 = np.clip(np.round(cam + TIF_PEDESTAL), 0, 65535).astype(np.uint16)
tifffile.imwrite(os.path.join(OUT, 'm33-stack.tif'), t16, photometric='rgb', compression='zlib', metadata=None)
tif_info = dict(size_px=[int(t16.shape[1]), int(t16.shape[0])], pedestal=TIF_PEDESTAL, units='DN of the 14-bit raw scale, white-balanced (R x %.4f, B x %.4f), per 15 s frame at the sensor centre' % (wb[0], wb[2]),
                clipped_low_px=int((cam + TIF_PEDESTAL < 0).sum()), clipped_high_px=int((cam + TIF_PEDESTAL > 65535).sum()), colour='camera RGB, daylight white balance, no colour matrix',
                origin_on_reference_grid=[x0, y0], compression='zlib, lossless')

# ---- the picture
rgb, info, L = render.finish(st, flat, wb, RGB_CAM, noise)
size = render.save_jpeg(rgb, os.path.join(OUT, 'm33.jpg'))
h, w = rgb.shape[:2]; W16 = 1600; H16 = int(round(h * W16 / w))
small = cv2.resize(rgb, (W16, H16), interpolation=cv2.INTER_AREA)
size16 = render.save_jpeg(small, os.path.join(OUT, 'm33-1600.jpg'))
sky = render.skycheck((rgb * 255 + 0.5).astype(np.uint8)); sky16 = render.skycheck((small * 255 + 0.5).astype(np.uint8))
# the reference frame alone, same steps, same numbers
rgb1, info1, L1 = render.finish(sg, flat, wb, RGB_CAM, noise)
render.save_jpeg(rgb1, W('v_single_finished.jpg'))
render.save_jpeg(np.hstack([rgb1[584:984, 1270:1870], rgb[584:984, 1270:1870]]), W('v_single_vs_stack_core.jpg'))
# luminance noise before and after the 1 px blur, in the faint region (linear DN)
wl, wbp = render.lum_weights(noise, wb)
Lraw = sum(wl[k] * st[k] * wbp[k] for k in range(4)); Lraw1 = sum(wl[k] * sg[k] * wbp[k] for k in range(4))
nL = dict(stack_unblurred=clipped_stats(Lraw[faint])[1], single_unblurred=clipped_stats(Lraw1[faint])[1], stack_after_blur=clipped_stats(L[faint])[1], single_after_blur=clipped_stats(L1[faint])[1])
nG = dict(stack=clipped_stats((0.5 * (st[1] + st[2]))[faint])[1], single=clipped_stats((0.5 * (sg[1] + sg[2]))[faint])[1])
# star size in the stack: half-flux diameter of compact, unsaturated, isolated stars (green), against the reference frame alone
stars = [s for s in json.load(open(W('step2_stars.json'))) if s['stamp'] == REF_STAMP][0]['stars']
Gs, G1s = 0.5 * (st[1] + st[2]), 0.5 * (sg[1] + sg[2])
def hfd(img, x, y, rmax=14):
    xi, yi = int(round(x)), int(round(y))
    if xi < 30 or yi < 30 or xi > img.shape[1] - 31 or yi > img.shape[0] - 31: return None
    t = img[yi - 30:yi + 31, xi - 30:xi + 31]; yy, xx = np.mgrid[-30:31, -30:31]; r = np.hypot(xx - (x - xi), yy - (y - yi))
    bg = np.median(t[(r > 20) & (r < 28)]); a = r <= rmax; o = np.argsort(r[a]); cum = np.cumsum((t - bg)[a][o])
    return float(2 * r[a][o][np.searchsorted(cum, cum[-1] / 2)]) if cum[-1] > 0 else None
cand = [s for s in stars if not s['saturated'] and s['nearest'] > 40 and s['flux'] > 20000]
hm = np.median([s['hfr'] for s in cand]); cand = [s for s in cand if s['hfr'] <= 1.25 * hm]
hs = [(hfd(Gs, s['x'] - x0, s['y'] - y0), hfd(G1s, s['x'] - x0, s['y'] - y0)) for s in cand]
hs = [v for v in hs if v[0] and v[1]]
star = dict(stars=len(hs), hfd_stack_px=float(np.median([v[0] for v in hs])), hfd_single_px=float(np.median([v[1] for v in hs])))
star.update(hfd_stack_arcsec=star['hfd_stack_px'] * s8['pixscale_arcsec'], hfd_single_arcsec=star['hfd_single_px'] * s8['pixscale_arcsec'])
# the galaxy's light against the stack's noise: green, in rings around the nucleus (stack px)
nx_, ny_ = s8['catalogue']['M33 nucleus']['pixel']
yy, xx = np.mgrid[0:h, 0:w]; rr = np.hypot(xx - nx_, yy - ny_)
prof = []
for a, b in ((0, 5), (5, 20), (20, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, 1200), (1200, 1700)):
    m = (rr >= a) & (rr < b)
    prof.append(dict(r_px=[a, b], r_arcmin=[round(a * s8['pixscale_arcsec'] / 60, 2), round(b * s8['pixscale_arcsec'] / 60, 2)], green_median_dn=round(float(np.median(Gs[m])), 2),
                     per_pixel_snr_stack=round(float(np.median(Gs[m]) / nG['stack']), 2), per_pixel_snr_single=round(float(np.median(Gs[m]) / nG['single']), 2)))
out = dict(tif=tif_info, white_balance_daylight=dict(R=float(wb[0]), G=1.0, B=float(wb[2]), from_matrix=pre_mul.tolist()), as_shot_white_balance_median=np.median([f['wb'] for f in s1['frames']], axis=0).tolist(),
           rgb_xyz_matrix=rgb_xyz, rgb_cam=RGB_CAM.tolist(), render_params=render.PARAMS, render_info=info, single_render_info=info1,
           jpg=dict(native=dict(size_px=list(size), pixel_scale_arcsec=s8['pixscale_arcsec'], skycheck=sky), w1600=dict(size_px=list(size16), resampling='area average (cv2.INTER_AREA) of the finished picture, %.3f x' % (W16 / w), pixel_scale_arcsec=s8['pixscale_arcsec'] * w / W16, skycheck=sky16)),
           noise_faint_region=dict(units='DN per stack pixel, 3-sigma clipped std in the faint region (step 7)', planes_stack=dict(zip(PLANE_NAMES, noise)), planes_single=dict(zip(PLANE_NAMES, noise1)),
                                   planes_half_difference_odd_even=dict(zip(PLANE_NAMES, half)), improvement=dict(zip(PLANE_NAMES, [round(a / b, 2) for a, b in zip(noise1, noise)])),
                                   ideal=round(float(np.sqrt(sum(u['weight'] for u in jload('step5_select.json')['used']) ** 2 / sum(u['weight'] ** 2 for u in jload('step5_select.json')['used']))), 2),
                                   green_mean_of_two=nG, luminance=nL),
           star_size=star, galaxy_green_profile=prof)
jdump(out, 'step9_deliver.json')
print('tif', tif_info['size_px'], 'clipped low/high', tif_info['clipped_low_px'], tif_info['clipped_high_px'])
print('jpg native', size, 'and', size16, '| sky', sky, '| colour shown on %.1f%% of the picture, ceiling px %d, white-clipped %.3f%%' % (100 * info['colour_shown_fraction'], info['ceiling_pixels'], info['white_clipped_pct']))
print('noise single -> stack (planes):', [round(a, 1) for a in noise1], '->', [round(a, 1) for a in noise], 'improvement', out['noise_faint_region']['improvement'], 'ideal', out['noise_faint_region']['ideal'])
print('luminance noise', {k: round(v, 2) for k, v in nL.items()}, '| green', {k: round(v, 2) for k, v in nG.items()})
print('star HFD: stack %.2f px = %.2f", single %.2f px = %.2f" (%d stars)' % (star['hfd_stack_px'], star['hfd_stack_arcsec'], star['hfd_single_px'], star['hfd_single_arcsec'], star['stars']))
for p in prof: print('  r %5.1f-%5.1f arcmin  green %6.2f DN  S/N per px stack %.2f single %.2f' % (*p['r_arcmin'], p['green_median_dn'], p['per_pixel_snr_stack'], p['per_pixel_snr_single']))
