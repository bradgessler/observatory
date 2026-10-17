"""Before and after, in numbers: the published stack against the calibrated one (same frames, same code but the flat
and the white balance), measured the same way on both linear TIFs and taken from both pipelines' own step JSONs.

  sky pattern   the TIF's green (and R, B over their white balance, back in raw DN), stars masked (rawplanes.star_mask)
                and the target's ellipse (catalogue, x 1.5 + 60 px) left out; 64 px clipped block means; a plane fitted
                (3.5 sigma, 4 rounds) and taken off: the rms and 1st to 99th percentile of what is left, in DN and in
                percent of the sky under it (step 8's median constants), and the median in rings around the target.
  dust          green, 2 x 2 px bins, over its own large scale (16 px block means, 9 x 9 median), Gaussian 4 bins,
                in the sky outside the masks: places below 1 - max(0.5%, 4 x the map noise) over at least 12 bins.
  star colours  star_colour.py on each TIF with the white balance it carries (Gaia DR3, cached): the residual of
                R/G and B/G against the catalogue, median and rms (mag), and Sun-like stars' sRGB colour.
  target        from each pipeline's step10_deliver.json (the same code): NGC 891 the disc followed along its major
                axis (odd/even rule) and the dust lane; M77 the ring medians around the nucleus, the outer ring test.
  noise         each pipeline's step10 noise in the sky region (planes, luminance).

Usage: compare_before_after.py <target> <published dir> <calibrated dir> <published TIF wb R B> <out.json>
(the TIFs are <dir>/<target>-stack.tif; the work folders <dir>/work)."""
import json, os, sys
import numpy as np, cv2, tifffile, rawpy
TOOLS = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
sys.path.insert(0, TOOLS)
import rawplanes as rp, twilight_flat as tf, star_colour
from wcs_tan import TanSip

PED = 1000.0


def jl(d, n): return json.load(open(os.path.join(d, 'work', n)))


def masks(G, e):
    h, w = G.shape
    m = rp.star_mask(G)
    yy, xx = np.mgrid[0:h, 0:w]; t = np.radians(e['major_axis_angle_deg'])
    u = (xx - e['centre_px'][0]) * np.cos(t) + (yy - e['centre_px'][1]) * np.sin(t); v = -(xx - e['centre_px'][0]) * np.sin(t) + (yy - e['centre_px'][1]) * np.cos(t)
    gal = (u / (1.5 * e['semi_major_px'] + 60)) ** 2 + (v / (1.5 * e['semi_minor_px'] + 60)) ** 2 <= 1
    return m, gal


def sky_pattern(A, mask, sky_dn, centre, bk=64):
    b = rp.block_means(A, bk, mask)
    ny, nx = b.shape; yy, xx = np.mgrid[0:ny, 0:nx]; X = xx * bk + bk / 2; Y = yy * bk + bk / 2
    ok = np.isfinite(b); z = b[ok]; Am = np.stack([np.ones(ok.sum()), (X[ok] - nx * bk / 2) / 1000, (Y[ok] - ny * bk / 2) / 1000], 1); keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(Am[keep], z[keep], rcond=None); r = z - Am @ co; s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3.5 * s
    lo, hi = np.percentile(r, [1, 99]); rr = np.hypot(X[ok] - centre[0], Y[ok] - centre[1])
    rings = []
    for a, c in ((0, 300), (300, 450), (450, 600), (600, 800), (800, 1100), (1100, 1600)):
        mm = (rr >= a) & (rr < c)
        rings.append(dict(r_px=[a, c], blocks=int(mm.sum()), median_dn=round(float(np.median(r[mm])), 3) if mm.sum() >= 3 else None))
    return dict(blocks=int(ok.sum()), plane_dn=dict(middle=float(co[0]), per_1000px_x=float(co[1]), per_1000px_y=float(co[2])),
                rms_dn=round(float(np.std(r[keep])), 3), robust_rms_dn=round(float(1.4826 * np.median(np.abs(r - np.median(r)))), 3), range_1_99_dn=[round(float(lo), 3), round(float(hi), 3)],
                rms_pct_of_sky=round(100 * float(np.std(r[keep])) / sky_dn, 3), range_1_99_pct_of_sky=[round(100 * float(lo) / sky_dn, 3), round(100 * float(hi) / sky_dn, 3)], sky_dn=round(sky_dn, 1),
                rings_around_target=rings)


def dust(G, mask, sky_dn):
    Q = np.where(mask, np.nan, G + sky_dn) / sky_dn          # relative to the sky level
    L = tf.large_scale(Q)
    R = Q / L
    h, w = R.shape
    with np.errstate(all='ignore'):
        R2 = np.nanmean(R[:h // 2 * 2, :w // 2 * 2].reshape(h // 2, 2, w // 2, 2).transpose(0, 2, 1, 3).reshape(h // 2, w // 2, 4), axis=2)
    ok = np.isfinite(R2).astype(np.float32); f = np.where(ok > 0, R2, 0).astype(np.float32)
    wgt = cv2.GaussianBlur(ok, (0, 0), 4.0); S = cv2.GaussianBlur(f, (0, 0), 4.0) / np.maximum(wgt, 1e-6); S[wgt < 0.6] = np.nan
    noise = float(1.4826 * np.nanmedian(np.abs(S - np.nanmedian(S)))); t = 1 - max(0.005, 4 * noise)
    found = tf.find_shadows(np.nan_to_num(S, nan=1.0), t, 12)
    return dict(map_noise_pct=round(100 * noise, 3), threshold=round(t, 4), shadows=len(found), deeper_than_1pct=sum(1 for s in found if s['depth'] > 0.01), deeper_than_2pct=sum(1 for s in found if s['depth'] > 0.02),
                deepest_pct=round(100 * found[0]['depth'], 2) if found else 0.0, deepest_dn=round(found[0]['depth'] * sky_dn, 2) if found else 0.0,
                area_below_threshold_pct=round(100 * float(np.nanmean(S < t)), 3), worst=found[:5])


def one(target, d, wb, raw):
    img = tifffile.imread(os.path.join(d, '%s-stack.tif' % target)).astype(np.float32) - PED
    s9 = jl(d, 'step9_solve.json'); s8 = jl(d, 'step8_stack.json'); e = s9['galaxy_ellipse_catalogue']
    C = np.median(np.array(list(s8['constants'].values())), 0); sky = [C[0], 0.5 * (C[1] + C[2]), C[3]]
    G = img[..., 1]
    m, gal = masks(G, e)
    edge = np.zeros_like(m); edge[:40] = edge[-40:] = True; edge[:, :40] = edge[:, -40:] = True
    mk = m | gal | edge
    pat = {c: sky_pattern(img[..., i] / [wb[0], 1.0, wb[2]][i], mk, sky[i], e['centre_px']) for i, c in enumerate('RGB')}
    du = dust(G, mk, sky[1])
    with rawpy.imread(raw) as r: rgb_xyz = np.array(r.rgb_xyz_matrix).tolist()
    wcs = TanSip(os.path.join(d, 'work', 'solve', 'stack.wcs')); h, w = G.shape
    ra0, dec0 = wcs.pix2world(w / 2, h / 2); radius = 0.5 * np.hypot(*s9['field_arcmin']) / 60 + 0.02
    yy, xx = np.mgrid[0:h, 0:w]; t = np.radians(e['major_axis_angle_deg'])
    u = (xx - e['centre_px'][0]) * np.cos(t) + (yy - e['centre_px'][1]) * np.sin(t); v = -(xx - e['centre_px'][0]) * np.sin(t) + (yy - e['centre_px'][1]) * np.cos(t)
    gm = (u / (1.3 * e['semi_major_px'])) ** 2 + (v / (1.3 * e['semi_minor_px'] + 30)) ** 2 <= 1
    sc = star_colour.calibrate(img, wcs, rgb_xyz, wb, (float(ra0), float(dec0)), float(radius), gm, 2026 + 285.5 / 365.25, raw_sky_dn=sky)
    col = dict(stars=sc['used'], residual_vs_catalogue=sc['residual_before'], residual_all_stars=sc['residual_all_stars_before'], sun_like=sc['sun_like_stars']['before'],
               further_factors_it_would_fit=sc['factors'], colour_term=sc['colour_term'])
    s10 = jl(d, 'step10_deliver.json')
    return dict(dir=d, white_balance=wb, sky_dn_rgb=[round(float(v), 2) for v in sky], sky_pattern_after_plane=pat, dust_left=du, star_colours=col,
                noise=s10['noise_faint_region'], galaxy=s10.get('galaxy'))


if __name__ == '__main__':
    target, before, after, wbR, wbB, out = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
    raw = sys.argv[7]
    s10a = jl(after, 'step10_deliver.json'); wa = s10a.get('white_balance_applied') or s10a['white_balance_daylight']
    res = dict(target=target, before=one(target, before, [wbR, 1.0, wbB], raw), after=one(target, after, [wa['R'], 1.0, wa['B']], raw))
    json.dump(res, open(out, 'w'), indent=1)
    for k in ('before', 'after'):
        r = res[k]; p = r['sky_pattern_after_plane']; du = r['dust_left']; sc = r['star_colours']
        print('== %s (%s)' % (k, r['dir']))
        for c in 'RGB':
            print('  sky %s: after a plane rms %.3f DN = %.2f%% of the sky (1-99%%: %.2f%%..%.2f%%); rings around the target (DN) %s' % (c, p[c]['rms_dn'], p[c]['rms_pct_of_sky'], *p[c]['range_1_99_pct_of_sky'], [x['median_dn'] for x in p[c]['rings_around_target']]))
        print('  dust left (green): %d places below %.4f (%d deeper than 1%%, %d deeper than 2%%), deepest %.2f%% = %.2f DN; map noise %.3f%%' % (du['shadows'], du['threshold'], du['deeper_than_1pct'], du['deeper_than_2pct'], du['deepest_pct'], du['deepest_dn'], du['map_noise_pct']))
        rv = sc['residual_vs_catalogue']
        print('  star colours (%d stars): R/G %+.3f mag (rms %.3f), B/G %+.3f mag (rms %.3f); Sun-like sRGB R/G %.3f B/G %.3f' % (sc['stars'], rv['median_mag_R_over_G'], rv['rms_mag_R_over_G'], rv['median_mag_B_over_G'], rv['rms_mag_B_over_G'], sc['sun_like']['median_srgb_R_over_G'], sc['sun_like']['median_srgb_B_over_G']))
        n = r['noise']; print('  noise (sky region, DN): planes %s; luminance %s' % ({a: round(b, 2) for a, b in n['planes_stack'].items()}, {a: round(b, 2) for a, b in n['luminance'].items()}))
