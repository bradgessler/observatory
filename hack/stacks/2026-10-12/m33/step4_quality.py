"""Step 4: per-frame transparency, star size and smear, from the same stars in every frame.

Quality stars: in the reference frame, not saturated, no neighbour within 40 sensor px, flux >= QFLUX, and compact
(half-flux radius within 1.25 x the median of such stars: M33's HII regions and clusters are left out). Each is found
in every frame through the registration (within 4 px of where it should be).

  transparency   each star's aperture flux over that star's median over the run, median over stars (1.0 = a typical
                 frame of this run; lower = light lost on the way)
  HFD            half-flux diameter, median over the stars, sensor px and arcsec (0.388 arcsec per sensor px)
  elongation     median over stars of sqrt(major / minor second moment)
  smear          the common-direction ellipticity: mean over stars of e exp(2 i theta). Trailing (a drift or a hold
                 settling during the exposure) stretches every star the same way; seeing does not.
  noise          the frame's own pixel noise at zero level (from step 2's noise model, a + b x level)."""
import json, numpy as np
from common import *

QFLUX = 20000.0
res = json.load(open(W('step2_stars.json'))); by = {r['stamp']: r for r in res}
T = json.load(open(W('step3_transforms.json'))); tr = {o['stamp']: o for o in T['transforms']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
cand = [s for s in by[REF_STAMP]['stars'] if not s['saturated'] and s['nearest'] > 40 and s['flux'] >= QFLUX]
hmed = np.median([s['hfr'] for s in cand])
ref = [s for s in cand if s['hfr'] <= 1.25 * hmed]
refxy = np.array([nat(s) for s in ref])
print('quality stars: %d of %d bright isolated sources in the reference are compact (HFR <= 1.25 x %.2f plane px)' % (len(ref), len(cand), hmed))
table = {}
for s, o in tr.items():
    R = np.array(o['R']); t = np.array(o['t']); r = by[s]
    xy = np.array([nat(k) for k in r['stars']])
    row = {}
    for i in range(len(ref)):
        p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not r['stars'][j]['saturated']: row[i] = r['stars'][j]
    table[s] = row
med = {i: {k: float(np.median([table[s][i][k] for s in table if i in table[s]])) for k in ('hfr', 'flux', 'peak')} for i in range(len(ref)) if sum(i in table[s] for s in table) >= 12}
out = []
for s in sorted(table):
    row = table[s]; ids = [i for i in row if i in med]
    fl = float(np.median([row[i]['flux'] / med[i]['flux'] for i in ids]))
    hfd = float(np.median([4 * row[i]['hfr'] for i in ids]))
    el = float(np.median([row[i]['elong'] for i in ids]))
    pk = float(np.median([row[i]['peak'] / med[i]['peak'] for i in ids]))
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in ids])
    sig_rms = float(np.median([np.sqrt((row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) / 2) for i in ids]))
    nm = by[s]['noise_model']
    out.append(dict(stamp=s, stars_matched=len(ids), transparency=fl, peak_rel=pk, hfd_px=hfd, hfd_arcsec=hfd * SCALE, elong_median=el, smear=float(abs(e)), smear_angle_deg=float(np.degrees(np.angle(e)) / 2),
                    sigma_rms_px=2 * sig_rms, noise_zero_dn=float(np.sqrt(max(nm['a'], 1))), noise_model=nm, since_slew_s=s1[s]['since_slew_s'], box_star_size_arcsec=s1[s]['box_star_size_arcsec'],
                    step_from_previous_px=None))
prev = None
for o in out:
    c = np.array(tr[o['stamp']]['shift_at_centre_px'])
    if prev is not None: o['step_from_previous_px'] = float(np.hypot(*(c - prev)))
    prev = c
for o in out:
    print('%s stars %2d  T %.3f  peak %.3f  HFD %.2f px = %.2f"  elong %.3f  smear %.3f @%+4.0f  noise %.1f  step %s  (box said %s")' % (o['stamp'], o['stars_matched'], o['transparency'], o['peak_rel'], o['hfd_px'], o['hfd_arcsec'], o['elong_median'], o['smear'], o['smear_angle_deg'], o['noise_zero_dn'], '%.1f' % o['step_from_previous_px'] if o['step_from_previous_px'] is not None else '-', o['box_star_size_arcsec']))
jdump(dict(quality=out, quality_stars=len(med), qflux=QFLUX, compact_hfr_limit_plane_px=1.25 * hmed, star_xy={str(i): refxy[i].tolist() for i in med}, star_medians={str(i): med[i] for i in med}), 'step4_quality.json')
