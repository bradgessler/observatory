"""Tests of obsmeta.py (and the FITS writing of stack_fits.py and master_fits.py) on made-up sidecars: an
observatory.still/1 frame exactly as the box writes it today, and the same frame as observatory.still/2 (the `fits`
block, `capture`, camera serial and firmware, and a `wcs` block in the solve answer) in each shape the block may take.
No RAWs are needed; nothing outside a temporary folder is written. Exit status 0 when every check passes.
Run: ~/.observatory/pyenv/bin/python test_obsmeta.py"""
import copy, json, os, sys, tempfile, warnings
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obsmeta as om

V1 = {"schema": "observatory.still/1", "seq": 12,
      "camera": {"exposure_s": 30.0, "f_number": 0.0, "focus": "manual", "id": "sony-ilce-6000", "iso": 1600, "manufacturer": "Sony Corporation", "model": "ILCE-6000", "quality": "RAW+JPEG", "shutter": "30"},
      "files": [{"bytes": 10, "camera_name": "DSC00001.ARW", "format": "arw", "name": "20261018-102251-DSC00001.ARW", "sha256": "a" * 64},
                {"bytes": 10, "camera_name": "DSC00001.JPG", "format": "jpeg", "name": "20261018-102251-DSC00001.JPG", "sha256": "b" * 64}],
      "optics": {"aperture_mm": 203, "focal_length_from": "solve", "focal_length_label_mm": 2032, "focal_length_mm": 2088.5},
      "pointing": {"alt_deg": 41.5, "az_deg": 148.5, "dec_deg": -5.6, "equinox": 2000.0, "ra_deg": 83.59, "source": "star alignment"},
      "site": {"lat": 10.25, "lon": -20.5},                         # made up
      "mount": {"id": "ttyUSB0"}, "dither": {"k": 3, "east_arcmin": 0.1, "north_arcmin": -0.2, "radius_arcmin": 1.5},
      "time": {"exposure_end": "2026-10-18T10:23:21.926956Z", "exposure_s": 30.0, "shutter_pressed": "2026-10-18T10:22:51.926956Z"}}
SOLVE1 = {"schema": "observatory.still.solve/1", "state": "solved", "picture": "20261018-102251-DSC00001",
          "solution": {"ra_deg": 83.77, "dec_deg": -5.46, "pixscale_arcsec": 1.552, "rotation_deg": 119.2, "parity": "neg", "stars": 419}}
WCS_FULL = {"WCSAXES": 2, "CTYPE1": "RA---TAN-SIP", "CTYPE2": "DEC--TAN-SIP", "CRPIX1": 3000.5, "CRPIX2": 2000.5, "CRVAL1": 83.77, "CRVAL2": -5.46,
            "CD1_1": -1e-4, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 1e-4, "IMAGEW": 6000, "IMAGEH": 4000, "A_ORDER": 2, "B_ORDER": 2}

checks = []; ok = True


def check(name, cond, detail=''):
    global ok
    checks.append(dict(check=name, passed=bool(cond), detail=str(detail))); ok &= bool(cond)
    print('%s %s %s' % ('ok  ' if cond else 'FAIL', name, detail))


def frame(td, side, solve, stem='20261018-102251-DSC00001'):
    json.dump(side, open(os.path.join(td, stem + '.json'), 'w'))
    if solve is not None: json.dump(solve, open(os.path.join(td, stem + '.solve.json'), 'w'))
    return os.path.join(td, stem + '.ARW')


def v2(shape):
    s = copy.deepcopy(V1); s['schema'] = 'observatory.still/2'
    s['camera'].update(serial='3141592', firmware='2.00')
    s['capture'] = {"target": {"name": "M 42", "id": "NGC 1976", "ra_deg": 83.82, "dec_deg": -5.39}, "purpose": "light", "plan": {"run": "r1", "step": 2, "index": 4, "of": 30}}
    cards = [["IMAGETYP", "LIGHT", "frame type"], ["OBJECT", "M 42", "target"], ["TELESCOP", "Celestron 8SE", "optical tube"], ["SITEELEV", 120.0, "[m]"],
             ["HIERARCH OBS CAMERA SERIAL", "3141592", None], ["EXPTIME", 30.0, "[s]"]]
    if shape == 'list': s['fits'] = cards
    elif shape == 'dict': s['fits'] = {k: v for k, v, _ in cards}
    elif shape == 'pairs': s['fits'] = {k: [v, c] for k, v, c in cards}
    elif shape == 'objects': s['fits'] = [{"keyword": k, "value": v, "comment": c} for k, v, c in cards]
    return s


if __name__ == '__main__':
    warnings.simplefilter('ignore')
    with tempfile.TemporaryDirectory() as td:
        # --- still/1
        p = frame(td, V1, SOLVE1); r = om.read_frame(p)
        check('v1: schema and version', r['version'] == 1 and r['schema'] == 'observatory.still/1')
        check('v1: times', om.iso_ms(r['time']['start']) == '2026-10-18T10:22:51.926' and r['time']['exposure_s'] == 30.0 and om.iso_ms(r['time']['mid']) == '2026-10-18T10:23:06.926')
        check('v1: RAW sha256 from the sidecar', r['sha256'] == 'a' * 64)
        check('v1: light by default, instrument named', r['imagetyp'] == 'LIGHT' and r['camera']['instrume'] == 'Sony ILCE-6000')
        check('v1: no wcs in a solve/1 answer', r['solve']['wcs_full'] is None and r['solve']['state'] == 'solved')
        check('v1: observing night from the site\'s solar time', r['night'] == '2026-10-17', r['night'])      # lon -20.5: 10:22 UTC is 09:00 local solar time, before noon: the night before
        c = dict((k, v) for k, v, _ in om.frame_cards(r))
        for k, v in (('DATE-OBS', '2026-10-18T10:22:51.926'), ('EXPTIME', 30.0), ('ISOSPEED', 1600), ('FOCALLEN', 2088.5), ('XPIXSZ', 3.92), ('BAYERPAT', 'RGGB'), ('TELESCOP', 'Celestron 8SE'),
                     ('RA', 83.59), ('OBS FILE RAW SHA256', 'a' * 64), ('OBS DITHER K', 3), ('PLTSOLVD', True)):
            check('v1 card %s' % k, c.get(k) == v, c.get(k))
        check('v1: no f-number 0.0 card (unknown is absent)', 'FOCRATIO' in c and all(v != 0.0 for k, v in c.items() if k.startswith('F')))
        # --- still/2 in every shape of the fits block, with a wcs block
        for shape in ('list', 'dict', 'pairs', 'objects'):
            for wshape in ('plain', 'nested', 'full_key'):
                s2 = copy.deepcopy(SOLVE1); s2['schema'] = 'observatory.still.solve/1'
                if wshape == 'plain': s2['wcs'] = dict(WCS_FULL)
                elif wshape == 'nested': s2['wcs'] = {'full': dict(WCS_FULL), 'solved': dict(WCS_FULL, IMAGEW=1500, IMAGEH=1000)}
                else: s2['wcs'] = dict(WCS_FULL, IMAGEW=1500, IMAGEH=1000); s2['wcs_full'] = dict(WCS_FULL)
                r2 = om.read_frame(frame(td, v2(shape), s2))
                good = (r2['version'] == 2 and r2['fits']['TELESCOP'][0] == 'Celestron 8SE' and r2['fits']['OBS CAMERA SERIAL'][0] == '3141592' and r2['target']['name'] == 'M 42'
                        and r2['purpose'] == 'light' and r2['plan']['of'] == 30 and r2['camera']['serial'] == '3141592' and r2['site']['elevation_m'] == 120.0
                        and r2['solve']['wcs_full']['IMAGEW'] == 6000 and (wshape == 'plain' or r2['solve']['wcs_solved']['IMAGEW'] == 1500))
                check('v2 (fits as %s, wcs %s): read' % (shape, wshape), good)
        c2 = om.frame_cards(r2); keys = [k for k, _, _ in c2]
        check('v2: the sidecar\'s own cards come first, as given, less the site', keys[:5] == ['IMAGETYP', 'OBJECT', 'TELESCOP', 'OBS CAMERA SERIAL', 'EXPTIME'], keys[:5])
        check('no card gives the site away (v1 or v2)', not any(om.LOCATION_KEYS.match(k) for k in keys + [k for k, _, _ in om.frame_cards(r)]))
        check('v2: the target\'s place from capture', dict((k, v) for k, v, _ in c2).get('OBJCTRA') == '05 35 16.80')
        check('v2: the full-size WCS in the cards', dict((k, v) for k, v, _ in c2).get('CRPIX1') == 3000.5)
        # --- still/2 as the box writes it (Controller.StillCamera.Sidecar): capture.{purpose, target, run, plan}, a fits block of
        # keyword -> value with our keys as 'OBS ...', and solve.json with wcs, wcs_full, wcs_full_of, wcs_scale. Made-up values, Lick site.
        box = copy.deepcopy(V1); box['schema'] = 'observatory.still/2'
        box['site'] = {'lat': 37.3414, 'lon': -121.6429, 'elevation_m': 1283.0}
        box['camera'].update(serial='0000001', firmware='ILCE-6000 v2.00')
        box['capture'] = {'purpose': 'light', 'target': {'id': 'NGC 1976', 'name': 'M 42', 'ra_deg': 83.8221, 'dec_deg': -5.3911, 'aim': 'the Trapezium'},
                          'run': {'id': 'run-20261018-090200', 'k': 7}, 'plan': {'run': 'plan-m42', 'step': 2, 'index': 7, 'of': 30}}
        box['fits'] = {'IMAGETYP': 'LIGHT', 'OBJECT': 'M 42', 'DATE-OBS': '2026-10-18T10:22:51.926', 'EXPTIME': 30.0, 'TELESCOP': 'Celestron 8SE',
                       'SITELAT': 37.3414, 'SITELONG': -121.6429, 'SITEELEV': 1283.0, 'CENTALT': 41.5, 'AIRMASS': 1.5123,
                       'OBS CAMERA SERIAL': '0000001', 'OBS RUN ID': 'run-20261018-090200', 'OBS RUN K': 7, 'OBS FRAME WHY': 'light'}
        bsolve = copy.deepcopy(SOLVE1)
        bsolve['wcs'] = dict(WCS_FULL, CRPIX1=750.5, CRPIX2=500.5, CD1_1=-4e-4, CD2_2=4e-4, IMAGEW=1500, IMAGEH=1000)
        bsolve['wcs_full'] = dict(WCS_FULL); bsolve['wcs_full_of'] = [6000, 4000]; bsolve['wcs_scale'] = 4.0
        rb = om.read_frame(frame(td, box, bsolve, stem='20261018-102252-DSC00002'))
        check('box v2: run and plan read from capture', rb['run'] == {'id': 'run-20261018-090200', 'k': 7} and rb['plan']['of'] == 30 and rb['plan']['run'] == 'plan-m42', (rb['run'], rb['plan']))
        check('box v2: target with its aim, purpose', rb['target'] == {'name': 'M 42', 'id': 'NGC 1976', 'ra_deg': 83.8221, 'dec_deg': -5.3911, 'aim': 'the Trapezium'} and rb['purpose'] == 'light' and rb['imagetyp'] == 'LIGHT')
        check('box v2: fits keys as given (OBS ..., no HIERARCH prefix)', rb['fits']['OBS RUN K'][0] == 7 and rb['fits']['OBS CAMERA SERIAL'][0] == '0000001' and rb['camera']['serial'] == '0000001')
        check('box v2: wcs is the solver copy, wcs_full the camera picture', rb['solve']['wcs_solved']['IMAGEW'] == 1500 and rb['solve']['wcs_full']['IMAGEW'] == 6000 and rb['solve']['wcs_full']['CRPIX1'] == 3000.5 and rb['solve']['wcs_full_of'] == [6000, 4000] and rb['solve']['wcs_scale'] == 4.0)
        cb = dict((k, v) for k, v, _ in om.frame_cards(rb))
        check('box v2: cards keep run, plan and purpose', cb.get('OBS RUN ID') == 'run-20261018-090200' and cb.get('OBS RUN K') == 7 and cb.get('OBS PLAN OF') == 30 and cb.get('OBS FRAME WHY') == 'light', {k: cb.get(k) for k in ('OBS RUN ID', 'OBS RUN K', 'OBS PLAN OF')})
        check('box v2: the site, CENTALT gone from the cards; AIRMASS to 0.1', not any(k in cb for k in ('SITELAT', 'SITELONG', 'SITEELEV', 'CENTALT')) and cb.get('AIRMASS') == 1.5, cb.get('AIRMASS'))
        check('box v2: observing night by the site\'s solar time', rb['night'] == '2026-10-17', rb['night'])
        fb = os.path.join(td, 'box.fits'); om.write_fits(fb, np.zeros((2, 2), np.float32), om.frame_cards(rb), 'w')
        hb = open(fb, 'rb').read().decode('ascii', 'replace')
        check('box v2: no site value anywhere in a written header', '37.34' not in hb and '121.64' not in hb and '1283' not in hb)
        bad = dict(V1, schema='observatory.still/9'); json.dump(bad, open(os.path.join(td, 'x.json'), 'w'))
        try: om.read_frame(os.path.join(td, 'x.json')); check('an unknown schema is refused', False)
        except ValueError: check('an unknown schema is refused', True)
        # --- a stack FITS: cards, HIERARCH split, checksum, reproducible bytes, astropy reads it, WCS with naxis=2
        frames = [om.read_frame(frame(td, V1, SOLVE1)), r2]
        rec = om.finish_recipe(dict(target=dict(name='M 42'), night=dict(date='2026-10-17'), made='2026-10-18T15:40:33+00:00', reproduce='x', roots={}, inputs=[], steps=[dict(step='1 a', history='did a')]), None)
        cards = om.stack_cards(frames, target=dict(name='M 42', ra_deg=83.82, dec_deg=-5.39), planes='R G B', exptime_s=30.0, livetime_s=60.0, iso=1600, pixel_um=7.84, binning=2,
                               wcs=WCS_FULL, history=om.history_lines(rec), recipe_id=rec['id'], recipe_path='hack/x/recipe.json', date='2026-10-18T15:40:33')
        data = np.arange(3 * 40 * 60, dtype=np.float32).reshape(3, 40, 60) / 7
        f1, f2 = os.path.join(td, 'a.fits'), os.path.join(td, 'b.fits')
        h1 = om.write_fits(f1, data, cards, 'recipe made 2026-10-18T15:40:33'); h2 = om.write_fits(f2, data, cards, 'recipe made 2026-10-18T15:40:33')
        check('the same inputs make the same bytes', h1 == h2)
        from astropy.io import fits
        cl, good = om.read_cards(f1); hd = fits.getheader(f1); d = fits.getdata(f1)
        check('CHECKSUM and DATASUM verify', good)
        check('data untouched (float32, equal)', d.dtype.kind == 'f' and d.dtype.itemsize == 4 and np.array_equal(d, data))
        check('a SHA-256 split over HIERARCH cards and joined back', om.joined(hd, 'OBS RECIPE ID') == rec['id'], om.joined(hd, 'OBS RECIPE ID'))
        check('NCOMBINE, STACKCNT, LIVETIME, IMAGETYP', hd['NCOMBINE'] == 2 and hd['STACKCNT'] == 2 and hd['LIVETIME'] == 60.0 and hd['IMAGETYP'] == 'MASTER LIGHT')
        check('DATE-OBS first, DATE-END last', hd['DATE-OBS'] == '2026-10-18T10:22:51.926' and hd['DATE-END'] == '2026-10-18T10:23:21.926')
        check('no site in a stack FITS', not any(om.LOCATION_KEYS.match(k.replace('HIERARCH ', '')) for k in hd.keys()))
        check('write_fits strips site cards whatever it is given', 'SITELAT' not in fits.getheader(f1 if om.write_fits(f1, data, cards + [('SITELAT', 10.25, ''), ('CENTALT', 41.5, ''), ('AIRMASS', 1.3456, '')], 'w') else f1)
              and fits.getheader(f1)['AIRMASS'] == 1.3)
        try: om.private_cards([('HISTORY', 'at 10.25 N', None)], (10.25, -20.5)); check('a HISTORY line naming the site is refused', False)
        except ValueError: check('a HISTORY line naming the site is refused', True)
        try: om.write_fits(os.path.join(om.REPO, 'x.fits'), data, cards, 'w'); check('no FITS into the repository', False)
        except ValueError: check('no FITS into the repository', True)
        check('HISTORY per step', any('step 1 a: did a' in str(v) for v in hd['HISTORY']))
        from astropy.wcs import WCS
        w = WCS(hd, naxis=2); check('astropy reads the WCS (naxis=2)', abs(w.all_pix2world([[3000.5, 2000.5]], 1)[0][0] - 83.77) < 1e-9)
        # --- recipes
        r_a = om.finish_recipe(dict(rec, made='2030-01-01', outputs=[dict(file='x', kind='k', sha256='0')]), None)
        check('the recipe id leaves out made and outputs', r_a['id'] == rec['id'])
        check('a recipe without problems conforms', om.check_recipe(rec) == [], om.check_recipe(rec))
        check('an absolute /Users path is scrubbed', om.scrub('/Users/someone/.observatory/nights/x') == '~/.observatory/nights/x' and om.scrub('/Users/someone/Projects/bradgessler/observatory/hack/a') == 'hack/a')
        b2 = dict(rec, inputs=[dict(name='a', night='n', sha256='s', used=True, site=dict(lat=1.0))]); b2['id'] = om.recipe_id(b2)
        check('a site field in a recipe is caught', any('site' in x for x in om.check_recipe(b2)), om.check_recipe(b2))
        # --- a master
        import master_fits
        mrec = dict(made_utc='2026-10-18T13:00:00+00:00')
        out = master_fits.write(os.path.join(td, 'm.fits'), np.ones((4, 8, 8), np.float32), 'flat', frames, mrec, 'median', norm='1 at the centre')
        mh = fits.getheader(os.path.join(td, 'm.fits'))
        check('master: IMAGETYP, NCOMBINE, EXPTIME, plane order', mh['IMAGETYP'] == 'MASTER FLAT' and mh['NCOMBINE'] == 2 and mh['EXPTIME'] == 30.0 and mh['HIERARCH OBS PLANES'] == 'R G1 G2 B')
        check('master: inputs\' sha256 in HISTORY and in its JSON', ('sha256 ' + 'a' * 64) in [str(v) for v in mh['HISTORY']] and mrec['schema'] == om.MASTER_SCHEMA and mrec['inputs'][0]['sha256'] == 'a' * 64)
    print('ALL PASSED' if ok else 'SOME CHECKS FAILED')
    sys.exit(0 if ok else 1)
