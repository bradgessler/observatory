"""Deconvolution trial on the 16 arcmin crop: PSF from half of the isolated stars, checks on the other half."""
import json, os, sys, numpy as np, cv2
from common import *
from render import *
from decon import *
import measure
fl = np.load(W('stack_flat.npy')); s1 = json.load(open(W('step1.json'))); s5 = json.load(open(W('step5.json'))); C = json.load(open(W('centres.json')))
s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}
x0, y0 = s5['origin_sensor_xy']; USED = s5['used']; f1 = {f['stamp']: f for f in s1['frames']}
wb = np.median(np.array([f1[s]['wb'] for s in USED]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
chans = [fl[0], (fl[1] + fl[2]) / 2, fl[3]]
cx, cy = int(round(C['cluster'][0])), int(round(C['cluster'][1])); half = 1237; PADC = 80
sl = (slice(cy - half, cy + half), slice(cx - half, cx + half))
G = np.ascontiguousarray(chans[1])
# candidate stars: isolated (50 px), unsaturated, between 2.9 and 10.3 arcmin from the cluster centre
cand = []
for s in s2[REF_STAMP]['stars']:
    if s['saturated'] or s['nearest'] < 50 or s['flux'] < 8000 or not (450 < s['r_cluster'] < 1600): continue
    m = measure.star(G, 2 * s['x'] + 0.5 - x0, 2 * s['y'] + 0.5 - y0)
    if m and max(s['plane_max']) < 12000: cand.append(m)
cand.sort(key=lambda m: -m['flux'])
psf_stars, test_stars = cand[0::2], cand[1::2]
print('candidates', len(cand), 'psf stars', len(psf_stars), 'test stars', len(test_stars), 'flux range', int(cand[-1]['flux']), int(cand[0]['flux']))
psfs = []
for k, ch in enumerate(chans):
    p, n = psf_from_stars(ch, [(m['x'], m['y']) for m in psf_stars]); psfs.append(p)
np.save(W('psf_rgb.npy'), np.array(psfs))
PED = 100.0
by0, by1, bx0, bx1 = max(cy - half - PADC, 0), min(cy + half + PADC, G.shape[0]), max(cx - half - PADC, 0), min(cx + half + PADC, G.shape[1])
big = (slice(by0, by1), slice(bx0, bx1)); inner = (slice(cy - half - by0, cy + half - by0), slice(cx - half - bx0, cx + half - bx0))
res = {0: [np.ascontiguousarray(ch[big]) for ch in chans]}
for rounds in (5, 10):
    res[rounds] = [richardson_lucy(ch[big], psfs[k], rounds, PED) for k, ch in enumerate(chans)]
    np.save(W('decon_%d.npy' % rounds), np.array([a[inner] for a in res[rounds]]))
    print('rounds', rounds, 'done', flush=True)
ox, oy = bx0, by0
def profile(img, x, y, rmax=56):
    xi, yi = int(round(x)), int(round(y)); R = rmax + 2
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64); yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
    sky = np.median(t[(rr >= 44) & (rr < 56)])
    return np.array([float(t[rr <= 1.5].mean()) - sky] + [np.median(t[(rr >= k - 0.5) & (rr < k + 0.5)]) - sky for k in range(1, 44)])
report = {}
for rounds in (0, 5, 10):
    g = res[rounds][1]; rows = []
    for m in test_stars:
        x, y = m['x'] - ox, m['y'] - oy
        if not (70 < x < g.shape[1] - 70 and 70 < y < g.shape[0] - 70): continue
        st = measure.star(g, x, y); pr = profile(g, st['x'], st['y'])
        pk = pr[0]; neg = pr[8:44].min() / pk                       # deepest point of the ring profile beyond 8 px, as a fraction of the peak
        # a ring: a local maximum beyond the first minimum
        i0 = int(np.argmin(pr[:44])); bump = (pr[i0:44].max() - pr[i0]) / pk
        rows.append(dict(hfd=st['hfd'], fwhm=st['fwhm'], elong=st['elong'], peak=pk, flux=st['flux'], deepest=neg, min_radius=i0, bump=bump))
    sky = np.concatenate([clipped_stats(res[rounds][1][r:r + 300, c:c + 300])[1:2] for r, c in ((100, 100), (2200, 150), (150, 2200))])
    report[rounds] = dict(stars=len(rows), hfd_arcsec=float(np.median([r['hfd'] for r in rows]) * SCALE), fwhm_arcsec=float(np.median([r['fwhm'] for r in rows]) * SCALE), 
                          peak_gain=float(np.median([r['peak'] for r in rows])), flux=float(np.median([r['flux'] for r in rows])), deepest_fraction_of_peak=dict(median=float(np.median([r['deepest'] for r in rows])), worst=float(min(r['deepest'] for r in rows))),
                          bump_fraction_of_peak=dict(median=float(np.median([r['bump'] for r in rows])), worst=float(max(r['bump'] for r in rows))), sky_noise_green=float(np.median(sky)))
    print(rounds, json.dumps(report[rounds]))
json.dump(report, open(W('decon_report.json'), 'w'), indent=1)
# pictures: same stretch as the delivered crop, plain / 5 / 10, core and a field of isolated stars
ST = dict(white=6000.0, soft=100.0, pedestal=8.0)
def show(ch3): return asinh_stretch(np.dstack([ch3[0] * wb_r, ch3[1], ch3[2] * wb_b])[inner], **ST)[:, :, ::-1]
ims = {r: show(res[r]) for r in (0, 5, 10)}
c = half
cv2.imwrite(W('v_decon_core.png'), np.hstack([ims[r][c - 250:c + 250, c - 250:c + 250] for r in (0, 5, 10)]))
cv2.imwrite(W('v_decon_outer.png'), np.hstack([ims[r][c + 350:c + 850, c - 1150:c - 650] for r in (0, 5, 10)]))
cv2.imwrite(W('v_decon_mid.png'), np.hstack([ims[r][c - 800:c - 300, c - 250:c + 250] for r in (0, 5, 10)]))
# hard stretch around the brightest test stars to show any dark halo: linear -15..+40 DN, green
t3 = sorted(test_stars, key=lambda m: -m['flux'])[:4]; rows = []
for m in t3:
    x, y = int(round(m['x'] - ox)), int(round(m['y'] - oy))
    rows.append(np.hstack([cv2.resize((np.clip((res[r][1][y - 60:y + 61, x - 60:x + 61] + 15) / 55, 0, 1) * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST) for r in (0, 5, 10)]))
cv2.imwrite(W('v_decon_halo.png'), np.vstack(rows))
