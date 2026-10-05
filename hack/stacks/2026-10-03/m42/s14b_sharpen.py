"""Step 14b: a sharpening TRIAL (after ../m31/scripts/try_sharpen.py). A sharpened picture is only worth
delivering if it draws no dark ring round the stars and does not turn grain into texture; both are measured.

On the green of the centred HDR stack (linear, zero taken off), the whole field. Stars for the blur and for the
check: isolated, unsaturated, no wider than 4.5 px half-flux radius (a knot of nebula is not a star), on nebula
fainter than 400 DN (so that the ring can be read against a smooth ground):
  Richardson-Lucy, 5 and 10 rounds, with the blur measured from stars of this stack (the median of the isolated,
      unsaturated stars with even numbers in the list; the odd ones are the check)
  an unsharp mask (amount 0.6, Gaussian sigma 2 half-grid px)
Per variant, on the check stars: width (FWHM from the azimuthal median profile), the deepest point of the
profile between 1.5 and 5 times the star's half-width, as a fraction of the star's peak and in DN (a ring), and
the grain (scatter of picture minus its 5x5 median) in a faint patch.
Then the same is asked of the finished picture (each variant through the picture's own grain step and curve, plus
an unsharp mask applied to the picture's brightness itself): round the bright stars, saturated ones included, how
many grey levels darker than the plain picture is the ground?
Verdict: delivered only if that is no more than 1 grey level in the median and 2 at worst. Otherwise nothing
is delivered and the numbers say why."""
import json, os
import numpy as np, cv2
from PIL import Image
from common import *
from decon import psf_from_stars, richardson_lucy

Hh = np.load(W('hdr_planes.npy')); Z = json.load(open(W('s13_mosaic.json')))['zero_taken_off_dn']
G = (Hh[1] + Hh[2]) / 2 - Z['G']
clip = np.load(W('deep_clip.npy')) > 0
wy0, wy1, wx0, wx1 = 12, 2000, 6, 3004
g = np.ascontiguousarray(np.nan_to_num(G[wy0:wy1, wx0:wx1], nan=0.0))
stars = json.load(open(W('s8_stars_deep.json')))['stars']
clipd = cv2.dilate(clip.astype(np.uint8), np.ones((41, 41), np.uint8)).astype(bool)
cand = []
for s in stars:
    x, y = s['x'] - wx0, s['y'] - wy0
    if not (70 < x < g.shape[1] - 70 and 70 < y < g.shape[0] - 70): continue
    if clipd[int(round(s['y'])), int(round(s['x']))] or s['nearest'] < 70 or s['flux'] < 20000 or s['elong'] > 1.6 or s['hfr'] is None or s['hfr'] > 4.5 or s['level'] - Z['G'] > 400: continue
    cand.append((s['flux'], x, y))
cand.sort(reverse=True)
psf_stars, test_stars = cand[0::2], cand[1::2]
psf, n = psf_from_stars(g, [(c[1], c[2]) for c in psf_stars], radius=20, ring=(26, 34))


def profile(img, x, y, R=34):
    xi, yi = int(round(x)), int(round(y))
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1].astype(np.float64); yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
    sky = np.median(t[(rr >= 26) & (rr < 33)])
    return np.array([float(t[rr <= 1.0].mean()) - sky] + [np.median(t[(rr >= k - 0.5) & (rr < k + 0.5)]) - sky for k in range(1, 26)])


def fwhm(pr):
    h = pr[0] / 2; k = np.nonzero(pr < h)[0]
    if len(k) == 0 or k[0] == 0: return None
    i = k[0]; return 2 * float((i - 1) + (pr[i - 1] - h) / (pr[i - 1] - pr[i]))


PED = float(Z['G'])
out = {'plain': g, 'richardson_lucy_5': richardson_lucy(g, psf, 5, PED), 'richardson_lucy_10': richardson_lucy(g, psf, 10, PED)}
out['unsharp_0.6_sigma2'] = (g + 0.6 * (g - cv2.GaussianBlur(g, (0, 0), 2.0))).astype(np.float32)
# a faint patch for the grain: the faintest 300 x 300 px block of the window (by a wide blur)
sm = cv2.blur(g, (301, 301)); sm[:160] = 1e9; sm[-160:] = 1e9; sm[:, :160] = 1e9; sm[:, -160:] = 1e9
py, px = np.unravel_index(np.argmin(sm), sm.shape); gp = (slice(py - 150, py + 150), slice(px - 150, px + 150))
rep = {}
for k, img in out.items():
    rows = []
    for f, x, y in test_stars:
        pr = profile(img, x, y); w = fwhm(pr)
        if w is None: continue
        lo, hi = max(int(round(0.75 * w)), 2), min(int(round(2.5 * w)) + 1, 25)
        if hi <= lo: continue
        rows.append(dict(fwhm=w, peak=pr[0], deepest=float(pr[lo:hi].min() / pr[0]), deepest_dn=float(pr[lo:hi].min())))
    grain = clipped_stats((img - cv2.medianBlur(img, 5))[gp])[1]
    rep[k] = dict(stars=len(rows), fwhm_arcsec=round(float(np.median([r['fwhm'] for r in rows])) * HS, 2), ring_deepest_fraction_of_peak=dict(median=round(float(np.median([r['deepest'] for r in rows])), 4), worst=round(float(min(r['deepest'] for r in rows)), 4)),
                  ring_deepest_dn=dict(median=round(float(np.median([r['deepest_dn'] for r in rows])), 1), worst=round(float(min(r['deepest_dn'] for r in rows)), 1)), grain_dn=round(float(grain), 2))
    print(k, rep[k])
# ---- the same question asked of the PICTURE: round the bright stars (the saturated ones too), how many grey levels darker
# than the plain picture does each variant make the ground? (green through the picture's own grain step and curve)
from render import grain, curve
D14 = json.load(open(W('s14_deliver.json'))) if os.path.exists(W('s14_deliver.json')) else dict(stretch=dict(white=40000.0, soft=8.0, pedestal=3.0, gamma=1.0), grain=dict(grain_sigma=3.0, s_lo=1.5, s_hi=8.0))
ST = D14['stretch']; GR = D14['grain']; okw = np.isfinite(G[wy0:wy1, wx0:wx1])
def shown(lin): return curve(grain(lin, okw, 9.0, ST['pedestal'], GR['grain_sigma'], GR['s_lo'], GR['s_hi'])[0], ST['white'], ST['soft'], ST['pedestal'], ST['gamma']).astype(np.float32)
E = {k: shown(v) for k, v in out.items()}
E['unsharp_on_the_picture_0.5_sigma2'] = E['plain'] + 0.5 * (E['plain'] - cv2.GaussianBlur(E['plain'], (0, 0), 2.0))
bright = [(s['x'] - wx0, s['y'] - wy0) for s in stars if 40 < s['x'] - wx0 < g.shape[1] - 40 and 40 < s['y'] - wy0 < g.shape[0] - 40 and s['nearest'] > 70 and s['flux'] > 60000 and s['hfr'] and s['hfr'] < 6][:60]
def prof_e(img, x, y, R=30):
    xi, yi = int(round(x)), int(round(y))
    t = img[yi - R:yi + R + 1, xi - R:xi + R + 1]; yy, xx = np.mgrid[-R:R + 1, -R:R + 1]; rr = np.hypot(xx - (x - xi), yy - (y - yi))
    return np.array([np.median(t[(rr >= k - 0.5) & (rr < k + 0.5)]) for k in range(3, 26)])
p0 = [prof_e(E['plain'], x, y) for x, y in bright]
for k in E:
    if k == 'plain': continue
    d = [float((prof_e(E[k], x, y) - p).min() * 255) for (x, y), p in zip(bright, p0)]
    rep.setdefault(k, {})['ring_in_the_picture_grey_levels_of_255_against_plain'] = dict(bright_stars=len(d), median=round(float(np.median(d)), 1), worst=round(float(min(d)), 1))
    print(k, 'ring in the picture, grey levels:', rep[k]['ring_in_the_picture_grey_levels_of_255_against_plain'])
verdict = {k: bool(v['ring_in_the_picture_grey_levels_of_255_against_plain']['median'] >= -1.0 and v['ring_in_the_picture_grey_levels_of_255_against_plain']['worst'] >= -2.0) for k, v in rep.items() if k != 'plain'}
ok = [k for k, v in verdict.items() if v]
report = dict(tried='on the green of the centred HDR stack, the whole field: Richardson-Lucy 5 and 10 rounds (blur = median of %d isolated unsaturated stars of this stack, checked on %d others), an unsharp mask on the linear data (amount 0.6, sigma 2 px), and an unsharp mask on the finished picture\'s brightness (amount 0.5, sigma 2 px)' % (n, len(test_stars)),
              blur_stars=n, check_stars=len(test_stars), pedestal_dn=PED, results=rep,
              rule='delivered only if, round the bright stars of the field (saturated ones included), the ground of the finished picture is no more than 1 grey level (of 255) darker than in the plain picture in the median and 2 at worst',
              passes=verdict, delivered=False, grain_patch_window_px=[int(px - 150), int(py - 150), int(px + 150), int(py + 150)])
if not ok:
    report['why_not'] = 'every variant draws a dark ring round the stars. In the picture, round the bright stars: ' + '; '.join('%s %.1f grey levels (worst %.1f)' % (k, v['ring_in_the_picture_grey_levels_of_255_against_plain']['median'], v['ring_in_the_picture_grey_levels_of_255_against_plain']['worst']) for k, v in rep.items() if k != 'plain') + \
                        '. On the linear data, round unsaturated check stars: ' + '; '.join('%s %.2f%% of the peak, stars %.2f arcsec wide, grain x %.2f' % (k, 100 * v['ring_deepest_fraction_of_peak']['median'], v['fwhm_arcsec'], v['grain_dn'] / rep['plain']['grain_dn']) for k, v in rep.items() if k != 'plain' and 'fwhm_arcsec' in v) + \
                        ' (plain: %.2f%%, %.2f arcsec). The stars sit on nebula, where a ring shows as a dark moat. Nothing sharpened is delivered.' % (100 * rep['plain']['ring_deepest_fraction_of_peak']['median'], rep['plain']['fwhm_arcsec'])
json.dump(report, open(W('sharpen_report.json'), 'w'), indent=1)
v = lambda a: (np.clip(np.arcsinh((a + 3) / 8) / np.arcsinh(40000 / 8), 0, 1) * 255).astype(np.uint8)
win = (slice(760, 1160), slice(1150, 1650))
cv2.imwrite(W('v_sharpen.png'), np.hstack([v(out[k][win]) for k in out]))
print('verdict', verdict)
