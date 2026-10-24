"""Step 16: the linear stack as FITS (OUT/m42-stack.fits, beside the TIF) and final/recipe.json in the schema
observatory.recipe/1. After step 13 (the recipe) and before the clean (it reads work/stack_linear_rgb.npy, the array
step 9 made the TIF from, and work/solve/stack.wcs).

The FITS: float32, NAXIS3 = 3 (R, G, B: camera RGB times the white balance of step 9, G the mean of G1 and G2), DN of
the 14-bit raw per 30 s long frame, no pedestal and not clipped (the TIF clips the Trapezium's core at 65535). Proven
to be the TIF's own array: round(data + 1000), clipped, equals the TIF. Its WCS is a plate solve of the stack's green
(astrometry.net, SIP order 2), checked against Gaia DR3. HISTORY: one line per step that shaped the data.
Recipe: tools/upgrade_recipe.py with this target's context (below), then the FITS added to its outputs."""
import json, os, sys
import numpy as np
from common import *
sys.path.insert(0, os.path.abspath(os.path.join(SCR, '..')))
import nightmeta as nm
import obsmeta as om, stack_fits, upgrade_recipe

OBJECT = dict(name='M 42', ids=['NGC 1976', 'M 43', 'NGC 1982'], title='the Orion Nebula, with M 43', ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'],
              what='theta1 Ori C, the Trapezium (ICRS)')


def history(old):
    s = old['summary']; c = s['combine']; j = s['join']
    dw = '; '.join('%s %d' % (k, v) for k, v in s['dropped_why'].items())
    return {'1 frames and hot pixels': '%s. Darks: %s' % (s['frames'], s['darks']),
            '3 registration': '%s; air dispersion: %s' % (s['registration'], s['air_dispersion']),
            '4 quality': 'every frame measured: star size, common ellipticity (smear), transparency on the stars, sky noise',
            '5 selection': 'dropped: %s. Weights (transparency / noise)^2' % dw,
            '6 is it the thing (reference frame plate solve)': s['is_it_the_thing'],
            '7a flatcheck on the dithered sky': 'flat: ' + s['flat'],
            '7 canvas and dust': 'dust: ' + s['dust'],
            '8 combine (proper coadd, control, short stack)': 'long: %s. Short: %s. Sky: %s' % (c['long'], c['short'], s['sky']),
            '8b join long and short': '%s; factor %.3f measured on the nebula (%.2f on stars) against %.0f expected' % (j['rule'], j['nebula_factor'], j['stars']['median_ratio'], j['expected_ratio']),
            '9 coverage, plate solve of the stack, star colours, render': 'cut to %s. Colour: %s' % (s['coverage']['picture'], s['colour'])}


def ctx(old):
    return dict(target=OBJECT, night=nm.NIGHT_DATE, folders=[STILLS], roots=nm.ROOTS, scripts=SCR, history=history(old),
                calibration=dict(flat=nm.flat_entry(FLAT_DIR, 'divided out of every frame (long and short), times this run\'s own dust measure (step 7)'),
                                 dark=dict(applied=False, why=old['summary']['darks']), bias=dict(applied=False, why='none taken'),
                                 hot_pixels=dict(applied=True, how='found from the frames themselves, one map per kind (long, short); repaired by the 3 x 3 median of their colour plane'),
                                 sensor_map=dict(applied=False, why='not used by this pipeline: the dust is measured on the run\'s own sky (step 7)')),
                outputs=nm.outputs(SCR, FINAL, NAME, OUT))


if __name__ == '__main__':
    rp = os.path.join(FINAL, 'recipe.json'); old = json.load(open(rp))
    rec = upgrade_recipe.upgrade(old, ctx(old)) if old.get('schema') != om.RECIPE_SCHEMA else old
    frames, weights = nm.frames_of(rec)
    long_ = [f for f in frames if f['time']['exposure_s'] == 30.0]; short = [f for f in frames if f['time']['exposure_s'] == 2.0]
    assert len(long_) + len(short) == len(frames), 'a used frame is neither 30 s nor 2 s'
    sm = rec['summary']; j = sm['join']
    d9 = jload('step9_deliver.json'); wb = d9['white_balance_applied']; nz = d9['noise_faint_region_dn']
    data = np.moveaxis(np.load(W('stack_linear_rgb.npy')), -1, 0)
    step = stack_fits.write(os.path.join(OUT, NAME + '-stack.fits'), data, frames, target=OBJECT, recipe=rec, recipe_path=om.rel(rp),
                            exptime_s=30.0, livetime_s=sm['integration_s'], iso=1600, weights=weights, pixel_um=7.84, binning=2,
                            bunit='adu', bunit_comment='DN of the 14-bit raw per 30 s frame, white-balanced',
                            calstat='F', calstat_comment='flat (13 Oct hybrid x own dust); no dark, no bias',
                            solve=dict(ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], scale_low=0.72, scale_high=0.84),
                            previous_wcs=W('solve/stack.wcs'), tif=os.path.join(OUT, NAME + '-stack.tif'), pedestal=1000.0,
                            extra=[('OBS NCOMBINE LONG', len(long_), '30 s ISO 1600 frames'), ('OBS NCOMBINE SHORT', len(short), '2 s ISO 400 frames'),
                                   ('OBS SHORT EXPTIME', 2.0, '[s] the short frames'), ('OBS SHORT ISOSPEED', 400, 'the short frames'),
                                   ('OBS JOIN FACTOR', j['nebula_factor'], 'short frames x this = long-frame DN'),
                                   ('OBS INTEGRATION S', sm['integration_s'], '[s] total exposure'),
                                   ('OBS COLOUR SPACE', 'camera RGB', 'no colour matrix applied'), ('OBS WB R', wb[0], 'red x this (daylight x Gaia)'), ('OBS WB B', wb[2], 'blue x this (daylight x Gaia)'),
                                   ('OBS STARS HFD ARCSEC', round(d9['star_size']['stack_arcsec'], 3), '[arcsec] half-flux diameter, green'),
                                   ('OBS NOISE R DN', round(nz['R'], 3), '[DN] faint region, red plane before WB'), ('OBS NOISE G1 DN', round(nz['G1'], 3), '[DN] faint region, G1 plane'),
                                   ('OBS NOISE G2 DN', round(nz['G2'], 3), '[DN] faint region, G2 plane'), ('OBS NOISE B DN', round(nz['B'], 3), '[DN] faint region, blue plane before WB')],
                            comments=['Linear stack: camera RGB x white balance (OBS WB R, OBS WB B), G = mean of the G1 and G2 planes.',
                                      'One pixel per 2 x 2 colour cell (XPIXSZ 7.84 um, XBINNING 2); never resampled after the stack.',
                                      'Long frames 30 s ISO 1600; the core from 2 s ISO 400 frames scaled by OBS JOIN FACTOR.',
                                      'The 16-bit TIF beside this file is round(this + 1000), clipped to 0..65535.',
                                      'astropy: WCS(header, naxis=2) (the WCS is 2-D; NAXIS3 is the colour).'])
    rec = nm.add_fits_output(rec, os.path.join(OUT, NAME + '-stack.fits'), step, SCR)
    om.dump_recipe(rec, rp)
    nm.report(rec, step)
