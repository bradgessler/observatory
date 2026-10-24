"""The linear stack as FITS: <target>-stack.fits beside the TIF, with the standard header of docs/metadata.md (Stage 4)
and a WCS of its own, from a plate solve of the stack itself.

What it does:
  1. takes the linear stack as the pipeline made it (float64, camera RGB times the white balance, no pedestal, not
     clipped), planes first (3, h, w); the data are written as float32 (the largest change that makes is recorded)
     and otherwise untouched;
  2. if a TIF of the same stack is given, proves the FITS holds what the TIF was made from: round(data + pedestal),
     clipped to 0..65535, must equal the TIF exactly (and says how many values the TIF clipped);
  3. plate-solves the green plane with the local astrometry.net (obsmeta.solve_image: Tycho-2 indexes, SIP order 2),
     for the image as stored (top row first, ROWORDER 'TOP-DOWN');
  4. checks that WCS independently: stars found in the stack against Gaia DR3 through it (obsmeta.check_wcs), and,
     if the pipeline kept its own solve of the stack (work/solve/stack.wcs), how far the two differ over the field;
  5. writes the FITS (obsmeta.stack_cards + write_fits: CHECKSUM, DATASUM, HISTORY per recipe step, the recipe's id).
     `when` (the recipe's `made`) is DATE and the checksum comment: the same stack and recipe make the same bytes.
A stack with no stars to solve on (a planet, lucky imaging) passes its own WCS cards (wcs=...) and its own check.

Inputs: write(path, data, frames, target, recipe, ...); see write's docstring. Frames are obsmeta.read_frame records.
Outputs: the FITS file, and a dict for the recipe's step 'stack FITS' (file, sha256, wcs_header, solve, wcs_check,
TIF check, header card count).
CLI: python stack_fits.py check <file.fits>    the header, the checksums, and the WCS against Gaia again."""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obsmeta as om


def tif_matches(data, tif_path, pedestal):
    """Does the TIF equal round(data + pedestal) clipped to 0..65535, plane for plane? (TIF is h, w, 3.)"""
    import tifffile
    t = tifffile.imread(tif_path)
    re = np.clip(np.round(np.moveaxis(data.astype(np.float64), 0, -1) + pedestal), 0, 65535).astype(np.uint16)
    return dict(tif=om.rel(tif_path), tif_sha256=om.sha256_file(tif_path), pedestal=pedestal, equal=bool(np.array_equal(re, t)),
                values_clipped_high=int((np.moveaxis(data, 0, -1) + pedestal > 65535).sum()), values_clipped_low=int((np.moveaxis(data, 0, -1) + pedestal < 0).sum()))


def write(path, data, frames, *, target, recipe, recipe_path, planes='R G B', exptime_s, livetime_s, iso, pixel_um, binning, bunit='adu', bunit_comment=None,
          calstat=None, calstat_comment=None, weights=None, focal_from='from this stack\'s plate solve', solve=None, wcs=None, wcs_check=None, previous_wcs=None,
          tif=None, pedestal=None, epoch_year=None, extra=(), comments=(), gmax=16.0):
    """data: (planes, h, w) float. frames: read_frame records of the frames combined. target: {name, title, ra_deg,
    dec_deg, what}. recipe: the schema'd recipe (its id, made and steps' history go in the header). solve: kwargs for
    obsmeta.solve_image (ra_deg, dec_deg, scale_low, scale_high) to plate-solve the green plane; or wcs: the cards to
    use as they are (and wcs_check: the record of how they were checked). previous_wcs: the pipeline's own .wcs of the
    same image, to compare. tif + pedestal: the TIF made from the same array, to prove it. Returns the step record."""
    from astropy.io import fits
    data = np.asarray(data)
    assert data.ndim == 3 and np.isfinite(data).all(), (data.shape, 'non-finite values')
    step = dict(file=None)
    if tif:                                                  # on the array as the pipeline made it (float64), before float32
        step['tif_check'] = tif_matches(data, tif, pedestal)
        if not step['tif_check']['equal']: raise SystemExit('the TIF %s is not round(data + %g): this is not the array the TIF was made from' % (tif, pedestal))
    d32 = np.ascontiguousarray(data.astype(np.float32))
    step['float32_max_change'] = float(np.abs(d32.astype(np.float64) - data).max())
    data = d32
    G = data[planes.split().index('G')] if 'G' in planes.split() else data.mean(0)
    h, w = G.shape
    if solve:
        cards, info = om.solve_image(G, **solve)
        step['solve'] = info
        epoch = epoch_year or (2000.0 + (om.mjd(om.weighted_mid(frames)) - 51544.5) / 365.25)
        chk = om.check_wcs(G, cards, epoch, gmax=gmax)
        step['wcs_check'] = chk
        if not chk['passed']: raise SystemExit('the stack\'s WCS does not pass against Gaia: %s' % json.dumps(chk['all']))
        if previous_wcs and os.path.exists(previous_wcs):
            prev = {c.keyword: c.value for c in fits.getheader(previous_wcs).cards if c.keyword not in ('', 'COMMENT', 'HISTORY', 'SIMPLE', 'BITPIX', 'NAXIS', 'EXTEND', 'END')}
            step['against_the_pipelines_own_solve'] = dict(file=om.rel(previous_wcs), **om.compare_wcs(cards, prev, (h, w)))
    else:
        cards = wcs or {}
        if wcs_check: step['wcs_check'] = wcs_check
    focal = None
    if cards.get('CD1_1') is not None:
        sc = float(np.sqrt(abs(cards['CD1_1'] * cards['CD2_2'] - cards['CD1_2'] * cards['CD2_1'])) * 3600)
        focal = pixel_um * 1e-3 / (sc / 206264.806)
        step['arcsec_per_px'] = round(sc, 5)
    ex = list(extra)
    if solve:
        s = step['solve']; c = step['wcs_check']['all']
        ex += [('OBS SOLVE SOFTWARE', 'astrometry.net %s' % (s['software'] or '').replace('solve-field', '').strip(), 'plate solve of this stack'),
               ('OBS SOLVE INDEX', s.get('index'), 'the index file that solved it'), ('OBS SOLVE STARS', s['matched_stars'], 'stars matched by the solver'),
               ('OBS SOLVE RMS PX', round(s['match_rms_px'], 4), '[px] solver match rms'),
               ('OBS WCS CHECK N', c['n'], 'Gaia DR3 stars matched through the WCS'), ('OBS WCS CHECK MEDIAN PX', c['median_px'], '[px] their median residual'),
               ('OBS WCS CHECK P90 PX', c['p90_px'], '[px] 90th percentile residual')]
        ex += [('PLTSOLVD', True, 'this stack was plate solved')]
    hist = om.history_lines(recipe) + ['recipe: %s' % recipe_path, 'recipe %s' % recipe['id']]
    cards_out = om.stack_cards(frames, target=target, planes=planes, exptime_s=exptime_s, livetime_s=livetime_s, iso=iso, weights=weights, pixel_um=pixel_um, binning=binning,
                               bunit=bunit, bunit_comment=bunit_comment, calstat=calstat, calstat_comment=calstat_comment, focal_length_mm=focal, focal_from=focal_from,
                               wcs=cards, history=hist, extra=ex, recipe_id=recipe['id'], recipe_path=recipe_path, date=recipe['made'][:19], comments=comments)
    if solve:
        ra_c, de_c = om.wcs_of(cards).all_pix2world([[w / 2 - 0.5, h / 2 - 0.5]], 0)[0]
        i = [k for k, _, _ in cards_out].index('RADESYS')
        cards_out[i:i] = [('RA', float(ra_c), '[deg] centre of this image (its WCS)'), ('DEC', float(de_c), '[deg] centre of this image (its WCS)')]
    when = 'recipe made %s' % recipe['made'][:19]
    step['file'] = om.rel(path)
    step['sha256'] = om.write_fits(path, data, cards_out, when)
    step['bytes'] = os.path.getsize(path)
    step['shape'] = list(data.shape); step['dtype'] = 'float32'; step['planes'] = planes
    step['wcs_header'] = cards
    step['cards'] = len(cards_out)
    return step


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'check':
        from astropy.io import fits
        cards, ok = om.read_cards(sys.argv[2])
        for k, v, c in cards: print('%-24s %-42r %s' % (k, v, c))
        print('CHECKSUM/DATASUM', 'verify' if ok else 'DO NOT verify')
        d = fits.getdata(sys.argv[2]); hd = fits.getheader(sys.argv[2])
        wcs = {k: v for k, v, _ in cards if k[:2] in ('CR', 'CD', 'CT', 'CU', 'A_', 'B_', 'AP', 'BP', 'LO', 'LA', 'WC', 'IM') and k != 'DATE'}
        if 'CTYPE1' in wcs and 'SIP' in str(wcs['CTYPE1']):
            yr = 2000.0 + (hd['MJD-AVG'] - 51544.5) / 365.25
            print(json.dumps(om.check_wcs(d[1] if d.ndim == 3 else d, wcs, yr)['all']))
    else:
        print(__doc__)
