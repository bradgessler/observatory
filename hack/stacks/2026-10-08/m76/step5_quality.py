"""Step 5: per-frame star width, elongation, trailing and transparency from the same stars in every frame, then
which frames go in and with what weight. The rule is fixed here and recorded; a frame is dropped if any limit is
crossed. Transparency is each frame's star flux against the clearest frame's (median over the same unsaturated
stars), so cloud shows as dimmer stars whatever the sky does. Adapted from ../../2026-10-03/ngc7662/step4_quality.py
and ../../2026-10-03/m15/step4c_select.py."""
import json, os, numpy as np
from common import *

LIMITS = dict(transparency_min=0.90, hfd_max_rel=1.20, elongation_max=1.45, registration_wrms_max_px=1.0)
res = json.load(open(W('step3_stars.json'))); tr = json.load(open(W('step4_transforms.json'))); s2 = json.load(open(W('step2.json')))
f2 = {f['stamp']: f for f in s2['frames']}
by = {r['stamp']: r for r in res}; ref = by[REF_STAMP]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])
neb = json.load(open(W('step1_solve.json')))
nebref = [s for s in neb if s['stamp'] == REF_STAMP]
bright = [i for i in range(len(refxy)) if refflux[i] >= 30000 and max(ref['stars'][i]['plane_max']) < 14000]
table = {}
for o in tr:
    R = np.array(o['R']); t = np.array(o['t']); r = by[o['stamp']]
    xy = np.array([nat(s) for s in r['stars']])
    row = {}
    for i in bright:
        p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and max(r['stars'][j]['plane_max']) < 14000: row[i] = r['stars'][j]
    table[o['stamp']] = row
common_ = [i for i in bright if all(i in table[s] for s in table)]
print('quality stars (flux >= 30000, unsaturated, in every frame):', len(common_))
med = {i: {k: float(np.median([table[s][i][k] for s in table])) for k in ('hfr', 'flux')} for i in common_}
q = []
for s, row in table.items():
    hfd_px = float(np.median([2 * row[i]['hfr'] for i in common_]))          # plane px
    hfr_rel = float(np.median([row[i]['hfr'] / med[i]['hfr'] for i in common_]))
    el = float(np.median([row[i]['elong'] for i in common_]))
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in common_])
    fl = float(np.median([row[i]['flux'] / med[i]['flux'] for i in common_]))
    pk = float(np.median([row[i]['peak'] for i in common_]))
    q.append(dict(stamp=s, hfd_plane_px=hfd_px, hfd_arcsec=hfd_px * 2 * SCALE_SENSOR, hfr_rel=hfr_rel, elong_median=el, coherent_ellipticity=float(abs(e)), coherent_angle_deg=float(np.degrees(np.angle(e)) / 2),
                  flux_rel_median=fl, peak_median=pk, stars_detected=len(by[s]['stars'])))
top = max(o['flux_rel_median'] for o in q)
clearest = [o['stamp'] for o in q if o['flux_rel_median'] == top][0]
for o in q:
    o['transparency'] = o['flux_rel_median'] / top
hfd_med = float(np.median([o['hfd_plane_px'] for o in q]))
sig_g = {s: (f2[s]['bg'][1]['clipped_std'] ** 2 + f2[s]['bg'][2]['clipped_std'] ** 2) ** 0.5 / 2 for s in table}
sig_med = float(np.median(list(sig_g.values())))
tt = {o['stamp']: o for o in tr}
use, rej = [], []
for o in q:
    why = []
    if o['transparency'] < LIMITS['transparency_min']: why.append('stars %.1f%% dimmer than in the clearest frame (limit 10%%): cloud or haze' % (100 * (1 - o['transparency'])))
    if o['hfd_plane_px'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the run median %.2f (limit 20%%)' % (o['hfd_arcsec'], 100 * (o['hfd_plane_px'] / hfd_med - 1), hfd_med * 2 * SCALE_SENSOR))
    if o['elong_median'] > LIMITS['elongation_max']: why.append('stars elongated %.2f : 1 (limit %.2f; run median %.2f), all leaning the same way (common ellipticity %.2f at %+.0f deg): the tube moved during the exposure' % (o['elong_median'], LIMITS['elongation_max'], float(np.median([x['elong_median'] for x in q])), o['coherent_ellipticity'], o['coherent_angle_deg']))
    if tt[o['stamp']]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % tt[o['stamp']]['wrms_px'])
    # weight: inverse variance of the frame after its stars are scaled to the clearest frame's brightness
    o['sky_noise_green_dn'] = sig_g[o['stamp']]
    o['weight_raw'] = o['transparency'] ** 2 * (sig_med / sig_g[o['stamp']]) ** 2
    o['why_dropped'] = '; '.join(why)
    (rej if why else use).append(o)
wsum = sum(o['weight_raw'] for o in use)
for o in q: o['weight'] = (o['weight_raw'] / wsum * len(use)) if not o['why_dropped'] else 0.0
for o in q:
    print('%s HFD %.2f px (%.2f") rel %.3f  elong %.3f  coh_e %.3f @%+4.0f  transparency %.3f  sky sigma %.1f  weight %.3f %s' % (o['stamp'], o['hfd_plane_px'], o['hfd_arcsec'], o['hfr_rel'], o['elong_median'], o['coherent_ellipticity'], o['coherent_angle_deg'], o['transparency'], o['sky_noise_green_dn'], o['weight'], ('DROP: ' + o['why_dropped']) if o['why_dropped'] else ''))
n_eff = sum(o['weight'] for o in use) ** 2 / sum(o['weight'] ** 2 for o in use)
print('clearest frame', clearest, '; run median HFD %.2f plane px = %.2f arcsec' % (hfd_med, hfd_med * 2 * SCALE_SENSOR))
print('used', len(use), 'dropped', len(rej), '; effective number of frames with these weights %.2f' % n_eff)
open(W('use.txt'), 'w').write('\n'.join(o['stamp'] for o in use) + '\n')
json.dump(dict(limits=LIMITS, quality=q, clearest_frame=clearest, hfd_run_median_plane_px=hfd_med, quality_star_ref_index=common_, used=[o['stamp'] for o in use],
               rejected=[dict(stamp=o['stamp'], why=o['why_dropped']) for o in rej], weights={o['stamp']: o['weight'] for o in use}, effective_frames=n_eff,
               weight_rule='w = transparency^2 x (median sky sigma / frame sky sigma)^2, normalised to mean 1 over the used frames; each frame is also divided by its transparency before combining, so a star is equally bright in every frame'),
          open(W('step5_quality.json'), 'w'), indent=1)
