"""Step 3: where Saturn's moons were, from JPL Horizons (ssd.jpl.nasa.gov/api/horizons.api), geocentric astrometric RA and
Dec every minute from 05:20 to 07:26 UTC 18 October 2026, for Saturn (699) and Mimas to Iapetus (601-608); and Saturn's
sub-observer latitude (the rings' opening, quantity 14) its north pole's position angle (17), its equatorial diameter (13) and distance (20). Geocentric, so
no site is sent; the parallax between Saturn and a moon is under 0.01 arcsec. The answers are cached beside the scripts
(horizons/) with the queries; SAT_HORIZONS_REFRESH=1 asks again. Only positions come from here: names are given to points
found in the pictures, never drawn where nothing is. Writes work/ephemeris.json (offsets from Saturn, arcsec east and north)."""
import urllib.parse, urllib.request
from common import *
BODIES = {'699': 'Saturn', '601': 'Mimas', '602': 'Enceladus', '603': 'Tethys', '604': 'Dione', '605': 'Rhea', '606': 'Titan', '607': 'Hyperion', '608': 'Iapetus'}
START, STOP, STEP = '2026-10-18 05:20', '2026-10-18 07:26', '1m'

def query(cmd):
    d = os.path.join(HERE, 'horizons'); os.makedirs(d, exist_ok=True); f = os.path.join(d, cmd + '.txt')
    q = dict(format='text', COMMAND="'%s'" % cmd, EPHEM_TYPE='OBSERVER', CENTER="'500@399'", START_TIME="'%s'" % START, STOP_TIME="'%s'" % STOP, STEP_SIZE="'%s'" % STEP,
             QUANTITIES="'1,13,14,17,20'" if cmd == '699' else "'1'", ANG_FORMAT='DEG', CSV_FORMAT='YES', EXTRA_PREC='YES')
    url = 'https://ssd.jpl.nasa.gov/api/horizons.api?' + urllib.parse.urlencode(q)
    if not os.path.exists(f) or os.environ.get('SAT_HORIZONS_REFRESH') == '1':
        txt = urllib.request.urlopen(url, timeout=60).read().decode(); open(f, 'w').write(txt); print('asked Horizons for', BODIES[cmd])
    txt = open(f).read(); body = txt.split('$$SOE')[1].split('$$EOE')[0].strip().splitlines(); rows = []
    for ln in body:
        c = [x.strip() for x in ln.split(',')]
        t = c[0]; hh, mm = int(t[-5:-3]), int(t[-2:]); r = dict(minute=hh * 60 + mm, ra=float(c[3]), dec=float(c[4]))
        if cmd == '699': r.update(ang_diam=float(c[5]), sub_lon=float(c[6]), sub_lat=float(c[7]), np_pa=float(c[8]), np_dist=float(c[9]), delta_au=float(c[10]))
        rows.append(r)
    return rows, url

if __name__ == '__main__':
    eph = {}; urls = {}
    for cmd in BODIES: eph[BODIES[cmd]], urls[BODIES[cmd]] = query(cmd)
    sat = eph['Saturn']; out = dict(source='JPL Horizons, geocentric astrometric (ICRF), ' + START + ' to ' + STOP + ' UTC every ' + STEP, queries=urls, minutes=[r['minute'] for r in sat],
                                    saturn_ra_dec=[[r['ra'], r['dec']] for r in sat], ring_opening_deg=[r['sub_lat'] for r in sat], north_pole_pa_deg=[r['np_pa'] for r in sat], equatorial_diameter_arcsec=[r['ang_diam'] for r in sat], distance_au=[r['delta_au'] for r in sat], moons={})
    for name, rows in eph.items():
        if name == 'Saturn': continue
        off = [[(m['ra'] - s['ra']) * np.cos(np.radians(s['dec'])) * 3600, (m['dec'] - s['dec']) * 3600] for m, s in zip(rows, sat)]
        out['moons'][name] = off
    jsave('ephemeris.json', out)
    i = out['minutes'].index(5 * 60 + 22)
    print('Saturn at 05:22 UTC: RA %.4f Dec %.4f; rings open %.2f deg (sub-observer latitude); north pole at position angle %.2f deg; %.2f arcsec across the equator; %.4f au away' % (*out['saturn_ra_dec'][i], out['ring_opening_deg'][i], out['north_pole_pa_deg'][i], out['equatorial_diameter_arcsec'][i], out['distance_au'][i]))
    for n, o in out['moons'].items():
        e, nn = o[i]; e2, n2 = o[-1]; print('  %-9s 05:22: %7.1f E %7.1f N arcsec (%.1f from Saturn, PA %.1f); 07:26: %7.1f E %7.1f N' % (n, e, nn, np.hypot(e, nn), np.degrees(np.arctan2(e, nn)) % 360, e2, n2))
