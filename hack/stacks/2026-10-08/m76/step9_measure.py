"""Step 9: the numbers that say what the stack is worth, all on the north-up grid (step 6 north) where the stack and
the reference frame alone went through the same repair, scaling and resampling:
  - sky noise per pixel, stack against the single reference frame (and at 4 x 4 binning, where pattern noise would
    show), against the ideal for the frame count and weights
  - star size and shape, the same stars in the stack and in the single frame; colour offsets left after step 6
  - the nebula's light in rings, and the "is it real?" test: the two half stacks (every other frame, step 6 with
    M76_HALF=a / b) measured independently in sectors of the faint outer loops; both after the sky dome of step 8
    and one constant per colour (as the picture gets them)
  - the sky's slope across the grid (vignetting with no flat) and dust shadows
No pixels are changed here."""
import json, os
import numpy as np, cv2
from common import *
from step3_stars import measure

g7 = json.load(open(W('step7_grid.json'))); s6 = json.load(open(W('step6_north.json'))); q5 = json.load(open(W('step5_quality.json'))); s2 = json.load(open(W('step2.json')))
SCALE = g7['pixscale_arcsec']
st = np.load(W('north_stack.npy')); sg = np.load(W('north_single.npy')); ha = np.load(W('north_a_stack.npy')); hb = np.load(W('north_b_stack.npy'))
f2 = {f['stamp']: f for f in s2['frames']}
wb = np.median(np.array([f2[s]['wb'] for s in s6['used']]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
def rgb(P): return np.dstack([P[0] * wb_r, (P[1] + P[2]) / 2, P[3] * wb_b]).astype(np.float32)
hh, ww = st.shape[1:]; cx, cy = g7['centre_out_px']
yy, xx = np.mgrid[0:hh, 0:ww]; rr = np.hypot(xx - cx, yy - cy)
dome = np.load(W('north_sky.npy')).transpose(1, 2, 0)
S, S1, A_, B_ = rgb(st), rgb(sg), rgb(ha), rgb(hb)
Sd, S1d, Ad, Bd = S - dome, S1 - dome, A_ - dome, B_ - dome
G = S[:, :, 1]
# stars: 4-sigma blobs of the smoothed green, grown by 4 px (more for bright ones)
sm = cv2.GaussianBlur(G, (0, 0), 2.0); m0, s0, _ = clipped_stats(sm[rr > 260])
star = (sm - m0) > 4 * s0
star &= ~(rr < 140)                                        # the nebula is not a star
nl, lab, stats, cent = cv2.connectedComponentsWithStats(star.astype(np.uint8))
smask = np.zeros_like(star)
for i in range(1, nl):
    x, y = cent[i]; a = stats[i, 4]; r = 5 + 1.5 * np.sqrt(a)
    smask |= (xx - x) ** 2 + (yy - y) ** 2 <= r * r
SKY = (rr > 260) & ~smask
print('sky pixels %d (%.0f%% of the grid), %d stars masked' % (SKY.sum(), 100 * SKY.mean(), nl - 1))

def block_noise(img, mask, b=40, binning=1):
    if binning > 1:
        h2, w2 = img.shape[0] // binning, img.shape[1] // binning
        img = img[:h2 * binning, :w2 * binning].reshape(h2, binning, w2, binning).mean((1, 3))
        mask = mask[:h2 * binning, :w2 * binning].reshape(h2, binning, w2, binning).all((1, 3)); b = b // binning * 2
    out = []
    for j in range(0, img.shape[0] - b + 1, b):
        for i in range(0, img.shape[1] - b + 1, b):
            m = mask[j:j + b, i:i + b]
            if m.mean() > 0.8: out.append(clipped_stats(img[j:j + b, i:i + b][m])[1])
    return float(np.median(out)), len(out)

noise = {}
for nm, img in (('stack', S), ('single', S1), ('half_a', A_), ('half_b', B_)):
    noise[nm] = {c: block_noise(img[:, :, k], SKY)[0] for k, c in enumerate('RGB')}
    noise[nm]['mean_of_RGB'] = block_noise(img.mean(2), SKY)[0]
    noise[nm]['mean_of_RGB_4x4_binned'] = block_noise(img.mean(2), SKY, binning=4)[0]
n_eff = q5['effective_frames']
imp = {k: noise['single'][k] / noise['stack'][k] for k in noise['stack']}
print('sky noise per px (DN): stack', {k: round(v, 2) for k, v in noise['stack'].items()}, '\n  single', {k: round(v, 2) for k, v in noise['single'].items()},
      '\n  improvement', {k: round(v, 2) for k, v in imp.items()}, 'ideal %.2f' % np.sqrt(n_eff))

# stars: the same isolated, unsaturated stars in the stack and the single frame
rows = []
cxs, cys = cent[1:, 0], cent[1:, 1]
for i in range(1, nl):
    x, y = cent[i]
    if rr[int(y), int(x)] < 240 or x < 40 or y < 40 or x > ww - 40 or y > hh - 40: continue
    if np.sort(np.hypot(cxs - x, cys - y))[1] < 25: continue
    a = measure(G - m0, x, y)
    if a is None or a['flux'] < 8000 or a['peak'] > 8000: continue
    b = measure(S1[:, :, 1] - clipped_stats(S1[:, :, 1][SKY])[0], a['x'], a['y'])
    rgt = [measure(S[:, :, k] - clipped_stats(S[:, :, k][SKY])[0], a['x'], a['y']) for k in (0, 2)]
    if b is None or None in rgt: continue
    rows.append(dict(x=a['x'], y=a['y'], flux=a['flux'], hfd_stack=2 * a['hfr'], hfd_single=2 * b['hfr'], elong_stack=a['elong'], elong_single=b['elong'],
                     red_minus_green=[rgt[0]['x'] - a['x'], rgt[0]['y'] - a['y']], blue_minus_green=[rgt[1]['x'] - a['x'], rgt[1]['y'] - a['y']]))
hs = np.array([r['hfd_stack'] for r in rows]); h1 = np.array([r['hfd_single'] for r in rows])
stars = dict(n=len(rows), method='step 3 measure() on the green of the north-up grid: Gaussian-windowed centroid, 14 px aperture, half-flux diameter; isolated stars (no neighbour within 25 px), flux 8000+ DN, peak under 8000 DN, outside 3.1 arcmin of the nebula',
             hfd_stack_px=float(np.median(hs)), hfd_stack_arcsec=float(np.median(hs) * SCALE), hfd_single_reference_px=float(np.median(h1)), hfd_single_reference_arcsec=float(np.median(h1) * SCALE),
             elong_stack=float(np.median([r['elong_stack'] for r in rows])), elong_single_reference=float(np.median([r['elong_single'] for r in rows])),
             colour_offset_left_px=dict(red_minus_green=np.median([r['red_minus_green'] for r in rows], 0).tolist(), blue_minus_green=np.median([r['blue_minus_green'] for r in rows], 0).tolist()),
             single_frames_hfd_arcsec=dict(used_median=float(np.median([o['hfd_arcsec'] for o in q5['quality'] if o['stamp'] in s6['used']])), used_range=[min(o['hfd_arcsec'] for o in q5['quality'] if o['stamp'] in s6['used']), max(o['hfd_arcsec'] for o in q5['quality'] if o['stamp'] in s6['used'])],
                                           note='step 5: the 59 brightest unsaturated stars on the raw colour planes; a different star set from the line above, so compare within a line, not across'))
print('stars:', json.dumps(stars))

# the nebula in rings (green, DN per frame-equivalent of the clearest frame, above the sky)
sky_c = [clipped_stats(Sd[:, :, k][SKY])[0] for k in range(3)]
sky_c1 = [clipped_stats(S1d[:, :, k][SKY])[0] for k in range(3)]
prof = []
for a, b in ((0, 20), (20, 40), (40, 60), (60, 80), (80, 100), (100, 130), (130, 160), (160, 200), (200, 240)):
    m = (rr >= a) & (rr < b) & ~smask
    v = float(np.mean(Sd[:, :, 1][m]) - sky_c[1]); v1 = float(np.mean(S1d[:, :, 1][m]) - sky_c1[1])
    prof.append(dict(r_arcsec=[round(a * SCALE, 1), round(b * SCALE, 1)], green_dn=round(v, 2), snr_per_px_stack=round(v / noise['stack']['G'], 2), snr_per_px_single=round(v1 / noise['single']['G'], 2)))
print('profile', prof)

# is it real? the lobes and the red at the ends of the bar, cross-checked: each region is chosen in one half stack
# and measured in the other (so the choice cannot ride on the measuring half's noise)
def regions(X):
    """X: dome-subtracted, sky-zeroed RGB. bar: smoothed green > 20 DN; lobes: 4 to 20 DN within 100 px of the
    centre; red: the reddest tenth (smoothed R/G) of the nebula above 8 DN. Stars masked throughout."""
    Gs_ = cv2.GaussianBlur(X[:, :, 1], (0, 0), 3); Rs_ = cv2.GaussianBlur(X[:, :, 0], (0, 0), 3)
    neb = (Gs_ > 8) & (rr < 110) & ~smask2
    ratio = Rs_ / np.maximum(Gs_, 1)
    red = neb & (ratio > np.percentile(ratio[neb], 90))
    return dict(bar=(Gs_ > 20) & (rr < 120) & ~smask2, lobes=(Gs_ > 4) & (Gs_ <= 20) & (rr < 100) & ~smask2, red=red, rest=neb & ~red)
def zeroed(X):
    return X - np.array([clipped_stats(X[:, :, k][SKY])[0] for k in range(3)], np.float32)
sm2 = cv2.GaussianBlur(G, (0, 0), 2.0)
smask2 = cv2.dilate(((sm2 - cv2.GaussianBlur(G, (0, 0), 12)) > 5 * s0).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)   # stars, also on the nebula
Za, Zb = zeroed(Ad), zeroed(Bd)
def mean_err(X, k, n):
    bs = int(np.sqrt(n)); vals = []
    for j in range(0, hh - bs, bs):
        for i in range(0, ww - bs, bs):
            mm = SKY[j:j + bs, i:i + bs]
            if mm.mean() > 0.7: vals.append(X[j:j + bs, i:i + bs, k][mm].mean())
    v = np.array(vals); return 1.4826 * float(np.median(np.abs(v - np.median(v))))
cross = {}
for sel, meas, nm in ((Za, Zb, 'chosen_in_a_measured_in_b'), (Zb, Za, 'chosen_in_b_measured_in_a')):
    rg = regions(sel)
    lob = float(meas[:, :, 1][rg['lobes']].mean()); e = mean_err(meas, 1, int(rg['lobes'].sum()))
    ys_, xs_ = np.nonzero(rg['red']); pa_ = (np.degrees(np.arctan2(-(xs_ - cx), -(ys_ - cy))) + 360) % 360
    cross[nm] = dict(lobes_green_dn=round(lob, 2), lobes_sigma=round(lob / e, 1), lobes_pixels=int(rg['lobes'].sum()), bar_green_dn=round(float(meas[:, :, 1][rg['bar']].mean()), 2),
                     red_region_pixels=int(rg['red'].sum()), red_region_r_over_g=round(float(meas[:, :, 0][rg['red']].sum() / meas[:, :, 1][rg['red']].sum()), 3),
                     rest_of_nebula_r_over_g=round(float(meas[:, :, 0][rg['rest']].sum() / meas[:, :, 1][rg['rest']].sum()), 3),
                     red_region_position_angles_deg_histogram_30deg=np.histogram(pa_, bins=12, range=(0, 360))[0].tolist())
    print('cross-check %s: %s' % (nm, json.dumps(cross[nm])))

# the sky's slope left on the north-up grid after the per-frame constants alone: block medians, a plane fitted (measured only)
def plane_fit(img, B=50):
    bl = []
    for j in range(0, hh - B + 1, B):
        for i in range(0, ww - B + 1, B):
            m = SKY[j:j + B, i:i + B]
            if m.mean() > 0.6: bl.append((i + B / 2, j + B / 2, clipped_stats(img[j:j + B, i:i + B][m])[2]))
    bl = np.array(bl); Am = np.column_stack([np.ones(len(bl)), bl[:, 0] - cx, bl[:, 1] - cy])
    coef, *_ = np.linalg.lstsq(Am, bl[:, 2], rcond=None); res = bl[:, 2] - Am @ coef
    return coef, res, bl
grad = {}
for k, c in enumerate('RGB'):
    coef, res, bl = plane_fit(S[:, :, k])
    grad[c] = dict(at_centre=float(coef[0]), dn_per_100px_x=float(coef[1] * 100), dn_per_100px_y=float(coef[2] * 100), resid_rms=float(res.std()), deepest_block_below_plane=float(res.min()),
                   deepest_block_xy=bl[int(np.argmin(res)), :2].tolist())
print('sky slope:', json.dumps(grad))

# is it real? the faint outer loops in two independent half stacks, sector by sector, outside the bright bar,
# each half less the sky dome (step 8) and its own constant (sky outside 260 px)
Ga, Gb_ = Ad[:, :, 1] - clipped_stats(Ad[:, :, 1][SKY])[0], Bd[:, :, 1] - clipped_stats(Bd[:, :, 1][SKY])[0]
bar = cv2.GaussianBlur(G - sky_c[1], (0, 0), 3) > 20                      # the bright bar and lobes: above 20 DN smoothed
ang = (np.degrees(np.arctan2(-(xx - cx), -(yy - cy))) + 360) % 360      # position angle: 0 = north (up), 90 = east (left)
def block_sigma(img, bs=30):
    vals = []
    for j in range(0, hh - bs + 1, bs):
        for i in range(0, ww - bs + 1, bs):
            mm = SKY[j:j + bs, i:i + bs]
            if mm.mean() > 0.7: vals.append(img[j:j + bs, i:i + bs][mm].mean())
    vals = np.array(vals); return 1.4826 * float(np.median(np.abs(vals - np.median(vals)))), bs * bs
sa, na_ = block_sigma(Ga); sb, _ = block_sigma(Gb_)
sectors = []
ring = (rr * SCALE >= 75) & (rr * SCALE < 150) & ~bar & ~smask
for a0 in range(0, 360, 30):
    m = ring & (ang >= a0) & (ang < a0 + 30)
    n_ = int(m.sum()); ea, eb = sa * np.sqrt(na_ / n_), sb * np.sqrt(na_ / n_)
    va, vb = float(Ga[m].mean()), float(Gb_[m].mean())
    sectors.append(dict(position_angle_deg=[a0, a0 + 30], pixels=n_, half_a_dn=round(va, 2), half_b_dn=round(vb, 2), half_a_sigma=round(va / ea, 1), half_b_sigma=round(vb / eb, 1)))
print('outer loops, 75-150 arcsec, outside the bar (green DN above each half\'s sky, dome removed, sigma):')
for s_ in sectors: print('  PA %3d-%3d: half a %+.2f (%+.1f sigma)  half b %+.2f (%+.1f sigma)' % (*s_['position_angle_deg'], s_['half_a_dn'], s_['half_a_sigma'], s_['half_b_dn'], s_['half_b_sigma']))
json.dump(dict(white_balance=dict(R=wb_r, B=wb_b), sky_mask=dict(outside_r_px=260, stars_masked=int(nl - 1), pixels=int(SKY.sum())), noise_dn_per_px=noise, improvement=imp, ideal_sqrt_n_eff=float(np.sqrt(n_eff)), n_eff=n_eff,
               stars=stars, sky_level_after_dome=dict(zip('RGB', sky_c)), nebula_green_profile=prof, lobes_and_red_cross_check=cross, outer_loops_half_stacks=dict(region='75 to 150 arcsec from the catalogue centre, outside where the smoothed stack exceeds 20 DN (the bar and its lobes), stars masked; position angle from north through east; each half less the step 8 sky dome and its own constant (sky outside 260 px); sigma from 30 x 30 px block means of masked sky, scaled to the sector area', halves=dict(a=json.load(open(W('step6_north_a.json')))['used'], b=json.load(open(W('step6_north_b.json')))['used']), sectors=sectors),
               sky_slope=grad), open(W('step9_measure.json'), 'w'), indent=1)
