"""Step 10 (a separate, labelled version; the plain picture is not touched): the same picture with the brightness
deconvolved by the blur measured from stars in the same stack.

The blur: stars within 800 px of M57 in the stack's green (brighter than 15000 DN, no pixel near the ceiling, no other
star within 30 px), each cut out, its local sky (ring 18-24 px) taken off, moved onto the pixel grid by an exact
Fourier shift, scaled to a total of 1, then the median of them, set to 0 beyond 18 px and below 0, total 1.
The restoration: a Wiener filter on the luminance Y only (linear sRGB, after the sky plane, before any smoothing):
W = conj(H) (1 + NSR) / (|H|^2 + NSR) (so that W = 1 at zero frequency: total light kept), with its gain capped at GAIN_MAX at every spatial frequency (|W| <= GAIN_MAX, phase kept),
H = the blur's transfer function. Colour is made exactly as in step 8 (from the plain data at 3.5 px), the stretch by
the same rule, then finish.py with the same numbers. Checks written to step10.json: star size before and after near
the nebula, the darkest ring around bright stars (ringing), the sky noise, the ring-to-hole contrast, the nebula's profile.
Tried (2026-10-09): NSR 0.02 with gain 3 tripled the sky noise and filled the ring's hole with noise blobs (not kept);
NSR 0.3 with gain 1.5 changed little; NSR 0.1 with gain 2 is the version kept: stars about 30% smaller, the hole a little
darker against the ring, sky noise up about 40%, a dark ring of at most -4 DN (under 1 sigma) round the brighter stars."""
import json, os, subprocess
import numpy as np, cv2
from PIL import Image
from common import *
from step2_stars import measure

NSR = float(os.environ.get('M57_NSR', 0.1)); GAIN_MAX = float(os.environ.get('M57_GAIN_MAX', 2.0))
LUMA = np.array([0.2126, 0.7152, 0.0722])
s7 = jload('step7_solve.json'); s8 = jload('step8.json'); s6 = jload('step6.json'); N = len(s6['frames'])
st = np.load(W_('stack_mean.npy')); cover = np.load(W_('cover.npy')); ok = cover == N
wb = np.array(s8['white_balance_daylight']); RGB_CAM = np.array(s8['rgb_cam'])
pc = np.array(s7['m57_catalogue']['stack_px'])

# ---- the blur, from the stars
G = np.where(ok, (st[1] + st[2]) / 2, 0).astype(np.float32)
BLK = 64; bh, bw = h2 // BLK, w2 // BLK
b = np.median(G[:bh * BLK, :bw * BLK].reshape(bh, BLK, bw, BLK), axis=(1, 3)).astype(np.float32)
D = G - cv2.resize(cv2.medianBlur(b, 3), (w2, h2), interpolation=cv2.INTER_LINEAR)
sm = cv2.GaussianBlur(D, (0, 0), 2.5); m_, s_, _ = clipped_stats(sm[ok][::7])
n_, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m_ + 8 * s_).astype(np.uint8))
allxy = np.array([cent[i] for i in range(1, n_)])
R0 = 24; cuts = []; used = []
yy, xx = np.mgrid[-R0:R0 + 1, -R0:R0 + 1]
for i in range(1, n_):
    r = measure(D, float(cent[i][0]), float(cent[i][1]))
    if r is None or r['flux'] < 15000 or np.hypot(r['x'] - pc[0], r['y'] - pc[1]) > 800 or np.hypot(r['x'] - pc[0], r['y'] - pc[1]) < 80: continue
    xi, yi = int(round(r['x'])), int(round(r['y']))
    if max(st[p, yi - 3:yi + 4, xi - 3:xi + 4].max() for p in range(4)) > SAT_DN * 0.7: continue
    d = np.hypot(allxy[:, 0] - r['x'], allxy[:, 1] - r['y']); d = d[d > 3]
    if len(d) and d.min() < 30: continue
    c = D[yi - R0:yi + R0 + 1, xi - R0:xi + R0 + 1].astype(np.float64)
    rr = np.hypot(xx, yy); c -= np.median(c[(rr >= 18) & (rr <= 24)])
    fy, fx = np.meshgrid(np.fft.fftfreq(c.shape[0]), np.fft.fftfreq(c.shape[1]), indexing='ij')
    c = np.real(np.fft.ifft2(np.fft.fft2(c) * np.exp(2j * np.pi * (fx * (r['x'] - xi) + fy * (r['y'] - yi)))))
    cuts.append(c / c[rr <= 18].sum()); used.append([round(r['x'], 1), round(r['y'], 1), round(r['flux']), round(2 * r['hfr'], 2)])
psf = np.median(np.array(cuts), axis=0); rr = np.hypot(xx, yy); psf[rr > 18] = 0; psf = np.clip(psf, 0, None); psf /= psf.sum()
order = np.argsort(rr.ravel()); cum = np.cumsum(psf.ravel()[order]); psf_hfd = 2 * rr.ravel()[order][np.searchsorted(cum, 0.5)]
print('blur from %d stars, half-flux diameter %.2f px' % (len(cuts), psf_hfd))

# ---- the crop as in step 8, luminance restored
c8 = s8['crop_stack_px']; x0, y0, cw, ch = c8['x0'], c8['y0'], c8['width'], c8['height']; K = s8['quarter_turns_counter_clockwise']
Y_, X_ = np.mgrid[y0:y0 + ch, x0:x0 + cw]; U, V = (X_ - pc[0]) / 100.0, (Y_ - pc[1]) / 100.0
PAD = 64
def cam_rgb(P, y0_, y1_, x0_, x1_):
    return np.dstack([P[0, y0_:y1_, x0_:x1_] * wb[0], (P[1, y0_:y1_, x0_:x1_] + P[2, y0_:y1_, x0_:x1_]) / 2, P[3, y0_:y1_, x0_:x1_] * wb[2]]).astype(np.float64)
a = cam_rgb(st, y0 - PAD, y0 + ch + PAD, x0 - PAD, x0 + cw + PAD)            # padded by real data, cut after the filter
Yp, Xp = np.mgrid[y0 - PAD:y0 + ch + PAD, x0 - PAD:x0 + cw + PAD]; Up, Vp = (Xp - pc[0]) / 100.0, (Yp - pc[1]) / 100.0
CO = [s8['sky_planes_dn'][c] for c in 'RGB']
for k in range(3): a[..., k] -= CO[k][0] + CO[k][1] * Up + CO[k][2] * Vp
a = a @ RGB_CAM.T
Y = a @ LUMA
Hh = np.zeros_like(Y); Hh[:psf.shape[0], :psf.shape[1]] = psf; Hh = np.roll(Hh, (-R0, -R0), axis=(0, 1)); H = np.fft.fft2(Hh)
Wf = np.conj(H) * (1 + NSR) / (np.abs(H) ** 2 + NSR); mag = np.abs(Wf); Wf = np.where(mag > GAIN_MAX, Wf / np.maximum(mag, 1e-12) * GAIN_MAX, Wf)
Yd = np.real(np.fft.ifft2(np.fft.fft2(Y) * Wf))
sl = (slice(PAD, PAD + ch), slice(PAD, PAD + cw))
a, Y, Yd = a[sl], Y[sl], Yd[sl]
# colour exactly as step 8
SKYM = np.hypot(X_ - pc[0], Y_ - pc[1]) > s8['sky_exclude_px']
C = cv2.GaussianBlur(a, (0, 0), s8['chroma_sigma_px']); Yc = C @ LUMA
sig = clipped_stats(Yc[SKYM])[1]; lo, hi = s8['chroma_snr']
t = np.clip((Yc / sig - lo) / (hi - lo), 0, 1); wgt = t * t * (3 - 2 * t)
ratio = C / np.where(Yc > 0, Yc, 1.0)[..., None]
A = Yd[..., None] * (wgt[..., None] * ratio + (1 - wgt[..., None]))
rr_c = np.hypot(X_ - pc[0], Y_ - pc[1])
WHITE = float(np.percentile(Yd[rr_c < 60], 99.9)); SOFT = s8['stretch']['soft']; OFFSET = s8['stretch']['offset']
with np.errstate(divide='ignore', invalid='ignore'):
    g = np.where(np.abs(Yd) < 1e-9, 1.0 / SOFT, np.arcsinh(Yd / SOFT) / Yd) / np.arcsinh(WHITE / SOFT)
o = np.rot90(np.clip(OFFSET + (1 - OFFSET) * A * g[..., None], 0, 1), K)
cv2.imwrite(W_('decon-stretched.png'), (o[..., ::-1] * 65535 + 0.5).astype(np.uint16))
args = os.environ.get('M57_FINISH_ARGS', '').split()
r = subprocess.run([os.sys.executable, os.path.join(SCR, 'finish.py'), W_('decon-stretched.png'), W_('decon-finished')] + args, capture_output=True, text=True); print(r.stdout.strip(), r.stderr[-500:])
pic = cv2.imread(W_('decon-finished.png'))[..., ::-1]
path = os.path.join(os.environ.get('M57_DECON_OUT', OUT), 'm57-deconvolved.jpg')
Image.fromarray(np.ascontiguousarray(pic), 'RGB').save(path, 'JPEG', quality=92, subsampling=0, optimize=True)
bb = open(path, 'rb').read(); assert b'Exif' not in bb[:4096] and b'http://ns.adobe.com/xap' not in bb

# ---- checks, on the linear luminance: plain (the Gaussian 1 px of step 8) against restored
Yb = cv2.GaussianBlur(Y, (0, 0), s8['blur_sigma_px'])
def hfd_at(img, x, y):
    rmeas = measure(img.astype(np.float32), x, y)
    return None if rmeas is None else 2 * rmeas['hfr']
checks = []
smc = cv2.GaussianBlur(Yb.astype(np.float32), (0, 0), 1.5); mc, sc_, _ = clipped_stats(smc[SKYM][::3])
nc, labc, statc, centc = cv2.connectedComponentsWithStats((smc > mc + 12 * sc_).astype(np.uint8))
for i in range(1, nc):
    lx, ly = centc[i]
    if not (30 < lx < cw - 30 and 30 < ly < ch - 30) or np.hypot(lx + x0 - pc[0], ly + y0 - pc[1]) < 90: continue
    a_, b_, c_ = hfd_at(Y, lx, ly), hfd_at(Yb, lx, ly), hfd_at(Yd, lx, ly)
    if None in (a_, b_, c_): continue
    cut = Yd[int(ly) - 20:int(ly) + 21, int(lx) - 20:int(lx) + 21]; rq = np.hypot(*np.mgrid[-20:21, -20:21])
    ringmin = float(np.min([np.median(cut[(rq >= q) & (rq < q + 2)]) for q in range(6, 18, 2)]))
    checks.append(dict(star_stack_px=[float(lx + x0), float(ly + y0)], hfd_px=dict(unsmoothed=a_, plain_picture=b_, restored=c_), darkest_ring_restored_dn=ringmin))
noise = dict(plain_picture=clipped_stats(Yb[SKYM])[1], restored=clipped_stats(Yd[SKYM])[1], unsmoothed=clipped_stats(Y[SKYM])[1])
def contrast(img):
    ring = np.percentile(img[(rr_c >= 22) & (rr_c < 36)], 90); hole = np.median(img[rr_c < 8]); return dict(ring_p90=float(ring), hole_median=float(hole), hole_over_ring=float(hole / ring))
prof = []
for a_, b_ in ((0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 100)):
    m = (rr_c >= a_) & (rr_c < b_); prof.append(dict(r_px=[a_, b_], plain_picture=round(float(np.mean(Yb[m])), 2), restored=round(float(np.mean(Yd[m])), 2)))
res = dict(nebula_profile_luminance_dn=prof, blur=dict(stars=len(cuts), star_list_x_y_flux_hfd=used, half_flux_diameter_px=float(psf_hfd), radius_px=18), wiener=dict(nsr=NSR, gain_max=GAIN_MAX, applied_to='luminance Y only'),
           stretch=dict(white=WHITE, soft=SOFT, offset=OFFSET), finish_arguments=' '.join(args), stars_in_crop=checks, sky_noise_dn=noise,
           ring_and_hole=dict(plain_picture=contrast(Yb), restored=contrast(Yd)), output='m57-deconvolved.jpg',
           star_hfd_median_px=dict(plain_picture=float(np.median([c['hfd_px']['plain_picture'] for c in checks])) if checks else None, restored=float(np.median([c['hfd_px']['restored'] for c in checks])) if checks else None))
jsave(res, 'step10.json')
print(json.dumps(res, indent=1)[:3000])
