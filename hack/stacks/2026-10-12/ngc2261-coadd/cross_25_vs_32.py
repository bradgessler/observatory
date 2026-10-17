"""The two NGC 2261 trials side by side: the 25 frames the published stack used (ngc2261-coadd) and all 32 frames of the
run, the first after the slew and the six through thin cloud too (ngc2261-coadd-all: N2261_T_MIN=0.4 N2261_DROP_FIRST=0
N2261_NAME=ngc2261-coadd-all). Run by hand after both, before their step14_clean (it reads their stack arrays).
On the green of the rectangle both cover, for the same stars as step15_compare: the matched-filter S/N of the delivered
mean and of the proper coadd from each set of frames, over the delivered mean of the 25; the per-pixel noise; and the
scatter of 100 px box means on the masked sky (noise on large scales, where cloud leaves its mark). Writes
<night>/ngc2261-coadd-all/work/cross_25_vs_32.json."""
import sys, os, json, numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
from scipy.signal import fftconvolve
import coadd
from common import *
import solvelib
NI = os.path.expanduser('~/.observatory/nights/2026-10-12-a6000/')
def L(t, n): return np.load(NI + t + '/work/' + n)
s9a = json.load(open(NI + 'ngc2261-coadd/work/step9_solve.json'))['crop_on_reference_grid']; s9b = json.load(open(NI + 'ngc2261-coadd-all/work/step9_solve.json'))['crop_on_reference_grid']
x0, y0, x1, y1 = max(s9a['x0'], s9b['x0']), max(s9a['y0'], s9b['y0']), min(s9a['x1'], s9b['x1']), min(s9a['y1'], s9b['y1'])
faint = L('ngc2261-coadd', 'faint_region.npy')[y0:y1, x0:x1] & L('ngc2261-coadd-all', 'faint_region.npy')[y0:y1, x0:x1]
imgs = {}
for t, lab in (('ngc2261-coadd', '25'), ('ngc2261-coadd-all', '32')):
    for n, k in (('control_mean.npy', 'control'), ('coadd_proper.npy', 'proper')):
        a = L(t, n); imgs[k + lab] = np.nan_to_num(0.5 * (a[1] + a[2])[y0:y1, x0:x1]).astype(np.float32)
d = {r['stamp']: r for r in json.load(open(NI + 'ngc2261-coadd/work/step2_stars.json'))}[REF_STAMP]['stars']
hm = np.median([s['hfr'] for s in d if s['flux'] > 20000 and not s['saturated']])
ell = solvelib.object_mask(json.load(open(NI + 'ngc2261-coadd/work/step6_solve_ref.json')), (h2, w2))[y0:y1, x0:x1]
hh, ww = faint.shape; sm = np.zeros((hh, ww), np.uint8)
for s in d:
    x, y = s['x'] - x0, s['y'] - y0
    if 0 <= x < ww and 0 <= y < hh: cv2.circle(sm, (int(x), int(y)), int(10 + 6 * np.log10(max(s['flux'], 1e3) / 1e3)), 1, -1)
sky = faint & (sm == 0)
cand = [s for s in d if s['flux'] >= 2000 and not s['saturated'] and s['nearest'] > 42 and s['hfr'] and s['hfr'] <= 1.25 * hm]
xy = np.array([(s['x'] - x0, s['y'] - y0) for s in cand]); fl = np.array([s['flux'] for s in cand])
ok = (xy[:, 0] > 40) & (xy[:, 0] < ww - 40) & (xy[:, 1] > 40) & (xy[:, 1] < hh - 40) & np.array([not ell[int(y), int(x)] if 0 <= x < ww and 0 <= y < hh else False for x, y in xy])
xy, fl = xy[ok], fl[ok]; xy = coadd.refine_positions(imgs['control25'], xy); g = np.isfinite(xy[:, 0]); xy, fl = xy[g], fl[g]
def value_at(img, x, y, r=12):
    xi, yi = int(round(x)), int(round(y)); t = img[yi - r:yi + r + 1, xi - r:xi + r + 1].astype(np.float64)
    return float(coadd._fshift(t, -(x - xi), -(y - yi))[r, r])
snr = {}; out = {}
for k, im in imgs.items():
    p, _ = coadd.measure_psf(im, xy[fl >= 5000], 18)
    f = fftconvolve(im, p[::-1, ::-1], mode='same'); ns = clipped_stats(f[sky])[1]
    snr[k] = np.array([value_at(f, x, y) for x, y in xy]) / ns
    # large-scale: 100 px box means on masked sky
    bx = []
    for yy in range(0, hh - 100, 100):
        for xx in range(0, ww - 100, 100):
            m = sky[yy:yy + 100, xx:xx + 100]
            if m.mean() > 0.6: bx.append(im[yy:yy + 100, xx:xx + 100][m].mean())
    out[k] = dict(pixel_noise=clipped_stats(im[sky])[1], box100_scatter=float(np.std(bx)), boxes=len(bx))
for k in snr: out[k]['mf_snr_over_control25'] = float(np.median(snr[k] / snr['control25']))
for k, v in out.items(): print(k, {a: round(b, 4) if isinstance(b, float) else b for a, b in v.items()})
json.dump(out, open(NI + 'ngc2261-coadd-all/work/cross_25_vs_32.json', 'w'), indent=1)
