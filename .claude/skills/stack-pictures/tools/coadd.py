"""Proper image coaddition (Zackay & Ofek 2017, "How to coadd images? II. A coaddition image that is optimal for any
purpose in the background-dominated noise limit", ApJ 836, 188; arXiv:1512.06879), for registered, calibrated,
sky-subtracted frames of one colour plane.

What it does, in one line: every frame is filtered with its own PSF (matched filter), weighted by flux / noise^2, summed,
and the sum is whitened in Fourier space so that its noise is white again:

    R_hat = sum_j (F_j / s_j^2) conj(P_hat_j) M_hat_j  /  sqrt( sum_j (F_j^2 / s_j^2) |P_hat_j|^2 )
    P_R_hat = sqrt( sum_j (F_j^2 / s_j^2) |P_hat_j|^2 ) / F_R,      F_R = sqrt( sum_j F_j^2 / s_j^2 )

(times, by default here, the phase of the frames' weighted mean PSF: an all-pass filter, see proper_coadd's keep_phase)

M_j a frame (sky subtracted), P_j its PSF (sum 1), F_j its flux scale (transparency: a star's flux in the frame over its
flux in a reference frame), s_j its background noise per pixel. ZO's R has white noise of unit variance and a
zero-phase PSF P_R. S = R / F_R is the same image in the flux units of an F = 1 frame (a star's total is its flux
there) with per-pixel noise 1 / F_R. In the background-dominated limit it is a sufficient statistic for any measurement
made on the frames; a point source's matched-filter S/N in it is the best possible, S/N^2 = sum_j S/N_j^2. With
identical PSFs it is the inverse-variance weighted mean: the gain comes from frames whose seeing, focus, trailing or
registration differ.

Here S keeps the phase of the weighted mean PSF (keep_phase='mean'). Only the frame-to-frame differences of phase
(registration error, trailing) are taken out. The optics' own asymmetry stays as it is at each place in the field.
ZO's zero-phase R takes out the field-average asymmetry everywhere, which puts its mirror image on stars where the
optics differ (dark crescents beside bright stars on NGC 2261, 12 October). The phase changes no S/N or noise.

Everything is linear in the pixel values once the outlier mask is fixed: weights, filters and the whitening come from
the PSFs and the noise, never from the image being made. Nothing is predicted and nothing is deconvolved: matching to a
target PSF multiplies by |P_t_hat / P_R_hat| capped at 1, a pure convolution that never gains.

Outliers (satellites, aircraft, cosmic rays, hot pixels the per-frame repair missed): `outlier_mask` compares each
frame, in flux units, with the per-pixel median of all frames. It flags a pixel two ways:
  - per pixel: beyond kappa times the frame's measured residual spread, widened by beta x the median, so that star
    cores whose seeing differs from the median's are not flagged (beta comes from the PSFs' peak spread);
  - on a 3 x 3 box-smoothed residual against its own measured spread, for faint trails and their wings.
Then it grows the mask by 1 px. `proper_coadd` fills each flagged (or uncovered) pixel of frame j in two passes. Pass 1
uses F_j x the inverse-variance mean of the other frames there, from the same subset, so halves stay independent.
Pass 2 uses what that first coadd says frame j saw there (its own PSF). The mask is the only non-linear decision and it
is recorded; given the mask, the result is linear in the data.

Interface (numpy arrays; (x, y) = (column, row) of the frames' common grid):

    psf, info  = measure_psf(img, xy, radius)                       # empirical PSF of one registered frame
    xy2        = refine_positions(img, xy)                          # windowed centroids (on a deep image)
    zones      = field_variation(img, xy, radius, shape=(3, 3))     # does the PSF change across the field?
    mask, info = outlier_mask(cube, flux, sigma, psfs=, noise_map=) # cube (N, H, W), NaN where a frame has no data
    out        = proper_coadd(cube, psfs, flux, sigma, mask=mask, target=None | 'mean-psf' | 'proper' | kernel,
                              keep_phase='mean', keep_hat=False)
    c          = convolve_to(out, Pt_modulus, phase=None)           # a coadd (keep_hat=True) taken to another PSF
    th         = theory(psfs, flux, sigma, weights=None)            # point-source S/N, proper vs a weighted mean
    st         = psf_stats(psf)                                     # HFD, FWHM, ellipticity, centroid of a kernel
    rec        = recipe(flux, sigma, psf_infos, mask_info, out, th) # every number that shaped it, JSON-ready

`proper_coadd` returns S, F_R, psf_R, noise_S (1 / F_R), fill counts and refill info. With a target it also returns C
(S convolved to the target), psf_C and target_info (how much the cap at 1 cut). The 'mean-psf' target is the weighted
mean's PSF exactly, so C is the coadd at the delivered stack's resolution: use it for comparisons, not as a picture.
Its low per-pixel noise only comes from filtering frequencies above the PSF's band.

Run `python test_coadd.py` beside this file for the synthetic test (known star field, known PSFs and noise)."""
import numpy as np
from scipy import fft as sfft
from scipy import ndimage

VERSION = 'coadd.py 1.1 (2026-10-17): mean PSF phase kept, measured outlier thresholds, two-pass refill'
PAPER = 'Zackay B. & Ofek E. O. 2017, ApJ 836, 188 (arXiv:1512.06879)'
WORKERS = 4


# ---------------------------------------------------------------------------------------------------------- PSFs
def psf_stats(psf):
    """Half-flux diameter (px), FWHM (px, from the area above half maximum), ellipticity (1 - b/a from second moments
    inside the HFD x 2), its angle (deg), centroid offset from the kernel centre (px), the sum, and sum(P^2)."""
    k = psf.shape[0]; c = k // 2
    yy, xx = np.mgrid[0:k, 0:k] - c
    tot = float(psf.sum())
    p = psf / tot
    cx, cy = float((p * xx).sum()), float((p * yy).sum())
    r = np.hypot(xx - cx, yy - cy)
    # half-flux diameter: the flux inside radius rho, sampled at every pixel's radius and treated as each pixel's light
    # spread over its own unit-width ring (rho - 0.5, rho + 0.5], interpolated to where it reaches one half
    rs = np.linspace(0, r.max(), 400); cumr = np.array([(p * np.clip(rho - r + 0.5, 0, 1)).sum() for rho in rs])
    hfd = float(2 * np.interp(0.5, cumr, rs))
    fwhm = float(2 * np.sqrt((p >= 0.5 * p.max()).sum() / np.pi))
    w = (r <= hfd) * np.clip(p, 0, None); s = w.sum()
    mxx = (w * (xx - cx) ** 2).sum() / s; myy = (w * (yy - cy) ** 2).sum() / s; mxy = (w * (xx - cx) * (yy - cy)).sum() / s
    tr, det = mxx + myy, mxx * myy - mxy ** 2; d = max(tr * tr / 4 - det, 0) ** 0.5
    a, b = (tr / 2 + d) ** 0.5, max(tr / 2 - d, 1e-12) ** 0.5
    return dict(hfd_px=hfd, fwhm_px=fwhm, ellipticity=float(1 - b / a), angle_deg=float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy))),
                centroid_px=[cx, cy], sum=tot, sum_sq=float((p ** 2).sum()))


def refine_positions(img, xy, sw=2.5, iters=10):
    """Gaussian-windowed centroids (window sigma sw px), iterated. NaN for a star that leaves the image or has no light."""
    h, w = img.shape; out = []
    for x, y in np.asarray(xy, float):
        ok = True
        for _ in range(iters):
            xi, yi = int(round(x)), int(round(y)); r = int(3 * sw) + 2
            if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: ok = False; break
            t = np.nan_to_num(img[yi - r:yi + r + 1, xi - r:xi + r + 1])
            yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]
            wg = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sw * sw)) * np.clip(t, 0, None); s = wg.sum()
            if s <= 0: ok = False; break
            nx, ny = x + 2 * (wg * (xx - x)).sum() / s, y + 2 * (wg * (yy - y)).sum() / s
            dd = np.hypot(nx - x, ny - y); x, y = nx, ny
            if dd < 1e-3: break
        out.append((x, y) if ok else (np.nan, np.nan))
    return np.array(out)


def _fshift(a, dx, dy):
    """Shift an array by (dx, dy) px with the Fourier shift theorem (exact for a band-limited image)."""
    return np.real(np.fft.ifft2(ndimage.fourier_shift(np.fft.fft2(a), (dy, dx))))


def stamps(img, xy, radius, bg_width=5):
    """Cut-outs (2 radius + 1 px) centred exactly on each (x, y) (Fourier shift of the fractional part), the median of
    an annulus radius+1 .. radius+1+bg_width subtracted. Returns stamps (n, k, k), fluxes inside radius, valid flags."""
    k = 2 * radius + 1; m = radius + bg_width + 4; K = 2 * m + 1
    yy, xx = np.mgrid[0:K, 0:K] - m; rr = np.hypot(xx, yy)
    ann = (rr > radius + 1) & (rr <= radius + 1 + bg_width)
    yk, xk = np.mgrid[0:k, 0:k] - radius; inside = np.hypot(xk, yk) <= radius
    h, w = img.shape; S, F, ok = [], [], []
    for x, y in np.asarray(xy, float):
        if not np.isfinite(x): S.append(np.zeros((k, k))); F.append(0.0); ok.append(False); continue
        xi, yi = int(round(x)), int(round(y))
        if xi - m < 0 or yi - m < 0 or xi + m + 1 > w or yi + m + 1 > h: S.append(np.zeros((k, k))); F.append(0.0); ok.append(False); continue
        t = img[yi - m:yi + m + 1, xi - m:xi + m + 1].astype(np.float64)
        if not np.isfinite(t).all(): S.append(np.zeros((k, k))); F.append(0.0); ok.append(False); continue
        t = t - np.median(t[ann])
        t = _fshift(t, -(x - xi), -(y - yi))[m - radius:m + radius + 1, m - radius:m + radius + 1]
        f = float(t[inside].sum()); S.append(t); F.append(f); ok.append(f > 0)
    return np.array(S), np.array(F), np.array(ok)


def taper(radius, width=4.0):
    """The window every PSF is cut with: 1 inside radius - width, cos^2 to 0 at radius, 0 beyond."""
    k = 2 * radius + 1; yy, xx = np.mgrid[0:k, 0:k] - radius; r = np.hypot(xx, yy)
    t = np.clip((radius - r) / width, 0, 1)
    return np.sin(0.5 * np.pi * t) ** 2


def measure_psf(img, xy, radius, noise=None, clip=5.0, taper_width=4.0, min_stars=5):
    """The PSF of one registered frame from its own isolated, unsaturated stars at the positions xy (the same sky
    positions in every frame, so the PSF includes that frame's registration error). Each star's stamp is centred on xy
    (Fourier shift), its annulus median subtracted, divided by its flux inside `radius`; the stamps are combined per
    pixel with a clip (clip x 1.4826 MAD about the median, which drops neighbours and cosmic rays) and weights flux^2
    (inverse variance of the normalised stamp in the background limit), cut with `taper`, and normalised to sum 1.
    Returns (psf, info)."""
    S, F, ok = stamps(img, xy, radius)
    S, F = S[ok], F[ok]
    if len(F) < min_stars: raise ValueError('measure_psf: %d usable stars' % len(F))
    N = S / F[:, None, None]; wgt = (F ** 2)[:, None, None]
    med = np.median(N, 0); mad = 1.4826 * np.median(np.abs(N - med), 0) + 1e-12
    keep = np.abs(N - med) <= clip * mad
    psf = (wgt * keep * N).sum(0) / np.maximum((wgt * keep).sum(0), 1e-30)
    psf = psf * taper(radius, taper_width); psf /= psf.sum()
    info = dict(stars=int(len(F)), radius_px=radius, taper_px=taper_width, clipped_fraction=float(1 - keep.mean()), flux_median=float(np.median(F)))
    if noise is not None:          # the PSF's own noise: per-pixel spread of the normalised stamps / sqrt(n), as a fraction of the peak
        info['noise_over_peak'] = float(np.median(mad) / np.sqrt(len(F)) / psf.max())
    info.update(psf_stats(psf))
    return psf.astype(np.float64), info


def field_variation(img, xy, radius, shape=(3, 3), min_stars=8):
    """The PSF in zones of the field (shape = rows x columns), from the stars in each zone of one deep image, beside the
    PSF of each half of the zone's stars (so the zone-to-zone spread can be told from the measuring noise). Returns a
    dict: per zone HFD, FWHM, ellipticity, angle, stars; the spread of HFD over zones (max/min - 1) and the noise of a
    zone's HFD (from the halves); and `varies`: True when the zones differ by more than 3 x that noise and by more than
    3 percent in HFD or 0.05 in ellipticity."""
    h, w = img.shape; xy = np.asarray(xy, float); zones = []
    for i in range(shape[0]):
        for j in range(shape[1]):
            sel = (xy[:, 0] >= j * w / shape[1]) & (xy[:, 0] < (j + 1) * w / shape[1]) & (xy[:, 1] >= i * h / shape[0]) & (xy[:, 1] < (i + 1) * h / shape[0])
            if sel.sum() < min_stars: zones.append(dict(zone=[i, j], stars=int(sel.sum()))); continue
            p, inf = measure_psf(img, xy[sel], radius)
            idx = np.nonzero(sel)[0]
            pa, _ = measure_psf(img, xy[idx[0::2]], radius, min_stars=3); pb, _ = measure_psf(img, xy[idx[1::2]], radius, min_stars=3)
            a, b = psf_stats(pa), psf_stats(pb)
            zones.append(dict(zone=[i, j], stars=int(sel.sum()), hfd_px=inf['hfd_px'], fwhm_px=inf['fwhm_px'], ellipticity=inf['ellipticity'], angle_deg=inf['angle_deg'],
                              hfd_halves_px=[a['hfd_px'], b['hfd_px']], e_halves=[a['ellipticity'], b['ellipticity']]))
    z = [q for q in zones if 'hfd_px' in q]
    hf = np.array([q['hfd_px'] for q in z]); el = np.array([q['ellipticity'] for q in z])
    noise_h = float(np.median([abs(q['hfd_halves_px'][0] - q['hfd_halves_px'][1]) / 2 for q in z]))
    noise_e = float(np.median([abs(q['e_halves'][0] - q['e_halves'][1]) / 2 for q in z]))
    spread = float(hf.max() / hf.min() - 1); de = float(el.max() - el.min())
    varies = bool((hf.max() - hf.min() > 3 * noise_h and spread > 0.03) or (de > 3 * noise_e and de > 0.05))
    return dict(zones=zones, hfd_spread=spread, hfd_zone_noise_px=noise_h, ellipticity_range=de, ellipticity_zone_noise=noise_e, varies=varies,
                rule='varies if the zones differ by > 3 x the halves\' noise and by > 3% in HFD or > 0.05 in ellipticity')


# ------------------------------------------------------------------------------------------------------ outliers
def _chunks(h, step=128):
    return [(a, min(a + step, h)) for a in range(0, h, step)]


def outlier_mask(cube, flux, sigma, psfs=None, noise_map=None, kappa=5.0, beta=None, beta_min=0.5, kappa_smooth=4.0, smooth=3, grow=1):
    """Flag pixels that disagree with the other frames. cube (N, H, W) with NaN where a frame has no data; flux F_j;
    sigma s_j (background noise per pixel of frame j, in its own units). In flux units X_j = M_j / F_j with noise
    s'_j = s_j / F_j, against the per-pixel median m of the frames that have the pixel:
      pixel test     |X_j - m| > kappa sqrt(r_j^2 + (beta m)^2)
      smoothed test  |B(X_j - m)| > kappa_smooth sqrt(b_j^2 + (beta B(m))^2), B a smooth x smooth box mean
                     (faint trails and the wings of bright ones)
    r_j and b_j are measured: the robust spread (1.4826 MAD) of X_j - m and of B(X_j - m) over the frame. So the
    median's own noise and the resampling's correlation between neighbouring pixels (which keeps a box mean noisier
    than s'_j / smooth) are in the thresholds; sigma is reported beside them.
    then each flagged pixel grown by `grow` px (a (2 grow + 1)^2 square).
    noise_map (H, W), optional: the noise's change across the field relative to where sigma was measured (after a
    flat, 1 / flat over its value there); s'_j is multiplied by it, so the corners are not flagged for being noisier.
    beta: how far a star's light may differ between frames because their seeing differs. Given psfs, it is set from
    them: beta = max(beta_min, 2 max_j |peak_j / median peak - 1| / kappa), so that the sharpest frame's star cores are
    never flagged (twice the largest peak ratio allowed); otherwise beta_min. Returns mask (N, H, W) bool, info."""
    import cv2
    N, H, W = cube.shape; flux = np.asarray(flux, np.float64); sigma = np.asarray(sigma, np.float64); sp = sigma / flux
    if beta is None:
        if psfs is not None:
            pk = np.array([p.max() for p in psfs]); rel = float(np.max(np.abs(pk / np.median(pk) - 1)))
            beta = max(beta_min, 2 * rel / kappa); beta_why = 'from the PSFs: the largest peak ratio to the median is %.3f; beta = max(%.2f, 2 x %.3f / kappa)' % (rel + 1, beta_min, rel)
        else:
            beta = beta_min; beta_why = 'beta_min (no PSFs given)'
    else:
        beta_why = 'given'
    med = np.empty((H, W), np.float32)
    for a, b in _chunks(H):
        with np.errstate(all='ignore'):
            med[a:b] = np.nanmedian(cube[:, a:b] / flux[:, None, None].astype(np.float32), axis=0)
    mask = np.zeros(cube.shape, bool); per = []; noise_meas = []
    ker = np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)
    medz = np.nan_to_num(med); medb = cv2.blur(medz, (smooth, smooth))
    nm = np.float32(1) if noise_map is None else noise_map.astype(np.float32)
    def rmad(v):
        v = v[np.isfinite(v)][::7]; return float(1.4826 * np.median(np.abs(v - np.median(v))))
    for j in range(N):
        X = cube[j] / np.float32(flux[j]); d = X - medz; have = np.isfinite(d); d0 = np.where(have, d, 0).astype(np.float32)
        ds = cv2.blur(d0, (smooth, smooth))
        # the residual's own noise, measured (robust, over the whole frame: mostly sky). It includes the median's noise
        # and the resampling's correlation between neighbours, which make the box mean noisier than s / smooth.
        sd = rmad(np.where(have, d0 / nm, np.nan)); sb = rmad(np.where(have, ds / nm, np.nan))
        m1 = have & (np.abs(d0) > kappa * np.sqrt((sd * nm) ** 2 + (beta * medz) ** 2))
        m2 = have & (np.abs(ds) > kappa_smooth * np.sqrt((sb * nm) ** 2 + (beta * medb) ** 2))
        noise_meas.append(dict(residual=sd, residual_box=sb, frame_noise_given=float(sp[j]), box_over_white=float(sb / (sd / smooth))))
        m = m1 | m2
        if grow > 0: m = cv2.dilate(m.astype(np.uint8), ker).astype(bool) & have
        mask[j] = m
        per.append(dict(frame=j, pixel_test=int(m1.sum()), smoothed_test=int(m2.sum()), after_grow=int(m.sum()), fraction=float(m.sum() / max(have.sum(), 1)), **noise_meas[-1]))
    info = dict(rule='flag |X_j - m| > kappa sqrt(r_j^2 + (beta m)^2) per pixel, or |B(X_j - m)| > kappa_smooth sqrt(b_j^2 + (beta B(m))^2) with B a %d x %d box mean; grow %d px; X_j = frame / F_j, m the per-pixel median of all frames that have the pixel, r_j and b_j the robust (1.4826 MAD) spread of X_j - m and of B(X_j - m) over the frame, times noise_map' % (smooth, smooth, grow),
                kappa=kappa, beta=float(beta), beta_why=beta_why, noise_map=None if noise_map is None else dict(min=float(np.min(noise_map)), max=float(np.max(noise_map))), kappa_smooth=kappa_smooth, smooth_box_px=smooth, grow_px=grow, per_frame=per,
                flagged_fraction=float(mask.sum() / max(np.isfinite(cube).sum(), 1)))
    return mask, info


# ------------------------------------------------------------------------------------------------------- coadd
def _embed(psf, shape):
    k = psf.shape[0]; c = k // 2; a = np.zeros(shape, np.float64); a[:k, :k] = psf
    return np.roll(a, (-c, -c), (0, 1))


def _fill_image(cube, mask, flux, sigma):
    """Per pixel, the inverse-variance weighted mean (flux units) over the frames that have it and do not flag it; where
    every frame that has it flags it, the same mean over all of them (nothing better is known); NaN where no frame has
    it. Returns the image and the count of pixels that fell back."""
    N, H, W = cube.shape; flux = np.asarray(flux, np.float64); sigma = np.asarray(sigma, np.float64)
    wj = (flux ** 2 / sigma ** 2).astype(np.float32); out = np.empty((H, W), np.float32); nback = 0
    for a, b in _chunks(H):
        c = cube[:, a:b]; good = np.isfinite(c)
        if mask is not None: good &= ~mask[:, a:b]
        have = np.isfinite(c); none = (good.sum(0) == 0) & (have.sum(0) > 0); good |= have & none[None]; nback += int(none.sum())
        x = np.where(good, c / flux[:, None, None].astype(np.float32), 0)
        ws = (wj[:, None, None] * good).sum(0)
        with np.errstate(all='ignore'):
            out[a:b] = np.where(ws > 0, (wj[:, None, None] * x).sum(0) / ws, np.nan)
    return out, nback


def proper_coadd(cube, psfs, flux, sigma, mask=None, pad=None, target=None, cap=1.0, refill=True, refill_cap=4.0, keep_phase='mean', workers=None, keep_R=False, keep_hat=False):
    """The proper coadd of the frames in cube (N, H, W); psfs (N, k, k) each summing to 1 and centred at k // 2; flux
    F_j; sigma s_j (each frame's background noise per pixel, its own units); mask (N, H, W) True = do not use.

    Pixels a frame lacks (NaN) or flags are filled, so every frame is complete and the sum is linear:
      pass 1   with F_j x the inverse-variance weighted mean of the other frames there (flux units);
      pass 2   (refill=True, where frame j has any filled pixel) with what the pass-1 coadd says frame j saw there:
               F_j x (S_1 convolved with P_j / P_R), the ratio's modulus capped at refill_cap. A filled pixel on a star
               then has frame j's own seeing, not the mean's. Only filled pixels take this value.
    A pixel no frame has is 0 (and NaN in the output). Frames are zero-padded by `pad` px (default the PSF size) so
    nothing wraps around.

    target: None; 'proper' (C = S, no convolution); 'mean-psf' (C is S convolved to |weighted mean of the P_hat_j|, the
    PSF a weighted mean of these frames would have, minus its phase: by Cauchy-Schwarz this never needs a gain above 1);
    or a kernel (k', k') summing to 1, or a transfer function on the coadd's rfft grid (the ratio |P_t_hat| / P_R_hat is
    capped at `cap`, and how much was capped is reported). The target's phase is dropped: C stays centred like S.
    keep_phase: 'mean' (default) puts back the phase of the frames' weighted mean PSF (see the code); 'none' leaves ZO's
    zero-phase R. Either way P_R_hat (returned with keep_hat) is the modulus and phase_hat the phase.
    keep_hat=True keeps S_hat, P_R_hat and phase_hat in the result, for convolve_to (e.g. halves brought to one PSF)."""
    workers = workers or WORKERS
    N, H, W = cube.shape; k = psfs.shape[1]; pad = k if pad is None else pad
    flux = np.asarray(flux, np.float64); sigma = np.asarray(sigma, np.float64)
    Hp, Wp = sfft.next_fast_len(H + 2 * pad, real=True), sfft.next_fast_len(W + 2 * pad, real=True)
    fill, nback = _fill_image(cube, mask, flux, sigma); nofill = ~np.isfinite(fill); fill0 = np.nan_to_num(fill)
    buf = np.zeros((Hp, Wp), np.float64)

    def badmap(j):
        bad = ~np.isfinite(cube[j])
        return bad | mask[j] if mask is not None else bad

    def accumulate(fills):
        num = np.zeros((Hp, Wp // 2 + 1), np.complex128); den2 = np.zeros((Hp, Wp // 2 + 1), np.float64)
        for j in range(N):
            bad = badmap(j)
            buf[:] = 0; buf[pad:pad + H, pad:pad + W] = np.where(bad, fills(j), cube[j]) if bad.any() else cube[j]
            Mh = sfft.rfft2(buf, workers=workers); Ph = sfft.rfft2(_embed(psfs[j], (Hp, Wp)), workers=workers)
            num += (flux[j] / sigma[j] ** 2) * np.conj(Ph) * Mh
            den2 += (flux[j] ** 2 / sigma[j] ** 2) * (Ph.real ** 2 + Ph.imag ** 2)
        return num, den2

    filled = [int(badmap(j).sum()) for j in range(N)]
    num, den2 = accumulate(lambda j: np.float32(flux[j]) * fill0)
    FR = float(np.sqrt((flux ** 2 / sigma ** 2).sum()))
    den = np.sqrt(den2); tiny = 1e-15 * den.max()
    Rh = num / np.maximum(den, tiny)
    PRh = den / FR
    refill_info = None
    if refill and sum(filled) > 0:
        S1h = Rh / FR; capped = 0

        def model(j):
            nonlocal capped
            Ph = sfft.rfft2(_embed(psfs[j], (Hp, Wp)), workers=workers)
            K = Ph / np.maximum(PRh, 1e-30); a = np.abs(K); over = a > refill_cap; capped += int(over.sum())
            K = np.where(over, K * (refill_cap / np.maximum(a, 1e-30)), K)
            E = sfft.irfft2(S1h * K, (Hp, Wp), workers=workers)[pad:pad + H, pad:pad + W]
            return np.where(nofill, 0, flux[j] * E)
        num, den2 = accumulate(model)
        den = np.sqrt(den2); Rh = num / np.maximum(den, tiny)
        refill_info = dict(passes=2, rule='filled pixels of frame j = F_j x (pass-1 coadd convolved with P_j / P_R), |P_j / P_R| capped at %.1f' % refill_cap,
                           capped_frequencies_fraction=float(capped / (N * PRh.size)))
    # the phase: ZO's R has a zero-phase PSF (every frame's PSF phase taken out). keep_phase='mean' puts back the phase of
    # the frames' weighted mean PSF, the part common to all frames (the optics' own asymmetry, averaged over the stars
    # the PSFs were measured on). That is an all-pass filter: S/N, noise and every statistic are unchanged; only the
    # frame-to-frame differences of phase (registration error, trailing) are taken out. Where the optics' asymmetry
    # changes across the field it keeps the stars as the optics draw them there, instead of imposing the field average's
    # mirror image on them (which drew dark crescents beside bright stars on NGC 2261).
    if keep_phase == 'mean':
        wj = flux ** 2 / sigma ** 2; acc = np.zeros_like(Rh)
        for j in range(N): acc += wj[j] * sfft.rfft2(_embed(psfs[j], (Hp, Wp)), workers=workers)
        a_ = np.abs(acc); ph = np.where(a_ > 1e-12 * a_.max(), acc / np.maximum(a_, 1e-300), 1.0); del acc
    else:
        ph = np.ones_like(Rh)
    Rh = Rh * ph
    R = sfft.irfft2(Rh, (Hp, Wp), workers=workers)[pad:pad + H, pad:pad + W]
    S = (R / FR).astype(np.float32); S[nofill] = np.nan
    psf_R = np.roll(sfft.irfft2(PRh * ph, (Hp, Wp), workers=workers), (k // 2, k // 2), (0, 1))[:k, :k]
    out = dict(S=S, F_R=FR, noise_S=1.0 / FR, psf_R=psf_R, pad_px=pad, fft_shape=[Hp, Wp], pixels_filled_per_frame=filled, pixels_without_data=int(nofill.sum()), pixels_flagged_in_every_frame=nback, refill=refill_info,
               keep_phase=keep_phase, S_hat=Rh / FR, P_R_hat=PRh, phase_hat=ph, _geom=(H, W, pad, Hp, Wp, k), _nofill=nofill)
    if keep_R: out['R'] = R.astype(np.float32)
    if target is not None:
        if isinstance(target, str) and target == 'proper':
            Pt, tname = PRh, 'proper: the coadd\'s own PSF, no convolution'
        elif isinstance(target, str) and target == 'mean-psf':
            wj = flux ** 2 / sigma ** 2; acc = np.zeros_like(Rh)
            for j in range(N): acc += wj[j] * sfft.rfft2(_embed(psfs[j], (Hp, Wp)), workers=workers)
            Pt, tname = np.abs(acc) / wj.sum(), 'mean-psf: |sum_j w_j P_hat_j| / sum_j w_j, w_j = F_j^2 / s_j^2 (a weighted mean\'s PSF, its phase dropped)'
        elif isinstance(target, np.ndarray) and target.shape == PRh.shape:
            Pt, tname = np.abs(target), 'a given transfer function (modulus)'
        else:
            Pt, tname = np.abs(sfft.rfft2(_embed(np.asarray(target, np.float64) / np.sum(target), (Hp, Wp)), workers=workers)), 'a given kernel (its modulus; phase dropped)'
        out.update(convolve_to(out, Pt, cap=cap, name=tname, workers=workers))
    if not keep_hat:
        for key in ('S_hat', 'P_R_hat', 'phase_hat', '_nofill'): out.pop(key)
    return out


def convolve_to(out, Pt, cap=1.0, name='', phase=None, workers=None):
    """A proper coadd (proper_coadd(..., keep_hat=True)) convolved to the transfer function Pt (modulus, on its rfft
    grid): C_hat = S_hat x min(Pt / P_R_hat, cap). With cap = 1 this never amplifies a frequency. phase (unit complex,
    same grid), optional: replace the coadd's own phase with this one (an all-pass filter), e.g. to give two halves
    exactly one PSF. Returns C, its PSF psf_C, its transfer function P_C_hat (complex), the per-pixel noise it would have
    for white input noise (noise_C_white) and target_info (how much the cap cut: nothing when Pt <= P_R_hat everywhere,
    e.g. Pt = |the weighted mean's PSF| or the minimum of several coadds')."""
    workers = workers or WORKERS
    H, W, pad, Hp, Wp, k = out['_geom']; PRh = out['P_R_hat']
    G = Pt / np.maximum(PRh, 1e-30); wanted = float(G.max()); capped = G > cap * (1 + 1e-9); pw = PRh ** 2
    tinfo = dict(target=name, max_gain_wanted=wanted, cap=cap, capped_fraction_of_frequencies=float(capped.mean()), capped_fraction_of_psf_power=float((pw * capped).sum() / pw.sum()),
                 phase='replaced' if phase is not None else 'the coadd\'s own')
    G = np.minimum(G, cap)
    base = out['S_hat'] if phase is None else out['S_hat'] * np.conj(out['phase_hat']) * phase
    ph = out['phase_hat'] if phase is None else phase
    C = sfft.irfft2(base * G, (Hp, Wp), workers=workers)[pad:pad + H, pad:pad + W].astype(np.float32); C[out['_nofill']] = np.nan
    psf_C = np.roll(sfft.irfft2(PRh * G * ph, (Hp, Wp), workers=workers), (k // 2, k // 2), (0, 1))[:k, :k]
    return dict(C=C, psf_C=psf_C, P_C_hat=PRh * G, noise_C_white=float(np.sqrt(_rfft_mean(G ** 2, Wp)) * out['noise_S']), target_info=tinfo)


def _rfft_mean(a, Wp):
    """Mean over the full 2-D spectrum of a quantity given on the rfft half-plane (Hermitian symmetric)."""
    wts = np.full(a.shape[1], 2.0); wts[0] = 1.0
    if Wp % 2 == 0: wts[-1] = 1.0
    return float((a * wts[None, :]).sum() / (a.shape[0] * Wp))


# ------------------------------------------------------------------------------------------------------ theory
def theory(psfs, flux, sigma, weights=None):
    """Point-source S/N for a source of flux 1 (per unit of flux, white background noise), from the PSFs and noise:
      proper        sqrt( sum_j F_j^2 ||P_j||^2 / s_j^2 )                       (= the best any method can do)
      weighted mean sqrt( ||sum_j a_j P_j||^2 / sum_j a_j^2 s_j^2 / F_j^2 ),  a_j = w_j / sum w (frames in flux units),
                    w_j = F_j^2 / s_j^2 unless `weights` are given; detected with its own PSF (matched filter)
    and the per-frame share of the proper coadd's S/N^2. The mean's PSF includes each frame's centroid error (the
    PSFs are measured at the same sky positions), the proper coadd's phase-only correction removes it."""
    flux = np.asarray(flux, np.float64); sigma = np.asarray(sigma, np.float64)
    n2 = np.array([(p ** 2).sum() for p in psfs])
    snr2_j = flux ** 2 * n2 / sigma ** 2
    w = flux ** 2 / sigma ** 2 if weights is None else np.asarray(weights, np.float64)
    a = w / w.sum(); Pm = np.tensordot(a, psfs, 1)
    var = (a ** 2 * sigma ** 2 / flux ** 2).sum()
    snr_mean = float(np.sqrt((Pm ** 2).sum() / var)); snr_proper = float(np.sqrt(snr2_j.sum()))
    return dict(snr_proper=snr_proper, snr_weighted_mean=snr_mean, gain=snr_proper / snr_mean, share=(snr2_j / snr2_j.sum()).tolist(),
                mean_weights=a.tolist(), effective_frames_proper=float(snr2_j.sum() ** 2 / (snr2_j ** 2).sum()))


def recipe(flux, sigma, psf_infos, mask_info, out, th=None, stamps_of=None, extra=None):
    """Every number that shaped a coadd, JSON-ready."""
    flux = np.asarray(flux, float); sigma = np.asarray(sigma, float)
    r = dict(method='proper image coaddition', paper=PAPER, tool=VERSION,
             formula='R_hat = sum_j (F_j/s_j^2) conj(P_hat_j) M_hat_j / sqrt(sum_j (F_j^2/s_j^2) |P_hat_j|^2); S = R / F_R, F_R = sqrt(sum_j F_j^2/s_j^2); PSF of S: P_R_hat = sqrt(sum_j (F_j^2/s_j^2) |P_hat_j|^2) / F_R',
             linear='given the outlier mask, S is linear in the frames; the weights and filters come from the PSFs and the noise only',
             phase=out.get('keep_phase'), F_R=out['F_R'], noise_per_pixel_flux_units=out['noise_S'], fft_shape=out['fft_shape'], pad_px=out['pad_px'], pixels_without_data=out['pixels_without_data'],
             psf_R=psf_stats(out['psf_R']),
             frames=[dict(index=j, stamp=(stamps_of[j] if stamps_of else None), flux_scale=float(flux[j]), noise=float(sigma[j]), weight_F2_over_s2=float(flux[j] ** 2 / sigma[j] ** 2),
                          pixels_filled=out['pixels_filled_per_frame'][j], psf={k: v for k, v in psf_infos[j].items()},
                          share_of_point_source_snr2=(th['share'][j] if th else None)) for j in range(len(flux))],
             outliers=mask_info)
    if 'target_info' in out: r['target'] = dict(out['target_info'], psf=psf_stats(out['psf_C']), noise_per_pixel_white=out['noise_C_white'])
    if th: r['theory'] = {k: v for k, v in th.items() if k not in ('share', 'mean_weights')}
    if extra: r.update(extra)
    return r
