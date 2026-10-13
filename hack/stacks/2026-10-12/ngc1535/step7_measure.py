"""Step 7: what is in the stack, in numbers, before any picture is made.

  a. Plate solve of the stack's green (local astrometry.net): scale, which way north is, where NGC 1535's catalogue
     place falls, against the centre of the nebula's own light (its central star).
  b. Star size in the stack: median half-flux diameter of its star-like sources.
  c. Did anything clip? For EVERY frame of the run, the highest raw value the camera wrote within 30 cells (23 arcsec)
     of the nebula in each colour plane, against the sensor's ceiling (16,372). Read from the RAWs, nothing repaired.
  d. Is the outer shell real? The inner disc is bright and the stars are 6 arcsec wide, so some of the disc's light is
     thrown outwards by the air and the telescope: light around the disc is not yet a shell. Three checks:
       1. the mean brightness in rings around the central star (green, blue and red alone; local sky from a ring 54 to
          78 arcsec out taken off), in the whole stack and in the odd and the even frames stacked alone;
       2. the same ring measure at blank-sky placements (no star, far from the nebula): its scatter is the noise;
       3. a model without a shell: the stack's own star profile (mean of its brightest isolated stars) as the blur,
          applied to a point (the central star) plus a uniform disc whose radius and brightness are fitted to the
          profile inside FIT_R px; what that model leaves in the shell's rings is spilled light, and only the light
          above it counts as shell.
     The verdict is written into step7_measure.json."""
import os
import numpy as np, cv2
from common import *
import solvelib
from step2_stars import measure, smooth_light

FIT_R = 11                     # px (8.5 arcsec): the bright disc's radius is about 10 arcsec
RINGS = [(0, 6), (6, 12), (12, 18), (18, 24), (24, 30), (30, 36), (36, 44), (44, 54)]     # px of the stack
SHELL = (18, 32)               # px: 14 to 25 arcsec from the central star, outside the bright disc, inside the catalogue shell
SKY_RING = (70, 100)
RMAX = 100


def ring_profile(img, c, rmax=RMAX):
    x, y = int(round(c[0])), int(round(c[1]))
    cut = img[y - rmax - 2:y + rmax + 3, x - rmax - 2:x + rmax + 3]
    yy, xx = np.mgrid[y - rmax - 2:y + rmax + 3, x - rmax - 2:x + rmax + 3]
    r = np.hypot(xx - c[0], yy - c[1])
    sky = float(np.median(cut[(r >= SKY_RING[0]) & (r < SKY_RING[1])]))
    k = np.clip(r.astype(int), 0, rmax + 5).ravel()
    s = np.bincount(k, weights=(cut - sky).ravel(), minlength=rmax + 6); n = np.bincount(k, minlength=rmax + 6)
    return (s / np.maximum(n, 1))[:rmax], n[:rmax], sky


def ring_mean(prof, n, a, b):
    return float((prof[a:b] * n[a:b]).sum() / n[a:b].sum())


if __name__ == '__main__':
    s6 = jload('step6_stack.json'); N = len(s6['frames']); T3 = jload('step3_transforms.json'); tr = {o['stamp']: o for o in T3['transforms']}
    st = {k: np.load(W('stack_%s.npy' % k)) for k in ('mean', 'odd', 'even')}; cover = np.load(W('cover.npy')); ok = cover == N
    col = lambda S: dict(G=0.5 * (S[1] + S[2]), B=S[3], R=S[0])
    G = np.where(ok, col(st['mean'])['G'], 0).astype(np.float32)
    # ---- a. plate solve of the stack
    D = G - smooth_light(G); D[~ok] = 0
    # for the solver: the stack wherever 12 or more frames cover it (the first run alone covers nearly the whole grid),
    # so that there is no blank border; everything measured below uses only the area all frames cover
    Gs = np.where(cover >= 12, np.nan_to_num(col(st['mean'])['G']), 0).astype(np.float32); Ds = Gs - smooth_light(Gs); Ds[cover < 12] = 0
    sol = solvelib.solve(cv2.GaussianBlur(Ds, (0, 0), 1.5) * 8, 'stack')
    cat = solvelib.rd2xy('stack', TARGET['ra_deg'], TARGET['dec_deg'])
    m = measure(D, *s6['nebula_px']); cen = np.array([m['x'], m['y']])
    ra_c, dec_c = solvelib.xy2rd('stack', *cen)
    sol.update(nebula_catalogue_px=list(cat), nebula_light_centre_px=cen.tolist(), nebula_light_centre_ra_dec=[ra_c, dec_c],
               light_centre_from_catalogue_arcsec=float(np.hypot(*(cen - cat)) * sol['pixscale_arcsec']), scale_arcsec_per_sensor_px=sol['pixscale_arcsec'] / 2)
    PS = sol['pixscale_arcsec']
    print('stack solved: %.4f arcsec/px (%.4f per sensor px, focal length %.0f mm); north %.1f deg clockwise from up, east %.1f; %s' % (PS, PS / 2, sol['focal_length_mm'], sol['north_angle_from_up_deg_clockwise'], sol['east_angle_from_up_deg_clockwise'], 'MIRRORED' if sol['mirrored'] else 'not mirrored'))
    print('NGC 1535 catalogue place (%.1f, %.1f); the nebula\'s light (central star) centred at (%.1f, %.1f): %.1f arcsec away' % (*cat, *cen, sol['light_centre_from_catalogue_arcsec']), flush=True)
    # ---- b. stars on the stack
    sm = cv2.GaussianBlur(D, (0, 0), 2.5); mu, sd, _ = clipped_stats(sm[ok][::7])
    n_, lab, stats, cent = cv2.connectedComponentsWithStats(((sm > mu + 8 * sd) & ok).astype(np.uint8), connectivity=8)
    stars = []
    for i in range(1, n_):
        if stats[i, cv2.CC_STAT_AREA] < 8: continue
        r = measure(D, float(cent[i][0]), float(cent[i][1]))
        if r is None or np.hypot(r['x'] - cent[i][0], r['y'] - cent[i][1]) > 8: continue
        stars.append(r)
    xy = np.array([[s['x'], s['y']] for s in stars])
    for i, s in enumerate(stars):
        d = np.hypot(*(xy - xy[i]).T); d[i] = 1e9; s['nearest'] = float(d.min()); s['from_nebula'] = float(np.hypot(*(xy[i] - cen)))
    starlike = [s for s in stars if s['flux'] > 3000 and s['from_nebula'] > 60 and s['nearest'] > 30]
    hfr_med = float(np.median([s['hfr'] for s in starlike])); starlike = [s for s in starlike if s['hfr'] < 1.4 * hfr_med]
    hfd = float(np.median([2 * s['hfr'] for s in starlike]))
    star_size = dict(stars=len(starlike), half_flux_diameter_px=hfd, half_flux_diameter_arcsec=hfd * PS, elongation_median=float(np.median([s['elong'] for s in starlike])))
    print('stars on the stack: %d found, %d star-like and isolated; half-flux diameter %.2f px = %.2f arcsec; elongation %.2f' % (len(stars), len(starlike), hfd, hfd * PS, star_size['elongation_median']), flush=True)
    # ---- c. clipping, from the RAWs
    used = set(s6['frames']); clip = []
    for f in jload('step1.json')['frames']:
        o = tr[f['stamp']]
        if o['failed']: continue
        p_ = (np.array(o['R']) @ (2 * cen + 0.5) + np.array(o['t']) - 0.5) / 2; x, y = int(round(p_[0])), int(round(p_[1]))
        P16, _ = load_raw16(f['path'])
        mx = [int(P16[p, y - 30:y + 31, x - 30:x + 31].max()) for p in range(4)]
        clip.append(dict(frame=f['name'], used=f['stamp'] in used, nebula_plane_px=[float(p_[0]), float(p_[1])], highest_raw_value=dict(zip(PLANE_NAMES, mx)), at_ceiling=bool(max(mx) >= CEILING_RAW)))
    top = {n: max(c['highest_raw_value'][n] for c in clip) for n in PLANE_NAMES}
    clipping = dict(ceiling_raw=16372, counted_as_clipped_from=CEILING_RAW, black=512, highest_raw_value_in_any_frame=top, highest_as_fraction_of_ceiling={n: (top[n] - 512) / (16372 - 512) for n in PLANE_NAMES},
                    frames_with_a_clipped_pixel=sum(c['at_ceiling'] for c in clip), per_frame=clip,
                    verdict='nothing clipped: the nebula and its central star stayed under the ceiling in every frame' if not any(c['at_ceiling'] for c in clip) else 'CLIPPED in %d frames' % sum(c['at_ceiling'] for c in clip))
    print('highest raw value within 30 cells of the nebula in any frame:', top, '=', {n: '%.1f%%' % (100 * v) for n, v in clipping['highest_as_fraction_of_ceiling'].items()}, 'of the ceiling;', clipping['verdict'], flush=True)
    # ---- d. the shell
    psf_stars = sorted([s for s in starlike if s['nearest'] > 110 and s['from_nebula'] > 200 and RMAX + 5 < s['x'] < w2 - RMAX - 5 and RMAX + 5 < s['y'] < h2 - RMAX - 5
                        and ok[int(s['y']) - RMAX:int(s['y']) + RMAX, int(s['x']) - RMAX:int(s['x']) + RMAX].all()], key=lambda s: -s['flux'])[:8]
    profs = {}
    for cname in ('G', 'B', 'R'):
        acc = np.zeros(RMAX); fl = 0.0
        for s in psf_stars:
            pr, n, _ = ring_profile(col(st['mean'])[cname], (s['x'], s['y'])); acc += pr; fl += float((pr[:60] * n[:60]).sum())
        profs[cname] = acc / fl                       # per px, for a star of total flux 1 (inside 60 px)
    # the star profile as an image, then the no-shell model: a point + a uniform disc of radius a, both blurred by it
    yy, xx = np.mgrid[-RMAX:RMAX + 1, -RMAX:RMAX + 1]; rr = np.hypot(xx, yy)
    def model_profiles(cname, a):
        psf = np.interp(rr, np.arange(RMAX) + 0.5, profs[cname], right=0.0).astype(np.float32); psf[rr > 60] = 0; psf /= psf.sum()
        disc = (rr <= a).astype(np.float32) + np.clip(a + 0.5 - rr, 0, 1) * (rr > a); disc /= disc.sum()
        blurred = cv2.filter2D(disc, -1, psf, borderType=cv2.BORDER_CONSTANT)
        k = np.clip(rr.astype(int), 0, RMAX + 5).ravel(); n = np.bincount(k, minlength=RMAX + 6)[:RMAX]
        return (np.bincount(k, weights=psf.ravel(), minlength=RMAX + 6)[:RMAX] / n, np.bincount(k, weights=blurred.ravel(), minlength=RMAX + 6)[:RMAX] / n)
    # blank-sky placements for the noise of a ring measure
    rng_pts = []
    smask = np.zeros((h2, w2), np.uint8)
    for s in stars: cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 12 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
    busy = cv2.dilate(smask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * SKY_RING[1] + 1, 2 * SKY_RING[1] + 1))) > 0
    for y in range(RMAX + 10, h2 - RMAX - 10, 70):
        for x in range(RMAX + 10, w2 - RMAX - 10, 70):
            if ok[y - RMAX - 3:y + RMAX + 4, x - RMAX - 3:x + RMAX + 4].all() and not busy[y, x] and np.hypot(x - cen[0], y - cen[1]) > 250: rng_pts.append((x, y))
    out_shell = {}
    for cname in ('G', 'B', 'R'):
        res = {}
        for half in ('mean', 'odd', 'even'):
            img = col(st[half])[cname]
            pr, n, sky = ring_profile(img, cen)
            blanks = np.array([[ring_mean(*ring_profile(img, p)[:2], a, b) for a, b in RINGS + [SHELL]] for p in rng_pts])
            sig = 1.4826 * np.median(np.abs(blanks - np.median(blanks, axis=0)), axis=0)
            res[half] = dict(profile_dn_per_px=[float(v) for v in pr[:60]], local_sky_dn=sky,
                             rings=[dict(px=[a, b], arcsec=[a * PS, b * PS], mean_dn=ring_mean(pr, n, a, b), blank_sky_sigma_dn=float(sig[i]), sigma=ring_mean(pr, n, a, b) / float(sig[i])) for i, (a, b) in enumerate(RINGS)],
                             shell=dict(px=list(SHELL), arcsec=[SHELL[0] * PS, SHELL[1] * PS], mean_dn=ring_mean(pr, n, *SHELL), blank_sky_sigma_dn=float(sig[-1]), sigma=ring_mean(pr, n, *SHELL) / float(sig[-1])))
            if half == 'mean':
                best = None
                for a in np.arange(6.0, 18.01, 0.5):
                    pp, pd = model_profiles(cname, a)
                    X = np.column_stack([pp[:FIT_R], pd[:FIT_R]]) * np.sqrt(n[:FIT_R])[:, None]; yv = pr[:FIT_R] * np.sqrt(n[:FIT_R])
                    co, *_ = np.linalg.lstsq(X, yv, rcond=None); co = np.clip(co, 0, None); chi = float(((X @ co - yv) ** 2).sum())
                    if best is None or chi < best[0]: best = (chi, float(a), co, pp, pd)
                chi, a, co, pp, pd = best; mod = co[0] * pp + co[1] * pd
                res['no_shell_model'] = dict(disc_radius_px=a, disc_radius_arcsec=a * PS, point_flux_dn=float(co[0]), disc_flux_dn=float(co[1]), fitted_inside_px=FIT_R, profile_dn_per_px=[float(v) for v in mod[:60]],
                                             rings=[dict(px=[a_, b_], model_dn=ring_mean(mod, n, a_, b_)) for a_, b_ in RINGS], shell_model_dn=ring_mean(mod, n, *SHELL))
        mdl = res['no_shell_model']['shell_model_dn']; sg = res['mean']['shell']['blank_sky_sigma_dn']
        res['shell_summary'] = dict(observed_dn=res['mean']['shell']['mean_dn'], spilled_from_the_disc_model_dn=mdl, excess_dn=res['mean']['shell']['mean_dn'] - mdl, excess_sigma=(res['mean']['shell']['mean_dn'] - mdl) / sg,
                                    odd_dn=res['odd']['shell']['mean_dn'], even_dn=res['even']['shell']['mean_dn'], odd_excess_sigma=(res['odd']['shell']['mean_dn'] - mdl) / res['odd']['shell']['blank_sky_sigma_dn'],
                                    even_excess_sigma=(res['even']['shell']['mean_dn'] - mdl) / res['even']['shell']['blank_sky_sigma_dn'], peak_dn_per_px=float(max(res['mean']['profile_dn_per_px'])))
        out_shell[cname] = res
        ss = res['shell_summary']
        print('%s: peak %.0f DN; ring %d-%d px (%.0f-%.0f"): observed %.2f DN (odd %.2f, even %.2f; blank-sky sigma %.3f); no-shell model (disc radius %.1f px = %.1f") gives %.2f; excess %.2f DN = %.1f sigma (odd %.1f, even %.1f)' % (
            cname, ss['peak_dn_per_px'], *SHELL, SHELL[0] * PS, SHELL[1] * PS, ss['observed_dn'], ss['odd_dn'], ss['even_dn'], sg, res['no_shell_model']['disc_radius_px'], res['no_shell_model']['disc_radius_arcsec'], mdl, ss['excess_dn'], ss['excess_sigma'], ss['odd_excess_sigma'], ss['even_excess_sigma']))
        for i, (a_, b_) in enumerate(RINGS):
            print('    ring %2d-%2d px (%4.1f-%4.1f"): mean %8.2f  odd %8.2f  even %8.2f  model %8.2f  blank sigma %.3f' % (a_, b_, a_ * PS, b_ * PS, res['mean']['rings'][i]['mean_dn'], res['odd']['rings'][i]['mean_dn'], res['even']['rings'][i]['mean_dn'], res['no_shell_model']['rings'][i]['model_dn'], res['mean']['rings'][i]['blank_sky_sigma_dn']))
    jdump(dict(solve=sol, star_size=star_size, clipping=clipping, psf_stars=[dict(px=[s['x'], s['y']], flux_dn=s['flux']) for s in psf_stars], blank_sky_placements=len(rng_pts),
               star_profile_per_px_for_flux_1={k: [float(v) for v in p[:60]] for k, p in profs.items()}, shell=out_shell), 'step7_measure.json')
    print('star profile from %d stars; %d blank-sky placements' % (len(psf_stars), len(rng_pts)))
