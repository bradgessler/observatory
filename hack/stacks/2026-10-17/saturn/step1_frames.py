"""Step 1: which frames are Saturn's. Every frame of the session window (common.T0..T1) with its sidecar facts and the
RAW's own exposure and ISO (trusted over the sidecar). Planet frames: 1/60 s at ISO 800 pointed at Saturn. Moon frames:
2 s at ISO 6400 pointed at Saturn (the centring frames, planet blown out). Writes work/frames.json."""
import glob, json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from common import *

def one(f):
    b = os.path.basename(f); j = json.load(open(f[:-4] + '.json')); cam = j.get('camera') or {}; pt = j.get('pointing') or {}
    sv = f[:-4] + '.solve.json'; so = json.load(open(sv)) if os.path.exists(sv) else {}
    e, iso = raw_exif(f)
    sep = float(np.hypot((pt.get('ra_deg', 0) - SATURN_POINTING[0]) * np.cos(np.radians(SATURN_POINTING[1])), pt.get('dec_deg', 0) - SATURN_POINTING[1]))
    return dict(name=b, exposure_s=e, iso=iso, sidecar_shutter=cam.get('shutter'), sidecar_iso=cam.get('iso'), sidecar_agrees=(cam.get('iso') == iso and abs((cam.get('exposure_s') or 0) - e) < 1e-3),
                pointing_ra_dec=[pt.get('ra_deg'), pt.get('dec_deg')], pointing_from_saturn_deg=round(sep, 3), alt_deg=pt.get('alt_deg'),
                since_slew_s=(j.get('settle') or {}).get('since_slew_s'), shutter_pressed=(j.get('time') or {}).get('shutter_pressed'),
                solve=so.get('solution') if so.get('state') == 'solved' else None, solve_state=so.get('state'),
                arw_sha256={x['format']: x['sha256'] for x in j.get('files', [])}.get('arw'))

if __name__ == '__main__':
    files = [f for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))) if T0 <= os.path.basename(f)[9:15] <= T1]
    with ProcessPoolExecutor(WORKERS) as ex: rows = list(ex.map(one, files))
    at = [r for r in rows if r['pointing_from_saturn_deg'] < 0.5]
    planet = [r['name'] for r in at if abs(r['exposure_s'] - 1 / 60) < 1e-4 and r['iso'] == 800]
    moons = [r['name'] for r in at if r['exposure_s'] >= 1.0]
    other = [r['name'] for r in rows if r['name'] not in planet and r['name'] not in moons]
    jsave('frames.json', dict(window_utc=[T0, T1], every_frame=rows, planet=planet, moons=moons, not_saturn=other))
    print('%d frames in the window: %d planet frames (1/60 s, ISO 800), %d moon frames (%s), %d elsewhere or other settings' % (len(rows), len(planet), len(moons), ', '.join('%s %.0f s ISO %d' % (r['name'][9:15], r['exposure_s'], r['iso']) for r in at if r['name'] in moons), len(other)))
    print('sidecar disagrees with the RAW on', [r['name'] for r in rows if not r['sidecar_agrees']])
    print('planet frames from', planet[0], 'to', planet[-1])
