"""Mosaic step 5: per-frame transparency, star width and elongation inside each panel, and which frames are used.
Same measures and the same limits as the core run (step5_quality.py, step7_select.py).

Transparency here is RELATIVE TO THE PANEL'S OWN CLEAREST FRAMES: each star's aperture flux over that star's
median flux in the panel's clear frames (first pass: 90th percentile over the panel; clear = within 7% of that),
median over the stars. Whether a panel's clearest frames were themselves under thin cloud cannot be seen inside
the panel; that is measured later against the core stack and the neighbouring panels (step 8) from the same stars.

A frame is used if: transparency >= 0.80, even across the field (straight-line fit of star brightness against
position changes by less than 10% per 3000 px), registration rms <= 1.0 px (all three as in the core run), stars
no wider than 1.30 x the panel's clear median and median elongation <= 1.60. The last two are LOOSER than the
core run's (1.10 and 1.40): the mosaic is shown at 2 to 4 times the core's pixel size and what the outer panels
hold is faint smooth light, where a star 5.5 arcsec wide instead of 4.4 costs nothing and a frame of exposure is
a third or half of a panel. Frames that only pass because of this are flagged (passes_core_star_limits: false). Used frames are multiplied by 1 / transparency and averaged with
weight (transparency / noise)^2, noise = the frame's corner noise over the panel's clear median."""
import json, numpy as np
from mcommon import *

LIMITS = dict(transparency_min=0.80, tilt_max=0.10, hfd_max_rel=1.30, elongation_max=1.60, registration_wrms_max_px=1.0, clear_min=0.93)
CORE_LIMITS = dict(hfd_max_rel=1.10, elongation_max=1.40)
QFLUX = 30000.0
s1l = json.load(open(W('m1.json')))['frames']; s1 = {f['stamp']: f for f in s1l}
res = json.load(open(W('m3_stars.json'))); by = {r['stamp']: r for r in res}
T4 = json.load(open(W('m4_transforms.json')))
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])

out = {}
for name, _, _ in PANELS:
    tr = T4[name]['transforms']; ref_stamp = T4[name]['reference']; trby = {o['stamp']: o for o in tr}
    ref = [s for s in by[ref_stamp]['stars'] if s['r_nucleus'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > 40 and s['flux'] >= QFLUX]
    refxy = np.array([nat(s) for s in ref])
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
        base = dict(stamp=s, panel=name, stars_matched=len(ids), corner_green=s1[s]['corner_green'], stars_detected=len(by[s]['stars']))
        if len(ids) < 5:
            rows.append(dict(base, flux_rel=None)); continue
        ratios = np.array([row[i]['flux'] / med[i]['flux'] for i in ids])
        fl = float(np.median(ratios))
        # evenness: straight-line fit of the ratio against the star's place in the frame
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
    hfd_med = float(np.median([q[s]['hfd_arcsec'] for s in clear2])); floor = float(np.median([s1[s]['corner_green'] for s in clear2]))
    noise0 = float(np.median([s1[s]['corner'][1]['clipped_std'] for s in clear2]))
    use, rej = [], []
    for s in [o['stamp'] for o in tr]:
        o = q[s]; lv = s1[s]['corner_green']; why = []
        if trby[s].get('failed') or o['flux_rel'] is None:
            why.append('cloud: too few stars to register or measure (%d detected); corner green %.0f DN, %.1f x the panel\'s clear level' % (o['stars_detected'], lv, lv / floor))
        else:
            if o['flux_rel'] < LIMITS['transparency_min']: why.append('cloud: stars at %.0f%% of their brightness in the panel\'s clear frames (limit %.0f%%); corner green %.0f DN, %.2f x the clear level' % (100 * o['flux_rel'], 100 * LIMITS['transparency_min'], lv, lv / floor))
            gx, gy = o['tilt']
            if not why and max(abs(gx), abs(gy)) > LIMITS['tilt_max']: why.append('thin cloud uneven across the field: star brightness changes by %.0f%% in x and %.0f%% in y per 3000 px (limit %.0f%%); transparency %.0f%%' % (100 * gx, 100 * gy, 100 * LIMITS['tilt_max'], 100 * o['flux_rel']))
            if o['hfd_arcsec'] > LIMITS['hfd_max_rel'] * hfd_med: why.append('stars %.2f arcsec half-flux diameter, %.0f%% wider than the clear-frame median %.2f (limit 10%%)' % (o['hfd_arcsec'], 100 * (o['hfd_arcsec'] / hfd_med - 1), hfd_med))
            if o['elong_median'] > LIMITS['elongation_max']: why.append('elongation %.2f' % o['elong_median'])
            if trby[s]['wrms_px'] > LIMITS['registration_wrms_max_px']: why.append('registration rms %.2f px' % trby[s]['wrms_px'])
        if why: rej.append(dict(stamp=s, why='; '.join(why), transparency=o['flux_rel'], corner_green=lv)); continue
        nrel = s1[s]['corner'][1]['clipped_std'] / noise0 / o['flux_rel']
        use.append(dict(stamp=s, transparency=o['flux_rel'], scale=1.0 / o['flux_rel'], noise_rel=nrel, weight=1.0 / nrel ** 2, corner_green=lv, tilt=o['tilt'], clear=bool(o['flux_rel'] >= 0.97),
                        hfd_arcsec=o['hfd_arcsec'], elong_median=o['elong_median'], passes_core_star_limits=bool(o['hfd_arcsec'] <= CORE_LIMITS['hfd_max_rel'] * hfd_med and o['elong_median'] <= CORE_LIMITS['elongation_max'])))
    bgref = min([u for u in use if u['clear']] or use, key=lambda u: u['corner_green'])['stamp']
    out[name] = dict(reference=ref_stamp, background_reference=bgref, quality_stars=len(med), limits=LIMITS, hfd_clear_median_arcsec=hfd_med, corner_green_clear_median=floor, corner_noise_clear_median=noise0, quality=rows, used=use, rejected=rej,
                     summed_weights=float(sum(u['weight'] for u in use)))
    print('panel %-6s quality stars %3d; clear corner level %.0f DN green, noise %.1f; used %d of %d, summed weights %.2f' % (name, len(med), floor, noise0, len(use), nfr, sum(u['weight'] for u in use)))
    for s in [o['stamp'] for o in tr]:
        o = q[s]; u = next((u for u in use if u['stamp'] == s), None)
        if o['flux_rel'] is None: print('   %s  -- not measurable; corner G %.0f' % (s, o['corner_green'])); continue
        print('   %s stars %3d  T %.3f (+-%.3f) tilt %+.3f %+.3f  HFD %.2f" (rel %.3f) elong %.3f  corner G %4.0f  wrms %.2f  %s' % (s, o['stars_matched'], o['flux_rel'], o['flux_rel_scatter'], *o['tilt'], o['hfd_arcsec'], o['hfr_rel'], o['elong_median'], o['corner_green'], trby[s].get('wrms_px', -1),
              ('USED w %.2f%s%s' % (u['weight'], '' if u['passes_core_star_limits'] else '  (fails the core run\'s star-shape limits)', '  <- clearest: background reference' if s == bgref else '')) if u else 'rejected: ' + next(r['why'] for r in rej if r['stamp'] == s)[:90]))
json.dump(out, open(W('m5_select.json'), 'w'), indent=1)
