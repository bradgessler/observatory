"""Step 10: a SEPARATE, LABELLED version restored by deconvolution (m31-deconvolved.jpg, -1600.jpg). The delivered
picture is m31.jpg; this one is offered beside it, never over it.

The blur is measured from the same stack's own stars: isolated, unsaturated stars of step 5 (more than 400 sensor px
from the nucleus, no neighbour within 40 px), every other one by position; each cut out, its local level (a ring
RING px out) taken off, centred to a fraction of a pixel (cubic), scaled to unit flux; the median per colour (R, G, B
each from its own channel). The other half of the stars is the check.

Restoration: a Wiener filter per colour towards a Gaussian target blur TARGET_FRAC x the measured FWHM (see wiener()),
amplifying no spatial frequency by more than GAIN_CAP; the total light is kept. No iterations, no learned parts.
(Tried first and dropped: the plain Wiener filter, no target, cap 2.6: stars went from 4.43 to 2.97 arcsec half-flux
diameter, but it dug a dark ring round every star, 4.8% of the star's peak (median; 189 DN, worst 963 DN) where the
galaxy round the stars is 14 DN: black holes. With a Gaussian target (blur cut out to 20 px, cosine taper from 14):
cap 2.5 / target 0.8 x FWHM gave rings median 15, worst 164 DN and 45% more grain at 1 px; cap 1.8 / target 0.9 gave
median 11, worst 56 DN, 17% more grain, stars only 4% narrower. Delivered: cap 2.0 / target 0.85.) Then the same stretch and finish as step 9, with
step 9's white point (lowered only if the sharper nucleus would clip).

Checks on the check stars (green): FWHM and half-flux diameter before and after; the dark ring a restoration digs
round a star (the deepest point of the ring-median profile between 1.2 and 4 FWHM, against the star's local level),
in DN and as a fraction of the star's peak; the grain (scatter of the picture minus its 5 x 5 median) in step 9's
faint patch, before and after."""
import os, json
import numpy as np, cv2, tifffile
from common import *
import measure, render9

GAIN_CAP = float(os.environ.get('M31_DECON_GAIN', '2.0'))
TARGET_FRAC = float(os.environ.get('M31_DECON_TARGET', '0.85'))
R_PSF, RING = int(os.environ.get('M31_PSF_R', '20')), (22, 30)
TAPER = float(os.environ.get('M31_PSF_TAPER', '14'))           # px: the measured blur is faded to zero between TAPER and R_PSF (cosine), not cut off
S9 = jload('step9.json'); Q = jload('step5_quality.json')
x0, y0 = S9['rect_plane_px'][:2]
rgb = tifffile.imread(os.path.join(OUT, 'm31-stack.tif')).astype(np.float32) - S9['pedestal']
h, w = rgb.shape[:2]

stars = []
for k, xy in Q['star_xy'].items():
    sx, sy = (xy[0] - 0.5) / 2 - x0, (xy[1] - 0.5) / 2 - y0
    if not (40 < sx < w - 40 and 40 < sy < h - 40): continue
    a = measure.star(np.ascontiguousarray(rgb[:, :, 1]), sx, sy, ap=14, sw=5.0, ann=(19, 27))
    if a and a['fwhm'] and a['elong'] < 1.35: stars.append(a)
stars.sort(key=lambda a: (a['y'] // 300, a['x']))
psf_set, check_set = stars[0::2], stars[1::2]
print('stars: %d usable, %d for the blur, %d to check' % (len(stars), len(psf_set), len(check_set)), flush=True)


def psf_from(img, sel):
    cuts = []; R = RING[1] + 4
    for a in sel:
        x, y = a['x'], a['y']; xi, yi = int(round(x)), int(round(y))
        t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64)
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
        t = t - np.median(t[(rr >= RING[0]) & (rr < RING[1])])
        M = np.float32([[1, 0, -(x - xi)], [0, 1, -(y - yi)]])
        t = cv2.warpAffine(t.astype(np.float32), M, (2 * R + 1, 2 * R + 1), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        c = t[R - R_PSF:R + R_PSF + 1, R - R_PSF:R + R_PSF + 1].astype(np.float64)
        cuts.append(c / c.sum())
    p = np.median(np.stack(cuts), axis=0)
    yy, xx = np.mgrid[-R_PSF:R_PSF + 1, -R_PSF:R_PSF + 1]
    rr = np.hypot(xx, yy); win = np.where(rr <= TAPER, 1.0, np.where(rr >= R_PSF, 0.0, 0.5 * (1 + np.cos(np.pi * (rr - TAPER) / (R_PSF - TAPER)))))
    p = np.clip(p, 0, None) * win
    return p / p.sum()


def wiener(img, psf, cap, target_sigma):
    """Wiener filter towards a Gaussian target blur: G = H* T / (|H|^2 + k), T the target's transfer function
    (Gaussian, sigma target_sigma px), so that the restored blur is T x |H|^2 / (|H|^2 + k): close to the smooth
    Gaussian target where the stars carry signal, falling away where they carry none. k is the smallest (bisection)
    for which no spatial frequency is amplified by more than cap; T(0) = 1, so the total light is kept."""
    pad = 64
    x = np.pad(img.astype(np.float64), pad, mode='reflect'); H_, W_ = x.shape
    P = np.zeros((H_, W_)); r = psf.shape[0] // 2
    P[:psf.shape[0], :psf.shape[1]] = psf; P = np.roll(P, (-r, -r), axis=(0, 1))
    Hf = np.fft.rfft2(P)
    fy = np.fft.fftfreq(H_)[:, None]; fx = np.fft.rfftfreq(W_)[None, :]
    T = np.exp(-2 * np.pi ** 2 * target_sigma ** 2 * (fx ** 2 + fy ** 2))
    lo, hi = 1e-8, 10.0
    for _ in range(80):
        k = np.sqrt(lo * hi); g = np.abs(np.conj(Hf) * T / (np.abs(Hf) ** 2 + k)).max()
        if g > cap: lo = k
        else: hi = k
    k = hi; G = np.conj(Hf) * T / (np.abs(Hf) ** 2 + k)
    G = G / G[0, 0].real                                              # total light kept exactly
    out = np.fft.irfft2(np.fft.rfft2(x) * G, s=x.shape)
    return out[pad:-pad, pad:-pad].astype(np.float32), float(np.abs(G).max()), float(k)


psfs = [psf_from(rgb[:, :, c], psf_set) for c in range(3)]
fw = measure.star(np.pad(psfs[1].astype(np.float32) * 1e6, 40), 40 + R_PSF, 40 + R_PSF, ap=14, sw=5.0, ann=(19, 27))['fwhm']
TARGET_SIGMA = TARGET_FRAC * fw / 2.3548                           # px: the blur aimed for, a fraction of the measured green FWHM
dec = np.empty_like(rgb); gains = []; ks = []
for c in range(3):
    dec[:, :, c], g, k = wiener(rgb[:, :, c], psfs[c], GAIN_CAP, TARGET_SIGMA); gains.append(g); ks.append(k)
print('measured green FWHM %.2f px; target FWHM %.2f px; largest gain per colour %s; k %s' % (fw, TARGET_SIGMA * 2.3548, np.round(gains, 3).tolist(), np.round(ks, 5).tolist()), flush=True)


def ring_depth(img, a, fwhm):
    x, y = a['x'], a['y']; xi, yi = int(round(x)), int(round(y)); R = 30
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
    lb = np.median(t[(rr > 22) & (rr < 29)])
    prof = np.array([np.median(t[(rr >= k_ - 0.5) & (rr < k_ + 0.5)]) - lb for k_ in range(0, 22)])
    pk = float(t[rr <= 1.0].mean() - lb)
    lo, hi = int(np.ceil(1.2 * fwhm)), int(np.floor(4 * fwhm))
    m = float(prof[lo:hi + 1].min())
    return m, m / pk, lb


def check(img):
    rows = []
    for a in check_set:
        b = measure.star(np.ascontiguousarray(img), a['x'], a['y'], ap=14, sw=5.0, ann=(19, 27))
        if b and b['fwhm']:
            d, f, lb = ring_depth(img, b, b['fwhm']); rows.append((b['fwhm'], b['hfd'], d, f, lb))
    r_ = np.array(rows)
    return dict(stars=len(rows), fwhm_arcsec=round(float(np.median(r_[:, 0])) * 2 * SCALE, 2), hfd_arcsec=round(float(np.median(r_[:, 1])) * 2 * SCALE, 2),
                ring_deepest_dn=dict(median=round(float(np.median(r_[:, 2])), 2), worst=round(float(r_[:, 2].min()), 2)),
                ring_deepest_fraction_of_peak=dict(median=round(float(np.median(r_[:, 3])), 4), worst=round(float(r_[:, 3].min()), 4)),
                local_galaxy_level_dn_median=round(float(np.median(r_[:, 4])), 1))


before, after = check(rgb[:, :, 1]), check(dec[:, :, 1])
pw = S9['numbers']['noise']['where']; import re
m = re.search(r'x (\d+)\.\.(\d+) y (\d+)\.\.(\d+)', pw); px0, px1, py0, py1 = map(int, m.groups())
def grain(img, s_):
    v = np.ascontiguousarray(img)
    b = cv2.GaussianBlur(v, (0, 0), s_) if s_ > 0 else v
    d = (b - cv2.GaussianBlur(v, (0, 0), 12))[py0:py1, px0:px1]
    return round(float(clipped_stats(d)[1]), 2)
# the grain at the scale of single pixels and at the scales where it is seen (Gaussian 1 and 2 px), large scales removed
gr = {('pixel' if s_ == 0 else 'gauss_%d_px' % s_): dict(before=[grain(rgb[:, :, c], s_) for c in range(3)], after=[grain(dec[:, :, c], s_) for c in range(3)]) for s_ in (0, 1, 2)}
print('check stars before', before, '\n            after ', after, '\n grain R G B', gr, flush=True)

# the same stretch and finish as step 9, starting from step 9's white point
nuc = S9['nucleus_crop_px']; Gd = dec[:, :, 1]
ax, ay = int(round(nuc[0])), int(round(nuc[1]))
gnuc = float(cv2.GaussianBlur(cv2.medianBlur(np.ascontiguousarray(Gd[ay - 60:ay + 60, ax - 60:ax + 60]), 5), (0, 0), 1.5).max())
st9 = S9['stretch']; soft, fl = st9['soft'], st9['floor']
a_, b_ = np.arcsinh(-fl / soft), np.arcsinh(st9['white_dn'] / soft)
c0 = float((np.arcsinh(min(gnuc, st9['white_dn']) / soft) - a_) / (b_ - a_))
core_list = [c0] + [v for v in (0.85, 0.82, 0.79, 0.76, 0.73, 0.70, 0.67) if v < c0]
fin16, fin8, srec, core = render9.picture(dec, nuc, gnuc, W('m31-deconvolved-finished'), S9['finish'], core_list, soft, fl, st9['colour_pedestal'], st9['chroma_sigma_px'], log=lambda m_: print(m_, flush=True))
p1, p2, sky = render9.save_jpegs(fin16, OUT, 'm31-deconvolved')
print(sky, 'core', core, flush=True)
np.save(W('psf_rgb.npy'), np.stack(psfs))
jdump(dict(method=__doc__ + wiener.__doc__, psf_taper_px=[TAPER, R_PSF], gain_cap=GAIN_CAP, target_fraction_of_measured_fwhm=TARGET_FRAC, target_fwhm_px=TARGET_SIGMA * 2.3548, k_per_colour=ks, largest_gain_per_colour=gains, psf_radius_px=R_PSF, psf_ring_px=RING, stars_for_blur=len(psf_set), stars_to_check=len(check_set),
           psf_fwhm_px_green=round(float(measure.star(np.pad(psfs[1].astype(np.float32) * 1e6, 40), 40 + R_PSF, 40 + R_PSF, ap=14, sw=5.0, ann=(19, 27))['fwhm']), 2),
           check_before=before, check_after=after, grain_rgb=gr, nucleus_green_dn=gnuc, stretch=srec, core=core, skycheck=sky.strip().split('\n'), files=[os.path.basename(p1), os.path.basename(p2)]), 'step10.json')
