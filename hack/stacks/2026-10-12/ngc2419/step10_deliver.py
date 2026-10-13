"""Step 10: the stack as files, from the stack arrays and the well-covered rectangle of step 9.

  ngc2419-stack.tif              the stack, linear, 16-bit RGB: R, mean of G1 and G2, B, times the camera's own daylight
                            white balance (no colour matrix), plus a pedestal of TIF_PEDESTAL. 1 unit = 1 DN of the
                            14-bit raw scale (white-balanced) for a 15 s frame at the sensor centre (the flat is 1
                            there). The sky is at the pedestal (one constant per colour per frame, nothing else).
                            Orientation: the reference frame's sensor, as the camera saw it (not mirrored); north is
                            given in the recipe. The full well-covered field.
  work/ngc2419-stretched.png     16-bit, colour and arcsinh stretch (render.py), the full field: the input of step 12.
  work/single-stretched.png the reference frame alone through exactly the same steps, for the comparison.

In the PICTURE only (the stretched PNGs, not the TIF): a sky plane per colour, a + b x + c y, fitted to the stack's own
sky far from the cluster (the sky region of step 8: outside NGC 2419's 4 arcmin circle and the 2 arcmin circles of the two
bright stars; 64 px block medians, 3-sigma clipped) and subtracted. It is this sky's own slope across the field (step 7
measures the same slope against the flat). The skill allows it in the picture and wants it said. Under the cluster it
is the plane's continuation: three numbers per colour cannot follow a haze 2 arcmin across.

Numbers for the recipe go to work/step10_deliver.json: noise of the stack and of one frame, the odd/even half
difference, star size in the stack. What is seen of the cluster, how wide the haze is, its grain, its colour, and whether each is real: step 11."""
import json, os
import numpy as np, cv2, tifffile, rawpy
from common import *
import render

TIF_PEDESTAL = 1000.0
s8 = jload('step9_solve.json'); c = s8['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
st = np.load(W('stack_mean.npy'))[:, y0:y1, x0:x1]; sg = np.load(W('stack_single.npy'))[:, y0:y1, x0:x1]
od = np.load(W('stack_odd.npy'))[:, y0:y1, x0:x1]; ev = np.load(W('stack_even.npy'))[:, y0:y1, x0:x1]
flat = np.load(W('flat.npy'))[1, y0:y1, x0:x1]; faint = np.load(W('faint_region.npy'))[y0:y1, x0:x1]
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
tifffile.imwrite(os.path.join(OUT, 'ngc2419-stack.tif'), t16, photometric='rgb', compression='zlib', metadata=None)
tif_info = dict(size_px=[int(t16.shape[1]), int(t16.shape[0])], pedestal=TIF_PEDESTAL, units='DN of the 14-bit raw scale, white-balanced (R x %.4f, B x %.4f), per 15 s frame at the sensor centre' % (wb[0], wb[2]),
                clipped_low_px=int((cam + TIF_PEDESTAL < 0).sum()), clipped_high_px=int((cam + TIF_PEDESTAL > 65535).sum()), colour='camera RGB, daylight white balance, no colour matrix',
                origin_on_reference_grid=[x0, y0], compression='zlib, lossless')

# ---- the stretched 16-bit pictures for step 10
# the sky plane, for the picture only
BK = 64; hh_, ww_ = st.shape[1:]; nby, nbx = hh_ // BK, ww_ // BK
by, bx = np.mgrid[0:nby, 0:nbx]; bxc, byc = bx * BK + BK / 2 - ww_ / 2, by * BK + BK / 2 - hh_ / 2
fb = faint[:nby * BK, :nbx * BK].reshape(nby, BK, nbx, BK).transpose(0, 2, 1, 3).reshape(nby, nbx, -1)
okb = fb.mean(2) > 0.5
yy_, xx_ = np.mgrid[0:hh_, 0:ww_].astype(np.float32); planes_fit = []; stp = np.empty_like(st); sgp = np.empty_like(sg); odp = np.empty_like(od); evp = np.empty_like(ev)   # (the halves are not used further here; step 11 has its own)
for p in range(4):
    v = np.where(faint, st[p], np.nan)[:nby * BK, :nbx * BK].reshape(nby, BK, nbx, BK).transpose(0, 2, 1, 3).reshape(nby, nbx, -1)
    with np.errstate(all='ignore'): med = np.nanmedian(v, axis=2)
    A = np.stack([np.ones(okb.sum()), bxc[okb], byc[okb]], 1); z = med[okb]; keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], z[keep], rcond=None); r = z - A @ co; s_ = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3 * s_
    pl = (co[0] + co[1] * (xx_ - ww_ / 2) + co[2] * (yy_ - hh_ / 2)).astype(np.float32)
    stp[p] = st[p] - pl; sgp[p] = sg[p] - pl; odp[p] = od[p] - pl; evp[p] = ev[p] - pl
    planes_fit.append(dict(plane=PLANE_NAMES[p], a_dn=float(co[0]), b_dn_per_px=float(co[1]), c_dn_per_px=float(co[2]), corner_to_corner_dn=float(abs(co[1]) * ww_ + abs(co[2]) * hh_), blocks=int(keep.sum()), rms_of_blocks_after=float(np.std(r[keep]))))
    print('sky plane %-2s: %+.2f DN at the middle, %+.2f DN across the width, %+.2f DN down the height; block rms after %.2f DN' % (PLANE_NAMES[p], co[0], co[1] * ww_, co[2] * hh_, np.std(r[keep])))
rgb, info, L = render.stretched(stp, flat, wb, RGB_CAM, noise)
cv2.imwrite(W('ngc2419-stretched.png'), (rgb[..., ::-1] * 65535 + 0.5).astype(np.uint16))
rgb1, info1, L1 = render.stretched(sgp, flat, wb, RGB_CAM, noise)
cv2.imwrite(W('single-stretched.png'), (rgb1[..., ::-1] * 65535 + 0.5).astype(np.uint16))
h, w = rgb.shape[:2]
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
out = dict(tif=tif_info, white_balance_daylight=dict(R=float(wb[0]), G=1.0, B=float(wb[2]), from_matrix=pre_mul.tolist()), as_shot_white_balance_median=np.median([f['wb'] for f in s1['frames']], axis=0).tolist(),
           rgb_xyz_matrix=rgb_xyz, rgb_cam=RGB_CAM.tolist(), render_params=render.PARAMS, render_info=info, single_render_info=info1, stretched_size_px=[int(w), int(h)],
           noise_faint_region=dict(units='DN per stack pixel, 3-sigma clipped std in the sky region (step 8)', planes_stack=dict(zip(PLANE_NAMES, noise)), planes_single=dict(zip(PLANE_NAMES, noise1)),
                                   planes_half_difference_odd_even=dict(zip(PLANE_NAMES, half)), improvement=dict(zip(PLANE_NAMES, [round(a / b, 2) for a, b in zip(noise1, noise)])),
                                   ideal=round(float(np.sqrt(sum(u['weight'] for u in jload('step5_select.json')['used']) ** 2 / sum(u['weight'] ** 2 for u in jload('step5_select.json')['used']))), 2),
                                   green_mean_of_two=nG, luminance=nL),
           star_size=star, sky_plane_in_the_picture_only=planes_fit)
jdump(out, 'step10_deliver.json')
print('tif', tif_info['size_px'], 'clipped low/high', tif_info['clipped_low_px'], tif_info['clipped_high_px'])
print('stretched', [w, h], '| colour shown on %.1f%% of the picture, ceiling px %d, at floor %d, at white %d' % (100 * info['colour_shown_fraction'], info['ceiling_pixels'], info['at_floor_px'], info['at_white_px']))
print('noise single -> stack (planes):', [round(a, 1) for a in noise1], '->', [round(a, 1) for a in noise], 'improvement', out['noise_faint_region']['improvement'], 'ideal', out['noise_faint_region']['ideal'])
print('luminance noise', {k: round(v, 2) for k, v in nL.items()}, '| green', {k: round(v, 2) for k, v in nG.items()})
print('star HFD: stack %.2f px = %.2f", single %.2f px = %.2f" (%d stars)' % (star['hfd_stack_px'], star['hfd_stack_arcsec'], star['hfd_single_px'], star['hfd_single_arcsec'], star['stars']))
