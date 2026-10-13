"""Step 11: what is seen of the nebula, and is the structure inside it real? Numbers only; no pixel of the picture is
changed here. Adapted from last week's hack/stacks/2026-10-08/m1/step9_measure.py (the same tests, so the two nights can
be compared number for number), on tonight's stack arrays.

All on the well-covered rectangle of step 9, raw camera units (DN of the 14-bit RAW per 15 s frame), colours R,
G = mean of G1 and G2, B, no white balance.

  sky        a plane per colour (3 numbers) fitted to the sky 464 to 650 px (6 to 8.4 arcmin) from M1's catalogue place,
             stars masked, 3-sigma clipped, and subtracted everywhere. Under the nebula it is the plane's continuation.
  stars      compact sources found on a difference of Gaussians (sigma 1.5 minus sigma 6 px, which ignores the smooth
             nebula) above 5 sigma, masked with a circle growing with brightness.
  shape      the nebula's own light smoothed by an 8 px Gaussian (stars masked, normalised convolution); its second
             moments within 250 px give the centre, the long axis's direction and the axis ratio.
  noise      per pixel: robust std of the sky ring, for the stack, the reference frame alone, the two half stacks (odd and
             even frames), half their difference. For a region: the same ellipse laid on blank sky at every place on a
             grid where it fits (464 px or more from M1); the scatter of those means is the uncertainty of a mean over
             that region, including faint stars and what the flat left.
  nebula     the masked mean inside the inner ellipse (semi-axes A_IN x A_IN * axis ratio) against that scatter; the
             profile in elliptical rings; where it falls to half its central level and into the sky.
  structure  THE HALF-STACK PROOF. Is there anything beyond a smooth oval, and does it repeat? Each half stack (stars
             masked) is band-passed (Gaussian sigma s minus Gaussian sigma 4 s, s = 1.5, 3 and 6 px (6 px: the scale of the colour patches the picture shows): detail of about 3 to
             22 arcsec, where the filaments and the bright inner wisps would show) and the two halves are correlated
             inside the nebula; the same is done at every blank-sky place. Real structure repeats in both halves
             (correlation well above every blank-sky place); noise does not. Done for green, for red, for the
             noise-weighted luminance, and for the RED EXCESS (red minus the nebula's own mean red : green ratio times
             green): the filaments shine in H-alpha and [N II], which only the red plane sees, while the smooth
             synchrotron glow is in all three, so the red excess is the filaments' own channel. Also the amplitude: the
             square root of the halves' covariance in the nebula is the rms of the structure that is really there (DN),
             set against the noise's rms in the same band.
             And with the smooth oval itself taken out (each half smoothed by 3 px, its own mean in elliptical rings of
             8 px taken off): that test also counts the nebula's large-scale lopsidedness, not only filaments.
  pulsar     the compact sources nearest the catalogue position (the pulsar, J2000) on the difference of Gaussians,
             their significance and their offsets east and north by the plate solution.
A look for the eye goes to the work folder (kept): halves_look.png (odd, even, stack; smoothed 2 px) and
halves_bandpass.png (the same three band-passed at s = 3 px, and the odd-minus-even difference: what noise alone does)."""
import os
import numpy as np, cv2
from common import *
from step2_stars import measure

SKY_R0, SKY_R1 = 464, 650
A_IN = 150                 # px, semi-major axis of the inner ellipse (1.9 arcmin)
NEB_A = 220                # px, the nebula for the structure tests: out to 220 px (2.8 arcmin) along the long axis
S9 = jload('step9_solve.json'); S5 = jload('step5_select.json'); S8 = jload('step8_stack.json')
c = S9['crop_on_reference_grid']; X0, Y0, X1, Y1 = c['x0'], c['y0'], c['x1'], c['y1']
SC = float(S9['pixscale_arcsec']); N = len(S5['used'])
cx, cy = S9['catalogue'][TARGET['name']]['pixel']
NORTH, EAST = np.array(S9['sky_axes']['north']), np.array(S9['sky_axes']['east'])
Mmap = SC * np.array([EAST, NORTH])           # picture px offset (x, y) -> arcsec (east, north)
cover = np.load(W('stack_cover.npy'))[Y0:Y1, X0:X1]; OK = cover == N
s10 = jload('step10_deliver.json'); pn = s10['noise_faint_region']['planes_stack']; wbd = np.array([s10['white_balance_daylight'][k] for k in 'RGB'])


def chans(name):
    a = np.load(W(name), mmap_mode='r')[:, Y0:Y1, X0:X1]
    return np.stack([a[0], (a[1] + a[2]) / 2, a[3]]).astype(np.float64)


ST, ODD, EVEN, ONE = chans('stack_mean.npy'), chans('stack_odd.npy'), chans('stack_even.npy'), chans('stack_single.npy')
for A in (ST, ODD, EVEN, ONE): np.nan_to_num(A, copy=False)
hh, ww = ST.shape[1:]
yy, xx = np.mgrid[0:hh, 0:ww]; RR = np.hypot(xx - cx, yy - cy)

# ---- stars (difference of Gaussians on the stack's green)
G = np.where(OK, ST[1], 0).astype(np.float32)
dog = cv2.GaussianBlur(G, (0, 0), 1.5) - cv2.GaussianBlur(G, (0, 0), 6.0)
_, sd_dog, _ = clipped_stats(dog[OK & (RR > SKY_R0)][::5])
det = (dog > 5 * sd_dog) & OK
nl, lab, stats, cent = cv2.connectedComponentsWithStats(det.astype(np.uint8), connectivity=8)
smask = np.zeros((hh, ww), np.uint8); nstars = 0; star_list = []
pk_all = np.zeros(nl); np.maximum.at(pk_all, lab.ravel(), dog.ravel())
for i in range(1, nl):
    a = stats[i, cv2.CC_STAT_AREA]
    if a < 3: continue
    pk = float(pk_all[i]); r = int(round(4 + 2.5 * np.sqrt(a) + 2 * np.log10(max(pk / sd_dog, 1))))
    cv2.circle(smask, (int(round(cent[i][0])), int(round(cent[i][1]))), r, 1, -1); nstars += 1
    star_list.append((float(cent[i][0]), float(cent[i][1]), pk / sd_dog, a))
FREE = OK & (smask == 0)
print('stars masked:', nstars, '; free pixels %.0f%%; of the nebula (within %d px) %.0f%% free' % (100 * FREE.mean(), NEB_A, 100 * FREE[RR < NEB_A].mean()))

# ---- sky plane per colour, from the ring around M1
SKYM = FREE & (RR >= SKY_R0) & (RR < SKY_R1)
U, V = (xx - cx) / 100.0, (yy - cy) / 100.0
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
theta = 0.5 * np.arctan2(2 * mxy, mxx - myy)            # long axis, radians from +x towards +y (picture)
AXR = float(np.sqrt(l2 / l1))
d_sky = Mmap @ np.array([np.cos(theta), np.sin(theta)]); PA = float(np.degrees(np.arctan2(d_sky[0], d_sky[1])) % 180)
light_c = np.array([mx, my]); d_lc = Mmap @ (light_c - np.array([cx, cy]))
print('shape: long axis at %.1f deg on the picture, position angle %.0f deg east of north, axis ratio %.2f; light centre %.1f arcsec from the catalogue place (%+.1f E, %+.1f N)' % (np.degrees(theta), PA, AXR, np.hypot(*d_lc), *d_lc))
c_, s_ = np.cos(theta), np.sin(theta)
ER = np.hypot((xx - cx) * c_ + (yy - cy) * s_, (-(xx - cx) * s_ + (yy - cy) * c_) / AXR)     # elliptical radius: px along the long axis

# ---- per-pixel noise
def pix_noise(A, m=SKYM):
    return [clipped_stats(A[k][m])[1] for k in range(3)]
noise = {n: pix_noise(A) for n, A in (('stack', ST), ('single_reference_frame', ONE), ('odd', ODD), ('even', EVEN), ('half_difference', DIFF))}
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
        if not (SKY_R0 <= np.hypot(px - cx, py - cy)): continue
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
                  per_pixel_signal_to_noise_green=round(neb[n][1] / noise[n][1], 2))
print('blank-sky places for the inner ellipse:', len(ctrl_pos))
for n, v in snr.items(): print(' ', n, v)

# ---- elliptical profile (rings of 10 px along the long axis)
prof = []
for a_ in range(0, 460, 10):
    m = (ER >= a_) & (ER < a_ + 10) & FREE
    if m.sum() < 20: continue
    prof.append(dict(a_px=[a_, a_ + 10], a_arcsec=[round(a_ * SC, 1), round((a_ + 10) * SC, 1)], n_px=int(m.sum()),
                     mean_dn=dict(zip('RGB', [round(float(ST[k][m].mean()), 3) for k in range(3)])), odd_g=round(float(ODD[1][m].mean()), 3), even_g=round(float(EVEN[1][m].mean()), 3),
                     error_g=round(float(noise['stack'][1] / np.sqrt(m.sum())), 3)))
centre = np.mean([p['mean_dn']['G'] for p in prof if p['a_px'][0] < 40])
half_a = next((p['a_px'][0] for p in prof if p['mean_dn']['G'] < 0.5 * centre), None)
# the edge: where the profile comes down to the level of the rings 300 to 400 px out (3.9 to 5.2 arcmin; that level is
# not exactly zero: the night's flat reads about 1.5% high in the middle of the sensor, where the nebula sits, so the
# sky just around the nebula is a little below the ring the plane was fitted to) within 3 x its ring-to-ring scatter.
plat = [p['mean_dn']['G'] for p in prof if 300 <= p['a_px'][0] < 400]
plateau, plateau_sd = float(np.median(plat)), float(np.std(plat))
fade_a = next((p['a_px'][0] for p in prof if p['a_px'][0] > 60 and p['mean_dn']['G'] < plateau + 3 * max(plateau_sd, p['error_g'])), None)
print('central level %.1f DN green; half of it at %s px along the long axis; down to the level of the sky around it (%.2f +- %.2f DN, 3.9 to 5.2 arcmin out) by %s px' % (centre, half_a, plateau, plateau_sd, fade_a))
print('profile G (DN) every 20 px:', ' '.join('%d:%.1f' % (p['a_px'][0], p['mean_dn']['G']) for p in prof[::2]))

# ---- structure: band-passed halves, correlated inside the nebula and on blank sky
NEBM = (ER < NEB_A) & FREE
def band(A, s):
    return msmooth(A, s) - msmooth(A, 4 * s)
def corr(a, b, m):
    a = a[m] - a[m].mean(); b = b[m] - b[m].mean(); return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))
def cov(a, b, m):
    a = a[m] - a[m].mean(); b = b[m] - b[m].mean(); return float((a * b).mean())
half2 = NEB_A + 2
oy2, ox2 = np.mgrid[-half2:half2 + 1, -half2:half2 + 1]
tmpl2 = np.hypot(ox2 * c_ + oy2 * s_, (-ox2 * s_ + oy2 * c_) / AXR) < NEB_A
ctrl2 = []
for py in range(half2, hh - half2, half2 // 2):
    for px in range(half2, ww - half2, half2 // 2):
        if np.hypot(px - cx, py - cy) < SKY_R0: continue
        sl_ = (slice(py - half2, py + half2 + 1), slice(px - half2, px + half2 + 1))
        if not OK[sl_][tmpl2].all() or (FREE[sl_] & tmpl2).sum() < 0.6 * tmpl2.sum(): continue
        ctrl2.append((px, py))
def place_mask(px, py):
    m = np.zeros((hh, ww), bool); m[py - half2:py + half2 + 1, px - half2:px + half2 + 1] = tmpl2; return m & FREE
wl = np.array([1 / (pn['R'] * wbd[0]) ** 2, 2 / ((0.5 * (pn['G1'] + pn['G2'])) ** 2), 1 / (pn['B'] * wbd[2]) ** 2]); wl /= wl.sum()
k_rg = neb['stack'][0] / neb['stack'][1]            # the nebula's own mean red : green (raw units), inside the inner ellipse
CH = dict(green=lambda A: A[1], red=lambda A: A[0], luminance=lambda A: wl[0] * wbd[0] * A[0] + wl[1] * A[1] + wl[2] * wbd[2] * A[2], red_excess=lambda A: A[0] - k_rg * A[1])
structure = {}; looks = {}
for cname, f in CH.items():
    structure[cname] = {}
    for s in (1.5, 3.0, 6.0):
        Bo, Be, Bs, Bd = band(f(ODD), s), band(f(EVEN), s), band(f(ST), s), band(f(DIFF), s)
        r_in = corr(Bo, Be, NEBM); cv_in = cov(Bo, Be, NEBM)
        rc, cvc, rms_c, rmsd_c = [], [], [], []
        for px, py in ctrl2:
            m = place_mask(px, py)
            rc.append(corr(Bo, Be, m)); cvc.append(cov(Bo, Be, m)); rms_c.append(float(Bs[m].std())); rmsd_c.append(float(Bd[m].std()))
        rc = np.array(rc); cvc = np.array(cvc)
        rms_in = float(Bs[NEBM].std()); rmsd_in = float(Bd[NEBM].std())
        d = dict(band='Gaussian %.1f px minus Gaussian %.1f px (detail of about %.0f to %.0f arcsec)' % (s, 4 * s, 2.355 * s * SC, 2.355 * 4 * s * SC),
                 halves_correlation_in_nebula=round(r_in, 3), blank_sky_correlation_mean=round(float(rc.mean()), 3), blank_sky_correlation_std=round(float(rc.std(ddof=1)), 3),
                 blank_sky_correlation_max=round(float(rc.max()), 3), blank_sky_places=int(len(rc)), places_at_or_above_the_nebula=int((rc >= r_in).sum()),
                 significance_sigma=round(float((r_in - rc.mean()) / rc.std(ddof=1)), 1),
                 real_structure_rms_dn=round(float(np.sqrt(max(cv_in, 0))), 3), blank_sky_structure_rms_dn=round(float(np.sqrt(max(np.median(cvc), 0))), 3),
                 noise_rms_in_this_band_dn=round(rmsd_in, 3), stack_rms_in_nebula_dn=round(rms_in, 3), stack_rms_blank_sky_dn=round(float(np.median(rms_c)), 3),
                 half_difference_rms_blank_sky_dn=round(float(np.median(rmsd_c)), 3))
        d['structure_to_noise'] = round(d['real_structure_rms_dn'] / max(d['noise_rms_in_this_band_dn'], 1e-9), 2)
        d['repeats'] = bool(d['places_at_or_above_the_nebula'] == 0 and d['significance_sigma'] >= 5)
        structure[cname]['sigma_%.1f_px' % s] = d
        print('structure, %-10s band sigma %.1f px: halves r = %.3f in the nebula; blank sky %.3f +- %.3f (max %.3f, %d places) -> %.1f sigma; real structure %.2f DN rms against noise %.2f (blank sky %.2f) -> %s' % (
            cname, s, r_in, rc.mean(), rc.std(ddof=1), rc.max(), len(rc), d['significance_sigma'], d['real_structure_rms_dn'], rmsd_in, d['blank_sky_structure_rms_dn'], 'REPEATS' if d['repeats'] else 'does not repeat'))
        if s == 3.0: looks[cname] = (Bo, Be, Bs, Bd)

# the same with the smooth oval itself taken out: each half smoothed by 3 px, minus its own mean in elliptical rings
So3, Se3 = msmooth(ODD[1], 3.0), msmooth(EVEN[1], 3.0)
er2 = np.hypot(ox2 * c_ + oy2 * s_, (-ox2 * s_ + oy2 * c_) / AXR)
def deprof_corr(px, py):
    ys, xs = slice(py - half2, py + half2 + 1), slice(px - half2, px + half2 + 1)
    m = tmpl2 & FREE[ys, xs]
    a, b = So3[ys, xs].copy(), Se3[ys, xs].copy()
    for a_ in range(0, NEB_A + 10, 8):
        r_ = (er2 >= a_) & (er2 < a_ + 8) & m
        if r_.sum(): a[r_] -= a[r_].mean(); b[r_] -= b[r_].mean()
    return corr(a, b, m)
r_dep = deprof_corr(int(round(cx)), int(round(cy)))
r_dep_c = np.array([deprof_corr(px, py) for px, py in ctrl2])
structure['oval_removed_3px_green'] = dict(how='each half smoothed by 3 px, its own mean in elliptical rings (8 px) taken off, correlated inside the nebula (out to %d px); blank sky: the same about each place. Counts the nebula\'s large-scale lopsidedness as well as fine detail.' % NEB_A,
                                           halves_correlation_in_nebula=round(r_dep, 3), blank_sky_correlation_mean=round(float(r_dep_c.mean()), 3), blank_sky_correlation_std=round(float(r_dep_c.std(ddof=1)), 3),
                                           blank_sky_correlation_max=round(float(r_dep_c.max()), 3), significance_sigma=round(float((r_dep - r_dep_c.mean()) / r_dep_c.std(ddof=1)), 1))
print('oval removed (green, 3 px): halves r = %.3f in the nebula; blank sky %.3f +- %.3f (max %.3f)' % (r_dep, r_dep_c.mean(), r_dep_c.std(ddof=1), r_dep_c.max()))
r_whole = corr(So3, Se3, NEBM)
structure['oval_included_3px_green'] = dict(halves_correlation_in_nebula=round(r_whole, 3))
print('oval included: halves r = %.3f' % r_whole)

# ---- the pulsar: compact sources near the catalogue position on the difference of Gaussians
sl = np.array(star_list); dd = np.hypot(sl[:, 0] - cx, sl[:, 1] - cy); near = np.argsort(dd)[:4]
pk_here = float(dog[int(round(cy)) - 2:int(round(cy)) + 3, int(round(cx)) - 2:int(round(cx)) + 3].max() / sd_dog)
near_rows = []
for k in near:
    if dd[k] > 40: continue
    en = Mmap @ np.array([sl[k, 0] - cx, sl[k, 1] - cy])
    near_rows.append(dict(picture_px=[round(float(sl[k, 0]), 1), round(float(sl[k, 1]), 1)], from_the_pulsars_place_arcsec=round(float(dd[k] * SC), 1), east_arcsec=round(float(en[0]), 1), north_arcsec=round(float(en[1]), 1), significance_sigma=round(float(sl[k, 2]), 1), area_px=int(sl[k, 3])))
pulsar = dict(catalogue_place_px=[cx, cy], sources_within_31_arcsec=near_rows, peak_within_2px_of_the_catalogue_place_sigma=round(pk_here, 1), star_size_arcsec=s10['star_size']['hfd_stack_arcsec'],
              known='the pulsar (about V 16.5) is the south-western of a pair of stars about 5 arcsec apart at the nebula\'s centre; its north-eastern neighbour is a little brighter')
print('pulsar check:', pulsar)

# ---- colour of the nebula (camera daylight white balance, as the picture), core against rim
nb = np.array(neb['stack']) * wbd
colour = dict(white_balanced_daylight=dict(zip('RGB', [round(float(v), 3) for v in nb])), ratio_to_green=dict(zip('RGB', [round(float(v / nb[1]), 3) for v in nb])), wb=wbd.tolist())
OUTER = (ER >= A_IN * 0.67) & (ER < A_IN * 1.4) & FREE; CORE = (ER < A_IN * 0.67) & FREE
col_parts = {}
for nm, m in (('core', CORE), ('rim', OUTER)):
    v = np.array([ST[k][m].mean() for k in range(3)]) * wbd
    col_parts[nm] = dict(ratio_to_green=dict(zip('RGB', [round(float(x / v[1]), 3) for x in v])), green_dn=round(float(v[1]), 2), pixels=int(m.sum()))
colour['core_and_rim'] = col_parts
print('colour:', colour)

# ---- looks for the eye (work folder, kept): the two halves and the stack
def cut(v): return v[int(cy) - 300:int(cy) + 300, int(cx) - 400:int(cx) + 400]
vis = [cut(msmooth(A[1], 2.0)) for A in (ODD, EVEN, ST)]
lo_, hi_ = -6.0, float(np.percentile(vis[2], 99.5))
cv2.imwrite(W('halves_look.png'), np.hstack([(np.clip((v - lo_) / (hi_ - lo_), 0, 1) ** 0.7 * 255).astype(np.uint8) for v in vis]))
rows = []
for cname in ('green', 'red_excess'):
    Bo, Be, Bs, Bd = looks[cname]; sdv = float(cut(Bd).std()) * 2
    rows.append(np.hstack([(np.clip(cut(b) / (6 * sdv) + 0.5, 0, 1) * 255).astype(np.uint8) for b in (Bo, Be, Bs, Bd * 2)]))
cv2.imwrite(W('halves_bandpass.png'), np.vstack(rows))

out = dict(on='the well-covered rectangle of step 9', catalogue_px=[cx, cy], scale_arcsec_per_px=SC,
           sky_plane=dict(coefficients=dict(zip('RGB', plane)), terms='DN = c0 + c1 (x - x_M1) / 100 + c2 (y - y_M1) / 100', ring_px=[SKY_R0, SKY_R1], pixels=int(SKYM.sum())),
           stars_masked=nstars, noise_per_px_dn=noise,
           shape=dict(long_axis_on_the_picture_deg=float(np.degrees(theta)), position_angle_deg_east_of_north=PA, axis_ratio=AXR, light_centre_px=light_c.tolist(),
                      light_centre_from_catalogue_arcsec=float(np.hypot(*d_lc)), light_centre_offset_east_north_arcsec=d_lc.tolist()),
           inner_ellipse_px=[A_IN, A_IN * AXR], inner_ellipse_arcmin=[round(2 * A_IN * SC / 60, 2), round(2 * A_IN * AXR * SC / 60, 2)],
           nebula=snr, blank_sky_places=len(ctrl_pos), profile=prof, central_level_green_dn=float(centre),
           half_level_along_long_axis_px=half_a, fades_into_sky_along_long_axis_px=fade_a, sky_around_it_green_dn=plateau, sky_around_it_ring_scatter_dn=plateau_sd,
           size_arcmin=dict(half_level=[round(2 * half_a * SC / 60, 2), round(2 * half_a * AXR * SC / 60, 2)] if half_a else None,
                            to_the_sky=[round(2 * fade_a * SC / 60, 2), round(2 * fade_a * AXR * SC / 60, 2)] if fade_a else None),
           structure=structure, structure_places=[list(p) for p in ctrl2], red_to_green_of_the_nebula_raw=k_rg, luminance_weights_rgb=wl.tolist(), pulsar=pulsar, colour=colour,
           subsets=dict(odd=len(S8['subsets']['odd']), even=len(S8['subsets']['even'])))
jdump(out, 'step11_measure.json')
