"""Step 4: per frame, from the same stars in every frame: transparency (star flux against the same stars in the other
frames, then scaled so the clearest frame is 1), how even it is across the field (straight-line fit of the flux ratio
against position), star width (half-flux diameter), elongation and a common direction of elongation (trailing), the sky
level and the pixel noise (from differences of neighbouring pixels, which the sky gradient does not inflate).
Adapted from hack/stacks/2026-10-03/ngc7662/step4_quality.py and m31/step7_select.py."""
import os
import numpy as np
from common import *

SCALE_GUESS = 0.386          # arcsec per sensor px (3.9 um at about 2084 mm); step 7 measures it
res = jload('step2_stars.json'); by = {r['stamp']: r for r in res}
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
st1 = {f['stamp']: f for f in jload('step1.json')['frames']}
ref = by[REF]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])
UC = np.array([3012.0, 2012.0]); US = 3000.0


def apply(o, A):
    u = (A - UC) / US
    X = np.column_stack([np.ones(len(A)), u[:, 0], u[:, 1], u[:, 0] ** 2, u[:, 0] * u[:, 1], u[:, 1] ** 2])
    return np.column_stack([X @ np.array(o['cx']), X @ np.array(o['cy'])])


cand = [i for i in range(len(refxy)) if refflux[i] >= 20000 and not ref['stars'][i]['saturated']]
table = {}
for s, o in tr.items():
    if o['failed']: continue
    xy = np.array([nat(k) for k in by[s]['stars']]); row = {}
    P = apply(o, refxy[cand])
    for i, p in zip(cand, P):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if d[j] < 4 and not by[s]['stars'][j]['saturated']: row[i] = by[s]['stars'][j]
    table[s] = row
present = {i: sum(i in table[s] for s in table) for i in cand}
qstars = [i for i in cand if present[i] >= 0.8 * len(table)]
print('quality stars (flux >= 20000 in the reference, unsaturated, found in >= 80% of frames):', len(qstars))
med = {i: {k: float(np.median([table[s][i][k] for s in table if i in table[s]])) for k in ('flux', 'hfr')} for i in qstars}


def noise(stamp):
    P = np.load(os.path.join(WORK, 'planes', stamp + '.npy'), mmap_mode='r')
    out = []
    for p in range(4):
        a = np.array(P[p, 200:-200:2, 200:-200])
        d = (a[:, 1:] - a[:, :-1]) / np.sqrt(2)
        out.append(clipped_stats(d[:, ::3])[1])
    return out


out = []
for s in sorted(table):
    row = table[s]; ii = [i for i in qstars if i in row]
    ratio = np.array([row[i]['flux'] / med[i]['flux'] for i in ii])
    hfd = np.array([4 * row[i]['hfr'] for i in ii])            # sensor px
    el = np.array([row[i]['elong'] for i in ii])
    e = np.mean([(row[i]['sig_major'] ** 2 - row[i]['sig_minor'] ** 2) / (row[i]['sig_major'] ** 2 + row[i]['sig_minor'] ** 2) * np.exp(2j * np.radians(row[i]['theta'])) for i in ii])
    # evenness: ratio = a + b u + c v, robust
    X = np.column_stack([np.ones(len(ii)), (refxy[ii] - UC) / 3000.0]); y = ratio / np.median(ratio); keep = np.ones(len(ii), bool)
    for _ in range(3):
        co, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None); rr = y - X @ co; sd = 1.4826 * np.median(np.abs(rr[keep])); keep = np.abs(rr) < 3 * sd
    nz = noise(s)
    out.append(dict(stamp=s, n_quality_stars=len(ii), flux_ratio_median=float(np.median(ratio)), flux_ratio_scatter=float(1.4826 * np.median(np.abs(ratio - np.median(ratio))) / np.median(ratio)),
                    tilt_per_3000px=[float(co[1]), float(co[2])], hfd_px=float(np.median(hfd)), hfd_arcsec=float(np.median(hfd) * SCALE_GUESS), elong_median=float(np.median(el)),
                    coherent_ellipticity=float(abs(e)), coherent_angle_deg=float(np.degrees(np.angle(e)) / 2),
                    sky_provisional_dn=[b['clipped_mean'] for b in st1[s]['bg_provisional']], pixel_noise_dn=nz, stars_detected=len(by[s]['stars'])))
top = max(o['flux_ratio_median'] for o in out)
for o in out:
    o['transparency'] = o['flux_ratio_median'] / top
    print('%s T %.3f (scatter %.3f, tilt %+.3f %+.3f, n %3d)  HFD %.1f px %.2f"  elong %.3f coh %.3f  sky G %.1f  noise G %.1f  stars %d' % (
        o['stamp'], o['transparency'], o['flux_ratio_scatter'], *o['tilt_per_3000px'], o['n_quality_stars'], o['hfd_px'], o['hfd_arcsec'], o['elong_median'], o['coherent_ellipticity'],
        o['sky_provisional_dn'][1], o['pixel_noise_dn'][1], o['stars_detected']))
failed = [s for s, o in tr.items() if o['failed']]
jsave(dict(quality=out, failed_registration=failed, quality_star_ref_index=qstars, clearest=max(out, key=lambda o: o['transparency'])['stamp'], scale_guess_arcsec_per_px=SCALE_GUESS), 'step4_quality.json')
