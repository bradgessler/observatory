"""Step 6: what the run itself says about the flat field, with no assumption about the galaxy.

The 'bright sky' frames are cloud (step 5: the stars lose light exactly as the sky brightens). A clouded frame is
    P_i = T_i * (galaxy + sky) * flat  +  glow_i * flat
with T_i the measured fraction of starlight that got through. The nearest clear frame gives (galaxy + sky) * flat,
so  P_i - T_i * P_clear = glow_i * flat: the cloud's own glow, which lights the aperture evenly, seen through the
optics and the dust. Each difference is divided by its median; the median over the clouded frames, in SENSOR
coordinates (no registration, so what is left of the stars moves and drops out), is a flat field measured
during this run at this focus. Within 400 px of the nucleus the galaxy does not cancel (it shifts between the
two frames) and the flat is not used there.

From it:
 (a) a smooth, radially symmetric, centred vignetting profile per colour (ring medians of 16 px blocks, a
     fitted linear tilt divided out first so it cannot bias the rings, smoothing spline, V(0) = 1). The tilt
     itself is recorded and NOT applied. Checked against the sky flat of the M15 run (vig1, vig2).
 (b) a map of the dust shadows: the green flat, Gaussian sigma 2.5 plane px, over the smooth model. Where it is
     below DUST_RATIO (or a sigma-4 copy is below DUST_RATIO_WIDE, which catches the faint rings) in blobs of at least MIN_BLOB plane px, grown by DUST_GROW px, the sensor pixels are
     marked. Marked pixels are LEFT OUT of the average in step 8 (nothing is divided by the dust map).
     Near the nucleus, where this flat is blind, the M15 run's dust map is used instead."""
import json, os, numpy as np, cv2
from scipy.interpolate import UnivariateSpline
from scipy.optimize import least_squares
from common import *
BS = 16
T_MAX, CORNER_MIN, CLEAR_MIN = 0.40, 180.0, 0.97
DUST_RATIO, DUST_RATIO_WIDE, DUST_GROW, MIN_BLOB, NUC_BLIND = 0.98, 0.986, 6, 60, 400
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
q = {o['stamp']: o for o in json.load(open(W('step5_quality.json')))['quality']}
stamps = sorted(s1)
clear = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= CLEAR_MIN]
cloud = [s for s in stamps if q[s]['flux_rel'] is not None and q[s]['flux_rel'] <= T_MAX and s1[s]['corner_green'] >= CORNER_MIN]
def tsec(s): return int(s[9:11]) * 3600 + int(s[11:13]) * 60 + int(s[13:15])
h, w = H // 2, Wd // 2; yy, xx = np.mgrid[0:h, 0:w]
blind = np.zeros((h, w), bool)
pairs = []
for s in cloud:
    j = min(clear, key=lambda c: abs(tsec(c) - tsec(s))); pairs.append((s, j))
    for nuc in (s1[j]['nucleus_sensor_xy'],): blind |= np.hypot(2 * xx + 0.5 - nuc[0], 2 * yy + 0.5 - nuc[1]) < NUC_BLIND
flat = np.zeros((4, h, w), np.float32); glow = []
for p in range(4):
    acc = []
    for s, j in pairs:
        D = np.load(W('planes/' + s + '.npy'), mmap_mode='r')[p] - q[s]['flux_rel'] * np.load(W('planes/' + j + '.npy'), mmap_mode='r')[p]
        m = float(np.median(D[::4, ::4])); acc.append((D / m).astype(np.float32))
        if p == 1: glow.append(m)
    flat[p] = np.median(np.stack(acc), axis=0); del acc
    print('flat', PLANE_NAMES[p], 'done', flush=True)
np.save(W('cloudflat.npy'), flat)
print('%d clouded frames (T <= %.2f, corner green >= %.0f), glow in green %.0f..%.0f DN, median %.0f' % (len(cloud), T_MAX, CORNER_MIN, min(glow), max(glow), np.median(glow)))

# ---------- (a) radial profiles ----------
def block_table(F, p, mask):
    ny, nx = h // BS, w // BS
    Fb = np.where(mask, F, np.nan)[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(Fb).sum(2); v = np.nanmedian(Fb, axis=2)
    v[n < BS * BS // 2] = np.nan
    Y, X = np.mgrid[0:ny, 0:nx]; ox, oy = OFFS[p]
    x = 2 * (X * BS + (BS - 1) / 2) + ox; y = 2 * (Y * BS + (BS - 1) / 2) + oy
    m = np.isfinite(v)
    return x[m], y[m], v[m]
def radial(c, rho): return 1 + c[0] * rho ** 2 + c[1] * rho ** 4 + c[2] * rho ** 6
def fit_poly(x, y, v):
    def model(qq, x, y):
        rho = np.hypot(x - CENTRE[0], y - CENTRE[1]) / 3000
        return qq[0] * radial(qq[1:4], rho) * (1 + qq[4] * (x - CENTRE[0]) / 3000 + qq[5] * (y - CENTRE[1]) / 3000)
    q0 = np.array([np.median(v), -0.2, 0, 0, 0, 0], float); keep = np.ones(len(v), bool)
    for _ in range(4):
        r = least_squares(lambda qq: model(qq, x[keep], y[keep]) - v[keep], q0); q0 = r.x
        res = v - model(q0, x, y); sd = 1.4826 * np.median(np.abs(res[keep] - np.median(res[keep]))); keep = np.abs(res) < 3 * sd
    return q0, keep
RINGS = [(a, a + 150) for a in range(0, 3600, 150)]
def profile(tables):
    """tables: list of (x, y, v) for the planes of one colour. Returns knots r, V and the fitted tilt."""
    rr, vv, tilt = [], [], []
    for x, y, v in tables:
        qf, keep = fit_poly(x, y, v)
        g = 1 + qf[4] * (x - CENTRE[0]) / 3000 + qf[5] * (y - CENTRE[1]) / 3000
        rr.append(np.hypot(x - CENTRE[0], y - CENTRE[1])[keep]); vv.append((v / g / qf[0])[keep]); tilt.append([float(qf[4]), float(qf[5])])
    r = np.concatenate(rr); v = np.concatenate(vv)
    kr, kv, kn = [], [], []
    for a, b in RINGS:
        m = (r >= a) & (r < b)
        if m.sum() >= 30: kr.append(float(np.median(r[m]))); kv.append(float(np.median(v[m]))); kn.append(int(m.sum()))
    kr, kv = np.array(kr), np.array(kv)
    # smoothing spline in r^2 through the ring medians, held flat at the centre by mirroring the first rings
    spl = UnivariateSpline(np.concatenate([-kr[:3][::-1], kr]), np.concatenate([kv[:3][::-1], kv]), k=3, s=len(kr) * (0.0015 ** 2))
    v0 = float(spl(0.0))
    return dict(ring_r=kr.tolist(), ring_measured=(kv / v0).tolist(), ring_blocks=kn, tilt_per_3000px=np.mean(tilt, axis=0).tolist(), spline=spl, v0=v0)
mask0 = ~blind
tabs = [block_table(flat[p], p, mask0) for p in range(4)]
prof = dict(R=profile([tabs[0]]), G=profile([tabs[1], tabs[2]]), B=profile([tabs[3]]))
rgrid = np.arange(0, 3700, 10.0)
table = {}
for c in 'RGB':
    V = prof[c]['spline'](rgrid) / prof[c]['v0']
    V = np.minimum.accumulate(np.minimum(V, 1.0))            # never above 1 and never rising outward
    table[c] = V
    fitres = np.interp(prof[c]['ring_r'], rgrid, V) - np.array(prof[c]['ring_measured'])
    print('vignetting %s: V at r = 0, 1000, 2000, 3000, 3600 px: %s ; tilt (not applied) %+.4f, %+.4f per 3000 px ; ring residual rms %.4f max %.4f' % (c, np.round(np.interp([0, 1000, 2000, 3000, 3600], rgrid, V), 4).tolist(), *prof[c]['tilt_per_3000px'], float(np.sqrt((fitres ** 2).mean())), float(np.abs(fitres).max())))
# check against the M15 sky flat: ring medians of its block tables, tilt divided out, over this profile
d15 = np.load(W('vig_skyflats.npz')); chk = {}
def m15_table(key, p):
    v = d15[key]; ny, nx = v.shape; ox, oy = OFFS[p]; Y, X = np.mgrid[0:ny, 0:nx]
    x = 2 * (X * BS + (BS - 1) / 2) + ox; y = 2 * (Y * BS + (BS - 1) / 2) + oy; m = np.isfinite(v)
    return x[m], y[m], v[m]
for c, planes in (('R', [0]), ('G', [1, 2]), ('B', [3])):
    rows = []
    for p in planes:
        x, y, v = m15_table('m15_' + PLANE_NAMES[p], p); qf, keep = fit_poly(x, y, v)
        g = 1 + qf[4] * (x - CENTRE[0]) / 3000 + qf[5] * (y - CENTRE[1]) / 3000
        rows.append((np.hypot(x - CENTRE[0], y - CENTRE[1])[keep], (v / g)[keep]))
    r = np.concatenate([a for a, b in rows]); v = np.concatenate([b for a, b in rows])
    ratio = v / np.interp(r, rgrid, table[c])
    ring = []
    for a, b in [(300, 900), (900, 1500), (1500, 2100), (2100, 2700), (2700, 3000), (3000, 3300), (3300, 3600)]:
        m = (r >= a) & (r < b); ring.append((a, b, float(np.median(ratio[m]))))
    base = ring[1][2]
    chk[c] = [dict(r_px=[a, b], m15_sky_flat_over_this_profile=round(v_ / base, 4)) for a, b, v_ in ring]
    print('  M15 sky flat / this profile, %s (1.000 = same shape, normalised at 900-1500 px):' % c, ' '.join('%d-%d: %.4f' % (a, b, v_ / base) for a, b, v_ in ring))
json.dump(dict(source='cloud glow in %d clouded frames of this run (transparency <= %.2f), galaxy and sky removed with the nearest clear frame times the measured transparency' % (len(cloud), T_MAX),
               frames=[dict(clouded=s, clear=j, transparency=round(q[s]['flux_rel'], 4), glow_green_dn=round(g_, 1)) for (s, j), g_ in zip(pairs, glow)],
               r_px=rgrid.tolist(), V={c: [float(v_) for v_ in table[c]] for c in 'RGB'},
               rings={c: dict(r_px=prof[c]['ring_r'], measured=prof[c]['ring_measured'], blocks=prof[c]['ring_blocks']) for c in 'RGB'},
               tilt_not_applied_per_3000px={c: prof[c]['tilt_per_3000px'] for c in 'RGB'}, check_against_m15_sky_flat=chk,
               centre_sensor_px=CENTRE.tolist()), open(W('vignette.json'), 'w'), indent=1)

# ---------- (b) dust map ----------
FG = (flat[1] + flat[2]) / 2
r_pl = np.hypot(2 * xx + 0.5 - CENTRE[0], 2 * yy + 0.5 - CENTRE[1])
tilt = prof['G']['tilt_per_3000px']
model = np.interp(r_pl, rgrid, table['G']) * (1 + tilt[0] * (2 * xx + 0.5 - CENTRE[0]) / 3000 + tilt[1] * (2 * yy + 0.5 - CENTRE[1]) / 3000)
r0 = cv2.GaussianBlur(FG, (0, 0), 2.5) / model
small = cv2.resize(r0, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small.astype(np.float32), 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
lowf = cv2.resize(low, (w, h), interpolation=cv2.INTER_CUBIC)
ratio = (r0 / lowf).astype(np.float32)
ratio_wide = (cv2.GaussianBlur(FG, (0, 0), 4.0) / model / lowf).astype(np.float32)     # a smoother copy, for the faint rings
patch = ratio[900:1100, 300:500]; noise = float(1.4826 * np.median(np.abs(patch - np.median(patch))))
patch_w = ratio_wide[900:1100, 300:500]; noise_wide = float(1.4826 * np.median(np.abs(patch_w - np.median(patch_w))))
m = ((ratio < DUST_RATIO) | (ratio_wide < DUST_RATIO_WIDE)) & ~blind
n, lab, stats, cent = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
keep_ids = np.array([i for i in range(1, n) if stats[i, 4] >= MIN_BLOB])
mask = np.isin(lab, keep_ids)
blobs = sorted([dict(centre_sensor_xy=[round(2 * float(cent[i][0]) + 0.5, 1), round(2 * float(cent[i][1]) + 0.5, 1)], plane_px=int(stats[i, 4]), deepest_ratio=round(float(ratio[lab == i].min()), 3)) for i in keep_ids], key=lambda b: -b['plane_px'])
# near the nucleus: the M15 run's dust map (measured in its empty sky a quarter of an hour earlier)
m15div = np.load(os.path.join(os.path.dirname(os.path.dirname(WORK)), 'm15', 'sharp', 'dustdiv.npy'))
from_m15 = (m15div < 0.99) & blind
mask |= from_m15
grown = cv2.dilate(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * DUST_GROW + 1, 2 * DUST_GROW + 1))).astype(bool)
np.save(W('dustmask.npy'), grown); np.save(W('dustratio.npy'), ratio)
# how well do the two runs agree on where the dust is? (outside both blind zones)
m15mask = m15div < 1
both_ok = ~blind
agree = float((grown & m15mask & both_ok).sum() / max((m15mask & both_ok).sum(), 1))
print('dust: ratio noise %.4f; %d patches, %.2f%% of the sensor marked after growing by %d px; deepest %.3f; %d plane px taken from the M15 map near the nucleus; %.0f%% of the M15 run\'s dust px are inside this mask' % (noise, len(blobs), 100 * grown.mean(), DUST_GROW, float(ratio[mask & ~blind].min()), int(from_m15.sum()), 100 * agree))
json.dump(dict(ratio_threshold_wide=DUST_RATIO_WIDE, blur_sigma_wide_plane_px=4.0, ratio_noise_wide=noise_wide, ratio_threshold=DUST_RATIO, grow_plane_px=DUST_GROW, min_blob_plane_px=MIN_BLOB, blur_sigma_plane_px=2.5, ratio_noise=noise, patches=len(blobs), marked_fraction_of_sensor=float(grown.mean()), deepest_ratio=float(ratio[mask & ~blind].min()),
               blind_zone='within %d sensor px of the nucleus (the galaxy does not cancel there); the M15 run\'s dust map (divisor < 0.99) is used there: %d plane px' % (NUC_BLIND, int(from_m15.sum())),
               fraction_of_m15_dust_px_inside_this_mask=agree, largest=blobs[:12], all_patches=blobs), open(W('dust.json'), 'w'), indent=1)
v = np.clip((ratio - 0.90) / 0.15, 0, 1); v8 = (cv2.resize(v, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA) * 255).astype(np.uint8)
ov = cv2.cvtColor(v8, cv2.COLOR_GRAY2BGR); mk = cv2.resize(grown.astype(np.uint8), (v8.shape[1], v8.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
edge = mk & ~cv2.erode(mk.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool); ov[edge] = (0, 200, 255)
cv2.imwrite(W('v_dustmask.png'), ov)
