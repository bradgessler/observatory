"""Step 6: is it the thing? Before anything is stacked, plate-solve the reference frame (its green planes' mean, hot
pixels repaired, on the grid of colour cells) and find M78's catalogue position on it. The brightest things in the
field are stars: the catalogue place decides, not the brightness.

Also writes the object mask on the reference grid: a circle of MASK_R arcmin on M78's catalogue place (the nebula is
8 x 6 arcmin by the catalogue, and NGC 2067, 5 arcmin north-west of it, is part of the same cloud: the circle holds
both, with margin, because a reflection nebula has no hard edge) and a circle on each other catalogued nebula in the
frame (NGC 2071, 4 arcmin; NGC 2064, 3 arcmin). Step 7 leaves the mask out of the flat's
check, step 8 out of the sky constant, step 10 out of the picture's sky plane.

The check that the catalogue place holds a nebula and not only stars: the smooth green (stars taken out by a median)
at the catalogue place against the sky's median, and the two bright stars the catalogue describes inside the glow: the
two brightest sources within 2 arcmin of the catalogue place, with their sky positions by this solution."""
import json, os, numpy as np, cv2
from common import *
import solvelib

MASK_R = float(os.environ.get('M78_MASK_R', '7.0'))   # arcmin

if __name__ == '__main__':
    P, meta = load_clean(path_of(REF_STAMP))
    G = 0.5 * (P[1] + P[2])
    out = solvelib.solve(G, 'ref')
    sc = out['pixscale_arcsec']
    e = solvelib.galaxy_ellipse('ref', sc, MASK_R, MASK_R)
    cx, cy = e['centre_px']; h, w = G.shape
    inside = bool(0 <= cx < w and 0 <= cy < h)
    extra = []
    for o in EXTRA:
        x, y = solvelib.place_px('ref', o['ra_deg'], o['dec_deg']); r = o['radius_arcmin'] * 60 / sc
        extra.append(dict(name=o['name'], dust_blind_px=o['dust_blind_px'], ra_deg=o['ra_deg'], dec_deg=o['dec_deg'], centre_px=[float(x), float(y)], radius_px=float(r), radius_arcmin=o['radius_arcmin'],
                          centre_inside_frame=bool(0 <= x < w and 0 <= y < h), circle_touches_frame=bool(-r <= x < w + r and -r <= y < h + r),
                          from_m78_arcmin=float(np.hypot(x - cx, y - cy) * sc / 60)))
    out.update(frame=REF_STAMP, target=TARGET, galaxy_ellipse=e, extra_masks=extra, mask_radius_arcmin=MASK_R)
    m = solvelib.object_mask(out, G.shape)
    small = cv2.medianBlur(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5)
    ms = cv2.resize(m.astype(np.uint8), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    sky = float(np.median(small[~ms])); sky_sd = float(1.4826 * np.median(np.abs(small[~ms] - sky)))
    at = float(small[int(np.clip(cy / 8, 0, small.shape[0] - 1)), int(np.clip(cx / 8, 0, small.shape[1] - 1))]) if inside else None
    stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF_STAMP][0]['stars']
    near = sorted([s for s in stars if np.hypot(s['x'] - cx, s['y'] - cy) * sc < 120], key=lambda s: -s['flux'])[:3]
    pair = []
    for s in near:
        ra, de = solvelib.xy2rd('ref', s['x'], s['y'])
        pair.append(dict(pixel=[round(s['x'], 1), round(s['y'], 1)], ra_deg=round(ra, 5), dec_deg=round(de, 5), green_flux_dn=round(s['flux']), from_catalogue_place_arcsec=round(float(np.hypot(s['x'] - cx, s['y'] - cy) * sc), 1), touched_the_ceiling=s['saturated']))
    out.update(target_inside_frame=inside, offset_from_frame_centre_arcmin=float(np.hypot(cx - w / 2, cy - h / 2) * sc / 60),
               smooth_green_at_catalogue_place_dn=at, green_sky_median_dn=sky, green_sky_scatter_of_64px_medians_dn=sky_sd, object_mask_fraction_of_frame=float(m.mean()),
               brightest_sources_within_2_arcmin=pair)
    jdump(out, 'step6_solve_ref.json')
    print('reference frame solved: %.4f arcsec/px (focal length %.0f mm), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north %.1f deg clockwise from up; %s' % (
        sc, out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], out['north_angle_from_up_deg_clockwise'], 'MIRRORED' if out['mirrored'] else 'not mirrored'))
    print('M78 catalogue place: pixel (%.1f, %.1f), %.1f arcmin from the frame centre, %s; smooth green there %s DN against a sky of %.1f (scatter %.2f)' % (cx, cy, out['offset_from_frame_centre_arcmin'], 'inside' if inside else 'OUTSIDE', at, sky, sky_sd))
    for x in extra: print('%s: pixel (%.0f, %.0f), %.1f arcmin from M78; centre %s the frame; its %.0f arcmin circle %s' % (x['name'], *x['centre_px'], x['from_m78_arcmin'], 'inside' if x['centre_inside_frame'] else 'OUTSIDE', x['radius_arcmin'], 'touches the frame' if x['circle_touches_frame'] else 'is clear of the frame'))
    for p_ in pair: print('  bright source near the catalogue place:', p_)
    print('object mask: %.1f%% of the frame' % (100 * m.mean()))
    # a look (kept): the reference frame's green, 4 x 4 binned, with the mask's outline
    v = cv2.resize(cv2.GaussianBlur(G, (0, 0), 3), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    v = (np.clip((v - sky + 8) / 60, 0, 1) ** 0.6 * 255).astype(np.uint8); v = cv2.cvtColor(v, cv2.COLOR_GRAY2BGR)
    cv2.circle(v, (int(cx / 4), int(cy / 4)), int(e['semi_major_px'] / 4), (0, 200, 255), 1)
    for x in extra: cv2.circle(v, (int(x['centre_px'][0] / 4), int(x['centre_px'][1] / 4)), int(x['radius_px'] / 4), (255, 200, 0), 1)
    cv2.imwrite(W('v_ref_look.png'), v)
    if not inside: raise SystemExit('the target is not in the frame')
