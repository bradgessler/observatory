"""Step 6: is it the thing? Before anything is stacked, plate-solve the reference frame (its green planes' mean, hot
pixels repaired, on the grid of colour cells) and find NGC 891's catalogue position on it.

Also writes the galaxy's ellipse on the reference grid (catalogue centre and position angle 22 deg, semi-axes
MASK_SEMI arcmin: generous, about 1.3 x the catalogue length and 2.4 x its width, so that the faint outer disc and
halo are inside). Step 7 leaves that ellipse out of the sky flat, step 8 out of the sky constant.

The check that the catalogue place holds a galaxy and not a star: the smoothed green (Gaussian 6 px) at the catalogue
centre against the sky's median, and the elongation of the light around it (second moments above the sky within the
ellipse) against the catalogue's position angle."""
import os, numpy as np, cv2
from common import *
import solvelib

MASK_SEMI = (float(os.environ.get('N891_MASK_A', '8.5')), float(os.environ.get('N891_MASK_B', '3.0')))   # arcmin

if __name__ == '__main__':
    P, meta = load_clean(path_of(REF_STAMP))
    G = 0.5 * (P[1] + P[2])
    out = solvelib.solve(G, 'ref')
    e = solvelib.galaxy_ellipse('ref', out['pixscale_arcsec'], *MASK_SEMI)
    cx, cy = e['centre_px']; h, w = G.shape
    inside = bool(0 <= cx < w and 0 <= cy < h)
    Gs = cv2.GaussianBlur(G, (0, 0), 6.0)
    sky = float(np.median(Gs[::8, ::8]))
    m = solvelib.ellipse_mask(e, G.shape)
    core = solvelib.ellipse_mask(dict(e, semi_major_px=e['semi_major_px'] * 0.6, semi_minor_px=e['semi_minor_px'] * 0.35), G.shape)
    # the light above the sky inside the inner ellipse, stars taken out by a 15 px median of an 8x shrunk copy
    small = cv2.medianBlur(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5)
    sm = cv2.resize(core.astype(np.uint8), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
    v = np.clip(small - np.median(small[~cv2.resize(m.astype(np.uint8), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)]), 0, None) * sm
    yy, xx = np.mgrid[0:small.shape[0], 0:small.shape[1]]
    f = v.sum(); mx, my = (v * xx).sum() / f, (v * yy).sum() / f
    mxx, myy, mxy = (v * (xx - mx) ** 2).sum() / f, (v * (yy - my) ** 2).sum() / f, (v * (xx - mx) * (yy - my)).sum() / f
    ang = float(0.5 * np.degrees(np.arctan2(2 * mxy, mxx - myy)))
    out.update(frame=REF_STAMP, target=TARGET, galaxy_ellipse=e, mask_semi_axes_arcmin=list(MASK_SEMI), target_inside_frame=inside,
               offset_from_frame_centre_arcmin=float(np.hypot(cx - w / 2, cy - h / 2) * out['pixscale_arcsec'] / 60),
               green_at_catalogue_place_dn=float(Gs[int(round(cy)), int(round(cx))]), green_sky_median_dn=sky,
               light_centroid_px=[float(8 * mx + 3.5), float(8 * my + 3.5)], light_centroid_from_catalogue_arcsec=float(np.hypot(8 * mx + 3.5 - cx, 8 * my + 3.5 - cy) * out['pixscale_arcsec']),
               light_major_axis_angle_deg=ang, catalogue_major_axis_angle_deg=e['major_axis_angle_deg'],
               angle_difference_deg=float((ang - e['major_axis_angle_deg'] + 90) % 180 - 90))
    jdump(out, 'step6_solve_ref.json')
    print('reference frame solved: %.4f arcsec/px (focal length %.0f mm), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north %.1f deg clockwise from up; %s' % (
        out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], out['north_angle_from_up_deg_clockwise'], 'MIRRORED' if out['mirrored'] else 'not mirrored'))
    print('NGC 891 catalogue place: pixel (%.1f, %.1f), %.1f arcmin from the frame centre, %s; smoothed green there %.1f DN against a sky of %.1f' % (cx, cy, out['offset_from_frame_centre_arcmin'], 'inside' if inside else 'OUTSIDE', out['green_at_catalogue_place_dn'], sky))
    print('light above the sky in the inner ellipse: centroid %.1f arcsec from the catalogue place, long axis at %.1f deg on the picture against %.1f for the catalogue position angle (difference %.1f)' % (
        out['light_centroid_from_catalogue_arcsec'], ang, e['major_axis_angle_deg'], out['angle_difference_deg']))
    if not inside: raise SystemExit('the target is not in the frame')
