"""Mosaic step 6c (a measurement, not a product): what the panel stacks hold at fixed places on the SENSOR, with the
first run's flat (M31M_BEFORE_WORK: the same step 6 run without the master-flat hooks) and with the master flat.

Places (plane px, away from the hair's box and 80 px from the frame edge):
  dust     where the master flat's own small-scale part (green over its wide smooth part, Gaussian sigma 2.5) is below
           0.97, blobs of 80 plane px or more: the real dust shadows, 3% and deeper.
  false    where the FIRST run's small-scale flat (smallflat_mosaic.npy) is above 1.012, blobs of 100 plane px or more:
           places it divided the frames by MORE than 1. Dust cannot do that. (They are galaxies and bright stars of
           single panels that leaked into the 19-frame median of step 5b.)
For every place and panel stack: median of green inside the blob over the median in a ring 5 to 15 px outside it,
minus 1 (stacks where a quarter of either has no data, or where the blob's own panel holds a bright object there,
left out: the place is skipped in a panel if the value is beyond +5%). Per place the median over the panels; then
over the places the mean and the rms, in percent and in DN of that panel's sky."""
import json, os, sys
import numpy as np, cv2
from mcommon import *
BEFORE = os.environ['M31M_BEFORE_WORK']; MF = np.load(os.environ['M31M_MASTER_FLAT_PLAIN']).astype(np.float32)
def wide(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
g = (MF[1] + MF[2]) / 2; D = cv2.GaussianBlur(g / wide(g), (0, 0), 2.5)
SF = cv2.GaussianBlur(np.load(os.path.join(BEFORE, 'smallflat_mosaic.npy')), (0, 0), 2.5)
ok = np.ones((H2, W2), bool); hx0, hy0, hx1, hy1 = [v // 2 for v in HAIR_BOX]; ok[max(hy0 - 60, 0):hy1 + 60, hx0 - 60:hx1 + 60] = False; ok[:80] = False; ok[-80:] = False; ok[:, :80] = False; ok[:, -80:] = False
def places(mask, minpx):
    n, lab, st, cen = cv2.connectedComponentsWithStats((mask & ok).astype(np.uint8), connectivity=8); out = []
    for i in range(1, n):
        if st[i, 4] < minpx: continue
        x0, y0, w, h = st[i, 0], st[i, 1], st[i, 2], st[i, 3]; m = 20
        sl = (slice(max(y0 - m, 0), y0 + h + m), slice(max(x0 - m, 0), x0 + w + m)); b = lab[sl] == i
        ring = cv2.dilate(b.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))).astype(bool) & ~cv2.dilate(b.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))).astype(bool)
        out.append(dict(sl=sl, blob=b, ring=ring, centre=[round(2 * float(cen[i][0])), round(2 * float(cen[i][1]))], px=int(st[i, 4])))
    return out
SETS = dict(dust=(places(D < 0.97, 80), D), false=(places(SF > 1.012, 100), SF))
names = [p[0] for p in PANELS if p[0] != 'centre']
res = {}
for run, wdir in (('before', BEFORE), ('after', WORK)):
    st = {k: np.load(os.path.join(wdir, k + '_planes.npy'))[1:3].mean(0) for k in names}; fl = {k: np.load(os.path.join(wdir, k + '_flag.npy')) for k in names}
    lev = {k: float(np.nanmedian(st[k][::8, ::8])) for k in names}
    for nm, (pl, ref) in SETS.items():
        rows = []
        for p_ in pl:
            vals = []; dn = []
            for k in names:
                a = st[k][p_['sl']]; f = np.isfinite(a) & (fl[k][p_['sl']] > 0)
                if (f & p_['blob']).sum() < 0.75 * p_['blob'].sum() or (f & p_['ring']).sum() < 0.75 * p_['ring'].sum(): continue
                c = float(np.median(a[f & p_['blob']]) / np.median(a[f & p_['ring']]) - 1)
                if c > 0.05: continue
                vals.append(c); dn.append(c * lev[k])
            if len(vals) >= 3: rows.append(dict(centre_sensor_xy=p_['centre'], plane_px=p_['px'], flat_value=float(np.median(ref[p_['sl']][p_['blob']])), panels=len(vals), contrast=float(np.median(vals)), contrast_dn=float(np.median(dn))))
        c = np.array([r['contrast'] for r in rows]); d = np.array([r['contrast_dn'] for r in rows])
        res.setdefault(nm, {})[run] = dict(places=len(rows), mean_percent=float(100 * c.mean()), rms_percent=float(100 * np.sqrt((c ** 2).mean())), mean_dn=float(d.mean()), rms_dn=float(np.sqrt((d ** 2).mean())), worst_dn=float(d[np.argmax(np.abs(d))]), rows=rows)
        print('%-6s %-5s places: %3d; what the stacks hold there: mean %+.2f%%, rms %.2f%%; in DN of sky: mean %+.2f, rms %.2f, worst %+.1f' % (run, nm, len(rows), 100 * c.mean(), 100 * np.sqrt((c ** 2).mean()), d.mean(), np.sqrt((d ** 2).mean()), d[np.argmax(np.abs(d))]))
# a yardstick: the same measure at random blobs (the dust set shifted by 300 px) gives the noise of the measure
json.dump(dict(sky_levels_dn={k: float(np.nanmedian(np.load(W(k + '_planes.npy'))[1][::8, ::8])) for k in names}, results=res), open(W('m6c_before_after.json'), 'w'), indent=1)
for nm in res:
    for r_b, r_a in list(zip(sorted(res[nm]['before']['rows'], key=lambda r: r['contrast_dn'])[:6], [None] * 6)):
        ra = next((r for r in res[nm]['after']['rows'] if r['centre_sensor_xy'] == r_b['centre_sensor_xy']), None)
        print('   %s at sensor %s (%d plane px, flat value %.3f): before %+.1f DN (%+.2f%%), after %s' % (nm, r_b['centre_sensor_xy'], r_b['plane_px'], r_b['flat_value'], r_b['contrast_dn'], 100 * r_b['contrast'], 'n/a' if ra is None else '%+.1f DN (%+.2f%%)' % (ra['contrast_dn'], 100 * ra['contrast'])))
