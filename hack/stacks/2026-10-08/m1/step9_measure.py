"""Step 9: is the nebula there, how strongly, and is any structure inside it real? Numbers only; no pixels are changed
for the picture here.

All on the stack grid (step 7), in a box 1300 px wide around M1's catalogue position, raw camera units (DN of the 14-bit
RAW per 15 s frame at the clearest frame's transparency at M1), colours R, G = mean of G1 and G2, B, no white balance.

  sky        a plane per colour (3 numbers) fitted to the sky 464 to 650 px (6 to 8.4 arcmin) from M1, stars masked,
             3-sigma clipped, and subtracted. Inside it is the plane's straight continuation.
  stars      compact sources found on a difference of Gaussians (sigma 1.5 minus sigma 6 px, which ignores the smooth
             nebula) above 5 sigma, masked with a circle growing with brightness.
  shape      the nebula's own light smoothed by an 8 px Gaussian (stars masked, normalised convolution); its second
             moments within 250 px give the long axis's direction and the axis ratio; the ellipses below follow them.
  noise      per pixel: robust std of the sky, for the stack, the reference frame alone, the two half stacks, half their
             difference; also after a 2 x 2 and 4 x 4 mean and a 2 px Gaussian. For a region: the same ellipse laid on
             blank sky at every place on a grid where it fits (centre 464 px or more from M1); the scatter of those
             means is the uncertainty of a mean over that region, including faint stars and sky structure (no flat).
  nebula     the masked mean inside the inner ellipse (semi-axes A_IN x A_IN * axis ratio) against that scatter; the
             profile in elliptical rings; where it falls to half its central level and into the sky.
  structure  is there anything beyond a smooth oval, and is it real? Each half stack's green (stars masked) is
             band-passed (Gaussian sigma s minus Gaussian sigma 4 s, s = 1.5 and 3 px: detail of about 3 to 25 arcsec,
             where M1's filaments and its bright inner parts would show) and the two halves are correlated inside the
             nebula; the same is done at every blank-sky place. Real structure repeats in both halves (correlation well
             above blank sky); noise does not. Also the amplitude: the band-passed light's rms in the nebula against the
             rms the noise alone gives (from blank sky).
  pulsar     the star nearest the catalogue position on the difference of Gaussians, and its significance.
  stars      half-flux diameter of isolated, unclipped stars in the stack and in the reference frame alone (same grid).
Written new for M1 after this night's ngc1514/step9_measure.py (same sky, noise, blank-sky and half-stack methods)."""
import os
import numpy as np, cv2
from common import *
from step2_stars import measure

SKY_R0, SKY_R1 = 464, 650
BOX = 650
A_IN = 150                 # px, semi-major axis of the inner ellipse (1.9 arcmin)
S8 = jload('step8_solve.json'); S7 = jload('step7.json'); S6 = jload('step6_select.json')
SCALE = float(np.mean(S8['scale_arcsec_per_px'])); N = len(S7['frames'])
cx, cy = S8['target_catalogue']['stack_px']
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
det = (dog > 5 * sd_dog) & OK
nl, lab, stats, cent = cv2.connectedComponentsWithStats(det.astype(np.uint8), connectivity=8)
smask = np.zeros((hh, ww), np.uint8); nstars = 0; star_list = []
for i in range(1, nl):
    a = stats[i, cv2.CC_STAT_AREA]
    if a < 3: continue
    pk = float(dog[lab == i].max()); r = int(round(4 + 2.5 * np.sqrt(a) + 2 * np.log10(max(pk / sd_dog, 1))))
    cv2.circle(smask, (int(round(cent[i][0])), int(round(cent[i][1]))), r, 1, -1); nstars += 1
    star_list.append((float(cent[i][0]), float(cent[i][1]), pk / sd_dog, a))
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


def msmooth(A, sig, m=None):
    m = FREE if m is None else m
    return cv2.GaussianBlur(np.where(m, A, 0).astype(np.float32), (0, 0), sig) / np.maximum(cv2.GaussianBlur(m.astype(np.float32), (0, 0), sig), 1e-3)


# ---- shape of the nebula from its own light
Gs8 = msmooth(ST[1], 8.0)
reg = (RR < 250) & OK
wgt = np.clip(Gs8[reg], 0, None); wgt = wgt * (wgt > 0.15 * np.percentile(wgt, 99.5))
mx = (wgt * xx[reg]).sum() / wgt.sum(); my = (wgt * yy[reg]).sum() / wgt.sum()
dx_, dy_ = xx[reg] - mx, yy[reg] - my
mxx = (wgt * dx_ ** 2).sum() / wgt.sum(); myy = (wgt * dy_ ** 2).sum() / wgt.sum(); mxy = (wgt * dx_ * dy_).sum() / wgt.sum()
tr_, det_ = mxx + myy, mxx * myy - mxy ** 2; disc = np.sqrt(max(tr_ ** 2 / 4 - det_, 0)); l1, l2 = tr_ / 2 + disc, tr_ / 2 - disc
theta = 0.5 * np.arctan2(2 * mxy, mxx - myy)            # long axis, radians from +x towards +y (image)
AXR = float(np.sqrt(l2 / l1))
# position angle on the sky (east of north) from step 8's map
Mmap = np.array([[S8['affine_xi_eta_arcsec']['cx'][1], S8['affine_xi_eta_arcsec']['cx'][2]], [S8['affine_xi_eta_arcsec']['cy'][1], S8['affine_xi_eta_arcsec']['cy'][2]]]) / 1000
d_sky = Mmap @ np.array([np.cos(theta), np.sin(theta)]); PA = float(np.degrees(np.arctan2(d_sky[0], d_sky[1])) % 180)
light_c = np.array([mx + x0, my + y0]); d_lc = Mmap @ (light_c - np.array([cx, cy]))
print('shape: long axis at %.1f deg in the image, position angle %.0f deg east of north, axis ratio %.2f; light centre %.1f arcsec from the catalogue (%+.1f E, %+.1f N)' % (np.degrees(theta), PA, AXR, np.hypot(*d_lc), *d_lc))
c_, s_ = np.cos(theta), np.sin(theta)
EA = ((xx - ccx) * c_ + (yy - ccy) * s_); EB = (-(xx - ccx) * s_ + (yy - ccy) * c_) / AXR
ER = np.hypot(EA, EB)                                       # elliptical radius: px along the long axis

# ---- per-pixel noise
def pix_noise(A, m=SKYM):
    return [clipped_stats(A[k][m])[1] for k in range(3)]
noise = {n: pix_noise(A) for n, A in (('stack', ST), ('single_reference_frame', ONE), ('odd', ODD), ('even', EVEN), ('half_difference', DIFF))}
def binned_noise(A, b):
    hb, wb = hh // b, ww // b
    Ab = A[:, :hb * b, :wb * b].reshape(3, hb, b, wb, b).mean((2, 4)); mb = SKYM[:hb * b, :wb * b].reshape(hb, b, wb, b).all((1, 3))
    return [clipped_stats(Ab[k][mb])[1] for k in range(3)]
noise['stack_2x2_mean'] = binned_noise(ST, 2); noise['stack_4x4_mean'] = binned_noise(ST, 4)
noise['single_2x2_mean'] = binned_noise(ONE, 2)
inner_free = SKYM & (cv2.erode(FREE.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)
noise['stack_gauss2'] = [clipped_stats(cv2.GaussianBlur(np.where(FREE, ST[k], 0).astype(np.float32), (0, 0), 2.0)[inner_free])[1] for k in range(3)]
print('noise per px (R, G, B DN):', {k: [round(x, 2) for x in v] for k, v in noise.items()})

# ---- the nebula: inner-ellipse mean, and the same ellipse on blank sky
INNER = ER < A_IN
def region_mean(A, m): return [float(A[k][m].mean()) for k in range(3)]
neb = {n: region_mean(A, INNER & FREE) for n, A in (('stack', ST), ('odd', ODD), ('even', EVEN), ('single_reference_frame', ONE))}
half = int(A_IN) + 2
oy, ox = np.mgrid[-half:half + 1, -half:half + 1]
tmpl = np.hypot(ox * c_ + oy * s_, (-ox * s_ + oy * c_) / AXR) < A_IN
ctrl = {n: [] for n in neb}; ctrl_pos = []
for py in range(half, hh - half, half):
    for px in range(half, ww - half, half):
        if not (SKY_R0 <= np.hypot(px - ccx, py - ccy)): continue
        sub = FREE[py - half:py + half + 1, px - half:px + half + 1] & tmpl
        if not OK[py - half:py + half + 1, px - half:px + half + 1][tmpl].all() or sub.sum() < 0.6 * tmpl.sum(): continue
        ctrl_pos.append([px, py])
        for n, A in (('stack', ST), ('odd', ODD), ('even', EVEN), ('single_reference_frame', ONE)):
            ctrl[n].append([float(A[k][py - half:py + half + 1, px - half:px + half + 1][sub].mean()) for k in range(3)])
ctrl = {n: np.array(v) for n, v in ctrl.items()}
snr = {}
npx = int((INNER & FREE).sum())
for n in neb:
    mu = ctrl[n].mean(0); sd = ctrl[n].std(0, ddof=1)
    snr[n] = dict(mean_dn=dict(zip('RGB', [round(v, 3) for v in neb[n]])), pixels=npx, blank_sky_mean_dn=dict(zip('RGB', [round(v, 3) for v in mu])),
                  blank_sky_scatter_dn=dict(zip('RGB', [round(v, 3) for v in sd])), signal_to_sky_structure=dict(zip('RGB', [round((s__ - m) / d, 1) for s__, m, d in zip(neb[n], mu, sd)])),
                  per_pixel_signal_to_noise_green=round(neb[n][1] / noise[n if n in noise else 'stack'][1], 2))
print('blank-sky places:', len(ctrl_pos))
for n, v in snr.items(): print(' ', n, v)

# ---- elliptical profile (rings of 10 px along the long axis)
prof = []
for a_ in range(0, 460, 10):
    m = (ER >= a_) & (ER < a_ + 10) & FREE
    if m.sum() < 20: continue
    prof.append(dict(a_px=[a_, a_ + 10], a_arcsec=[round(a_ * SCALE, 1), round((a_ + 10) * SCALE, 1)], n_px=int(m.sum()),
                     mean_dn=dict(zip('RGB', [round(float(ST[k][m].mean()), 3) for k in range(3)])), odd_g=round(float(ODD[1][m].mean()), 3), even_g=round(float(EVEN[1][m].mean()), 3),
                     error_g=round(float(noise['stack'][1] / np.sqrt(m.sum())), 3)))
centre = np.mean([p['mean_dn']['G'] for p in prof if p['a_px'][0] < 40])
half_a = next((p['a_px'][0] for p in prof if p['mean_dn']['G'] < 0.5 * centre), None)
# outside the nebula the profile does not fall to 0 but levels off a few DN up from 3 to 4.6 arcmin: the sky plane is
# fitted 6 to 8.4 arcmin out, and without a flat the sky glow is a dome (vignetting), brighter in the middle. The edge is
# where the profile comes down to that plateau (median of the rings 260 to 360 px) within 3 x its ring-to-ring scatter.
plat = [p['mean_dn']['G'] for p in prof if 260 <= p['a_px'][0] < 360]
plateau, plateau_sd = float(np.median(plat)), float(np.std(plat))
fade_a = next((p['a_px'][0] for p in prof if p['a_px'][0] > 60 and p['mean_dn']['G'] < plateau + 3 * max(plateau_sd, p['error_g'])), None)
print('central level %.1f DN green; half of it at %s px along the long axis; down to the plateau (%.2f +- %.2f DN, 3.4 to 4.6 arcmin) by %s px' % (centre, half_a, plateau, plateau_sd, fade_a))

# ---- structure: band-passed halves, correlated inside the nebula and on blank sky
NEBM = (ER < 220) & FREE                                   # where the nebula is: out to 220 px (2.8 arcmin) along the long axis
def band(A, s):
    return msmooth(A, s) - msmooth(A, 4 * s)
def corr(a, b, m):
    a = a[m] - a[m].mean(); b = b[m] - b[m].mean(); return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
structure = {}
half2 = 222
oy2, ox2 = np.mgrid[-half2:half2 + 1, -half2:half2 + 1]
tmpl2 = np.hypot(ox2 * c_ + oy2 * s_, (-ox2 * s_ + oy2 * c_) / AXR) < 220
ctrl2 = []
for py in range(half2, hh - half2, half2 // 2):
    for px in range(half2, ww - half2, half2 // 2):
        if np.hypot(px - ccx, py - ccy) < 464: continue
        if not OK[py - half2:py + half2 + 1, px - half2:px + half2 + 1][tmpl2].all(): continue
        ctrl2.append((px, py))
for s in (1.5, 3.0):
    Bo, Be, Bs = band(ODD[1], s), band(EVEN[1], s), band(ST[1], s)
    Bd = band(DIFF[1], s)
    r_in = corr(Bo, Be, NEBM)
    rc, rms_c, rmsd_c = [], [], []
    for px, py in ctrl2:
        m = np.zeros((hh, ww), bool); m[py - half2:py + half2 + 1, px - half2:px + half2 + 1] = tmpl2; m &= FREE
        if m.sum() < 0.6 * tmpl2.sum(): continue
        rc.append(corr(Bo, Be, m)); rms_c.append(float(Bs[m].std())); rmsd_c.append(float(Bd[m].std()))
    rc = np.array(rc)
    rms_in = float(Bs[NEBM].std()); rmsd_in = float(Bd[NEBM].std())
    structure['sigma_%.1f_px' % s] = dict(band='Gaussian %.1f px minus Gaussian %.1f px (detail of about %.0f to %.0f arcsec)' % (s, 4 * s, 2.355 * s * SCALE, 2.355 * 4 * s * SCALE),
                                           halves_correlation_in_nebula=round(r_in, 3), blank_sky_correlation_mean=round(float(rc.mean()), 3), blank_sky_correlation_std=round(float(rc.std()), 3),
                                           blank_sky_correlation_max=round(float(rc.max()), 3), blank_sky_places=int(len(rc)),
                                           significance_sigma=round(float((r_in - rc.mean()) / rc.std()), 1),
                                           stack_rms_in_nebula_dn=round(rms_in, 3), stack_rms_blank_sky_dn=round(float(np.median(rms_c)), 3),
                                           half_difference_rms_in_nebula_dn=round(rmsd_in, 3), half_difference_rms_blank_sky_dn=round(float(np.median(rmsd_c)), 3))
    print('structure, band sigma %.1f px: halves r = %.3f in the nebula; blank sky %.3f +- %.3f (max %.3f, %d places); rms in nebula %.2f DN against %.2f on blank sky (half difference %.2f / %.2f)' % (
        s, r_in, rc.mean(), rc.std(), rc.max(), len(rc), rms_in, np.median(rms_c), rmsd_in, np.median(rmsd_c)))

# the same with the smooth oval itself taken out: each half smoothed by 3 px, minus its own mean in elliptical rings
# (8 px) about the centre; on blank sky the same, with rings about each place's centre
So3, Se3 = msmooth(ODD[1], 3.0), msmooth(EVEN[1], 3.0)
def deprof_corr(px, py, m_full):
    ys, xs = slice(py - half2, py + half2 + 1), slice(px - half2, px + half2 + 1)
    m = m_full[ys, xs] & FREE[ys, xs]
    er = np.hypot(ox2 * c_ + oy2 * s_, (-ox2 * s_ + oy2 * c_) / AXR)
    a, b = So3[ys, xs].copy(), Se3[ys, xs].copy()
    for a_ in range(0, 230, 8):
        r_ = (er >= a_) & (er < a_ + 8) & m
        if r_.sum(): a[r_] -= a[r_].mean(); b[r_] -= b[r_].mean()
    return corr(a, b, m)
full_t = np.zeros((hh, ww), bool)
r_dep = deprof_corr(int(round(ccx)), int(round(ccy)), (ER < 220))
r_dep_c = []
for px, py in ctrl2:
    m = np.zeros((hh, ww), bool); m[py - half2:py + half2 + 1, px - half2:px + half2 + 1] = tmpl2
    if (m & FREE).sum() < 0.6 * tmpl2.sum(): continue
    r_dep_c.append(deprof_corr(px, py, m))
r_dep_c = np.array(r_dep_c)
structure['oval_removed_3px'] = dict(how='each half smoothed by 3 px, its own mean in elliptical rings (8 px) taken off, correlated inside the nebula (out to 220 px); blank sky: the same about each place',
                                     halves_correlation_in_nebula=round(r_dep, 3), blank_sky_correlation_mean=round(float(r_dep_c.mean()), 3), blank_sky_correlation_std=round(float(r_dep_c.std()), 3),
                                     blank_sky_correlation_max=round(float(r_dep_c.max()), 3), significance_sigma=round(float((r_dep - r_dep_c.mean()) / r_dep_c.std()), 1))
print('oval removed: halves r = %.3f in the nebula; blank sky %.3f +- %.3f (max %.3f)' % (r_dep, r_dep_c.mean(), r_dep_c.std(), r_dep_c.max()))
# and the whole smooth light (the oval included) for comparison: the halves smoothed by 3 px, correlated in the nebula
r_whole = corr(msmooth(ODD[1], 3.0), msmooth(EVEN[1], 3.0), NEBM)
structure['oval_included_3px'] = dict(halves_correlation_in_nebula=round(r_whole, 3))
print('oval included: halves r = %.3f' % r_whole)

# ---- the pulsar: nearest compact source to the catalogue position on the difference of Gaussians
sl = np.array(star_list); dd = np.hypot(sl[:, 0] - ccx, sl[:, 1] - ccy); k = int(np.argmin(dd))
pk_here = float(dog[int(round(ccy)) - 4:int(round(ccy)) + 5, int(round(ccx)) - 4:int(round(ccx)) + 5].max() / sd_dog)
pulsar = dict(nearest_5sigma_source_px_from_catalogue=float(dd[k]), nearest_offset_arcsec=float(dd[k] * SCALE), nearest_significance_sigma=float(sl[k, 2]),
              nearest_offset_east_north_arcsec=(Mmap @ np.array([sl[k, 0] - ccx, sl[k, 1] - ccy])).tolist(), peak_within_4px_of_catalogue_sigma=pk_here)
print('pulsar check:', pulsar)

# ---- colour of the nebula (camera daylight white balance, as the picture)
f0 = jload('step1.json')['frames'][0]; wbd = np.array(f0['wb_daylight'][:3]) / f0['wb_daylight'][1]
nb = np.array(neb['stack']) * wbd
colour = dict(white_balanced_daylight=dict(zip('RGB', [round(float(v), 3) for v in nb])), ratio_to_green=dict(zip('RGB', [round(float(v / nb[1]), 3) for v in nb])), wb=wbd.tolist())
# outer part against inner part: the filament-rich rim is redder in a camera (H-alpha) than the synchrotron core
OUTER = (ER >= A_IN * 0.67) & (ER < A_IN * 1.4) & FREE; CORE = (ER < A_IN * 0.67) & FREE
col_parts = {}
for nm, m in (('core', CORE), ('rim', OUTER)):
    v = np.array([ST[k][m].mean() for k in range(3)]) * wbd
    col_parts[nm] = dict(ratio_to_green=dict(zip('RGB', [round(float(x / v[1]), 3) for x in v])), green_dn=round(float(v[1]), 2), pixels=int(m.sum()))
colour['core_and_rim'] = col_parts
print('colour:', colour)

# ---- stars: half-flux diameter in the stack and in the reference frame alone
ref_stars = [r for r in jload('step2_stars.json') if r['stamp'] == S7['reference']][0]['stars']
rows = []
for s in sorted(ref_stars, key=lambda s: -s['flux']):
    if len(rows) >= 40: break
    px, py = s['x'] - x0, s['y'] - y0
    if s['saturated'] or not (40 <= px < ww - 40 and 40 <= py < hh - 40) or np.hypot(px - ccx, py - ccy) < 300 or s['flux'] < 3000: continue
    if any(np.hypot(o['x'] - s['x'], o['y'] - s['y']) < 30 and o is not s for o in ref_stars): continue
    a_ = measure(ST[1].astype(np.float32), px, py); b_ = measure(ONE[1].astype(np.float32), px, py)
    if a_ and b_: rows.append((4 * a_['hfr'], 4 * b_['hfr'], a_['elong'], b_['elong']))
rows = np.array(rows)
stars = dict(n=len(rows), hfd_stack_arcsec=float(np.median(rows[:, 0]) * SCALE / 2), hfd_single_reference_arcsec=float(np.median(rows[:, 1]) * SCALE / 2),
             elong_stack=float(np.median(rows[:, 2])), elong_single_reference=float(np.median(rows[:, 3])),
             frames_used_hfd_arcsec=dict(median=float(np.median([u['hfd_arcsec'] for u in S6['used']])), range=[min(u['hfd_arcsec'] for u in S6['used']), max(u['hfd_arcsec'] for u in S6['used'])]))
print('stars:', stars)

# ---- dark patches in the sky near the nebula: the green smoothed by 12 px (stars masked), a plane taken off the sky
# outside 260 px (elliptical), within the picture's crop (300 x 400 px either side of M1 in the stack); the two deepest
# places, and the same places in the half stacks and the single frame. In both halves = not noise.
CROP = (np.abs(xx - ccx) < 300) & (np.abs(yy - ccy) < 400)
SKY2 = CROP & (ER > 260)
sm12 = {n: msmooth(A[1], 12.0) for n, A in (('stack', ST), ('odd', ODD), ('even', EVEN), ('single_reference_frame', ONE))}
for n in sm12:
    v = sm12[n][SKY2]; X = np.column_stack([np.ones(SKY2.sum()), U[SKY2], V[SKY2]]); co, *_ = np.linalg.lstsq(X, v, rcond=None)
    sm12[n] = sm12[n] - (co[0] + co[1] * U + co[2] * V)
work = np.where(SKY2, sm12['stack'], np.inf); patches = []
sd12 = float(sm12['stack'][SKY2].std())
for _ in range(2):
    i = int(np.argmin(work)); py_, px_ = np.unravel_index(i, work.shape)
    off = Mmap @ np.array([px_ - ccx, py_ - ccy]) / 60
    patches.append(dict(stack_px=[int(px_ + x0), int(py_ + y0)], offset_east_north_arcmin=[round(float(off[0]), 2), round(float(off[1]), 2)], depth_dn={n: round(float(sm12[n][py_, px_]), 1) for n in sm12},
                        smoothed_sky_sd_dn=round(sd12, 2)))
    work[max(py_ - 60, 0):py_ + 60, max(px_ - 60, 0):px_ + 60] = np.inf
print('dark patches:', patches)

# a look for the eye (work folder only): the two halves and the stack, smoothed 2 px, same scale
vis = [msmooth(A[1], 2.0)[int(ccy) - 300:int(ccy) + 300, int(ccx) - 400:int(ccx) + 400] for A in (ODD, EVEN, ST)]
lo_, hi_ = -10.0, max(60.0, float(np.percentile(vis[2], 99.0)))
cv2.imwrite(W_('halves_look.png'), np.hstack([(np.clip((v - lo_) / (hi_ - lo_), 0, 1) ** 0.6 * 255).astype(np.uint8) for v in vis]))

out = dict(box_stack_px=dict(x0=x0, y0=y0, width=ww, height=hh), catalogue_stack_px=[cx, cy], scale_arcsec_per_px=SCALE,
           sky_plane=dict(coefficients=dict(zip('RGB', plane)), terms='DN = c0 + c1 (x - x_M1) / 100 + c2 (y - y_M1) / 100', ring_px=[SKY_R0, SKY_R1], pixels=int(SKYM.sum())),
           stars_masked=nstars, noise_per_px_dn=noise,
           shape=dict(long_axis_image_deg=float(np.degrees(theta)), position_angle_deg_east_of_north=PA, axis_ratio=AXR, light_centre_stack_px=light_c.tolist(),
                      light_centre_from_catalogue_arcsec=float(np.hypot(*d_lc)), light_centre_offset_east_north_arcsec=d_lc.tolist()),
           inner_ellipse_px=[A_IN, A_IN * AXR], inner_ellipse_arcmin=[round(2 * A_IN * SCALE / 60, 2), round(2 * A_IN * AXR * SCALE / 60, 2)],
           nebula=snr, blank_sky_places=len(ctrl_pos), profile=prof, central_level_green_dn=float(centre),
           half_level_along_long_axis_px=half_a, fades_into_sky_along_long_axis_px=fade_a, plateau_green_dn=plateau, plateau_ring_scatter_dn=plateau_sd,
           size_arcmin=dict(half_level=[round(2 * half_a * SCALE / 60, 2), round(2 * half_a * AXR * SCALE / 60, 2)] if half_a else None,
                            to_the_sky=[round(2 * fade_a * SCALE / 60, 2), round(2 * fade_a * AXR * SCALE / 60, 2)] if fade_a else None),
           structure=structure, pulsar=pulsar, colour=colour, stars=stars, dark_patches=patches)
jsave(out, 'step9_measure.json')
