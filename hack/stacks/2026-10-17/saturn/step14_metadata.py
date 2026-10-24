"""Step 14: the planet stack as FITS (~/.observatory/nights/2026-10-17-a6000/saturn/saturn-stack.fits) and
final/recipe.json in the schema observatory.recipe/1. After step 12 (the recipe) and before the clean: it reads
work/stack.npy (step 5, the linear stack), work/moons.json (step 6) and ./horizons/699.txt.

The FITS: float32, NAXIS3 = 3 (R, G, B; G the mean of G1 and G2), each plane as a fraction of the raw full scale
(white - black) times the as-shot white balance, per 1/60 s frame; on the fine grid of step 5, 3 px per sensor px
(0.1295 arcsec per px; effective pixel 3.92 / 3 um), turned back for the field's turn to 05:22:35 UTC.

What a WCS means here. Lucky imaging registers every frame on the planet, and Saturn moved about 18 arcsec against the
stars over the 1.7 hours of the 25 frames: the stars would be trails, and there are none in this 93 arcsec tile anyway.
So the WCS is Saturn-centred: it says where each pixel was on the sky for the planet at DATE-AVG (the mean of the frames'
mid-exposures). Not a plate solve, and nothing to check against catalogue stars. It is made from
  * the scale and turn of step 6's similarity fit: five moons in the 2 s frames of 05:22 against JPL Horizons, 0.07
    arcsec rms; the stack was turned back to that moment, so the same turn holds (x 3 for the fine grid);
  * CRPIX at the planet's middle in the stack (metrics.measure on green, as step 9 places it);
  * CRVAL at Saturn's Horizons position (geocentric astrometric, ICRF) at DATE-AVG. Geocentric on purpose: seen from
    the site, Saturn sat up to about 1 arcsec (8 px here) off that by the diurnal parallax, and a CRVAL moved by it
    would, with the time, give the site away (Brad's rule: nothing a processed file carries may). Said in the header.
It is checked on the rings: the ring's long axis through this WCS (Horizons' north pole position angle + 90 degrees)
against the ring line measured in the stack. WCSNAME says it is Saturn-centred."""
import json, os, sys, datetime
import numpy as np
from common import *
if TOOLS not in sys.path: sys.path.insert(0, TOOLS)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..')))
import nightmeta as nm
import obsmeta as om, stack_fits, upgrade_recipe

OBJECT = dict(name='Saturn', ids=['699 (JPL Horizons)'], title='Saturn and its moons', ra_deg=None, dec_deg=None, what='Saturn at DATE-AVG, geocentric (ICRF)')
SECTIONS = [('1-2 frames and grades', 'frames'), ('3 ephemeris (JPL Horizons)', 'ephemeris'), ('4 selection', 'selection'), ('5 stack', 'stack'), ('6 moons', 'moons'),
            ('7 Titan\'s blur', 'titan_blur'), ('8 restoration', 'restoration'), ('9 composite', 'composite'), ('10 finish', 'finish')]
OUT = os.path.join(NIGHT, 'saturn')


def history(old):
    f = old['frames']; se = old['selection']; st = old['stack']
    hm = lambda x: '%s:%s:%s' % (x[:2], x[2:4], x[4:])
    return {'1-2 frames and grades': '%d frames at %s from %s to %s UTC, each graded by sharpness and light; the moons from %s' % (f['planet'], f['exposure_planet'], hm(f['window_utc'][0]), hm(f['window_utc'][1]), f['exposure_moons']),
            '3 ephemeris (JPL Horizons)': old['ephemeris']['source'],
            '4 selection': 'the sharpest %d frames (light within %s of the median); the field turns %.4f deg per minute, every frame turned back to %.3f min UTC' % (st['keep'], se['flux_band'], se['turn_deg_per_minute'], se['reference_minute_utc']),
            '5 stack': 'each colour plane laid on a grid 3 x finer than the sensor at its own place in the 2 x 2 cell, turned back and shifted in one Lanczos resampling, mean of %d; red and blue slid onto green by least squares (%s sensor px); residual %.3f fine px rms' % (
                st['keep'], st['dispersion_native_px'], st['residual_after_fine_px_rms'] if 'residual_after_fine_px_rms' in st else st['residual_shift_after_fine_px_rms'])}


def made_of_recipe():
    import subprocess
    r = subprocess.run(['git', '-C', HERE, 'log', '--diff-filter=A', '--format=%cI', '--', 'final/recipe.json'], capture_output=True, text=True).stdout.split()
    return om.parse_time(r[-1]).isoformat(timespec='seconds') if r else None


def ctx(old):
    return dict(target=OBJECT, night=nm.NIGHT_DATE, folders=[STILLS], roots=nm.ROOTS, scripts=HERE, history=history(old), sections=SECTIONS,
                made=made_of_recipe(), made_from='this recipe had no time of its own: the time of the commit that first delivered it',
                calibration=dict(flat=dict(applied=False, why='no flat: a 93 arcsec tile on the planet; the sky is each plane\'s own median, subtracted per frame'),
                                 dark=dict(applied=False, why='none taken'), bias=dict(applied=False, why='none taken'),
                                 hot_pixels=dict(applied=False, why='the planet moves on the sensor between frames and the mean of 25 frames carries any single hot pixel at 1/25'),
                                 sensor_map=dict(applied=False, why='not used')),
                outputs=nm.outputs(HERE, FINAL, 'saturn', OUT, extra=[(os.path.join(FINAL, f), k, 'repo') for f, k in (('saturn-finished.png', 'picture_png'), ('saturn-finished.jpg', 'picture_jpg'), ('saturn-finished.json', 'finish_recipe'))]))


def horizons(t):
    """Saturn's geocentric astrometric RA, Dec (deg, ICRF), north pole position angle (deg) and distance (AU) at t,
    interpolated linearly in the 1-minute table of ./horizons/699.txt."""
    rows = []; on = False
    for line in open(os.path.join(HERE, 'horizons', '699.txt')):
        if line.startswith('$$SOE'): on = True; continue
        if line.startswith('$$EOE'): break
        if on:
            c = [x.strip() for x in line.split(',')]
            rows.append((datetime.datetime.strptime(c[0], '%Y-%b-%d %H:%M').replace(tzinfo=datetime.timezone.utc), float(c[3]), float(c[4]), float(c[8]), float(c[10])))
    for a, b in zip(rows, rows[1:]):
        if a[0] <= t <= b[0]:
            f = (t - a[0]).total_seconds() / (b[0] - a[0]).total_seconds()
            return tuple(a[k] + f * (b[k] - a[k]) for k in (1, 2, 3, 4))
    raise SystemExit('DATE-AVG outside the Horizons table')


if __name__ == '__main__':
    rp = os.path.join(FINAL, 'recipe.json'); old = json.load(open(rp))
    rec = upgrade_recipe.upgrade(old, ctx(old)) if old.get('schema') != om.RECIPE_SCHEMA else old
    sec = {x['key']: x['numbers'] for x in rec['steps'] if x.get('key')}
    frames, _ = nm.frames_of(rec, role='planet')
    assert len(frames) == 25, len(frames)
    S = np.load(W('stack.npy')); data = np.moveaxis(S, -1, 0)
    mo = jload('moons.json'); A = np.array(mo['similarity_fit']['matrix'])[:, :2]          # sensor px per arcsec (E, N), the frames of 05:22
    from metrics import measure
    m, _ = measure(S[:, :, 1]); fcx, fcy = m['centre']
    t_avg = om.weighted_mid(frames)
    ra_g, dec_g, npang, delta = horizons(t_avg)
    ra, dec = ra_g, dec_g                                                               # geocentric: see the docstring
    CD = np.linalg.inv(UP * A) / 3600.0                                                  # deg per fine px: (E, N) = CD (dx, dy)
    wcs = dict(WCSAXES=2, WCSNAME='Saturn-centred at DATE-AVG', CTYPE1='RA---TAN', CTYPE2='DEC--TAN', CUNIT1='deg', CUNIT2='deg',
               CRPIX1=float(fcx + 1), CRPIX2=float(fcy + 1), CRVAL1=ra, CRVAL2=dec, CD1_1=float(CD[0, 0]), CD1_2=float(CD[0, 1]), CD2_1=float(CD[1, 0]), CD2_2=float(CD[1, 1]))
    # the check: the ring's long axis (position angle NP.ang + 90, east of north) through the WCS, against the stack's ring line
    W2 = om.wcs_of(wcs); pa = np.radians(npang + 90.0); d = 5.0 / 3600
    p0 = W2.all_world2pix([[ra, dec]], 0)[0]; p1 = W2.all_world2pix([[ra + d * np.sin(pa) / np.cos(np.radians(dec)), dec + d * np.cos(pa)]], 0)[0]
    pred = float(np.degrees(np.arctan2(p1[1] - p0[1], p1[0] - p0[0])))
    diff = float((pred - m['ring_line_deg'] + 90) % 180 - 90)
    scale = float(np.sqrt(abs(np.linalg.det(CD))) * 3600)
    check = dict(what='Saturn-centred WCS, not a plate solve: scale and turn from five moons against JPL Horizons (step 6), CRVAL Saturn at DATE-AVG; checked on the ring\'s long axis',
                 moons_fit_rms_arcsec=round(mo['similarity_fit']['rms_arcsec'], 3), moons_matched=sum(1 for v in mo['moons'].values() if v['state'] == 'found'),
                 ring_axis_predicted_deg=round(pred, 3), ring_line_measured_deg=m['ring_line_deg'], ring_difference_deg=round(diff, 3),
                 ring_line_scatter_between_frames_deg=round(sec['selection']['ring_line_scatter_deg'], 3), arcsec_per_px=round(scale, 5), planet_centre_px=[fcx, fcy],
                 saturn_moved_over_the_frames_arcsec=None, passed=bool(abs(diff) < 1.5))
    t0, t1 = min(f['time']['start'] for f in frames), max(f['time']['end'] for f in frames)
    a0, a1 = horizons(t0), horizons(t1)
    check['saturn_moved_over_the_frames_arcsec'] = round(float(np.hypot((a1[0] - a0[0]) * np.cos(np.radians(dec)), a1[1] - a0[1]) * 3600), 2)
    if not check['passed']: raise SystemExit('the Saturn WCS does not pass the ring check: %s' % check)
    OBJECT.update(ra_deg=ra, dec_deg=dec)
    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, 'saturn-stack.fits')
    step = stack_fits.write(fp, data, frames, target=OBJECT, recipe=rec, recipe_path=om.rel(rp), exptime_s=1 / 60, livetime_s=len(frames) / 60, iso=800,
                            pixel_um=round(3.92 / UP, 5), binning=None, bunit=None, calstat=None, focal_from='from step 6 (moons against JPL Horizons)',
                            wcs=wcs, wcs_check=check,
                            extra=[('OBS UNITS', 'raw full scale x as-shot WB', 'per 1/60 s frame'),
                                   ('OBS FINE GRID', UP, 'image px per sensor px, each way'), ('OBS INTEGRATION S', round(len(frames) / 60, 4), '[s] total exposure'),
                                   ('OBS CALIBRATION', 'none', 'no dark, no flat'), ('OBS COLOUR SPACE', 'camera RGB', 'no colour matrix applied'),
                                   ('OBS TURNED TO', '2026-10-18T05:22:35', 'UTC'),
                                   ('OBS RING CHECK DEG', round(diff, 3), 'WCS - measured'),
                                   ('OBS WCS FROM', 'moons vs JPL Horizons, no solve', '')],
                            comments=['OBS UNITS: each plane is (raw - black) / (white - black) minus its median, x the as-shot white balance; there is no BUNIT for that.', 'Lucky imaging: 25 sharpest of 488 frames at 1/60 s ISO 800, registered on the planet, mean.',
                                      'Fine grid: 3 px per sensor px (XPIXSZ = 3.92 / 3 um); the arithmetic grid, not an enlargement for show.',
                                      'WCS: Saturn-centred at DATE-AVG. Saturn moved %.0f arcsec against the stars over the frames, so the WCS gives sky positions for the planet at DATE-AVG; stars would not be there.' % check['saturn_moved_over_the_frames_arcsec'],
                                      'CRVAL is geocentric (JPL Horizons): from the telescope Saturn sat up to about 1 arcsec off it (diurnal parallax), not applied.',
                                      'astropy: WCS(header, naxis=2) (the WCS is 2-D; NAXIS3 is the colour).'])
    rec = nm.add_fits_output(rec, fp, step, HERE)
    om.dump_recipe(rec, rp)
    nm.report(rec, step)
    print('  Saturn WCS: %.5f arcsec/px, ring axis %+.2f deg from the measured ring line, planet moved %.1f arcsec over the frames' % (scale, diff, check['saturn_moved_over_the_frames_arcsec']))
