"""Metadata for the stacking tools: what is known about every frame, stack and master, under the standard names of
docs/metadata.md. One module, so the stacks, the masters and the recipes can never disagree on a name.

What it does:
  read_frame(path)        a frame's sidecar (<stem>.json, observatory.still/1 or /2) and its plate solve
                          (<stem>.solve.json) as ONE normalised record, whichever version wrote them.
  frame_cards(record)     the frame's FITS cards (keyword, value, comment): the sidecar's own `fits` block when it has one
                          (still/2), filled in from the record's fields by the spec's Stage 1 map otherwise (still/1).
  stack_cards(...)        the cards of a linear stack (spec Stage 4): target, NCOMBINE/STACKCNT, EXPTIME per frame,
                          LIVETIME, DATE-OBS/DATE-END/DATE-AVG and MJDs of the frames, optics, effective pixel size,
                          CALSTAT, colour, site, HISTORY per recipe step, the recipe's id.
  master_cards(...)       the cards of a calibration master (spec Stage 3): IMAGETYP 'MASTER DARK' / 'MASTER FLAT',
                          NCOMBINE, EXPTIME, ISOSPEED, dates, BAYERPAT, the inputs' names and SHA-256 as HISTORY.
  write_fits(path, data, cards, when)
                          one primary HDU, float32 data as given (no rescale), CHECKSUM/DATASUM; `when` (a fixed time)
                          goes in the checksum comment so the same inputs make the same bytes.
  solve_image(G, ...)     a plate solve of a 2-D image with the local astrometry.net (Tycho-2 indexes, SIP order 2);
                          returns its WCS cards for the image as stored (top row first) and the solver's numbers.
  check_wcs(G, cards, ...)
                          an independent check: stars found in the image against Gaia DR3 (catalogue.py, proper motion
                          to the epoch of the frames) through the WCS; residuals in px across the field.
  Recipes, schema observatory.recipe/1:
  software(), git_info()  tool versions and the repository's commit.
  rel(path), scrub(obj)   paths relative to the repository or under ~/.observatory, never /Users/...
  input_entry(record, ...), output_entry(path, kind, root)
  recipe_id(recipe)       SHA-256 of the recipe's substance (everything but id, made, git, outputs): the FITS carries it.
  finish_recipe(recipe)   adds schema, id, software and git, scrubs paths; a pipeline's last recipe step calls it.

Conventions (docs/metadata.md): UTC, ISO 8601 with milliseconds, TIMESYS 'UTC'; ICRS, EQUINOX 2000; degrees; um for
pixels, mm for optics; arrays top row first, ROWORDER 'TOP-DOWN', and any WCS is for the array as stored (FITS pixel
(i, j) = array [j - 1, i - 1]); SHA-256 lower-case hex; unknown is absent, not zero; our own values as HIERARCH OBS ...

Privacy (Brad's rule): nothing a processed file carries may give the site away. No FITS written here has SITELAT,
SITELONG, SITEELEV, OBSGEO-*, CENTALT, CENTAZ, OBJCTHA or a local time zone; AIRMASS only rounded to 0.1. write_fits
strips those cards whatever the caller passes (a still/2 sidecar's own `fits` block included), and refuses a HISTORY or
COMMENT line that names the site. Sky coordinates and UTC times are fine. A recipe (public) names the frames; the
frames' sidecars, on the box and the Mac, are the only place the site is kept. FITS files are written under
~/.observatory only, never into the repository.

Inputs: paths to sidecars, RAWs or stems (read only). Outputs: dicts, cards, FITS files where asked.
CLI:  python obsmeta.py frame <path>          the normalised record and the frame's cards
      python obsmeta.py cards <file.fits>     a FITS file's header, and whether its CHECKSUM/DATASUM verify"""
import datetime, glob, hashlib, json, os, platform, re, subprocess, sys, tempfile, warnings
import numpy as np

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path: sys.path.insert(0, TOOLS)
REPO = os.path.abspath(os.path.join(TOOLS, '..', '..', '..', '..'))
DATA = os.path.expanduser('~/.observatory')
HOME = os.path.expanduser('~')
ASTROMETRY_CFG = os.path.join(DATA, 'astrometry', 'astrometry.cfg')

RECIPE_SCHEMA = 'observatory.recipe/1'
MASTER_SCHEMA = 'observatory.master/1'
STACK_SCHEMA = 'observatory.stack/1'          # HIERARCH OBS SCHEMA of a stack FITS
SWCREATE = 'Observatory stack-pictures'

# What a still/1 sidecar does not say (docs/metadata.md, Stage 1: telescope name, observer, camera profile). A still/2
# sidecar's own `fits` block and `sensor` block win over these.
OBSERVER = 'Brad Gessler'
TELESCOPE = 'Celestron 8SE'
MOUNT = 'Sky-Watcher EQ6-R'
CAMERAS = {'sony-ilce-6000': dict(pixel_um=3.92, w_px=6024, h_px=4024, cfa='RGGB', bayer_offset=[0, 0], black_dn=512, white_dn=16000, bits=14)}
PURPOSE_IMAGETYP = dict(light='LIGHT', dark='DARK', flat='FLAT', bias='BIAS', darkflat='DARKFLAT')   # anything else: 'SNAPSHOT'


# ---------------------------------------------------------------------------------------------------- small helpers

def sha256_file(path, chunk=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(chunk), b''): h.update(b)
    return h.hexdigest()


def canonical(obj):
    """The JSON bytes a hash is taken of: sorted keys, no spaces, floats as Python writes them."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=_jdefault).encode()


def _jdefault(o):
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    if isinstance(o, (np.bool_,)): return bool(o)
    raise TypeError(type(o))


def parse_time(s):
    """ISO 8601 (Z or offset) -> aware UTC datetime."""
    if s is None: return None
    if isinstance(s, datetime.datetime): return s.astimezone(datetime.timezone.utc)
    s = str(s).strip().replace('Z', '+00:00')
    m = re.match(r'(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$', s)         # Python wants 0, 3 or 6 fraction digits
    if m and m.group(2): s = m.group(1) + (m.group(2) + '000000')[:7] + m.group(3)
    d = datetime.datetime.fromisoformat(s)
    if d.tzinfo is None: d = d.replace(tzinfo=datetime.timezone.utc)
    return d.astimezone(datetime.timezone.utc)


def iso_ms(d):
    """UTC ISO 8601 with milliseconds and no zone letter, as FITS DATE-* want it (TIMESYS = 'UTC')."""
    return d.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + '%03d' % (d.microsecond // 1000)


def mjd(d):
    """Modified Julian Date (UTC) of an aware datetime."""
    return (d - datetime.datetime(1858, 11, 17, tzinfo=datetime.timezone.utc)).total_seconds() / 86400.0


def sexagesimal(ra_deg, dec_deg):
    """('HH MM SS.ss', '+DD MM SS.s') as OBJCTRA / OBJCTDEC want them."""
    h = (ra_deg % 360.0) / 15.0; hh = int(h); mm = int((h - hh) * 60); ss = ((h - hh) * 60 - mm) * 60
    if round(ss, 2) >= 60: ss = 0; mm += 1
    if mm >= 60: mm -= 60; hh = (hh + 1) % 24
    sg = '-' if dec_deg < 0 else '+'; d = abs(dec_deg); dd = int(d); dm = int((d - dd) * 60); ds = ((d - dd) * 60 - dm) * 60
    if round(ds, 1) >= 60: ds = 0; dm += 1
    if dm >= 60: dm -= 60; dd += 1
    return '%02d %02d %05.2f' % (hh, mm, ss), '%s%02d %02d %04.1f' % (sg, dd, dm, ds)


def _get(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d: return default
        d = d[p]
    return d


# ---------------------------------------------------------------------------------------------------- frames

def _stem(path):
    p = os.path.abspath(os.path.expanduser(path))
    for ext in ('.solve.json', '.json', '.ARW', '.arw', '.JPG', '.jpg', '.fits'):
        if p.endswith(ext): return p[:-len(ext)]
    return p


def _fits_block(b):
    """A `fits` block in any of the shapes a sidecar may use -> {KEYWORD: (value, comment)} in order. Shapes:
    {"EXPTIME": 30.0}, {"EXPTIME": [30.0, "s"]}, {"EXPTIME": {"value": 30.0, "comment": "s"}},
    [["EXPTIME", 30.0, "s"], ...], [{"keyword": "EXPTIME", "value": 30.0, "comment": "s"}, ...].
    A leading 'HIERARCH ' is dropped from the keyword (write_fits puts it back where it is needed)."""
    out = {}
    if not b: return out
    items = []
    if isinstance(b, dict):
        for k, v in b.items():
            if isinstance(v, dict): items.append((k, v.get('value'), v.get('comment')))
            elif isinstance(v, (list, tuple)): items.append((k, v[0] if v else None, v[1] if len(v) > 1 else None))
            else: items.append((k, v, None))
    else:
        for v in b:
            if isinstance(v, dict): items.append((v.get('keyword') or v.get('key') or v.get('name'), v.get('value'), v.get('comment')))
            elif isinstance(v, (list, tuple)) and v: items.append((v[0], v[1] if len(v) > 1 else None, v[2] if len(v) > 2 else None))
    for k, v, c in items:
        if not k: continue
        k = str(k).strip().upper()
        if k.startswith('HIERARCH '): k = k[9:].strip()
        out[k] = (v, c)
    return out


def _wcs_blocks(solve):
    """The WCS a still/2 solve answer carries -> (cards for the full-resolution frame, cards as solved on the copy), each
    {KEYWORD: value} or None. Accepts `wcs` holding the cards, or `wcs` holding sub-blocks (full / solved / copy ...),
    and `wcs_full` beside it (the spec's names)."""
    def cards(x):
        if not x: return None
        c = {k: v for k, (v, _) in _fits_block(x).items()}
        return c if any(k.startswith(('CRVAL', 'CD1', 'CTYPE')) for k in c) else None
    w = solve.get('wcs'); full = cards(solve.get('wcs_full')); solved = None
    if isinstance(w, dict) and any(isinstance(v, dict) and not {'value'} & set(v) for v in w.values()):
        sub = {k.lower(): v for k, v in w.items() if isinstance(v, (dict, list))}
        full = full or cards(sub.get('full') or sub.get('full_resolution') or sub.get('frame') or sub.get('picture'))
        solved = cards(sub.get('solved') or sub.get('as_solved') or sub.get('copy') or sub.get('solver') or sub.get('solver_copy'))
    elif w:
        c = cards(w)
        if c and (c.get('IMAGEW') or 0) >= 3000: full = full or c
        else: solved = c
    return full, solved


def observing_night(t, lon_deg=None):
    """The observing night a time belongs to: the date of local solar noon before it (local solar time from the site's
    longitude; without one, UTC - 12 h). A frame at 03:00 local belongs to the evening before."""
    if t is None: return None
    off = datetime.timedelta(hours=(lon_deg / 15.0 if lon_deg is not None else 0.0) - 12.0)
    return (t + off).date().isoformat()


def read_frame(path, exif=False):
    """One frame (a RAW, JPEG, sidecar or stem path) as a normalised record. Reads <stem>.json and <stem>.solve.json
    (observatory.still/1 or /2; observatory.still.solve/1); with exif=True also the RAW's own exposure and ISO, which
    stacking trusts over the sidecar's. Raises FileNotFoundError without a sidecar, ValueError on another schema."""
    stem = _stem(path); sc = stem + '.json'; sv = stem + '.solve.json'
    j = json.load(open(sc))
    schema = j.get('schema') or ''
    m = re.match(r'observatory\.still/(\d+)$', schema)
    if not m or int(m.group(1)) not in (1, 2): raise ValueError('%s: schema %r is not observatory.still/1 or /2' % (sc, schema))
    version = int(m.group(1))
    files = {f.get('format'): dict(name=f.get('name'), sha256=f.get('sha256'), bytes=f.get('bytes'), camera_name=f.get('camera_name')) for f in j.get('files') or []}
    arw = files.get('arw') or {}
    name = arw.get('name') or (files.get('jpeg') or {}).get('name') or os.path.basename(stem)
    folder = os.path.dirname(stem)
    cam = j.get('camera') or {}; tm = j.get('time') or {}; opt = j.get('optics') or {}; site = j.get('site') or {}; pt = j.get('pointing') or {}
    cap = j.get('capture') or {}; fits = _fits_block(j.get('fits'))
    fv = lambda k: fits.get(k, (None, None))[0]
    start = parse_time(tm.get('shutter_pressed') or fv('DATE-OBS') or fv('DATE-BEG'))
    exp = tm.get('exposure_s', cam.get('exposure_s'))
    if exp is None: exp = fv('EXPTIME')
    end = parse_time(tm.get('exposure_end') or fv('DATE-END')) or (start + datetime.timedelta(seconds=float(exp)) if start and exp is not None else None)
    mid = start + (end - start) / 2 if start and end else None
    ftype = (j.get('frame') or {}).get('type') if isinstance(j.get('frame'), dict) else None
    if j.get('dark') is True: ftype = ftype or 'dark'
    purpose = cap.get('purpose') or ftype or None
    imagetyp = fv('IMAGETYP') or (PURPOSE_IMAGETYP.get(purpose, 'SNAPSHOT') if purpose else 'LIGHT')   # spec: frame.type absent means light
    tgt = cap.get('target') or j.get('object') or None
    profile = dict(CAMERAS.get(cam.get('id'), {})); profile.update(j.get('sensor') or {})
    make = (cam.get('manufacturer') or '').replace(' Corporation', '').strip()
    rec = dict(
        name=name, stem=os.path.basename(stem), path_stem=stem, folder=rel(folder), version=version, schema=schema,
        files=files, sha256=arw.get('sha256'), sidecar_sha256=sha256_file(sc),
        solve_sha256=sha256_file(sv) if os.path.exists(sv) else None,
        seq=j.get('seq'), imagetyp=imagetyp, purpose=purpose, frame_type=ftype, plan=cap.get('plan'), run=j.get('run'),
        target=dict(name=tgt.get('name'), id=tgt.get('id'), ra_deg=tgt.get('ra_deg'), dec_deg=tgt.get('dec_deg')) if isinstance(tgt, dict) else None,
        time=dict(start=start, end=end, mid=mid, exposure_s=float(exp) if exp is not None else None, ready=tm.get('picture_ready'), saved=tm.get('saved'), clock=tm.get('clock')),
        camera=dict(id=cam.get('id'), make=make or None, model=cam.get('model'), instrume=fv('INSTRUME') or (('%s %s' % (make, cam.get('model'))).strip() if cam.get('model') else None),
                    iso=cam.get('iso') if cam.get('iso') is not None else fv('ISOSPEED'), exposure_s=cam.get('exposure_s'), serial=cam.get('serial') or fv('OBS CAMERA SERIAL'),
                    firmware=cam.get('firmware') or fv('OBS CAMERA FIRMWARE'), quality=cam.get('quality'), shutter=cam.get('shutter'), focus=cam.get('focus'), battery_pct=cam.get('battery_pct'),
                    settings_from=cam.get('settings_from')),
        sensor=profile or None,
        optics=dict(focal_length_mm=opt.get('focal_length_mm') or fv('FOCALLEN'), focal_length_from=opt.get('focal_length_from'), focal_length_label_mm=opt.get('focal_length_label_mm'),
                    aperture_mm=opt.get('aperture_mm') or fv('APTDIA'), telescope=fv('TELESCOP') or opt.get('telescope') or None),
        site=dict(lat=site.get('lat', fv('SITELAT')), lon=site.get('lon', fv('SITELONG')), elevation_m=site.get('elevation_m', fv('SITEELEV')), source=site.get('from')),
        pointing=dict(ra_deg=pt.get('ra_deg'), dec_deg=pt.get('dec_deg'), alt_deg=pt.get('alt_deg'), az_deg=pt.get('az_deg'), source=pt.get('source'), equinox=pt.get('equinox')),
        mount_id=_get(j, 'mount', 'id'), box=j.get('box'), dither=j.get('dither'), settle=j.get('settle'), settling=j.get('settling'),
        star_size_arcsec=_get(j, 'measured', 'star_size', 'arcsec'), transparency=j.get('transparency'), cloud=j.get('cloud'),
        observer=fv('OBSERVER'), fits=fits, sidecar=j)
    rec['night'] = observing_night(start, rec['site']['lon'])
    rec['solve'] = None
    if os.path.exists(sv):
        s = json.load(open(sv)); sol = s.get('solution') or {}
        full, solved = _wcs_blocks(s)
        rec['solve'] = dict(state=s.get('state'), reason=s.get('reason'), ra_deg=sol.get('ra_deg'), dec_deg=sol.get('dec_deg'), pixscale_arcsec=sol.get('pixscale_arcsec'),
                            rotation_deg=sol.get('rotation_deg'), parity=sol.get('parity'), stars=sol.get('stars'), seconds=sol.get('seconds'), solver=sol.get('solver'),
                            width_deg=sol.get('width_deg'), height_deg=sol.get('height_deg'), focal_length_mm=s.get('focal_length_mm'), written=s.get('written'),
                            wcs_full=full, wcs_solved=solved, schema=s.get('schema'))
    if exif and 'arw' in files:
        p = os.path.join(folder, files['arw']['name'])
        if os.path.exists(p):
            import rawplanes
            e, iso = rawplanes.raw_exif(p)
            rec['exif'] = dict(exposure_s=e, iso=iso)
            rec['exif']['agrees'] = bool(abs(e - (rec['time']['exposure_s'] or -1)) < 0.01 * e and iso == rec['camera']['iso'])
    return rec


def find_frame(name, folders):
    """The sidecar stem of a frame named by file name or stamp ('20261018-102251'), in the first folder that has it."""
    base = os.path.basename(name)
    for d in folders:
        d = os.path.expanduser(d)
        for pat in (base, base + '-*.ARW', base + '*.ARW') if not base.endswith(('.ARW', '.JPG', '.json')) else (base,):
            hits = sorted(glob.glob(os.path.join(d, pat)))
            for h in hits:
                if os.path.exists(_stem(h) + '.json'): return _stem(h)
    return None


# ---------------------------------------------------------------------------------------------------- FITS cards

def _num(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else v


def frame_cards(rec):
    """FITS cards for one frame: [(keyword, value, comment)], standard keywords first, ours as OBS ... (written with
    HIERARCH). A still/2 sidecar's `fits` block is taken as it is, less anything that gives the site away
    (private_cards); anything it lacks is filled from the record."""
    have = dict(rec.get('fits') or {})
    out = [(k, v, c) for k, (v, c) in have.items()]
    def add(k, v, c=None):
        v = _num(v)
        if v is None or k in have: return
        have[k] = (v, c); out.append((k, v, c))
    t = rec['time']; cam = rec['camera']; opt = rec['optics']; site = rec['site']; pt = rec['pointing']; sen = rec.get('sensor') or {}
    add('IMAGETYP', rec['imagetyp'], 'frame type (N.I.N.A. names)')
    add('OBJECT', (rec.get('target') or {}).get('name'), 'target (SIMBAD name)')
    if rec.get('target') and rec['target'].get('ra_deg') is not None:
        ra_s, de_s = sexagesimal(rec['target']['ra_deg'], rec['target']['dec_deg'])
        add('OBJCTRA', ra_s, "target's catalogue RA (ICRS)"); add('OBJCTDEC', de_s, "target's catalogue Dec (ICRS)")
    add('TIMESYS', 'UTC')
    if t['start']:
        add('DATE-OBS', iso_ms(t['start']), 'shutter pressed (UTC)'); add('DATE-BEG', iso_ms(t['start'])); add('MJD-OBS', round(mjd(t['start']), 8))
    if t['end']: add('DATE-END', iso_ms(t['end']), 'exposure end (UTC)'); add('MJD-END', round(mjd(t['end']), 8))
    if t['mid']: add('DATE-AVG', iso_ms(t['mid']), 'mid-exposure (UTC)'); add('MJD-AVG', round(mjd(t['mid']), 8))
    exp = (rec.get('exif') or {}).get('exposure_s', t['exposure_s'])
    add('EXPTIME', exp, '[s] exposure'); add('XPOSURE', exp, '[s] exposure')
    add('ISOSPEED', (rec.get('exif') or {}).get('iso', cam['iso']), 'ISO')
    add('INSTRUME', cam['instrume'], 'camera')
    add('TELESCOP', opt.get('telescope') or TELESCOPE, 'optical tube')
    add('OBSERVER', rec.get('observer') or OBSERVER)
    add('FOCALLEN', opt['focal_length_mm'], '[mm] focal length (%s)' % (opt.get('focal_length_from') or 'sidecar'))
    add('APTDIA', opt['aperture_mm'], '[mm] aperture')
    if opt['focal_length_mm'] and opt['aperture_mm']: add('FOCRATIO', round(opt['focal_length_mm'] / opt['aperture_mm'], 3), 'focal ratio')
    if sen.get('pixel_um'):
        add('XPIXSZ', sen['pixel_um'], '[um] pixel size'); add('YPIXSZ', sen['pixel_um'], '[um] pixel size'); add('XBINNING', 1); add('YBINNING', 1)
    if sen.get('cfa'):
        add('BAYERPAT', sen['cfa'], 'colour filter array'); add('XBAYROFF', (sen.get('bayer_offset') or [0, 0])[0]); add('YBAYROFF', (sen.get('bayer_offset') or [0, 0])[1])
    add('SATURATE', sen.get('white_dn'), '[DN] raw white level'); add('OBS RAW BLACK', sen.get('black_dn'), '[DN] raw black level')
    add('RADESYS', 'ICRS'); add('EQUINOX', 2000.0)
    add('RA', pt['ra_deg'], '[deg] where the mount says it points'); add('DEC', pt['dec_deg'], '[deg] where the mount says it points')
    add('OBS SCHEMA', rec['schema']); add('OBS FRAME SEQ', rec.get('seq'))
    add('OBS FILE RAW SHA256', rec.get('sha256'))
    add('OBS CAMERA ID', cam['id']); add('OBS CAMERA SERIAL', cam.get('serial')); add('OBS CAMERA FIRMWARE', cam.get('firmware'))
    add('OBS MOUNT ID', rec.get('mount_id')); add('OBS POINTING SOURCE', pt.get('source'))
    d = rec.get('dither') or {}
    add('OBS DITHER K', d.get('k')); add('OBS DITHER EAST ARCMIN', d.get('east_arcmin')); add('OBS DITHER NORTH ARCMIN', d.get('north_arcmin'))
    add('OBS STARS HFD ARCSEC', rec.get('star_size_arcsec'), '[arcsec] the box\'s star size')
    add('OBS BOX NODE', (rec.get('box') or {}).get('node')); add('OBS BOX FIRMWARE', (rec.get('box') or {}).get('firmware'))
    s = rec.get('solve')
    if s:
        add('PLTSOLVD', s.get('state') == 'solved', 'plate solved')
        for k, v in (s.get('wcs_full') or {}).items():
            if k not in ('COMMENT', 'HISTORY', 'SIMPLE', 'BITPIX', 'NAXIS', 'EXTEND', 'END'): add(k, v)
    return private_cards(out)


def _isot_frames(frames):
    starts = [f['time']['start'] for f in frames if f['time']['start']]
    ends = [f['time']['end'] for f in frames if f['time']['end']]
    return (min(starts) if starts else None), (max(ends) if ends else None)


def weighted_mid(frames, weights=None):
    """Exposure (times weight) weighted mean of the frames' mid-exposure times."""
    t0 = min(f['time']['mid'] for f in frames)
    w = np.array([(f['time']['exposure_s'] or 0) * (1.0 if weights is None else weights[i]) for i, f in enumerate(frames)], float)
    dt = np.array([(f['time']['mid'] - t0).total_seconds() for f in frames], float)
    if w.sum() <= 0: w = np.ones_like(dt)
    return t0 + datetime.timedelta(seconds=float((w * dt).sum() / w.sum()))


def common_value(frames, get):
    """The value every frame agrees on, else None."""
    vals = set()
    for f in frames:
        v = get(f)
        if v is None: return None
        vals.add(json.dumps(v, sort_keys=True, default=str))
    return json.loads(vals.pop()) if len(vals) == 1 else None


# FITS cards a stack can take over from its frames' own `fits` blocks (still/2) when every frame agrees on them.
STACK_FROM_FRAMES = ('TELESCOP', 'INSTRUME', 'OBSERVER', 'APTDIA',
                     'OBS CAMERA ID', 'OBS CAMERA SERIAL', 'OBS CAMERA FIRMWARE', 'OBS MOUNT ID', 'OBS MOUNT NAME', 'OBS OPTICS TRAIN')


def stack_cards(frames, *, target, imagetyp='MASTER LIGHT', planes, exptime_s, exptime_comment=None, livetime_s, iso=None, weights=None,
                pixel_um, binning=None, bunit='adu', bunit_comment=None, calstat=None, calstat_comment=None, focal_length_mm=None, focal_from=None,
                wcs=None, history=(), extra=(), recipe_id=None, recipe_path=None, date=None, comments=()):
    """Cards of a linear stack (docs/metadata.md, Stage 4). frames: read_frame records of the frames combined (used),
    in any order. target: {name (SIMBAD), title, ra_deg, dec_deg, what (the place's comment)}. planes: e.g. 'R G B'.
    exptime_s: the exposure the data are in units of (one frame). livetime_s: the total. pixel_um: the effective pixel
    size of the stack's pixels (e.g. 7.84 for one pixel per 2 x 2 colour cell). wcs: {KEYWORD: value} for the image as
    stored (or None). history: lines, one or more per recipe step. extra: more (keyword, value, comment)."""
    C = []
    add = lambda k, v, c=None: C.append((k, v, c)) if _num(v) is not None else None
    add('DATE', date, 'this HDU (the stack) was made (UTC)')
    add('ORIGIN', 'Observatory', 'github.com/bradgessler/observatory')
    add('OBJECT', target['name'], target.get('title'))
    if target.get('ra_deg') is not None:
        ra_s, de_s = sexagesimal(target['ra_deg'], target['dec_deg'])
        add('OBJCTRA', ra_s, target.get('what') or "target's catalogue RA (ICRS)"); add('OBJCTDEC', de_s, target.get('what') or "target's catalogue Dec (ICRS)")
    add('IMAGETYP', imagetyp, 'a combined (stacked) light')
    t0, t1 = _isot_frames(frames)
    add('NCOMBINE', len(frames), 'frames combined'); add('STACKCNT', len(frames), 'frames combined (Siril)')
    add('EXPTIME', exptime_s, exptime_comment or '[s] one frame: the data are per frame'); add('XPOSURE', exptime_s, '[s] one frame')
    add('LIVETIME', livetime_s, '[s] total exposure of the frames combined')
    add('ISOSPEED', iso, 'ISO')
    add('TIMESYS', 'UTC')
    if t0: add('DATE-OBS', iso_ms(t0), 'first frame: shutter pressed'); add('DATE-BEG', iso_ms(t0)); add('MJD-OBS', round(mjd(t0), 8)); add('MJD-BEG', round(mjd(t0), 8))
    if t1: add('DATE-END', iso_ms(t1), 'last frame: exposure end'); add('MJD-END', round(mjd(t1), 8))
    if frames:
        ta = weighted_mid(frames, weights)
        add('DATE-AVG', iso_ms(ta), 'mid-exposures, weighted by exposure%s' % (' x weight' if weights is not None else '')); add('MJD-AVG', round(mjd(ta), 8))
    fits_common = {}
    for k in STACK_FROM_FRAMES:
        v = common_value(frames, lambda f: (f.get('fits') or {}).get(k, (None,))[0])
        if v is not None: fits_common[k] = v
    cam = common_value(frames, lambda f: f['camera']['instrume'])
    add('TELESCOP', fits_common.get('TELESCOP') or common_value(frames, lambda f: f['optics'].get('telescope')) or TELESCOPE, 'optical tube')
    add('INSTRUME', fits_common.get('INSTRUME') or cam, 'camera')
    add('OBSERVER', fits_common.get('OBSERVER') or OBSERVER)
    ap = fits_common.get('APTDIA') or common_value(frames, lambda f: f['optics']['aperture_mm'])
    add('FOCALLEN', None if focal_length_mm is None else round(float(focal_length_mm), 1), '[mm] %s' % (focal_from or 'focal length'))
    add('APTDIA', ap, '[mm] aperture')
    if focal_length_mm and ap: add('FOCRATIO', round(float(focal_length_mm) / ap, 3), 'focal ratio')
    add('XPIXSZ', pixel_um, '[um] effective pixel size of this image'); add('YPIXSZ', pixel_um, '[um] effective pixel size of this image')
    if binning: add('XBINNING', binning, 'sensor px per image px, each way'); add('YBINNING', binning, 'sensor px per image px, each way')
    add('BUNIT', bunit, bunit_comment)
    add('CALSTAT', calstat, calstat_comment or 'calibration applied (MaxIm: B bias, D dark, F flat)')
    add('ROWORDER', 'TOP-DOWN', 'first row is the top of the picture')
    add('OBS PLANES', planes, 'NAXIS3 planes, in order')
    add('RADESYS', 'ICRS'); add('EQUINOX', 2000.0, 'ICRS; for readers that want it')
    for k, v in (wcs or {}).items():
        if k in ('COMMENT', 'HISTORY', 'SIMPLE', 'BITPIX', 'NAXIS', 'NAXIS1', 'NAXIS2', 'EXTEND', 'END', 'EQUINOX', 'RADESYS', 'DATE', 'DATE-OBS'): continue
        add(k, v)
    fits_common.setdefault('OBS CAMERA ID', common_value(frames, lambda f: f['camera']['id']))
    fits_common.setdefault('OBS CAMERA SERIAL', common_value(frames, lambda f: f['camera'].get('serial')))
    fits_common.setdefault('OBS CAMERA FIRMWARE', common_value(frames, lambda f: f['camera'].get('firmware')))
    fits_common.setdefault('OBS MOUNT ID', common_value(frames, lambda f: f.get('mount_id')))
    for k in STACK_FROM_FRAMES:
        if k.startswith('OBS ') and fits_common.get(k) is not None: add(k, fits_common[k])
    add('OBS SCHEMA', STACK_SCHEMA)
    add('OBS RECIPE ID', recipe_id, 'recipe id (SHA-256)')
    add('OBS RECIPE', recipe_path, 'in the repository')
    for k, v, c in extra: add(k, v, c)
    add('SWCREATE', SWCREATE)
    out = list(C)
    for line in history: out.append(('HISTORY', line, None))
    for line in comments: out.append(('COMMENT', line, None))
    return out


def master_cards(kind, inputs, *, planes='R G1 G2 B', exptime_s=None, iso=None, combine=None, norm=None, hot_n=None, date=None, temperature_c=None,
                 extra=(), history=(), comments=()):
    """Cards of a calibration master (docs/metadata.md, Stage 3). kind: 'dark' or 'flat'. inputs: read_frame records
    (or dicts with name, sha256 and time) of the frames combined. Each input becomes a HISTORY line with its SHA-256."""
    C = []
    add = lambda k, v, c=None: C.append((k, v, c)) if _num(v) is not None else None
    add('DATE', date, 'this master was made (UTC)')
    add('ORIGIN', 'Observatory', 'github.com/bradgessler/observatory')
    add('IMAGETYP', 'MASTER ' + kind.upper(), 'PixInsight WBPP form')
    add('NCOMBINE', len(inputs), 'frames combined')
    add('EXPTIME', exptime_s, '[s] exposure of the frames'); add('ISOSPEED', iso, 'ISO')
    add('CCD-TEMP', temperature_c, '[degC] sensor temperature')
    ts = [i['time']['start'] for i in inputs if i.get('time') and i['time'].get('start')]
    te = [i['time']['end'] for i in inputs if i.get('time') and i['time'].get('end')]
    add('TIMESYS', 'UTC')
    if ts: add('DATE-OBS', iso_ms(min(ts)), 'first frame'); add('MJD-OBS', round(mjd(min(ts)), 8))
    if te: add('DATE-END', iso_ms(max(te)), 'last frame'); add('MJD-END', round(mjd(max(te)), 8))
    instr = common_value([i for i in inputs if i.get('camera')], lambda f: f['camera']['instrume']) if any(i.get('camera') for i in inputs) else None
    add('INSTRUME', instr, 'camera'); add('TELESCOP', TELESCOPE, 'optical tube'); add('OBSERVER', OBSERVER)
    sen = next((i.get('sensor') for i in inputs if i.get('sensor')), None) or CAMERAS['sony-ilce-6000']
    add('XPIXSZ', 2 * sen['pixel_um'], '[um] one plane px = one 2 x 2 colour cell'); add('YPIXSZ', 2 * sen['pixel_um'], '[um] one plane px = one 2 x 2 colour cell')
    add('BAYERPAT', sen.get('cfa', 'RGGB'), 'the sensor\'s colour filter array'); add('OBS PLANES', planes, 'NAXIS3 planes: the CFA\'s colour planes, no demosaic')
    add('ROWORDER', 'TOP-DOWN', 'first row is the top of the sensor')
    if kind == 'dark': add('BUNIT', 'adu', '[DN] above the raw black level')
    else: C.append(('COMMENT', 'Data: relative response per colour plane, 1 at the sensor centre; divide the black-subtracted plane by it.', None))
    add('OBS COMBINE', combine); add('OBS FLAT NORM', norm); add('OBS HOT N', hot_n, 'hot pixels counted')
    add('OBS SCHEMA', MASTER_SCHEMA)
    for k, v, c in extra: add(k, v, c)
    add('SWCREATE', SWCREATE)
    out = list(C)
    for line in history: out.append(('HISTORY', line, None))
    for i in inputs:
        out.append(('HISTORY', 'input %s' % i.get('name'), None)); out.append(('HISTORY', 'sha256 %s' % (i.get('sha256') or 'unknown'), None))
    for line in comments: out.append(('COMMENT', line, None))
    return out


LOCATION_KEYS = re.compile(r'^(SITELAT|SITELONG|SITELON|SITEELEV|LATITUDE|LONGITUD|LAT-OBS|LONG-OBS|ALT-OBS|OBSGEO-.*|CENTALT|CENTAZ|OBJCTALT|OBJCTAZ|OBJCTHA|HA|LST|DATE-LOC|TIMEZONE|TZ|'
                           r'OBS SITE.*|OBS MODEL AXIS.*|OBS TRACKING AXIS ALT.*|OBS TRACKING AXIS AZ.*|OBS PARALLAX.*)$')


def site_secret():
    """(lat, lon) from config/site.secret.exs when it is on this machine (untracked), for the checks only; else None."""
    try:
        s = open(os.path.join(REPO, 'config', 'site.secret.exs')).read()
        return float(re.search(r'lat:\s*(-?[\d.]+)', s).group(1)), float(re.search(r'lon:\s*(-?[\d.]+)', s).group(1))
    except (OSError, AttributeError):
        return None


def private_cards(cards, site=None):
    """Brad's rule for every processed file: drop each card that gives the site away (LOCATION_KEYS), round AIRMASS to
    0.1, and refuse HISTORY/COMMENT text that names the site's latitude or longitude (site = (lat, lon), when known)."""
    out = []
    for k, v, c in cards:
        if LOCATION_KEYS.match(k.upper()): continue
        if k == 'AIRMASS' and v is not None: v = round(float(v), 1)
        if site and (k in ('HISTORY', 'COMMENT') or isinstance(v, str)):
            for m in re.finditer(r'-?\d+\.\d+', str(v)):
                if any(abs(float(m.group()) - s) < 0.05 for s in site if s is not None): raise ValueError('a %s line names the site: %r' % (k, v))
        out.append((k, v, c))
    return out


def to_header(cards):
    """(keyword, value, comment) list -> astropy Header. Keywords longer than 8 characters or with spaces are HIERARCH.
    HISTORY and COMMENT text is wrapped at word boundaries (72 characters a card). A string too long for one HIERARCH
    card (a SHA-256 is) is split, nothing cut: KEY holds the first part, 'KEY 2', 'KEY 3' ... the rest, in order; join
    them to read it. A comment too long for its card is shortened (comments are not data)."""
    import textwrap
    from astropy.io import fits
    h = fits.Header()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        for k, v, c in cards:
            if k in ('HISTORY', 'COMMENT'):
                for line in textwrap.wrap(str(v), 72, break_long_words=True, break_on_hyphens=False) or ['']:
                    h.append(fits.Card(k, line), end=True)
                continue
            if isinstance(v, (np.floating,)): v = float(v)
            if isinstance(v, (np.integer,)): v = int(v)
            if isinstance(v, (np.bool_,)): v = bool(v)
            hier = len(k) > 8 or ' ' in k
            key = 'HIERARCH ' + k if hier else k
            if isinstance(v, str) and hier:
                room = 80 - len(key) - 3 - 2 - 2               # ' = ', the quotes, and the last key's ' N'
                if len(v) > room:
                    n = -(-len(v) // room); size = -(-len(v) // n)
                    parts = [v[i:i + size] for i in range(0, len(v), size)]
                    for i, p in enumerate(parts):
                        h.append(fits.Card(key + ('' if i == 0 else ' %d' % (i + 1)), p, (c or '') if i == 0 else 'continued'), end=True)
                    continue
            h.append(fits.Card(key, v, c or ''), end=True)
    return h


def joined(header, key):
    """A value to_header split over KEY, 'KEY 2', ... read back as one string."""
    v = header.get(key)
    if v is None: return None
    i = 2
    while ('%s %d' % (key, i)) in header:
        v += header['%s %d' % (key, i)]; i += 1
    return v


def write_fits(path, data, cards, when):
    """One primary HDU: data as given (float32 stays float32: no BSCALE, no rescale), the cards, CHECKSUM and DATASUM.
    `when` (a fixed string, e.g. the recipe's time) is the checksum cards' comment, so the file is reproducible.
    Returns sha256 of the file. Verifies the checksums by reading the file back."""
    from astropy.io import fits
    if os.path.abspath(path).startswith(REPO + os.sep): raise ValueError('%s: FITS files are written under ~/.observatory, never into the repository' % path)
    cards = private_cards(cards, site_secret())
    hdu = fits.PrimaryHDU(data=np.ascontiguousarray(data))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')                  # comments too long for a card are shortened, values never (to_header)
        for card in to_header(cards).cards:
            hdu.header.append(card, end=True)
        hdu.add_checksum(when=when)
        tmp = path + '.part'
        hdu.writeto(tmp, overwrite=True, checksum=False, output_verify='exception')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        with fits.open(tmp, checksum=True) as f: f[0].header['DATASUM']
        bad = [str(x.message) for x in w if 'checksum' in str(x.message).lower() or 'datasum' in str(x.message).lower()]
    if bad: raise RuntimeError('%s: %s' % (path, bad))
    os.replace(tmp, path)
    return sha256_file(path)


def read_cards(path):
    """A FITS file's primary header as (keyword, value, comment) and whether CHECKSUM/DATASUM verify."""
    from astropy.io import fits
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        with fits.open(path, checksum=True) as f:
            h = f[0].header
            cards = [(c.keyword, c.value, c.comment) for c in h.cards]
        bad = [str(x.message) for x in w if 'checksum' in str(x.message).lower() or 'datasum' in str(x.message).lower()]
    return cards, not bad


# ---------------------------------------------------------------------------------------------------- plate solve

def _image2xy_fits(path, G):
    """16-bit FITS of a 2-D image for image2xy, rows as stored (as the pipelines' solvelib writes it): G + 100, clipped."""
    from astropy.io import fits
    im = np.clip(np.nan_to_num(np.asarray(G, np.float64)) + 100, -32768, 32767).round().astype('>i2')
    fits.PrimaryHDU(im).writeto(path, overwrite=True)


def astrometry_version():
    try:
        r = subprocess.run(['solve-field', '--version'], capture_output=True, text=True, timeout=30)
        return (r.stdout or r.stderr).strip().splitlines()[0]
    except Exception:
        return None


INDEX_SERIES = {'41': 'Tycho-2', '42': '2MASS', '50': 'Tycho-2 + Gaia DR2', '52': 'Tycho-2 + Gaia DR2'}


def astrometry_index_summary(names=None):
    """The index files as series and scale ranges: {'Tycho-2': 'index-4107 to 4119 (13 files)', ...}."""
    names = astrometry_indexes() if names is None else names
    by = {}
    for n in names:
        m = re.match(r'index-(\d\d)(\d\d)', n)
        if m: by.setdefault(INDEX_SERIES.get(m.group(1), m.group(1) + 'xx series'), []).append(int(m.group(1) + m.group(2)))
    return {k: 'index-%d to %d (%d files)' % (min(v), max(v), len(v)) for k, v in by.items()}


def astrometry_indexes():
    """The index files the local astrometry.net uses (from its config's add_path folders)."""
    out = []
    try:
        for line in open(ASTROMETRY_CFG):
            if line.startswith('add_path'):
                out += sorted(os.path.basename(p) for p in glob.glob(os.path.join(line.split(None, 1)[1].strip(), 'index-*.fits')))
    except OSError:
        pass
    return out


def solve_image(G, ra_deg, dec_deg, scale_low, scale_high, radius_deg=1.0, tweak_order=2, cpulimit=120, keep=None, indexes=None):
    """Plate-solve a 2-D image with the local astrometry.net, as the 17 October pipelines' solvelib does (image2xy at 8
    sigma, solve-field with the observatory's config, scale window in arcsec/px, within radius_deg of the place, SIP of
    tweak_order). Returns (wcs cards {KEYWORD: value} for the image as stored, info). keep: a folder to copy the
    solver's .wcs, .corr and log into. Raises RuntimeError if it does not solve."""
    from astropy.io import fits
    h, w = G.shape
    with tempfile.TemporaryDirectory() as td:
        f = lambda ext: os.path.join(td, 'img' + ext)
        cfg = ASTROMETRY_CFG
        if indexes:                                      # only these index files (globs in the config's folders), in this order
            folder = os.path.dirname(ASTROMETRY_CFG); names = [p for g in indexes for p in sorted(glob.glob(os.path.join(folder, g)))]
            cfg = f('.cfg'); open(cfg, 'w').write('inparallel\ncpulimit %d\n' % cpulimit + ''.join('index %s\n' % p for p in names))
        _image2xy_fits(f('.fits'), G)
        subprocess.run(['image2xy', '-O', '-p', '8', '-w', '3', '-o', f('.xy'), f('.fits')], check=True, capture_output=True)
        cmd = ['solve-field', '--config', cfg, '--overwrite', '--no-plots', '--no-remove-lines', '--uniformize', '0', '--width', str(w), '--height', str(h),
               '--x-column', 'X', '--y-column', 'Y', '--sort-column', 'FLUX', '--scale-units', 'arcsecperpix', '--scale-low', '%g' % scale_low, '--scale-high', '%g' % scale_high,
               '--ra', '%.4f' % ra_deg, '--dec', '%.4f' % dec_deg, '--radius', '%g' % radius_deg, '--cpulimit', str(cpulimit), '--tweak-order', str(tweak_order),
               '-N', 'none', '--rdls', 'none', '--match', 'none', '--solved', 'none', '--index-xyls', 'none', '--corr', f('.corr'), '--wcs', f('.wcs'), f('.xy')]
        r = subprocess.run(cmd, capture_output=True, text=True)
        log = r.stdout + r.stderr
        if not os.path.exists(f('.wcs')): raise RuntimeError('not solved:\n' + log[-3000:])
        hd = fits.getheader(f('.wcs'))
        cards = {}
        for c in hd.cards:
            if c.keyword in ('', 'COMMENT', 'HISTORY', 'SIMPLE', 'BITPIX', 'NAXIS', 'EXTEND', 'END', 'DATE'): continue
            cards[c.keyword] = c.value
        corr = fits.getdata(f('.corr'))
        dx = corr['field_x'] - corr['index_x']; dy = corr['field_y'] - corr['index_y']
        idx = re.findall(r'index-(\d+)', ' '.join(l for l in log.splitlines() if 'solved' in l.lower() or 'index' in l.lower()))
        lo = re.findall(r'log-odds ratio ([\d.]+)', log)
        info = dict(matched_stars=int(len(corr)), match_rms_px=float(np.sqrt(np.mean(dx * dx + dy * dy))), log_odds=float(lo[-1]) if lo else None,
                    index=('index-%s' % idx[-1]) if idx else None, indexes_offered=list(indexes) if indexes else 'all in astrometry.cfg',
                    command=' '.join(os.path.basename(c) if c.startswith(td) else c for c in cmd).replace(ASTROMETRY_CFG, '~/.observatory/astrometry/astrometry.cfg'),
                    software=astrometry_version(), sources=int(len(fits.getdata(f('.xy')))))
        if keep:
            os.makedirs(keep, exist_ok=True)
            for ext in ('.wcs', '.corr'):
                with open(f(ext), 'rb') as a, open(os.path.join(keep, 'solve' + ext), 'wb') as b: b.write(a.read())
            open(os.path.join(keep, 'solve.log'), 'w').write(log)
    return cards, info


def wcs_of(cards):
    """astropy WCS (2 axes, with SIP) from {KEYWORD: value}."""
    from astropy.io import fits
    from astropy.wcs import WCS
    h = fits.Header()
    for k, v in cards.items():
        if k in ('NAXIS3',): continue
        h[k] = v
    h['NAXIS'] = 2
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return WCS(h, naxis=2, relax=True)


def find_stars(G, k=8.0, n=400, sat=None):
    """Compact sources in a 2-D image: (x, y, flux) arrays, array px (0-based, column x, row y), brightest first.
    Background: 32 px block medians, bilinear; detection on a 1.5 px Gaussian above k sigma; centroid: intensity-weighted
    over 9 x 9 px. Sources touching `sat` (or the image's own maximum) or wider than 60 px^2 at threshold are left out."""
    import cv2
    G = np.nan_to_num(np.asarray(G, np.float32)); h, w = G.shape; bk = 32; ny, nx = h // bk, w // bk
    b = np.median(G[:ny * bk, :nx * bk].reshape(ny, bk, nx, bk).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2).astype(np.float32)
    bg = cv2.resize(cv2.medianBlur(b, 5), (w, h), interpolation=cv2.INTER_LINEAR)
    D = G - bg; S = cv2.GaussianBlur(D, (0, 0), 1.5)
    s = 1.4826 * np.median(np.abs(S[::3, ::3] - np.median(S[::3, ::3])))
    nl, lab, st, cen = cv2.connectedComponentsWithStats((S > k * s).astype(np.uint8))
    top = sat if sat is not None else 0.98 * float(G.max())
    out = []
    for i in range(1, nl):
        if st[i, 4] > 60 or st[i, 4] < 3: continue
        cx, cy = int(round(cen[i][0])), int(round(cen[i][1]))
        if cx < 6 or cy < 6 or cx > w - 7 or cy > h - 7: continue
        win = D[cy - 4:cy + 5, cx - 4:cx + 5]; wg = np.clip(win, 0, None)
        if G[cy - 4:cy + 5, cx - 4:cx + 5].max() >= top or wg.sum() <= 0: continue
        yy, xx = np.mgrid[-4:5, -4:5]
        out.append((cx + float((wg * xx).sum() / wg.sum()), cy + float((wg * yy).sum() / wg.sum()), float(wg.sum())))
    out.sort(key=lambda r: -r[2])
    a = np.array(out[:n]) if out else np.zeros((0, 3))
    return a[:, 0], a[:, 1], a[:, 2]


def _background(G, bk=32):
    import cv2
    h, w = G.shape; ny, nx = h // bk, w // bk
    b = np.median(G[:ny * bk, :nx * bk].reshape(ny, bk, nx, bk).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2).astype(np.float32)
    return cv2.resize(cv2.medianBlur(b, 5), (w, h), interpolation=cv2.INTER_LINEAR)


def check_wcs(G, cards, epoch_year, gmax=16.0, match_px=4.0, isolated_px=10.0, snr_min=15.0, sat=None, offline=False):
    """The WCS against Gaia DR3 (proper motion to epoch_year): every isolated catalogue star (no other star within
    isolated_px, G < gmax + 2) that lands in the image is looked for there: an intensity-weighted centroid over 9 x 9
    px of the image less its smooth background (32 px block medians), started at the predicted place and moved to the
    light three times. Kept when its peak is snr_min x the noise above the background, it is not near the image's
    ceiling (or `sat`), and the centroid ends within match_px of the prediction. The residual is centroid - prediction.
    Starting at the catalogue's place (not from a list of detections) keeps nebula and galaxy knots out of the match;
    a star the WCS missed by more than match_px is counted as lost. Returns residuals overall and by region."""
    import catalogue
    W = wcs_of(cards); G = np.nan_to_num(np.asarray(G, np.float32)); h, w = G.shape
    D = G - _background(G)
    noise = 1.4826 * float(np.median(np.abs(D[::3, ::3] - np.median(D[::3, ::3]))))
    top = sat if sat is not None else 0.98 * float(G.max())
    ra0, de0 = W.all_pix2world([[w / 2 - 0.5, h / 2 - 0.5]], 0)[0]
    cor = W.all_pix2world([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1]], 0)
    rad = max(float(np.degrees(np.arccos(np.clip(np.sin(np.radians(de0)) * np.sin(np.radians(d)) + np.cos(np.radians(de0)) * np.cos(np.radians(d)) * np.cos(np.radians(r - ra0)), -1, 1)))) for r, d in cor) + 0.01
    cat, src = catalogue.gaia_field(float(ra0), float(de0), rad, gmax + 2, offline=offline)
    dt = epoch_year - 2016.0
    ok = np.isfinite(cat['ra']) & np.isfinite(cat['dec'])
    ra = cat['ra'] + np.nan_to_num(cat['pmra']) * dt / 3.6e6 / np.cos(np.radians(cat['dec'])); de = cat['dec'] + np.nan_to_num(cat['pmdec']) * dt / 3.6e6
    px = W.all_world2pix(np.c_[ra[ok], de[ok]], 0); g = cat['g'][ok]
    from scipy.spatial import cKDTree
    T = cKDTree(px); nb = T.query(px, k=2)[0][:, 1]
    cand = (g < gmax) & (nb > isolated_px) & (px[:, 0] > 8) & (px[:, 0] < w - 9) & (px[:, 1] > 8) & (px[:, 1] < h - 9)
    yy, xx = np.mgrid[-4:5, -4:5]
    P, C, lost = [], [], 0
    for (x0, y0) in px[cand]:
        cx, cy = x0, y0; good = True
        for _ in range(3):
            ix, iy = int(round(cx)), int(round(cy))
            if not (4 <= ix < w - 4 and 4 <= iy < h - 4): good = False; break
            win = D[iy - 4:iy + 5, ix - 4:ix + 5]; wg = np.clip(win - np.median(win), 0, None)
            if wg.sum() <= 0: good = False; break
            cx, cy = ix + float((wg * xx).sum() / wg.sum()), iy + float((wg * yy).sum() / wg.sum())
        if not good: lost += 1; continue
        ix, iy = int(round(cx)), int(round(cy))
        if D[iy - 1:iy + 2, ix - 1:ix + 2].max() < snr_min * noise: continue          # too faint to measure: not counted
        if G[iy - 4:iy + 5, ix - 4:ix + 5].max() >= top: continue                      # near the ceiling
        if np.hypot(cx - x0, cy - y0) > match_px: lost += 1; continue
        P.append((x0, y0)); C.append((cx, cy))
    P, C = np.array(P).reshape(-1, 2), np.array(C).reshape(-1, 2)
    dx, dy = (C - P).T if len(P) else (np.zeros(0), np.zeros(0)); r = np.hypot(dx, dy)
    scale = float(np.sqrt(abs(np.linalg.det(W.pixel_scale_matrix))) * 3600)
    def stats(sel):
        if sel.sum() == 0: return dict(n=0)
        rr = r[sel]
        return dict(n=int(sel.sum()), median_px=round(float(np.median(rr)), 3), rms_px=round(float(np.sqrt(np.mean(rr ** 2))), 3), p90_px=round(float(np.percentile(rr, 90)), 3),
                    max_px=round(float(rr.max()), 3), mean_dx_px=round(float(dx[sel].mean()), 3), mean_dy_px=round(float(dy[sel].mean()), 3))
    xm, ym = (P[:, 0], P[:, 1]) if len(P) else (np.zeros(0), np.zeros(0))
    regions = dict(centre=(np.abs(xm - w / 2) < w / 4) & (np.abs(ym - h / 2) < h / 4))
    for name, sx, sy in (('top_left', -1, -1), ('top_right', 1, -1), ('bottom_left', -1, 1), ('bottom_right', 1, 1)):
        regions[name] = (sx * (xm - w / 2) > w / 4) & (sy * (ym - h / 2) > h / 4)
    res = dict(what='"within a pixel or two": passes with at least 20 stars, median <= 1.5 px, 90th percentile <= 2.5 px, mean offset <= 1 px each way. Isolated Gaia DR3 stars (G < %.1f, proper motion to %.2f) looked for at their places through the WCS: intensity-weighted 9 x 9 px centroid, three moves, peak above %.0f x the noise, unsaturated, within %.0f px' % (gmax, epoch_year, snr_min, match_px),
               catalogue_in_field=int(cand.sum()), measured=int(len(P)), lost=int(lost), arcsec_per_px=round(scale, 5), all=stats(np.ones(len(P), bool)), regions={k: stats(v) for k, v in regions.items()},
               catalogue=dict(table=src.get('table') or 'I/355/gaiadr3', cache_file=rel(src.get('cache_file')) if src.get('cache_file') else None, used_from_cache=src.get('used_from_cache'), rows_used=src.get('rows_used')))
    a = res['all']
    res['passed'] = bool(a.get('n', 0) >= 20 and a['median_px'] <= 1.5 and a['p90_px'] <= 2.5 and abs(a['mean_dx_px']) <= 1.0 and abs(a['mean_dy_px']) <= 1.0)
    return res


def compare_wcs(cards_a, cards_b, shape, step=100):
    """Largest and median separation (px) between two WCS over a grid of the image."""
    A, B = wcs_of(cards_a), wcs_of(cards_b); h, w = shape
    yy, xx = np.mgrid[0:h:step, 0:w:step]; p = np.c_[xx.ravel(), yy.ravel()].astype(float)
    q = B.all_world2pix(A.all_pix2world(p, 0), 0); d = np.hypot(*(q - p).T)
    return dict(max_px=round(float(d.max()), 4), median_px=round(float(np.median(d)), 4), grid_px=step)


# ---------------------------------------------------------------------------------------------------- recipes

def rel(path):
    """A path as a recipe writes it: relative to the repository, or under ~/.observatory, or under ~; never /Users/..."""
    if path is None: return None
    p = os.path.abspath(os.path.expanduser(str(path)))
    for root, pre in ((REPO, ''), (DATA, '~/.observatory/'), (HOME, '~/')):
        if p == root: return pre.rstrip('/') or '.'
        if p.startswith(root + os.sep):
            return pre + os.path.relpath(p, root)
    return p


_ABS = [(re.compile(r'/Users/[^/\s"\']+/Projects/bradgessler/observatory(?:/\.claude/worktrees/[^/\s"\']+)?/'), ''),
        (re.compile(r'/Users/[^/\s"\']+/\.observatory'), '~/.observatory'),
        (re.compile(r'/Users/[^/\s"\']+/'), '~/')]


def scrub(obj):
    """Every string in obj with absolute home paths made relative (repository) or ~-based (data)."""
    if isinstance(obj, str):
        for rx, to in _ABS: obj = rx.sub(to, obj)
        return obj
    if isinstance(obj, dict): return {scrub(k): scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)): return [scrub(v) for v in obj]
    return obj


def software(extra=()):
    """Names and versions of what made a stack: Python, numpy, OpenCV, rawpy, tifffile, SciPy, astropy, astrometry.net
    (and its index files)."""
    out = [dict(name='python', version=platform.python_version())]
    for mod, name in (('numpy', 'numpy'), ('cv2', 'opencv'), ('rawpy', 'rawpy'), ('tifffile', 'tifffile'), ('scipy', 'scipy'), ('astropy', 'astropy')):
        try: out.append(dict(name=name, version=__import__(mod).__version__))
        except Exception: pass
    v = astrometry_version()
    if v: out.append(dict(name='astrometry.net', version=v.replace('solve-field', '').strip() or v, indexes=astrometry_index_summary()))
    out += list(extra)
    return out


def git_info(scripts=None):
    """The repository's commit, whether the given scripts folder has changes not committed, and the last commit that
    touched that folder."""
    def g(*a):
        r = subprocess.run(['git', '-C', REPO] + list(a), capture_output=True, text=True)
        return r.stdout.rstrip('\n') if r.returncode == 0 else None
    out = dict(commit=g('rev-parse', 'HEAD'), repository='github.com/bradgessler/observatory')
    if scripts:
        rp = os.path.relpath(os.path.abspath(scripts), REPO)
        out['scripts'] = rp
        out['scripts_commit'] = g('log', '-1', '--format=%H', '--', rp)
        st = g('status', '--porcelain', '--', rp)
        out['scripts_changed_since'] = sorted(l[3:].strip() for l in st.splitlines() if l.strip()) if st else []
    return out


def input_entry(rec, used=True, why=None, **extra):
    """A recipe's entry for one frame: name, observing night, folder, the RAW's SHA-256 (from its sidecar), the
    sidecar's and the solve's own SHA-256, used or not and why. No site, no altitude: those stay in the sidecar."""
    e = dict(name=rec['name'], night=rec['night'], folder=rec['folder'], sha256=rec['sha256'], sidecar_sha256=rec['sidecar_sha256'], solve_sha256=rec['solve_sha256'], schema=rec['schema'], used=bool(used))
    if why: e['why'] = why
    for k, v in extra.items():
        if v is not None: e[k] = v
    return e


def output_entry(path, kind, root=None, roots=None):
    """{file, root, kind, sha256, bytes} for a file a pipeline made. root: a name from the recipe's roots ('repo',
    'night', ...); the file is written relative to it."""
    p = os.path.abspath(os.path.expanduser(path))
    base = REPO if root == 'repo' else ((roots or {}).get(root) if root else None)
    f = os.path.relpath(p, os.path.abspath(os.path.expanduser(base))) if base else rel(p)
    return dict(file=f, root=root, kind=kind, sha256=sha256_file(p), bytes=os.path.getsize(p))


ID_LEAVES_OUT = ('id', 'made', 'git', 'outputs')


def recipe_id(recipe):
    """SHA-256 of the recipe without id, made, git and outputs: the same numbers, frames and steps give the same id,
    whenever and from whichever commit the recipe was written. The stack FITS carries it (HIERARCH OBS RECIPE ID)."""
    return hashlib.sha256(canonical({k: v for k, v in recipe.items() if k not in ID_LEAVES_OUT})).hexdigest()


def check_recipe(recipe):
    """Problems with a recipe against observatory.recipe/1 (an empty list when it conforms)."""
    bad = []
    if recipe.get('schema') != RECIPE_SCHEMA: bad.append('schema is %r' % recipe.get('schema'))
    for k in ('id', 'target', 'night', 'made', 'reproduce', 'roots', 'software', 'git', 'inputs', 'steps', 'outputs'):
        if k not in recipe: bad.append('no %s' % k)
    t = recipe.get('target') or {}
    if not isinstance(t, dict) or not t.get('name'): bad.append('target has no name')
    for i in recipe.get('inputs') or []:
        for k in ('name', 'night', 'sha256', 'used'):
            if k not in i: bad.append('input %s has no %s' % (i.get('name'), k)); break
    for o in recipe.get('outputs') or []:
        for k in ('file', 'kind', 'sha256'):
            if k not in o: bad.append('output %s has no %s' % (o.get('file'), k)); break
    for s in recipe.get('steps') or []:
        if 'step' not in s: bad.append('a step has no name')
    txt = json.dumps(recipe, default=str)
    if '/Users/' in txt: bad.append('an absolute /Users/ path')
    if re.search(r'"(site|lat|lon|latitude|longitude|sitelat|sitelong|obsgeo[^"]*)"\s*:', txt, re.I): bad.append('a site field')
    if recipe.get('id') and recipe_id(recipe) != recipe['id']: bad.append('id does not match the recipe')
    return bad


def finish_recipe(recipe, scripts=None):
    """Bring a recipe dict to observatory.recipe/1 in place of its free shape: schema first, paths scrubbed, software
    and git added if missing, the id computed last. Returns the new dict (key order: schema, id, target, night, made,
    reproduce, roots, software, git, inputs, calibration, steps, outputs, then the pipeline's own keys)."""
    r = scrub(recipe)
    r.setdefault('software', software())
    r['git'] = r.get('git') or git_info(scripts)
    r.setdefault('outputs', [])
    order = ['schema', 'id', 'target', 'night', 'made', 'reproduce', 'roots', 'software', 'git', 'inputs', 'calibration', 'steps', 'outputs']
    r['schema'] = RECIPE_SCHEMA
    out = {k: r[k] for k in order if k in r}
    out.update({k: v for k, v in r.items() if k not in out})
    out['id'] = recipe_id(out)
    return {k: out[k] for k in order if k in out} | {k: v for k, v in out.items() if k not in order}


def history_lines(recipe):
    """HISTORY lines of a recipe's steps: 'step <name>: <the step's history line>' for each, then the recipe's place."""
    out = []
    for s in recipe.get('steps') or []:
        h = s.get('history')
        if h: out.append('step %s: %s' % (s['step'], h))
    return out


def dump_recipe(recipe, path):
    json.dump(recipe, open(path, 'w'), indent=1, default=_jdefault, ensure_ascii=False)
    open(path, 'a').write('\n')


# ---------------------------------------------------------------------------------------------------- CLI

if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'frame':
        r = read_frame(sys.argv[2], exif=True)
        show = {k: v for k, v in r.items() if k not in ('sidecar', 'fits')}
        print(json.dumps(show, indent=1, default=str))
        for k, v, c in frame_cards(r): print('%-24s %-40r %s' % (k, v, c or ''))
    elif len(sys.argv) >= 3 and sys.argv[1] == 'cards':
        cards, ok = read_cards(sys.argv[2])
        for k, v, c in cards: print('%-24s %-40r %s' % (k, v, c or ''))
        print('CHECKSUM/DATASUM', 'verify' if ok else 'DO NOT verify')
    else:
        print(__doc__)
