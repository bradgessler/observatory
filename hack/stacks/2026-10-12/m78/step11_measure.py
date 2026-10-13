"""Step 11: what is seen of M78, how far does it reach, is it blue, and is each of those real? Numbers only; no pixel of
the picture is changed here. The tests are those of tonight's hack/stacks/2026-10-12/m1/step11_measure.py (half stacks
of the odd and the even frames; the same aperture laid on blank sky), asked of a reflection nebula.

All on the well-covered rectangle of step 9, raw camera units (DN of the 14-bit RAW per 15 s frame), colours R,
G = mean of G1 and G2, B. The sky is the stack's own zero (one constant per colour per frame over the sky region,
step 8) less the picture's sky plane (step 10: a + b x + c y per colour plane, fitted outside the object mask), so the
numbers describe the picture that is shown.

  stars      compact sources found on a difference of Gaussians (sigma 1.5 minus sigma 6 px, which ignores the smooth
             nebula) above 5 sigma, masked with a circle growing with brightness.
  sky        blank-sky places: a circle of AP px radius laid on a grid wherever it lies wholly outside the object mask
             (M78's 7 arcmin circle, NGC 2071's, NGC 2064's) and inside the full coverage, stars masked. The scatter of
             their means is how well the sky's zero is known over an area of that size, with what the flat, the dust
             and faint stars left in it. Done for the stack and for each half.
  profile    rings of 20 px about M78's catalogue place out to the frame's edge (stars and the other nebulae masked),
             per colour, stack and halves: where the glow falls to half its central level, where it is last above the
             blank-sky scatter in the stack AND in both halves, and what level the sky just outside the 7 arcmin
             circle has (it should be zero; if the flat reads high in the middle of the sensor it is below zero).
  extent     the smoothed green (Gaussian 8 px, stars masked, normalised) above 4 x the blank-sky scatter of the same
             smoothing, in the stack and in both halves alone; the connected region that holds the two stars; its
             size along north-south and east-west by the plate solution.
  glow       mean green within 1.5 arcmin of the midpoint of the two stars, against blank sky.
  lane       the dark lane: a strip 120 px wide from the midpoint of the two stars through the catalogue place of
             NGC 2067 and beyond (that is towards the north-west, across the lane), in bins of 10 px, stars masked:
             the bright body, the minimum, the second rise (NGC 2067, the far bank of the lane), the sky. The lane is
             real if the minimum lies between two rises in the stack and in both halves, and the far bank stands above
             the minimum by many times the blank-sky scatter of a bin-sized patch.
  others     NGC 2071, NGC 2064, NGC 2067: mean green within OTHER_R px of the catalogue place against blank sky.
  colour     IS THE BLUE MEASURED? The nebula's R : G : B in the camera's daylight white balance (the picture's own
             colour scale, before the matrix), in bands of the smoothed green, stack and halves, with the error a
             sky-zero mistake of 1 blank-sky scatter would make; against the same ratios for the field's stars
             (aperture sums on the stack's planes) and for the two stars that light the nebula. A reflection nebula
             is bluer than the star whose light it scatters.
  structure  band-passed halves correlated inside the nebula against the same on blank sky (as for M1).
Looks for the eye go to the work folder (kept): halves_look.png (odd, even, stack; smoothed 3 px)."""
import os
import numpy as np, cv2
from common import *

AP = 100                  # px, blank-sky aperture radius (1.3 arcmin)
OTHER_R = 115             # px, 1.5 arcmin
NEB_R = 300               # px (3.9 arcmin): the nebula for the structure test
S6 = jload('step6_solve_ref.json'); S9 = jload('step9_solve.json'); S5 = jload('step5_select.json'); S8 = jload('step8_stack.json'); S10 = jload('step10_deliver.json')
c = S9['crop_on_reference_grid']; X0, Y0, X1, Y1 = c['x0'], c['y0'], c['x1'], c['y1']
SC = float(S9['pixscale_arcsec']); N = len(S5['used'])
cx, cy = S9['catalogue'][TARGET['name']]['pixel']
NORTH, EAST = np.array(S9['sky_axes']['north']), np.array(S9['sky_axes']['east'])
cover = np.load(W('stack_cover.npy'))[Y0:Y1, X0:X1]; OK = cover == N
wbd = np.array([S10['white_balance_daylight'][k] for k in 'RGB'])
hh, ww = OK.shape
yy, xx = np.mgrid[0:hh, 0:ww]; RR = np.hypot(xx - cx, yy - cy)
PL = S10['sky_plane_in_the_picture_only']


def chans(name):
    a = np.load(W(name), mmap_mode='r')[:, Y0:Y1, X0:X1].astype(np.float64)
    for p in range(4):
        a[p] -= PL[p]['a_dn'] + PL[p]['b_dn_per_px'] * (xx - ww / 2) + PL[p]['c_dn_per_px'] * (yy - hh / 2)
    return np.nan_to_num(np.stack([a[0], (a[1] + a[2]) / 2, a[3]]))


ST, ODD, EVEN = chans('stack_mean.npy'), chans('stack_odd.npy'), chans('stack_even.npy')
SETS = (('stack', ST), ('odd', ODD), ('even', EVEN))

# ---- the object mask on this rectangle
MASK_R = S6['mask_radius_arcmin'] * 60 / SC
OBJ = RR <= MASK_R; others = {}
for name, v in S9['catalogue'].items():
    if name == TARGET['name']: continue
    others[name] = v['pixel']
for e in S6['extra_masks']:
    ox, oy = others[e['name']]; OBJ |= np.hypot(xx - ox, yy - oy) <= e['radius_px']

# ---- stars (difference of Gaussians on the stack's green)
G = np.where(OK, ST[1], 0).astype(np.float32)
dog = cv2.GaussianBlur(G, (0, 0), 1.5) - cv2.GaussianBlur(G, (0, 0), 6.0)
_, sd_dog, _ = clipped_stats(dog[OK & ~OBJ][::5])
nl, lab, stats, cent = cv2.connectedComponentsWithStats(((dog > 5 * sd_dog) & OK).astype(np.uint8), connectivity=8)
smask = np.zeros((hh, ww), np.uint8); star_list = []
pk_all = np.zeros(nl); np.maximum.at(pk_all, lab.ravel(), dog.ravel())
for i in range(1, nl):
    a = stats[i, cv2.CC_STAT_AREA]
    if a < 3: continue
    pk = float(pk_all[i]); r = int(round(4 + 2.5 * np.sqrt(a) + 2 * np.log10(max(pk / sd_dog, 1))))
    cv2.circle(smask, (int(round(cent[i][0])), int(round(cent[i][1]))), r, 1, -1)
    star_list.append((float(cent[i][0]), float(cent[i][1]), pk / sd_dog, int(a), r))
FREE = OK & (smask == 0)
print('stars masked: %d; free pixels %.0f%%; within %d px of M78 %.0f%% free' % (len(star_list), 100 * FREE.mean(), NEB_R, 100 * FREE[RR < NEB_R].mean()))


def msmooth(A, sig, m=None):
    m = FREE if m is None else m
    return cv2.GaussianBlur(np.where(m, A, 0).astype(np.float32), (0, 0), sig) / np.maximum(cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig), 1e-3)


# ---- blank-sky places
def places(rad, step=None):
    step = step or rad; t = np.hypot(*np.mgrid[-rad:rad + 1, -rad:rad + 1]) <= rad; out = []
    for py in range(rad + 1, hh - rad - 1, step):
        for px in range(rad + 1, ww - rad - 1, step):
            sl = (slice(py - rad, py + rad + 1), slice(px - rad, px + rad + 1))
            if OBJ[sl][t].any() or not OK[sl][t].all() or (FREE[sl] & t).sum() < 0.6 * t.sum(): continue
            out.append((px, py))
    return out, t


def disc_mean(A, px, py, rad, t):
    sl = (slice(py - rad, py + rad + 1), slice(px - rad, px + rad + 1)); m = FREE[sl] & t
    return [float(A[k][sl][m].mean()) for k in range(3)]


PLC, T_AP = places(AP)
blank = {n: np.array([disc_mean(A, px, py, AP, T_AP) for px, py in PLC]) for n, A in SETS}
sky = {n: dict(places=len(PLC), aperture_radius_px=AP, mean_dn=dict(zip('RGB', blank[n].mean(0).round(3).tolist())), scatter_dn=dict(zip('RGB', blank[n].std(0, ddof=1).round(3).tolist()))) for n in blank}
SKY_SD = blank['stack'].std(0, ddof=1)          # R, G, B: how well the zero is known over an AP-sized patch
print('blank sky, %d places of %d px radius: mean (R G B) %s, scatter %s DN; odd %s even %s' % (len(PLC), AP, blank['stack'].mean(0).round(2).tolist(), SKY_SD.round(2).tolist(), blank['odd'].std(0, ddof=1).round(2).tolist(), blank['even'].std(0, ddof=1).round(2).tolist()))
pix_noise = {n: [clipped_stats(A[k][FREE & ~OBJ][::3])[1] for k in range(3)] for n, A in SETS}
pix_noise['half_difference'] = [clipped_stats(((ODD[k] - EVEN[k]) / 2)[FREE & ~OBJ][::3])[1] for k in range(3)]
print('noise per px (R, G, B DN):', {k: [round(x, 2) for x in v] for k, v in pix_noise.items()})

# ---- radial profile about the catalogue place
others_mask = np.zeros((hh, ww), bool)
for e in S6['extra_masks']:
    ox, oy = others[e['name']]; others_mask |= np.hypot(xx - ox, yy - oy) <= e['radius_px']
prof = []
for a_ in range(0, 1000, 20):
    m = (RR >= a_) & (RR < a_ + 20) & FREE & ~others_mask
    if m.sum() < 2000 and a_ > 100: break
    full = bool(OK[(RR >= a_) & (RR < a_ + 20)].mean() > 0.6)
    prof.append(dict(r_px=[a_, a_ + 20], r_arcmin=[round(a_ * SC / 60, 2), round((a_ + 20) * SC / 60, 2)], n_px=int(m.sum()), ring_mostly_in_frame=full,
                     mean_dn=dict(zip('RGB', [round(float(ST[k][m].mean()), 3) for k in range(3)])), odd_g=round(float(ODD[1][m].mean()), 3), even_g=round(float(EVEN[1][m].mean()), 3),
                     noise_error_g=round(float(pix_noise['stack'][1] / np.sqrt(m.sum())), 3)))
centre = float(np.mean([p['mean_dn']['G'] for p in prof if p['r_px'][0] < 60]))
half_r = next((p['r_px'][0] for p in prof if p['mean_dn']['G'] < 0.5 * centre), None)
# the ring is large, so its own noise is small; what limits it is the sky's zero: use the blank-sky scatter of an AP patch
lim = float(SKY_SD[1]); SKY_MU = blank['stack'].mean(0)      # the blank sky's own mean is not exactly the stack's zero (the zero is the darker 60% of it)
last_above = None
for p in prof:
    if min(p['mean_dn']['G'], p['odd_g'], p['even_g']) - SKY_MU[1] > 2 * lim: last_above = p['r_px'][1]
    else: break
outside = [p for p in prof if p['r_px'][0] >= MASK_R]
just_out = [p['mean_dn'] for p in outside if p['r_px'][0] < MASK_R + 160]; far_out = [p['mean_dn'] for p in outside if p['r_px'][0] >= MASK_R + 160]
sky_ring = dict(just_outside_the_circle_7_to_9_arcmin_dn={k: round(float(np.mean([v[k] for v in just_out])), 3) for k in 'RGB'} if just_out else None,
                further_out_dn={k: round(float(np.mean([v[k] for v in far_out])), 3) for k in 'RGB'} if far_out else None)
inner_ring = [p['mean_dn'] for p in prof if MASK_R - 120 <= p['r_px'][0] < MASK_R]
sky_ring['just_inside_the_circle_5_5_to_7_arcmin_dn'] = {k: round(float(np.mean([v[k] for v in inner_ring])), 3) for k in 'RGB'}
print('profile: central level %.1f DN green; half of it at %s px (%.1f arcmin radius); above the blank sky\'s mean (%.2f DN) by 2 x its scatter (%.2f DN) in the stack and both halves out to %s px (%.1f arcmin radius)' % (centre, half_r, (half_r or 0) * SC / 60, SKY_MU[1], lim, last_above, (last_above or 0) * SC / 60))
print('profile G (DN) every 40 px:', ' '.join('%d:%.2f' % (p['r_px'][0], p['mean_dn']['G']) for p in prof[::2]))
print('sky rings:', sky_ring)

# ---- extent: smoothed green above 4 x the blank-sky scatter of the same smoothing
ext = {}
for n, A in SETS:
    S8g = msmooth(A[1], 8.0)
    sd8 = clipped_stats(S8g[FREE & ~OBJ & (cv2.erode(FREE.astype(np.uint8), np.ones((17, 17), np.uint8)) > 0)][::7])[1]
    ext[n] = (S8g, sd8)
thr = {n: float(blank[n].mean(0)[1]) + 4 * ext[n][1] for n in ext}
above_all = (ext['stack'][0] > thr['stack']) & (ext['odd'][0] > thr['odd']) & (ext['even'][0] > thr['even']) & OK
above_stack = (ext['stack'][0] > thr['stack']) & OK
tw = S9['the_two_stars']; mid = np.mean([t['pixel_in_the_stack'] for t in tw], axis=0)


def region_of(mask, seed):
    nl_, lab_, st_, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    l = lab_[int(round(seed[1])), int(round(seed[0]))]
    if l == 0:      # the seed itself may sit on a masked star: take the largest region within 60 px
        near = lab_[int(seed[1]) - 60:int(seed[1]) + 60, int(seed[0]) - 60:int(seed[0]) + 60]; ids = np.bincount(near[near > 0]); l = int(np.argmax(ids)) if len(ids) else 0
    return lab_ == l


def size_of(reg):
    ys, xs = np.nonzero(reg); d = np.stack([xs - cx, ys - cy], 1).astype(np.float64)
    n_ = d @ NORTH * SC / 60; e_ = d @ EAST * SC / 60
    return dict(area_arcmin2=round(float(reg.sum() * SC * SC / 3600), 1), north_south_arcmin=round(float(n_.max() - n_.min()), 1), east_west_arcmin=round(float(e_.max() - e_.min()), 1),
                reaches_north_arcmin=round(float(n_.max()), 1), reaches_south_arcmin=round(float(-n_.min()), 1), reaches_east_arcmin=round(float(e_.max()), 1), reaches_west_arcmin=round(float(-e_.min()), 1),
                box_px=[int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())], equivalent_diameter_arcmin=round(float(2 * np.sqrt(reg.sum() / np.pi) * SC / 60), 1))


reg_all = region_of(above_all, mid); reg_stack = region_of(above_stack, mid)
extent = dict(how='green smoothed by a Gaussian of 8 px (stars masked), above the blank sky\'s mean by 4 x the scatter of the same smoothing on blank sky; the connected region that holds the two stars',
              threshold_dn={n: round(float(thr[n]), 3) for n in thr}, in_the_stack=size_of(reg_stack), in_the_stack_and_in_both_halves=size_of(reg_all), measured_from='M78\'s catalogue place')
print('extent (stack):', extent['in_the_stack']); print('extent (stack and both halves):', extent['in_the_stack_and_in_both_halves'])

# ---- the glow round the two stars; the other nebulae
PL2, T2 = places(OTHER_R)
blank2 = {n: np.array([disc_mean(A, px, py, OTHER_R, T2) for px, py in PL2]) for n, A in SETS}


def against_sky(px, py, label):
    px, py = int(round(px)), int(round(py)); d = dict(what=label, place_px=[px, py], radius_px=OTHER_R, radius_arcmin=round(OTHER_R * SC / 60, 2))
    if not (OTHER_R < px < ww - OTHER_R and OTHER_R < py < hh - OTHER_R):
        d['measured'] = False; d['why'] = 'the circle does not fit in the frame'; return d
    for n, A in SETS:
        v = disc_mean(A, px, py, OTHER_R, T2); sd = blank2[n].std(0, ddof=1); mu = blank2[n].mean(0)
        d[n] = dict(mean_dn=dict(zip('RGB', [round(x, 3) for x in v])), times_the_blank_sky_scatter=dict(zip('RGB', [round(float((x - m_) / s_), 1) for x, m_, s_ in zip(v, mu, sd)])))
    d['blank_sky_scatter_dn'] = dict(zip('RGB', blank2['stack'].std(0, ddof=1).round(3).tolist())); d['blank_sky_places'] = len(PL2)
    d['seen'] = bool(min(d[n]['times_the_blank_sky_scatter']['G'] for n in ('stack', 'odd', 'even')) >= 5)
    return d


def local_contrast(A, px, py, r_in=45, r0=70, r1=110):
    px, py = int(round(px)), int(round(py)); sl = (slice(py - r1, py + r1 + 1), slice(px - r1, px + r1 + 1))
    r = np.hypot(*np.mgrid[-r1:r1 + 1, -r1:r1 + 1]); f = FREE[sl]; a = f & (r <= r_in); b = f & (r >= r0) & (r <= r1)
    return float(A[1][sl][a].mean() - A[1][sl][b].mean()) if a.sum() > 0.5 * (r <= r_in).sum() and b.sum() > 0.5 * ((r >= r0) & (r <= r1)).sum() else None


PL5, _ = places(110, 110)
LOCAL_SD = {n: float(np.std([v for v in (local_contrast(A, px, py) for px, py in PL5) if v is not None], ddof=1)) for n, A in SETS}


def local_test(px, py):
    if not (110 < px < ww - 110 and 110 < py < hh - 110): return None
    d = dict(how='mean green within 45 px (35 arcsec) less the mean of the ring 70 to 110 px around it, against the scatter of the same on %d blank-sky places' % len(PL5))
    for n, A in SETS:
        v = local_contrast(A, px, py); d[n] = dict(contrast_dn=round(v, 3), sigma=round(v / LOCAL_SD[n], 1)) if v is not None else None
    if not all(d[n] for n in ('stack', 'odd', 'even')):
        d['seen'] = None; d['why'] = 'not measured this way: a masked star covers more than half of the inner circle'; return d
    d['seen'] = bool(all(d[n] and d[n]['sigma'] >= 4 for n in ('stack', 'odd', 'even')))
    return d


glow = against_sky(mid[0], mid[1], 'the glow round the two stars: 1.5 arcmin about their midpoint, stars masked')
oth = {name: against_sky(p[0], p[1], name + ' at its catalogue place') for name, p in others.items()}
for name, p in others.items(): oth[name]['as_a_small_patch'] = local_test(p[0], p[1])
print('glow:', glow)
for k, v in oth.items(): print(k, v)

# ---- the dark lane: a strip from the stars' midpoint through NGC 2067's place and beyond
p67 = np.array(others['NGC 2067']); u = (p67 - mid) / np.hypot(*(p67 - mid)); perp = np.array([-u[1], u[0]])
t_ = (xx - mid[0]) * u[0] + (yy - mid[1]) * u[1]; s_ = (xx - mid[0]) * perp[0] + (yy - mid[1]) * perp[1]
STRIP = (np.abs(s_) <= 60) & FREE
lane_prof = []
for a_ in range(-120, 700, 10):
    m = STRIP & (t_ >= a_) & (t_ < a_ + 10)
    if m.sum() < 300: lane_prof.append(None); continue
    lane_prof.append(dict(along_px=a_, along_arcsec=round(a_ * SC, 1), n_px=int(m.sum()), g=round(float(ST[1][m].mean()), 3), odd_g=round(float(ODD[1][m].mean()), 3), even_g=round(float(EVEN[1][m].mean()), 3),
                          r=round(float(ST[0][m].mean()), 3), b=round(float(ST[2][m].mean()), 3)))
lp = [p for p in lane_prof if p]
# the blank-sky scatter of a bin-sized patch (120 x 10 px), from the stack: places of 120 x 30 (three bins, smoothed like the test below)
def run3(key): return np.convolve([p[key] for p in lp], np.ones(3) / 3, mode='same')
al = np.array([p['along_px'] for p in lp]); lane = {}
PL3, _ = places(60, 60); binsd = {}
pairsd = {}          # the same patch against one 110 px beside it (the lane's minimum and its far bank are about that far apart): a local difference, free of the sky's large-scale error
for n, A in SETS:
    v = []; dv = []
    for px, py in PL3:
        m = FREE[py - 15:py + 15, px - 60:px + 60]
        if m.sum() > 1800: v.append(float(A[1][py - 15:py + 15, px - 60:px + 60][m].mean()))
        if py + 125 < hh and not OBJ[py + 95:py + 125, px - 60:px + 60].any() and OK[py + 95:py + 125, px - 60:px + 60].all():
            m2 = FREE[py + 95:py + 125, px - 60:px + 60]
            if m.sum() > 1800 and m2.sum() > 1800: dv.append(float(A[1][py - 15:py + 15, px - 60:px + 60][m].mean() - A[1][py + 95:py + 125, px - 60:px + 60][m2].mean()))
    binsd[n] = float(np.std(v, ddof=1)); pairsd[n] = float(np.std(dv, ddof=1))
for key, n in (('g', 'stack'), ('odd_g', 'odd'), ('even_g', 'even')):
    g3 = run3(key)
    body = (al >= -60) & (al <= 120); i_body = int(np.argmax(np.where(body, g3, -1e9)))
    far = (al >= 250) & (al <= 520); i_far = int(np.argmax(np.where(far, g3, -1e9)))
    between = (al > al[i_body]) & (al < al[i_far]); i_min = int(np.argmin(np.where(between, g3, 1e9)))
    lane[n] = dict(body_peak_dn=round(float(g3[i_body]), 2), body_at_px=int(al[i_body]), lane_minimum_dn=round(float(g3[i_min]), 2), lane_at_px=int(al[i_min]), lane_at_arcmin=round(float(al[i_min] * SC / 60), 2),
                   far_bank_peak_dn=round(float(g3[i_far]), 2), far_bank_at_px=int(al[i_far]), far_bank_at_arcmin=round(float(al[i_far] * SC / 60), 2),
                   far_bank_above_the_lane_dn=round(float(g3[i_far] - g3[i_min]), 2), blank_sky_scatter_of_such_a_patch_dn=round(binsd[n], 3), blank_sky_scatter_of_two_such_patches_110_px_apart_dn=round(pairsd[n], 3), far_bank_above_the_lane_sigma=round(float((g3[i_far] - g3[i_min]) / pairsd[n]), 1),
                   lane_below_the_blank_skys_mean_dn=round(float(blank[n].mean(0)[1] - g3[i_min]), 2), lane_below_the_blank_skys_mean_sigma=round(float((blank[n].mean(0)[1] - g3[i_min]) / binsd[n]), 1))
lane_dir = dict(north=float(u @ NORTH), east=float(u @ EAST))
lane_real = bool(all(lane[n]['far_bank_above_the_lane_sigma'] >= 4 for n in lane) and max(lane[n]['lane_at_px'] for n in lane) - min(lane[n]['lane_at_px'] for n in lane) <= 40)
print('lane strip heads %.0f deg east of north; ' % (np.degrees(np.arctan2(lane_dir['east'], lane_dir['north'])) % 360), {k: v for k, v in lane.items()}, 'REAL' if lane_real else 'not proven')
print('strip G every 20 px:', ' '.join('%d:%.1f' % (p['along_px'], p['g']) for p in lp[::2]))

# ---- colour: is the blue measured?
S8st = msmooth(ST[1], 8.0)
bands = [(20, 1e9), (10, 20), (5, 10), (2.5, 5)]; col = []
in_neb = (RR < MASK_R) & FREE
for lo, hi in bands:
    m = in_neb & (S8st >= lo) & (S8st < hi)
    if m.sum() < 500: continue
    row = dict(smoothed_green_dn=[lo, None if hi > 1e8 else hi], pixels=int(m.sum()))
    for n, A in SETS:
        v = np.array([A[k][m].mean() for k in range(3)]) * wbd
        row[n] = dict(rgb_daylight_dn=[round(float(x), 2) for x in v], r_over_g=round(float(v[0] / v[1]), 3), b_over_g=round(float(v[2] / v[1]), 3))
    v = np.array([ST[k][m].mean() for k in range(3)]) * wbd
    # what one blank-sky scatter of error in the zero of blue (against green) would do to the ratio
    row['b_over_g_error_from_the_sky_zero'] = round(float(np.hypot(SKY_SD[2] * wbd[2] / v[1], SKY_SD[1] * v[2] / v[1] ** 2)), 3)
    row['r_over_g_error_from_the_sky_zero'] = round(float(np.hypot(SKY_SD[0] * wbd[0] / v[1], SKY_SD[1] * v[0] / v[1] ** 2)), 3)
    row['b_over_g_half_stacks_differ_by'] = round(abs(row['odd']['b_over_g'] - row['even']['b_over_g']), 3)
    col.append(row)
    print('colour, smoothed green %s DN: R/G %.3f B/G %.3f (odd %.3f even %.3f; sky-zero error %.3f), %d px' % (row['smoothed_green_dn'], row['stack']['r_over_g'], row['stack']['b_over_g'], row['odd']['b_over_g'], row['even']['b_over_g'], row['b_over_g_error_from_the_sky_zero'], m.sum()))


def star_colour(x, y, rad=10):
    xi, yi = int(round(x)), int(round(y))
    if xi < 40 or yi < 40 or xi > ww - 41 or yi > hh - 41: return None
    oy_, ox_ = np.mgrid[-36:37, -36:37]; r = np.hypot(ox_ - (x - xi), oy_ - (y - yi)); v = []
    for k in range(3):
        t = ST[k][yi - 36:yi + 37, xi - 36:xi + 37]; bg = np.median(t[(r > 24) & (r < 34)]); v.append(float((t - bg)[r <= rad].sum()))
    v = np.array(v) * wbd
    return v if v.min() > 0 else None


# field stars: bright enough (peak > 40 sigma on the DoG), outside the object mask, unclipped (peak green under 9000 DN)
fs = []
for x, y, sg, a, r in star_list:
    if sg < 40 or OBJ[int(y), int(x)] or ST[1][int(y), int(x)] > 9000: continue
    v = star_colour(x, y)
    if v is not None: fs.append([v[0] / v[1], v[2] / v[1]])
fs = np.array(fs)
two_col = []
for t in tw:
    v = star_colour(*t['pixel_in_the_stack'])
    two_col.append(dict(pixel=t['pixel_in_the_stack'], r_over_g=round(float(v[0] / v[1]), 3), b_over_g=round(float(v[2] / v[1]), 3), note='the nebula\'s own light under the star is taken off with a ring of 24 to 34 px') if v is not None else None)
bright = col[0] if col else None
field = dict(stars=int(len(fs)), r_over_g_median=round(float(np.median(fs[:, 0])), 3), b_over_g_median=round(float(np.median(fs[:, 1])), 3), b_over_g_quartiles=[round(float(q), 3) for q in np.percentile(fs[:, 1], [25, 75])], b_over_g_bluest=round(float(fs[:, 1].max()), 3)) if len(fs) else None
blue = None
if bright and field and all(two_col):
    err = float(np.hypot(bright['b_over_g_error_from_the_sky_zero'], bright['b_over_g_half_stacks_differ_by']))
    bg_ = bright['stack']['b_over_g']; star_bg = max(t['b_over_g'] for t in two_col)
    blue = dict(nebula_b_over_g=bg_, error=round(err, 3), lighting_stars_b_over_g=[t['b_over_g'] for t in two_col], field_stars_b_over_g_median=field['b_over_g_median'], white_is=1.0,
                bluer_than_its_stars_by_sigma=round((bg_ - star_bg) / err, 1), bluer_than_the_field_stars_median_by_sigma=round((bg_ - field['b_over_g_median']) / err, 1), bluer_than_white_by_sigma=round((bg_ - 1.0) / err, 1),
                measured_bluer_than_its_stars=bool(bg_ - star_bg > 3 * err), measured_bluer_than_white=bool(bg_ - 1.0 > 3 * err))
print('field stars:', field); print('the two stars:', two_col); print('blue:', blue)

# ---- structure: band-passed halves, correlated inside the nebula and on blank sky
NEBM = (RR < NEB_R) & FREE
def band(A, s): return msmooth(A, s) - msmooth(A, 4 * s)
def corr(a, b, m):
    a = a[m] - a[m].mean(); b = b[m] - b[m].mean(); return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
PL4, T4 = places(NEB_R, NEB_R // 3)
structure = {}
for s in (3.0, 6.0, 12.0):
    Bo, Be = band(ODD[1], s), band(EVEN[1], s)
    r_in = corr(Bo, Be, NEBM); rc = []
    for px, py in PL4:
        m = np.zeros((hh, ww), bool); m[py - NEB_R:py + NEB_R + 1, px - NEB_R:px + NEB_R + 1] = T4; rc.append(corr(Bo, Be, m & FREE))
    rc = np.array(rc)
    d = dict(band='Gaussian %.0f px minus Gaussian %.0f px (detail of about %.0f to %.0f arcsec)' % (s, 4 * s, 2.355 * s * SC, 2.355 * 4 * s * SC), halves_correlation_in_nebula=round(r_in, 3),
             blank_sky_places=int(len(rc)), blank_sky_correlation_mean=round(float(rc.mean()), 3) if len(rc) else None, blank_sky_correlation_std=round(float(rc.std(ddof=1)), 3) if len(rc) > 2 else None,
             blank_sky_correlation_max=round(float(rc.max()), 3) if len(rc) else None)
    d['significance_sigma'] = round(float((r_in - rc.mean()) / rc.std(ddof=1)), 1) if len(rc) > 2 else None
    d['repeats'] = bool(len(rc) > 2 and (rc >= r_in).sum() == 0 and d['significance_sigma'] >= 5)
    structure['sigma_%.0f_px' % s] = d
    print('structure, green, band sigma %.0f px: halves r = %.3f within %d px of M78; blank sky %s +- %s (max %s, %d places) -> %s sigma, %s' % (s, r_in, NEB_R, d['blank_sky_correlation_mean'], d['blank_sky_correlation_std'], d['blank_sky_correlation_max'], len(rc), d['significance_sigma'], 'REPEATS' if d['repeats'] else 'does not repeat'))

# ---- a look for the eye: odd, even, stack around M78 (smoothed 3 px), same scale
def cut(v): return v[max(int(cy) - 420, 0):int(cy) + 420, max(int(cx) - 520, 0):int(cx) + 520]
vis = [cut(cv2.GaussianBlur(A[1].astype(np.float32), (0, 0), 3.0)) for A in (ODD, EVEN, ST)]
cv2.imwrite(W('halves_look.png'), np.hstack([(np.clip((np.arcsinh((v + 2) / 3) / np.arcsinh(60 / 3)), 0, 1) * 255).astype(np.uint8) for v in vis])[::2, ::2])

out = dict(on='the well-covered rectangle of step 9, the picture\'s sky plane taken off', catalogue_px=[cx, cy], scale_arcsec_per_px=SC, stars_masked=len(star_list), noise_per_px_dn=pix_noise,
           sky=dict(how_it_was_set='in every frame and colour plane one constant, the 3-sigma clipped mean of the sky region (step 8: %d px, the darker %d%% of the area outside M78\'s %.0f arcmin circle and the circles of NGC 2071 and NGC 2064); in the picture also a plane per colour plane fitted to the stack outside those circles (step 10)' % (S8['faint_region']['pixels'], S8['faint_region']['percentile'], S6['mask_radius_arcmin']),
                    blank_sky_apertures=sky, rings_about_m78=sky_ring,
                    trusted='the zero is known to about %.2f DN in green over a patch of %.1f arcmin radius (scatter of %d blank-sky places; %.2f red, %.2f blue). No sky is seen inside %.0f arcmin of M78, so under the nebula the zero is the continuation of a plane; the ring just outside the circle reads %+.2f DN green and the ring just inside it %+.2f (the blank sky\'s own mean is %+.2f: the zero is the darker 60%% of it).' % (
                        SKY_SD[1], AP * SC / 60, len(PLC), SKY_SD[0], SKY_SD[2], S6['mask_radius_arcmin'], sky_ring['just_outside_the_circle_7_to_9_arcmin_dn']['G'] if sky_ring['just_outside_the_circle_7_to_9_arcmin_dn'] else float('nan'), sky_ring['just_inside_the_circle_5_5_to_7_arcmin_dn']['G'], SKY_MU[1])),
           profile=prof, central_level_green_dn=centre, half_level_radius_px=half_r, half_level_radius_arcmin=round(half_r * SC / 60, 2) if half_r else None,
           above_twice_the_sky_scatter_out_to_px=last_above, above_twice_the_sky_scatter_out_to_arcmin=round(last_above * SC / 60, 2) if last_above else None,
           extent=extent, glow=glow, others=oth,
           lane=dict(strip='from the midpoint of the two stars (%.0f, %.0f) towards NGC 2067\'s catalogue place and beyond, 120 px wide, bins of 10 px, running mean of 3' % tuple(mid), heading_deg_east_of_north=round(float(np.degrees(np.arctan2(lane_dir['east'], lane_dir['north'])) % 360), 1),
                     numbers=lane, real=lane_real, profile=lane_prof),
           colour=dict(units='R, G, B times the camera\'s daylight white balance; white (the Sun\'s colour) is 1 : 1 : 1', white_balance=wbd.tolist(), bands=col, field_stars=field, the_two_stars=two_col, blue=blue),
           structure=structure, subsets=dict(odd=len(S8['subsets']['odd']), even=len(S8['subsets']['even'])), the_two_stars_midpoint_px=mid.tolist())
jdump(out, 'step11_measure.json')
