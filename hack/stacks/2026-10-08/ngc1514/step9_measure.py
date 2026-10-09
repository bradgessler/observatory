"""Step 9: is the shell there, and how strongly? Numbers only; no pixels are changed for the picture here.

All on the stack grid (step 7), in a box 1300 px wide around the central star, raw camera units (DN of the 14-bit RAW per
15 s frame at the clearest frame's transparency), colours R, G = mean of G1 and G2, B, no white balance.

  sky       a plane per colour (3 numbers) fitted to the sky 250 to 600 px (3.2 to 7.8 arcmin) from the central star,
            stars masked, 3-sigma clipped, and subtracted. Inside 250 px it is the plane's straight continuation.
  stars     compact sources found on a difference of Gaussians (sigma 1.5 minus sigma 6 px, which ignores the smooth
            shell) above 5 sigma, masked with a circle growing with brightness; the central star itself is not masked,
            the rings start outside its core.
  noise     per pixel: robust std of the sky, for the stack, the reference frame alone, the two half stacks, and half
            their difference (the stack's noise with the sky and stars cancelled). For a region: the same annulus as the
            shell measurement laid on blank sky at every position on a grid where it fits (centre 330 px or more from the
            star), its masked mean taken; the scatter of those means is the uncertainty of a mean over that region,
            including correlated noise, faint stars and sky structure.
  shell     the masked mean in the annulus SHELL_R0 to SHELL_R1 px (12 to 60 arcsec) around the central star, against that
            scatter: the signal to noise. Rings of 4 px for the profile.
  star light the central star's own light at those radii (its seeing halo and the telescope's scatter), predicted from
            other bright stars in the same stack: each comparison star's ring profile, scaled to the central star's in
            the 6 to 12 px ring (where both are unclipped and starlight outweighs the shell 20 to 1), carried outward.
  is it real the two half stacks (odd and even frames, step 7), each measured alone; and the shell's shape (the two halves
            smoothed by a 3 px Gaussian, correlated inside the shell) against the same correlation on blank sky.
  stars     half-flux diameter of isolated, unclipped stars in the stack and in the reference frame alone (same grid)."""
import os
import numpy as np, cv2
from common import *
from step2_stars import measure

SHELL_R0, SHELL_R1 = 16, 77           # px (12.4 to 59.8 arcsec at 0.776 arcsec per px)
SKY_R0, SKY_R1 = 250, 600
BOX = 650
S8 = jload('step8_solve.json'); S7 = jload('step7.json'); S6 = jload('step6_select.json')
SCALE = float(np.mean(S8['scale_arcsec_per_px'])); N = len(S7['frames'])
cx, cy = S8['central_star_centroid']['stack_px']
x0, x1 = int(cx) - BOX, int(cx) + BOX; y0, y1 = max(int(cy) - BOX, 0), min(int(cy) + BOX, h2)
cover = np.load(W_('cover.npy'))[y0:y1, x0:x1]; OK = cover == N


def chans(name):
    a = np.load(W_(name), mmap_mode='r')[:, y0:y1, x0:x1]
    return np.stack([a[0], (a[1] + a[2]) / 2, a[3]]).astype(np.float64)


ST, ODD, EVEN, ONE = chans('stack_mean.npy'), chans('stack_odd.npy'), chans('stack_even.npy'), chans('single_planes.npy')
hh, ww = ST.shape[1:]; ccx, ccy = cx - x0, cy - y0
yy, xx = np.mgrid[0:hh, 0:ww]; RR = np.hypot(xx - ccx, yy - ccy)

# ---- stars (difference of Gaussians on the stack's green)
G = np.where(OK, ST[1], 0).astype(np.float32)
dog = cv2.GaussianBlur(G, (0, 0), 1.5) - cv2.GaussianBlur(G, (0, 0), 6.0)
_, sd_dog, _ = clipped_stats(dog[OK & (RR > SKY_R0)][::5])
det = (dog > 5 * sd_dog) & OK & (RR > 10)
nl, lab, stats, cent = cv2.connectedComponentsWithStats(det.astype(np.uint8), connectivity=8)
smask = np.zeros((hh, ww), np.uint8); nstars = 0
for i in range(1, nl):
    a = stats[i, cv2.CC_STAT_AREA]
    if a < 3: continue
    pk = float(dog[lab == i].max()); r = int(round(4 + 2.5 * np.sqrt(a) + 2 * np.log10(max(pk / sd_dog, 1))))
    cv2.circle(smask, (int(round(cent[i][0])), int(round(cent[i][1]))), r, 1, -1); nstars += 1
FREE = OK & (smask == 0)
print('stars masked:', nstars, '; free pixels %.0f%%' % (100 * FREE.mean()))

# ---- sky plane per colour
SKYM = FREE & (RR >= SKY_R0) & (RR < SKY_R1)
U, V = (xx - ccx) / 100.0, (yy - ccy) / 100.0
plane = []
for k in range(3):
    v = ST[k][SKYM]; X = np.column_stack([np.ones(SKYM.sum()), U[SKYM], V[SKYM]]); keep = np.ones(len(v), bool)
    for _ in range(6):
        co, *_ = np.linalg.lstsq(X[keep], v[keep], rcond=None); res = v - X @ co; keep = np.abs(res) < 3 * res[keep].std()
    plane.append(co.tolist())
def flatten(A):
    return np.stack([A[k] - (plane[k][0] + plane[k][1] * U + plane[k][2] * V) for k in range(3)])
ST, ODD, EVEN, ONE = flatten(ST), flatten(ODD), flatten(EVEN), flatten(ONE)
DIFF = (ODD - EVEN) / 2

# ---- per-pixel noise
def pix_noise(A, m=SKYM):
    return [clipped_stats(A[k][m])[1] for k in range(3)]
noise = {n: pix_noise(A) for n, A in (('stack', ST), ('single_reference_frame', ONE), ('odd', ODD), ('even', EVEN), ('half_difference', DIFF))}
def binned_noise(A, b):
    hb, wb = hh // b, ww // b
    Ab = A[:, :hb * b, :wb * b].reshape(3, hb, b, wb, b).mean((2, 4)); mb = SKYM[:hb * b, :wb * b].reshape(hb, b, wb, b).all((1, 3))
    return [clipped_stats(Ab[k][mb])[1] for k in range(3)]
noise['stack_2x2_mean'] = binned_noise(ST, 2); noise['stack_4x4_mean'] = binned_noise(ST, 4)
noise['stack_gauss2'] = [clipped_stats(cv2.GaussianBlur(np.where(FREE, ST[k], 0).astype(np.float32), (0, 0), 2.0)[SKYM & (cv2.erode(FREE.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)])[1] for k in range(3)]
print('noise per px (R, G, B DN):', {k: [round(x, 2) for x in v] for k, v in noise.items()})

# ---- the shell: annulus mean, and the same annulus on blank sky
ANN = (RR >= SHELL_R0) & (RR < SHELL_R1)
def region_mean(A, m): return [float(A[k][m].mean()) for k in range(3)]
shell = {n: region_mean(A, ANN & FREE) for n, A in (('stack', ST), ('odd', ODD), ('even', EVEN), ('single_reference_frame', ONE))}
oy, ox = np.mgrid[-SHELL_R1:SHELL_R1 + 1, -SHELL_R1:SHELL_R1 + 1]; tmpl = (np.hypot(ox, oy) >= SHELL_R0) & (np.hypot(ox, oy) < SHELL_R1)
ctrl = {n: [] for n in shell}; ctrl_pos = []
step = SHELL_R1                  # neighbouring places overlap by half: the scatter is still that of one place
for py in range(SHELL_R1, hh - SHELL_R1, step):
    for px in range(SHELL_R1, ww - SHELL_R1, step):
        if not (330 <= np.hypot(px - ccx, py - ccy) <= SKY_R1): continue
        sub = FREE[py - SHELL_R1:py + SHELL_R1 + 1, px - SHELL_R1:px + SHELL_R1 + 1] & tmpl
        if not OK[py - SHELL_R1:py + SHELL_R1 + 1, px - SHELL_R1:px + SHELL_R1 + 1][tmpl].all() or sub.sum() < 0.6 * tmpl.sum(): continue
        ctrl_pos.append([px + x0, py + y0])
        for n, A in (('stack', ST), ('odd', ODD), ('even', EVEN), ('single_reference_frame', ONE)):
            ctrl[n].append([float(A[k][py - SHELL_R1:py + SHELL_R1 + 1, px - SHELL_R1:px + SHELL_R1 + 1][sub].mean()) for k in range(3)])
ctrl = {n: np.array(v) for n, v in ctrl.items()}
snr = {}
for n in shell:
    mu = ctrl[n].mean(0); sd = ctrl[n].std(0, ddof=1)
    npx = int((ANN & FREE).sum()); pn = noise['stack_4x4_mean'] if n == 'stack' else ([v * noise['stack_4x4_mean'][k] / noise['stack'][k] for k, v in enumerate(noise[n])])
    stat = [v / np.sqrt(npx / 16.0) for v in pn]
    snr[n] = dict(shell_mean_dn=dict(zip('RGB', [round(v, 3) for v in shell[n]])), pixels=npx, pixel_noise_error_of_mean_dn=dict(zip('RGB', [round(v, 3) for v in stat])),
                  signal_to_pixel_noise=dict(zip('RGB', [round((s_ - m) / d, 1) for s_, m, d in zip(shell[n], mu, stat)])), blank_sky_mean_dn=dict(zip('RGB', [round(v, 3) for v in mu])),
                  blank_sky_scatter_dn=dict(zip('RGB', [round(v, 3) for v in sd])), signal_to_sky_structure=dict(zip('RGB', [round((s_ - m) / d, 1) for s_, m, d in zip(shell[n], mu, sd)])))
print('blank-sky positions:', len(ctrl_pos))
for n, v in snr.items(): print(' ', n, v)

# ---- radial profile (rings of 4 px), median and mean of star-free pixels
edges = list(range(0, 24, 2)) + list(range(24, 160, 4)) + list(range(160, 260, 10))
prof = []
for a, b in zip(edges[:-1], edges[1:]):
    m = (RR >= a) & (RR < b) & (FREE if a >= 10 else OK)
    if m.sum() < 5: continue
    prof.append(dict(r_px=[a, b], r_arcsec=[round(a * SCALE, 1), round(b * SCALE, 1)], n_px=int(m.sum()),
                     median_dn=dict(zip('RGB', [round(float(np.median(ST[k][m])), 3) for k in range(3)])), mean_dn=dict(zip('RGB', [round(float(ST[k][m].mean()), 3) for k in range(3)])),
                     odd_mean_g=round(float(ODD[1][m].mean()), 3), even_mean_g=round(float(EVEN[1][m].mean()), 3),
                     mean_error_g=round(float(noise['half_difference'][1] / np.sqrt(m.sum()) * 2.0), 3)))
# ---- the central star's own light at those radii, from comparison stars
ref_stars = [r for r in jload('step2_stars.json') if r['stamp'] == S7['reference']][0]['stars']
def ring_profile(A, px, py, mask, X, Y):
    rr = np.hypot(X - px, Y - py); out = []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (rr >= a) & (rr < b) & mask
        out.append(float(np.median(A[m])) if m.sum() >= 5 else np.nan)
    return np.array(out)
mid = np.array([(a + b) / 2 for a, b in zip(edges[:-1], edges[1:])]); match = (mid >= 6) & (mid < 12)
own = ring_profile(ST[1], ccx, ccy, FREE | (RR < 12), xx, yy)
own_ring_max = float(ST[:, (RR >= 6) & (RR < 12)].max())
assert own_ring_max < 0.8 * SAT_DN, own_ring_max
# the whole stacked frame, for comparison stars as bright as possible (clipped cores are fine: the match ring is not)
FULL = np.load(W_('stack_mean.npy'), mmap_mode='r'); covf = np.load(W_('cover.npy')) == N
Gf = np.where(covf, (FULL[1] + FULL[2]) / 2, 0).astype(np.float32)
dogf = cv2.GaussianBlur(Gf, (0, 0), 1.5) - cv2.GaussianBlur(Gf, (0, 0), 6.0)
nlf, labf, statsf, centf = cv2.connectedComponentsWithStats(((dogf > 5 * sd_dog) & covf).astype(np.uint8), connectivity=8)
circ = []
for i in range(1, nlf):
    a_ = statsf[i, cv2.CC_STAT_AREA]
    if a_ < 3: continue
    x_, y_ = centf[i]; pk = float(dogf[int(round(y_)), int(round(x_))])
    circ.append((x_, y_, int(round(4 + 2.5 * np.sqrt(a_) + 2 * np.log10(max(pk / sd_dog, 1))))))
circ = np.array(circ)
CUT = 170
cy_, cx_ = np.mgrid[-CUT:CUT + 1, -CUT:CUT + 1]
comp = []; tried = 0
for s_ in sorted(ref_stars, key=lambda s_: -s_['flux']):
    if len(comp) >= 12 or tried >= 80: break
    X0, Y0 = int(round(s_['x'])), int(round(s_['y']))
    if not (CUT <= X0 < w2 - CUT and CUT <= Y0 < h2 - CUT) or np.hypot(s_['x'] - cx, s_['y'] - cy) < 400: continue
    if not covf[Y0 - CUT:Y0 + CUT + 1, X0 - CUT:X0 + CUT + 1].all(): continue
    tried += 1
    sub = Gf[Y0 - CUT:Y0 + CUT + 1, X0 - CUT:X0 + CUT + 1].astype(np.float64)
    fx, fy = s_['x'] - X0, s_['y'] - Y0
    rr_ = np.hypot(cx_ - fx, cy_ - fy)
    ring = (rr_ >= 6) & (rr_ < 12)
    if FULL[:, Y0 - CUT:Y0 + CUT + 1, X0 - CUT:X0 + CUT + 1][:, ring].max() > 0.8 * SAT_DN: continue
    mk = np.zeros(sub.shape, np.uint8)
    for (qx, qy, qr) in circ:
        if abs(qx - X0) > CUT + qr or abs(qy - Y0) > CUT + qr or np.hypot(qx - s_['x'], qy - s_['y']) < 6: continue
        cv2.circle(mk, (int(round(qx - X0 + CUT)), int(round(qy - Y0 + CUT))), int(qr), 1, -1)
    p = ring_profile(sub, fx, fy, mk == 0, cx_, cy_)
    bg = np.nanmedian(p[(mid > 130) & (mid < 165)]) if np.isfinite(p[(mid > 130) & (mid < 165)]).any() else np.nan
    if not np.isfinite(bg): continue
    p = p - bg
    if not np.all(np.isfinite(p[match])) or np.any(p[match] <= 0): continue
    k = float(np.median(own[match] / p[match]))
    comp.append(dict(stack_px=[float(s_['x']), float(s_['y'])], flux_dn_reference=s_['flux'], saturated_core=s_['saturated'], local_background_dn=float(bg), scale_to_central_star=k, predicted=(k * p).tolist()))
print('comparison stars: %d of %d tried; scale to the central star %s' % (len(comp), tried, [round(c['scale_to_central_star'], 2) for c in comp]))
# combined with weights 1 / k^2: a comparison star's noise is carried out multiplied by k, so the brightest count most
PR = np.array([c['predicted'] for c in comp]); KK = np.array([c['scale_to_central_star'] for c in comp]); WK = np.where(np.isfinite(PR), 1.0 / KK[:, None] ** 2, 0)
pred = np.nansum(np.nan_to_num(PR) * WK, 0) / np.maximum(WK.sum(0), 1e-12)
bright = KK < 6                                                   # comparison stars within a factor 6 of the central star
pred_lo = np.nanmin(PR[bright], axis=0); pred_hi = np.nanmax(PR[bright], axis=0)
starlight = [dict(r_px=[a, b], r_arcsec=[round(a * SCALE, 1), round(b * SCALE, 1)], seen_median_g=round(float(o), 3), central_star_light_predicted_g=round(float(p), 3), predicted_range_bright_comparisons=[round(float(l), 3), round(float(h), 3)])
             for a, b, o, p, l, h in zip(edges[:-1], edges[1:], own, pred, pred_lo, pred_hi) if a >= 6]
inshell = (mid >= SHELL_R0) & (mid < SHELL_R1)
w_ann = np.array([((RR >= a) & (RR < b) & FREE).sum() for a, b in zip(edges[:-1], edges[1:])], float)
starlight_frac = float(np.nansum((pred * w_ann)[inshell]) / np.nansum((own * w_ann)[inshell]))
print('the central star\'s own light is %.1f%% of what is seen in the shell annulus' % (100 * starlight_frac))
for r in starlight:
    if r['r_px'][0] < 120: print('  r %5.1f-%5.1f"  seen %8.2f  star light %8.2f  (%.2f..%.2f)' % (*r['r_arcsec'], r['seen_median_g'], r['central_star_light_predicted_g'], *r['predicted_range_bright_comparisons']))

# ---- is it real: the shell's shape in the two halves
def smooth(A): return cv2.GaussianBlur(np.where(FREE, A, 0).astype(np.float32), (0, 0), 3.0) / np.maximum(cv2.GaussianBlur(FREE.astype(np.float32), (0, 0), 3.0), 1e-3)
So, Se = smooth(ODD[1]), smooth(EVEN[1])
def corr(m):
    a, b = So[m], Se[m]; a = a - a.mean(); b = b - b.mean(); return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
inner = ANN & FREE
r_shell = corr(inner)
# the same, with each half's own ring-mean profile removed (structure beyond the round profile: lobes and rims)
def deprof(Sx):
    out = Sx.copy()
    for a, b in zip(range(SHELL_R0, SHELL_R1, 4), range(SHELL_R0 + 4, SHELL_R1 + 4, 4)):
        m = (RR >= a) & (RR < b) & FREE; out[m] -= Sx[m].mean()
    return out
Do, De = deprof(So), deprof(Se)
a, b = Do[inner] - Do[inner].mean(), De[inner] - De[inner].mean(); r_struct = float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
r_ctrl = []
for px, py in ctrl_pos:
    m = np.zeros((hh, ww), bool); qx, qy = px - x0, py - y0
    m[qy - SHELL_R1:qy + SHELL_R1 + 1, qx - SHELL_R1:qx + SHELL_R1 + 1] = tmpl; m &= FREE
    r_ctrl.append(corr(m))
r_ctrl = np.array(r_ctrl)
print('halves: shape correlation inside the shell r = %.3f (round profile removed: %.3f); on blank sky %.3f +- %.3f (max %.3f, %d places)' % (r_shell, r_struct, r_ctrl.mean(), r_ctrl.std(), r_ctrl.max(), len(r_ctrl)))

# ---- where the shell ends: the green profile against the blank-sky scatter of a ring
edge = None
for p_ in prof:
    if p_['r_px'][0] >= 40 and p_['mean_dn']['G'] < 0.5 * np.mean([q['mean_dn']['G'] for q in prof if 24 <= q['r_px'][0] < 60]):
        edge = p_['r_arcsec'][0]; break

# ---- colour of the shell (camera daylight white balance, as the picture)
f0 = jload('step1.json')['frames'][0]; wbd = np.array(f0['wb_daylight'][:3]) / f0['wb_daylight'][1]
sh = np.array(shell['stack']) * wbd
colour = dict(white_balanced_daylight=dict(zip('RGB', [round(float(v), 3) for v in sh])), ratio_to_green=dict(zip('RGB', [round(float(v / sh[1]), 3) for v in sh])), wb=wbd.tolist())

# ---- stars: half-flux diameter in the stack and in the reference frame alone
rows = []
for s in sorted(ref_stars, key=lambda s: -s['flux']):
    if len(rows) >= 40: break
    px, py = s['x'] - x0, s['y'] - y0
    if s['saturated'] or not (40 <= px < ww - 40 and 40 <= py < hh - 40) or np.hypot(px - ccx, py - ccy) < 150 or s['flux'] < 3000: continue
    if any(np.hypot(o['x'] - s['x'], o['y'] - s['y']) < 30 and o is not s for o in ref_stars): continue
    a_ = measure(ST[1].astype(np.float32), px, py); b_ = measure(ONE[1].astype(np.float32), px, py)
    if a_ and b_: rows.append((4 * a_['hfr'], 4 * b_['hfr'], a_['elong'], b_['elong']))
rows = np.array(rows)
# measure() works on the plane grid: 4 x hfr is the HFD in sensor px; times the sensor scale for arcsec
stars = dict(n=len(rows), hfd_stack_arcsec=float(np.median(rows[:, 0]) * SCALE / 2), hfd_single_reference_arcsec=float(np.median(rows[:, 1]) * SCALE / 2),
             elong_stack=float(np.median(rows[:, 2])), elong_single_reference=float(np.median(rows[:, 3])),
             frames_used_hfd_arcsec=dict(median=float(np.median([u['hfd_arcsec'] for u in S6['used']])), range=[min(u['hfd_arcsec'] for u in S6['used']), max(u['hfd_arcsec'] for u in S6['used'])]))
print('stars:', stars)
out = dict(box_stack_px=dict(x0=x0, y0=y0, width=ww, height=hh), central_star_stack_px=[cx, cy], scale_arcsec_per_px=SCALE,
           sky_plane=dict(coefficients=dict(zip('RGB', plane)), terms='DN = c0 + c1 (x - x_star) / 100 + c2 (y - y_star) / 100', ring_px=[SKY_R0, SKY_R1], pixels=int(SKYM.sum())),
           stars_masked=nstars, noise_per_px_dn=noise, shell_annulus_px=[SHELL_R0, SHELL_R1], shell_annulus_arcsec=[round(SHELL_R0 * SCALE, 1), round(SHELL_R1 * SCALE, 1)],
           shell=snr, blank_sky_positions=len(ctrl_pos), profile=prof, shell_half_brightness_radius_arcsec=edge,
           central_star_light=dict(combined='weighted mean of the comparison stars\' predictions, weights 1 / k^2 (k = the scale to the central star); range = the comparison stars within a factor 6 of the central star', central_star_match_ring_max_dn=own_ring_max, comparison_stars=[{k: v for k, v in c.items() if k != 'predicted'} for c in comp], match_ring_px=[6, 12], rings=starlight, fraction_of_shell_annulus_light=starlight_frac),
           halves=dict(shape_correlation_in_shell=r_shell, shape_correlation_round_profile_removed=r_struct, blank_sky_correlation_mean=float(r_ctrl.mean()), blank_sky_correlation_std=float(r_ctrl.std()), blank_sky_correlation_max=float(r_ctrl.max()), smoothing_sigma_px=3.0),
           shell_colour=colour, stars=stars)
jsave(out, 'step9_measure.json')
