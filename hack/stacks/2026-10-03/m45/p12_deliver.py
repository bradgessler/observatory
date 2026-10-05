"""Step 12: the deliverables.

m45-mosaic.png / .jpg          the whole mosaic, north up, east left, 2 x 2 block mean of the fine grid: 1.5526 arcsec
                               per pixel (four sensor pixels). As-shot white balance. Stretch of render.py.
m45-mosaic-starwhite.png/.jpg  the same with the white reference taken from the mean of unsaturated field stars.
m45-mosaic-detail.png / .jpg   the Merope field at the sensor's own scale, 0.3881 arcsec per pixel, resampled from the
                               stacks themselves (not from the mosaic): each colour plane has one sample per 2 x 2
                               sensor pixels, so this is the half grid interpolated up by two (Lanczos-4).
m45-mosaic-detail-linear.tif   an extra: the detail field, linear, 32-bit float RGB, unsmoothed (the detail picture is smoothed a good deal).
m45-mosaic-linear.tif          the mosaic, linear, 32-bit float RGB, as-shot white balance, the grid of m45-mosaic.png,
                               not smoothed, not stretched. No data = 0 in all three colours (coverage 0).
m45-mosaic-coverage.tif        8-bit, same grid: the number of 10 s frames that went into each pixel; 0 = no data.
m45-mosaic-coverage.png        the same for the eye: grey = 9 x frames.

Pictures only (never the linear file): smoothing where the data is thin, colour pedestal, black point: render.py."""
import json, os, sys
import numpy as np, cv2, tifffile
from c import *
from render import *
import p11_combine as p11

os.makedirs(OUT, exist_ok=True)
PL = p11.PL; PS = p11.PS; X0, Y0 = p11.X0, p11.Y0
C11 = json.load(open(W('p11_combine.json'))); zero = np.array([C11['zero_dn'][c_] for c_ in 'RGB'], np.float32)
CEILING = 12000.0
MOSAIC = dict(target_noise_dn=1.0, sigma_max_px=3.0, colour_pedestal_dn=6.0, white_dn=3000.0, soft_dn=8.0, black_dn=1.2, chroma_sigma_px=4.0)
DETAIL = dict(target_noise_dn=0.8, sigma_max_px=6.0, colour_pedestal_dn=8.0, white_dn=3000.0, soft_dn=6.0, black_dn=-0.3, chroma_sigma_px=20.0)
LEVELS = (0.0, 0.4, 0.6, 0.8, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)


def save_picture(stem, img8):
    cv2.imwrite(os.path.join(OUT, stem + '.png'), img8[..., ::-1], [cv2.IMWRITE_PNG_COMPRESSION, 9])
    cv2.imwrite(os.path.join(OUT, stem + '.jpg'), img8[..., ::-1], [cv2.IMWRITE_JPEG_QUALITY, 92])


def picture(lin, noise, p, mult=(1.0, 1.0, 1.0)):
    v = lin * np.array(mult, np.float32)
    sm, sig, after = adaptive_smooth(v, noise, p['target_noise_dn'], p['sigma_max_px'], LEVELS)
    img = stretch(sm, p['colour_pedestal_dn'], p['white_dn'], p['soft_dn'], p['black_dn'], p['chroma_sigma_px'], CEILING)
    ok = np.isfinite(lin).all(2)
    return img, dict(smoothing_sigma_px=dict(none_fraction=float((sig[ok] == 0).mean()), median=float(np.median(sig[ok])), max=float(sig[ok].max())),
                     expected_noise_green_dn_after_smoothing=dict(median=float(np.nanmedian(after[ok])), p95=float(np.nanpercentile(after[ok], 95))),
                     pixels_at_255_in_all_channels=int((img.min(2) == 255).sum()), pixels_black_where_data=float((img.max(2) == 0)[ok].mean()), median_8bit_where_data=[int(np.median(img[..., c_][ok])) for c_ in range(3)])


def ap_flux(D, x, y, ap=14):
    xi, yi = int(round(x)), int(round(y)); r = 28
    h, w = D.shape
    if xi - r < 0 or yi - r < 0 or xi + r + 1 > w or yi + r + 1 > h: return np.nan
    t = D[yi - r:yi + r + 1, xi - r:xi + r + 1]
    if not np.isfinite(t).all(): return np.nan
    yy, xx = np.mgrid[yi - r:yi + r + 1, xi - r:xi + r + 1]; rr = np.hypot(xx - x, yy - y)
    lb = float(np.median(t[(rr > 19) & (rr < 27)])); a = rr <= ap
    return float((t[a] - lb).sum())


if __name__ == '__main__':
    out = {}
    mos = np.load(W('mosaic_fine.npy')); noise = np.load(W('mosaic_fine_noise.npy')); sat = np.load(W('mosaic_fine_sat.npy')); frames = np.load(W('mosaic_fine_frames.npy')); cloud = np.load(W('mosaic_fine_cloudshare.npy')); nst = np.load(W('mosaic_fine_nst.npy'))
    ok = np.isfinite(mos).all(2)
    ys, xs = np.nonzero(ok)
    fx0 = max((xs.min() - 24) // 4 * 4, 0); fy0 = max((ys.min() - 24) // 4 * 4, 0); fx1 = min(-(-(xs.max() + 25) // 4) * 4, mos.shape[1]); fy1 = min(-(-(ys.max() + 25) // 4) * 4, mos.shape[0])
    sl = (slice(fy0, fy1), slice(fx0, fx1))
    # ---------------- white reference from field stars (fine grid) ----------------
    G = mos[..., 1][sl]; okc = ok[sl]
    fill = cv2.blur(np.where(okc, G, 0).astype(np.float32), (201, 201)) / np.maximum(cv2.blur(okc.astype(np.float32), (201, 201)), 1e-3)
    Gf = np.where(okc, G, fill).astype(np.float32)
    stars, nm, zs = detect_image(Gf)
    satd = cv2.dilate(sat[sl].astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
    rows = []
    for s in stars:
        xi, yi = int(round(s['x'])), int(round(s['y']))
        if satd[yi, xi] or cloud[sl][yi, xi] > 0 or s['nearest'] / 2 < 12 or s['flux'] < 6000: continue
        f = [ap_flux(mos[..., c_][sl], s['x'], s['y']) for c_ in range(3)]
        if not np.isfinite(f).all() or f[1] <= 0: continue
        rows.append(f)
    rows = np.array(rows); rg = rows[:, 0] / rows[:, 1]; bg = rows[:, 2] / rows[:, 1]
    def cm(v):
        k = np.ones(len(v), bool)
        for _ in range(5): m, s_ = v[k].mean(), v[k].std(); k = np.abs(v - m) < 3 * s_
        return float(v[k].mean()), float(v[k].std()), int(k.sum())
    r_m, r_s, r_n = cm(rg); b_m, b_s, b_n = cm(bg)
    SW = (1.0 / r_m, 1.0, 1.0 / b_m)
    WB = PL['white_balance']
    out['colour'] = dict(as_shot_multipliers=dict(R=WB['R'], G=1.0, B=WB['B'], camera_values_over_the_used_frames=WB['raw_range']),
                         field_stars=dict(detected=len(stars), used=len(rows), min_flux_green_dn=6000.0, r_over_g_as_shot=dict(mean=r_m, std=r_s, used=r_n, median=float(np.median(rg)), ratio_of_sums=float(rows[:, 0].sum() / rows[:, 1].sum())),
                                          b_over_g_as_shot=dict(mean=b_m, std=b_s, used=b_n, median=float(np.median(bg)), ratio_of_sums=float(rows[:, 2].sum() / rows[:, 1].sum()))),
                         star_white_multipliers_on_top_of_as_shot=dict(R=SW[0], G=1.0, B=SW[2]), star_white_multipliers_on_raw=dict(R=WB['R'] * SW[0], G=1.0, B=WB['B'] * SW[2]),
                         note='stars with no pixel at the ceiling within 20 fine px, no detected neighbour within 12 px, outside the two cloud stacks, green flux of 6000 DN or more; 28 px sensor aperture on the fine grid; 3-sigma clipped mean of the per-star ratios. The mean field star comes out a little red of neutral under the as-shot balance, so the star-white picture is a little bluer than the as-shot one.')
    print('field stars: %d detected, %d used; as-shot R/G %.4f +- %.4f, B/G %.4f +- %.4f; star-white multipliers on top of as-shot: R x %.4f, B x %.4f (on raw: R x %.4f, B x %.4f)' % (len(stars), len(rows), r_m, r_s / np.sqrt(r_n), b_m, b_s / np.sqrt(b_n), SW[0], SW[2], WB['R'] * SW[0], WB['B'] * SW[2]))
    # ---------------- the mosaic on its delivered grid ----------------
    b2 = bin2(mos[sl]); n2 = np.sqrt(bin2(noise[sl] ** 2)) / 2
    h2, w2 = b2.shape[:2]
    def mx(a): return a[sl][:h2 * 2, :w2 * 2].reshape(h2, 2, w2, 2).max((1, 3))
    ok2 = np.isfinite(b2).all(2); fr2 = np.where(ok2, mx(frames), 0).astype(np.uint8); sat2 = mx(sat.astype(np.uint8)).astype(bool) & ok2; cl2 = mx(cloud); nst2 = np.where(ok2, mx(nst), 0)
    ps2 = 2 * PS; xc = (X0 - fx0 - 0.5) / 2; yc = (Y0 - fy0 - 0.5) / 2
    gridinfo = dict(size_px=[int(w2), int(h2)], pixel_scale_arcsec=ps2, field_arcmin=[w2 * ps2 / 60, h2 * ps2 / 60], mosaic_centre_at_px=[xc, yc], tangent_point_ra_dec=[RA0, DEC0],
                    orientation='north up, east left; tangent plane about RA %.2f Dec +%.2f (J2000): pixel (X, Y) is at xi = (%.2f - X) x %.4f arcsec east, eta = (%.2f - Y) x %.4f arcsec north' % (RA0, DEC0, xc, ps2, yc, ps2),
                    crop_of_fine_grid_px=[int(fx0), int(fy0), int(fx1), int(fy1)])
    img, info = picture(b2, n2, MOSAIC); save_picture('m45-mosaic', img)
    out['m45-mosaic.png / .jpg'] = dict(gridinfo, white_balance='as shot', pixels_with_data=int(ok2.sum()), fraction_of_picture_with_data=float(ok2.mean()), stretch=MOSAIC, ceiling_dn=CEILING, **info)
    img_sw, info_sw = picture(b2, n2, MOSAIC, SW); save_picture('m45-mosaic-starwhite', img_sw)
    out['m45-mosaic-starwhite.png / .jpg'] = dict(gridinfo, white_balance='star white: as shot x R %.4f, B %.4f' % (SW[0], SW[2]), stretch=MOSAIC, ceiling_dn=CEILING, **info_sw)
    lin = np.where(ok2[..., None], b2, 0).astype(np.float32)
    tifffile.imwrite(os.path.join(OUT, 'm45-mosaic-linear.tif'), lin, photometric='rgb', compression='zlib')
    tifffile.imwrite(os.path.join(OUT, 'm45-mosaic-coverage.tif'), fr2, compression='zlib')
    cv2.imwrite(os.path.join(OUT, 'm45-mosaic-coverage.png'), np.clip(fr2.astype(np.int32) * 9, 0, 255).astype(np.uint8), [cv2.IMWRITE_PNG_COMPRESSION, 9])
    okv = ok2 & (cl2 == 0)
    out['m45-mosaic-linear.tif'] = dict(gridinfo, what='the mosaic: linear, 32-bit float RGB, as-shot white balance, backgrounds of step 10 and the zero of step 11 taken off, not stretched, not smoothed',
                                        units='DN of the 14-bit RAW scale per 10 s frame at ISO 1600 under the clearest stack\'s sky, flat-fielded (R and B x the as-shot white balance)',
                                        no_data='0 in all three colours; m45-mosaic-coverage.tif is 0 there', compression='zlib, lossless',
                                        saturated='pixels that were at the sensor\'s ceiling in any frame are at or above %.0f DN in green (and higher in R and B after white balance); they are not corrected or rebuilt: %d pixels' % (15000.0, int(sat2.sum())),
                                        min_max=[float(np.nanmin(b2)), float(np.nanmax(b2))], expected_noise_green_dn_per_px=dict(median=float(np.nanmedian(n2[ok2])), best=float(np.nanmin(n2[ok2])), p95=float(np.nanpercentile(n2[ok2], 95))))
    vals, cnts = np.unique(fr2, return_counts=True)
    out['m45-mosaic-coverage.tif'] = dict(what='8-bit, the grid of m45-mosaic.png: the number of 10 s frames used at each pixel (the largest of the four fine pixels); 0 = no data', pixels_by_frames={int(v): int(c_) for v, c_ in zip(vals, cnts)},
                                          stacks_per_pixel={int(v): int(c_) for v, c_ in zip(*np.unique(nst2, return_counts=True))}, area_with_data_sq_deg=float(ok2.sum() * ps2 * ps2 / 3600 ** 2),
                                          area_from_a_cloud_stack_alone_sq_deg=float((cl2 >= 0.999).sum() * ps2 * ps2 / 3600 ** 2), area_with_any_weight_from_a_cloud_stack_sq_deg=float((cl2 > 0).sum() * ps2 * ps2 / 3600 ** 2))
    out['m45-mosaic-coverage.png'] = dict(what='the same for the eye: grey level = 9 x frames (28 frames = 252)')
    np.save(W('deliver_b2.npy'), b2); np.save(W('deliver_n2.npy'), n2); np.save(W('deliver_sat2.npy'), sat2); np.save(W('deliver_cloud2.npy'), cl2); np.save(W('deliver_frames2.npy'), fr2)
    # ---------------- named stars ----------------
    named = {}
    nlab, lab, st_, cent = cv2.connectedComponentsWithStats(sat2.astype(np.uint8), connectivity=8)
    dist_nodata = cv2.distanceTransform(np.pad(ok2, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    for nm, (ra, dec) in NAMED.items():
        xi, eta = gnomonic(ra, dec); px, py = xc - xi / ps2, yc - eta / ps2
        inside = 0 <= px < w2 and 0 <= py < h2 and bool(ok2[int(round(py)), int(round(px))])
        d = np.hypot(cent[1:, 0] - px, cent[1:, 1] - py) if nlab > 1 else np.array([1e9]); j = int(np.argmin(d))
        found = d[j] < 30
        named[nm] = dict(catalogue_ra_dec=[ra, dec], offset_arcmin_east_north=[float(xi / 60), float(eta / 60)], predicted_px=[float(px), float(py)], inside_the_mosaic=bool(inside),
                         saturated_core_found=bool(found), core_centroid_px=[float(cent[j + 1][0]), float(cent[j + 1][1])] if found else None, core_minus_catalogue_arcsec_east_north=[float(-(cent[j + 1][0] - px) * ps2), float(-(cent[j + 1][1] - py) * ps2)] if found else None,
                         core_px_at_ceiling=int(st_[j + 1, cv2.CC_STAT_AREA]) if found else 0, frames_at_the_star=int(fr2[int(round(py)), int(round(px))]) if inside else 0, stacks=[i['stack'] for i in PL['named_stars'][nm]['in_stacks']],
                         arcmin_to_the_nearest_edge_or_hole=float(dist_nodata[int(round(py)), int(round(px))] * ps2 / 60) if inside else None, cloud_stack_share=float(cl2[int(round(py)), int(round(px))]) if inside else None)
        print('%-9s predicted px (%.0f, %.0f) inside %s; saturated core %s at %s, core - catalogue %s arcsec (E, N); frames %d; %.1f arcmin to the edge; cloud share %.2f' % (nm, px, py, inside, found, np.round(cent[j + 1], 1).tolist() if found else None,
              np.round(named[nm]['core_minus_catalogue_arcsec_east_north'], 1).tolist() if found else None, named[nm]['frames_at_the_star'], named[nm]['arcmin_to_the_nearest_edge_or_hole'] or -1, named[nm]['cloud_stack_share'] or 0))
    out['named_stars'] = named
    # ---------------- holes ----------------
    nh, labh, sth, cenh = cv2.connectedComponentsWithStats((~ok2).astype(np.uint8), connectivity=4)
    border = set(np.unique(np.concatenate([labh[0], labh[-1], labh[:, 0], labh[:, -1]])).tolist())
    enclosed = [dict(centre_px=[float(cenh[i][0]), float(cenh[i][1])], offset_arcmin_east_north=[float((xc - cenh[i][0]) * ps2 / 60), float((yc - cenh[i][1]) * ps2 / 60)], area_sq_arcmin=float(sth[i, cv2.CC_STAT_AREA] * ps2 * ps2 / 3600))
                for i in range(1, nh) if i not in border and sth[i, cv2.CC_STAT_AREA] >= 4]
    # the hair's circle in each stack: is it filled by another stack?
    HAIR = json.load(open(W('p2b_hair.json'))); hair = {}
    for k in PL['images']:
        M = np.array(PL['affine_to_tangent_plane_arcsec'][k]); hc = HAIR[k]['centre_plane_px']; xi, eta = M @ np.array([hc[0], hc[1], 1.0])
        px, py = xc - xi / ps2, yc - eta / ps2; yy, xx = np.mgrid[0:h2, 0:w2]; disc = np.hypot(xx - px, yy - py) < 100 * PS / ps2
        hair[k] = dict(offset_arcmin_east_north=[float(xi / 60), float(eta / 60)], px=[float(px), float(py)], fraction_of_the_circle_filled_by_other_stacks=float(ok2[disc].mean()) if disc.any() else None, frames_in_the_circle_median=float(np.median(fr2[disc])) if disc.any() else None)
        print('hair circle of %-5s at %+6.1f E %+6.1f N: %.0f%% filled by other stacks' % (k, xi / 60, eta / 60, 100 * hair[k]['fraction_of_the_circle_filled_by_other_stacks']))
    out['holes'] = dict(enclosed_holes_without_data=enclosed, hair_circles=hair)
    print('enclosed holes without data:', enclosed)
    # ---------------- the detail: Merope at the sensor's own scale ----------------
    mer = PL['named_stars']['Merope']['fine_grid_pixel']
    dfx0 = int(round(mer[0])) - 800; dfy0 = int(round(mer[1])) - 480; dw, dh = 3200, 2400
    psd = PS / 2; x0d = 2 * (X0 - dfx0) + 0.5; y0d = 2 * (Y0 - dfy0) + 0.5
    md, wsd, satd_, frd, nstd, boxes = p11.combine(psd, x0d, y0d, dw, dh)
    md -= zero
    nd = 2 * p11.combine.noise           # the detail grid is the fine grid interpolated up by two: its pixels are not independent; this is the white-noise equivalent
    imgd, infod = picture(md, nd, DETAIL); save_picture('m45-mosaic-detail', imgd)
    xi, eta = gnomonic(*NAMED['Merope'])
    out['m45-mosaic-detail.png / .jpg'] = dict(size_px=[dw, dh], pixel_scale_arcsec=psd, field_arcmin=[dw * psd / 60, dh * psd / 60], white_balance='as shot',
                                               orientation='north up, east left; pixel (X, Y) is at xi = (%.2f - X) x %.5f arcsec east, eta = (%.2f - Y) x %.5f arcsec north of RA %.2f Dec +%.2f' % (x0d, psd, y0d, psd, RA0, DEC0),
                                               merope_catalogue_position_px=[float(x0d - xi / psd), float(y0d - eta / psd)], stacks=sorted(boxes), frames_per_pixel=dict(min=int(frd[np.isfinite(md[..., 1])].min()), median=float(np.median(frd[np.isfinite(md[..., 1])])), max=int(frd.max())),
                                               how='resampled from the stacks (half grid, 0.7763 arcsec) straight onto this grid with Lanczos-4, same backgrounds, zero and weights as the mosaic; each colour plane has one sample per 2 x 2 sensor pixels, so there is no detail finer than the half grid in it',
                                               stretch=DETAIL, ceiling_dn=CEILING, **infod)
    tifffile.imwrite(os.path.join(OUT, 'm45-mosaic-detail-linear.tif'), np.where(np.isfinite(md), md, 0).astype(np.float32), photometric='rgb', compression='zlib')
    out['m45-mosaic-detail-linear.tif'] = dict(what='an extra: the detail field, linear, 32-bit float RGB, as-shot white balance, same grid as m45-mosaic-detail.png, not smoothed, not stretched; units and no-data as m45-mosaic-linear.tif', size_px=[dw, dh], pixel_scale_arcsec=psd, compression='zlib, lossless')
    np.save(W('deliver_detail.npy'), md)
    json.dump(out, open(W('p12_deliver.json'), 'w'), indent=1)
    for k in ('m45-mosaic.png / .jpg', 'm45-mosaic-starwhite.png / .jpg', 'm45-mosaic-detail.png / .jpg'):
        print(k, out[k].get('size_px'), 'smoothing', out[k]['smoothing_sigma_px'], 'black where data %.2f' % out[k]['pixels_black_where_data'], 'white px', out[k]['pixels_at_255_in_all_channels'])
