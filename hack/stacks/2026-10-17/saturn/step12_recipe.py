"""Step 12: final/recipe.json, every number that shaped the pictures, gathered from the steps' own records (work/*.json),
with the SHA-256 of every RAW used (from its sidecar) and of every delivered file."""
import hashlib
from common import *
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
if __name__ == '__main__':
    fr = jload('frames.json'); g = jload('grades.json'); se = jload('select.json'); st = jload('stack.json'); ti = jload('titan.json'); rs = jload('restore.json'); mo = jload('moons.json'); co = jload('compose.json'); eph = jload('ephemeris.json')
    fin = json.load(open(os.path.join(FINAL, 'saturn-finished.json')))
    rawsha = {r['name']: r['arw_sha256'] for r in fr['every_frame']}; kept = set(st['frames'])
    every = []
    for r in g:
        rk = next((x['rank'] for x in se['ranked'] if x['name'] == r['name']), None)
        every.append(dict(frame=r['name'], sha256=rawsha[r['name']], sharpness=r.get('sharp'), rank=rk, flux=r.get('flux'), ring_line_deg=r.get('ring_line_deg'),
                          fate='kept' if r['name'] in kept else ('usable, not among the sharpest %d' % st['keep'] if rk else 'dropped: ' + (r.get('why') or 'light outside 0.8 to 1.25 of the median'))))
    out = dict(what='Saturn and five of its moons, night of 17/18 October 2026 (frames of 18 October UTC)', scripts='hack/stacks/2026-10-17/saturn (run_all.sh)',
               camera='Sony a6000 (ILCE-6000), RAW, prime focus', telescope='Celestron 8SE, 203 mm, %.0f mm by plate solve' % FL_MM, mount='Sky-Watcher EQ6-R, unguided, not dithered',
               frames=dict(window_utc=fr['window_utc'], planet=len(fr['planet']), moons=fr['moons'], exposure_planet='1/60 s ISO 800 (RAW EXIF)', exposure_moons='2 s ISO 6400 (RAW EXIF)', sidecar_disagreements=[r['name'] for r in fr['every_frame'] if not r['sidecar_agrees']]),
               ephemeris=dict(source=eph['source'], queries=eph['queries'], ring_opening_deg=eph['ring_opening_deg'][2], north_pole_pa_deg=eph['north_pole_pa_deg'][2], equatorial_diameter_arcsec=eph['equatorial_diameter_arcsec'][2], distance_au=eph['distance_au'][2]),
               selection=dict(turn_deg_per_minute=se['turn_deg_per_minute'], ring_line_scatter_deg=se['ring_line_scatter_deg'], reference_minute_utc=se['reference_minute_utc'], flux_band=se['flux_band'], dropped_for_flux=se['dropped_for_flux'],
                              counts_compared=se['counts'], step4_rule_choice=se['chosen'], soft=se['soft'], kept=st['keep'],
                              why_kept='plain stacks: 8 to 25 one plateau (within 3%), 5 sharper by gap contrast (0.145 vs 0.127); restored: 25 beats 5 (gap contrast 0.359 vs 0.313) with 0.0059 vs 0.0135 grain and Titan at 18 vs 8 sigma; checks/k5-vs-k25-rounds-0-8-12-20.png'),
               stack={k: v for k, v in st.items() if k not in ('frames',)}, titan_blur=ti, restoration={k: v for k, v in rs.items()}, moons=mo, composite=co, finish=fin, every_frame=every)
    files = {}
    for d_, names in ((FINAL, ['saturn.png', 'saturn-finished.png', 'saturn-finished.jpg']), (os.path.join(HERE, 'share'), ['saturn.jpg', 'saturn-annotated.jpg', 'saturn-how.jpg'])):
        for n in names: files[os.path.relpath(os.path.join(d_, n), HERE)] = sha(os.path.join(d_, n))
    out['delivered_sha256'] = files
    json.dump(out, open(os.path.join(FINAL, 'recipe.json'), 'w'), indent=1)
    print('final/recipe.json:', len(every), 'frames listed;', files)
