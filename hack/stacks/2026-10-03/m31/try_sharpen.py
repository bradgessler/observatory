"""Sharpening trial on the dust-lane crop (version B, green): Richardson-Lucy, 5 and 10 rounds, with the blur
measured from stars of this stack, and a gentle unsharp mask. Half of the isolated unsaturated stars in and
around the crop make the blur, the other half are the check. A sharpened picture is only worth delivering if it
draws no dark ring round the stars and does not turn the grain of the faint parts into texture: both are
measured here. Nothing from this trial is delivered unless it passes."""
import json, numpy as np, cv2
from common import *
from final import *
from decon import *
import measure
s10 = json.load(open(W('step10.json'))); x0, y0, x1, y1 = s10['rect']; lev = s10['zero']['B']['levels_subtracted_dn']
st = np.load(W('B_final.npy'))[:, y0:y1, x0:x1]
G = np.ascontiguousarray((st[1] - lev['G1'] + st[2] - lev['G2']) / 2)
cx0, cy0, cx1, cy1 = s10['dust_crop']; PAD = 200
big = (slice(cy0 - y0 - PAD, cy1 - y0 + PAD), slice(cx0 - x0 - PAD, cx1 - x0 + PAD)); g = np.ascontiguousarray(G[big])
res = {r['stamp']: r for r in json.load(open(W('step3_stars.json')))}
cand = []
for s in res[REF_STAMP]['stars']:
    if s['saturated'] or s['nearest'] < 60 or s['flux'] < 6000 or s['r_nucleus'] < 500 or max(s['plane_max']) > 12000: continue
    x, y = 2 * s['x'] + 0.5 - x0 - big[1].start, 2 * s['y'] + 0.5 - y0 - big[0].start
    if not (80 < x < g.shape[1] - 80 and 80 < y < g.shape[0] - 80): continue
    m = measure.star(g, x, y)
    if m and m['fwhm']: cand.append(m)
cand.sort(key=lambda m: -m['flux']); psf_stars, test_stars = cand[0::2], cand[1::2]
psf, n = psf_from_stars(g, [(m['x'], m['y']) for m in psf_stars])
print('stars: %d for the blur, %d for the check' % (n, len(test_stars)))
PED = float((lev['G1'] + lev['G2']) / 2)            # the sky that was taken off goes back on for the iteration, so the data is positive
out = {0: g, 5: richardson_lucy(g, psf, 5, PED), 10: richardson_lucy(g, psf, 10, PED)}
um = g + 0.6 * (g - cv2.GaussianBlur(g, (0, 0), 4.0)); out['unsharp'] = um.astype(np.float32)      # amount 0.6, radius sigma 4 px
def profile(img, x, y):
    xi, yi = int(round(x)), int(round(y)); R = 58
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64); yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
    sky = np.median(t[(rr >= 44) & (rr < 56)])
    return np.array([float(t[rr <= 1.5].mean()) - sky] + [np.median(t[(rr >= k - 0.5) & (rr < k + 0.5)]) - sky for k in range(1, 44)])
# grain: scatter of (picture - its 5x5 median) in a 400 px patch of smooth galaxy light well away from the lanes
gp = (slice(PAD + 1250, PAD + 1550), slice(PAD + 900, PAD + 1300))
rep = {}
for k, img in out.items():
    rows = []
    for m in test_stars:
        s_ = measure.star(img, m['x'], m['y'])
        if not s_ or not s_['fwhm']: continue
        pr = profile(img, s_['x'], s_['y']); rows.append(dict(fwhm=s_['fwhm'], peak=pr[0], deepest=pr[8:44].min() / pr[0], deepest_dn=pr[8:44].min()))
    grain = clipped_stats((img - cv2.medianBlur(img, 5))[gp])[1]
    rep[str(k)] = dict(stars=len(rows), fwhm_arcsec=round(float(np.median([r['fwhm'] for r in rows])) * SCALE, 2), ring_deepest_fraction_of_peak=dict(median=round(float(np.median([r['deepest'] for r in rows])), 4), worst=round(float(min(r['deepest'] for r in rows)), 4)),
                       ring_deepest_dn=dict(median=round(float(np.median([r['deepest_dn'] for r in rows])), 1), worst=round(float(min(r['deepest_dn'] for r in rows)), 1)), grain_dn=round(float(grain), 2))
    print(k, rep[str(k)])
json.dump(dict(blur_stars=n, check_stars=len(test_stars), pedestal_dn=PED, unsharp=dict(amount=0.6, sigma_px=4.0), results=rep, grain_patch='300 x 400 px of smooth bulge light below the lanes'), open(W('sharpen_report.json'), 'w'), indent=1)
v = lambda a: (np.clip(np.arcsinh((a + 4) / 45) / np.arcsinh(1500 / 45), 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)
win = (slice(PAD + 500, PAD + 1000), slice(PAD + 700, PAD + 1300))
cv2.imwrite(W('v_sharpen.png'), np.hstack([v(out[k][win]) for k in (0, 5, 10, 'unsharp')]))
