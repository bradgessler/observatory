"""Step 8: the long frames combined by PROPER COADDITION (the default combine since 17 October 2026; Zackay & Ofek 2017,
ApJ 836, 188; .claude/skills/stack-pictures/tools/coadd.py) with the old sigma-clipped weighted mean made from the same
cube as a control; the short frames combined by that clipped weighted mean; and, per pixel, whether any frame of each kind
came within 7 percent of the sensor's ceiling (the join's rule, step 8b). As hack/stacks/2026-10-17/m27/step8_coadd.py,
on the canvas of hack/stacks/2026-10-17/m33 (the dithers widen the field).

Per frame and plane, both kinds: read from the RAW in place (black subtracted, hot pixels repaired on the fly; nothing
cached) / the flat (step 7: the 13 October hybrid flat times this run's own measured dust) x 1/transparency (step 5,
against its own kind) -> resampled onto the canvas (rotation + shift + the plane's own place in the 2 x 2 colour cell
+ the air-dispersion offset of red and blue, Lanczos-4, no demosaic, no enlargement) -> minus ONE constant: the 3-sigma
clipped mean over the FAINT REGION (the area every long frame covers, of that the darker FAINT_PCT percent of the first
green stack, 16 px block medians, 5 x 5 median, Gaussian 32 px). M42's glow fills the field: the zero is the faintest
part of the field, not the true sky. No surface is fitted.

Near the ceiling: each frame's plane pixels at or above 0.93 x (16000 - black) raw DN before any repair (a fixed hot
pixel excepted) are put on the canvas with the same geometry (bilinear, any contribution counts) and ORed over frames
and planes, per kind.

Air dispersion (30 to 47 degrees up): red and blue star images against green, measured on every DISP_EVERY-th used
long frame (windowed centroids of bright unclipped isolated stars in R, mean green and B, each plane's place in the
colour cell allowed for; median over stars and frames), taken out in the one resampling for both kinds, and measured
again on the stack.

Long, per plane (as m27/step8_coadd.py): the control (the clipped weighted mean, weights (transparency / noise)^2);
s_j each frame's clipped standard deviation over the faint region, F_j = 1 (transparency already divided out); PSF
stars from the reference frame's list (unsaturated, below PSF_PEAK_MAX raw DN in every frame, isolated, compact,
outside the Trapezium's circle, in the area every frame covers), refined on the control; one PSF per frame and plane
(coadd.measure_psf), the field variation measured and the frame-to-frame part tested (separable_check, green);
coadd.outlier_mask (noise scaled by 1 / flat); coadd.proper_coadd(keep_phase='mean', target='mean-psf'); the odd and the
even frames each coadded and taken to one common PSF (the minimum of the full set's and both halves' P_R_hat, with the
full set's phase) for the half-stack test; the plain inverse-variance mean with the same mask (what the mask alone does).

COADD AGAINST CONTROL, measured on the images (green): per-pixel noise over the faint region; star size (HFD) on the PSF
stars; and point-source S/N: each image with its smooth light taken off (smooth_level, 16 px blocks) filtered by its own
PSF (matched filter), the noise of that filtered image over the faint region (stars masked; this includes every
correlation between neighbouring pixels), the signal its value at each PSF star; the median over stars of the ratio.

Short, per plane: the clipped weighted mean (the control's code) and its odd/even halves; PSFs are not needed (its job is
the bright core, where the long frames clipped). DELIVER (M42_COADD_DELIVER): 'proper' (default) or 'control' for the
long stack that step 8b joins."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import canvas as CV, solvelib
import coadd

coadd.WORKERS = WORKERS
KAPPA = 3.0
FAINT_PCT = float(os.environ.get('M42_FAINT_PCT', '30'))
INSET = 16
DELIVER = os.environ.get('M42_COADD_DELIVER', 'proper')
PSF_FLUX_MIN = float(os.environ.get('M42_PSF_FLUX_MIN', '5000'))
PSF_ISOLATION = 42.0
PSF_PEAK_MAX = 12000.0
DISP_EVERY = 3
sel = jload('step5_select.json')
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
S2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
X0, Y0, HC, WC = CV.load()
FL = {k: np.load(W('flat_%s.npy' % k)) for k in ('long', 'short')}
ELL = jload('step6_solve_ref.json')['galaxy_ellipse']
DISP = {}
KIND = {}
for kd in ('long', 'short'):
    U = [u for u in sel['used'] if u['kind'] == kd]
    KIND[kd] = dict(stamps=[u['stamp'] for u in U], wts=np.array([u['weight'] for u in U], np.float32), nfac=np.array([u['noise_rel'] for u in U], np.float32), scale={u['stamp']: u['scale'] for u in U})
SCALE_OF = {**KIND['long']['scale'], **KIND['short']['scale']}
KIND_OF_STAMP = {u['stamp']: u['kind'] for u in sel['used']}


def RT(s): return np.array(tr[s]['R']), np.array(tr[s]['t'])


def warp(s, p, near=False):
    P, nc = load_clean_plane(path_of(s), p, near=True)
    P = P / FL[KIND_OF_STAMP[s]][p] * np.float32(SCALE_OF[s])
    R, t = RT(s)
    mx, my = CV.maps(R, t, X0, Y0, HC, WC, ox=OFFS[p][0], oy=OFFS[p][1], d=DISP.get(p, (0.0, 0.0)))
    v = (mx >= INSET / 2) & (mx <= w2 - 1 - INSET / 2) & (my >= INSET / 2) & (my <= h2 - 1 - INSET / 2)
    o = cv2.remap(P, mx, my, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    o[~v] = np.nan
    if not near: return o
    n = cv2.remap(nc.astype(np.float32), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0
    return o, n & v


def offsets_in_frame(stamp):
    """Red and blue centroids against green for the bright unclipped isolated stars of one frame, sensor px (m27 step 8)."""
    from step2_stars import measure, smooth_light
    P, _ = load_clean(path_of(stamp)); rows = []
    D = [P[0] - smooth_light(P[0]), 0.5 * (P[1] + P[2]) - smooth_light(0.5 * (P[1] + P[2])), P[3] - smooth_light(P[3])]
    for s_ in S2[stamp]['stars']:
        if s_['saturated'] or s_['flux'] < 20000 or s_['nearest'] < 40 or s_['hfr'] > 5.0: continue
        r = measure(D[0], s_['x'], s_['y']); g = measure(D[1], s_['x'], s_['y']); b = measure(D[2], s_['x'], s_['y'])
        if r and g and b:
            rows.append((2 * (r['x'] - g['x']) - 0.5, 2 * (r['y'] - g['y']) - 0.5, 2 * (b['x'] - g['x']) + 0.5, 2 * (b['y'] - g['y']) + 0.5))
    return rows


def offsets_in_stack(planes):
    from step2_stars import measure, smooth_light
    D = [np.nan_to_num(planes[0]), np.nan_to_num(0.5 * (planes[1] + planes[2])), np.nan_to_num(planes[3])]; D = [d - smooth_light(d) for d in D]; rows = []
    for s_ in S2[REF_STAMP]['stars']:
        if s_['saturated'] or s_['flux'] < 20000 or s_['nearest'] < 40 or s_['hfr'] > 5.0: continue
        x, y = s_['x'] - X0, s_['y'] - Y0
        if not (30 < x < WC - 30 and 30 < y < HC - 30): continue
        r = measure(D[0], x, y); g = measure(D[1], x, y); b = measure(D[2], x, y)
        if r and g and b: rows.append((2 * (r['x'] - g['x']), 2 * (r['y'] - g['y']), 2 * (b['x'] - g['x']), 2 * (b['y'] - g['y'])))
    return rows


def offsets_summary(rows):
    a = np.array(rows)
    return dict(measures=len(a), red_minus_green_sensor_px=np.median(a[:, :2], 0).round(4).tolist(), blue_minus_green_sensor_px=np.median(a[:, 2:], 0).round(4).tolist(),
                scatter_sensor_px=(1.4826 * np.median(np.abs(a - np.median(a, 0)), 0)).round(4).tolist(), error_of_the_median_sensor_px=(1.2533 * 1.4826 * np.median(np.abs(a - np.median(a, 0)), 0) / np.sqrt(len(a))).round(4).tolist())


def take(s, k): return np.take_along_axis(s, k[None], 0)[0]


def combine(c, valid, floor, subs, wts, nfac):
    """The template's control combine (hack/stacks/2026-10-17/m33/step8_stack.combine), the same arithmetic."""
    N = len(wts); f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        lo = np.clip((n - 1) // 2, 0, N - 1); hi = np.clip(n // 2, 0, N - 1)
        s = np.sort(cv_, axis=0); med = 0.5 * (take(s, lo) + take(s, hi)); del s
        dev = np.abs(cv_ - med); sd = np.sort(dev, axis=0); mad = 0.5 * (take(sd, lo) + take(sd, hi)); del sd
        sig = np.maximum(1.4826 * mad, floor)
        keep = valid & (dev <= KAPPA * sig * f); del dev
        c0 = np.where(valid, c, 0)
        ws = (w * keep).sum(0); m1 = (w * keep * c0).sum(0) / np.maximum(ws, 1e-9)
        r = np.where(keep, (c0 - m1) / f, 0); nk = keep.sum(0)
        sd1 = np.maximum(np.sqrt((r ** 2).sum(0) / np.maximum(nk - 1, 1)), floor); del r
        keep = valid & (np.abs(c0 - m1) <= KAPPA * sd1 * f)
        ws = (w * keep).sum(0)
        mean = np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32)
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint16))
        for name, idx in subs.items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


def control(cube, geo, faint_s, wts, nfac, SUB):
    fs7 = np.array([clipped_stats(cube[i][faint_s][::7])[1] for i in range(len(cube))])
    floor = np.float32(0.4 * np.nanmedian(fs7))
    rows = [(a, min(a + 48, HC)) for a in range(0, HC, 48)]
    res = {k: np.zeros((HC, WC), np.uint16 if k == 'used' else np.float32) for k in ['mean', 'used'] + list(SUB)}
    def work(ab):
        a, b = ab
        return ab, combine(cube[:, a:b], geo[:, a:b], floor, SUB, wts, nfac)
    with ThreadPoolExecutor(WORKERS) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): res[k][a:b] = v
    return res, floor, fs7


def psf_stars(common):
    d = S2[REF_STAMP]['stars']
    hm = np.median([s['hfr'] for s in d if s['flux'] > 20000 and not s['saturated']])
    iso = max(PSF_ISOLATION, 2 * (np.ceil(2.5 * 2 * hm / 2) + 4))
    cx, cy = ELL['centre_px'][0] - X0, ELL['centre_px'][1] - Y0; R0 = ELL['semi_major_px']
    xy = []
    for s in d:
        if s['flux'] >= PSF_FLUX_MIN and not s['saturated'] and s['nearest'] > iso and s['hfr'] and s['hfr'] <= 1.25 * hm:
            x, y = s['x'] - X0, s['y'] - Y0
            if np.hypot(x - cx, y - cy) > R0 and 30 < x < WC - 31 and 30 < y < HC - 31 and common[int(round(y)), int(round(x))]: xy.append((x, y))
    return np.array(xy), float(4 * hm)


def peak_ok(cube, xy, consts, p, scale):
    ok = []
    for x, y in xy:
        xi, yi = int(round(x)), int(round(y))
        pk = np.nanmax(cube[:, yi - 3:yi + 4, xi - 3:xi + 4], axis=(1, 2))
        fy, fx = min(max(yi + Y0, 0), h2 - 1), min(max(xi + X0, 0), w2 - 1)
        raw = (pk + consts) * FL['long'][p][fy, fx] / scale
        ok.append(bool(np.all(raw < PSF_PEAK_MAX)))
    return np.array(ok)


def separable_check(cube, xy, radius):
    bands = dict(middle=(xy[:, 0] >= WC / 3) & (xy[:, 0] < 2 * WC / 3), outer=(xy[:, 0] < WC / 3) | (xy[:, 0] >= 2 * WC / 3))
    hf = {b: np.array([coadd.measure_psf(np.nan_to_num(cube[j]), xy[m], radius)[1]['hfd_px'] for j in range(len(cube))]) for b, m in bands.items()}
    rel = {b: v / np.median(v) for b, v in hf.items()}
    r = float(np.corrcoef(rel['middle'], rel['outer'])[0, 1]); d = rel['middle'] - rel['outer']
    return dict(stars=dict(middle=int(bands['middle'].sum()), outer=int(bands['outer'].sum())), frame_to_frame_spread=dict(middle=float(np.std(rel['middle'])), outer=float(np.std(rel['outer']))), correlation=r, rms_difference=float(np.std(d)),
                verdict='the frames\' PSFs %s across the field (correlation %.2f; the bands differ by %.1f%% rms against a frame-to-frame spread of %.1f%%); one PSF per frame' % ('change together' if r > 0.5 else 'do NOT change together', r, 100 * np.std(d), 100 * np.std(rel['middle'])))


def matched_snr(img, psf, xy, faint, starmask):
    """Point-source S/N in an image: smooth light off, matched filter with the image's own PSF, noise of the filtered
    image over the faint region (stars masked), signal at each star. Returns the per-star S/N."""
    D = np.nan_to_num(img) - smooth_level(np.nan_to_num(img), 16, 5)
    k = psf[::-1, ::-1].astype(np.float32); k = k / np.sqrt((k ** 2).sum())
    Fm = cv2.filter2D(D.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
    v = Fm[faint & ~starmask][::3]; sd = float(1.4826 * np.median(np.abs(v - np.median(v))))
    return np.array([Fm[int(round(y)), int(round(x))] / sd for x, y in xy]), sd


def hfd_of(img, xy, radius):
    return coadd.psf_stats(coadd.measure_psf(np.nan_to_num(img), xy, radius)[0])['hfd_px']


if __name__ == '__main__':
    t00 = time.time()
    L = KIND['long']; Ss = KIND['short']; N = len(L['stamps']); iref = L['stamps'].index(REF_STAMP)
    with ThreadPoolExecutor(WORKERS) as ex:
        drows = sum(ex.map(offsets_in_frame, L['stamps'][::DISP_EVERY]), [])
    disp_before = offsets_summary(drows); disp_before['frames'] = L['stamps'][::DISP_EVERY]
    print('colour offsets in the frames (sensor px): red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f), scatter %s, %d measures' % (*disp_before['red_minus_green_sensor_px'], *disp_before['blue_minus_green_sensor_px'], disp_before['scatter_sensor_px'], disp_before['measures']), flush=True)
    if os.environ.get('M42_DISPERSION', '1') == '1':
        DISP[0] = tuple(disp_before['red_minus_green_sensor_px']); DISP[3] = tuple(disp_before['blue_minus_green_sensor_px'])
    cover = np.load(W('pass1_cover.npy')); allcov = cover == N
    T1 = np.load(W('pass1_green.npy'))
    Gs = cv2.GaussianBlur(smooth_level(np.nan_to_num(T1, nan=float(np.nanmedian(T1))), 16, 5), (0, 0), 32)
    thr = np.percentile(Gs[allcov], FAINT_PCT); faint = allcov & (Gs <= thr)
    np.save(W('faint_region.npy'), faint); ys, xs = np.nonzero(faint); samp = (ys[::5], xs[::5])
    print('canvas %d x %d; area every long frame covers %.1f%%; faint region %d px (darkest %.0f%% of it); %d long, %d short frames' % (WC, HC, 100 * allcov.mean(), faint.sum(), FAINT_PCT, N, len(Ss['stamps'])), flush=True)
    starmask = np.zeros((HC, WC), np.uint8)
    for s_ in S2[REF_STAMP]['stars']:
        r = 40 if s_['saturated'] else int(np.clip(8 + 8 * np.log10(max(s_['flux'], 1e3) / 1e4), 6, 30))
        cv2.circle(starmask, (int(round(s_['x'] - X0)), int(round(s_['y'] - Y0))), r, 1, -1)
    starmask = starmask > 0
    xy0, hfd_run = psf_stars(allcov); RADIUS = int(np.ceil(2.5 * hfd_run / 2))
    print('PSF stars (reference frame list): %d; run median HFD %.2f plane px -> PSF radius %d px' % (len(xy0), hfd_run / 2, RADIUS), flush=True)
    order = np.arange(N); SUB = dict(odd=order[1::2], even=order[0::2])
    keys = ('proper', 'mean-psf', 'proper_odd', 'proper_even', 'masked-mean', 'control', 'control_odd', 'control_even')
    res = {k: np.zeros((4, HC, WC), np.float32) for k in keys}
    usedc = np.zeros((4, HC, WC), np.uint16); single = np.zeros((4, HC, WC), np.float32)
    near_long = np.zeros((HC, WC), bool); near_long_frames = np.zeros((HC, WC), np.uint16)
    CONST = np.zeros((N, 4)); info = []; rec = {}; compare = {}
    for p in range(4):
        t0 = time.time(); P = PLANE_NAMES[p]
        cube = np.empty((N, HC, WC), np.float32); nearp = np.zeros((HC, WC), np.uint16)
        def put(i):
            a, n = warp(L['stamps'][i], p, near=True)
            m, sd, _ = clipped_stats(a[samp]); CONST[i, p] = m
            cube[i] = a - np.float32(m)
            return n
        with ThreadPoolExecutor(WORKERS) as ex:
            for n in ex.map(put, range(N)): nearp += n
        near_long |= nearp > 0; near_long_frames = np.maximum(near_long_frames, nearp)
        geo = np.isfinite(cube); single[p] = cube[iref]
        ctl, floor, fs7 = control(cube, geo, faint, L['wts'], L['nfac'], SUB)
        res['control'][p] = ctl['mean']; res['control_odd'][p] = ctl['odd']; res['control_even'][p] = ctl['even']
        seen = int(geo.sum()); usedn = int(ctl['used'].sum())
        info.append(dict(plane=P, frame_noise_in_faint_region=fs7.tolist(), sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=float((seen - usedn) / seen), near_ceiling_px=int((nearp > 0).sum())))
        t1 = time.time()
        sig = np.array([clipped_stats(cube[i][faint])[1] for i in range(N)]); F = np.ones(N)
        xy = coadd.refine_positions(np.nan_to_num(ctl['mean']), xy0)
        ok = np.isfinite(xy[:, 0]) & peak_ok(cube, np.nan_to_num(xy), CONST[:, p], p, np.array([L['scale'][s] for s in L['stamps']]))
        xy = xy[ok]
        fv = coadd.field_variation(np.nan_to_num(ctl['mean']), xy, RADIUS, shape=(3, 3), min_stars=8)
        sep = separable_check(cube, xy, RADIUS) if p == 1 else None
        psfs, pinf = [], []
        for j in range(N):
            ps, inf = coadd.measure_psf(np.nan_to_num(cube[j]), xy, RADIUS); psfs.append(ps); pinf.append(inf)
        psfs = np.array(psfs)
        th = coadd.theory(psfs, F, sig); th_ctl = coadd.theory(psfs, F, sig, weights=L['wts'])
        fyy, fxx = np.clip(np.mgrid[0:HC, 0:WC][0] + Y0, 0, h2 - 1), np.clip(np.mgrid[0:HC, 0:WC][1] + X0, 0, w2 - 1)
        flatc = FL['long'][p][fyy, fxx]; del fyy, fxx
        nmap = np.float32(np.median(flatc[faint])) / flatc
        mask, minfo = coadd.outlier_mask(cube, F, sig, psfs=psfs, noise_map=nmap)
        minfo['flagged_fraction_in_faint_region'] = float(mask[:, faint].mean())
        usedc[p] = (geo & ~mask).sum(0)
        rows = [(a, min(a + 48, HC)) for a in range(0, HC, 48)]
        for a0, b0 in rows:
            k_ = geo[:, a0:b0] & ~mask[:, a0:b0]; w_ = (1 / sig ** 2).astype(np.float32)[:, None, None] * k_
            res['masked-mean'][p, a0:b0] = np.where(w_.sum(0) > 0, (w_ * np.where(k_, cube[:, a0:b0], 0)).sum(0) / np.maximum(w_.sum(0), 1e-12), np.nan)
        out = coadd.proper_coadd(cube, psfs, F, sig, mask=mask, target='mean-psf', keep_hat=True)
        res['proper'][p] = out['S']; res['mean-psf'][p] = out['C']
        hv = {name: coadd.proper_coadd(cube[idx], psfs[idx], F[idx], sig[idx], mask=mask[idx], keep_hat=True) for name, idx in SUB.items()}
        Pcom = np.minimum(out['P_R_hat'], np.minimum(hv['odd']['P_R_hat'], hv['even']['P_R_hat']))
        halves = {}
        for name, o in hv.items():
            a_ = coadd.convolve_to(o, Pcom, phase=out['phase_hat'], name='the minimum of the full set\'s and both halves\' P_R_hat, with the full set\'s phase')
            res['proper_' + name][p] = a_['C']
            halves[name] = dict(F_R=o['F_R'], psf_R=coadd.psf_stats(o['psf_R']), common_psf=coadd.psf_stats(a_['psf_C']), to_common=a_['target_info'])
        del hv
        # coadd against the control, measured on the images (green planes only, for the time)
        if p in (1, 2):
            psf_ctl = coadd.measure_psf(np.nan_to_num(ctl['mean']), xy, RADIUS)[0]
            sn_p, nf_p = matched_snr(out['S'], out['psf_R'], xy, faint, starmask); sn_c, nf_c = matched_snr(ctl['mean'], psf_ctl, xy, faint, starmask)
            okk = (sn_p > 10) & (sn_c > 10)
            compare[P] = dict(stars=int(okk.sum()), snr_ratio_median=float(np.median(sn_p[okk] / sn_c[okk])), snr_ratio_quartiles=[float(np.percentile(sn_p[okk] / sn_c[okk], 25)), float(np.percentile(sn_p[okk] / sn_c[okk], 75))],
                              pixel_noise_faint_region=dict(proper=clipped_stats(out['S'][faint & ~starmask])[1], control=clipped_stats(ctl['mean'][faint & ~starmask])[1], masked_mean=clipped_stats(res['masked-mean'][p][faint & ~starmask])[1]),
                              filtered_noise=dict(proper=nf_p, control=nf_c), hfd_px=dict(proper=coadd.psf_stats(out['psf_R'])['hfd_px'], control=coadd.psf_stats(psf_ctl)['hfd_px']),
                              theory_gain_over_control_weights=float(th['snr_proper'] / th_ctl['snr_weighted_mean']))
            print('   %s coadd vs control: point-source S/N ratio %.4f (median of %d stars, quartiles %.3f..%.3f); pixel noise %.2f vs %.2f DN; HFD %.2f vs %.2f px; theory %.4f' % (P, compare[P]['snr_ratio_median'], compare[P]['stars'], *compare[P]['snr_ratio_quartiles'], compare[P]['pixel_noise_faint_region']['proper'], compare[P]['pixel_noise_faint_region']['control'], compare[P]['hfd_px']['proper'], compare[P]['hfd_px']['control'], compare[P]['theory_gain_over_control_weights']), flush=True)
        rec[P] = coadd.recipe(F, sig, pinf, minfo, out, th=th, stamps_of=L['stamps'],
                              extra=dict(psf_stars=int(len(xy)), psf_radius_px=RADIUS, field_variation=fv, separable=sep, halves=halves,
                                         theory_with_the_control_weights=dict(snr_weighted_mean=th_ctl['snr_weighted_mean'], gain_of_proper=th['snr_proper'] / th_ctl['snr_weighted_mean']), sky_noise_per_frame_dn=sig.tolist()))
        for pi in rec[P]['frames']: pi['psf'] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pi['psf'].items()}
        if p == 1: np.save(W('psf_R_green.npy'), out['psf_R'])
        print('%s: constants %.1f..%.1f; control dropped %.3f%% (%.0fs) | coadd: %d PSF stars r=%d, PSF HFD %.2f..%.2f px (P_R %.2f), flagged %.3f%% (faint region %.3f%%, beta %.2f), theory gain %.4f; near ceiling %d px; %.0fs' % (
            P, CONST[:, p].min(), CONST[:, p].max(), 100 * info[-1]['dropped_fraction'], t1 - t0, len(xy), RADIUS, min(i['hfd_px'] for i in pinf), max(i['hfd_px'] for i in pinf), coadd.psf_stats(out['psf_R'])['hfd_px'],
            100 * minfo['flagged_fraction'], 100 * minfo['flagged_fraction_in_faint_region'], minfo['beta'], th['gain'], info[-1]['near_ceiling_px'], time.time() - t1), flush=True)
        if sep: print('   ', sep['verdict'], flush=True)
        del cube, geo, mask, out
    # ---- the short frames: the control combine, and where they too came near the ceiling
    NS = len(Ss['stamps']); SSUB = dict(odd=np.arange(NS)[1::2], even=np.arange(NS)[0::2])
    short = {k: np.zeros((4, HC, WC), np.float32) for k in ('mean', 'odd', 'even')}; short_cover = np.zeros((HC, WC), np.uint16)
    near_short = np.zeros((HC, WC), bool); CONST_S = np.zeros((NS, 4)); short_info = []
    for p in range(4):
        cube = np.empty((NS, HC, WC), np.float32); nearp = np.zeros((HC, WC), np.uint16)
        def puts(i):
            a, n = warp(Ss['stamps'][i], p, near=True)
            v = a[samp]; v = v[np.isfinite(v)]
            m, sd, _ = clipped_stats(v); CONST_S[i, p] = m
            cube[i] = a - np.float32(m)
            return n
        with ThreadPoolExecutor(WORKERS) as ex:
            for n in ex.map(puts, range(NS)): nearp += n
        near_short |= nearp > 0
        geo = np.isfinite(cube)
        if p == 1: short_cover[:] = geo.sum(0)
        fsS = np.array([clipped_stats(cube[i][faint & geo[i]][::7])[1] for i in range(NS)])
        o, floor, _ = control(cube, geo, faint, Ss['wts'], Ss['nfac'], SSUB)
        for k in short: short[k][p] = o[k]
        short_info.append(dict(plane=PLANE_NAMES[p], frame_noise_in_faint_region_median=float(np.median(fsS)), sigma_floor=float(floor), constants_range=[float(CONST_S[:, p].min()), float(CONST_S[:, p].max())], near_ceiling_px=int((nearp > 0).sum())))
        print('short %s: constants %.1f..%.1f DN, frame noise %.1f DN, near ceiling %d px' % (PLANE_NAMES[p], CONST_S[:, p].min(), CONST_S[:, p].max(), np.median(fsS), short_info[-1]['near_ceiling_px']), flush=True)
        del cube, geo
    # ---- save
    for k, v in res.items(): np.save(W('long_%s.npy' % k.replace('-', '')), v)
    np.save(W('long_used.npy'), usedc); np.save(W('stack_single.npy'), single); np.save(W('stack_cover.npy'), cover)
    np.save(W('long_near.npy'), near_long); np.save(W('short_near.npy'), near_short); np.save(W('short_cover.npy'), short_cover)
    for k, v in short.items(): np.save(W('short_%s.npy' % k), v)
    pick = dict(proper=('proper', 'proper_odd', 'proper_even'), control=('control', 'control_odd', 'control_even'))[DELIVER]
    for k, src in zip(('long_deliver', 'long_deliver_odd', 'long_deliver_even'), pick): np.save(W(k + '.npy'), res[src])
    disp_after = offsets_summary(offsets_in_stack(res[pick[0]]))
    print('colour offsets left in the long stack (sensor px): red - green (%+.3f, %+.3f), blue - green (%+.3f, %+.3f), %d stars' % (*disp_after['red_minus_green_sensor_px'], *disp_after['blue_minus_green_sensor_px'], disp_after['measures']), flush=True)
    noise = {k: [clipped_stats(res[k][p][faint & ~starmask])[1] for p in range(4)] for k in ('proper', 'control', 'masked-mean')}
    noise['single'] = [clipped_stats(single[p][faint & ~starmask & np.isfinite(single[p])])[1] for p in range(4)]
    noise['half_difference_proper'] = [clipped_stats(((res['proper_odd'][p] - res['proper_even'][p]) / 2)[faint & ~starmask])[1] for p in range(4)]
    noise['short'] = [clipped_stats(short['mean'][p][faint & ~starmask & np.isfinite(short['mean'][p])])[1] for p in range(4)]
    for k, v in noise.items(): print('noise in the faint region (stars masked), %-24s %s DN' % (k, ' '.join('%s %.2f' % (PLANE_NAMES[q], v[q]) for q in range(4))))
    jdump(dict(frames=L['stamps'], short_frames=Ss['stamps'], reference=REF_STAMP, kappa=KAPPA, canvas=dict(X0=X0, Y0=Y0, HC=HC, WC=WC), combine='long: proper coadd (coadd.py), delivered %s; control: the clipped weighted mean from the same cube; short: the clipped weighted mean' % DELIVER,
               faint_region=dict(percentile=FAINT_PCT, pixels=int(faint.sum()), smoothed_green_max=float(thr), what='area every long frame covers, darkest part of the first green stack (M42 fills the field: not the true sky)'),
               constants={s: CONST[i].tolist() for i, s in enumerate(L['stamps'])}, short_constants={s: CONST_S[i].tolist() for i, s in enumerate(Ss['stamps'])}, subsets={k: [L['stamps'][i] for i in v] for k, v in SUB.items()},
               planes=info, short_planes=short_info, noise_faint_region_dn=noise, coadd_vs_control=compare, near_ceiling=dict(rule='at or above %.2f x (16000 - black) raw DN in a plane of a frame, before any repair' % NEAR_CEILING, long_px=int(near_long.sum()), short_px=int(near_short.sum()), long_max_frames_per_pixel=int(near_long_frames.max())),
               air_dispersion=dict(measured_in_the_frames=disp_before, taken_out_sensor_px={PLANE_NAMES[k]: list(v) for k, v in DISP.items()}, left_in_the_stack=disp_after)), 'step8_stack.json')
    jdump(dict(deliver=DELIVER, what='proper coaddition per colour plane of the long frames; the control (the clipped weighted mean) made from the same cube', planes=rec), 'step8_coadd.json')
    print('%.0f s in all' % (time.time() - t00))
