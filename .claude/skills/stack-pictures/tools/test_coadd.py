"""Synthetic test of coadd.py: frames of a known star field, each with its own known PSF, flux scale and noise, combined
by the proper coadd and by the plain inverse-variance weighted mean (the stacking used until now, without its clip),
with the point-source S/N of each measured and compared with theory. Deterministic (fixed seeds). Exit status 0 when
every check passes. Run: ~/.observatory/pyenv/bin/python test_coadd.py [--json out.json]

Regimes
  steady    like NGC 891 on 12 October: FWHM 4.6 to 5.6 px (3.6 to 4.4 arcsec at 0.78 arcsec/px), transparency 0.97 to
            1.0, noise within 5 percent, registration error 0.2 px rms
  variable  seeing 2.5 to 7 px, three frames trailed, transparency 0.4 to 1, noise 20 to 40, registration error 0.3 px
For each: (1) the PSFs known exactly and the stars on whole pixels (so the frames are exactly F_j P_j * sky + noise and
measured S/N must equal theory); (2) stars at sub-pixel places drawn from the analytic PSF at 5 x 5 sub-samples per
pixel, and the PSFs MEASURED from the frames' own stars with coadd.measure_psf, as the pipeline does.
S/N of a point source: the image filtered with its own PSF (the matched filter, the best detector for each image), at
the star, over the standard deviation of the same filter applied to the noise-only coadd (linearity lets signal and
noise be coadded separately). Also: outliers (cosmic rays, a satellite trail) found and removed; linearity; flux."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import coadd

Hs = Ws = 640
NSTAR = 160


def moffat(dx, dy, fwhm, e=0.0, ang=0.0, beta=3.0):
    a = fwhm / (2 * np.sqrt(2 ** (1 / beta) - 1)); q = 1 - e
    c, s = np.cos(ang), np.sin(ang); u = c * dx + s * dy; v = -s * dx + c * dy
    return (1 + (u ** 2 + (v / q) ** 2) / a ** 2) ** (-beta)


def psf_fn(p):
    """A frame's PSF as a function of (dx, dy): Moffat, shifted by the registration error, smeared along a trail."""
    def f(dx, dy):
        out = 0.0; n = max(1, int(np.ceil(p['trail'] * 2)) + 1)
        for t in np.linspace(-p['trail'] / 2, p['trail'] / 2, n):
            out = out + moffat(dx - p['jx'] - t * np.cos(p['tang']), dy - p['jy'] - t * np.sin(p['tang']), p['fwhm'], p['e'], p['ang'])
        return out / n
    return f


def kernel(p, radius, sub=5):
    k = 2 * radius + 1; o = (np.arange(sub) + 0.5) / sub - 0.5
    yy, xx = np.mgrid[0:k, 0:k] - radius; acc = np.zeros((k, k)); f = psf_fn(p)
    for a in o:
        for b in o: acc += f(xx + a, yy + b)
    return acc / acc.sum()


def frames_params(regime, n, rng):
    P = []
    for j in range(n):
        if regime == 'steady':
            P.append(dict(fwhm=rng.uniform(4.6, 5.6), e=rng.uniform(0, 0.06), ang=rng.uniform(0, np.pi), jx=rng.normal(0, 0.2), jy=rng.normal(0, 0.2), trail=0.0, tang=0.0,
                          F=rng.uniform(0.97, 1.0), s=30 * rng.uniform(0.975, 1.025)))
        else:
            P.append(dict(fwhm=rng.uniform(2.5, 7.0), e=rng.uniform(0, 0.1), ang=rng.uniform(0, np.pi), jx=rng.normal(0, 0.3), jy=rng.normal(0, 0.3),
                          trail=(rng.uniform(3, 6) if j in (3, 9, 15) else 0.0), tang=0.6, F=rng.uniform(0.4, 1.0), s=rng.uniform(20, 40)))
    return P


def value_at(img, x, y, r=12):
    """The value of a band-limited image at (x, y), by a Fourier shift of a cut-out."""
    xi, yi = int(round(x)), int(round(y)); t = img[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float64)
    return float(coadd._fshift(t, -(x - xi), -(y - yi))[r, r])


def mfilter(img, psf):
    """Correlate with a PSF (the matched filter); zero padding."""
    from scipy.signal import fftconvolve
    return fftconvolve(np.nan_to_num(img), psf[::-1, ::-1], mode='same')


def run(regime, measured, seed=1, n=24, radius=20):
    rng = np.random.default_rng(seed)
    P = frames_params(regime, n, rng)
    flux = np.array([p['F'] for p in P]); sig = np.array([p['s'] for p in P])
    m = 40
    if measured:
        xy = np.column_stack([rng.uniform(m, Ws - m, NSTAR), rng.uniform(m, Hs - m, NSTAR)])
    else:
        xy = np.column_stack([rng.integers(m, Ws - m, NSTAR), rng.integers(m, Hs - m, NSTAR)]).astype(float)
    f = 10 ** rng.uniform(3.3, 5.3, NSTAR)                 # star fluxes 2,000 to 200,000 (sum over the PSF, F = 1 frame)
    true_k = np.array([kernel(p, radius) for p in P])
    sigc = np.zeros((n, Hs, Ws), np.float32); noic = np.zeros((n, Hs, Ws), np.float32)
    for j, p in enumerate(P):
        img = np.zeros((Hs, Ws))
        if measured:
            fn = psf_fn(p); o = (np.arange(5) + 0.5) / 5 - 0.5; R = radius
            for (x, y), fl in zip(xy, f):
                xi, yi = int(round(x)), int(round(y)); yy, xx = np.mgrid[yi - R:yi + R + 1, xi - R:xi + R + 1]
                acc = np.zeros(xx.shape)
                for a in o:
                    for b in o: acc += fn(xx + a - x, yy + b - y)
                img[yi - R:yi + R + 1, xi - R:xi + R + 1] += fl * acc / acc.sum()
        else:
            for (x, y), fl in zip(xy.astype(int), f):
                img[y - radius:y + radius + 1, x - radius:x + radius + 1] += fl * true_k[j]
        sigc[j] = p['F'] * img
        noic[j] = rng.normal(0, p['s'], (Hs, Ws))
    if measured:
        iso = []
        for i in range(NSTAR):
            d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9
            if d.min() > 2.2 * radius and f[i] > 2e4: iso.append(i)
        psfs = []; infos = []
        for j in range(n):
            pj, inf = coadd.measure_psf(sigc[j] + noic[j], xy[iso], radius); psfs.append(pj); infos.append(inf)
        psfs = np.array(psfs)
    else:
        psfs = true_k; iso = []
    th = coadd.theory(true_k, flux, sig)                    # theory always from the true PSFs
    cs = coadd.proper_coadd(sigc, psfs, flux, sig, target='mean-psf'); cn = coadd.proper_coadd(noic, psfs, flux, sig, target='mean-psf')
    # the weighted mean, frames in flux units, weights F^2/s^2 (the pipeline's weights (T / noise)^2 after x 1/T)
    a = flux ** 2 / sig ** 2; a = a / a.sum()
    ms = np.tensordot(a, sigc / flux[:, None, None], 1); mn = np.tensordot(a, noic / flux[:, None, None], 1)
    Pm = np.tensordot(a, true_k, 1)
    inner = (xy[:, 0] > 50) & (xy[:, 0] < Ws - 50) & (xy[:, 1] > 50) & (xy[:, 1] < Hs - 50)
    def snr(sig_img, noi_img, psf):
        t = mfilter(sig_img, psf); tn = mfilter(noi_img, psf)
        v = np.array([value_at(t, x, y) for x, y in xy[inner]]) / f[inner]
        return float(np.median(v) / tn[60:-60, 60:-60].std())
    sp = snr(cs['S'], cn['S'], cs['psf_R']); sm = snr(ms, mn, Pm)
    # noise per pixel at the same PSF: C (proper, convolved to the mean's PSF minus its phase) against the mean
    nC, nM = float(cn['C'][60:-60, 60:-60].std()), float(mn[60:-60, 60:-60].std())
    # flux: the proper image's total over a big aperture around isolated stars against the truth
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]; ap = np.hypot(xx, yy) <= radius
    iso2 = [i for i in range(NSTAR) if inner[i] and np.sort(np.hypot(*(xy - xy[i]).T))[1] > 2.5 * radius]
    fr = [float((cs['S'][int(round(xy[i, 1])) - radius:int(round(xy[i, 1])) + radius + 1, int(round(xy[i, 0])) - radius:int(round(xy[i, 0])) + radius + 1] * ap).sum() / f[i]) for i in iso2]
    out = dict(regime=regime, psfs='measured from the frames (%d stars)' % len(iso) if measured else 'known exactly', frames=n,
               fwhm_px=[round(p['fwhm'], 2) for p in P], trail_px=[round(p['trail'], 1) for p in P], flux_scale=[round(x, 3) for x in flux], noise=[round(x, 1) for x in sig],
               theory_snr_per_unit_flux=dict(proper=th['snr_proper'], weighted_mean=th['snr_weighted_mean'], gain=th['gain']),
               measured_snr_per_unit_flux=dict(proper=sp, weighted_mean=sm, gain=sp / sm),
               proper_over_theory=sp / th['snr_proper'], mean_over_theory=sm / th['snr_weighted_mean'],
               noise_at_the_means_psf=dict(proper_convolved=nC, weighted_mean=nM, ratio=nC / nM, predicted_ratio=cn['noise_C_white'] / float(np.sqrt((a ** 2 * sig ** 2 / flux ** 2).sum()))),
               psf_hfd_px=dict(proper=coadd.psf_stats(cs['psf_R'])['hfd_px'], weighted_mean=coadd.psf_stats(Pm)['hfd_px']),
               flux_recovered=dict(median=float(np.median(fr)), stars=len(fr)))
    if measured:
        out['psf_error'] = dict(rms_over_peak=float(np.median([np.sqrt(((psfs[j] - true_k[j]) ** 2).mean()) / true_k[j].max() for j in range(n)])),
                                hfd_measured_over_true=float(np.median([coadd.psf_stats(psfs[j])['hfd_px'] / coadd.psf_stats(true_k[j])['hfd_px'] for j in range(n)])))
    return out, (sigc, noic, psfs, flux, sig, xy, f, radius)


def outliers_and_linearity(data, seed=7):
    """Cosmic rays and a satellite trail in two frames: found, removed, and the result against the clean coadd."""
    sigc, noic, psfs, flux, sig, xy, f, radius = data
    rng = np.random.default_rng(seed)
    clean = sigc + noic; dirty = clean.copy(); n = len(flux)
    cr = []
    for j in range(n):                                     # 40 cosmic rays per frame: 1 to 3 px, 300 to 20,000 DN
        for _ in range(40):
            x, y = rng.integers(30, Ws - 30), rng.integers(30, Hs - 30); v = rng.uniform(300, 20000)
            dirty[j, y, x] += v; cr.append((j, x, y))
            if rng.uniform() < 0.5: dirty[j, y, x + 1] += 0.4 * v
    yy, xx = np.mgrid[0:Hs, 0:Ws]
    trail = np.exp(-0.5 * ((yy - (0.35 * xx + 100)) / 1.3) ** 2)   # a satellite: a line 3 px wide (FWHM) at 4 x the frame's noise at its core
    faint = np.exp(-0.5 * ((yy - (-0.5 * xx + 560)) / 1.3) ** 2)   # a fainter one at 2 x the noise (reported, not required)
    for j in (4, 11): dirty[j] += 4 * sig[j] * trail
    dirty[17] += 2 * sig[17] * faint
    mask, minfo = coadd.outlier_mask(dirty, flux, sig, psfs=psfs)
    a = coadd.proper_coadd(dirty, psfs, flux, sig, mask=mask)['S']; b = coadd.proper_coadd(clean, psfs, flux, sig, mask=mask)['S']
    c = coadd.proper_coadd(clean, psfs, flux, sig)['S']; nomask = coadd.proper_coadd(dirty, psfs, flux, sig)['S']
    noise = float(np.std((c - coadd.proper_coadd(sigc, psfs, flux, sig)['S'])[60:-60, 60:-60]))
    on_trail = (trail > 0.3)[60:-60, 60:-60]; on_faint = (faint > 0.3)[60:-60, 60:-60]
    star_core = np.zeros((Hs, Ws), bool)
    for x, y in xy: star_core[max(int(y) - 3, 0):int(y) + 4, max(int(x) - 3, 0):int(x) + 4] = True
    clean_mask, _ = coadd.outlier_mask(clean, flux, sig, psfs=psfs)
    # linearity: with the mask fixed, coadd(signal + noise) = coadd(signal) + coadd(noise)
    s1 = coadd.proper_coadd(sigc, psfs, flux, sig, mask=mask)['S']; s2 = coadd.proper_coadd(noic, psfs, flux, sig, mask=mask)['S']
    s3 = coadd.proper_coadd(sigc + noic, psfs, flux, sig, mask=mask)['S']
    return dict(beta=minfo['beta'], beta_why=minfo['beta_why'], cosmic_rays=len(cr), cosmic_rays_flagged=int(sum(mask[j, y, x] for j, x, y in cr)), satellite_frames=[4, 11],
                satellite_core_pixels_flagged_fraction=float(np.mean([mask[j][trail > 0.5].mean() for j in (4, 11)])),
                flagged_fraction=minfo['flagged_fraction'], flagged_fraction_clean_frames=float(clean_mask.mean()),
                star_core_pixels_flagged_in_clean_frames=float(clean_mask[:, star_core].mean()),
                residual_on_trail_after_over_noise=float(np.abs((a - c)[60:-60, 60:-60][on_trail]).mean() / noise),
                residual_on_trail_without_mask_over_noise=float(np.abs((nomask - c)[60:-60, 60:-60][on_trail]).mean() / noise),
                faint_trail_core_pixels_flagged_fraction=float(mask[17][faint > 0.5].mean()),
                residual_on_faint_trail_after_over_noise=float(np.abs((a - c)[60:-60, 60:-60][on_faint]).mean() / noise),
                residual_on_faint_trail_without_mask_over_noise=float(np.abs((nomask - c)[60:-60, 60:-60][on_faint]).mean() / noise),
                max_residual_after_over_noise=float(np.abs(a - c)[60:-60, 60:-60].max() / noise),
                mask_cost_noise_increase=float(np.std(coadd.proper_coadd(noic, psfs, flux, sig, mask=mask)['S'][60:-60, 60:-60]) / np.std(coadd.proper_coadd(noic, psfs, flux, sig)['S'][60:-60, 60:-60]) - 1),
                star_flux_change_from_the_mask=float(np.median([(b - c)[int(y) - 6:int(y) + 7, int(x) - 6:int(x) + 7].sum() / fl for (x, y), fl in zip(xy, f) if 60 < x < Ws - 60 and 60 < y < Hs - 60])),
                linearity_max_abs_error_over_noise=float(np.abs(s3 - s1 - s2)[60:-60, 60:-60].max() / noise))


if __name__ == '__main__':
    res = {}; ok = True; checks = []
    def check(name, cond, val):
        global ok
        checks.append(dict(check=name, value=val, passed=bool(cond))); ok &= bool(cond)
        print('  %-70s %-28s %s' % (name, ('%.4f' % val) if isinstance(val, float) else val, 'ok' if cond else 'FAILED'))
    keep = None
    for regime in ('steady', 'variable'):
        for measured in (False, True):
            r, data = run(regime, measured)
            key = '%s, %s' % (regime, 'measured PSFs' if measured else 'known PSFs'); res[key] = r
            t, m = r['theory_snr_per_unit_flux'], r['measured_snr_per_unit_flux']
            print('%s: S/N per unit flux, theory proper %.5f mean %.5f gain %.4f | measured proper %.5f mean %.5f gain %.4f | noise at the mean\'s PSF %.4f (predicted %.4f) | HFD proper %.2f mean %.2f px | flux %.4f' % (
                key, t['proper'], t['weighted_mean'], t['gain'], m['proper'], m['weighted_mean'], m['gain'], r['noise_at_the_means_psf']['ratio'], r['noise_at_the_means_psf']['predicted_ratio'], r['psf_hfd_px']['proper'], r['psf_hfd_px']['weighted_mean'], r['flux_recovered']['median']))
            if measured: print('   PSF error: rms/peak %.4f, HFD measured/true %.4f' % (r['psf_error']['rms_over_peak'], r['psf_error']['hfd_measured_over_true']))
            if not measured:
                check(key + ': proper S/N / theory', abs(r['proper_over_theory'] - 1) < 0.02, r['proper_over_theory'])
                check(key + ': mean S/N / theory', abs(r['mean_over_theory'] - 1) < 0.02, r['mean_over_theory'])
                check(key + ': measured gain / theory gain', abs(m['gain'] / t['gain'] - 1) < 0.01, m['gain'] / t['gain'])
                check(key + ': flux recovered', abs(r['flux_recovered']['median'] - 1) < 0.01, r['flux_recovered']['median'])
            else:
                check(key + ': proper S/N / theory (measured PSFs lose < 3%)', r['proper_over_theory'] > 0.97, r['proper_over_theory'])
            check(key + ': proper never worse than the mean', m['gain'] > 0.995, m['gain'])
            check(key + ': noise at the mean\'s PSF <= the mean\'s', r['noise_at_the_means_psf']['ratio'] < 1.005, r['noise_at_the_means_psf']['ratio'])
            if regime == 'variable' and not measured: keep = data
    o = outliers_and_linearity(keep); res['outliers and linearity (variable, known PSFs)'] = o
    print('outliers:', {k: (round(v, 4) if isinstance(v, float) else v) for k, v in o.items()})
    check('cosmic rays flagged', o['cosmic_rays_flagged'] >= 0.95 * o['cosmic_rays'], '%d of %d' % (o['cosmic_rays_flagged'], o['cosmic_rays']))
    check('satellite core flagged (fraction of its core pixels)', o['satellite_core_pixels_flagged_fraction'] > 0.9, o['satellite_core_pixels_flagged_fraction'])
    check('on the trail: residual after / noise', o['residual_on_trail_after_over_noise'] < 0.5, o['residual_on_trail_after_over_noise'])
    check('star cores flagged in clean frames', o['star_core_pixels_flagged_in_clean_frames'] < 0.001, o['star_core_pixels_flagged_in_clean_frames'])
    check('the mask costs little noise (fractional increase)', o['mask_cost_noise_increase'] < 0.01, o['mask_cost_noise_increase'])
    check('max residual anywhere after / noise', o['max_residual_after_over_noise'] < 6, o['max_residual_after_over_noise'])
    check('linear (error / noise)', o['linearity_max_abs_error_over_noise'] < 1e-3, o['linearity_max_abs_error_over_noise'])
    res['checks'] = checks; res['passed'] = bool(ok); res['tool'] = coadd.VERSION
    if '--json' in sys.argv: json.dump(res, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)
    print('ALL PASSED' if ok else 'SOME CHECKS FAILED')
    sys.exit(0 if ok else 1)
