"""Star catalogue for a field, fetched once and kept: Gaia DR3 (positions, proper motions, G, BP, RP) from VizieR.

What it does: a cone around (ra, dec) of the given radius down to a G limit, from the CDS VizieR server's plain-text
interface (asu-tsv, table I/355/gaiadr3), cached under ~/.observatory/catalogs/gaia-dr3/. A cached cone is reused for
any request inside it (same or smaller radius, same or brighter limit); the network is used only when nothing cached
covers the request. Every fetch writes a .json beside the table with the exact URL, the time, the row count and the
columns, so the recipe can say exactly what was fetched.

Why not offline: the local astrometry.net index files carry Tycho-2 BT and VT, but a 39 x 26 arcmin field at 2,084 mm
holds a few dozen Tycho stars, most of them bright enough to touch the sensor's ceiling in 15 s, and Tycho colours are
0.1 to 0.3 mag uncertain at VT 10 to 11. Gaia gives hundreds of unsaturated stars per field with BP - RP to 0.01 mag.

Inputs:  ra_deg, dec_deg, radius_deg, gmax.
Outputs: a dict of numpy arrays: source, ra, dec (ICRS, epoch 2016.0), pmra (mas/yr, times cos dec), pmdec, g, bp, rp,
         bp_rp, bp_rp_excess (phot_bp_rp_excess_factor); and the record of where it came from.
Recipe entries: catalogue{name, table, url, fetched_utc, cache_file, rows, cone{ra, dec, radius_deg, gmax}}.

CLI: python catalogue.py <ra> <dec> <radius_deg> [gmax]"""
import datetime, glob, json, os, sys, urllib.parse, urllib.request
import numpy as np

CACHE = os.path.expanduser('~/.observatory/catalogs/gaia-dr3')
SERVER = 'https://vizier.cds.unistra.fr/viz-bin/asu-tsv'
COLS = ['Source', 'RA_ICRS', 'DE_ICRS', 'pmRA', 'pmDE', 'Gmag', 'BPmag', 'RPmag', 'BP-RP', 'E(BP/RP)']
KEYS = ['source', 'ra', 'dec', 'pmra', 'pmdec', 'g', 'bp', 'rp', 'bp_rp', 'bp_rp_excess']


def _sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(np.radians, (ra1, dec1, ra2, dec2))
    return float(np.degrees(np.arccos(np.clip(np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2), -1, 1))))


def _parse(text):
    lines = [l for l in text.splitlines() if l and not l.startswith('#')]
    head = lines[0].split('\t'); data = lines[3:]                      # names, units, dashes, rows
    idx = [head.index(c) for c in COLS]
    out = {k: [] for k in KEYS}
    for l in data:
        f = l.split('\t')
        if len(f) < len(head): continue
        for k, i in zip(KEYS, idx):
            v = f[i].strip()
            out[k].append(int(v) if k == 'source' and v else (float(v) if v else np.nan))
    return {k: np.array(v) for k, v in out.items()}


def gaia_field(ra, dec, radius_deg, gmax=17.0, offline=False):
    """The Gaia DR3 stars within radius_deg of (ra, dec) brighter than gmax, and the record of where they came from."""
    os.makedirs(CACHE, exist_ok=True)
    for j in sorted(glob.glob(os.path.join(CACHE, '*.json'))):
        r = json.load(open(j)); c = r['cone']
        if c['gmax'] >= gmax and _sep_deg(ra, dec, c['ra'], c['dec']) + radius_deg <= c['radius_deg'] + 1e-9:
            cat = _parse(open(r['cache_file']).read())
            keep = (_sep(cat, ra, dec) <= radius_deg) & (cat['g'] <= gmax)
            return {k: v[keep] for k, v in cat.items()}, dict(r, used_from_cache=True, rows_used=int(keep.sum()))
    if offline:
        raise SystemExit('no cached Gaia cone covers (%.4f, %.4f) r %.3f deg G < %.1f, and offline was asked' % (ra, dec, radius_deg, gmax))
    q = {'-source': 'I/355/gaiadr3', '-c': '%.6f %+.6f' % (ra, dec), '-c.rd': '%.4f' % radius_deg, '-out': ','.join(COLS), 'Gmag': '<%.2f' % gmax, '-out.max': 'unlimited'}
    url = SERVER + '?' + urllib.parse.urlencode(q)
    text = urllib.request.urlopen(url, timeout=120).read().decode('utf-8', 'replace')
    stem = 'gaiadr3_ra%.4f_dec%+.4f_r%.3f_G%.1f' % (ra, dec, radius_deg, gmax)
    path = os.path.join(CACHE, stem + '.tsv')
    open(path, 'w').write(text)
    cat = _parse(text)
    rec = dict(name='Gaia DR3', table='I/355/gaiadr3 (VizieR, CDS)', url=url, fetched_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
               cache_file=path, rows=int(len(cat['g'])), columns=COLS, cone=dict(ra=ra, dec=dec, radius_deg=radius_deg, gmax=gmax),
               epoch='positions at 2016.0 (ICRS); move them with the proper motions to the night')
    json.dump(rec, open(os.path.join(CACHE, stem + '.json'), 'w'), indent=1)
    return cat, dict(rec, used_from_cache=False, rows_used=rec['rows'])


def _sep(cat, ra, dec):
    r1, d1, r2, d2 = np.radians(cat['ra']), np.radians(cat['dec']), np.radians(ra), np.radians(dec)
    return np.degrees(np.arccos(np.clip(np.sin(d1) * np.sin(d2) + np.cos(d1) * np.cos(d2) * np.cos(r1 - r2), -1, 1)))


def at_epoch(cat, year):
    """RA, Dec moved from 2016.0 to `year` with the proper motions (missing proper motion: not moved)."""
    dt = year - 2016.0
    pmra = np.nan_to_num(cat['pmra']); pmdec = np.nan_to_num(cat['pmdec'])
    dec = cat['dec'] + pmdec * dt / 3.6e6
    ra = cat['ra'] + pmra * dt / 3.6e6 / np.cos(np.radians(cat['dec']))
    return ra, dec


if __name__ == '__main__':
    a = sys.argv[1:]
    cat, rec = gaia_field(float(a[0]), float(a[1]), float(a[2]), float(a[3]) if len(a) > 3 else 17.0)
    print(json.dumps(rec, indent=1)); print(len(cat['g']), 'stars; G', np.nanmin(cat['g']), '..', np.nanmax(cat['g']))
