"""Step 7: stack each set on the HALF grid of its registration reference frame (3012 x 2012, 0.776 arcsec per
pixel; each colour plane has exactly one sample per half-grid pixel, so nothing is interpolated up). The SHORT
set is stacked on the DEEP set's grid. Method of the M31 mosaic run (m6_stack.py).

Per frame and colour plane:
  black-subtracted, hot pixels repaired (step 2)
  / the flat of that plane (step 6)
  x 1 / transparency (step 5)
  -> resampled onto the set's grid (rotation + shift + the plane's own place in the 2x2 colour cell, Lanczos-4)
  -> minus a smooth surface fitted to (this frame - the set's clearest frame): a SECOND-ORDER SURFACE (six
     numbers) for the 20 s frames, ONE CONSTANT for the 2 s frames. The nebula and the true sky are the same in
     both frames and cancel in the difference, so nothing of the nebula is fitted; the surface is fitted to 64 px
     block medians of the difference, blocks weighted down where the nebula is bright (weight 1 / (1 + (level /
     150 DN)^2), so that a small error of the transparency, which leaves a trace only where the nebula is bright,
     cannot pull the surface), 3-sigma rejection. After it every frame of a set carries the large-scale
     background of the set's CLEAREST frame. That one frame's sky and moonlight are still in the stack: they are
     dealt with later (one constant per colour for the deep stack, a constant and a plane per panel against it).

The hair on the sensor is found in every frame from the frame itself (hair.py) and left out. Where no frame is
clear of it there is NO data. Pixels listed in the flat's leave-out map (dust under the cloud flat; the hair's
place in the twilight flats) are left out where at least half the frames see that sky through other pixels,
and otherwise taken from a second combine with them left in (flag 2).

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD,
floor 0.4 x the single-frame noise, widened by each frame's noise factor), then 3 sigma about the weighted
mean, then the weighted mean (weights from step 5). With only two samples a pair is tested instead: if the two
differ by more than 5 sigma of their difference, the lower one is kept (a satellite, an aircraft or a cosmic
ray only adds light).

CLIPPING. Before anything else each frame's pixels within a margin of the ceiling are noted: any of the four
colour planes of a 2x2 cell at or above NEAR_CEILING (14400 DN above black; the ceiling is about 15500), grown
by one cell. These masks are carried onto the grid and counted: <set>_clip.npy = in how many of the set's used
frames this pixel was near the ceiling in ANY plane. The HDR blend (step 9) uses the short stack wherever that
count is not zero.

Also kept: the two half-stacks (alternate frames) for the noise, the summed weights, the flags."""
import json, os, sys, time, warnings
warnings.filterwarnings('ignore', message='All-NaN slice encountered')
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import prep, hair as hairmod

KAPPA = 3.0
BS = 64
s1 = prep.s1()
SEL = json.load(open(W('s5_select.json'))); T4 = json.load(open(W('s4_transforms.json')))
FLAT = np.load(W('flat.npy')); FLAT_SMOOTH = np.load(W('flat_smooth.npy')); LEAVE = np.load(W('flat_leaveout.npy'))
LEAVEF = LEAVE.astype(np.float32)
YY, XX = np.mgrid[0:H2, 0:W2].astype(np.float32)
K3 = np.ones((3, 3), np.uint8)

ny_, nx_ = H2 // BS, W2 // BS
BY, BX = np.mgrid[0:ny_, 0:nx_]
bxn = ((BX + 0.5) * BS - W2 / 2) / (W2 / 2); byn = ((BY + 0.5) * BS - H2 / 2) / (H2 / 2)
XN = (XX + 0.5 - W2 / 2) / (W2 / 2); YN = (YY + 0.5 - H2 / 2) / (H2 / 2)


def quad_terms(x, y, order): return [np.ones_like(x), x, y, x * x, x * y, y * y][:{0: 1, 1: 3, 2: 6}[order]]


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
        two = keep.sum(0) == 2
        if two.any():
            idx = np.argsort(~keep, axis=0, kind='stable')[:2]
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


def stack_set(name):
    t0 = time.time()
    sel = SEL[name]; USE = sel['used']; N = len(USE); stamps = [u['stamp'] for u in USE]
    order = 0 if name == 'short' else 2
    tr = {o['stamp']: o for o in T4[name]['transforms']}
    wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32)
    bgref = sel['background_reference']; iref = stamps.index(bgref)
    with ThreadPoolExecutor(6) as ex: loaded = list(ex.map(lambda s: prep.load_repaired(s, masks=True), stamps))
    P = {s: l[0] for s, l in zip(stamps, loaded)}
    nearf = {s: cv2.dilate(l[2].any(0).astype(np.uint8), K3).astype(np.float32) for s, l in zip(stamps, loaded)}     # near the ceiling in any plane, grown by one cell
    ceilf = {s: l[1].any(0).astype(np.float32) for s, l in zip(stamps, loaded)}                                     # at the ceiling in any plane
    spikes = {s: l[3] for s, l in zip(stamps, loaded)}; del loaded
    # the hair, per frame
    hairs = {}; hmask = {}
    if name == 'short':
        # a 2 s frame has 3 DN of sky: the hair's shadow cannot be seen in it. Its place is taken from the 20 s frame nearest in time.
        longs = [u['stamp'] for u in SEL['deep']['used']]
        for s in stamps: hairs[s] = None
        near_t = sorted(longs, key=lambda k: abs(tsec(s1[k]['t']) - tsec(s1[stamps[len(stamps) // 2]]['t'])))[:2]
        mm = None
        for k in near_t:
            m, info = hairmod.find_hair(prep.load_repaired(k), FLAT_SMOOTH)
            if m is not None: mm = m if mm is None else (mm | m); hairs['from ' + k] = info
        assert mm is not None
        for s in stamps: hmask[s] = mm.astype(np.float32)
    else:
        for s in stamps:
            m, info = hairmod.find_hair(P[s], FLAT_SMOOTH); hairs[s] = info
            if m is not None: hmask[s] = m.astype(np.float32)
    known = [s for s in stamps if s in hmask]
    for s in stamps:
        if s not in hmask:
            assert known, 'no hair position in set ' + name
            j = min(known, key=lambda k: abs(tsec(s1[k]['t']) - tsec(s1[s]['t']))); hmask[s] = hmask[j]
    def maps(s):
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t'])
        sx = 2 * XX + 0.5; sy = 2 * YY + 0.5
        return (R[0, 0] * sx + R[0, 1] * sy + t[0]).astype(np.float32), (R[1, 0] * sx + R[1, 1] * sy + t[1]).astype(np.float32)
    def warp(s, p):
        fx, fy = maps(s); ox, oy = OFFS[p]
        v = (P[s][p] / FLAT[p] * np.float32(1.0 / next(u['transparency'] for u in USE if u['stamp'] == s))).astype(np.float32)
        out = cv2.remap(v, (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
        mx, my = (fx - 0.5) / 2, (fy - 0.5) / 2
        dust = cv2.remap(LEAVEF, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        hair = cv2.remap(hmask[s], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        fl = cv2.remap(FLAT[p], (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return out, dust, hair, fl
    # clipping maps
    clip = np.zeros((H2, W2), np.uint8); ceil = np.zeros((H2, W2), np.uint8)
    for s in stamps:
        fx, fy = maps(s); mx, my = (fx - 0.5) / 2, (fy - 0.5) / 2
        clip += cv2.remap(nearf[s], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        ceil += cv2.remap(ceilf[s], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
    halves = dict(A=np.arange(0, N, 2), B=np.arange(1, N, 2))
    final = np.full((4, H2, W2), np.nan, np.float32); flag = np.zeros((H2, W2), np.uint8); wsum = np.zeros((4, H2, W2), np.float32); dAB = np.zeros((4, H2, W2), np.float32)
    flat_ref = np.zeros((4, H2, W2), np.float32); nused = np.zeros((H2, W2), np.uint8)
    surf = {s: [] for s in stamps}; info = []
    need = (N + 1) // 2
    for p in range(4):
        with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda s: warp(s, p), stamps))
        cube = np.stack([r[0] for r in res]); dust = np.stack([r[1] for r in res]); hair = np.stack([r[2] for r in res])
        flat_ref[p] = res[iref][3]; del res
        geo = np.isfinite(cube)
        # ---- background: every frame to the clearest frame ----
        okr = geo[iref] & ~dust[iref] & ~hair[iref]
        refb = blocks_median(np.where(okr, cube[iref], np.nan), BS); floor_lv = float(np.nanpercentile(refb, 2))
        for i, s in enumerate(stamps):
            if i == iref: surf[s].append(dict(plane=PLANE_NAMES[p], reference=True)); continue
            d = blocks_median(np.where(okr & geo[i] & ~dust[i] & ~hair[i], cube[i] - cube[iref], np.nan), BS)
            ok = np.isfinite(d) & np.isfinite(refb)
            neb = (refb[ok] - floor_lv)
            A = np.column_stack([t_[ok] for t_ in quad_terms(bxn, byn, order)]); v = d[ok]; w = 1.0 / (1.0 + (neb / (150.0 if name != 'short' else 4.0)) ** 2); keep = np.ones(len(v), bool)
            for _ in range(5):
                sw = np.sqrt(w[keep]); co, *_ = np.linalg.lstsq(A[keep] * sw[:, None], v[keep] * sw, rcond=None)
                r = v - A @ co; sd = 1.4826 * np.median(np.abs(r[keep] * np.sqrt(w[keep]))); keep = np.abs(r) * np.sqrt(w) < 3 * max(sd, 1e-3)
            faint = keep & (neb < (150 if name != 'short' else 4))
            r0 = v - np.median(v[keep])
            surface = sum(c_ * t_ for c_, t_ in zip(co, quad_terms(XN, YN, order))).astype(np.float32)
            cube[i] -= surface
            rec = dict(plane=PLANE_NAMES[p], constant=float(co[0]), blocks=int(keep.sum()), rms_of_difference_dn=dict(after_a_constant=float(np.sqrt(np.mean(r0[faint] ** 2))), after_this_surface=float(np.sqrt(np.mean(r[faint] ** 2)))))
            if order == 2: rec.update(slope_x_dn_per_half_frame=float(co[1]), slope_y_dn_per_half_frame=float(co[2]), second_order=[float(c_) for c_ in co[3:6]], surface_min_max_dn=[float(surface.min() - co[0]), float(surface.max() - co[0])])
            surf[s].append(rec)
        # ---- combine ----
        dk = s1[bgref]['dark_block']
        floor = np.float32(0.4 * dk['clipped_std'][p])
        L0 = np.float32(max(dk['clipped_mean'][p], 1.0)); n0 = np.float32(dk['clipped_std'][p])
        rows = [(a, min(a + 96, H2)) for a in range(0, H2, 96)]
        def work(ab):
            a, b = ab; c = cube[:, a:b]; g = geo[:, a:b] & ~hair[:, a:b]
            lev = np.maximum(np.nanmedian(np.where(g, c, np.nan), axis=0), L0) if g.any() else np.full(c.shape[1:], L0)
            sig1 = n0 * nfac[:, None, None] * np.sqrt(np.nan_to_num(lev, nan=float(L0)) / L0)[None]
            o = combine(c, g & ~dust[:, a:b], wts, nfac, floor, sig1, halves)
            o2 = combine(c, g, wts, nfac, floor, sig1, None) if LEAVE.any() else None
            return ab, o, o2
        usedc = np.zeros((H2, W2), np.uint8); used2 = np.zeros((H2, W2), np.uint8); mean2 = np.zeros((H2, W2), np.float32); ws2 = np.zeros((H2, W2), np.float32)
        hA = np.zeros((H2, W2), np.float32); hB = np.zeros((H2, W2), np.float32)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), o, o2 in ex.map(work, rows):
                final[p, a:b] = o['mean']; usedc[a:b] = o['used']; wsum[p, a:b] = o['wsum']; hA[a:b] = o['A']; hB[a:b] = o['B'] if N > 1 else np.nan
                if o2 is not None: mean2[a:b] = o2['mean']; used2[a:b] = o2['used']; ws2[a:b] = o2['wsum']
        nmax = (geo & ~hair).sum(0)
        # enough samples: half of the set's frames, or, where the hair or the frame edges leave fewer frames than that, half of those there are
        clean = (usedc >= np.minimum(need, (nmax + 1) // 2)) & (usedc > 0)
        fb = ~clean & (used2 > 0)
        final[p] = np.where(clean, final[p], np.where(fb, mean2, np.nan)); wsum[p] = np.where(clean, wsum[p], np.where(fb, ws2, 0))
        if p == 1:
            flag[clean] = 1; flag[fb] = 2; nused = np.where(clean, usedc, np.where(fb, used2, 0)).astype(np.uint8)
            cover_any = geo.any(0); hair_all = cover_any & ~(geo & ~hair).any(0)
        dAB[p] = (hA - hB) if N > 1 else np.nan
        seen = int(geo.sum()); dustn = int((geo & dust & ~hair).sum()); hairn = int((geo & hair).sum())
        info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=seen, samples_left_out_by_the_flat_map=dustn, samples_left_out_for_the_hair=hairn,
                         samples_dropped_by_the_clip=int(seen - dustn - hairn - int(usedc.sum())), pixels_clean=int(clean.sum()), pixels_from_the_second_combine=int(fb.sum()), pixels_without_data_inside_the_frame=int((geo.any(0) & ~clean & ~fb).sum())))
        del cube, dust, hair, geo
    # noise of the stack from the half-stacks, in the faintest clean quarter of the fully covered part
    G = (final[1] + final[2]) / 2
    sm = cv2.GaussianBlur(cv2.medianBlur(cv2.resize(np.nan_to_num(G, nan=float(np.nanmedian(G))), None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5), (0, 0), 3)
    smf = cv2.resize(sm, (W2, H2), interpolation=cv2.INTER_LINEAR)
    full = (flag == 1) & (wsum[1] >= 0.9 * wsum[1].max()) & np.isfinite(dAB[1])
    faint = full & (smf <= np.percentile(smf[full], 25)) if full.any() else full
    WA, WB = float(wts[halves['A']].sum()), float(wts[halves['B']].sum())
    k = np.sqrt(WA * WB) / (WA + WB) if N > 1 else float('nan')
    noise = [float(clipped_stats(dAB[p][faint][::3])[1] * k) if N > 1 else None for p in range(4)]
    level = [float(clipped_stats(final[p][faint][::3])[0]) for p in range(4)]
    np.save(W('%s_planes.npy' % name), final); np.save(W('%s_wsum.npy' % name), wsum[1]); np.save(W('%s_flag.npy' % name), flag); np.save(W('%s_flatref.npy' % name), flat_ref)
    np.save(W('%s_dAB.npy' % name), (dAB * np.float32(k)).astype(np.float32)); np.save(W('%s_clip.npy' % name), clip); np.save(W('%s_ceil.npy' % name), ceil); np.save(W('%s_n.npy' % name), nused)
    out = dict(set=name, frames=stamps, registration_reference=T4[name]['reference'], background_reference=bgref, background_surface_order=order, weights=[float(v) for v in wts], transparency=[u['transparency'] for u in USE],
               hair=hairs, hair_grown_by_sensor_px=60, spikes_repaired={s: spikes[s] for s in stamps},
               surfaces_taken_off={s: surf[s] for s in stamps}, planes=info, halves={k_: [stamps[i] for i in v] for k_, v in halves.items()}, half_difference_factor=k,
               noise_of_stack_dn_per_half_grid_px=dict(zip(PLANE_NAMES, noise)), level_in_faintest_quarter_dn=dict(zip(PLANE_NAMES, level)),
               pixels_near_ceiling_in_any_frame=int((clip > 0).sum()), pixels_at_ceiling_in_any_frame=int((ceil > 0).sum()),
               units='DN of one frame of this set at the transparency of the set\'s clear frames, flat-fielded; the level is that of the clearest frame (sky included)',
               flags=dict(no_data=int((flag == 0).sum()), clean=int((flag == 1).sum()), second_combine=int((flag == 2).sum()), hair_no_data=int(hair_all.sum())))
    json.dump(out, open(W('s7_%s.json' % name), 'w'), indent=1)
    hs = [v['centre_sensor_xy'] for v in hairs.values() if v]
    print('set %-7s %d frames, clearest %s; hair found in %d frames, centre %s .. %s; clean %.1f%%, second combine %.1f%%, no data %.1f%% (hair %.2f%%); near ceiling in any frame %d px; stack noise per half-grid px R %.1f G1 %.1f G2 %.1f B %.1f DN; level %s; %.0fs' % (
        name, N, bgref[9:], len(hs), hs[0] if hs else None, hs[-1] if hs else None, 100 * (flag == 1).mean(), 100 * (flag == 2).mean(), 100 * (flag == 0).mean(), 100 * hair_all.mean(), int((clip > 0).sum()), *[v if v is not None else float('nan') for v in noise], np.round(level, 1).tolist(), time.time() - t0), flush=True)
    for s in stamps:
        g1 = surf[s][1]
        if g1.get('reference'): print('    %s clearest frame (reference)' % s); continue
        if order == 2:
            print('    %s G1 surface: const %+7.1f slope x %+6.1f y %+6.1f second order %s (range %+.0f..%+.0f DN) | rms const %.2f surface %.2f' % (
                s, g1['constant'], g1['slope_x_dn_per_half_frame'], g1['slope_y_dn_per_half_frame'], np.round(g1['second_order'], 1).tolist(), *g1['surface_min_max_dn'], g1['rms_of_difference_dn']['after_a_constant'], g1['rms_of_difference_dn']['after_this_surface']))
        else:
            print('    %s constants R %+.2f G1 %+.2f G2 %+.2f B %+.2f' % (s, *[surf[s][p_]['constant'] for p_ in range(4)]))


if __name__ == '__main__':
    names = sys.argv[1:] or list(SEL)
    for nm in names: stack_set(nm)
