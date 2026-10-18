"""Step 9: is it the thing, on the stack? Plate-solve the stack (astrometry.net, local Tycho-2 index files; solvelib.py)
and find M77's catalogue position (the nucleus of NGC 1068) in it.

The stack is first cut to the well-covered rectangle (every pixel seen by at least 80% of the used frames, even size);
that rectangle is the full field that is delivered. The galaxy's ellipse (catalogue place and position angle) is
written on that rectangle's pixels, and the crop around the galaxy for the finished picture: CROP_W x CROP_H px
centred on the catalogue place (moved inside the rectangle if it would stick out), pixels untouched."""
import json, os
import numpy as np, cv2
from common import *
import solvelib

COVER_MIN_FRACTION = 0.80
CROP_W, CROP_H = int(os.environ.get('M27_CROP_W', '1200')), int(os.environ.get('M27_CROP_H', '1000'))


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
    # the light's own centre near the catalogue place: centroid above the sky of the green, blurred 2 px, within 12 px (the nucleus is star-like)
    Gs = cv2.GaussianBlur(G.astype(np.float32), (0, 0), 2.0)
    R = 12; xi, yi = int(round(px)), int(round(py)); cut = np.clip(Gs[yi - R:yi + R + 1, xi - R:xi + R + 1], 0, None)
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; cxl, cyl = xi + (cut * xx).sum() / cut.sum(), yi + (cut * yy).sum() / cut.sum()
    cx0 = int(np.clip(round(px - CROP_W / 2), 0, w - CROP_W)); cy0 = int(np.clip(round(py - CROP_H / 2), 0, h - CROP_H))
    out.update(crop_on_reference_grid=dict(x0=x0, y0=y0, x1=x1, y1=y1, width=w, height=h, cover_min_frames=int(np.ceil(COVER_MIN_FRACTION * N))),
               catalogue={TARGET['name']: dict(ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], pixel=[round(px, 1), round(py, 1)], inside=bool(0 <= px < w and 0 <= py < h),
                                               smoothed_green_there_dn=round(float(Gs[yi, xi]), 2), nucleus_centroid_within_12px=[round(float(cxl), 1), round(float(cyl), 1)],
                                               offset_arcsec=round(float(np.hypot(cxl - px, cyl - py) * out['pixscale_arcsec']), 1))},
               galaxy_ellipse_catalogue=e, galaxy_crop=dict(x=cx0, y=cy0, w=CROP_W, h=CROP_H, why='the field is 39 x 26 arcmin and the nebula\'s bright body 8 x 5.6 inside a halo about 15 across: a %d x %d px cut around the central star\'s catalogue place at the stack\'s own pixels (%.1f x %.1f arcmin), nothing resampled' % (CROP_W, CROP_H, CROP_W * out['pixscale_arcsec'] / 60, CROP_H * out['pixscale_arcsec'] / 60)),
               agrees_with_reference_frame_solve=dict(pixscale_ref=s6['pixscale_arcsec'], north_ref=s6['north_angle_from_up_deg_clockwise']))
    # the other bright things in the field, so nobody takes one of them for the galaxy: the brightest sources of the reference frame, with their sky places
    st = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF_STAMP][0]['stars']
    bright = []
    for s_ in sorted(st, key=lambda k: -k['flux'])[:5]:
        ra, de = solvelib.xy2rd('stack', s_['x'] - x0, s_['y'] - y0)
        bright.append(dict(pixel=[round(s_['x'] - x0, 1), round(s_['y'] - y0, 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5), green_flux_dn=round(s_['flux']), half_flux_radius_px=round(s_['hfr'], 2), touched_the_ceiling=s_['saturated'],
                           from_the_nucleus_arcmin=round(float(np.hypot(s_['x'] - x0 - px, s_['y'] - y0 - py) * out['pixscale_arcsec'] / 60), 2)))
    out['brightest_sources_of_the_reference_frame'] = bright
    out['nucleus_in_the_galaxy_crop_px'] = [round(float(cxl - cx0), 1), round(float(cyl - cy0), 1)]
    out['north_in_words'] = 'north is %.1f degrees clockwise from up (east %.1f): in the picture north points to the %s; the sky as seen, not mirrored' % (out['north_angle_from_up_deg_clockwise'], out['east_angle_from_up_deg_clockwise'], 'upper left' if -90 < out['north_angle_from_up_deg_clockwise'] < 0 else 'upper right' if 0 <= out['north_angle_from_up_deg_clockwise'] < 90 else 'lower left' if out['north_angle_from_up_deg_clockwise'] <= -90 else 'lower right')
    jdump(out, 'step9_solve.json')
    print('solved: %.4f arcsec/px (focal length %.0f mm for 3.92 um pixels in 2 x 2 cells), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north is %.1f deg clockwise from up, east %.1f; %s' % (
        out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], out['north_angle_from_up_deg_clockwise'], out['east_angle_from_up_deg_clockwise'], 'MIRRORED' if out['mirrored'] else 'not mirrored (the sky as seen)'))
    print('M27 catalogue place (the central star) at pixel (%.1f, %.1f); green there (2 px blur) %.1f DN above the sky; the nucleus\'s centroid is %.1f arcsec away; catalogue major axis at %.1f deg on the picture' % (px, py, Gs[yi, xi], out['catalogue'][TARGET['name']]['offset_arcsec'], e['major_axis_angle_deg']))
    print('galaxy crop: x %d y %d, %d x %d px; nucleus at (%.1f, %.1f) in it;' % (cx0, cy0, CROP_W, CROP_H, *out['nucleus_in_the_galaxy_crop_px']), out['north_in_words'])
    for b in bright: print('  bright source', b)
