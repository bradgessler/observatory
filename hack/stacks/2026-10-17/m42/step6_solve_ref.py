"""Step 6: is it the thing? Before anything is stacked, plate-solve the reference frame (its green planes' mean, hot
pixels repaired, on the grid of colour cells; astrometry.net) and find the Trapezium's catalogue place on it (theta1
Orionis C). The check: the catalogue place is inside the frame, the smoothed green there is the brightest part of the
nebula (near the sensor's ceiling in 30 s), and the centroid of the brightest 2 percent of the smoothed light (the
Huygens region) lies within a few arcmin of it. M43's catalogue place (NU Orionis, HD 37061) is found too.
The circle written here (OBJ_R_ARCMIN round the Trapezium, as 'galaxy_ellipse', the template's name) keeps the PSF
stars, the dust search and the colour calibration off the bright core; M42's glow fills the whole frame, so there is
no open sky anywhere. Step 3 uses this solution to place every frame's own plate solve on the reference grid."""
import os, numpy as np, cv2
from common import *
import solvelib

M43 = dict(ra_deg=83.880667, dec_deg=-5.267389)              # NU Orionis (HD 37061), the star inside M43, J2000 (05h 35m 31.36s, -05d 16' 02.6")

if __name__ == '__main__':
    P, meta = load_clean(path_of(REF_STAMP))
    G = 0.5 * (P[1] + P[2])
    out = solvelib.solve(G, 'ref')
    e = solvelib.galaxy_ellipse('ref', out['pixscale_arcsec'], OBJ_R_ARCMIN, OBJ_R_ARCMIN)
    cx, cy = e['centre_px']; h, w = G.shape
    inside = bool(0 <= cx < w and 0 <= cy < h)
    small = cv2.medianBlur(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5)
    thr = np.percentile(small, 98); yy, xx = np.nonzero(small >= thr)
    lc = np.array([8 * xx.mean() + 3.5, 8 * yy.mean() + 3.5])
    m43 = solvelib.rd2xy('ref', M43['ra_deg'], M43['dec_deg'])
    Gs = cv2.GaussianBlur(G, (0, 0), 6.0)
    out.update(frame=REF_STAMP, target=TARGET, galaxy_ellipse=e, object_mask=dict(what='circle round the Trapezium', radius_arcmin=OBJ_R_ARCMIN), target_inside_frame=inside,
               offset_from_frame_centre_arcmin=float(np.hypot(cx - w / 2, cy - h / 2) * out['pixscale_arcsec'] / 60),
               green_at_catalogue_place_dn=float(Gs[int(round(cy)), int(round(cx))]), green_median_dn=float(np.median(Gs[::8, ::8])), green_p99_dn=float(np.percentile(Gs[::8, ::8], 99)),
               brightest_2pct_centroid_px=lc.tolist(), brightest_2pct_centroid_from_trapezium_arcmin=float(np.hypot(*(lc - [cx, cy])) * out['pixscale_arcsec'] / 60),
               m43_star_px=[float(m43[0]), float(m43[1])], m43_inside_frame=bool(0 <= m43[0] < w and 0 <= m43[1] < h))
    jdump(out, 'step6_solve_ref.json')
    print('reference frame %s solved: %.4f arcsec/px (focal length %.0f mm), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north %.1f deg clockwise from up; %s' % (
        REF_STAMP, out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], out['north_angle_from_up_deg_clockwise'], 'MIRRORED' if out['mirrored'] else 'not mirrored'))
    print('Trapezium (theta1 Ori C) catalogue place: pixel (%.1f, %.1f), %.1f arcmin from the frame centre, %s; smoothed green there %.0f DN (frame median %.0f, 99th percentile %.0f)' % (
        cx, cy, out['offset_from_frame_centre_arcmin'], 'inside' if inside else 'OUTSIDE', out['green_at_catalogue_place_dn'], out['green_median_dn'], out['green_p99_dn']))
    print('brightest 2%% of the smoothed light: centroid %.2f arcmin from the Trapezium; M43\'s star at (%.0f, %.0f), %s' % (out['brightest_2pct_centroid_from_trapezium_arcmin'], *m43, 'inside' if out['m43_inside_frame'] else 'outside'))
    if not inside: raise SystemExit('the target is not in the frame')
