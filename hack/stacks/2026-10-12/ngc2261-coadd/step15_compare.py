"""Step 15 (the trial; as hack/stacks/2026-10-12/ngc891-coadd/step14_compare.py, with the nebula's own measures of step 11
in place of the galaxy's): the proper coadd against the delivered stack, with numbers. Writes work/step15_compare.json and
work/v_compare_*.png (the finished pictures side by side at full size, for looking).

  control   the delivered combine made in step 8 from the same cube (control_*.npy); first checked against the
            published ngc2261/ngc2261-stack.tif: it must give the same 16-bit file.
  proper    S, the proper coadd (coadd_proper.npy), PSF P_R
  mean-psf  C, S convolved to the weighted mean's PSF (coadd_meanpsf.npy)
  masked-mean  the plain inverse-variance mean with the coadd's outlier mask, no PSFs (masked_mean.npy): what the mask
            alone does against the delivered clip

Measured on the green (mean of G1 and G2) of the well-covered rectangle of step 9:
  noise              3-sigma clipped standard deviation over the sky region, per pixel; and (odd - even) / 2
  point-source S/N   for the same stars (isolated, unsaturated, compact, outside the nebula, flux >= SNR_FLUX_MIN in a
                     frame): (a) the matched filter: each image filtered with its own PSF (measured on it with
                     coadd.measure_psf from the same PSF stars as step 8), the value at the star over the filtered
                     sky's clipped std (stars masked); (b) aperture photometry, radius = the control's HFD: the plain
                     sum, the noise the robust spread of the same sum over the masked sky. Per star ratio, median and
                     its bootstrap error (the error of the noise estimate itself, about 1%, is not in it).
  star HFD           step 10's measure (14 px, annulus 20-28 px) on the same compact stars; and at matched noise: the
                     less noisy image Gaussian-blurred until its sky noise equals the other's, then measured again
  nebula             step 10's numbers (disc followed along the major axis above 3 x the noise; the dust lane's depth
                     below the lower ridge, in DN and over the profile noise) from this run and from the published run
  anything new?      D = C - control, for the odd and the even frames apart; band-passed (difference of Gaussians,
                     sigma 1.5 and 6 px), stars masked; the correlation of D_odd with D_even over the nebula against
                     the same over blank-sky boxes. A structure that one method makes and the other does not would
                     repeat in both halves. Also the plain half test for each method: band-passed odd against even
                     over the nebula (how strongly the real structure repeats)."""
import json, os, sys
import numpy as np, cv2, tifffile
from scipy.signal import fftconvolve
from common import *
import solvelib
sys.path.insert(0, os.path.join(SCR, '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
import coadd

PUB = os.environ.get('N2261_PUBLISHED', os.path.join(NIGHT, 'ngc2261'))
PUB_NAME = 'ngc2261'
SNR_FLUX_MIN = 2000.0
s9 = jload('step9_solve.json'); c = s9['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
cut = lambda a: a[..., y0:y1, x0:x1]
faint = cut(np.load(W('faint_region.npy')))
s8c = jload('step8_coadd.json')


def green(a): return 0.5 * (a[1] + a[2])


def load(name): return cut(np.load(W(name)))


def cstd(img, m): return clipped_stats(img[m])[1]


def value_at(img, x, y, r=12):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float64)
    return float(coadd._fshift(t, -(x - xi), -(y - yi))[r, r])


def hfd(img, x, y, rmax=14):
    xi, yi = int(round(x)), int(round(y))
    t = img[yi - 30:yi + 31, xi - 30:xi + 31]; yy, xx = np.mgrid[-30:31, -30:31]; r = np.hypot(xx - (x - xi), yy - (y - yi))
    bg = np.median(t[(r > 20) & (r < 28)]); a = r <= rmax; o = np.argsort(r[a]); cum = np.cumsum((t - bg)[a][o])
    return float(2 * r[a][o][np.searchsorted(cum, cum[-1] / 2)]) if cum[-1] > 0 else np.nan


def bandpass(img, a=1.5, b=6.0): return cv2.GaussianBlur(img, (0, 0), a) - cv2.GaussianBlur(img, (0, 0), b)


if __name__ == '__main__':
    out = {}
    # ---- 1. the control reproduces the published file
    s1 = jload('step1.json'); ref = [f for f in s1['frames'] if f['stamp'] == REF_STAMP][0]
    wbd = np.array(ref['wb_daylight'][:3]); wb = wbd / wbd[1]
    ctl = load('control_mean.npy')
    t16 = np.clip(np.round(np.dstack([ctl[0] * wb[0], 0.5 * (ctl[1] + ctl[2]), ctl[3] * wb[2]]) + 1000.0), 0, 65535).astype(np.uint16)
    pub = tifffile.imread(os.path.join(PUB, PUB_NAME + '-stack.tif'))
    same = pub.shape == t16.shape and bool((pub == t16).all())
    out['control_reproduces_published_tif'] = dict(identical=same, max_abs_difference=int(np.abs(pub.astype(int) - t16.astype(int)).max()) if pub.shape == t16.shape else None, file=os.path.join(PUB, PUB_NAME + '-stack.tif'))
    print('control vs published %s: %s' % (PUB_NAME + '-stack.tif', 'IDENTICAL' if same else 'differs by up to %s' % out['control_reproduces_published_tif']['max_abs_difference']), flush=True)
    imgs = dict(control=ctl, proper=load('coadd_proper.npy'), **{'mean-psf': load('coadd_meanpsf.npy'), 'masked-mean': load('masked_mean.npy')})
    halves = dict(control=(load('control_odd.npy'), load('control_even.npy')), proper=(load('coadd_proper_odd.npy'), load('coadd_proper_even.npy')), **{'mean-psf': (load('coadd_meanpsf_odd.npy'), load('coadd_meanpsf_even.npy'))})
    Gimg = {k: green(v).astype(np.float32) for k, v in imgs.items()}
    # ---- 2. noise
    noise = {k: dict(planes=dict(zip(PLANE_NAMES, [cstd(v[p], faint) for p in range(4)])), green=cstd(Gimg[k], faint), green_half_difference=cstd(green((halves[k][0] - halves[k][1]) / 2), faint) if k in halves else None) for k, v in imgs.items()}
    out['noise_per_pixel_dn'] = noise
    for k in noise: print('noise %-11s planes %s green %.3f half-diff %s' % (k, [round(v, 3) for v in noise[k]['planes'].values()], noise[k]['green'], noise[k]['green_half_difference']))
    # ---- 3. stars
    d = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}[REF_STAMP]['stars']
    hm = np.median([s['hfr'] for s in d if s['flux'] > 20000 and not s['saturated']])
    ell = cut(solvelib.object_mask(jload('step6_solve_ref.json'), (h2, w2)))
    hh, ww = faint.shape
    allxy = np.array([(s['x'] - x0, s['y'] - y0) for s in d])
    starmask = np.zeros((hh, ww), np.uint8)
    for (x, y), s in zip(allxy, d):
        if 0 <= x < ww and 0 <= y < hh: cv2.circle(starmask, (int(round(x)), int(round(y))), int(10 + 6 * np.log10(max(s['flux'], 1e3) / 1e3)), 1, -1)
    sky = faint & (starmask == 0)
    cand = [s for s in d if s['flux'] >= SNR_FLUX_MIN and not s['saturated'] and s['nearest'] > 42 and s['hfr'] and s['hfr'] <= 1.25 * hm]
    xy = np.array([(s['x'] - x0, s['y'] - y0) for s in cand]); fl = np.array([s['flux'] for s in cand])
    inside = (xy[:, 0] > 40) & (xy[:, 0] < ww - 40) & (xy[:, 1] > 40) & (xy[:, 1] < hh - 40)
    inside &= np.array([not ell[int(round(y)), int(round(x))] if 0 <= x < ww and 0 <= y < hh else False for x, y in xy])
    xy, fl = xy[inside], fl[inside]
    xy = coadd.refine_positions(Gimg['control'], xy); ok = np.isfinite(xy[:, 0]); xy, fl = xy[ok], fl[ok]
    psfxy = xy[fl >= 5000]; RAD = s8c['planes']['G1']['psf_radius_px']
    psf = {k: coadd.measure_psf(np.nan_to_num(Gimg[k]), psfxy, RAD) for k in Gimg}
    snr = {}
    for k, img in Gimg.items():
        p_ = psf[k][0]; f = fftconvolve(np.nan_to_num(img), p_[::-1, ::-1], mode='same')
        ns = cstd(f, sky); snr[k] = np.array([value_at(f, x, y) for x, y in xy]) / ns
    hf_ctl = float(np.nanmedian([hfd(Gimg['control'], x, y) for x, y in xy[fl >= 5000]])); rap = max(2, int(round(hf_ctl)))
    # aperture photometry: the plain sum inside r = the control's HFD (the sky is zero by construction: one constant per
    # frame and colour was subtracted), the noise the robust spread (1.4826 MAD) of the same sum over the masked sky
    rng = np.random.default_rng(1)
    kap = np.zeros((2 * rap + 1, 2 * rap + 1), np.float32); yy, xx = np.mgrid[-rap:rap + 1, -rap:rap + 1]; kap[np.hypot(xx, yy) <= rap] = 1
    apsnr = {}
    for k, img in Gimg.items():
        a_ = cv2.filter2D(np.nan_to_num(img).astype(np.float32), -1, kap, borderType=cv2.BORDER_CONSTANT)
        v = a_[sky][::37]; nb = float(1.4826 * np.median(np.abs(v - np.median(v))))
        apsnr[k] = np.array([value_at(a_, x, y) for x, y in xy]) / nb
    def ratio(a, b):
        r = a / b; g = np.isfinite(r) & (b > 5)
        bs = [np.median(rng.choice(r[g], g.sum())) for _ in range(500)]
        return dict(median=float(np.median(r[g])), error=float(np.std(bs)), stars=int(g.sum()))
    # flux: the same stars in a small (r = HFD) and a big (r = 14 px) aperture, proper and mean-psf over control, by brightness
    def apf(img, x, y, r, r1, r2):
        xi, yi = int(round(x)), int(round(y)); R_ = r2 + 1; t = img[yi - R_:yi + R_ + 1, xi - R_:xi + R_ + 1]; yy_, xx_ = np.mgrid[-R_:R_ + 1, -R_:R_ + 1]; q = np.hypot(xx_ - (x - xi), yy_ - (y - yi))
        return float(t[q <= r].sum() - (q <= r).sum() * np.median(t[(q > r1) & (q <= r2)]))
    fluxcmp = {}
    for nm, (r, r1, r2) in dict(small=(rap, rap + 3, rap + 8), big=(14, 20, 28)).items():
        F_ = {k: np.array([apf(Gimg[k], x, y, r, r1, r2) for x, y in xy]) for k in Gimg}
        bins = [(SNR_FLUX_MIN, 5000), (5000, 20000), (20000, 1e9)]
        fluxcmp[nm] = dict(radius_px=r, **{k: [dict(one_frame_flux=[lo, hi], stars=int(((fl >= lo) & (fl < hi)).sum()), median_ratio_to_control=float(np.median((F_[k] / F_['control'])[(fl >= lo) & (fl < hi)]))) for lo, hi in bins] for k in ('proper', 'mean-psf')})
    print('star flux over the control (small r=%d / big r=14 aperture), by one-frame flux 2k-5k, 5k-20k, >20k: proper %s / %s' % (rap, [round(b['median_ratio_to_control'], 4) for b in fluxcmp['small']['proper']], [round(b['median_ratio_to_control'], 4) for b in fluxcmp['big']['proper']]), flush=True)
    out['point_source_snr'] = dict(flux_over_control=fluxcmp, stars=int(len(xy)), flux_range_one_frame=[float(fl.min()), float(fl.max())], aperture_radius_px=rap,
                                   matched_filter=dict(median_snr={k: float(np.median(v)) for k, v in snr.items()}, proper_over_control=ratio(snr['proper'], snr['control']), meanpsf_over_control=ratio(snr['mean-psf'], snr['control']), masked_mean_over_control=ratio(snr['masked-mean'], snr['control'])),
                                   aperture=dict(median_snr={k: float(np.median(v)) for k, v in apsnr.items()}, proper_over_control=ratio(apsnr['proper'], apsnr['control']), meanpsf_over_control=ratio(apsnr['mean-psf'], apsnr['control']), masked_mean_over_control=ratio(apsnr['masked-mean'], apsnr['control'])),
                                   theory_gain=dict((P, s8c['planes'][P]['theory_with_the_control_weights']['gain_of_proper']) for P in PLANE_NAMES),
                                   psf_measured_on_each={k: {q: v[1][q] for q in ('hfd_px', 'fwhm_px', 'ellipticity', 'stars')} for k, v in psf.items()})
    ps = out['point_source_snr']
    print('point-source S/N, %d stars: matched filter proper/control %.4f +- %.4f, mean-psf/control %.4f, masked mean/control %.4f | aperture (r %d px) proper/control %.4f +- %.4f | theory %.4f' % (
        len(xy), ps['matched_filter']['proper_over_control']['median'], ps['matched_filter']['proper_over_control']['error'], ps['matched_filter']['meanpsf_over_control']['median'], ps['matched_filter']['masked_mean_over_control']['median'], rap,
        ps['aperture']['proper_over_control']['median'], ps['aperture']['proper_over_control']['error'], ps['theory_gain']['G1']), flush=True)
    # ---- 4. star size, and at matched noise
    bright = xy[fl >= 5000]
    hfdv = {k: float(np.nanmedian([hfd(Gimg[k], x, y) for x, y in bright])) for k in Gimg}
    def blur_to(img, target):
        lo, hi = 0.0, 3.0
        for _ in range(30):
            m = (lo + hi) / 2; n = cstd(cv2.GaussianBlur(img, (0, 0), m) if m > 0.05 else img, faint)
            lo, hi = (m, hi) if n > target else (lo, m)
        return (lo + hi) / 2
    matched = {}
    for k in ('proper', 'mean-psf'):                       # the noisier of the two is blurred down to the other's noise
        a, b = noise[k]['green'], noise['control']['green']
        noisier, other = ('control', k) if b > a else (k, 'control')
        sgm = blur_to(Gimg[noisier], min(a, b)); im = cv2.GaussianBlur(Gimg[noisier], (0, 0), sgm)
        h_ = float(np.nanmedian([hfd(im, x, y) for x, y in bright]))
        matched[k] = dict(blurred=noisier, gaussian_sigma_px=sgm, noise_after=cstd(im, faint), hfd_px_of_the_blurred=h_, hfd_px_of_the_other=hfdv[other], other=other,
                          verdict='%s at %.3f DN noise: HFD %.3f px; %s blurred to the same noise: %.3f px' % (other, min(a, b), hfdv[other], noisier, h_))
    out['star_hfd_px'] = dict(stars=int(len(bright)), median=hfdv, arcsec={k: v * s9['pixscale_arcsec'] for k, v in hfdv.items()}, at_matched_noise=matched)
    print('star HFD (px) %s' % {k: round(v, 3) for k, v in hfdv.items()})
    for k, v in matched.items(): print('  at matched noise (%s vs control): %s' % (k, v['verdict']), flush=True)
    # ---- 5. the nebula (step 11's numbers) and step 10's noise and star size, this run against the published run
    mine = jload('step11_measure.json'); theirs = json.load(open(os.path.join(PUB, 'work', 'step11_measure.json')))
    m10 = jload('step10_deliver.json'); t10 = json.load(open(os.path.join(PUB, 'work', 'step10_deliver.json')))
    def neb(s, s10):
        f = s['fan']; st = s['structure']
        return dict(fan_area_sq_arcmin={k: f[k]['area_sq_arcmin'] for k in ('stack', 'odd', 'even')}, fan_length_arcsec={k: f[k]['length_along_the_axis_arcsec'] for k in ('stack', 'odd', 'even')},
                    fan_widest_arcsec=f['stack']['widest_arcsec'], fan_reach_north_arcsec=f['stack']['reach_from_the_star_arcsec']['north'], fan_threshold_dn=f['stack']['threshold_dn'],
                    fan_mean_over_blank_sky_scatter=f['over_blank_sky_scatter'], blank_box_scatter_dn=s['sky']['stack']['scatter_of_box_means_dn'],
                    structure_band_noise_stack_dn=st['noise_of_the_stack_in_this_band_dn'], structure_odd_even_correlation_inside=st['odd_even_correlation']['inside_the_fan'],
                    structure_features_in_both_halves=st['features_in_both_halves'], structure_features=len(st['features']),
                    r_mon_hfd_arcsec=s['r_mon']['half_flux_diameter_arcsec'], field_star_hfd_arcsec=s['r_mon']['field_stars_half_flux_diameter_arcsec'],
                    noise_planes=s10['noise_faint_region']['planes_stack'], noise_improvement=s10['noise_faint_region']['improvement'], ideal=s10['noise_faint_region']['ideal'], star_hfd_arcsec=s10['star_size']['hfd_stack_arcsec'])
    out['nebula_and_noise_from_steps_10_11'] = dict(trial=neb(mine, m10), published=neb(theirs, t10))
    for k in ('trial', 'published'): print('nebula %-9s' % k, out['nebula_and_noise_from_steps_10_11'][k], flush=True)
    # ---- 6. anything new? D = C - control in each half; and each method's own half test
    smask = cv2.dilate(starmask, np.ones((5, 5), np.uint8)) > 0
    gal_in = ell & ~smask & np.isfinite(Gimg['control'])
    def corr(a, b, m): a_, b_ = a[m] - a[m].mean(), b[m] - b[m].mean(); return float((a_ * b_).sum() / np.sqrt((a_ ** 2).sum() * (b_ ** 2).sum()))
    ys_, xs_ = np.nonzero(gal_in); bh, bw = ys_.max() - ys_.min() + 1, xs_.max() - xs_.min() + 1
    shape_m = gal_in[ys_.min():ys_.min() + bh, xs_.min():xs_.min() + bw]
    blanks = []
    for yb in range(0, hh - bh, bh // 2 + 1):
        for xb in range(0, ww - bw, bw // 3 + 1):
            m = np.zeros_like(gal_in); m[yb:yb + bh, xb:xb + bw] = shape_m; m &= sky
            if m.sum() > 0.6 * shape_m.sum() and not (m & ell).any(): blanks.append(m)
    def ztest(a, b):
        rg = corr(a, b, gal_in); rb = np.array([corr(a, b, m) for m in blanks])
        return dict(nebula=rg, blank_mean=float(rb.mean()), blank_std=float(rb.std()), blank_boxes=len(rb), z=float((rg - rb.mean()) / max(rb.std(), 1e-9)))
    BANDS = dict(fine=(1.5, 6.0), coarse=(4.0, 16.0))
    newd, own = {}, {}
    for bn, (ba, bb) in BANDS.items():
        Db = [bandpass(np.nan_to_num(green(halves['mean-psf'][i]) - green(halves['control'][i])).astype(np.float32), ba, bb) for i in (0, 1)]
        newd[bn] = ztest(Db[0], Db[1])
        own[bn] = {k: ztest(bandpass(np.nan_to_num(green(halves[k][0])).astype(np.float32), ba, bb), bandpass(np.nan_to_num(green(halves[k][1])).astype(np.float32), ba, bb)) for k in halves}
    out['anything_new'] = dict(difference_mean_psf_minus_control_odd_vs_even=newd, each_method_odd_vs_even=own, bands_sigma_px=BANDS, rule='band-pass (difference of Gaussians), stars masked; correlation over the nebula ellipse against blank-sky boxes of the same shape; z = (nebula - blank mean) / blank std')
    for bn in BANDS:
        n_ = newd[bn]; print('anything new? [%s] (C - control) odd vs even over the nebula: r %.3f, blank %.3f +- %.3f (%d boxes): z %.1f | each method\'s halves: %s' % (bn, n_['nebula'], n_['blank_mean'], n_['blank_std'], n_['blank_boxes'], n_['z'], {k: (round(v['nebula'], 3), round(v['z'], 1)) for k, v in own[bn].items()}), flush=True)
    # ---- 7. pictures side by side, full size, for looking
    a = cv2.imread(os.path.join(NIGHT, 'final', PUB_NAME + '.png')); b = cv2.imread(os.path.join(FINAL, NAME + '.png'))
    if a is not None and b is not None and a.shape == b.shape:
        H_, W_ = a.shape[:2]
        for nm, (yy0, xx0) in dict(centre=(H_ // 2 - 300, W_ // 2 - 450), corner=(40, 40)).items():
            pa, pb = a[yy0:yy0 + 600, xx0:xx0 + 900], b[yy0:yy0 + 600, xx0:xx0 + 900]
            cv2.imwrite(W('v_compare_%s.png' % nm), np.vstack([pa, np.full((8, pa.shape[1], 3), 128, np.uint8), pb]))
        diff = cv2.absdiff(a, b); out['finished_pictures'] = dict(published=os.path.join(NIGHT, 'final', PUB_NAME + '.png'), trial=os.path.join(FINAL, NAME + '.png'), mean_abs_difference_8bit=float(diff.mean()), max_abs_difference_8bit=int(diff.max()))
    jdump(out, 'step15_compare.json')
    print('written', W('step15_compare.json'))
