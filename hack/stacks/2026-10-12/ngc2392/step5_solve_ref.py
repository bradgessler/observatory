"""Step 5: is it the thing? Before anything is stacked, plate-solve the reference frame (its green planes' mean, hot
pixels repaired, on the grid of colour cells) with the local astrometry.net and find NGC 2392's catalogue position on
it. The catalogue place decides, not the brightness: the source nearest to it must be the one that is wider than a
star (a disc 20 arcsec across), and the stars around must be where the catalogue has them (the solve itself).
Writes where the nebula sits on the reference grid (the source's own centroid: the central star) for the later steps."""
import numpy as np, cv2
from common import *
import solvelib

if __name__ == '__main__':
    REF = jload('step3_transforms.json')['reference']
    P, meta = load_clean(path_of(REF))
    G = 0.5 * (P[1] + P[2])
    G = G - cv2.resize(cv2.medianBlur(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5), (w2, h2), interpolation=cv2.INTER_LINEAR)
    out = solvelib.solve(cv2.GaussianBlur(G, (0, 0), 1.5) * 8, 'ref')         # x 8: the FITS is 16-bit integers
    cx, cy = solvelib.rd2xy('ref', TARGET['ra_deg'], TARGET['dec_deg'])
    stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF][0]['stars']
    d = [float(np.hypot(s['x'] - cx, s['y'] - cy)) for s in stars]; k = int(np.argmin(d)); s = stars[k]
    med_hfr = float(np.median([t['hfr'] for t in stars if t['flux'] > 6000]))
    rank = sorted(range(len(stars)), key=lambda i: -stars[i]['flux']).index(k) + 1
    brightest = max(stars, key=lambda t: t['flux'])
    out.update(frame=REF, target=TARGET, catalogue_place_px=[cx, cy], offset_from_frame_centre_arcmin=float(np.hypot(cx - w2 / 2, cy - h2 / 2) * out['pixscale_arcsec'] / 60),
               nearest_source=dict(px=[s['x'], s['y']], sensor_px=nat(s).tolist(), from_catalogue_arcsec=d[k] * out['pixscale_arcsec'], flux_dn=s['flux'], peak_dn=s['peak'], half_flux_radius_px=s['hfr'],
                                   half_flux_diameter_arcsec=2 * s['hfr'] * out['pixscale_arcsec'], rank_by_flux=rank),
               stars_median_half_flux_radius_px=med_hfr,
               brightest_source=dict(px=[brightest['x'], brightest['y']], flux_dn=brightest['flux'], half_flux_radius_px=brightest['hfr'], from_catalogue_arcmin=float(np.hypot(brightest['x'] - cx, brightest['y'] - cy) * out['pixscale_arcsec'] / 60)))
    ok = d[k] * out['pixscale_arcsec'] < 15 and s['hfr'] > 1.5 * med_hfr
    out['verdict'] = ('NGC 2392: the source %.1f arcsec from the catalogue place is %.1f x wider than the stars (half-flux diameter %.1f arcsec against %.1f)' % (d[k] * out['pixscale_arcsec'], s['hfr'] / med_hfr, 2 * s['hfr'] * out['pixscale_arcsec'], 2 * med_hfr * out['pixscale_arcsec'])) if ok else 'NOT CONFIRMED'
    jdump(out, 'step5_solve_ref.json')
    print('reference frame %s solved: %.4f arcsec/px (focal length %.0f mm), field %.1f x %.1f arcmin, centre RA %.4f Dec %.4f; north %.1f deg clockwise from up, east %.1f; %s' % (
        REF, out['pixscale_arcsec'], out['focal_length_mm'], *out['field_arcmin'], *out['centre_ra_dec'], out['north_angle_from_up_deg_clockwise'], out['east_angle_from_up_deg_clockwise'], 'MIRRORED' if out['mirrored'] else 'not mirrored'))
    print('NGC 2392 catalogue place: pixel (%.1f, %.1f), %.1f arcmin from the frame centre' % (cx, cy, out['offset_from_frame_centre_arcmin']))
    print('nearest source: (%.1f, %.1f), %.1f arcsec away, flux %.0f DN (rank %d of %d), half-flux radius %.2f px against %.2f for the stars' % (s['x'], s['y'], d[k] * out['pixscale_arcsec'], s['flux'], rank, len(stars), s['hfr'], med_hfr))
    print('brightest source: (%.1f, %.1f), flux %.0f, half-flux radius %.2f px, %.1f arcmin from the catalogue place' % (*out['brightest_source']['px'], brightest['flux'], brightest['hfr'], out['brightest_source']['from_catalogue_arcmin']))
    print(out['verdict'])
    if not ok: raise SystemExit('the target is not confirmed')
