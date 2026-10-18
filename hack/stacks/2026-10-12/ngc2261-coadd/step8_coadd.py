"""(NGC 2261: as hack/stacks/2026-10-12/ngc891-coadd/step8_coadd.py, with this run's object mask and its air-dispersion
step, both from its own step8_stack.py.)

Step 8 (the trial's one change): combine by PROPER COADDITION (Zackay & Ofek 2017, ApJ 836, 188) instead of the
sigma-clipped weighted mean, with .claude/skills/stack-pictures/tools/coadd.py. The control is made on the same cube
in the same pass.

Per colour plane, exactly as the delivered step 8 (step8_stack.py, imported, so the arithmetic is the same code): every
used frame read from its RAW, hot pixels repaired, / flat, x 1 / transparency, resampled onto the reference cell grid
(Lanczos-4), minus ONE sky constant (3-sigma clipped mean over the sky region). Then:

  control   the delivered combine (step8_stack.combine: 3-sigma clips about the median and the weighted mean, weights
            (transparency / zero-level noise)^2). Saved as control_*.npy; it must reproduce ngc2261/ngc2261-stack.tif.
  noise     s_j: each resampled frame's own 3-sigma clipped standard deviation over the sky region. F_j = 1 for every
            frame: the transparency was already divided out when the frame was read (x 1/T, step 5), so a frame's
            weight F_j^2 / s_j^2 is (T_j / its noise)^2, the same quantity the delivered weights estimate.
  stars     for the PSFs: the reference frame's stars (step 2) with flux >= PSF_FLUX_MIN, unsaturated (and below
            PSF_PEAK_MAX raw DN in every frame), no neighbour within PSF_ISOLATION sensor px, compact (half-flux radius
            <= 1.25 x the median of the bright ones), outside the object mask, inside the common area; their
            positions refined on the control stack of this plane (Gaussian-windowed centroids).
  PSFs      one per frame and plane: coadd.measure_psf on the frame itself (stamps of radius PSF_RADIUS = 2.5 x the run's
            median HFD, Fourier-shifted onto the refined positions, annulus median off, each / its flux, 5-MAD clip
            across stars, flux^2 weights, cos^2 taper over the outer 4 px, sum 1). Field variation is measured
            (coadd.field_variation on the control, 3 x 3 zones) and the frame-to-frame part of it tested: if every
            frame's PSF changes across the field only by the same optics (the frames' HFD ratio to the run in the
            middle third and the outer thirds agree), one PSF per frame gives the proper weights everywhere (the optics
            cancel in the ratio of each frame's |P_hat|^2 to the sum), and that is what is done.
  outliers  coadd.outlier_mask (5 sigma per pixel or 4 sigma on a 3 x 3 box against the per-pixel median of all frames,
            beta from the PSFs' peak spread, grown 1 px; the noise scaled across the field by 1 / flat, as the flat
            raised it). Linear given the mask.
  coadd     coadd.proper_coadd: S = R / F_R in the units of a frame (a star's total is its flux in one 15 s frame at
            the sensor centre, as the control's), PSF P_R. Also C: S convolved to the weighted mean's PSF (modulus),
            for the comparison at matched PSF. And, to tell what the outlier mask alone does, the plain inverse-variance
            mean of the frames with the same mask (masked_mean.npy; no PSFs). The odd and even frames alone: each coadded and convolved to one common
            PSF, the frequency-by-frequency minimum of the full set's and both halves' P_R_hat (so neither needs a
            gain) with the full set's phase, so the halves share one PSF, a little softer than the full coadd's.
            The coadd keeps the phase of the frames' weighted mean PSF (coadd.proper_coadd keep_phase='mean'): only
            the frame-to-frame differences of phase are taken out, so stars keep the optics' own shape across the field.

DELIVER (N2261_COADD_DELIVER): which result steps 9 to 12 finish as stack_mean.npy: 'proper' (S; default), 'mean-psf'
(C) or 'control' (the delivered mean). stack_odd/even are the halves of the same kind. Writes step8_stack.json (the
keys step 12 reads, as before) and step8_coadd.json (every number that shaped the coadd, per plane)."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import solvelib
import step8_stack as S8
sys.path.insert(0, os.path.join(SCR, '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
import coadd

coadd.WORKERS = WORKERS
DELIVER = os.environ.get('N2261_COADD_DELIVER', 'proper')
PSF_FLUX_MIN = float(os.environ.get('N2261_PSF_FLUX_MIN', '5000'))
PSF_ISOLATION = 42.0                                       # sensor px to the nearest detected source (or 2 x (PSF radius + 4) if more)
PSF_PEAK_MAX = 12000.0                                     # raw DN above black, in every frame (the ceiling is ~15,500)
N = S8.N; stamps = S8.stamps; iref = S8.iref; FLAT = S8.FLAT


def psf_stars():
    d = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}[REF_STAMP]['stars']
    hm = np.median([s['hfr'] for s in d if s['flux'] > 20000 and not s['saturated']])
    ell = solvelib.object_mask(jload('step6_solve_ref.json'), (h2, w2))
    iso = max(PSF_ISOLATION, 2 * (np.ceil(2.5 * 2 * hm / 2) + 4))                # sensor px: at least the PSF stamp's radius + 4 plane px
    xy = [(s['x'], s['y']) for s in d if s['flux'] >= PSF_FLUX_MIN and not s['saturated'] and s['nearest'] > iso and s['hfr'] and s['hfr'] <= 1.25 * hm]
    return np.array([v for v in xy if not ell[int(round(v[1])), int(round(v[0]))]]), float(4 * hm)


def peak_ok(cube, xy, consts, p):
    """Stars below PSF_PEAK_MAX raw DN in every frame (undoing / flat and x 1/T approximately: the flat at the grid place)."""
    ok = []
    for x, y in xy:
        xi, yi = int(round(x)), int(round(y))
        if xi < 30 or yi < 30 or xi > w2 - 31 or yi > h2 - 31: ok.append(False); continue
        pk = np.nanmax(cube[:, yi - 3:yi + 4, xi - 3:xi + 4], axis=(1, 2))
        raw = (pk + consts) * FLAT[p][yi, xi] / np.array([S8.scale[s] for s in stamps])
        ok.append(bool(np.all(raw < PSF_PEAK_MAX)))
    return np.array(ok)


def separable_check(cube, xy, radius, sel_frames):
    """Does each frame's PSF differ from the run's by the same amount in the middle third of the field and the outer
    thirds? HFD of each frame's PSF in each band over the run's median in that band."""
    bands = dict(middle=(xy[:, 0] >= w2 / 3) & (xy[:, 0] < 2 * w2 / 3), outer=(xy[:, 0] < w2 / 3) | (xy[:, 0] >= 2 * w2 / 3))
    hf = {b: np.array([coadd.measure_psf(np.nan_to_num(cube[j]), xy[m], radius)[1]['hfd_px'] for j in sel_frames]) for b, m in bands.items()}
    rel = {b: v / np.median(v) for b, v in hf.items()}
    r = float(np.corrcoef(rel['middle'], rel['outer'])[0, 1]); d = rel['middle'] - rel['outer']
    return dict(stars=dict(middle=int(bands['middle'].sum()), outer=int(bands['outer'].sum())), hfd_px_middle=hf['middle'].tolist(), hfd_px_outer=hf['outer'].tolist(),
                frame_to_frame_spread=dict(middle=float(np.std(rel['middle'])), outer=float(np.std(rel['outer']))), correlation=r, rms_difference=float(np.std(d)),
                verdict=('separable: the frames\' PSFs change together across the field (correlation %.2f; the bands differ by %.1f%% rms against a frame-to-frame spread of %.1f%%); one PSF per frame' % (r, 100 * np.std(d), 100 * np.std(rel['middle']))))


if __name__ == '__main__':
    t00 = time.time()
    # ---- air dispersion, from the frames: as step8_stack.py, same code
    with ThreadPoolExecutor(WORKERS) as ex:
        rows = sum(ex.map(S8.offsets_in_frame, stamps[::S8.DISP_EVERY]), [])
    disp_before = S8.offsets_summary(rows); disp_before['frames'] = stamps[::S8.DISP_EVERY]
    if os.environ.get('N2261_DISPERSION', '1') == '1':
        S8.DISP[0] = tuple(disp_before['red_minus_green_sensor_px']); S8.DISP[3] = tuple(disp_before['blue_minus_green_sensor_px'])
    print('colour offsets in the frames (sensor px): red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f)' % (*disp_before['red_minus_green_sensor_px'], *disp_before['blue_minus_green_sensor_px']), flush=True)
    # ---- the common area and the sky region: as step8_stack.py, same code
    common = np.ones((h2, w2), bool)
    for s in stamps:
        mx, my = S8.maps(s, 0)
        common &= (mx >= S8.INSET) & (mx <= w2 - 1 - S8.INSET) & (my >= S8.INSET) & (my <= h2 - 1 - S8.INSET)
    G = (S8.prep(REF_STAMP, 1) + S8.prep(REF_STAMP, 2)) / 2
    Gs = smooth_level(G, 16, 5); Gs = cv2.GaussianBlur(Gs, (0, 0), 32)
    ell = solvelib.object_mask(jload('step6_solve_ref.json'), (h2, w2))
    thr = np.percentile(Gs[common & ~ell], S8.FAINT_PCT)
    faint = common & ~ell & (Gs <= thr); del G
    np.save(W('faint_region.npy'), faint)
    ys, xs = np.nonzero(faint)
    print('common area %.1f%% of the grid; sky region %d px' % (100 * common.mean(), faint.sum()), flush=True)
    order = np.arange(N); SUB = dict(odd=order[1::2], even=order[0::2])
    xy0, hfd_run = psf_stars(); RADIUS = int(np.ceil(2.5 * hfd_run / 2))   # hfd_run: sensor px -> plane px is / 2
    print('PSF stars (reference frame list): %d; run median HFD %.2f plane px -> PSF radius %d px' % (len(xy0), hfd_run / 2, RADIUS), flush=True)
    ctl = {k: np.zeros((4, h2, w2), np.uint8 if k == 'used' else np.float32) for k in ('mean', 'used', 'odd', 'even')}
    res = {k: np.zeros((4, h2, w2), np.float32) for k in ('proper', 'mean-psf', 'proper_odd', 'proper_even', 'meanpsf_odd', 'meanpsf_even', 'masked-mean')}
    usedc = np.zeros((4, h2, w2), np.uint8)
    single = np.zeros((4, h2, w2), np.float32); cover = np.zeros((h2, w2), np.uint8)
    CONST = np.zeros((N, 4)); CONST_ERR = np.zeros((N, 4)); info = []; rec = {}; psf_store = {}
    for p in range(4):
        t0 = time.time(); P = PLANE_NAMES[p]
        with ThreadPoolExecutor(WORKERS) as ex:
            cube = np.stack(list(ex.map(lambda s: S8.warp(s, p), stamps)))
        for i in range(N):
            m, sd, _ = clipped_stats(cube[i][faint])
            CONST[i, p] = m; CONST_ERR[i, p] = sd / np.sqrt(faint.sum())
            cube[i] -= np.float32(m)
        geo = np.isfinite(cube)
        if p == 1: cover[:] = geo.sum(0)
        single[p] = cube[iref]
        # ---- the control: the delivered combine, the same code on the same cube
        fs7 = np.array([clipped_stats(cube[i][faint][::7])[1] for i in range(N)])
        floor = np.float32(0.4 * np.median(fs7))
        rows = [(a, min(a + 64, h2)) for a in range(0, h2, 64)]
        def work(ab):
            a, b = ab
            return ab, S8.combine(cube[:, a:b], geo[:, a:b], floor, SUB)
        with ThreadPoolExecutor(WORKERS) as ex:
            for (a, b), o in ex.map(work, rows):
                for k, v in o.items(): ctl[k][p, a:b] = v
        seen = int(geo.sum()); usedn = int(ctl['used'][p].sum())
        info.append(dict(plane=P, frame_noise_in_faint_region=fs7.tolist(), sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=float((seen - usedn) / seen)))
        t1 = time.time()
        # ---- noise and flux of each frame for the coadd
        sig = np.array([clipped_stats(cube[i][faint])[1] for i in range(N)]); F = np.ones(N)
        # ---- PSF stars, positions refined on this plane's control stack
        xy = coadd.refine_positions(np.nan_to_num(ctl['mean'][p]), xy0)
        ok = np.isfinite(xy[:, 0]) & peak_ok(cube, np.nan_to_num(xy), CONST[:, p], p)
        ok &= np.array([common[int(round(y)), int(round(x))] if np.isfinite(x) else False for x, y in xy])
        xy = xy[ok]
        fv = coadd.field_variation(np.nan_to_num(ctl['mean'][p]), xy, RADIUS, shape=(3, 3), min_stars=8)
        sep = separable_check(cube, xy, RADIUS, range(N)) if p == 1 else None
        psfs, pinf = [], []
        for j in range(N):
            ps, inf = coadd.measure_psf(np.nan_to_num(cube[j]), xy, RADIUS); psfs.append(ps); pinf.append(inf)
        psfs = np.array(psfs)
        th = coadd.theory(psfs, F, sig)
        th_ctl = coadd.theory(psfs, F, sig, weights=S8.wts)           # the control's own weights
        # ---- outliers, then the coadd
        nmap = np.float32(np.median(FLAT[p][faint])) / FLAT[p]          # the noise after the flat, relative to the sky region's
        mask, minfo = coadd.outlier_mask(cube, F, sig, psfs=psfs, noise_map=nmap)
        minfo['flagged_fraction_in_sky_region'] = float(mask[:, faint].mean())
        usedc[p] = (geo & ~mask).sum(0)
        # the plain inverse-variance mean with the same outlier mask (no PSFs): to tell what the mask alone does
        for a0, b0 in rows:
            k_ = geo[:, a0:b0] & ~mask[:, a0:b0]; w_ = (1 / sig ** 2).astype(np.float32)[:, None, None] * k_
            res['masked-mean'][p, a0:b0] = np.where(w_.sum(0) > 0, (w_ * np.where(k_, cube[:, a0:b0], 0)).sum(0) / np.maximum(w_.sum(0), 1e-12), np.nan)
        out = coadd.proper_coadd(cube, psfs, F, sig, mask=mask, target='mean-psf', keep_hat=True)
        res['proper'][p] = out['S']; res['mean-psf'][p] = out['C']
        hv = {name: coadd.proper_coadd(cube[idx], psfs[idx], F[idx], sig[idx], mask=mask[idx], keep_hat=True) for name, idx in SUB.items()}
        Pcom = np.minimum(out['P_R_hat'], np.minimum(hv['odd']['P_R_hat'], hv['even']['P_R_hat']))      # one PSF both halves can reach without a gain
        Pcom_m = np.minimum(out['P_C_hat'], np.minimum(hv['odd']['P_R_hat'], hv['even']['P_R_hat']))
        halves = {}
        for name, o in hv.items():
            a_ = coadd.convolve_to(o, Pcom, phase=out['phase_hat'], name='the minimum of the full set\'s and both halves\' P_R_hat, with the full set\'s phase')
            b_ = coadd.convolve_to(o, Pcom_m, phase=out['phase_hat'], name='the minimum of the full set\'s mean-psf target and both halves\' P_R_hat, with the full set\'s phase')
            res['proper_' + name][p] = a_['C']; res['meanpsf_' + name][p] = b_['C']
            halves[name] = dict(F_R=o['F_R'], psf_R=coadd.psf_stats(o['psf_R']), common_psf=coadd.psf_stats(a_['psf_C']), to_common=a_['target_info'])
        g_full = coadd.convolve_to(out, Pcom, phase=out['phase_hat'], name='common'); halves['full_at_the_common_psf'] = dict(psf=coadd.psf_stats(g_full['psf_C']), noise_white=g_full['noise_C_white'], noise_S=out['noise_S'])
        del hv, g_full
        psf_store[P] = dict(frames=psfs.astype(np.float32), psf_R=out['psf_R'].astype(np.float32), psf_C=out['psf_C'].astype(np.float32), xy=xy)
        rec[P] = coadd.recipe(F, sig, pinf, minfo, out, th=th, stamps_of=stamps,
                              extra=dict(psf_stars=int(len(xy)), psf_radius_px=RADIUS, field_variation=fv, separable=sep, halves=halves,
                                         theory_with_the_control_weights=dict(snr_weighted_mean=th_ctl['snr_weighted_mean'], gain_of_proper=th['snr_proper'] / th_ctl['snr_weighted_mean']),
                                         sky_noise_per_frame_dn=sig.tolist()))
        for pi in rec[P]['frames']: pi['psf'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pi['psf'].items()}
        print('%s: constants %.2f..%.2f; control dropped %.3f%% (%.0fs) | coadd: %d PSF stars r=%d, PSF HFD %.2f..%.2f px (P_R %.2f), field HFD spread %.0f%% (varies: %s), flagged %.3f%% (sky region %.3f%%, beta %.2f), theory gain %.4f (vs the control\'s weights %.4f); %.0fs' % (
            P, CONST[:, p].min(), CONST[:, p].max(), 100 * info[-1]['dropped_fraction'], t1 - t0, len(xy), RADIUS, min(i['hfd_px'] for i in pinf), max(i['hfd_px'] for i in pinf), coadd.psf_stats(out['psf_R'])['hfd_px'],
            100 * fv['hfd_spread'], fv['varies'], 100 * minfo['flagged_fraction'], 100 * minfo['flagged_fraction_in_sky_region'], minfo['beta'], th['gain'], th['snr_proper'] / th_ctl['snr_weighted_mean'], time.time() - t1), flush=True)
        if sep: print('   ', sep['verdict'], flush=True)
        del cube, geo, mask
    # ---- save: the control, the coadds, and what steps 9-12 read
    for k, v in ctl.items(): np.save(W('control_%s.npy' % k), v)
    np.save(W('coadd_proper.npy'), res['proper']); np.save(W('coadd_meanpsf.npy'), res['mean-psf']); np.save(W('masked_mean.npy'), res['masked-mean'])
    for k in ('proper_odd', 'proper_even', 'meanpsf_odd', 'meanpsf_even'): np.save(W('coadd_%s.npy' % k), res[k])
    np.savez_compressed(W('coadd_psfs.npz'), **{'%s_%s' % (P, k): v for P, d in psf_store.items() for k, v in d.items()})
    pick = dict(proper=('proper', 'proper_odd', 'proper_even'), **{'mean-psf': ('mean-psf', 'meanpsf_odd', 'meanpsf_even')})
    if DELIVER == 'control':
        deliver = dict(mean=ctl['mean'], odd=ctl['odd'], even=ctl['even'], used=ctl['used'])
    else:
        a, b, c = pick[DELIVER]; deliver = dict(mean=res[a], odd=res[b], even=res[c], used=usedc)
    for k, v in deliver.items(): np.save(W('stack_%s.npy' % k), v)
    disp_after = S8.offsets_summary(S8.offsets_in_stack(deliver['mean'])); disp_after_ctl = S8.offsets_summary(S8.offsets_in_stack(ctl['mean']))
    print('colour offsets left (sensor px): delivered red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f); control (%+.3f, %+.3f), (%+.3f, %+.3f)' % (*disp_after['red_minus_green_sensor_px'], *disp_after['blue_minus_green_sensor_px'], *disp_after_ctl['red_minus_green_sensor_px'], *disp_after_ctl['blue_minus_green_sensor_px']), flush=True)
    np.save(W('stack_single.npy'), single); np.save(W('stack_cover.npy'), cover); np.save(W('common_area.npy'), common)
    jdump(dict(frames=stamps, reference=REF_STAMP, kappa=S8.KAPPA, combine='proper coadd (coadd.py), delivered: %s' % DELIVER,
               faint_region=dict(what='the sky region', percentile=S8.FAINT_PCT, pixels=int(faint.sum()), smoothed_green_max_dn=float(thr), centroid_xy=[float(xs.mean()), float(ys.mean())], box=[int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())]),
               constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, constants_statistical_error={s: CONST_ERR[i].tolist() for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info, control_planes=info,
               air_dispersion=dict(measured_in_the_frames=disp_before, taken_out_sensor_px={PLANE_NAMES[k]: list(v) for k, v in S8.DISP.items()}, left_in_the_stack=disp_after, left_in_the_control=disp_after_ctl,
                                   picture_px='1 picture px = 2 sensor px', how='red and blue sampled at green\'s place plus their offset, in the one Lanczos-4 resampling')), 'step8_stack.json')
    jdump(dict(deliver=DELIVER, what='proper coaddition per colour plane; the control (the delivered sigma-clipped weighted mean) made from the same cube', planes=rec), 'step8_coadd.json')
    print('delivered as stack_mean.npy: %s; %.0f s in all' % (DELIVER, time.time() - t00))
