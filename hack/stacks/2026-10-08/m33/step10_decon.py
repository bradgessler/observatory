"""Step 10: a deconvolved version, separate and labelled, with a blur measured from the same stack's stars.

The blur (point-spread function): the luminance L of the stack (render.py's inverse-variance mix of the four planes),
cut out around every compact, unsaturated, isolated star with flux between PSF_MINFLUX and PSF_MAXFLUX (step 2's list,
reference frame; brighter stars reach the sensor's ceiling in the sharpest frames, so their stacked cores are flat),
local sky (ring 20..28 px) subtracted, each shifted onto a common centre (bicubic, sub-pixel), normalised to unit sum,
median over the stars, clipped at zero beyond the first ring that reaches zero, unit sum. One blur for the whole field.

The restoration: a Wiener filter on L only (colour is untouched), in the Fourier domain,
    F = conj(H) (1 + K) / (|H|^2 + K) (1 at zero frequency: total light kept),  |F| capped at GAIN_CAP (phase kept),
H = the transfer function of the measured blur, K = the noise-to-signal ratio, one number. Then exactly the same finish
as step 9 (render.py) except that L is not blurred again (the filter's K already rolls the noise off).
Also tried: Richardson-Lucy (plain multiplicative, fixed rounds, a 200 DN pedestal keeps the noisy sky positive).
Settings tried: Wiener K 0.1 cap 2.0, K 0.3 cap 1.5; Richardson-Lucy 5 and 10 rounds.
Checks written to work/step10_decon.json: the stars' half-flux diameter before and after, the noise in the faint region
before and after, and the darkest ring (moat) round the nucleus and the bright unsaturated stars (ringing).
Delivered only if the stars are at least 10% smaller than in m33.jpg and no moat is deeper than 3 DN:
m33-deconvolved.jpg (and -1600). work/v_decon_compare.jpg shows the gentlest Wiener setting beside the plain picture."""
import json, os
import numpy as np, cv2
from common import *
import render

PSF_MINFLUX = 30000.0
PSF_MAXFLUX = float(os.environ.get('M33_PSF_MAXFLUX', '120000'))     # brighter stars reach the ceiling in the sharpest frames: their stacked cores are flattened
R_PSF = 15
K = float(os.environ.get('M33_WIENER_K', '0.1'))
GAIN_CAP = float(os.environ.get('M33_GAIN_CAP', '2.0'))
s8 = jload('step8_solve.json'); c = s8['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
s9 = jload('step9_deliver.json')
st = np.load(W('stack_mean.npy'))[:, y0:y1, x0:x1]; flat = np.load(W('flat.npy'))[y0:y1, x0:x1]; faint = np.load(W('faint_region.npy'))[y0:y1, x0:x1]
wb = np.array([s9['white_balance_daylight'][k] for k in 'RGB']); RGB_CAM = np.array(s9['rgb_cam'])
noise = [s9['noise_faint_region']['planes_stack'][k] for k in PLANE_NAMES]
wl, wbp = render.lum_weights(noise, wb)
L = sum(wl[k] * st[k] * wbp[k] for k in range(4)).astype(np.float32)
h, w = L.shape
stars = [s for s in json.load(open(W('step2_stars.json'))) if s['stamp'] == REF_STAMP][0]['stars']
cand = [s for s in stars if not s['saturated'] and s['nearest'] > 50 and PSF_MINFLUX < s['flux'] < PSF_MAXFLUX]
hm = np.median([s['hfr'] for s in cand]); cand = [s for s in cand if s['hfr'] <= 1.25 * hm]


def centroid(img, x, y, sw=2.5):
    for _ in range(30):
        xi, yi = int(round(x)), int(round(y)); r = 10
        t = img[yi - r:yi + r + 1, xi - r:xi + r + 1]; yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
        wgt = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sw * sw)) * np.clip(t, 0, None); s = wgt.sum()
        nx, ny = x + 2 * (wgt * (xx - x)).sum() / s, y + 2 * (wgt * (yy - y)).sum() / s
        done = np.hypot(nx - x, ny - y) < 1e-3; x, y = nx, ny
        if done: break
    return x, y


def hfd(img, x, y, rmax=14):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - 30:yi + 31, xi - 30:xi + 31]; yy, xx = np.mgrid[-30:31, -30:31]; r = np.hypot(xx - (x - xi), yy - (y - yi))
    bg = np.median(t[(r > 20) & (r < 28)]); a = r <= rmax; o = np.argsort(r[a]); cum = np.cumsum((t - bg)[a][o])
    return float(2 * r[a][o][np.searchsorted(cum, cum[-1] / 2)])


cuts, used = [], []
for s in cand:
    x, y = s['x'] - x0, s['y'] - y0
    if not (40 < x < w - 40 and 40 < y < h - 40): continue
    x, y = centroid(L, x, y)
    xi, yi = int(round(x)), int(round(y)); big = L[yi - 30:yi + 31, xi - 30:xi + 31].astype(np.float64)
    yy, xx = np.mgrid[-30:31, -30:31]; bg = np.median(big[(np.hypot(xx, yy) > 20) & (np.hypot(xx, yy) < 28)])
    M = np.float32([[1, 0, -(x - xi)], [0, 1, -(y - yi)]])
    sh = cv2.warpAffine((big - bg).astype(np.float32), M, (61, 61), flags=cv2.INTER_CUBIC)
    cut = sh[30 - R_PSF:30 + R_PSF + 1, 30 - R_PSF:30 + R_PSF + 1]
    cuts.append(cut / cut.sum()); used.append([float(x), float(y)])
psf = np.median(np.stack(cuts), axis=0)
yy, xx = np.mgrid[-R_PSF:R_PSF + 1, -R_PSF:R_PSF + 1]; rr = np.hypot(xx, yy)
ring = [np.median(psf[(rr >= k) & (rr < k + 1)]) for k in range(R_PSF)]
r0 = next((k for k, v in enumerate(ring) if v <= 0), R_PSF)
psf = np.clip(psf, 0, None) * (rr <= r0); psf /= psf.sum()
np.save(W('psf.npy'), psf)
# ---- the trials
from scipy.signal import fftconvolve
TRIALS = [('wiener', 0.1, 2.0), ('wiener', 0.3, 1.5), ('richardson-lucy', 5, None), ('richardson-lucy', 10, None)]
pad = 64
Lp = np.pad(L.astype(np.float64), pad, mode='reflect')
Hp = np.zeros(Lp.shape); Hp[:psf.shape[0], :psf.shape[1]] = psf; Hp = np.roll(Hp, (-R_PSF, -R_PSF), axis=(0, 1)); Hfp = np.fft.rfft2(Hp)
Lf = np.fft.rfft2(Lp)


def restore(kind, a, b):
    if kind == 'wiener':
        F = np.conj(Hfp) * (1 + a) / (np.abs(Hfp) ** 2 + a); m_ = np.abs(F); F = np.where(m_ > b, F * b / m_, F)
        return np.fft.irfft2(Lf * F, s=Lp.shape)[pad:-pad, pad:-pad].astype(np.float32)
    PED = 200.0                                  # keeps the noisy sky positive for the multiplicative updates
    x = np.clip(Lp + PED, 1e-3, None); u = x.copy(); pm = psf[::-1, ::-1]
    for _ in range(int(a)):
        u *= fftconvolve(x / np.clip(fftconvolve(u, psf, mode='same'), 1e-6, None), pm, mode='same')
    return (u[pad:-pad, pad:-pad] - PED).astype(np.float32)


n0 = clipped_stats(L[faint])[1]; Lb = cv2.GaussianBlur(L, (0, 0), 1.0); nb = clipped_stats(Lb[faint])[1]
bright = sorted([s for s in stars if not s['saturated'] and s['nearest'] > 50], key=lambda s: -s['flux'])
places = [('nucleus', tuple(s8['catalogue']['M33 nucleus']['pixel']))] + [('star, flux %.0f' % s['flux'], (s['x'] - x0, s['y'] - y0)) for s in bright[:6] + bright[40:43]]


def moat(img, x, y):
    """The darkest 1 px ring 4..24 px from (x, y), against the ring 25..30 px (DN)."""
    xi, yi = int(round(x)), int(round(y)); yy2, xx2 = np.mgrid[-30:31, -30:31]; r2 = np.hypot(xx2 - (x - xi), yy2 - (y - yi)); t = img[yi - 30:yi + 31, xi - 30:xi + 31]
    return float(min(np.median(t[(r2 >= k) & (r2 < k + 1)]) for k in range(4, 25)) - np.median(t[(r2 > 25) & (r2 < 30)]))


res = dict(psf_stars=len(cuts), psf_radius_px=int(r0), psf_hfd_px=float(hfd(np.pad(psf, 30 - R_PSF), 30, 30)),
           plain=dict(star_hfd_px=float(np.median([hfd(L, x, y) for x, y in used])), star_hfd_px_after_1px_blur_as_in_m33_jpg=float(np.median([hfd(Lb, x, y) for x, y in used])),
                      noise_faint_region_dn=n0, noise_after_1px_blur=nb, moats_dn={nm: round(moat(Lb, *xy), 1) for nm, xy in places if 40 < xy[0] < w - 40 and 40 < xy[1] < h - 40}),
           faint_galaxy_light_dn='3 to 20 (green, 5 to 22 arcmin from the nucleus); the black point is at 4 DN', trials=[])
best = None
for kind, a, b in TRIALS:
    Ld = restore(kind, a, b)
    t = dict(kind=kind, wiener_K=a if kind == 'wiener' else None, gain_cap=b, rounds=a if kind != 'wiener' else None,
             star_hfd_px=float(np.median([hfd(Ld, x, y) for x, y in used])), noise_faint_region_dn=clipped_stats(Ld[faint])[1],
             moats_dn={nm: round(moat(Ld, *xy), 1) for nm, xy in places if 40 < xy[0] < w - 40 and 40 < xy[1] < h - 40})
    t['worst_moat_dn'] = min(t['moats_dn'].values())
    t['acceptable'] = bool(t['star_hfd_px'] < 0.9 * res['plain']['star_hfd_px_after_1px_blur_as_in_m33_jpg'] and t['worst_moat_dn'] > -3.0)
    res['trials'].append(t)
    print('%-16s %s: star HFD %.2f px (plain %.2f, as shown %.2f); faint-region noise %.2f DN (plain %.2f, as shown %.2f); worst dark moat round a bright star %.0f DN -> %s' % (
        kind, ('K %.2f cap %.1f' % (a, b)) if kind == 'wiener' else ('%d rounds' % a), t['star_hfd_px'], res['plain']['star_hfd_px'], res['plain']['star_hfd_px_after_1px_blur_as_in_m33_jpg'], t['noise_faint_region_dn'], n0, nb, t['worst_moat_dn'], 'acceptable' if t['acceptable'] else 'not acceptable'), flush=True)
    if kind == 'wiener' and a == 0.3:
        P = dict(render.PARAMS); P['LUM_BLUR'] = 0.0
        rgb, info, _ = render.finish(st, flat, wb, RGB_CAM, noise, P=P, lum_override=Ld)
        ref = cv2.imread(os.path.join(OUT, 'm33.jpg'))[..., ::-1].astype(np.float32) / 255
        render.save_jpeg(np.vstack([np.hstack([ref[584:984, 1270:1870], rgb[584:984, 1270:1870]]), np.hstack([ref[983:1383, 459:1059], rgb[983:1383, 459:1059]])]), W('v_decon_compare.jpg'))
    if t['acceptable'] and best is None: best = (t, Ld)
res['delivered'] = best is not None and os.environ.get('M33_DECON_DELIVER', '1') == '1'
if res['delivered']:
    P = dict(render.PARAMS); P['LUM_BLUR'] = 0.0
    rgb, info, _ = render.finish(st, flat, wb, RGB_CAM, noise, P=P, lum_override=best[1])
    render.save_jpeg(rgb, os.path.join(OUT, 'm33-deconvolved.jpg'))
    hh, ww = rgb.shape[:2]; render.save_jpeg(cv2.resize(rgb, (1600, int(round(hh * 1600 / ww))), interpolation=cv2.INTER_AREA), os.path.join(OUT, 'm33-deconvolved-1600.jpg'))
    res['delivered_trial'] = best[0]
res['verdict'] = ('delivered: m33-deconvolved.jpg' if res['delivered'] else
                  'not delivered: every setting that makes the stars measurably smaller also digs a dark moat round the bright stars, tens to hundreds of DN deep, '
                  'against galaxy light of 3 to 20 DN; on the picture each bright star gets a black ring. Hiding that would need a star mask (a local, selective step), '
                  'and the gain on HII regions and clusters is small at this signal-to-noise. The plain stack is the picture.')
jdump(res, 'step10_decon.json')
print(res['verdict'])
