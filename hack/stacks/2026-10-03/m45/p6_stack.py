"""Step 6: stack each panel on the HALF grid of its registration reference frame (3012 x 2012, 0.7754 arcsec per
pixel; each colour plane has exactly one sample per half-grid pixel, so nothing is interpolated up). Adapted from
the night's M31 mosaic (m6_stack.py).

Per frame and colour plane:
  black-subtracted, hot pixels and spikes repaired (steps 2, 3)
  / the M31 run's smooth flat of that plane (flat2d.npy: vignetting, tilt, edge shading)
  / the small-scale flat of the sensor's dust shadows (the M31 core run's dust map, measured three hours earlier;
    checked against this hour's own sky flat in step 2: the shadows are still where they were, except the hair,
    in whose box nothing is divided)
  x 1 / transparency (step 5)
  -> resampled onto the panel grid (rotation + shift + the plane's own place in the 2x2 colour cell, Lanczos-4)
  -> minus a smooth SECOND-ORDER SURFACE fitted to (this frame - the panel's clearest frame).
The sky, the glare and the nebulosity are the same in two frames of one panel and cancel in the difference, so
nothing of the nebulosity is fitted: the surface is six numbers fitted to 64 px block medians of the difference,
blocks weighted down where the picture is bright (weight 1 / (1 + (level / 150 DN)^2)), 3-sigma rejection. After
it every frame of a panel carries the large-scale background of the panel's CLEAREST frame; that frame's sky,
moonlight gradient and glare stay in the panel and are dealt with between panels (one constant per panel, step 10).

The hair on the sensor moves (it turned by 70 degrees during this hour): a circle of 200 sensor px round its
measured place in each panel (step 2b) is left out of every frame: NO data there (flag 0). Pixels under a mapped
dust shadow are kept (they have been divided by the shadow's measured transmission) and flagged 2.

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD,
floor 0.4 x the single-frame noise, widened by each frame's noise factor), then 3 sigma about the weighted mean,
then the weighted mean (weights from step 5). With only two samples a pair is tested instead: if the two differ by
more than 5 sigma of their difference, the lower one is kept (a satellite, an aircraft or a cosmic ray only adds).
Also kept: the two half-stacks (alternate frames) for the noise, the summed weights, the flags, and which pixels
were at the sensor's ceiling in any frame."""
import json, sys, time, warnings
warnings.filterwarnings('ignore', message='All-NaN slice encountered')
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from c import *

KAPPA = 3.0
BS = 64
HAIR_R = 100            # plane px (200 sensor px)
F1 = {f['stamp']: f for f in json.load(open(W('p1.json')))['frames']}
SEL = json.load(open(W('p5_select.json'))); T4 = json.load(open(W('p4_transforms.json'))); HAIR = json.load(open(W('p2b_hair.json')))
FLAT, DUSTF, NODATA = stack_flats()             # first run: cloud-glow flat x dust map, its dust mask, nothing; with M45_MASTER_FLAT: see c.stack_flats
YY, XX = np.mgrid[0:H2, 0:W2].astype(np.float32)


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
    N = c.shape[0]; f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        c0 = np.where(valid, c, 0)
        dropped_hi = np.zeros(c.shape[1:], np.uint8)
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


def stack_panel(name):
    t0 = time.time()
    sel = SEL[name]; USE = sel['used']; N = len(USE); stamps = [u['stamp'] for u in USE]
    tr = {o['stamp']: o for o in T4[name]['transforms']}
    wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32)
    bgref = sel['background_reference']; iref = stamps.index(bgref)
    def rd(s):
        P, ceil, meta, trans = repaired(F1[s]['path'], [c_['clipped_std'] for c_ in F1[s]['corner']])
        return P, ceil.any(0).astype(np.float32), trans
    with ThreadPoolExecutor(7) as ex: loaded = list(ex.map(rd, stamps))
    P = {s: l[0] for s, l in zip(stamps, loaded)}; CE = {s: l[1] for s, l in zip(stamps, loaded)}; spikes = {s: l[2] for s, l in zip(stamps, loaded)}
    hc = HAIR[name]['centre_plane_px']
    hmask = (np.hypot(XX - hc[0], YY - hc[1]) < HAIR_R).astype(np.float32)
    if NODATA is not None: hmask = np.maximum(hmask, NODATA)
    def maps(s):
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t'])
        sx = 2 * XX + 0.5; sy = 2 * YY + 0.5
        fx = R[0, 0] * sx + R[0, 1] * sy + t[0]; fy = R[1, 0] * sx + R[1, 1] * sy + t[1]
        return fx.astype(np.float32), fy.astype(np.float32)
    MAPS = {s: maps(s) for s in stamps}
    def warp(s, p):
        fx, fy = MAPS[s]; ox, oy = OFFS[p]
        v = (P[s][p] / FLAT[p] * np.float32(1.0 / next(u['transparency'] for u in USE if u['stamp'] == s))).astype(np.float32)
        out = cv2.remap(v, (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
        mx, my = (fx - 0.5) / 2, (fy - 0.5) / 2
        dust = cv2.remap(DUSTF, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        hair = cv2.remap(hmask, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
        fl = cv2.remap(FLAT[p], (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return out, dust, hair, fl
    sat = np.zeros((H2, W2), bool)
    for s in stamps:
        fx, fy = MAPS[s]
        sat |= cv2.remap(CE[s], (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
    halves = dict(A=np.arange(0, N, 2), B=np.arange(1, N, 2))
    final = np.full((4, H2, W2), np.nan, np.float32); flag = np.zeros((H2, W2), np.uint8); wsum = np.zeros((4, H2, W2), np.float32); dAB = np.zeros((4, H2, W2), np.float32)
    flat_ref = np.zeros((4, H2, W2), np.float32)
    surf = {s: [] for s in stamps}; info = []
    need = (N + 1) // 2
    for p in range(4):
        with ThreadPoolExecutor(7) as ex: res = list(ex.map(lambda s: warp(s, p), stamps))
        cube = np.stack([r[0] for r in res]); dust = np.stack([r[1] for r in res]); hair = np.stack([r[2] for r in res])
        flat_ref[p] = res[iref][3]; del res
        geo = np.isfinite(cube)
        # ---- background: every frame to the clearest frame, second-order surface of the difference ----
        okr = geo[iref] & ~hair[iref]
        refb = blocks(np.where(okr, cube[iref], np.nan)); floor_lv = float(np.nanpercentile(refb, 2))
        for i, s in enumerate(stamps):
            if i == iref: surf[s].append(dict(plane=PLANE_NAMES[p], reference=True)); continue
            d = blocks(np.where(okr & geo[i] & ~hair[i], cube[i] - cube[iref], np.nan))
            ok = np.isfinite(d) & np.isfinite(refb)
            lev = (refb[ok] - floor_lv)
            A = np.column_stack([t_[ok] for t_ in quad_terms(bxn, byn)]); v = d[ok]; w = 1.0 / (1.0 + (lev / 150.0) ** 2); keep = np.ones(len(v), bool)
            for _ in range(5):
                sw = np.sqrt(w[keep]); co, *_ = np.linalg.lstsq(A[keep] * sw[:, None], v[keep] * sw, rcond=None)
                r = v - A @ co; sd = 1.4826 * np.median(np.abs(r[keep] * np.sqrt(w[keep]))); keep = np.abs(r) * np.sqrt(w) < 3 * max(sd, 1e-3)
            r0 = v - np.median(v[keep])
            Apl = A[:, :3]; cpl, *_ = np.linalg.lstsq(Apl[keep] * np.sqrt(w[keep])[:, None], v[keep] * np.sqrt(w[keep]), rcond=None); rpl = v - Apl @ cpl
            faint = keep & (lev < 150)
            surface = sum(c_ * t_ for c_, t_ in zip(co[:6], quad_terms(XN, YN))).astype(np.float32)
            cube[i] -= surface
            surf[s].append(dict(plane=PLANE_NAMES[p], constant=float(co[0]), slope_x_dn_per_half_frame=float(co[1]), slope_y_dn_per_half_frame=float(co[2]), second_order=[float(c_) for c_ in co[3:6]],
                                blocks=int(keep.sum()), surface_min_max_dn=[float(surface.min() - co[0]), float(surface.max() - co[0])],
                                rms_of_difference_dn=dict(after_a_constant=float(np.sqrt(np.mean(r0[faint] ** 2))), after_a_plane=float(np.sqrt(np.mean(rpl[faint] ** 2))), after_this_surface=float(np.sqrt(np.mean(r[faint] ** 2))))))
        # ---- combine ----
        n0 = np.float32(F1[bgref]['corner'][p]['clipped_std']); floor = np.float32(0.4 * n0)
        rows = [(a, min(a + 96, H2)) for a in range(0, H2, 96)]
        def work(ab):
            a, b = ab; c = cube[:, a:b]; g = geo[:, a:b] & ~hair[:, a:b]
            with np.errstate(all='ignore'):
                lev = np.nanmedian(np.where(g, c, np.nan), axis=0) if g.any() else np.zeros(c.shape[1:], np.float32)
            sig1 = np.sqrt(n0 ** 2 + NOISE_GAIN * np.clip(np.nan_to_num(lev, nan=0.0), 0, None))[None] * nfac[:, None, None]
            return ab, combine(c, g, wts, nfac, floor, sig1, halves)
        usedc = np.zeros((H2, W2), np.uint8); hA = np.zeros((H2, W2), np.float32); hB = np.zeros((H2, W2), np.float32)
        with ThreadPoolExecutor(8) as ex:
            for (a, b), o in ex.map(work, rows):
                final[p, a:b] = o['mean']; usedc[a:b] = o['used']; wsum[p, a:b] = o['wsum']; hA[a:b] = o['A']; hB[a:b] = o['B'] if N > 1 else np.nan
        okp = usedc >= need
        final[p] = np.where(okp, final[p], np.nan); wsum[p] = np.where(okp, wsum[p], 0)
        if p == 1: nused = usedc.copy()
        if p == 0: allok = okp.copy(); dustmaj = dust.sum(0) * 2 > N; cover_any = geo.any(0); hair_all = cover_any & ~(geo & ~hair).any(0)
        else: allok &= okp
        dAB[p] = (hA - hB) if N > 1 else np.nan
        seen = int((geo & ~hair).sum())
        info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=int(geo.sum()), samples_left_out_for_the_hair=int((geo & hair).sum()),
                         samples_dropped_by_the_clip=int(seen - int(usedc.sum())), fraction_dropped_by_the_clip=float((seen - int(usedc.sum())) / max(seen, 1)), pixels_with_data=int(okp.sum())))
        del cube, dust, hair, geo
    final[:, ~allok] = np.nan
    flag[allok] = 1; flag[allok & dustmaj] = 2
    WA, WB = float(wts[halves['A']].sum()), float(wts[halves['B']].sum())
    k = np.sqrt(WA * WB) / (WA + WB) if N > 1 else float('nan')
    inner = np.zeros((H2, W2), bool); inner[150:-150, 150:-150] = True
    G = (final[1] + final[2]) / 2
    sm = cv2.blur(np.nan_to_num(G, nan=float(np.nanmedian(G))), (65, 65))
    okn = inner & (flag == 1) & np.isfinite(dAB[1])
    faint = okn & (sm <= np.percentile(sm[okn], 25))
    noise = [float(clipped_stats(dAB[p][faint][::3])[1] * k) if N > 1 else None for p in range(4)]
    level = [float(clipped_stats(final[p][faint][::3])[0]) for p in range(4)]
    np.save(W('%s_planes.npy' % name), final); np.save(W('%s_wsum.npy' % name), wsum[1]); np.save(W('%s_flag.npy' % name), flag); np.save(W('%s_flatref.npy' % name), (flat_ref[1] + flat_ref[2]) / 2)
    np.save(W('%s_sat.npy' % name), sat); np.save(W('%s_nused.npy' % name), np.where(allok, nused, 0).astype(np.uint8))
    out = dict(panel=name, frames=stamps, registration_reference=T4[name]['reference'], background_reference=bgref, weights=[float(v) for v in wts], transparency=[u['transparency'] for u in USE],
               spikes_repaired={s: spikes[s] for s in stamps}, hair_centre_sensor_px=HAIR[name]['centre_sensor_px'], hair_circle_radius_sensor_px=2 * HAIR_R, master_flat=MASTER_FLAT,
               surfaces_taken_off={s: surf[s] for s in stamps}, planes=info, halves={k_: [stamps[i] for i in v] for k_, v in halves.items()}, half_difference_factor=k,
               noise_of_stack_dn_per_half_grid_px=dict(zip(PLANE_NAMES, noise)), level_in_faintest_quarter_dn=dict(zip(PLANE_NAMES, level)),
               single_frame_noise_dn=[F1[bgref]['corner'][p]['clipped_std'] for p in range(4)], summed_weights=float(wts.sum()),
               pixels_at_the_ceiling_in_any_frame=int(sat.sum()),
               units='DN of one 10 s frame at the transparency of the panel\'s clear frames, flat-fielded; the level is that of the clearest frame (sky included)',
               flags=dict(no_data=int((flag == 0).sum()), clean=int((flag == 1).sum()), dust_divided=int((flag == 2).sum()), hair_no_data=int(hair_all.sum())))
    json.dump(out, open(W('p6_%s.json' % name), 'w'), indent=1)
    print('panel %-5s %d frames, clearest %s; clean %.1f%%, dust-divided %.1f%%, no data %.1f%% (hair %.2f%%); clipped %.2f%%; stack noise per half-grid px R %s G1 %s G2 %s B %s DN; level %s; sat px %d; %.0fs' % (
        name, N, bgref[9:], 100 * (flag == 1).mean(), 100 * (flag == 2).mean(), 100 * (flag == 0).mean(), 100 * hair_all.mean(), 100 * info[1]['fraction_dropped_by_the_clip'],
        *['%.1f' % v if v is not None else '-' for v in noise], np.round(level, 1).tolist(), int(sat.sum()), time.time() - t0), flush=True)
    for s in stamps:
        g1 = surf[s][1]
        if g1.get('reference'): print('    %s clearest frame (reference)' % s); continue
        print('    %s G1 surface: const %+7.1f slope x %+6.1f y %+6.1f second order %s (range %+.0f..%+.0f DN) | rms const %.2f plane %.2f surface %.2f' % (
            s, g1['constant'], g1['slope_x_dn_per_half_frame'], g1['slope_y_dn_per_half_frame'], np.round(g1['second_order'], 1).tolist(), *g1['surface_min_max_dn'], g1['rms_of_difference_dn']['after_a_constant'], g1['rms_of_difference_dn']['after_a_plane'], g1['rms_of_difference_dn']['after_this_surface']))


if __name__ == '__main__':
    names = sys.argv[1:] or PANELS
    for nm in names: stack_panel(nm)
