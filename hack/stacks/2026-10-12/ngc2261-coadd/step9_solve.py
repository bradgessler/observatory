"""Step 9: is it the thing, on the stack? Plate-solve the stack (astrometry.net, local Tycho-2 index files; solvelib.py)
and find the catalogue place in it: NGC 2261 = R Monocerotis, the star at the fan's tip (the brightest source within
40 arcsec of the catalogue place; its centroid on the stack's green and its sky position by this solution).

The stack is first cut to the well-covered rectangle (every pixel seen by at least 80% of the used frames, even size);
that rectangle is the full field. The crop for the finished picture: CROP_W x CROP_H px, centred CROP_NORTH px north of
R Monocerotis by the solution (the fan opens northwards, so the middle of the fan is the middle of the picture), moved
inside the rectangle if it would stick out, pixels untouched. 800 x 600 px (10.4 x 7.8 arcmin): the fan is about
150 px long, a fifth of the width, with sky and field stars all round; nothing enlarged."""
import json, os
import numpy as np, cv2
from common import *
from step2_stars import measure, smooth_light
import solvelib

COVER_MIN_FRACTION = 0.80
CROP_W, CROP_H = int(os.environ.get('N2261_CROP_W', '800')), int(os.environ.get('N2261_CROP_H', '600'))
CROP_NORTH = float(os.environ.get('N2261_CROP_NORTH', '60'))     # px: the picture's middle is this far north of R Monocerotis
OTHERS = []


def cover_rect(cover, nmin):
    inside = cover >= nmin
    ys, xs = np.nonzero(inside); x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    while True:
        sub = inside[y0:y1, x0:x1]
        if sub.all(): break
        fr = [(~sub[0, :]).mean(), (~sub[-1, :]).mean(), (~sub[:, 0]).mean(), (~sub[:, -1]).mean()]
        i = int(np.argmax(fr))
        if i == 0: y0 += 1
        elif i == 1: y1 -= 1
        elif i == 2: x0 += 1
        else: x1 -= 1
    x0 += x0 % 2; y0 += y0 % 2; x1 -= (x1 - x0) % 2; y1 -= (y1 - y0) % 2
    return int(x0), int(y0), int(x1), int(y1)


if __name__ == '__main__':
    st = np.load(W('stack_mean.npy')); cover = np.load(W('stack_cover.npy'))
    N = len(jload('step5_select.json')['used'])
    x0, y0, x1, y1 = cover_rect(cover, int(np.ceil(COVER_MIN_FRACTION * N)))
    print('well-covered rectangle (>= %d of %d frames): x %d..%d, y %d..%d -> %d x %d px' % (int(np.ceil(COVER_MIN_FRACTION * N)), N, x0, x1, y0, y1, x1 - x0, y1 - y0))
    G = np.nan_to_num(0.5 * (st[1, y0:y1, x0:x1] + st[2, y0:y1, x0:x1]))
    h, w = G.shape
    out = solvelib.solve(G, 'stack')
    sc = out['pixscale_arcsec']
    s6 = jload('step6_solve_ref.json')
    px, py = solvelib.place_px('stack', TARGET['ra_deg'], TARGET['dec_deg'])
    small = cv2.medianBlur(cv2.resize(G.astype(np.float32), None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5)
    def smooth_at(x, y): return round(float(small[int(np.clip(y / 8, 0, small.shape[0] - 1)), int(np.clip(x / 8, 0, small.shape[1] - 1))]), 2)
    n_ = out['north_angle_from_up_deg_clockwise']; e_ = out['east_angle_from_up_deg_clockwise']
    CROP_DX, CROP_DY = CROP_NORTH * np.sin(np.radians(n_)), -CROP_NORTH * np.cos(np.radians(n_))
    cx0 = int(np.clip(round(px + CROP_DX - CROP_W / 2), 0, w - CROP_W)); cy0 = int(np.clip(round(py + CROP_DY - CROP_H / 2), 0, h - CROP_H))
    cat = {TARGET['name']: dict(what='R Monocerotis, the catalogue position of NGC 2261', ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], pixel=[round(px, 1), round(py, 1)], inside=bool(0 <= px < w and 0 <= py < h), smooth_green_there_dn=smooth_at(px, py))}
    for o in OTHERS:
        x, y = solvelib.place_px('stack', o['ra_deg'], o['dec_deg']); ins = bool(0 <= x < w and 0 <= y < h)
        cat[o['name']] = dict(ra_deg=o['ra_deg'], dec_deg=o['dec_deg'], pixel=[round(x, 1), round(y, 1)], inside=ins, from_the_nearest_edge_px=round(float(min(x, y, w - x, h - y)), 1), from_ngc2261_arcmin=round(float(np.hypot(x - px, y - py) * sc / 60), 2),
                              smooth_green_there_dn=smooth_at(x, y) if ins else None, in_the_picture_crop=bool(cx0 <= x < cx0 + CROP_W and cy0 <= y < cy0 + CROP_H), pixel_in_the_picture=[round(x - cx0, 1), round(y - cy0, 1)])
    # R Monocerotis: the brightest compact source of the reference frame within 40 arcsec of the catalogue place, if step 2 listed one
    stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF_STAMP][0]['stars']
    D = G.astype(np.float32) - smooth_light(G.astype(np.float32)); two = []
    for s_ in sorted([s_ for s_ in stars if np.hypot(s_['x'] - x0 - px, s_['y'] - y0 - py) * sc < 40], key=lambda k: -k['flux'])[:1]:
        m = measure(D, s_['x'] - x0, s_['y'] - y0) or dict(x=s_['x'] - x0, y=s_['y'] - y0, flux=s_['flux'], hfr=s_['hfr'])
        ra, de = solvelib.xy2rd('stack', m['x'], m['y'])
        two.append(dict(pixel_in_the_stack=[round(m['x'], 1), round(m['y'], 1)], pixel_in_the_picture=[round(m['x'] - cx0, 1), round(m['y'] - cy0, 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5),
                        green_flux_dn=round(m['flux']), half_flux_diameter_arcsec=round(2 * m['hfr'] * sc, 2), touched_the_ceiling_in_the_reference_frame=s_['saturated'], from_the_catalogue_place_arcsec=round(float(np.hypot(m['x'] - px, m['y'] - py) * sc), 1)))
    if not two:      # R Monocerotis sits in its own nebula and step 2 (which keeps compact, isolated stars) did not list it: take the brightest
        # pixel of the lightly smoothed green within 40 arcsec of the catalogue place and centre on it (flux-weighted, 9 x 9 px)
        Gb = cv2.GaussianBlur(G.astype(np.float32), (0, 0), 1.5); yy, xx = np.mgrid[0:h, 0:w]; near = np.hypot(xx - px, yy - py) * sc < 40
        iy, ix = np.unravel_index(np.argmax(np.where(near, Gb, -1e9)), Gb.shape)
        t = G[iy - 4:iy + 5, ix - 4:ix + 5].astype(np.float64); t = np.clip(t - np.median(G[iy - 14:iy + 15, ix - 14:ix + 15]), 0, None); gy, gx = np.mgrid[-4:5, -4:5]
        mx, my = ix + float((t * gx).sum() / t.sum()), iy + float((t * gy).sum() / t.sum()); ra, de = solvelib.xy2rd('stack', mx, my)
        two.append(dict(pixel_in_the_stack=[round(float(mx), 1), round(float(my), 1)], pixel_in_the_picture=[round(float(mx - cx0), 1), round(float(my - cy0), 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5), peak_green_dn=round(float(G[iy, ix]), 1),
                        how='the brightest point within 40 arcsec of the catalogue place, flux-weighted centre of 9 x 9 px; not in step 2\'s star list (not compact: it sits in its own nebula)',
                        from_the_catalogue_place_arcsec=round(float(np.hypot(mx - px, my - py) * sc), 1)))
    pair = None
    out.update(crop_on_reference_grid=dict(x0=x0, y0=y0, x1=x1, y1=y1, width=w, height=h, cover_min_frames=int(np.ceil(COVER_MIN_FRACTION * N))),
               catalogue=cat, r_monocerotis=two[0] if two else None,
               nebula_crop=dict(x=cx0, y=cy0, w=CROP_W, h=CROP_H, why='the field is %.0f x %.0f arcmin and NGC 2261 about 2 arcmin long: a %d x %d px cut (%.1f x %.1f arcmin) at the stack\'s own pixels, nothing resampled' % (w * sc / 60, h * sc / 60, CROP_W, CROP_H, CROP_W * sc / 60, CROP_H * sc / 60)),
               crop_centre_north_of_r_mon_px=CROP_NORTH, catalogue_place_in_the_nebula_crop_px=[round(float(px - cx0), 1), round(float(py - cy0), 1)],
               sky_axes=dict(what='unit vectors on the picture (x right, y down) towards north and east', north=[float(np.sin(np.radians(n_))), float(-np.cos(np.radians(n_)))], east=[float(np.sin(np.radians(e_))), float(-np.cos(np.radians(e_)))]),
               agrees_with_reference_frame_solve=dict(pixscale_ref=s6['pixscale_arcsec'], north_ref=s6['north_angle_from_up_deg_clockwise']))
    bright = []
    for s_ in sorted(stars, key=lambda k: -k['flux'])[:6]:
        ra, de = solvelib.xy2rd('stack', s_['x'] - x0, s_['y'] - y0)
        bright.append(dict(pixel=[round(s_['x'] - x0, 1), round(s_['y'] - y0, 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5), green_flux_dn=round(s_['flux']), half_flux_radius_px=round(s_['hfr'], 2), touched_the_ceiling=s_['saturated'],
                           from_the_catalogue_place_arcmin=round(float(np.hypot(s_['x'] - x0 - px, s_['y'] - y0 - py) * sc / 60), 2)))
    out['brightest_sources_of_the_reference_frame'] = bright
    out['north_in_words'] = 'north is %.1f degrees clockwise from up (east %.1f): in the picture north points to the %s and east to the %s; the sky as seen, not mirrored' % (n_, e_, 'upper left' if -90 < n_ < 0 else 'upper right' if 0 <= n_ < 90 else 'lower left' if n_ <= -90 else 'lower right', 'lower left' if e_ < -90 else 'upper left' if e_ < 0 else 'upper right' if e_ < 90 else 'lower right')
    if out['mirrored']: out['north_in_words'] = out['north_in_words'].replace('the sky as seen, not mirrored', 'MIRRORED')
    jdump(out, 'step9_solve.json')
    print('solved: %.4f arcsec/px (focal length %.0f mm for 3.92 um pixels in 2 x 2 cells), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north is %.1f deg clockwise from up, east %.1f; %s' % (
        sc, out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], n_, e_, 'MIRRORED' if out['mirrored'] else 'not mirrored (the sky as seen)'))
    for k, v in cat.items(): print(' ', k, v)
    for t in two: print('  star', t)
    print('picture crop: x %d y %d, %d x %d px; NGC 2261 catalogue place at (%.1f, %.1f) in it;' % (cx0, cy0, CROP_W, CROP_H, *out['catalogue_place_in_the_nebula_crop_px']), out['north_in_words'])
    for b in bright: print('  bright source', b)
