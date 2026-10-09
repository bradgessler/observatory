"""Step 12c: is the structure round Merope and Maia nebulosity, or the star's own glare, or noise?
Glare from the optics is ROUND about the star (this telescope has no spider vanes); ghosts and reflections move
with the star's place on the sensor; noise differs from stack to stack (different frames). Nebulosity is none of
these: it is lopsided and it stays on the sky. Merope lies where four stacks meet (in a different corner of the
sensor in each) and Maia is in (1,0) and in the centre check. For each pair of stacks that share sky near the star:
both are put on the mosaic grid separately (each with its own background of step 10), 2 x 2 binned (1.55 arcsec);
stars are masked (anything 2 sigma above a 5 px median after a 1 px blur, in either stack, grown by 4 px);
THE ROUND PART IS TAKEN OFF each (the median in rings of 3 px about the star, over the pixels the two share);
both are band-passed (Gaussian sigma 3 px minus Gaussian sigma 25 px: structure of 10 to 60 arcsec, the size of
the streaks). The correlation of the two over the sky they share between 1 and 8 arcmin from the star is the
test: only what is on the sky and not round correlates. The same is done (without the ring step) on three
control fields of blank sky shared by two clear stacks."""
import json
import numpy as np, cv2
from c import *
import p11_combine as p11
from render import bin2, nblur

PL = p11.PL; PS = p11.PS; ps2 = 2 * PS
zero = np.array([json.load(open(W('p11_combine.json')))['zero_dn'][c_] for c_ in 'RGB'], np.float32)
LABEL = dict(c='centre check', p00a='(0,0) first try', p00='(0,0) retake', p10='(1,0)', p20='(2,0)', p21='(2,1)', p11='(1,1)', p01='(0,1)', p02='(0,2)', p12='(1,2)', p22='(2,2)')


def single(k, fx0, fy0, n):
    mos, *_ = p11.combine(PS, p11.X0 - fx0, p11.Y0 - fy0, n, n, [k])
    return bin2(mos - zero)[..., 1]


def bandpass(g, ok):
    return nblur(np.where(ok, g, 0), ok, 3.0) - nblur(np.where(ok, g, 0), ok, 25.0)


def compare(a, b, cx, cy, rmin, rmax, rings=True):
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 5000: return None
    star = np.zeros(a.shape, bool)
    for g in (a, b):
        gf = np.where(np.isfinite(g), g, 0).astype(np.float32); d = gf - cv2.medianBlur(gf, 5)
        s = 1.4826 * np.median(np.abs(d[ok])); star |= cv2.GaussianBlur(d, (0, 0), 1.0) > 2.0 * s
    star = cv2.dilate(star.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]; rr = np.hypot(xx - cx, yy - cy) * ps2 / 60
    use = ok & ~star
    if rings:
        ri = (np.hypot(xx - cx, yy - cy) / 3).astype(int); a = a.copy(); b = b.copy(); nb = int(ri.max()) + 1
        for g in (a, b):
            idx = ri[use]; v = g[use]; order = np.argsort(idx, kind='stable'); idx = idx[order]; v = v[order]
            cuts = np.searchsorted(idx, np.arange(nb + 1)); prof = np.array([np.median(v[cuts[i]:cuts[i + 1]]) if cuts[i + 1] - cuts[i] > 20 else np.nan for i in range(nb)])
            g -= np.nan_to_num(prof, nan=0.0)[ri].astype(np.float32)
    A = bandpass(a, use); B = bandpass(b, use)
    m = use & (rr >= rmin) & (rr < rmax) & (cv2.erode(use.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    if m.sum() < 3000: return None
    x = A[m] - A[m].mean(); y = B[m] - B[m].mean()
    r = float((x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum()))
    nind = m.sum() / (4 * np.pi * 3.0 ** 2)                     # independent resolution elements after a sigma 3 px blur
    return dict(pixels=int(m.sum()), area_sq_arcmin=float(m.sum() * ps2 * ps2 / 3600), correlation=r, expected_scatter_if_nothing_shared=float(1 / np.sqrt(nind)), sigma=float(r * np.sqrt(nind)),
                rms_of_band_passed_dn=[float(x.std()), float(y.std())], common_part_dn_rms=float(np.sqrt(max((x * y).mean(), 0))))

out = {}
for star, stacks in (('Merope', ('p11', 'p21', 'p12', 'p22')), ('Maia', ('p10', 'c'))):
    f = PL['named_stars'][star]['fine_grid_pixel']; n = 1600
    fx0, fy0 = int(f[0]) - n // 2, int(f[1]) - n // 2
    S = {k: single(k, fx0, fy0, n) for k in stacks}
    res = {}
    for i, a in enumerate(stacks):
        for b in stacks[i + 1:]:
            c_ = compare(S[a], S[b], n / 4, n / 4, 1.0, 8.0)
            if c_: res['%s | %s' % (LABEL[a], LABEL[b])] = c_; print('%-7s %-18s shared %.0f sq arcmin: correlation %+.3f (scatter if nothing shared %.3f: %+.1f sigma); common structure %.2f DN rms; band-passed rms %.2f and %.2f DN' % (star, a + '-' + b, c_['area_sq_arcmin'], c_['correlation'], c_['expected_scatter_if_nothing_shared'], c_['sigma'], c_['common_part_dn_rms'], *c_['rms_of_band_passed_dn']))
    out[star] = res
# control: the same test on blank sky shared by two clear stacks, far from the named stars
ctrl = {}
for nm, (a, b, e, nn) in dict(north=('p00', 'p10', 5.0, 30.0), south=('p12', 'p22', -5.0, -33.0), east=('p01', 'p11', 14.0, 8.0)).items():
    X = p11.X0 - e * 60 / PS; Y = p11.Y0 - nn * 60 / PS; n = 1600
    fx0, fy0 = int(X) - n // 2, int(Y) - n // 2
    c_ = compare(single(a, fx0, fy0, n), single(b, fx0, fy0, n), n / 4, n / 4, 0.0, 12.0, rings=False)
    if c_: ctrl['%s | %s at %+.0f E %+.0f N arcmin' % (LABEL[a], LABEL[b], e, nn)] = c_; print('control %-6s %s-%s shared %.0f sq arcmin: correlation %+.3f (scatter %.3f: %+.1f sigma); common %.2f DN rms' % (nm, a, b, c_['area_sq_arcmin'], c_['correlation'], c_['expected_scatter_if_nothing_shared'], c_['sigma'], c_['common_part_dn_rms']))
out['control_blank_sky'] = ctrl
json.dump(out, open(W('p12c_seen_twice.json'), 'w'), indent=1)
