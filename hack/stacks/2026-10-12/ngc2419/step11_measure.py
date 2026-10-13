"""Step 11: what is seen of NGC 2419, and is each thing real? Numbers only; no pixel of the picture is changed here.
The tests are those of tonight's hack/stacks/2026-10-12/m78 and ngc2261 step 11 (half stacks of the odd and the even
frames; the same measure laid on blank sky), asked of a small round haze of unresolved stars.

All on the well-covered rectangle of step 9, raw camera units (DN of the 14-bit RAW per 15 s frame through a clear
sky), colours R, G = mean of G1 and G2, B. The sky is the stack's own zero (one constant per colour per frame over the
sky region, step 8) less the picture's sky plane (step 10), so the numbers describe the picture that is shown.

  run        star brightness (against the clear level of step 5), star size and the RAW sky level, frame by frame.
  centre     the haze's own flux centre (green smoothed 6 px, within 60 px of the catalogue place, above half its
             peak) against the catalogue place.
  profile    the MEDIAN green in rings RING px wide about the catalogue place (a median, so a foreground star in a
             ring does not count), in the stack and in the odd and the even half stacks alone, and red and blue.
  sky        the same rings laid on every blank-sky place of a grid (outside the object mask, fully covered): the
             scatter of each ring's median over those places is how well zero is known for that ring. The haze's
             WIDTH ABOVE THE SKY is twice the radius out to which every ring stands above K_RING x that scatter;
             given for the stack and for each half with its own scatter.
  glare      the two bright stars clip and spread light. Star A's glare is measured on its far side (a 120 degree
             sector pointing away from the cluster), at the distances at which the cluster lies on its near side.
  points     ARE ANY OF ITS STARS RESOLVED? Band-pass (Gaussian 1.5 px minus Gaussian 6 px) of the green. Every local
             maximum of the band-passed STACK inside the haze (the smooth round haze's own share of that band taken off
             first) that stands above K_PT x the stack's noise in that band
             there (from the half difference inside the haze) is listed with its value in each half; it REPEATS only if
             both halves show a local maximum within 1.5 px of it above 3 x a half's noise. The same count on blank-sky
             discs of the same size says how many repeating points the field's own stars give by chance: only an excess
             over that belongs to the cluster. And the odd-even correlation of the band-passed haze against blank sky:
             grain that repeats is real light (clumps of unresolved stars), which is not the same as resolved stars.
  colour     the haze's R : G : B in the camera's daylight white balance within COL_R px (ring medians x ring areas),
             stack and halves, with the error a sky-zero error of one blank-sky scatter makes, beside the field stars'.
Looks for the eye go to the work folder (kept): halves_look.png (odd, even, stack; 360 px boxes at the stack's own
pixels, one linear scale), points_look.png (the stack's box with the repeating points ringed)."""
import json, os
import numpy as np, cv2
from common import *

RING, RMAX, RBLANK, K_RING, K_PT, COL_R = 8, 352, 160, 3.0, 4.0, 80
S1 = jload('step1.json'); S4 = jload('step4_quality.json'); S5 = jload('step5_select.json'); S6 = jload('step6_solve_ref.json'); S8 = jload('step8_stack.json'); S9 = jload('step9_solve.json'); S10 = jload('step10_deliver.json')
c = S9['crop_on_reference_grid']; X0, Y0, X1, Y1 = c['x0'], c['y0'], c['x1'], c['y1']
SC = float(S9['pixscale_arcsec']); N = len(S5['used'])
CX, CY = [float(v) for v in S9['catalogue'][TARGET['name']]['pixel']]
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

# ---- the run, frame by frame
used = {u['stamp'] for u in S5['used']}; TR = S5['transparency']; RAWSKY = {f['stamp']: f['plane_median'] for f in S1['frames']}
rows = [dict(frame=o['stamp'], used=o['stamp'] in used, star_brightness_of_clear=round(TR[o['stamp']], 3), star_size_arcsec=round(o['hfd_arcsec'], 2), smear=round(o['smear'], 3),
             raw_sky_dn=dict(R=RAWSKY[o['stamp']][0], G=0.5 * (RAWSKY[o['stamp']][1] + RAWSKY[o['stamp']][2]), B=RAWSKY[o['stamp']][3]), box_star_size_arcsec=o.get('box_star_size_arcsec')) for o in sorted(S4['quality'], key=lambda o: o['stamp'])]
T = np.array([r['star_brightness_of_clear'] for r in rows]); H = np.array([r['star_size_arcsec'] for r in rows]); SKYG = np.array([r['raw_sky_dn']['G'] for r in rows]); clear = T >= 0.95
out['run'] = dict(what='star_brightness_of_clear: the summed light of the same 41 stars in each frame over the clear level (step 5: the median of the upper half of the frames); star size: their median half-flux diameter; raw sky: the RAW green planes\' median (the RAW is stepped by 4 DN at this level)',
                  frames=rows, clear_frames=int(clear.sum()), clear_from_to=[rows[int(np.nonzero(clear)[0][0])]['frame'], rows[int(np.nonzero(clear)[0][-1])]['frame']], clear_frames_brightness_range=[float(T[clear].min()), float(T[clear].max())],
                  frames_before_the_clear_stretch=[r['star_brightness_of_clear'] for r in rows[:int(np.nonzero(clear)[0][0])]], frames_after_it=[r['star_brightness_of_clear'] for r in rows[int(np.nonzero(clear)[0][-1]) + 1:]],
                  star_size_arcsec=dict(min=float(H.min()), median=float(np.median(H)), max=float(H.max()), of_used_frames_median=float(np.median([r['star_size_arcsec'] for r in rows if r['used']]))),
                  raw_green_sky_dn=dict(clear_frames_median=float(np.median(SKYG[clear])), frames_under_half_brightness_median=float(np.median(SKYG[T < 0.5])) if (T < 0.5).any() else None))
print('the run: %d frames at the clear level (%.3f..%.3f), %s to %s; before: %s; after: %s' % (clear.sum(), T[clear].min(), T[clear].max(), *[s[9:] for s in out['run']['clear_from_to']], out['run']['frames_before_the_clear_stretch'], out['run']['frames_after_it']))
print('  star size %.2f..%.2f arcsec, median %.2f; RAW green sky %.0f DN clear, %s under half brightness' % (H.min(), H.max(), np.median(H), np.median(SKYG[clear]), out['run']['raw_green_sky_dn']['frames_under_half_brightness_median']))

# ---- geometry: the object mask on the stack, ring labels
objects = [(CX, CY, S6['mask_radius_arcmin'] * 60 / SC)] + [(e['centre_px'][0] - X0, e['centre_px'][1] - Y0, e['radius_px']) for e in S6['extra_masks']]
omask = np.zeros((hh, ww), bool)
for ox, oy, r_ in objects: omask |= np.hypot(xx - ox, yy - oy) <= r_


def ring_labels(R):
    gy, gx = np.mgrid[-R:R + 1, -R:R + 1]; r = np.hypot(gx, gy); lab = (r // RING).astype(int); lab[r >= R] = -1
    return lab, r


def profile(img, cx, cy, R, lab):
    t = img[cy - R:cy + R + 1, cx - R:cx + R + 1]
    return np.array([float(np.median(t[lab == k])) for k in range(R // RING)])


icx, icy = int(round(CX)), int(round(CY))
LAB, RR = ring_labels(RMAX); LABB, _ = ring_labels(RBLANK)
nring = RMAX // RING; mid = (np.arange(nring) + 0.5) * RING; area = np.array([(LAB == k).sum() for k in range(nring)])
places = [(x, y) for y in range(RBLANK + 8, hh - RBLANK - 8, 180) for x in range(RBLANK + 8, ww - RBLANK - 8, 180)
          if OK[y - RBLANK:y + RBLANK + 1, x - RBLANK:x + RBLANK + 1].all() and all(np.hypot(x - ox, y - oy) > r_ + RBLANK for ox, oy, r_ in objects)]
C3 = dict(stack=ST, odd=OD, even=EV)
prof = {k: profile(G[k], icx, icy, RMAX, LAB) for k in G}
profRB = {k: dict(R=profile(C3[k][0], icx, icy, RMAX, LAB), B=profile(C3[k][2], icx, icy, RMAX, LAB)) for k in C3}
blank = {k: np.array([profile(G[k], x, y, RBLANK, LABB) for x, y in places]) for k in G}
blankRB = {ch: np.array([profile(ST[i], x, y, RBLANK, LABB) for x, y in places]) for ch, i in (('R', 0), ('B', 2))}
nb = RBLANK // RING


def ring_sigma(b):                     # per ring: scatter of that ring's median over the blank places; beyond the blank discs, the outermost ring's (larger rings can only be better)
    s = b.std(0); return np.concatenate([s, np.full(nring - nb, s[-1])])


sig = {k: ring_sigma(blank[k]) for k in G}; bmean = {k: float(blank[k].mean()) for k in G}
ext = {}
for k in G:
    above = prof[k] > K_RING * sig[k]; n_ = int(np.argmin(above)) if not above.all() else nring
    half = float(mid[int(np.argmax(prof[k] < 0.5 * prof[k][0]))])
    ext[k] = dict(central_ring_median_dn=round(float(prof[k][0]), 2), falls_to_half_at_radius_arcsec=round(half * SC, 1), above_the_sky_out_to_radius_arcsec=round(n_ * RING * SC, 1), width_above_the_sky_arcmin=round(2 * n_ * RING * SC / 60, 2),
                  rings_above=n_, blank_sky_mean_of_ring_medians_dn=round(bmean[k], 3), ring_scatter_dn_at_30_60_120_arcsec=[round(float(sig[k][int(a / SC / RING)]), 3) for a in (30, 60, 120)])
    print('haze (%s): centre %.1f DN, half at %.0f", above %.0f x the blank-sky ring scatter out to %.0f" radius = %.2f arcmin wide' % (k, prof[k][0], half * SC, K_RING, n_ * RING * SC, ext[k]['width_above_the_sky_arcmin']))
nmin = min(ext[k]['rings_above'] for k in G); RDET = nmin * RING
# the same against the LOCAL sky: the rings 100 to 180 arcsec out (beyond the haze, inside star A's distance) read below the stack's zero
LOC = (mid * SC >= 100) & (mid * SC < 180); loc = {}
for k in G:
    z = float(np.median(prof[k][LOC])); above = (prof[k] - z) > K_RING * sig[k]; n_ = int(np.argmin(above))
    loc[k] = dict(local_sky_dn=round(z, 2), above_it_out_to_radius_arcsec=round(n_ * RING * SC, 1), width_arcmin=round(2 * n_ * RING * SC / 60, 2), central_ring_above_it_dn=round(float(prof[k][0] - z), 2))
    print('  against the local sky (%s): rings 100-180" read %+.2f DN; above that out to %.0f" = %.2f arcmin wide' % (k, z, n_ * RING * SC, loc[k]['width_arcmin']))
out['haze'] = dict(rule='median green in rings %d px (%.1f arcsec) wide about the catalogue place; above the sky = every ring out to there stands above %.0f x the scatter of the same ring\'s median over %d blank-sky places' % (RING, RING * SC, K_RING, len(places)),
                   blank_sky_places=len(places), **ext, against_the_local_sky=dict(what='the stack\'s zero is the mean of the sky region over the whole field; round the cluster the rings from 100 to 180 arcsec read a little below it (the night\'s flat is known to be about 1% high in the middle of the sensor). Taking those rings as the sky instead:', **loc), in_the_stack_and_in_both_halves=dict(radius_arcsec=round(RDET * SC, 1), width_arcmin=round(2 * RDET * SC / 60, 2)),
                   profile=[dict(radius_arcsec=round(float(mid[i] * SC), 1), stack=round(float(prof['stack'][i]), 2), odd=round(float(prof['odd'][i]), 2), even=round(float(prof['even'][i]), 2), red=round(float(profRB['stack']['R'][i]), 2), blue=round(float(profRB['stack']['B'][i]), 2),
                                 ring_scatter_dn=round(float(sig['stack'][i]), 3), sigma=round(float(prof['stack'][i] / sig['stack'][i]), 1)) for i in range(nring)])
print('profile (arcsec: stack/odd/even DN, sigma):', ' '.join('%.0f:%.1f/%.1f/%.1f(%.0f)' % (p['radius_arcsec'], p['stack'], p['odd'], p['even'], p['sigma']) for p in out['haze']['profile'][:30:2]))
# the haze's summed light (ring medians x areas) inside the detected radius, and the radius that holds half of it
cum = np.cumsum((prof['stack'] * area)[:nmin]); out['haze']['green_sum_inside_dn'] = round(float(cum[-1])); out['haze']['half_light_radius_arcsec'] = round(float(mid[int(np.searchsorted(cum, cum[-1] / 2))] * SC), 1)

# ---- the haze's own centre
Gs = cv2.GaussianBlur(G['stack'], (0, 0), 6.0); m = (np.hypot(xx - CX, yy - CY) <= 60) & (Gs > 0.5 * Gs[icy, icx])
fx, fy = float((Gs[m] * xx[m]).sum() / Gs[m].sum()), float((Gs[m] * yy[m]).sum() / Gs[m].sum()); d = np.array([fx - CX, fy - CY])
out['centre'] = dict(catalogue_place_px=[round(CX, 1), round(CY, 1)], flux_centre_px=[round(fx, 1), round(fy, 1)], flux_centre_from_catalogue_arcsec=dict(total=round(float(np.hypot(*d) * SC), 1), north=round(float(d @ NORTH * SC), 1), east=round(float(d @ EAST * SC), 1)),
                     smoothed_green_peak_dn=round(float(Gs[m].max()), 1))
print('centre: flux centre %.1f" from the catalogue place (N %+.1f", E %+.1f"); smoothed peak %.1f DN' % (out['centre']['flux_centre_from_catalogue_arcsec']['total'], d @ NORTH * SC, d @ EAST * SC, Gs[m].max()))

# ---- glare of bright star A on its far side
ax_, ay_ = objects[1][0], objects[1][1]; away = np.array([ax_ - CX, ay_ - CY]); dist = float(np.hypot(*away)); away /= dist
dxa, dya = xx - ax_, yy - ay_; ra = np.hypot(dxa, dya); cosang = (dxa * away[0] + dya * away[1]) / np.maximum(ra, 1e-6)
gl = []
for r0 in range(48, int(dist) + 96, 24):
    s_ = (ra >= r0) & (ra < r0 + 24) & (cosang > 0.5) & OK
    if s_.sum() > 200: gl.append(dict(from_star_a_arcsec=round((r0 + 12) * SC, 1), median_green_dn=round(float(np.median(G['stack'][s_])), 2), odd=round(float(np.median(G['odd'][s_])), 2), even=round(float(np.median(G['even'][s_])), 2)))
near = [g for g in gl if abs(g['from_star_a_arcsec'] - dist * SC) <= 40]
out['glare'] = dict(what='median green in a 120 degree sector on the far side of bright star A (pointing away from the cluster), 24 px steps: what the star\'s spread light is at a given distance, where there is no cluster', star_a_from_the_cluster_arcsec=round(dist * SC, 1), far_side=gl,
                    at_the_clusters_distance_dn=round(float(np.mean([g['median_green_dn'] for g in near])), 2) if near else None,
                    at_the_hazes_near_edge_dn=[g for g in gl if g['from_star_a_arcsec'] >= dist * SC - RDET * SC][:1])
print('glare of star A on its far side (arcsec: DN):', ' '.join('%.0f:%.1f' % (g['from_star_a_arcsec'], g['median_green_dn']) for g in gl), '| at the cluster\'s distance (%.0f"): %s DN' % (dist * SC, out['glare']['at_the_clusters_distance_dn']))

# ---- points: is any star resolved?
def bp(a): return cv2.GaussianBlur(a, (0, 0), 1.5) - cv2.GaussianBlur(a, (0, 0), 6.0)
# the smooth haze passes this band a little by itself (its curvature at the centre), which would let noise through the
# limits more easily there than on blank sky: a round model of the haze (the stack's ring medians, interpolated over
# radius) goes through the same band-pass and is taken off all three before anything is counted
model = np.zeros((hh, ww), np.float32)
model[icy - RMAX:icy + RMAX + 1, icx - RMAX:icx + RMAX + 1] = np.where(RR < RMAX, np.interp(RR, np.concatenate([[0.0], mid]), np.concatenate([[prof['stack'][0]], prof['stack']])), 0).astype(np.float32)
Mb = bp(model)
Bs, Bo, Be = bp(G['stack']) - Mb, bp(G['odd']) - Mb, bp(G['even']) - Mb
k7 = np.ones((7, 7), np.uint8); mx = {k: (b == cv2.dilate(b, k7)) for k, b in (('s', Bs), ('o', Bo), ('e', Be))}
RPT = max(RDET, 40)


def points(cx, cy):
    """Local maxima of the band-passed stack within RPT px of (cx, cy) above K_PT x the stack's band noise there (the
    half difference in that disc), each with its value in the halves and whether both halves have their own local
    maximum within 1.5 px above 3 x a half's noise."""
    disc = np.hypot(xx - cx, yy - cy) <= RPT
    ns = float(clipped_stats(((Bo - Be) / 2)[disc])[1]); nh = ns * 2 ** 0.5; res = []
    for y, x in zip(*np.nonzero(mx['s'] & disc & (Bs > K_PT * ns))):
        rep = True; hv = {}
        for key, B in (('o', Bo), ('e', Be)):
            sl = (slice(max(y - 2, 0), y + 3), slice(max(x - 2, 0), x + 3)); gy, gx = np.nonzero(mx[key][sl] & (B[sl] > 3 * nh))
            okk = [(float(B[sl][a, b])) for a, b in zip(gy, gx) if np.hypot(a - (y - sl[0].start), b - (x - sl[1].start)) <= 1.5]
            hv[key] = float(B[y, x]); rep &= bool(okk)
        res.append(dict(x=int(x), y=int(y), stack=float(Bs[y, x]), odd=hv['o'], even=hv['e'], repeats=rep, sigma=float(Bs[y, x] / ns)))
    return res, ns, disc


pts, ns_in, DISC = points(CX, CY)
bl_counts = []; bl_r = []
for x, y in places:
    p_, _, d_ = points(x, y); bl_counts.append(sum(q['repeats'] for q in p_)); bl_r.append(float(np.corrcoef(Bo[d_], Be[d_])[0, 1]))
rep = sorted([p for p in pts if p['repeats']], key=lambda p: -p['stack'])
for p in pts:
    dd = np.array([p['x'] - CX, p['y'] - CY]); p.update(from_the_centre_arcsec=round(float(np.hypot(*dd) * SC), 1), north_arcsec=round(float(dd @ NORTH * SC), 1), east_arcsec=round(float(dd @ EAST * SC), 1), pixel_in_the_stack=[p.pop('x'), p.pop('y')],
                                                    band_passed_dn=dict(stack=round(p.pop('stack'), 2), odd=round(p.pop('odd'), 2), even=round(p.pop('even'), 2)), sigma=round(p['sigma'], 1))
r_in = float(np.corrcoef(Bo[DISC], Be[DISC])[0, 1]); bm, bs = float(np.mean(bl_counts)), float(np.std(bl_counts))
out['points'] = dict(band='green, Gaussian 1.5 px minus Gaussian 6 px (things about 3 to 12 arcsec across: a star here is 5 arcsec)', where='within %.0f arcsec of the catalogue place (the haze\'s measured radius)' % (RPT * SC),
                     noise_of_the_stack_in_this_band_inside_dn=round(ns_in, 3), smooth_haze_taken_out_first=dict(what='the band-pass of a round model of the haze (the ring medians of the stack), subtracted from the stack and both halves before counting, so that the limits mean the same inside the haze as on blank sky', largest_dn=round(float(Mb.max()), 2)), candidates=len(pts), candidate_threshold_sigma=K_PT, repeating_in_both_halves=len(rep), the_points=sorted(pts, key=lambda p: -p['sigma']),
                     blank_sky=dict(places=len(places), repeating_points_per_disc_mean=round(bm, 2), scatter=round(bs, 2), most=int(max(bl_counts)), what='the same count on blank-sky discs of the same size: the field\'s own faint stars'),
                     excess_over_the_field=round(len(rep) - bm, 1), excess_sigma=round((len(rep) - bm) / max(bs, np.sqrt(max(bm, 1))), 1),
                     odd_even_correlation=dict(inside_the_haze=round(r_in, 3), blank_sky_mean=round(float(np.mean(bl_r)), 3), blank_sky_scatter=round(float(np.std(bl_r)), 3), sigma=round((r_in - float(np.mean(bl_r))) / float(np.std(bl_r)), 1),
                                               caution='a round haze with a peak passes this band a little by itself (its curvature at the centre), and so do clumps of unresolved stars: a correlation above the blank sky says the grain is real light, not that stars are resolved'))
print('points: %d local maxima above %.0f sigma within %.0f" of the centre, %d repeat in both halves; blank-sky discs of the same size hold %.2f +- %.2f (most %d): excess %.1f (%.1f sigma)' % (len(pts), K_PT, RPT * SC, len(rep), bm, bs, max(bl_counts), len(rep) - bm, out['points']['excess_sigma']))
for p in sorted(pts, key=lambda p: -p['sigma'])[:14]: print('   %5.1f" from the centre (N %+6.1f, E %+6.1f)  %s  %.1f sigma  %s' % (p['from_the_centre_arcsec'], p['north_arcsec'], p['east_arcsec'], p['band_passed_dn'], p['sigma'], 'REPEATS' if p['repeats'] else 'not in both'))
print('  odd-even correlation of the band-passed green: %.3f inside the haze, %.3f +- %.3f on blank sky (%.1f sigma)' % (r_in, np.mean(bl_r), np.std(bl_r), out['points']['odd_even_correlation']['sigma']))

# ---- colour
ncol = COL_R // RING
def colsum(C): return np.array([float((profile(C[i], icx, icy, RMAX, LAB)[:ncol] * area[:ncol]).sum()) * wbd[i] for i in range(3)])
blank3 = np.array([[float((profile(ST[i], x, y, RBLANK, LABB)[:ncol] * area[:ncol]).sum()) * wbd[i] for i in range(3)] for x, y in places]); zerr = blank3.std(0)
col = {}
for k in C3:
    v = colsum(C3[k]); col[k] = dict(red_over_green=round(float(v[0] / v[1]), 3), blue_over_green=round(float(v[2] / v[1]), 3))
v = colsum(ST); err = dict(red_over_green=round(float(np.hypot(zerr[0] / v[1], v[0] * zerr[1] / v[1] ** 2)), 3), blue_over_green=round(float(np.hypot(zerr[2] / v[1], v[2] * zerr[1] / v[1] ** 2)), 3))
stars = [s for s in json.load(open(W('step2_stars.json'))) if s['stamp'] == REF_STAMP][0]['stars']; fs = []
for s in stars:
    x, y = int(round(s['x'] - X0)), int(round(s['y'] - Y0))
    if s['saturated'] or s['nearest'] <= 40 or s['flux'] < 20000 or not (24 <= x < ww - 24 and 24 <= y < hh - 24) or np.hypot(x - CX, y - CY) < RPT: continue
    gy, gx = np.mgrid[-22:23, -22:23]; r = np.hypot(gx, gy); f = []
    for i in range(3):
        t = ST[i][y - 22:y + 23, x - 22:x + 23]; f.append(float((t[r <= 9] - np.median(t[(r > 15) & (r <= 22)])).sum()) * wbd[i])
    if f[1] > 0: fs.append((f[0] / f[1], f[2] / f[1]))
fs = np.array(fs)
out['colour'] = dict(what='in the camera\'s daylight white balance (white = 1 : 1 : 1), before the colour matrix; the haze within %.0f arcsec of the centre, ring medians x ring areas' % (COL_R * SC), haze=col, error_from_the_sky_zero=err,
                     field_stars=dict(stars=len(fs), red_over_green_median=round(float(np.median(fs[:, 0])), 3), blue_over_green_median=round(float(np.median(fs[:, 1])), 3), red_over_green_quartiles=[round(float(v_), 3) for v_ in np.percentile(fs[:, 0], [25, 75])], blue_over_green_quartiles=[round(float(v_), 3) for v_ in np.percentile(fs[:, 1], [25, 75])]))
print('colour (daylight balance): haze', col, '+-', err, '| field stars (%d): R/G %.3f, B/G %.3f' % (len(fs), np.median(fs[:, 0]), np.median(fs[:, 1])))

# ---- looks (kept)
B_ = 180
def box(a): return np.clip((cv2.GaussianBlur(a, (0, 0), 1.0)[icy - B_:icy + B_, icx - B_:icx + B_] + 6) / (1.3 * prof['stack'][0] + 6), 0, 1) ** 0.6
cv2.imwrite(W('halves_look.png'), (np.hstack([box(G['odd']), np.ones((2 * B_, 4)), box(G['even']), np.ones((2 * B_, 4)), box(G['stack'])]) * 255).astype(np.uint8))
v = cv2.cvtColor((box(G['stack']) * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
v = cv2.resize(v, None, fx=1, fy=1)
for p in pts: cv2.circle(v, (p['pixel_in_the_stack'][0] - icx + B_, p['pixel_in_the_stack'][1] - icy + B_), 7, (0, 200, 255) if p['repeats'] else (120, 120, 120), 1)
cv2.circle(v, (B_, B_), int(RPT), (255, 160, 0), 1)
cv2.imwrite(W('points_look.png'), v)
jdump(out, 'step11_measure.json')
