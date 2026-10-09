"""Step 5: per-frame transparency, star width and elongation inside each set, and which frames are used.
The measures and limits of the M31 mosaic run (m5_quality_select.py).

Transparency is RELATIVE TO THE SET'S OWN CLEAREST FRAMES: each star's aperture flux over that star's median flux
in the set's clear frames (first pass: 90th percentile over the set; clear = within 7% of that), median over the
stars. Whether a set's clearest frames were themselves under thin cloud cannot be seen inside the set; that is
measured later against the deep stack from the stars they share (step 8).

A frame is used if: transparency >= 0.80, even across the field (straight-line fit of star brightness against
position changes by less than 10% per 3000 px), registration rms <= 1.0 px, stars no wider than 1.30 x the set's
clear median and median elongation <= 1.60. Used frames are multiplied by 1 / transparency and averaged with
weight (transparency / noise)^2, noise = the frame's sky noise (its darkest block) over the set's clear median:
a frame under a brighter sky (thin cloud, the Moon, morning twilight) counts for less, in proportion to what
its faint parts are worth. For the 20 s sets a frame whose weight would be under 0.30 is left out: it would add
under a third of a clear frame's signal and carries the gradients of a bright sky."""
import json, numpy as np
from common import *

LIMITS = dict(transparency_min=0.80, tilt_max=0.10, hfd_max_rel=1.30, elongation_max=1.60, registration_wrms_max_px=1.0, clear_min=0.93, weight_min=0.30)
s1l = json.load(open(W('s1.json')))['frames']; s1 = {f['stamp']: f for f in s1l}
res = json.load(open(W('s3_stars.json'))); by = {r['stamp']: r for r in res}
T4 = json.load(open(W('s4_transforms.json')))
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])

out = {}
for name in T4:
    QFLUX = 4000.0 if name == 'short' else 30000.0
    tr = T4[name]['transforms']; trby = {o['stamp']: o for o in tr}
    okf = [o for o in tr if not o.get('failed')]
    # the frame whose stars are followed through the set: the registered frame with the most bright, clean stars
    def qstars(s): return [k for k in by[s]['stars'] if k['r_core'] > CORE_RADIUS and not k['saturated'] and k['nearest'] > 40 and k['flux'] >= QFLUX]
    q_stamp = max([o['stamp'] for o in okf], key=lambda s: len(qstars(s)))
    Rq = np.array(trby[q_stamp]['R']); tq = np.array(trby[q_stamp]['t'])
    ref = qstars(q_stamp); refxy = (np.array([nat(s) for s in ref]) - tq) @ Rq          # in the reference grid: R^T (x - t)
    table = {}
    for o in tr:
        if o.get('failed'): table[o['stamp']] = {}; continue
        R = np.array(o['R']); t = np.array(o['t']); r = by[o['stamp']]
        xy = np.array([nat(s) for s in r['stars']]); row = {}
        for i in range(len(ref)):
            p = refxy[i] @ R.T + t; d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < 4 and not r['stars'][j]['saturated']: row[i] = dict(r['stars'][j], pos=p.tolist())
        table[o['stamp']] = row
    nfr = len(tr); need = min(3, nfr)
    clearflux = {}
    for i in range(len(ref)):
        v = [table[s][i]['flux'] for s in table if i in table[s]]
        if len(v) >= need: clearflux[i] = float(np.percentile(v, 90))
    def bright(row):
        v = [row[i]['flux'] / clearflux[i] for i in row if i in clearflux]
        return float(np.median(v)) if len(v) >= 5 else None
    b0 = {s: bright(table[s]) for s in table}
    top = max(v for v in b0.values() if v is not None)
    clear = [s for s in table if b0[s] is not None and b0[s] > LIMITS['clear_min'] * top]
    med = {i: {k: float(np.median([table[s][i][k] for s in clear if i in table[s]])) for k in ('hfr', 'flux', 'peak')} for i in clearflux if sum(i in table[s] for s in clear) >= min(2, len(clear))}
    rows = []
    for s, row in table.items():
        ids = [i for i in row if i in med]
        base = dict(stamp=s, set=name, stars_matched=len(ids), sky_green=s1[s]['sky_green'], noise_g1=s1[s]['noise_g1'], stars_detected=len(by[s]['stars']))
        if len(ids) < 5:
            rows.append(dict(base, flux_rel=None)); continue
        ratios = np.array([row[i]['flux'] / med[i]['flux'] for i in ids])
        fl = float(np.median(ratios))
        X = np.array([(np.array(row[i]['pos']) - CENTRE) / 3000 for i in ids]); Y = ratios / fl
        A = np.column_stack([np.ones(len(Y)), X]); keep = np.ones(len(Y), bool)
        for _ in range(3):
            co, *_ = np.linalg.lstsq(A[keep], Y[keep], rcond=None); rr = Y - A @ co; sd = 1.4826 * np.median(np.abs(rr[keep])); keep = np.abs(rr) < 3 * max(sd, 1e-3)
        hfd = float(np.median([4 * row[i]['hfr'] for i in ids]))
        rows.append(dict(base, flux_rel=fl, flux_rel_scatter=float(1.4826 * np.median(np.abs(ratios - fl)) / np.sqrt(len(ids))), tilt=[float(co[1]), float(co[2])],
                         hfd_arcsec=hfd * SCALE, hfr_rel=float(np.median([row[i]['hfr'] / med[i]['hfr'] for i in ids])), elong_median=float(np.median([row[i]['elong'] for i in ids])),
                         peak_rel=float(np.median([row[i]['peak'] / med[i]['peak'] for i in ids]))))
    q = {r['stamp']: r for r in rows}
    clear2 = [s for s in q if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= 0.97] or clear
    hfd_med = float(np.median([q[s]['hfd_arcsec'] for s in clear2])); floor = float(np.median([s1[s]['sky_green'] for s in clear2]))
    noise0 = float(np.median([s1[s]['noise_g1'] for s in clear2]))
    use, rej = [], []
    for s in [o['stamp'] for o in tr]:
        o = q[s]; lv = s1[s]['sky_green']; why = []
        if trby[s].get('failed') or o['flux_rel'] is None:
            why.append('cloud: too few stars to register or measure (%d detected); sky green %.0f DN, %.1f x the set\'s clear level' % (o['stars_detected'], lv, lv / floor))
        else:
            if o['flux_rel'] < LIMITS['transparency_min']: why.append('cloud: stars at %.0f%% of their brightness in the set\'s clear frames (limit %.0f%%); sky green %.0f DN, %.2f x the clear level' % (100 * o['flux_rel'], 100 * LIMITS['transparency_min'], lv, lv / floor))
            gx, gy = o['tilt']
            if not why and max(abs(gx), abs(gy)) > LIMITS['tilt_max']: why.append('thin cloud uneven across the field: star brightness changes by %.0f%% in x and %.0f%% in y per 3000 px (limit %.0f%%); transparency %.0f%%' % (100 * gx, 100 * gy, 100 * LIMITS['tilt_max'], 100 * o['flux_rel']))
            if o['hfd_arcsec'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the clear-frame median %.2f (limit 30%%)' % (o['hfd_arcsec'], 100 * (o['hfd_arcsec'] / hfd_med - 1), hfd_med))
            if o['elong_median'] > LIMITS['elongation_max']: why.append('elongation %.2f' % o['elong_median'])
            if trby[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % trby[s]['wrms_px'])
            nrel = s1[s]['noise_g1'] / noise0 / o['flux_rel']
            if not why and name != 'short' and 1.0 / nrel ** 2 < LIMITS['weight_min']: why.append('bright sky: sky green %.0f DN, %.2f x the clear level (cloud glow or twilight); transparency %.0f%%; its weight would be %.2f (limit %.2f)' % (lv, lv / floor, 100 * o['flux_rel'], 1.0 / nrel ** 2, LIMITS['weight_min']))
        if why: rej.append(dict(stamp=s, why='; '.join(why), transparency=o['flux_rel'], sky_green=lv)); continue
        use.append(dict(stamp=s, transparency=o['flux_rel'], scale=1.0 / o['flux_rel'], noise_rel=nrel, weight=1.0 / nrel ** 2, sky_green=lv, tilt=o['tilt'], clear=bool(o['flux_rel'] >= 0.97),
                        hfd_arcsec=o['hfd_arcsec'], elong_median=o['elong_median']))
    bgref = min([u for u in use if u['clear']] or use, key=lambda u: u['sky_green'])['stamp']
    out[name] = dict(reference=T4[name]['reference'], quality_reference=q_stamp, background_reference=bgref, quality_stars=len(med), limits=LIMITS, hfd_clear_median_arcsec=hfd_med, sky_green_clear_median=floor, noise_clear_median=noise0, quality=rows, used=use, rejected=rej,
                     summed_weights=float(sum(u['weight'] for u in use)))
    print('set %-7s quality stars %3d (from %s); clear sky level %.0f DN green, noise %.1f; clear-frame HFD %.2f arcsec; used %d of %d, summed weights %.2f' % (name, len(med), q_stamp[9:], floor, noise0, hfd_med, len(use), nfr, sum(u['weight'] for u in use)))
    for s in [o['stamp'] for o in tr]:
        o = q[s]; u = next((u for u in use if u['stamp'] == s), None)
        if o['flux_rel'] is None: print('   %s  -- not measurable; sky G %.0f' % (s, o['sky_green'])); continue
        print('   %s stars %3d  T %.3f (+-%.3f) tilt %+.3f %+.3f  HFD %.2f" (rel %.3f) elong %.3f  sky G %4.0f  wrms %.2f  %s' % (s, o['stars_matched'], o['flux_rel'], o['flux_rel_scatter'], *o['tilt'], o['hfd_arcsec'], o['hfr_rel'], o['elong_median'], o['sky_green'], trby[s].get('wrms_px', -1),
              ('USED w %.2f%s' % (u['weight'], '  <- clearest: background reference' if s == bgref else '')) if u else 'rejected: ' + next(r['why'] for r in rej if r['stamp'] == s)[:110]))
json.dump(out, open(W('s5_select.json'), 'w'), indent=1)
