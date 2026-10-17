"""CALIBRATED: the white balance is the camera's daylight balance times the star-colour factors of step 9b (Gaia DR3)
when M77_COLOUR_CAL=1 (the default); the TIF and the picture both carry it.

Step 10: the stack as files, from the stack arrays and the well-covered rectangle of step 9.

  m77-stack.tif             the stack, linear, 16-bit RGB: R, mean of G1 and G2, B, times the camera's own daylight
                            white balance (no colour matrix), plus a pedestal of TIF_PEDESTAL. 1 unit = 1 DN of the
                            14-bit raw scale (white-balanced) for a 15 s frame at the sensor centre (the flat is 1
                            there). The sky is at the pedestal (one constant per colour per frame, nothing else).
                            Orientation: the reference frame's sensor, as the camera saw it (not mirrored); north is
                            given in the recipe. The full well-covered field.
  work/m77-stretched.png    16-bit, colour and arcsinh stretch (render.py), the full field: the input of step 11.
  work/single-stretched.png the reference frame alone through exactly the same steps, for the comparison.

In the PICTURE only (the stretched PNGs, not the TIF): a sky plane per colour, a + b x + c y, fitted to the stack's own
sky far from the galaxy (the sky region of step 8: outside the 5.3 x 4.5 arcmin ellipse; 64 px block medians, 3-sigma
clipped) and subtracted. It is this sky's own slope across the field (step 7 found the same slope against the flat).
The skill allows it in the picture and wants it said.

Numbers for the recipe go to work/step10_deliver.json: noise of the stack and of one frame, the odd/even half
difference, star size in the stack, whether the core reached the sensor's ceiling (from every frame's own RAW values,
step 2), and what is seen of the galaxy: the median of the green light in rings around the nucleus (a median, so stars
drop out), from the whole stack and from the odd and the even frames alone, against the SAME rings laid on 11 places of
blank sky in the same stack (their spread is what the flat and the sky leave at each radius: the real floor, larger
than the pixel noise). The galaxy is "followed" out to where its ring median stays above 3 x that spread, and the
outer ring is called seen only if there is light above that floor at its radius."""
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
wb_daylight = wb.copy(); colour_cal = None
if COLOUR_CAL:
    colour_cal = jload('step9b_colour.json')['factors']
    wb = wb * np.array([colour_cal['R'], 1.0, colour_cal['B']])
    print('white balance: daylight R %.4f B %.4f x star colours kR %.4f kB %.4f -> R %.4f B %.4f' % (wb_daylight[0], wb_daylight[2], colour_cal['R'], colour_cal['B'], wb[0], wb[2]))
noise = [clipped_stats(st[p][faint])[1] for p in range(4)]
noise1 = [clipped_stats(sg[p][faint])[1] for p in range(4)]
half = [clipped_stats(((od[p] - ev[p]) / 2)[faint])[1] for p in range(4)]
assert np.isfinite(st).all()

# ---- the linear TIF
cam = np.dstack([st[0] * wb[0], 0.5 * (st[1] + st[2]), st[3] * wb[2]])
t16 = np.clip(np.round(cam + TIF_PEDESTAL), 0, 65535).astype(np.uint16)
tifffile.imwrite(os.path.join(OUT, 'm77-stack.tif'), t16, photometric='rgb', compression='zlib', metadata=None)
tif_info = dict(size_px=[int(t16.shape[1]), int(t16.shape[0])], pedestal=TIF_PEDESTAL, units='DN of the 14-bit raw scale, white-balanced (R x %.4f, B x %.4f), per 15 s frame at the sensor centre' % (wb[0], wb[2]),
                clipped_low_px=int((cam + TIF_PEDESTAL < 0).sum()), clipped_high_px=int((cam + TIF_PEDESTAL > 65535).sum()), colour='camera RGB, daylight white balance, no colour matrix',
                origin_on_reference_grid=[x0, y0], compression='zlib, lossless')

# ---- the stretched 16-bit pictures for step 10
# the sky plane, for the picture only
BK = 64; hh_, ww_ = st.shape[1:]; nby, nbx = hh_ // BK, ww_ // BK
by, bx = np.mgrid[0:nby, 0:nbx]; bxc, byc = bx * BK + BK / 2 - ww_ / 2, by * BK + BK / 2 - hh_ / 2
fb = faint[:nby * BK, :nbx * BK].reshape(nby, BK, nbx, BK).transpose(0, 2, 1, 3).reshape(nby, nbx, -1)
okb = fb.mean(2) > 0.5
yy_, xx_ = np.mgrid[0:hh_, 0:ww_].astype(np.float32); planes_fit = []; stp = np.empty_like(st); sgp = np.empty_like(sg); odp = np.empty_like(od); evp = np.empty_like(ev)
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
cv2.imwrite(W('m77-stretched.png'), (rgb[..., ::-1] * 65535 + 0.5).astype(np.uint16))
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
# ---- did the core reach the sensor's ceiling? every frame's own RAW values around the nucleus (step 2: the largest value of each plane within 14 px)
s3 = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}; s6 = jload('step6_solve_ref.json'); nref = np.array([2 * s6['galaxy_ellipse']['centre_px'][0] + 0.5, 2 * s6['galaxy_ellipse']['centre_px'][1] + 0.5])
core_rows = []
for r in json.load(open(W('step2_stars.json'))):
    o = s3[r['stamp']]; p_ = nref @ np.array(o['R']).T + np.array(o['t'])
    k = min(r['stars'], key=lambda k_: np.hypot(2 * k_['x'] + 0.5 - p_[0], 2 * k_['y'] + 0.5 - p_[1]))
    if np.hypot(2 * k['x'] + 0.5 - p_[0], 2 * k['y'] + 0.5 - p_[1]) < 12: core_rows.append((r['stamp'], k['plane_max']))
cm = np.array([v for _, v in core_rows]); CEIL = CEILING_RAW - 512.0
core = dict(what='the largest black-subtracted RAW value of each colour plane within 14 px of the nucleus, in every frame of the run (15 s, ISO 3200); the ceiling is %.0f DN above black' % CEIL,
            frames=len(core_rows), max_over_frames_dn=dict(zip(PLANE_NAMES, cm.max(0).round().tolist())), median_over_frames_dn=dict(zip(PLANE_NAMES, np.median(cm, 0).round().tolist())),
            highest_fraction_of_the_ceiling=round(float(cm.max() / CEIL), 3), clipped=bool(cm.max() >= 0.93 * CEIL), stack_peak_green_dn=None)
# ---- what is seen of the galaxy: ring medians around the nucleus against the same rings on blank sky
nx_, ny_ = s8['catalogue'][TARGET['name']]['nucleus_centroid_within_12px']; scale = s8['pixscale_arcsec']
core['stack_peak_green_dn'] = round(float((0.5 * (st[1] + st[2]))[int(round(ny_)) - 3:int(round(ny_)) + 4, int(round(nx_)) - 3:int(round(nx_)) + 4].max()), 1)
EDGES = np.concatenate([np.arange(0, 60, 6), np.arange(60, 337, 12)]).astype(float); RMID = 0.5 * (EDGES[:-1] + EDGES[1:])
G3 = {k: 0.5 * (a_[1] + a_[2]) for k, a_ in (('stack', stp), ('odd', odp), ('even', evp))}
hh, ww = G3['stack'].shape
def rings(img, cx, cy):
    R = int(EDGES[-1]) + 1; xi, yi = int(round(cx)), int(round(cy))
    if xi - R < 0 or yi - R < 0 or xi + R + 1 > ww or yi + R + 1 > hh: return None
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1]; yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (cx - xi), yy - (cy - yi))
    return np.array([float(np.median(t[(rr >= a_) & (rr < b_)])) for a_, b_ in zip(EDGES[:-1], EDGES[1:])])
prof = {k: rings(G3[k], nx_, ny_) for k in G3}
BLANK = [(380, 380), (380, 990), (380, 1600), (960, 1600), (1540, 1600), (2120, 1600), (2600, 1600), (2600, 990), (2600, 380), (900, 380), (2250, 380)]
blank = [(c_, rings(G3['stack'], *c_)) for c_ in BLANK]; blank = [(c_, v) for c_, v in blank if v is not None]
B = np.array([v for _, v in blank]); floor = B.std(0, ddof=1); bmean = B.mean(0)
half = np.abs(prof['odd'] - prof['even']) / 2
sig = np.maximum(floor, 1e-6)
above = prof['stack'] > 3 * sig
last = 0
for i in range(len(RMID)):
    if not above[i]: break
    last = i
followed_px = float(EDGES[last + 1])
def at(r_arcmin):
    i = int(np.argmin(np.abs(RMID * scale / 60 - r_arcmin)))
    return dict(r_arcmin=round(float(RMID[i] * scale / 60), 2), r_px=float(RMID[i]), stack_dn=round(float(prof['stack'][i]), 2), odd_dn=round(float(prof['odd'][i]), 2), even_dn=round(float(prof['even'][i]), 2),
                blank_sky_spread_dn=round(float(floor[i]), 2), blank_sky_mean_dn=round(float(bmean[i]), 2), over_the_floor=round(float(prof['stack'][i] / sig[i]), 1))
table = [at(r_) for r_ in (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.75, 4.0)]
ringzone = (RMID * scale / 60 >= 2.2) & (RMID * scale / 60 <= 3.6)                     # where the catalogue's outer ring lies (its 7.1 x 6.0 arcmin diameters)
ring_seen = bool((prof['stack'][ringzone] > 3 * sig[ringzone]).all() and (prof['odd'][ringzone] > 2 * sig[ringzone]).all() and (prof['even'][ringzone] > 2 * sig[ringzone]).all())
sky_green = float(np.median([v[1] for v in jload('step8_stack.json')['constants'].values()]))
galaxy = dict(what='green (mean of G1 and G2), sky plane removed, the MEDIAN in rings around the nucleus (6 px wide to 60 px, 12 px wide beyond; 1 px = %.4f arcsec); a median, so the stars drop out, the 10th magnitude star 1.45 arcmin from the nucleus among them' % scale,
              nucleus_px=[nx_, ny_], ring_mid_px=RMID.tolist(), stack_dn=np.round(prof['stack'], 3).tolist(), odd_frames_dn=np.round(prof['odd'], 3).tolist(), even_frames_dn=np.round(prof['even'], 3).tolist(),
              blank_sky=dict(what='the same rings laid on %d places of blank sky in the same stack; their spread (standard deviation between the places) at each radius is what the flat and the sky leave: the floor' % len(blank), centres_px=[list(c_) for c_, _ in blank], spread_dn=np.round(floor, 3).tolist(), mean_dn=np.round(bmean, 3).tolist()),
              odd_even_half_difference_dn=np.round(half, 3).tolist(), sky_under_it_dn=round(sky_green, 1),
              followed_to=dict(rule='the ring median above 3 x the blank-sky spread, unbroken from the centre', radius_px=followed_px, radius_arcmin=round(followed_px * scale / 60, 2), diameter_arcmin=round(2 * followed_px * scale / 60, 2), catalogue_diameters_arcmin=list(GALAXY_SIZE_ARCMIN)),
              at_radii=table,
              outer_ring=dict(where='2.2 to 3.6 arcmin from the nucleus (the catalogue\'s 7.1 x 6.0 arcmin diameters)', seen=ring_seen, rule='every ring median there above 3 x the blank-sky spread in the stack and above 2 x in the odd and in the even frames alone',
                              stack_dn_there=[round(float(v), 2) for v in prof['stack'][ringzone]], floor_dn_there=[round(float(v), 2) for v in floor[ringzone]], as_a_fraction_of_the_sky=[round(float(v / sky_green), 4) for v in prof['stack'][ringzone]]))
out = dict(tif=tif_info, white_balance_daylight=dict(R=float(wb_daylight[0]), G=1.0, B=float(wb_daylight[2]), from_matrix=pre_mul.tolist()), white_balance_applied=dict(R=float(wb[0]), G=1.0, B=float(wb[2]), star_colour_factors=colour_cal), as_shot_white_balance_median=np.median([f['wb'] for f in s1['frames']], axis=0).tolist(),
           rgb_xyz_matrix=rgb_xyz, rgb_cam=RGB_CAM.tolist(), render_params=render.PARAMS, render_info=info, single_render_info=info1, stretched_size_px=[int(w), int(h)],
           noise_faint_region=dict(units='DN per stack pixel, 3-sigma clipped std in the faint region (step 7)', planes_stack=dict(zip(PLANE_NAMES, noise)), planes_single=dict(zip(PLANE_NAMES, noise1)),
                                   planes_half_difference_odd_even=dict(zip(PLANE_NAMES, half)), improvement=dict(zip(PLANE_NAMES, [round(a / b, 2) for a, b in zip(noise1, noise)])),
                                   ideal=round(float(np.sqrt(sum(u['weight'] for u in jload('step5_select.json')['used']) ** 2 / sum(u['weight'] ** 2 for u in jload('step5_select.json')['used']))), 2),
                                   green_mean_of_two=nG, luminance=nL),
           star_size=star, core=core, galaxy=galaxy, sky_plane_in_the_picture_only=planes_fit)
jdump(out, 'step10_deliver.json')
print('tif', tif_info['size_px'], 'clipped low/high', tif_info['clipped_low_px'], tif_info['clipped_high_px'])
print('stretched', [w, h], '| colour shown on %.1f%% of the picture, ceiling px %d, at floor %d, at white %d' % (100 * info['colour_shown_fraction'], info['ceiling_pixels'], info['at_floor_px'], info['at_white_px']))
print('noise single -> stack (planes):', [round(a, 1) for a in noise1], '->', [round(a, 1) for a in noise], 'improvement', out['noise_faint_region']['improvement'], 'ideal', out['noise_faint_region']['ideal'])
print('luminance noise', {k: round(v, 2) for k, v in nL.items()}, '| green', {k: round(v, 2) for k, v in nG.items()})
print('star HFD: stack %.2f px = %.2f", single %.2f px = %.2f" (%d stars)' % (star['hfd_stack_px'], star['hfd_stack_arcsec'], star['hfd_single_px'], star['hfd_single_arcsec'], star['stars']))
print('core: highest RAW value around the nucleus in any frame %s DN (ceiling %.0f): %.0f%% of the ceiling -> %s; the stack\'s green peak %.0f DN' % (core['max_over_frames_dn'], CEIL, 100 * core['highest_fraction_of_the_ceiling'], 'CLIPPED' if core['clipped'] else 'not clipped', core['stack_peak_green_dn']))
print('ring medians (green, DN; sky under it %.0f DN):' % sky_green)
for t_ in table: print('  r %.2f\' (%3.0f px): stack %7.2f  odd %7.2f  even %7.2f  | blank sky %+.2f +- %.2f  -> %.1f x the floor' % (t_['r_arcmin'], t_['r_px'], t_['stack_dn'], t_['odd_dn'], t_['even_dn'], t_['blank_sky_mean_dn'], t_['blank_sky_spread_dn'], t_['over_the_floor']))
print('galaxy followed to %.2f arcmin from the nucleus (%.1f arcmin across; catalogue 7.1 x 6.0); outer ring (2.2 to 3.6 arcmin): %s' % (galaxy['followed_to']['radius_arcmin'], galaxy['followed_to']['diameter_arcmin'], 'SEEN' if ring_seen else 'not seen'))
