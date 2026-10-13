"""Step 7: the flat. Not made here: the night's flat (<night>/flat/flat_planes.npz, built by the NGC 891 stack from its
31 frames of 08:50 to 09:10 UTC, same telescope, camera, 15 s, ISO 3200; its README.txt and flat.json say how) is read,
CHECKED AGAINST THIS RUN'S OWN OPEN SKY, and written to work/flat.npy for step 8. Nothing is written into <night>/flat/.

The check (outside the object mask of step 6: M78's 7 arcmin circle, NGC 2071's and NGC 2064's; 77% of the frame):
  own sky   per used frame and colour plane: the RAW plane (black subtracted, hot pixels repaired), 8 x 8 px block
            medians; blocks inside the object mask (moved by the frame's own shift, grown 24 px) and within a
            flux-scaled radius of every star found in step 2 are left out; divided by the frame's own median over the
            blocks left within 800 plane px of the sensor centre; the median over the frames, without registration
            (the field wandered by tens of pixels, the optics did not).
  remainder own sky / flat (the flat averaged over the same blocks), median set to 1. A perfect flat under an even sky
            leaves exactly 1 everywhere. Reported per colour, on 32 px blocks: robust rms, the range, the median in
            rings of radius, and a plane a + b x + c y fitted to it (a real slope of the sky is not a flat error; the
            NGC 891 fit found one too and left it out of the flat); the rms that is left after the plane.
            NOTE for this target: the innermost rings are mostly under M78's circle, so what the flat does in the
            middle of the sensor (the M77 and M1 stacks found it about 1.5% high there) is seen here only at the
            circle's rim. Step 11 measures what that leaves around the nebula.
  which     the README warns that red (and less so blue) may carry an additive term, and says to use the green
            profile for all four planes if a target's colours tilt towards the corners. Both are measured here: each
            colour's own flat, and the green flat 0.5 x (G1 + G2) for all. FLAT_CHOICE (hook M78_FLAT) decides:
            'auto' takes, per colour, whichever leaves the smaller rms after the plane; 'own' or 'green' force one.
  dust      "check the flat against the hour" (the skill). The 13 largest shadows of the flat (flat.json,
            dust.shadows): the depth of each in THIS run's own sky (median inside 0.7 x its radius over the median of a
            ring around it) before and after the division. The M77 and M1 stacks found that the night's flat left its
            shadows 1 to 5% deep; the same is measured here, and the remainder is measured from this run's own sky
            (green, 8 px blocks, over its own 160 px scale; seen in the even and in the odd frames alone) and divided
            out where it is a shadow; the flat is untouched everywhere else. Hook M78_OWN_DUST=0 leaves the night's
            flat as it came. Under the nebulae themselves no dust can be judged (DUST_BLIND_R and common.EXTRA).

Also v_flat_check.png: the green remainder (0.96 black to 1.04 white, 8 px blocks, the object mask blank)."""
import json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *
import solvelib

BK = 8
DUST_BLIND_R = 330          # plane px (4.3 arcmin) around M78's catalogue place where no dust can be judged (the nebula itself); NGC 2071 and NGC 2064 have their own (common.EXTRA)
DUST_MIN, DUST_MIN_HALF, DUST_MIN_BLOCKS = 0.012, 0.006, 6
FLAT_CHOICE = os.environ.get('M78_FLAT', 'auto')
sel = jload('step5_select.json'); stamps = [u['stamp'] for u in sel['used']]
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
S6 = jload('step6_solve_ref.json'); ELL = S6['galaxy_ellipse']
nby, nbx = h2 // BK, w2 // BK


def blocks(a):
    return a[:nby * BK, :nbx * BK].reshape(nby, BK, nbx, BK).transpose(0, 2, 1, 3).reshape(nby, nbx, -1)


def own(stamp):
    P, meta = load_clean(path_of(stamp))
    stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == stamp][0]['stars']
    sh = np.array(tr[stamp]['shift_at_centre_px']) / 2                       # where the reference's centre went, plane px
    mask = solvelib.object_mask(S6, (h2, w2), shift=tuple(sh), grow=24.0).astype(np.uint8)
    for s in stars:
        r = 80 if s['saturated'] else int(np.clip(10 + 9 * np.log10(max(s['flux'], 1e3) / 1e4), 8, 40))
        cv2.circle(mask, (int(round(s['x'])), int(round(s['y']))), r, 1, -1)
    mb = blocks(mask).mean(2) > 0
    yy, xx = np.mgrid[0:nby, 0:nbx]; rc = np.hypot(xx * BK + BK / 2 - w2 / 2, yy * BK + BK / 2 - h2 / 2)
    out = np.empty((4, nby, nbx), np.float32); lev = []
    for p in range(4):
        b = np.median(blocks(P[p]), axis=2).astype(np.float32)
        b[mb] = np.nan
        l = float(np.nanmedian(b[rc < 800])); lev.append(l)
        out[p] = b / l
    # for the dust search: green, stars left out as above, but of the nebula only the part where it is brighter than about 1% of the sky (DUST_BLIND_R px
    # around its centre): further out its light is under 1% of the sky and smooth, and a shadow is judged against a ring
    cx, cy = ELL['centre_px'][0] + sh[0], ELL['centre_px'][1] + sh[1]
    m2 = np.zeros((h2, w2), np.uint8); cv2.circle(m2, (int(round(cx)), int(round(cy))), DUST_BLIND_R, 1, -1)
    for e_ in S6['extra_masks']: cv2.circle(m2, (int(round(e_['centre_px'][0] + sh[0])), int(round(e_['centre_px'][1] + sh[1]))), int(e_['dust_blind_px']), 1, -1)
    for s in stars:
        r = 80 if s['saturated'] else int(np.clip(10 + 9 * np.log10(max(s['flux'], 1e3) / 1e4), 8, 40))
        cv2.circle(m2, (int(round(s['x'])), int(round(s['y']))), r, 1, -1)
    g = np.median(blocks(0.5 * (P[1] + P[2])), axis=2).astype(np.float32); g[blocks(m2).mean(2) > 0] = np.nan
    return out, lev, g / np.float32(0.5 * (lev[1] + lev[2]))


def bin4(a):
    """32 px blocks from 8 px blocks: the median of the 4 x 4 that are there (at least half of them)."""
    ny, nx = a.shape[0] // 4, a.shape[1] // 4
    v = a[:ny * 4, :nx * 4].reshape(ny, 4, nx, 4).transpose(0, 2, 1, 3).reshape(ny, nx, 16)
    with np.errstate(all='ignore'):
        m = np.nanmedian(v, axis=2)
    m[np.isfinite(v).sum(2) < 8] = np.nan
    return m


def describe(Q):
    """Q: remainder on 8 px blocks. Numbers on 32 px blocks."""
    q = bin4(Q); ny, nx = q.shape
    yy, xx = np.mgrid[0:ny, 0:nx]; X = (xx * 32 + 16 - w2 / 2) * 2.0; Y = (yy * 32 + 16 - h2 / 2) * 2.0   # sensor px from the centre
    ok = np.isfinite(q); z = q[ok]; A = np.stack([np.ones(ok.sum()), X[ok], Y[ok]], 1); keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], z[keep], rcond=None); r = z - A @ co; s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3.5 * s
    rr = np.hypot(X, Y)[ok]; rings = []
    for a, b in ((0, 600), (600, 1200), (1200, 1800), (1800, 2400), (2400, 3000), (3000, 3700)):
        m = (rr >= a) & (rr < b)
        rings.append(dict(r_sensor_px=[a, b], blocks=int(m.sum()), remainder=round(float(np.median(z[m])), 4) if m.sum() > 5 else None, after_plane=round(float(np.median(r[m]) + 1), 4) if m.sum() > 5 else None))
    lo, hi = np.percentile(z, [1, 99])
    return dict(blocks=int(ok.sum()), robust_rms=float(1.4826 * np.median(np.abs(z - np.median(z)))), range_1_99_pct=[float(lo), float(hi)],
                sky_plane=dict(at_centre=float(co[0]), across_the_long_side=float(co[1] * Wd), across_the_short_side=float(co[2] * H)),
                robust_rms_after_plane=float(1.4826 * np.median(np.abs(r - np.median(r)))), rms_after_plane=float(np.std(r[keep])), rings=rings)


if __name__ == '__main__':
    need = [os.path.join(FLAT_DIR, f) for f in ('flat_planes.npz', 'flat.json', 'README.txt')]
    if not all(os.path.exists(f) for f in need):
        raise SystemExit('the night\'s flat is not in %s: build one from this run\'s own sky instead (the skill, "A flat from the night\'s own open-sky frames")' % FLAT_DIR)
    Z = np.load(need[0]); F = np.stack([Z[k].astype(np.float32) for k in PLANE_NAMES]); fj = json.load(open(need[1]))
    assert F.shape == (4, h2, w2), F.shape
    Fg = 0.5 * (F[1] + F[2])
    with ProcessPoolExecutor(WORKERS) as ex:
        res = list(ex.map(own, stamps))
    cube = np.stack([r[0] for r in res]); lev = np.array([r[1] for r in res]); gcube = np.stack([r[2] for r in res])
    with np.errstate(all='ignore'):
        S = np.nanmedian(cube, axis=0); n_there = np.isfinite(cube).sum(0)
    S[n_there < 10] = np.nan
    del cube
    print('own sky from %d frames; sky level (DN above black) R %.1f G1 %.1f G2 %.1f B %.1f; blocks with sky in at least 10 frames: %.1f%%' % (len(stamps), *np.median(lev, 0), 100 * np.isfinite(S[1]).mean()), flush=True)
    yy, xx = np.mgrid[0:nby, 0:nbx]; rc = np.hypot(xx * BK + BK / 2 - w2 / 2, yy * BK + BK / 2 - h2 / 2)
    out = dict(flat_from=dict(dir=FLAT_DIR, files=[os.path.basename(f) for f in need], made_from=fj['made_from']['target'], frames=len(fj['made_from']['frames']), their_sky_dn=fj['made_from']['sky_level_dn_median'], formula=fj.get('formula')),
               own_sky=dict(frames=stamps, block_px=BK, sky_level_dn_median=dict(zip(PLANE_NAMES, np.median(lev, 0).round(2).tolist())), coverage=float(np.isfinite(S[1]).mean())), planes={}, choice_rule=FLAT_CHOICE)
    USE = np.empty_like(F); Qshow = None
    for p in range(4):
        d = {}
        for name, flat in (('own', F[p]), ('green', Fg)):
            Fb = blocks(flat).mean(2); Q = S[p] / Fb; Q /= np.nanmedian(Q[rc < 800])
            d[name] = describe(Q)
            if p == 1 and name == 'own': Qshow = Q
        pick = FLAT_CHOICE if FLAT_CHOICE in ('own', 'green') else ('own' if d['own']['robust_rms_after_plane'] <= d['green']['robust_rms_after_plane'] else 'green')
        if p in (1, 2) and FLAT_CHOICE == 'auto': pick = 'own'
        d['used'] = pick; USE[p] = F[p] if pick == 'own' else Fg
        out['planes'][PLANE_NAMES[p]] = d
        for name in ('own', 'green'):
            v = d[name]
            print('%-2s / %-5s flat: remainder rms %.4f (1%%..99%%: %.3f..%.3f); sky plane %+.3f across the long side, %+.3f across the short; after the plane rms %.4f; rings %s%s' % (
                PLANE_NAMES[p], name, v['robust_rms'], *v['range_1_99_pct'], v['sky_plane']['across_the_long_side'], v['sky_plane']['across_the_short_side'], v['robust_rms_after_plane'],
                ' '.join('%.3f' % r['after_plane'] if r['after_plane'] else '-' for r in v['rings']), '   <- used' if name == pick else ''), flush=True)
    # ---- dust: this run's own sky against the flat, at 8 px blocks (green)
    Fb = blocks(0.5 * (USE[1] + USE[2])).mean(2)

    def remainder(idx):
        """Own green sky of the frames idx over the flat, over its own large scale (32 px block medians, 5 x 5 median of
        those = 160 px, bilinear back), then a Gaussian of 1 block (holes left out)."""
        with np.errstate(all='ignore'):
            Sg = np.nanmedian(gcube[idx], axis=0)
        Sg[np.isfinite(gcube[idx]).sum(0) < max(5, len(idx) // 3)] = np.nan
        R = Sg / Fb; R /= np.nanmedian(R)
        big = bin4(R); big = cv2.medianBlur(np.where(np.isfinite(big), big, 1.0).astype(np.float32), 5)
        D = R / cv2.resize(big, (nbx, nby), interpolation=cv2.INTER_LINEAR)
        ok = np.isfinite(D).astype(np.float32)
        Ds = cv2.GaussianBlur(np.where(ok > 0, D, 0).astype(np.float32), (0, 0), 1.0) / np.maximum(cv2.GaussianBlur(ok, (0, 0), 1.0), 1e-3)
        Ds[cv2.GaussianBlur(ok, (0, 0), 1.0) < 0.5] = np.nan
        return D, Ds

    alli = np.arange(len(stamps)); D, Ds = remainder(alli); De, Dse = remainder(alli[0::2]); Do, Dso = remainder(alli[1::2])
    n, lab, stats, cent = cv2.connectedComponentsWithStats((np.nan_to_num(Ds, nan=1.0) < 1 - DUST_MIN).astype(np.uint8), connectivity=8)
    corr = np.ones((nby, nbx), np.float32); found = []; turned = []
    for i in range(1, n):
        m = lab == i; area = int(m.sum()); x, y = cent[i][0] * BK + BK / 2, cent[i][1] * BK + BK / 2
        d = dict(plane_px=[round(float(x), 1), round(float(y), 1)], blocks=area, left_by_the_flat=round(float(1 - np.nanmin(Ds[m])), 4), in_even_frames=round(float(1 - np.nanmedian(Dse[m])), 4), in_odd_frames=round(float(1 - np.nanmedian(Dso[m])), 4))
        if area < DUST_MIN_BLOCKS or not (d['in_even_frames'] >= DUST_MIN_HALF and d['in_odd_frames'] >= DUST_MIN_HALF) or min(x, y, w2 - x, h2 - y) < 24:
            turned.append(d); continue
        g = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        corr[g] = np.clip(np.nan_to_num(Ds, nan=1.0)[g], 0.8, 1.0)
        near = [s_ for s_ in fj['dust']['shadows'] if np.hypot(s_['plane_px'][0] - x, s_['plane_px'][1] - y) < 40]
        d['in_the_flat_as'] = dict(plane_px=near[0]['plane_px'], depth=near[0]['depth']) if near else None
        found.append(d)
    corr_full = cv2.resize(corr, (nbx * BK, nby * BK), interpolation=cv2.INTER_LINEAR)
    CF = np.ones((h2, w2), np.float32); CF[:nby * BK, :nbx * BK] = corr_full
    if os.environ.get('M78_OWN_DUST', '1') == '1':
        USE *= CF[None]
    for d in sorted(found, key=lambda d_: -d_['left_by_the_flat']):
        print('dust left by the flat at (%4.0f, %4.0f): %.3f deep over %d blocks (even frames %.3f, odd %.3f)%s -> divided out with this run\'s own measure' % (*d['plane_px'], d['left_by_the_flat'], d['blocks'], d['in_even_frames'], d['in_odd_frames'], ', the flat has a shadow of %.3f there' % d['in_the_flat_as']['depth'] if d['in_the_flat_as'] else ', not in the flat'))
    # the flat's own fitted shadows: depth here before any flat, and what the night's flat alone left
    with np.errstate(all='ignore'):
        Sg = np.nanmedian(gcube, axis=0)
    Fn = blocks(Fg).mean(2); dust = []
    for sh in fj['dust']['shadows']:
        x, y = sh['plane_px']; r = sh['radius_plane_px']
        d = np.hypot(xx * BK + BK / 2 - x, yy * BK + BK / 2 - y); inn = d <= max(r * 0.7, BK); ring = (d > r + 12) & (d < r + 44)
        def depth(a):
            a_in, a_ring = a[inn & np.isfinite(a)], a[ring & np.isfinite(a)]
            return round(float(1 - np.median(a_in) / np.median(a_ring)), 4) if len(a_in) >= 2 and len(a_ring) >= 8 else None
        dust.append(dict(plane_px=[x, y], radius_plane_px=r, depth_in_flat=sh['depth'], depth_in_own_sky=depth(Sg), left_by_the_nights_flat=depth(Sg / Fn), left_after_own_correction=depth(Sg / Fn / corr)))
    seen = [d for d in dust if d['left_by_the_nights_flat'] is not None]
    out['dust'] = dict(what='this run\'s own green sky over the flat, over its own 160 px scale, Gaussian 1 block (8 px): a shadow the flat left is where that is below 1 - %.3f over at least %d blocks and at least %.3f deep in the even and in the odd frames alone. There the flat is multiplied by the measured remainder (bilinear from the blocks, never above 1); it is the night\'s flat everywhere else. The same factor for all four colours.' % (DUST_MIN, DUST_MIN_BLOCKS, DUST_MIN_HALF),
                       why='the night\'s flat was made from another run an hour earlier and carries its shadows shallower than they are under this run\'s sky (the_flats_fitted_shadows below: left_by_the_nights_flat); dust moves and the flat could not see under NGC 891',
                       applied=os.environ.get('M78_OWN_DUST', '1') == '1', divided_out=found, turned_down=turned, sensor_fraction_changed=float((CF < 0.999).mean()), deepest_factor=float(CF.min()),
                       the_flats_fitted_shadows=dust, worst_left_by_the_nights_flat=max([abs(d['left_by_the_nights_flat']) for d in seen] or [0.0]), worst_left_after_own_correction=max([abs(d['left_after_own_correction']) for d in seen if d['left_after_own_correction'] is not None] or [0.0]),
                       blind='within %d plane px (%.1f arcmin) of M78\'s catalogue place (and %s), in every frame\'s own place, no dust can be judged from these frames (the nebulae themselves)' % (DUST_BLIND_R, DUST_BLIND_R * 0.7772 / 60, ', '.join('%d px of %s' % (e_['dust_blind_px'], e_['name']) for e_ in S6['extra_masks'])))
    print('dust: %d shadows left by the flat divided out (%.2f%% of the sensor, deepest factor %.3f), %d candidates turned down; of the flat\'s 13 fitted shadows the worst was left %.3f deep, after this run\'s own correction %.3f' % (len(found), 100 * out['dust']['sensor_fraction_changed'], CF.min(), len(turned), out['dust']['worst_left_by_the_nights_flat'], out['dust']['worst_left_after_own_correction']))
    v2 = np.clip((np.nan_to_num(Ds, nan=0.96) - 0.96) / 0.08, 0, 1)
    cv2.imwrite(W('v_dust_left.png'), cv2.resize((v2 * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    np.save(W('flat.npy'), USE)
    out['flat_range'] = [float(USE.min()), float(USE.max())]
    jdump(out, 'step7_flat.json')
    v = np.clip((np.nan_to_num(Qshow, nan=0.96) - 0.96) / 0.08, 0, 1)
    cv2.imwrite(W('v_flat_check.png'), cv2.resize((v * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST))
    print('flat used: ' + ', '.join('%s %s' % (k, out['planes'][k]['used']) for k in PLANE_NAMES))
