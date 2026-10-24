"""Step 16: the linear stack as FITS (OUT/m27-stack.fits, beside the TIF) and final/recipe.json in the schema
observatory.recipe/1. After step 13 (the recipe) and before the clean (it reads work/stack_linear_rgb.npy, the array
step 10 made the TIF from, and work/solve/stack.wcs).

The FITS: float32, NAXIS3 = 3 (R, G, B: camera RGB times the white balance of step 10, G the mean of G1 and G2), DN of
the 14-bit raw per 15 s frame, no pedestal. Proven to be the TIF's own array: round(data + 1000), clipped, equals the
TIF. Its WCS is a plate solve of the stack's green
(astrometry.net, SIP order 2), checked against Gaia DR3. HISTORY: one line per step that shaped the data.
Recipe: tools/upgrade_recipe.py with this target's context (below), then the FITS added to its outputs."""
import json, os, sys
import numpy as np
from common import *
sys.path.insert(0, os.path.abspath(os.path.join(SCR, '..')))
import nightmeta as nm
import obsmeta as om, stack_fits, upgrade_recipe

OBJECT = dict(name='M 27', ids=['NGC 6853'], title='the Dumbbell Nebula', ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], what='the central star of NGC 6853 (ICRS)')


def history(old):
    s = old['summary']; st = {x['step']: x['numbers'] for x in old['steps']}; r = st['2-3 stars and registration (rotation + shift on the stars)']
    return {'1 frames and hot pixels': '%s. Darks: %s' % (s['frames'], s['darks']),
            '2-3 stars and registration (rotation + shift on the stars)': 'rotation + shift on the stars onto %s, weighted rms at most %.2f px; the field turned %.3f to %.3f deg' % (r['reference'], r['wrms_px_max'], *r['rotation_deg_range']),
            '4-5 quality and selection': 'dropped: %s. Transparency %s. Weights (transparency / noise)^2' % ('; '.join('%s %s' % kv for kv in s['dropped'].items()), s['transparency']),
            '6 is it the thing (reference frame plate solve)': s['is_it_the_thing'],
            "7a candidate flats on this run's own sky (flatcheck.py)": 'flat: ' + s['flat'],
            "7 flat check and this run's own dust": 'dust: ' + s['dust'],
            '8 combine (proper coadd) and air dispersion': s['combine'],
            '9 plate solve of the stack and the crop': 'the stack plate-solved and cut to where every frame has data (origin on the reference grid in the recipe)',
            '9b star colours (Gaia DR3)': 'colour: ' + s['colour'],
            '10 deliver: TIF, stretch, sky plane in the picture only, measures': 'the linear stack = camera RGB x the white balance above; the sky plane is in the picture only, not in this stack'}


def ctx(old):
    return dict(target=OBJECT, night=nm.NIGHT_DATE, folders=[STILLS], roots=nm.ROOTS, scripts=SCR, history=history(old),
                calibration=dict(flat=nm.flat_entry(FLAT_DIR, 'divided out of every frame, times this run\'s own dust measure (step 7)'),
                                 dark=dict(applied=False, why=old['summary']['darks']), bias=dict(applied=False, why='none taken'),
                                 hot_pixels=dict(applied=True, how='found from the run itself; repaired by the 3 x 3 median of their colour plane'),
                                 sensor_map=dict(applied=False, why='not used by this pipeline: the dust is measured on the run\'s own sky (step 7)')),
                outputs=nm.outputs(SCR, FINAL, NAME, OUT))


if __name__ == '__main__':
    rp = os.path.join(FINAL, 'recipe.json'); old = json.load(open(rp))
    rec = upgrade_recipe.upgrade(old, ctx(old)) if old.get('schema') != om.RECIPE_SCHEMA else old
    frames, weights = nm.frames_of(rec)
    sm = rec['summary']
    d = jload('step10_deliver.json'); wb = d['white_balance_applied']; nz = d['noise_faint_region']['planes_stack']
    data = np.moveaxis(np.load(W('stack_linear_rgb.npy')), -1, 0)
    step = stack_fits.write(os.path.join(OUT, NAME + '-stack.fits'), data, frames, target=OBJECT, recipe=rec, recipe_path=om.rel(rp),
                            exptime_s=15.0, livetime_s=sm['integration_s'], iso=3200, weights=weights, pixel_um=7.84, binning=2,
                            bunit='adu', bunit_comment='DN of the 14-bit raw per 15 s frame, white-balanced',
                            calstat='F', calstat_comment='flat (13 Oct hybrid x own dust); no dark, no bias',
                            solve=dict(ra_deg=TARGET['ra_deg'], dec_deg=TARGET['dec_deg'], scale_low=0.72, scale_high=0.84),
                            previous_wcs=W('solve/stack.wcs'), tif=os.path.join(OUT, NAME + '-stack.tif'), pedestal=1000.0,
                            extra=[('OBS INTEGRATION S', sm['integration_s'], '[s] total exposure'),
                                   ('OBS COLOUR SPACE', 'camera RGB', 'no colour matrix applied'), ('OBS WB R', wb['R'], 'red x this (daylight x Gaia)'), ('OBS WB B', wb['B'], 'blue x this (daylight x Gaia)'),
                                   ('OBS STARS HFD ARCSEC', round(d['star_size']['hfd_stack_arcsec'], 3), '[arcsec] half-flux diameter, green'),
                                   ('OBS NOISE R DN', round(nz['R'], 3), '[DN] faint region, red plane before WB'), ('OBS NOISE G1 DN', round(nz['G1'], 3), '[DN] faint region, G1 plane'),
                                   ('OBS NOISE G2 DN', round(nz['G2'], 3), '[DN] faint region, G2 plane'), ('OBS NOISE B DN', round(nz['B'], 3), '[DN] faint region, blue plane before WB')],
                            comments=['Linear stack: camera RGB x white balance (OBS WB R, OBS WB B), G = mean of the G1 and G2 planes.',
                                      'One pixel per 2 x 2 colour cell (XPIXSZ 7.84 um, XBINNING 2); never resampled after the stack.',
                                      'The 16-bit TIF beside this file is round(this + 1000), clipped to 0..65535.',
                                      'astropy: WCS(header, naxis=2) (the WCS is 2-D; NAXIS3 is the colour).'])
    rec = nm.add_fits_output(rec, os.path.join(OUT, NAME + '-stack.fits'), step, SCR)
    om.dump_recipe(rec, rp)
    nm.report(rec, step)
