"""Step 4: each frame's quality from the same stars in every frame, then which frames go into the stack and with what
weight. The rule is fixed here and recorded.

Quality stars: sources of the reference with flux >= Q_MIN_FLUX DN, star-like (half-flux radius within 0.6 to 1.5 x
the median of the bright ones: the nebula itself is left out), found in 80% or more of the frames.
  transparency   the median, over those stars, of each star's flux against its own median over the run, scaled so the
                 clearest frame is 1 (cloud dims the stars; sky brightness alone misleads)
  star size      median half-flux diameter (sensor px and arcsec at 0.388)
  star shape     median elongation, and the common-direction ellipticity |mean((a^2 - b^2) / (a^2 + b^2) e^(2 i theta))|:
                 when the mount moves during the exposure every star is stretched the same way
  the mount      from the sidecar: seconds since the last slew, and how far each axis turned between shutter open and
                 close (tracking alone turns the hour-angle axis by about 60 arcsec in 4 s and the other by 1 or 2)
A frame is dropped if: it is the first frame of the series after the slew (DROP_FIRST: the skill's rule, whatever it
measures; N2392_DROP_FIRST=0 keeps it); taken less than SLEW_MIN_S after a slew; an axis turned more than AXIS_TOL arcsec away from the
run's median during the exposure (the mount was still moving); common-direction ellipticity above COH_MAX; star size
above HFD_MAX_ARCSEC or above HFD_MAX_REL x the median of the clear frames; transparency under T_MIN; registration
failed or its weighted rms above WRMS_MAX px. (The skill's 8 October rules.)
Used frames are multiplied by 1 / transparency and averaged with weight (transparency / noise)^2."""
import os
import numpy as np
from common import *

DROP_FIRST = os.environ.get('N2392_DROP_FIRST', '1') == '1'
LIMITS = dict(drop_first_frame_after_the_slew=DROP_FIRST, slew_min_s=10.0, axis_tol_arcsec=20.0, coh_max=0.20, hfd_max_arcsec=float(os.environ.get('N2392_HFD_MAX', '6.5')), hfd_max_rel=1.20, t_min=0.50, wrms_max_px=1.5, clear_min=0.90,
              q_min_flux=float(os.environ.get('N2392_Q_MIN_FLUX', '6000')))
res = json.load(open(W('step2_stars.json'))); by = {r['stamp']: r for r in res}
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
ref = by[REF]
A0 = np.array([nat(s) for s in ref['stars']]); F0 = np.array([s['flux'] for s in ref['stars']]); R0 = np.array([s['hfr'] for s in ref['stars']])
hfr_med = float(np.median(R0[F0 >= LIMITS['q_min_flux']]))
cand = [i for i in range(len(A0)) if F0[i] >= LIMITS['q_min_flux'] and 0.6 * hfr_med <= R0[i] <= 1.5 * hfr_med and not ref['stars'][i]['saturated']]
table = {}
for s, o in tr.items():
    if o['failed']: continue
    xy = np.array([nat(k) for k in by[s]['stars']]); P = A0[cand] @ np.array(o['R']).T + np.array(o['t']); row = {}
    for i, p in zip(cand, P):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not by[s]['stars'][j]['saturated']: row[i] = by[s]['stars'][j]
    table[s] = row
qstars = [i for i in cand if sum(i in table[s] for s in table) >= 0.8 * len(table)]
print('quality stars (flux >= %.0f in the reference, star-like, found in >= 80%% of frames): %d of %d sources; reference median half-flux radius %.2f plane px' % (LIMITS['q_min_flux'], len(qstars), len(A0), hfr_med))
med = {i: float(np.median([table[s][i]['flux'] for s in table if i in table[s]])) for i in qstars}
turn = np.array([s1[s]['mount_axes_turned_arcsec'] for s in sorted(s1) if s1[s]['mount_axes_turned_arcsec']]); turn_med = np.median(turn, axis=0)
Q = {}
for s in sorted(table):
    row = table[s]; ii = [i for i in qstars if i in row]
    ratio = np.array([row[i]['flux'] / med[i] for i in ii])
    hfd = np.array([4 * row[i]['hfr'] for i in ii]); el = np.array([row[i]['elong'] for i in ii])
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in ii])
    Q[s] = dict(n=len(ii), flux_ratio=float(np.median(ratio)), flux_ratio_scatter=float(1.4826 * np.median(np.abs(ratio - np.median(ratio)))), hfd_px=float(np.median(hfd)), hfd_arcsec=float(np.median(hfd) * SCALE),
                elong=float(np.median(el)), coh=float(abs(e)), coh_angle_deg=float(np.degrees(np.angle(e)) / 2))
top = max(q['flux_ratio'] for q in Q.values())
for q in Q.values(): q['transparency'] = q['flux_ratio'] / top
clear = [s for s in Q if Q[s]['transparency'] >= LIMITS['clear_min'] and (s1[s]['since_slew_s'] or 0) >= LIMITS['slew_min_s']]
hfd_clear = float(np.median([Q[s]['hfd_px'] for s in clear]))
# pixel noise: the plane's own neighbouring-pixel differences would be better than step 1's quantised MAD, but the
# frames are alike (same exposure, same sky within 10%): the noise factor is 1 for all, the weight is transparency^2
use, rej = [], []
for s in sorted(tr):
    o = tr[s]; f = s1[s]; why = []
    if o['failed']: rej.append(dict(stamp=s, why='registration failed')); continue
    q = Q[s]; t = q['transparency']
    if DROP_FIRST and s == min(tr): why.append('the first frame of the series after the slew (taken %.0f s after it): dropped by rule' % (f['since_slew_s'] or 0))
    if f['since_slew_s'] is not None and f['since_slew_s'] < LIMITS['slew_min_s']: why.append('taken %.1f s after a move (limit %.0f s)' % (f['since_slew_s'], LIMITS['slew_min_s']))
    if f['mount_axes_turned_arcsec'] is not None and np.abs(np.array(f['mount_axes_turned_arcsec']) - turn_med).max() > LIMITS['axis_tol_arcsec']:
        why.append('the mount was moving during the exposure: its axes turned %+.0f and %+.0f arcsec between shutter open and close (tracking alone: %+.0f and %+.0f)' % (*f['mount_axes_turned_arcsec'], *turn_med))
    if q['coh'] > LIMITS['coh_max']: why.append('stars stretched in one direction (common ellipticity %.2f, limit %.2f): trailing' % (q['coh'], LIMITS['coh_max']))
    if q['hfd_arcsec'] > LIMITS['hfd_max_arcsec']: why.append('stars %.2f arcsec half-flux diameter (limit %.1f)' % (q['hfd_arcsec'], LIMITS['hfd_max_arcsec']))
    elif q['hfd_px'] > LIMITS['hfd_max_rel'] * hfd_clear: why.append('stars %.0f%% wider than the clear frames (limit %.0f%%)' % (100 * (q['hfd_px'] / hfd_clear - 1), 100 * (LIMITS['hfd_max_rel'] - 1)))
    if t < LIMITS['t_min']: why.append('cloud: stars at %.0f%% of the clearest frame (limit %.0f%%)' % (100 * t, 100 * LIMITS['t_min']))
    if o['wrms_px'] > LIMITS['wrms_max_px']: why.append('registration rms %.2f px' % o['wrms_px'])
    rec = dict(stamp=s, transparency=t, hfd_px=q['hfd_px'], hfd_arcsec=q['hfd_arcsec'], elong=q['elong'], common_ellipticity=q['coh'], quality_stars=q['n'], since_slew_s=f['since_slew_s'], mount_axes_turned_arcsec=f['mount_axes_turned_arcsec'],
               registration_wrms_px=o['wrms_px'], run=1)
    if why: rej.append(dict(rec, why='; '.join(why)))
    else: use.append(dict(rec, scale=1.0 / t, noise_rel=1.0 / t, weight=t ** 2))
wsum = sum(u['weight'] for u in use)
jdump(dict(limits=LIMITS, quality_stars=len(qstars), tracking_turn_median_arcsec=turn_med.tolist(), hfd_clear_median_px=hfd_clear, hfd_clear_median_arcsec=hfd_clear * SCALE,
           used=use, rejected=rej, sum_of_weights=wsum, quality=Q), 'step4_select.json')
for s in sorted(tr):
    if s not in Q: print('  drop %s registration failed' % s); continue
    q = Q[s]; u = [x for x in use if x['stamp'] == s]
    line = 'T %.3f (scatter %.3f, n %2d)  HFD %.1f px %.2f"  elong %.2f  common %.3f  since slew %5.0f s  wrms %.2f' % (q['transparency'], q['flux_ratio_scatter'], q['n'], q['hfd_px'], q['hfd_arcsec'], q['elong'], q['coh'], s1[s]['since_slew_s'] or 0, tr[s]['wrms_px'])
    print(('  use  %s  %s  weight %.3f' % (s, line, u[0]['weight'])) if u else ('  DROP %s  %s  | %s' % (s, line, [x for x in rej if x['stamp'] == s][0]['why'])))
print('used %d of %d (one run: %d, %d); clear-frame median star size %.1f px = %.2f arcsec; sum of weights %.2f' % (len(use), len(tr), sum(u['run'] == 1 for u in use), sum(u['run'] == 2 for u in use), hfd_clear, hfd_clear * SCALE, wsum))
