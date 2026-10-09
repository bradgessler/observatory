"""The colour of the field stars in the stack, for the second (star-neutral) colour version.
Stars of the reference frame that are not saturated (no plane within 1500 DN of the ceiling in any frame's
detection), more than 400 px from the nucleus, with no neighbour within 40 px and at least MINFLUX of green flux.
Aperture 28 px radius, local level from the ring 38 to 54 px (so the galaxy and the sky under the star drop
out), on the four planes of the finished version-B stack. Per star: R/G and B/G of the raw plane fluxes."""
import json, numpy as np
from common import *
MINFLUX = 20000.0
res = {r['stamp']: r for r in json.load(open(W('step3_stars.json')))}
st = np.load(W('B_final.npy'))
G = (st[1] + st[2]) / 2
stars = [s for s in res[REF_STAMP]['stars'] if s['r_nucleus'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > 40 and s['flux'] >= MINFLUX / 4]   # plane-px flux of the mean green = 1/4 of the sensor-grid sum
yy, xx = np.mgrid[-56:57, -56:57]; rr = np.hypot(xx, yy); ap = rr <= 28; ann = (rr > 38) & (rr < 54)
rows = []
for s in stars:
    x, y = int(round(2 * s['x'] + 0.5)), int(round(2 * s['y'] + 0.5))
    if x < 60 or y < 60 or x > Wd - 61 or y > H - 61: continue
    f = []
    for img in (st[0], G, st[3]):
        t = img[y - 56:y + 57, x - 56:x + 57]
        if not np.isfinite(t).all(): f = None; break
        f.append(float((t[ap] - np.median(t[ann])).sum()))
    if f is None or min(f) <= 0: continue
    pk = max(float(st[p][y - 6:y + 7, x - 6:x + 7].max()) for p in range(4))
    if pk > CEILING_RAW - 512 - 1500: continue
    rows.append(dict(sensor_xy=[x, y], flux_R=f[0], flux_G=f[1], flux_B=f[2], r_over_g=f[0] / f[1], b_over_g=f[2] / f[1]))
rows = [r for r in rows if r['flux_G'] >= MINFLUX]
rg = np.array([r['r_over_g'] for r in rows]); bg = np.array([r['b_over_g'] for r in rows]); fg = np.array([r['flux_G'] for r in rows])
def cmean(v):
    keep = np.ones(len(v), bool)
    for _ in range(4):
        m = v[keep].mean(); s = v[keep].std(); keep = np.abs(v - m) < 2.5 * s
    return float(v[keep].mean()), float(v[keep].std()), int(keep.sum())
mr, sr, nr = cmean(rg); mb, sb, nb = cmean(bg)
out = dict(stars=len(rows), minflux_green_dn=MINFLUX, r_over_g=dict(mean=mr, std=sr, used=nr, median=float(np.median(rg)), ratio_of_sums=float(sum(r['flux_R'] for r in rows) / fg.sum())),
           b_over_g=dict(mean=mb, std=sb, used=nb, median=float(np.median(bg)), ratio_of_sums=float(sum(r['flux_B'] for r in rows) / fg.sum())),
           star_neutral_multipliers=dict(R=1.0 / mr, G=1.0, B=1.0 / mb), list=rows)
json.dump(out, open(W('starcolour.json'), 'w'), indent=1)
print({k: v for k, v in out.items() if k != 'list'})
