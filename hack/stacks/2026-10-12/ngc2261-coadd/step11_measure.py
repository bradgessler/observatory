"""Step 11: what is seen of NGC 2261, and is each thing real? Numbers only; no pixel of the picture is changed here.
The tests are those of tonight's hack/stacks/2026-10-12/m1/step11_measure.py and m78 (half stacks of the odd and the
even frames; the same measure laid on blank sky), asked of a small bright fan.

All on the well-covered rectangle of step 9, raw camera units (DN of the 14-bit RAW per 15 s frame), colours R,
G = mean of G1 and G2, B. The sky is the stack's own zero (one constant per colour per frame over the sky region,
step 8) less the picture's sky plane (step 10), so the numbers describe the picture that is shown.

  run        the dew question: star brightness (transparency), star size and the sky's level frame by frame, from
             steps 1, 4 and 8 and the index; thirds of the run compared; what the last frames did, and what the sky
             did while the stars were dim (cloud brightens the sky, dew does not).
  r_mon      the star at the tip: its place (step 9), its peak, and its half-flux diameter against the field's stars
             (is it a star or a knot of nebula at this resolution?).
  sky        blank-sky boxes of the fan's own area laid on a grid outside the object mask, stars masked: the scatter
             of their means is how well zero is known over an area like the fan. Stack and each half.
  fan        the smoothed green (Gaussian FAN_BLUR px) above FAN_K x the blank-sky pixel scatter of the same
             smoothing; the connected region that holds R Monocerotis, in the stack and in each half alone. Its reach
             from the star along north and east by the plate solution, its length along its own axis (the direction
             from the star to the region's flux centre), its width across that axis at 20, 40, 60 and 80% of the
             length, its area and summed light.
  profile    along the axis in a strip 24 px wide, bins of 6 px: stack and halves.
  structure  IS THERE ANYTHING INSIDE THE FAN? Band-pass (Gaussian 1.5 px minus Gaussian 6 px) of each half's green.
             Inside the fan, further than CORE_R px from the star and EDGE px inside the fan's edge: the correlation of
             the odd half with the even half, against the same on blank-sky boxes (stars masked). And every local
             extreme of the band-passed STACK there that stands above 5 x the half-difference noise is listed with its
             value in each half: a feature is called real only if both halves show it with the same sign above
             3 sigma of a half. A smooth fan has a bright spine and that is structure of a kind, so the list says where
             each feature is.
  colour     the fan's R : G : B in the camera's daylight white balance (summed over the region, the star's core
             left out), stack and halves, and the star's.
Looks for the eye go to the work folder (kept): halves_look.png (odd, even, stack; 240 px boxes at the stack's own
pixels, one linear scale), fan_region.png."""
import json, os
import numpy as np, cv2
from common import *

FAN_BLUR, FAN_K = 2.0, 4.0
CORE_R, EDGE = 14, 6
S6 = jload('step6_solve_ref.json'); S9 = jload('step9_solve.json'); S5 = jload('step5_select.json'); S8 = jload('step8_stack.json'); S10 = jload('step10_deliver.json'); S4 = jload('step4_quality.json')
c = S9['crop_on_reference_grid']; X0, Y0, X1, Y1 = c['x0'], c['y0'], c['x1'], c['y1']
SC = float(S9['pixscale_arcsec']); N = len(S5['used'])
rm = S9['r_monocerotis']; sx, sy = [float(v) for v in rm['pixel_in_the_stack']]
NORTH, EAST = np.array(S9['sky_axes']['north']), np.array(S9['sky_axes']['east'])
cover = np.load(W('stack_cover.npy'))[Y0:Y1, X0:X1]; OK = cover == N
wbd = np.array([S10['white_balance_daylight'][k] for k in 'RGB'])
hh, ww = OK.shape
yy, xx = np.mgrid[0:hh, 0:ww]
PL = S10['sky_plane_in_the_picture_only']


def chans(name):
    a = np.load(W(name), mmap_mode='r')[:, Y0:Y1, X0:X1].astype(np.float64)
    for p in range(4):
        a[p] -= PL[p]['a_dn'] + PL[p]['b_dn_per_px'] * (xx - ww / 2) + PL[p]['c_dn_per_px'] * (yy - hh / 2)
    return np.nan_to_num(np.stack([a[0], (a[1] + a[2]) / 2, a[3]])).astype(np.float32)


ST, OD, EV = chans('stack_mean.npy'), chans('stack_odd.npy'), chans('stack_even.npy')
G = {'stack': ST[1], 'odd': OD[1], 'even': EV[1]}
out = {}

# ---- the run: star brightness, star size, sky level, frame by frame (the dew question)
q = sorted(S4['quality'], key=lambda o: o['stamp']); used = {u['stamp'] for u in S5['used']}
RAWSKY = {f['stamp']: f['plane_median'] for f in jload('step1.json')['frames']}     # the RAW planes' own medians (black subtracted; the camera's RAW is stepped by 4 DN here), for every frame, used or not
rows = [dict(frame=o['stamp'], used=o['stamp'] in used, star_brightness=round(o['transparency'], 3), star_peak=round(o.get('peak_rel', float('nan')), 3) if o.get('peak_rel') is not None else None, star_size_arcsec=round(o['hfd_arcsec'], 2),
             smear=round(o['smear'], 3), green_sky_dn=round(float(np.mean(S8['constants'][o['stamp']][1:3])), 1) if o['stamp'] in S8['constants'] else None, raw_sky_dn=dict(R=RAWSKY[o['stamp']][0], G=0.5 * (RAWSKY[o['stamp']][1] + RAWSKY[o['stamp']][2]), B=RAWSKY[o['stamp']][3]), box_star_size_arcsec=o.get('box_star_size_arcsec')) for o in q]
T = np.array([r['star_brightness'] for r in rows]); H = np.array([r['star_size_arcsec'] for r in rows]); n3 = len(rows) // 3
clear = T >= 0.9
out['run'] = dict(frames=rows, what='star_brightness: the summed light of the same ~75 stars in each frame over the run\'s usual (1 = the median of the clear frames); star_size: their median half-flux diameter; green_sky: the constant taken off the used frames in step 8',
                  thirds=[dict(frames='%s .. %s' % (rows[a]['frame'][9:], rows[b - 1]['frame'][9:]), star_brightness_median=round(float(np.median(T[a:b])), 3), star_size_median_arcsec=round(float(np.median(H[a:b])), 2)) for a, b in ((0, n3), (n3, 2 * n3), (2 * n3, len(rows)))],
                  clear_frames=int(clear.sum()), dim_frames=[dict(frame=r['frame'], star_brightness=r['star_brightness'], star_size_arcsec=r['star_size_arcsec']) for r in rows if r['star_brightness'] < 0.9],
                  star_size_arcsec=dict(min=float(H.min()), median=float(np.median(H)), max=float(H.max()), of_clear_frames_first_half=float(np.median(H[:len(H) // 2])), of_the_dim_frames=float(np.median(H[~clear])) if (~clear).any() else None),
                  star_brightness_of_clear_frames=dict(first=float(T[clear][0]), last=float(T[clear][-1]), slope_per_10_min=float(np.polyfit(np.arange(len(T))[clear] * 41.5 / 600, T[clear], 1)[0])))
SKYG = np.array([r['raw_sky_dn']['G'] for r in rows])
out['run']['green_sky_dn'] = dict(clear_frames_median=float(np.median(SKYG[clear])), clear_frames_range=[float(SKYG[clear].min()), float(SKYG[clear].max())], dim_frames=SKYG[~clear].tolist(), dim_frames_median=float(np.median(SKYG[~clear])) if (~clear).any() else None,
                               what='the RAW green planes\' median: with the stars at half, the sky went UP; a brighter sky with dimmer stars is cloud (the skill), dew would dim both')
print('  green sky: clear frames %.0f (%.0f..%.0f), dim frames %s' % (np.median(SKYG[clear]), SKYG[clear].min(), SKYG[clear].max(), SKYG[~clear].tolist()))
print('the run: thirds', out['run']['thirds']); print('  dim frames', out['run']['dim_frames']); print('  clear-frame star brightness %.3f -> %.3f (slope %+.3f per 10 min)' % (T[clear][0], T[clear][-1], out['run']['star_brightness_of_clear_frames']['slope_per_10_min']))

# ---- stars (difference of Gaussians, which ignores the smooth fan), masked with a disc growing with brightness
dog = cv2.GaussianBlur(G['stack'], (0, 0), 1.5) - cv2.GaussianBlur(G['stack'], (0, 0), 6.0)
ds = 1.4826 * np.median(np.abs(dog[::5, ::5] - np.median(dog[::5, ::5])))
pk = (dog > 5 * ds) & (dog == cv2.dilate(dog, np.ones((9, 9), np.uint8)))
smask = np.zeros((hh, ww), np.uint8)
for y, x in zip(*np.nonzero(pk)):
    cv2.circle(smask, (int(x), int(y)), int(np.clip(6 + 5 * np.log10(dog[y, x] / (5 * ds)), 6, 40)), 1, -1)
STARS = smask.astype(bool)
omask = np.hypot(xx - sx, yy - sy) * SC < S6['mask_radius_arcmin'] * 60

# ---- the fan: smoothed green above FAN_K x the blank-sky scatter of the same smoothing
blank = OK & ~STARS & ~omask
fan = {}
for k in G:
    Gs = cv2.GaussianBlur(G[k], (0, 0), FAN_BLUR); sd = clipped_stats(Gs[blank][::11])[1]
    n, lab = cv2.connectedComponents((Gs > FAN_K * sd).astype(np.uint8)); reg = lab == lab[int(round(sy)), int(round(sx))]
    ys, xs = np.nonzero(reg); dx, dy = xs - sx, ys - sy; w_ = np.clip(Gs[reg], 0, None)
    core = np.hypot(dx, dy) <= CORE_R
    ax = np.array([(w_ * dx)[~core].sum(), (w_ * dy)[~core].sum()]); ax /= np.hypot(*ax); perp = np.array([-ax[1], ax[0]])
    along = dx * ax[0] + dy * ax[1]; across = dx * perp[0] + dy * perp[1]; L = float(np.percentile(along, 99.5))
    widths = {}
    for f in (0.2, 0.4, 0.6, 0.8):
        m = np.abs(along - f * L) < 3
        widths['at_%d_pct_of_the_length' % (100 * f)] = round(float((across[m].max() - across[m].min()) * SC), 1) if m.any() else None
    nN, nE = dx * NORTH[0] + dy * NORTH[1], dx * EAST[0] + dy * EAST[1]
    fan[k] = dict(threshold_dn=round(float(FAN_K * sd), 2), smoothed_pixel_scatter_dn=round(float(sd), 3), area_px=int(reg.sum()), area_sq_arcmin=round(float(reg.sum() * SC ** 2 / 3600), 2),
                  reach_from_the_star_arcsec=dict(north=round(float(nN.max() * SC), 1), south=round(float(-nN.min() * SC), 1), east=round(float(nE.max() * SC), 1), west=round(float(-nE.min() * SC), 1)),
                  axis_position_angle_deg_north_through_east=round(float(np.degrees(np.arctan2(ax @ EAST, ax @ NORTH)) % 360), 1), length_along_the_axis_arcsec=round(L * SC, 1), behind_the_star_arcsec=round(float(-np.percentile(along, 0.5) * SC), 1),
                  width_across_the_axis_arcsec=widths, widest_arcsec=round(float((across.max() - across.min()) * SC), 1),
                  green_sum_dn=round(float(G[k][reg].sum())), green_peak_outside_the_core_dn=round(float(Gs[reg][~core].max()), 1), stars_found_inside=int((pk & reg & (np.hypot(xx - sx, yy - sy) > CORE_R)).sum()))
    if k == 'stack': REG, AX, PERP, LEN, GS = reg, ax, perp, L, Gs
    print('fan (%s): above %.1f DN, %d px = %.2f sq arcmin; length %.0f" along PA %.0f deg, widest %.0f"; reach N %.0f" S %.0f" E %.0f" W %.0f"; widths %s' % (k, fan[k]['threshold_dn'], reg.sum(), fan[k]['area_sq_arcmin'], fan[k]['length_along_the_axis_arcsec'],
          fan[k]['axis_position_angle_deg_north_through_east'], fan[k]['widest_arcsec'], *[fan[k]['reach_from_the_star_arcsec'][d] for d in ('north', 'south', 'east', 'west')], list(widths.values())))
out['fan'] = dict(rule='green smoothed by a Gaussian of %.1f px, above %.0f x the scatter of the same on blank sky; the connected region that holds R Monocerotis' % (FAN_BLUR, FAN_K), **fan)

# ---- blank sky: boxes of the fan's area
side = int(np.sqrt(REG.sum())); sky = {k: [] for k in G}
for y in range(0, hh - side, side):
    for x in range(0, ww - side, side):
        b = blank[y:y + side, x:x + side]
        if b.mean() < 0.85: continue
        for k in G: sky[k].append(float(G[k][y:y + side, x:x + side][b].mean()))
out['sky'] = dict(box_px=side, boxes=len(sky['stack']), **{k: dict(mean_dn=round(float(np.mean(v)), 3), scatter_of_box_means_dn=round(float(np.std(v)), 3)) for k, v in sky.items()})
fm = {k: float(G[k][REG].mean()) for k in G}
out['fan']['mean_green_dn'] = {k: round(v, 2) for k, v in fm.items()}; out['fan']['over_blank_sky_scatter'] = {k: round(fm[k] / out['sky'][k]['scatter_of_box_means_dn'], 1) for k in G}
print('blank sky: %d boxes of %d px, scatter of means %.2f DN (stack); the fan\'s mean green %.1f DN = %.0f x that; odd %.1f, even %.1f' % (len(sky['stack']), side, out['sky']['stack']['scatter_of_box_means_dn'], fm['stack'], out['fan']['over_blank_sky_scatter']['stack'], fm['odd'], fm['even']))

# ---- R Monocerotis: star or knot?
def hfd(img, x, y, rmax=14):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - 30:yi + 31, xi - 30:xi + 31]; gy, gx = np.mgrid[-30:31, -30:31]; r = np.hypot(gx - (x - xi), gy - (y - yi))
    bg = np.median(t[(r > 20) & (r < 28)]); a = r <= rmax; o = np.argsort(r[a]); cum = np.cumsum((t - bg)[a][o])
    return float(2 * r[a][o][np.searchsorted(cum, cum[-1] / 2)])
out['r_mon'] = dict(**rm, half_flux_diameter_arcsec=round(hfd(G['stack'], sx, sy) * SC, 2), field_stars_half_flux_diameter_arcsec=round(S10['star_size']['hfd_stack_arcsec'], 2),
                    peak_green_dn_of_5x5=dict(stack=round(float(G['stack'][int(round(sy)) - 2:int(round(sy)) + 3, int(round(sx)) - 2:int(round(sx)) + 3].max()), 1), odd=round(float(G['odd'][int(round(sy)) - 2:int(round(sy)) + 3, int(round(sx)) - 2:int(round(sx)) + 3].max()), 1), even=round(float(G['even'][int(round(sy)) - 2:int(round(sy)) + 3, int(round(sx)) - 2:int(round(sx)) + 3].max()), 1)),
                    note='measured in an aperture of 14 px radius over a ring 20 to 28 px out, which holds fan light on one side: the diameter is an upper limit')
print('R Monocerotis: at (%.1f, %.1f) in the stack, %.1f" from the catalogue place; peak %.0f DN; half-flux diameter %.2f" against the field stars\' %.2f"' % (sx, sy, rm['from_the_catalogue_place_arcsec'], out['r_mon']['peak_green_dn_of_5x5']['stack'], out['r_mon']['half_flux_diameter_arcsec'], out['r_mon']['field_stars_half_flux_diameter_arcsec']))

# ---- profile along the axis
dxx, dyy = xx - sx, yy - sy; AL = dxx * AX[0] + dyy * AX[1]; AC = dxx * PERP[0] + dyy * PERP[1]
prof = []
for a in np.arange(-30, LEN + 42, 6):
    m = (AL >= a) & (AL < a + 6) & (np.abs(AC) <= 12)
    prof.append(dict(from_the_star_arcsec=round(float((a + 3) * SC), 1), stack=round(float(G['stack'][m].mean()), 1), odd=round(float(G['odd'][m].mean()), 1), even=round(float(G['even'][m].mean()), 1)))
out['profile_along_the_axis'] = dict(what='mean green (DN) in a strip 24 px wide along the fan\'s axis, bins of 6 px, from behind the star to beyond the fan\'s end', bins=prof)
print('along the axis (arcsec: stack odd even):', ' '.join('%.0f:%.0f/%.0f/%.0f' % (p['from_the_star_arcsec'], p['stack'], p['odd'], p['even']) for p in prof[::2]))

# ---- structure inside the fan: do the halves agree?
def bp(a): return cv2.GaussianBlur(a, (0, 0), 1.5) - cv2.GaussianBlur(a, (0, 0), 6.0)
Bs, Bo, Be = bp(G['stack']), bp(G['odd']), bp(G['even'])
inner = cv2.erode(REG.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * EDGE + 1, 2 * EDGE + 1))).astype(bool) & (np.hypot(dxx, dyy) > CORE_R)
half_noise = float(clipped_stats(((Bo - Be) / 2)[blank][::7])[1]); one_half = half_noise * 2 ** 0.5
r_in = float(np.corrcoef(Bo[inner], Be[inner])[0, 1]); r_sky = []
for y in range(0, hh - side, side):
    for x in range(0, ww - side, side):
        b = blank[y:y + side, x:x + side]
        if b.mean() < 0.85: continue
        r_sky.append(float(np.corrcoef(Bo[y:y + side, x:x + side][b], Be[y:y + side, x:x + side][b])[0, 1]))
ext = ((Bs == cv2.dilate(Bs, np.ones((7, 7), np.uint8))) | (Bs == cv2.erode(Bs, np.ones((7, 7), np.uint8)))) & inner & (np.abs(Bs) > 5 * half_noise)
feats = []
for y, x in zip(*np.nonzero(ext)):
    o_, e_ = float(Bo[y, x]), float(Be[y, x]); real = bool(np.sign(o_) == np.sign(e_) and min(abs(o_), abs(e_)) > 3 * one_half)
    feats.append(dict(kind='brighter' if Bs[y, x] > 0 else 'darker', from_the_star_arcsec=dict(north=round(float((dxx[y, x] * NORTH[0] + dyy[y, x] * NORTH[1]) * SC), 1), east=round(float((dxx[y, x] * EAST[0] + dyy[y, x] * EAST[1]) * SC), 1)),
                      along_the_axis_arcsec=round(float(AL[y, x] * SC), 1), across_the_axis_arcsec=round(float(AC[y, x] * SC), 1), pixel_in_the_stack=[int(x), int(y)],
                      band_passed_dn=dict(stack=round(float(Bs[y, x]), 2), odd=round(o_, 2), even=round(e_, 2)), in_both_halves=real))
feats.sort(key=lambda f: -abs(f['band_passed_dn']['stack']))
out['structure'] = dict(band='green, Gaussian 1.5 px minus Gaussian 6 px (detail of about 3 to 12 arcsec)', where='inside the fan, more than %d px from the star and %d px inside the fan\'s edge: %d px' % (CORE_R, EDGE, int(inner.sum())),
                        noise_of_the_stack_in_this_band_dn=round(half_noise, 3), noise_of_one_half_dn=round(one_half, 3), rms_inside_the_fan_dn=dict(stack=round(float(Bs[inner].std()), 3), half_difference=round(float(((Bo - Be) / 2)[inner].std()), 3)),
                        odd_even_correlation=dict(inside_the_fan=round(r_in, 3), blank_sky_boxes_mean=round(float(np.mean(r_sky)), 3), blank_sky_boxes_scatter=round(float(np.std(r_sky)), 3), boxes=len(r_sky)),
                        features=feats, features_in_both_halves=int(sum(f['in_both_halves'] for f in feats)),
                        caution='a smooth fan with a bright spine and a sharp edge passes this band too: the list says where each feature is; a feature on the axis near the star is the fan\'s own brightness gradient, not a knot')
print('structure: band-passed rms inside the fan %.2f DN against a half-difference of %.2f; odd-even correlation %.3f inside, %.3f +- %.3f on %d blank boxes; %d extremes above 5 sigma, %d in both halves' % (
    Bs[inner].std(), ((Bo - Be) / 2)[inner].std(), r_in, np.mean(r_sky), np.std(r_sky), len(r_sky), len(feats), out['structure']['features_in_both_halves']))
for f in feats[:8]: print('  ', f['kind'], 'N %+.0f" E %+.0f"' % (f['from_the_star_arcsec']['north'], f['from_the_star_arcsec']['east']), 'along %.0f" across %+.0f"' % (f['along_the_axis_arcsec'], f['across_the_axis_arcsec']), f['band_passed_dn'], 'BOTH HALVES' if f['in_both_halves'] else 'not in both')

# ---- colour
body = REG & (np.hypot(dxx, dyy) > CORE_R); corem = np.hypot(dxx, dyy) <= 5
def ratio(C, m):
    v = np.array([C[i][m].sum() * wbd[i] for i in range(3)]); return dict(red_over_green=round(float(v[0] / v[1]), 3), blue_over_green=round(float(v[2] / v[1]), 3))
out['colour'] = dict(what='sums in the camera\'s daylight white balance (white = 1, 1); before the colour matrix', fan=dict(stack=ratio(ST, body), odd=ratio(OD, body), even=ratio(EV, body)), r_monocerotis_core=dict(stack=ratio(ST, corem), odd=ratio(OD, corem), even=ratio(EV, corem)))
print('colour (daylight balance): fan', out['colour']['fan'], '| star core', out['colour']['r_monocerotis_core']['stack'])

# ---- looks (kept): the halves and the stack on one linear scale, at the stack's own pixels; the fan's region
cxl, cyl = int(sx + 0.45 * LEN * AX[0]), int(sy + 0.45 * LEN * AX[1])
def box(a): return np.clip((cv2.GaussianBlur(a, (0, 0), 1.0)[cyl - 120:cyl + 120, cxl - 120:cxl + 120] + 10) / 260, 0, 1) ** 0.5
cv2.imwrite(W('halves_look.png'), (np.hstack([box(G['odd']), np.ones((240, 4)), box(G['even']), np.ones((240, 4)), box(G['stack'])]) * 255).astype(np.uint8))
v = (box(G['stack']) * 255).astype(np.uint8); v = cv2.cvtColor(v, cv2.COLOR_GRAY2BGR); cnt, _ = cv2.findContours(REG[cyl - 120:cyl + 120, cxl - 120:cxl + 120].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
cv2.drawContours(v, cnt, -1, (0, 200, 255), 1); cv2.imwrite(W('fan_region.png'), v)
jdump(out, 'step11_measure.json')
