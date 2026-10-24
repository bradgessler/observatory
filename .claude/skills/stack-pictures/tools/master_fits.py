"""Calibration masters as FITS, beside the .npz the pipelines read: IMAGETYP 'MASTER DARK' / 'MASTER FLAT', NCOMBINE,
EXPTIME, ISOSPEED, the frames' dates, the plane order, and every input frame's name and SHA-256 (docs/metadata.md,
Stage 3). darks.py, twilight_flat.py and skyflat.py call write() when they build a master; the CLI writes one for a
master already on disk.

What it writes: <master>.fits, one primary HDU, float32, NAXIS3 = 4 (the colour planes R, G1, G2, B as in the .npz;
plane pixel (X, Y) is sensor pixel (2X + ox, 2Y + oy)), the data exactly as in the .npz; CHECKSUM/DATASUM with the
master's own made_utc as the checksum comment (the same master makes the same bytes). And the master's JSON gains
schema observatory.master/1, `inputs` (name, sha256, night) and `fits` (file, sha256).

Inputs: the planes, the kind, the input frames (RAW paths: their sidecars are read when there are any, else the RAW is
hashed), the master's JSON record. Outputs: the FITS; the record, updated. Recipe entries: the JSON's `fits` block.
CLI:  python master_fits.py <master folder or .npz> [--frames-in FOLDER ...]
      writes the FITS for a master built before this tool (flat_planes.npz + flat.json, or master_*.npz + .json); the
      JSON beside it is left as it is (written once), the FITS carries the inputs."""
import argparse, glob, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import obsmeta as om

PLANES = ['R', 'G1', 'G2', 'B']


def frame_record(path):
    """read_frame for a RAW with a sidecar; without one, its name and a SHA-256 of the file itself."""
    stem = om._stem(path)
    if os.path.exists(stem + '.json'):
        try: return om.read_frame(stem)
        except ValueError: pass
    return dict(name=os.path.basename(path), sha256=om.sha256_file(path), night=None, folder=om.rel(os.path.dirname(path)), time=None)


def write(fits_path, planes, kind, inputs, rec, combine, norm=None, hot_n=None, exptime_s=None, iso=None, history=(), extra=()):
    """planes: (4, h, w). kind: 'dark' | 'flat'. inputs: frame records (frame_record). rec: the master's JSON dict (its
    made_utc is used). Returns {file, sha256}; adds schema, inputs and fits to rec."""
    data = np.ascontiguousarray(np.asarray(planes, np.float32))
    assert data.shape[0] == 4, data.shape
    exps = sorted(set(round(i['time']['exposure_s'], 4) for i in inputs if i.get('time') and i['time'].get('exposure_s')))
    if exptime_s is None and len(exps) == 1: exptime_s = exps[0]
    ex = list(extra)
    if exptime_s is None and exps: ex += [('OBS EXPTIME MIN', exps[0], '[s] shortest input'), ('OBS EXPTIME MAX', exps[-1], '[s] longest input')]
    if iso is None:
        isos = set(i['camera']['iso'] for i in inputs if i.get('camera'))
        iso = isos.pop() if len(isos) == 1 else None
    cards = om.master_cards(kind, inputs, exptime_s=exptime_s, iso=iso, combine=combine, norm=norm, hot_n=hot_n, date=(rec.get('made_utc') or '')[:19] or None,
                            extra=ex, history=history)
    sha = om.write_fits(fits_path, data, cards, 'master made %s' % (rec.get('made_utc') or 'unknown'))
    rec['schema'] = om.MASTER_SCHEMA
    rec['inputs'] = [dict(name=i['name'], sha256=i['sha256'], night=i.get('night'), folder=i.get('folder')) for i in inputs]
    rec['fits'] = dict(file=om.rel(fits_path), sha256=sha, imagetyp='MASTER ' + kind.upper(), planes=' '.join(PLANES))
    return rec['fits']


def _planes(npz):
    Z = np.load(npz)
    return np.stack([Z[k].astype(np.float32) for k in PLANES])


def backfill(target, folders=()):
    """The FITS for a master already on disk (its JSON is not changed). Returns {file, sha256, inputs}."""
    target = os.path.abspath(os.path.expanduser(target))
    if os.path.isdir(target):
        npz, js = os.path.join(target, 'flat_planes.npz'), os.path.join(target, 'flat.json')
    else:
        npz, js = target, target[:-4] + '.json'
    rec = json.load(open(js)); d = os.path.dirname(npz)
    flat = os.path.basename(js) == 'flat.json'
    mf = rec.get('made_from') or {}
    names = mf.get('frames') or rec.get('frames') or []
    look = [os.path.expanduser(f) for f in folders] + [mf.get('night') or '', d, os.path.dirname(d)]
    inputs = []
    for n in names:
        stem = om.find_frame(n, [f for f in look if f])
        if stem: inputs.append(frame_record(stem + '.ARW') if os.path.exists(stem + '.ARW') else om.read_frame(stem))
        else: inputs.append(dict(name=n, sha256=None, night=None, time=None))
    hist = []
    if flat:
        hist.append('formula: %s' % rec.get('formula', ''))
        for m in rec.get('method') or []: hist.append(m)
        sm = rec.get('small_scale_from')
        if sm:
            t = os.path.expanduser(sm['dir']); tf = os.path.join(t, 'flat_planes.fits')
            hist.append('small scale (dust, pixel response) from %s' % om.rel(t))
            if os.path.exists(tf): hist.append('its FITS sha256 %s' % om.sha256_file(tf))
        kind = 'flat'; norm = '1 at the sensor centre (central 128 x 128 plane px)'
        combine = 'per-pixel median over the frames' if rec.get('method') else 'block medians over the runs x the twilight small scale'
        hot = sum((rec.get('pixel_defects_replaced') or {}).values()) or None
    else:
        kind, combine, norm = 'dark', 'sigma-clipped mean, 3 sigma about the median (MAD)', None
        hot = sum(v.get('hot_px_over_8_sigma', 0) for v in (rec.get('planes') or {}).values()) or None
    fp = npz[:-4] + '.fits'
    r2 = dict(rec)
    out = write(fp, _planes(npz), kind, inputs, r2, combine, norm=norm, hot_n=hot, exptime_s=rec.get('exposure_s') if not flat else None,
                iso=int(mf['iso']) if mf.get('iso') not in (None, '') else rec.get('iso'), history=[om.scrub(h) for h in hist],
                extra=[('OBS MASTER JSON', os.path.basename(js), 'the record beside this file'), ('OBS MASTER NPZ SHA256', om.sha256_file(npz), 'the .npz this copies')])
    out['inputs'] = len(inputs); out['inputs_without_sidecar'] = sum(1 for i in inputs if not i.get('sha256'))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('master', nargs='+'); ap.add_argument('--frames-in', action='append', default=[])
    a = ap.parse_args()
    for m in a.master:
        print(m, json.dumps(backfill(m, a.frames_in)))
