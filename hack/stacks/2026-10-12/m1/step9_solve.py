"""Step 9: is it the thing, on the stack? Plate-solve the stack (astrometry.net, local Tycho-2 index files; solvelib.py)
and find M1's catalogue position (the Crab pulsar, at the nebula's centre) in it.

The stack is first cut to the well-covered rectangle (every pixel seen by at least 80% of the used frames, even size);
that rectangle is the full field that is delivered. The nebula's catalogue ellipse (6 x 4 arcmin, long axis at position
angle 127 deg) is written on that rectangle's pixels, and the crop around the nebula for the finished picture:
CROP_W x CROP_H px centred on the catalogue place (moved inside the rectangle if it would stick out), pixels untouched.
800 x 600 px, the size of last week's Crab picture, so the two can be laid side by side.

Where the nebula's own light is centred, its shape, and which star (if any) is the pulsar: step 11."""
import json, os
import numpy as np, cv2
from common import *
import solvelib

COVER_MIN_FRACTION = 0.80
CROP_W, CROP_H = int(os.environ.get('M1_CROP_W', '800')), int(os.environ.get('M1_CROP_H', '600'))


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
    s6 = jload('step6_solve_ref.json')
    e = solvelib.galaxy_ellipse('stack', out['pixscale_arcsec'], GALAXY_SIZE_ARCMIN[0] / 2, GALAXY_SIZE_ARCMIN[1] / 2)
    px, py = e['centre_px']
    Gs = cv2.GaussianBlur(G.astype(np.float32), (0, 0), 6.0); xi, yi = int(round(px)), int(round(py))
    cx0 = int(np.clip(round(px - CROP_W / 2), 0, w - CROP_W)); cy0 = int(np.clip(round(py - CROP_H / 2), 0, h - CROP_H))
    n_ = out['north_angle_from_up_deg_clockwise']; e_ = out['east_angle_from_up_deg_clockwise']
    out.update(crop_on_reference_grid=dict(x0=x0, y0=y0, x1=x1, y1=y1, width=w, height=h, cover_min_frames=int(np.ceil(COVER_MIN_FRACTION * N))),
               catalogue={TARGET['name']: dict(what='the Crab pulsar, the catalogue position of M1', ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], pixel=[round(px, 1), round(py, 1)], inside=bool(0 <= px < w and 0 <= py < h),
                                               smoothed_green_there_dn=round(float(Gs[yi, xi]), 2))},
               nebula_ellipse_catalogue=e, nebula_crop=dict(x=cx0, y=cy0, w=CROP_W, h=CROP_H, why='the field is %.0f x %.0f arcmin and the nebula 6 x 4: a %d x %d px cut around the catalogue place at the stack\'s own pixels (%.1f x %.1f arcmin), nothing resampled' % (w * out['pixscale_arcsec'] / 60, h * out['pixscale_arcsec'] / 60, CROP_W, CROP_H, CROP_W * out['pixscale_arcsec'] / 60, CROP_H * out['pixscale_arcsec'] / 60)),
               catalogue_place_in_the_nebula_crop_px=[round(float(px - cx0), 1), round(float(py - cy0), 1)],
               sky_axes=dict(what='unit vectors on the picture (x right, y down) towards north and east', north=[float(np.sin(np.radians(n_))), float(-np.cos(np.radians(n_)))], east=[float(np.sin(np.radians(e_))), float(-np.cos(np.radians(e_)))]),
               agrees_with_reference_frame_solve=dict(pixscale_ref=s6['pixscale_arcsec'], north_ref=s6['north_angle_from_up_deg_clockwise']))
    # the brightest sources of the reference frame, with their sky places, so nobody takes one of them for the nebula
    stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF_STAMP][0]['stars']
    bright = []
    for s_ in sorted(stars, key=lambda k: -k['flux'])[:5]:
        ra, de = solvelib.xy2rd('stack', s_['x'] - x0, s_['y'] - y0)
        bright.append(dict(pixel=[round(s_['x'] - x0, 1), round(s_['y'] - y0, 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5), green_flux_dn=round(s_['flux']), half_flux_radius_px=round(s_['hfr'], 2), touched_the_ceiling=s_['saturated'],
                           from_the_catalogue_place_arcmin=round(float(np.hypot(s_['x'] - x0 - px, s_['y'] - y0 - py) * out['pixscale_arcsec'] / 60), 2)))
    out['brightest_sources_of_the_reference_frame'] = bright
    out['north_in_words'] = 'north is %.1f degrees clockwise from up (east %.1f): in the picture north points to the %s; the sky as seen, not mirrored' % (n_, e_, 'upper left' if -90 < n_ < 0 else 'upper right' if 0 <= n_ < 90 else 'lower left' if n_ <= -90 else 'lower right')
    if out['mirrored']: out['north_in_words'] = out['north_in_words'].replace('the sky as seen, not mirrored', 'MIRRORED')
    jdump(out, 'step9_solve.json')
    print('solved: %.4f arcsec/px (focal length %.0f mm for 3.92 um pixels in 2 x 2 cells), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north is %.1f deg clockwise from up, east %.1f; %s' % (
        out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], n_, e_, 'MIRRORED' if out['mirrored'] else 'not mirrored (the sky as seen)'))
    print('M1 catalogue place (the pulsar) at pixel (%.1f, %.1f); green there (6 px blur) %.1f DN above the sky; catalogue long axis at %.1f deg on the picture' % (px, py, Gs[yi, xi], e['major_axis_angle_deg']))
    print('nebula crop: x %d y %d, %d x %d px; catalogue place at (%.1f, %.1f) in it;' % (cx0, cy0, CROP_W, CROP_H, *out['catalogue_place_in_the_nebula_crop_px']), out['north_in_words'])
    for b in bright: print('  bright source', b)
