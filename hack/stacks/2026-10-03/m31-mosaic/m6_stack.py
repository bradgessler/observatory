"""Mosaic step 6: stack each panel on the HALF grid of its registration reference frame (3012 x 2012, 0.776
arcsec per pixel; each colour plane has exactly one sample per half-grid pixel, so nothing is interpolated up).

Per frame and colour plane:
  black-subtracted, hot pixels repaired (step 2)
  / the core run's smooth cloud-glow flat of that plane (flat2d.npy: radial part, tilt, edge shading; version C)
  / the small-scale flat (step 5b: the mean of the core run's and this hour's dust-ratio maps; green, used for all planes)
  x 1 / transparency (step 5)
  -> resampled onto the panel grid (rotation + shift + the plane's own place in the 2x2 colour cell, Lanczos-4)
  -> minus a smooth SECOND-ORDER SURFACE fitted to (this frame - the panel's clearest frame).

That last step is where this departs from the core run (which took off one constant per frame). Under the Moon
the thin cloud's glow is not even: between two frames of the same panel the background differs by slopes of up
to 42 DN and bows of up to 26 DN across half the frame (more in the rejected frames), as large as the galaxy's outer disc. The galaxy and the true
sky are the same in both frames and cancel in the difference, so nothing of the galaxy is fitted: the surface is
six numbers (constant, two slopes, three second-order terms) fitted to 64 px block medians of the difference,
blocks weighted down where the galaxy is bright (weight 1 / (1 + (galaxy / 150 DN)^2), so that a small error of
the transparency, which leaves a trace only where the galaxy is bright, cannot pull the surface), 3-sigma rejection.
After it every frame of a panel carries the large-scale background of the panel's CLEAREST frame (lowest sky
among its frames with transparency >= 0.97). That one frame's sky, moonlight gradient and whatever thin cloud
it had are still in the panel: they are dealt with (one constant and one plane per panel) in step 9, against the
other panels and the core stack.

Sensor pixels under a mapped dust shadow (core run's map OR this hour's, step 5b) are LEFT OUT of the average,
as in the core run. The field moves only 30 to 90 px inside a panel, so most shadows cannot be cleared: where
fewer than half of the panel's frames are clean, the pixel is taken from a second combine with the masked samples
left in (they too have been divided by the measured small-scale flat, which holds the shadow's transmission),
and flagged (flag 2).
The hair on the sensor moved 175 px and turned 55 degrees during the hour; its centre is measured in every used
frame and a circle of 220 sensor px round it is left out. Where no frame is clear of the hair there is NO data
(flag 0).

Combine, per pixel and plane, as the core run: values further than 3 sigma from the median are dropped (sigma =
1.4826 x MAD, floor 0.4 x the single-frame noise, widened by each frame's noise factor), then 3 sigma about the
weighted mean, then the weighted mean (weights from step 5). With only two samples a median cannot reject
anything, so there a pair is tested instead: if the two differ by more than 5 sigma of their difference, the lower
one is kept (a satellite, an aircraft or a cosmic ray only adds light).
Also kept: the two half-stacks (alternate frames) for the noise, the summed weights, the flags."""
import json, os, sys, time, warnings
warnings.filterwarnings('ignore', message='All-NaN slice encountered')
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from mcommon import *

KAPPA = 3.0
BS = 64
HAIR_R = 110            # plane px (220 sensor px)
s1 = {f['stamp']: f for f in json.load(open(W('m1.json')))['frames']}
SEL = json.load(open(W('m5_select.json'))); T4 = json.load(open(W('m4_transforms.json')))
FLAT = np.load(CW('flat2d.npy'))
DUSTM = np.load(W('dustmask_mosaic.npy')); SMALL = np.load(W('smallflat_mosaic.npy'))
DUSTF = DUSTM.astype(np.float32)
FLAT_SMOOTH = FLAT
FLAT = FLAT * SMALL[None]                     # the smooth flat times the small-scale flat: every frame is divided by both
# With real flat frames (the dawn flats): M31M_MASTER_FLAT = a .npy of shape (4, 2012, 3012), one flat per colour
# plane (R, G1, G2, B; black-subtracted median of the flat frames, each plane divided by its value at the sensor
# centre). It then replaces BOTH flats above, dust included, so nothing needs to be left out for dust; the hair is
# still cut out per frame (it will sit elsewhere in the flats than in these frames: give its place in the flats as
# M31M_DUST_MASK, a boolean .npy (2012, 3012), and those sensor pixels are left out as dust was).
# M31M_NODATA_MASK (added with the first run that used these hooks): a boolean .npy (2012, 3012) of sensor pixels from
# which NO data is taken, like the hair's circle (the dawn hair's place in the flat: the flat is wrong there).
NODATA = None
if os.environ.get('M31M_MASTER_FLAT'):
    FLAT = np.load(os.environ['M31M_MASTER_FLAT']).astype(np.float32); assert FLAT.shape == (4, H2, W2), FLAT.shape
    DUSTM = np.load(os.environ['M31M_DUST_MASK']).astype(bool) if os.environ.get('M31M_DUST_MASK') else np.zeros((H2, W2), bool)
    DUSTF = DUSTM.astype(np.float32)
    if os.environ.get('M31M_NODATA_MASK'): NODATA = np.load(os.environ['M31M_NODATA_MASK']).astype(np.float32)
YY, XX = np.mgrid[0:H2, 0:W2].astype(np.float32)


def hair_centre(P):
    """Centre of the hair's shadow in this frame (plane px), from the frame itself, or None."""
    x0, y0, x1, y1 = 1500, 0, 2300, 420
    G = ((P[1] / FLAT_SMOOTH[1] + P[2] / FLAT_SMOOTH[2]) / 2)[y0:y1, x0:x1]
    sub = cv2.GaussianBlur(G, (0, 0), 4); sub = sub / np.median(sub)
    n, lab, stats, cent = cv2.connectedComponentsWithStats((sub < 0.90).astype(np.uint8), connectivity=8)
    best = None
    for i in range(1, n):
        if 1500 <= stats[i, 4] <= 9000 and (best is None or stats[i, 4] > stats[best, 4]): best = i
    if best is None: return None
    return float(cent[best][0] + x0), float(cent[best][1] + y0), int(stats[best, 4]), float(sub[lab == best].min())


def blocks(a):
    ny, nx = H2 // BS, W2 // BS
    b = a[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(b).sum(2); v = np.nanmedian(b, axis=2)
    v[n < BS * BS // 2] = np.nan
    return v

ny_, nx_ = H2 // BS, W2 // BS
BY, BX = np.mgrid[0:ny_, 0:nx_]
bxn = ((BX + 0.5) * BS - W2 / 2) / (W2 / 2); byn = ((BY + 0.5) * BS - H2 / 2) / (H2 / 2)
XN = (XX + 0.5 - W2 / 2) / (W2 / 2); YN = (YY + 0.5 - H2 / 2) / (H2 / 2)


def quad_terms(x, y): return [np.ones_like(x), x, y, x * x, x * y, y * y]


def take(s, k): return np.take_along_axis(s, k[None], 0)[0]


def combine(c, valid, wts, nfac, floor, sig1, halves):
    """c: (N, h, w); valid: bool; sig1: (N, h, w) or broadcastable, the single-sample sigma (for the pair test)."""
    N = c.shape[0]; f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        c0 = np.where(valid, c, 0)
        if N >= 3:
            lo = np.clip((n - 1) // 2, 0, N - 1); hi = np.clip(n // 2, 0, N - 1)
            s = np.sort(cv_, axis=0); med = 0.5 * (take(s, lo) + take(s, hi)); del s
            dev = np.abs(cv_ - med); sd = np.sort(dev, axis=0); mad = 0.5 * (take(sd, lo) + take(sd, hi)); del sd
            sig = np.maximum(1.4826 * mad, floor)
            keep = valid & (dev <= KAPPA * sig * f) | (valid & (n <= 2))
            ws = (w * keep).sum(0); m1 = (w * keep * c0).sum(0) / np.maximum(ws, 1e-9)
            r = np.where(keep, (c0 - m1) / f, 0); nk = keep.sum(0)
            sd1 = np.maximum(np.sqrt((r ** 2).sum(0) / np.maximum(nk - 1, 1)), floor)
            keep = valid & ((np.abs(c0 - m1) <= KAPPA * sd1 * f) | (n <= 2))
        else:
            keep = valid.copy()
        # pixels with exactly two samples: the pair test
        two = keep.sum(0) == 2
        if two.any():
            idx = np.argsort(~keep, axis=0, kind='stable')[:2]          # the two kept samples
            a = np.take_along_axis(c0, idx[:1], 0)[0]; b = np.take_along_axis(c0, idx[1:2], 0)[0]
            sa = np.take_along_axis(np.broadcast_to(sig1, c.shape), idx[:1], 0)[0]; sb = np.take_along_axis(np.broadcast_to(sig1, c.shape), idx[1:2], 0)[0]
            bad = two & (np.abs(a - b) > 5.0 * np.sqrt(sa ** 2 + sb ** 2))
            drop_first = bad & (a > b); drop_second = bad & (b >= a)
            ii = np.arange(N)[:, None, None]
            keep &= ~((ii == idx[0][None]) & drop_first[None]) & ~((ii == idx[1][None]) & drop_second[None])
        ws = (w * keep).sum(0)
        mean = np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32)
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint8), wsum=ws.astype(np.float32))
        for nm, idxs in (halves or {}).items():
            ww = w[idxs] * keep[idxs]; wsum = ww.sum(0)
            out[nm] = np.where(wsum > 0, (ww * c0[idxs]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


def stack_panel(name):
    t0 = time.time()
    sel = SEL[name]; USE = sel['used']; N = len(USE); stamps = [u['stamp'] for u in USE]
    tr = {o['stamp']: o for o in T4[name]['transforms']}
    wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32)
    bgref = sel['background_reference']; iref = stamps.index(bgref)
    P = {s: np.load(W('planes/' + s + '.npy')) for s in stamps}
    # the hair, per frame
    hairs = {}
    for s in stamps:
        hc = hair_centre(P[s]); hairs[s] = hc
    known = [(tsec(s1[s]['t']), hairs[s][0], hairs[s][1]) for s in stamps if hairs[s] is not None]
    hmask = {}
    for s in stamps:
        if hairs[s] is None:
            assert known, 'no hair position in panel ' + name
            j = int(np.argmin([abs(k[0] - tsec(s1[s]['t'])) for k in known])); cx, cy = known[j][1], known[j][2]
        else: cx, cy = hairs[s][0], hairs[s][1]
        hmask[s] = (np.hypot(XX - cx, YY - cy) < HAIR_R).astype(np.float32)
        if NODATA is not None: hmask[s] = np.maximum(hmask[s], NODATA)
    def maps(s, p):
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t']); ox, oy = OFFS[p]
        sx = 2 * XX + 0.5; sy = 2 * YY + 0.5
        fx = R[0, 0] * sx + R[0, 1] * sy + t[0]; fy = R[1, 0] * sx + R[1, 1] * sy + t[1]
        return fx.astype(np.float32), fy.astype(np.float32)
    def warp(s, p):
        fx, fy = maps(s, p); ox, oy = OFFS[p]
        v = (P[s][p] / FLAT[p] * np.float32(1.0 / next(u['transparency'] for u in USE if u['stamp'] == s))).astype(np.float32)
        out = cv2.remap(v, (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
        mx, my = (fx - 0.5) / 2, (fy - 0.5) / 2
        dust = cv2.remap(DUSTF, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        hair = cv2.remap(hmask[s], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        fl = cv2.remap(FLAT[p], (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return out, dust, hair, fl
    halves = dict(A=np.arange(0, N, 2), B=np.arange(1, N, 2))
    final = np.full((4, H2, W2), np.nan, np.float32); flag = np.zeros((H2, W2), np.uint8); wsum = np.zeros((4, H2, W2), np.float32); dAB = np.zeros((4, H2, W2), np.float32)
    flat_ref = np.zeros((4, H2, W2), np.float32)
    surf = {s: [] for s in stamps}; info = []
    need = (N + 1) // 2
    for p in range(4):
        with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda s: warp(s, p), stamps))
        cube = np.stack([r[0] for r in res]); dust = np.stack([r[1] for r in res]); hair = np.stack([r[2] for r in res])
        flat_ref[p] = res[iref][3]; del res
        geo = np.isfinite(cube)
        # ---- background: every frame to the clearest frame, second-order surface of the difference ----
        okr = geo[iref] & ~dust[iref] & ~hair[iref]
        refb = blocks(np.where(okr, cube[iref], np.nan)); floor_lv = float(np.nanpercentile(refb, 2))
        for i, s in enumerate(stamps):
            if i == iref: surf[s].append(dict(plane=PLANE_NAMES[p], reference=True)); continue
            d = blocks(np.where(okr & geo[i] & ~dust[i] & ~hair[i], cube[i] - cube[iref], np.nan))
            ok = np.isfinite(d) & np.isfinite(refb)
            gal = (refb[ok] - floor_lv)
            A = np.column_stack([t_[ok] for t_ in quad_terms(bxn, byn)]); v = d[ok]; w = 1.0 / (1.0 + (gal / 150.0) ** 2); keep = np.ones(len(v), bool)
            for _ in range(5):
                sw = np.sqrt(w[keep]); co, *_ = np.linalg.lstsq(A[keep] * sw[:, None], v[keep] * sw, rcond=None)
                r = v - A @ co; sd = 1.4826 * np.median(np.abs(r[keep] * np.sqrt(w[keep]))); keep = np.abs(r) * np.sqrt(w) < 3 * max(sd, 1e-3)
            r0 = v - np.median(v[keep])
            Apl = A[:, :3]; cpl, *_ = np.linalg.lstsq(Apl[keep] * np.sqrt(w[keep])[:, None], v[keep] * np.sqrt(w[keep]), rcond=None); rpl = v - Apl @ cpl
            faint = keep & (gal < 150)
            surface = sum(c_ * t_ for c_, t_ in zip(co[:6], quad_terms(XN, YN))).astype(np.float32)
            cube[i] -= surface
            surf[s].append(dict(plane=PLANE_NAMES[p], constant=float(co[0]), slope_x_dn_per_half_frame=float(co[1]), slope_y_dn_per_half_frame=float(co[2]), second_order=[float(c_) for c_ in co[3:6]],
                                blocks=int(keep.sum()), surface_min_max_dn=[float(surface.min() - co[0]), float(surface.max() - co[0])],
                                rms_of_difference_dn=dict(after_a_constant=float(np.sqrt(np.mean(r0[faint] ** 2))), after_a_plane=float(np.sqrt(np.mean(rpl[faint] ** 2))), after_this_surface=float(np.sqrt(np.mean(r[faint] ** 2))))))
        # ---- combine ----
        floor = np.float32(0.4 * s1[bgref]['corner'][p]['clipped_std'])
        L0 = np.float32(max(s1[bgref]['corner'][p]['clipped_mean'], 1.0)); n0 = np.float32(s1[bgref]['corner'][p]['clipped_std'])
        rows = [(a, min(a + 96, H2)) for a in range(0, H2, 96)]
        def work(ab):
            a, b = ab; c = cube[:, a:b]; g = geo[:, a:b] & ~hair[:, a:b]
            lev = np.maximum(np.nanmedian(np.where(g, c, np.nan), axis=0), L0) if g.any() else np.full(c.shape[1:], L0)
            sig1 = n0 * nfac[:, None, None] * np.sqrt(np.nan_to_num(lev, nan=float(L0)) / L0)[None]
            o = combine(c, g & ~dust[:, a:b], wts, nfac, floor, sig1, halves)
            o2 = combine(c, g, wts, nfac, floor, sig1, None)
            return ab, o, o2
        usedc = np.zeros((H2, W2), np.uint8); used2 = np.zeros((H2, W2), np.uint8); mean2 = np.zeros((H2, W2), np.float32); ws2 = np.zeros((H2, W2), np.float32)
        hA = np.zeros((H2, W2), np.float32); hB = np.zeros((H2, W2), np.float32)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), o, o2 in ex.map(work, rows):
                final[p, a:b] = o['mean']; usedc[a:b] = o['used']; wsum[p, a:b] = o['wsum']; hA[a:b] = o['A']; hB[a:b] = o['B'] if N > 1 else np.nan
                mean2[a:b] = o2['mean']; used2[a:b] = o2['used']; ws2[a:b] = o2['wsum']
        clean = usedc >= need
        fb = ~clean & (used2 >= need)
        final[p] = np.where(clean, final[p], np.where(fb, mean2, np.nan)); wsum[p] = np.where(clean, wsum[p], np.where(fb, ws2, 0))
        if p == 1:
            flag[clean] = 1; flag[fb] = 2
            cover_any = geo.any(0); hair_all = cover_any & ~(geo & ~hair).any(0)
        dAB[p] = (hA - hB) if N > 1 else np.nan
        seen = int(geo.sum()); dustn = int((geo & dust & ~hair).sum()); hairn = int((geo & hair).sum())
        info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=seen, samples_left_out_for_dust=dustn, samples_left_out_for_the_hair=hairn,
                         samples_dropped_by_the_clip=int(seen - dustn - hairn - int(usedc.sum())), pixels_clean=int(clean.sum()), pixels_from_dust_divided_combine=int(fb.sum()), pixels_without_data_inside_the_frame=int((geo.any(0) & ~clean & ~fb).sum())))
        del cube, dust, hair, geo
    # noise of the stack from the half-stacks, in the faintest clean quarter
    G = (final[1] + final[2]) / 2
    sm = cv2.GaussianBlur(cv2.medianBlur(cv2.resize(np.nan_to_num(G, nan=float(np.nanmedian(G))), None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5), (0, 0), 3)
    smf = cv2.resize(sm, (W2, H2), interpolation=cv2.INTER_LINEAR)
    inner = np.zeros((H2, W2), bool); inner[150:-150, 150:-150] = True
    okn = inner & (flag == 1) & np.isfinite(dAB[1])
    faint = okn & (smf <= np.percentile(smf[okn], 25)) if okn.any() else okn
    WA, WB = float(wts[halves['A']].sum()), float(wts[halves['B']].sum())
    k = np.sqrt(WA * WB) / (WA + WB) if N > 1 else float('nan')
    noise = [float(clipped_stats(dAB[p][faint][::3])[1] * k) if N > 1 else None for p in range(4)]
    level = [float(clipped_stats(final[p][faint][::3])[0]) for p in range(4)]
    np.save(W('%s_planes.npy' % name), final); np.save(W('%s_wsum.npy' % name), wsum[1]); np.save(W('%s_flag.npy' % name), flag); np.save(W('%s_flatref.npy' % name), flat_ref)
    np.save(W('%s_dAB.npy' % name), (dAB * np.float32(k)).astype(np.float32))
    out = dict(panel=name, frames=stamps, registration_reference=T4[name]['reference'], background_reference=bgref, weights=[float(v) for v in wts], transparency=[u['transparency'] for u in USE],
               hair_centre_sensor_px={s: (None if hairs[s] is None else [round(2 * hairs[s][0] + 0.5), round(2 * hairs[s][1] + 0.5)]) for s in stamps}, hair_circle_radius_sensor_px=2 * HAIR_R,
               master_flat=os.environ.get('M31M_MASTER_FLAT'), dust_mask=os.environ.get('M31M_DUST_MASK'), nodata_mask=os.environ.get('M31M_NODATA_MASK'),
               surfaces_taken_off={s: surf[s] for s in stamps}, planes=info, halves={k_: [stamps[i] for i in v] for k_, v in halves.items()}, half_difference_factor=k,
               noise_of_stack_dn_per_half_grid_px=dict(zip(PLANE_NAMES, noise)), level_in_faintest_quarter_dn=dict(zip(PLANE_NAMES, level)),
               units='DN of one 30 s frame at the transparency of the panel\'s clear frames, flat-fielded; the level is that of the clearest frame (sky included)',
               flags=dict(no_data=int((flag == 0).sum()), clean=int((flag == 1).sum()), dust_divided=int((flag == 2).sum()), hair_no_data=int(hair_all.sum())))
    json.dump(out, open(W('m6_%s.json' % name), 'w'), indent=1)
    print('panel %-6s %d frames, clearest %s; hair at %s; clean %.1f%%, dust-divided %.1f%%, no data %.1f%% (hair %.2f%%); stack noise per half-grid px R %.1f G1 %.1f G2 %.1f B %.1f DN; level %s; %.0fs' % (
        name, N, bgref[9:], [out['hair_centre_sensor_px'][s] for s in stamps][:1], 100 * (flag == 1).mean(), 100 * (flag == 2).mean(), 100 * (flag == 0).mean(), 100 * hair_all.mean(), *[v if v is not None else float('nan') for v in noise], np.round(level, 1).tolist(), time.time() - t0), flush=True)
    for s in stamps:
        g1 = surf[s][1]
        if g1.get('reference'): print('    %s clearest frame (reference)' % s); continue
        print('    %s G1 surface: const %+7.1f slope x %+6.1f y %+6.1f second order %s (range %+.0f..%+.0f DN) | rms const %.2f plane %.2f surface %.2f' % (
            s, g1['constant'], g1['slope_x_dn_per_half_frame'], g1['slope_y_dn_per_half_frame'], np.round(g1['second_order'], 1).tolist(), *g1['surface_min_max_dn'], g1['rms_of_difference_dn']['after_a_constant'], g1['rms_of_difference_dn']['after_a_plane'], g1['rms_of_difference_dn']['after_this_surface']))


if __name__ == '__main__':
    names = sys.argv[1:] or [p[0] for p in PANELS]
    for nm in names: stack_panel(nm)
