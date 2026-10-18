"""Step 7: the canvas, a first green stack, and the dust measured on the run's own sky against that stack, per night.

Canvas: where at least CANVAS_MIN_FRAC of the used frames have data (each frame's outline put on the reference grid
through its registration), bounding box, 8 px margin (canvas.py).

The flat: the 13 October hybrid flat (FLAT_DIR, read only: large scale from that night's open sky of NGC 891, NGC 2261,
NGC 2419 and M1; dust and pixel response from that dawn's twilight flats), chosen as tonight's M27 pipeline chose it
(it scored best on M27's open sky) and checked on this run's dithered sky in step 7a. M33 fills the frame, so no large
scale can be built or judged from these frames.

The dust that moved since 13 October, measured on these frames' own sky, so the galaxy cancels:
  pass 1   every used frame's mean green / the flat x 1/transparency, put on the canvas (bilinear), minus one constant
           (its median over the area every frame covers), the weighted mean (step 5 weights): the first stack T.
  pass 2   T put back on each frame's own sensor grid (the inverse of its registration). On 8 px blocks of the sensor
           (stars masked as in the template: a flux-scaled circle round every source of step 2; the core of M33,
           CORE_BLIND_R round the nucleus in the frame's own place, left out), the frame's green / the flat = k T + c
           fitted (iterated 3-sigma, per frame: its brightness and its sky); the frame over that fit is what the
           sensor did that the flat did not. The median over the frames of a night, on the sensor's own grid: dust that
           sits still on the sensor stays, the galaxy (which moved under the dithers and the drift) goes. T carries
           each shadow diluted over the frames' places, so a shadow is read a little shallow (said in the recipe).
  shadows  that map over its own 160 px large scale, Gaussian 1 block; a shadow is below 1 - DUST_MIN over at least
           DUST_MIN_BLOCKS blocks and at least DUST_MIN_HALF deep in BOTH independent halves: tonight, turn 1 (1a + 1b)
           and turn 2 (the field turned 7 degrees and moved between them, so a feature of the galaxy cannot sit at
           the same sensor place in both); 13 October, its odd and even frames. There the night's flat is multiplied by
           the measured remainder (never above 1); everywhere else it is the 13 October flat as it came.
Writes work/flat_18oct.npy, work/flat_13oct.npy, work/canvas.json, work/pass1_green.npy, work/pass1_cover.npy,
work/step7_dust.json, work/v_dust_<night>.png."""
import json, os, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import canvas as CV, solvelib

BK = 8
CANVAS_MIN_FRAC = float(os.environ.get('M33_CANVAS_MIN_FRAC', '0.2'))
DUST_MIN, DUST_MIN_HALF, DUST_MIN_BLOCKS = 0.012, 0.006, 6
CORE_BLIND_R = int(os.environ.get('M33_CORE_BLIND_R', '160'))   # plane px (2 arcmin) round the nucleus: the core is too bright and peaked to judge a 1% shadow on
OWN_DUST = os.environ.get('M33_OWN_DUST', '1') == '1'
sel = jload('step5_select.json'); USE = sel['used']; stamps = [u['stamp'] for u in USE]
wts = {u['stamp']: u['weight'] for u in USE}; scale = {u['stamp']: u['scale'] for u in USE}; night = {u['stamp']: u['night'] for u in USE}; turn = {u['stamp']: u['turn'] for u in USE}
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
S2 = {r['stamp']: r['stars'] for r in json.load(open(W('step2_stars.json')))}
ELL = jload('step6_solve_ref.json')['galaxy_ellipse']
Z = np.load(os.path.join(FLAT_DIR, 'flat_planes.npz')); F0 = np.stack([Z[k].astype(np.float32) for k in PLANE_NAMES]); fj = json.load(open(os.path.join(FLAT_DIR, 'flat.json')))
F0g = 0.5 * (F0[1] + F0[2])
nby, nbx = h2 // BK, w2 // BK


def RT(s): return np.array(tr[s]['R']), np.array(tr[s]['t'])


def blocks(a):
    return a[:nby * BK, :nbx * BK].reshape(nby, BK, nbx, BK).transpose(0, 2, 1, 3).reshape(nby, nbx, -1)


def make_canvas():
    pad = CANVAS_PAD; g = 8
    hh, ww = (h2 + 2 * pad) // g, (w2 + 2 * pad) // g
    cnt = np.zeros((hh, ww), np.int32)
    corners = np.array([[0, 0], [Wd - 1, 0], [Wd - 1, H - 1], [0, H - 1]], np.float64)
    for s in stamps:
        R, t = RT(s); rs = (corners - t) @ R                      # reference sensor px
        pp = ((rs - 0.5) / 2 + pad) / g
        m = np.zeros((hh, ww), np.uint8); cv2.fillConvexPoly(m, np.round(pp).astype(np.int32), 1); cnt += m
    ys, xs = np.nonzero(cnt >= CANVAS_MIN_FRAC * len(stamps))
    X0 = int(xs.min() * g - pad - 8); Y0 = int(ys.min() * g - pad - 8)
    WC = int((xs.max() + 1) * g - pad + 8) - X0; HC = int((ys.max() + 1) * g - pad + 8) - Y0
    return dict(X0=X0, Y0=Y0, HC=HC, WC=WC, min_frac=CANVAS_MIN_FRAC, frames=len(stamps), what='canvas pixel (X, Y) = reference plane pixel (X + X0, Y + Y0)')


def green(s):
    P, meta = load_clean(path_of(s))
    return 0.5 * (P[1] + P[2]) / F0g


def pass1(s):
    G = green(s) * np.float32(scale[s]); R, t = RT(s)
    mx, my = CV.maps(R, t, X0, Y0, HC, WC)
    return cv2.remap(G, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))


def star_mask(s, sh):
    m = np.zeros((h2, w2), np.uint8)
    for st in S2[s]:
        r = 80 if st['saturated'] else int(np.clip(10 + 9 * np.log10(max(st['flux'], 1e3) / 1e4), 8, 40))
        cv2.circle(m, (int(round(st['x'])), int(round(st['y']))), r, 1, -1)
    cx, cy = ELL['centre_px'][0] + sh[0], ELL['centre_px'][1] + sh[1]
    cv2.circle(m, (int(round(cx)), int(round(cy))), CORE_BLIND_R, 1, -1)
    return m


def pass2(s):
    G = green(s); R, t = RT(s)
    bx, by_ = CV.back_maps(R, t, X0, Y0)
    T = cv2.remap(T1, bx, by_, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    sh = np.array(tr[s]['shift_at_centre_px']) / 2
    mb = blocks(star_mask(s, sh)).mean(2) > 0
    g = np.median(blocks(G), axis=2).astype(np.float32); tb = np.median(blocks(T), axis=2).astype(np.float32)
    ok = ~mb & np.isfinite(tb) & np.isfinite(g)
    A = np.stack([tb[ok], np.ones(ok.sum())], 1); y = g[ok]; keep = np.ones(len(y), bool)
    for _ in range(5):
        co, *_ = np.linalg.lstsq(A[keep], y[keep], rcond=None); r = y - A @ co; sd = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * sd
    out = np.full((nby, nbx), np.nan, np.float32); out[ok] = g[ok] / (co[0] * tb[ok] + co[1])
    return out, [float(co[0]), float(co[1])], float(np.median(np.abs(out[ok] - 1)))


def bin4(a):
    ny, nx = a.shape[0] // 4, a.shape[1] // 4
    v = a[:ny * 4, :nx * 4].reshape(ny, 4, nx, 4).transpose(0, 2, 1, 3).reshape(ny, nx, 16)
    with np.errstate(all='ignore'): m = np.nanmedian(v, axis=2)
    m[np.isfinite(v).sum(2) < 8] = np.nan
    return m


def remainder(cube):
    with np.errstate(all='ignore'): Sg = np.nanmedian(cube, axis=0)
    Sg[np.isfinite(cube).sum(0) < max(5, len(cube) // 3)] = np.nan
    Rr = Sg / np.nanmedian(Sg)
    big = bin4(Rr); big = cv2.medianBlur(np.where(np.isfinite(big), big, 1.0).astype(np.float32), 5)
    D = Rr / cv2.resize(big, (nbx, nby), interpolation=cv2.INTER_LINEAR)
    ok = np.isfinite(D).astype(np.float32)
    Ds = cv2.GaussianBlur(np.where(ok > 0, D, 0).astype(np.float32), (0, 0), 1.0) / np.maximum(cv2.GaussianBlur(ok, (0, 0), 1.0), 1e-3)
    Ds[cv2.GaussianBlur(ok, (0, 0), 1.0) < 0.5] = np.nan
    return Rr, Ds


def depth_at(a, x, y, r=30):
    yy, xx = np.mgrid[0:nby, 0:nbx]
    d = np.hypot(xx * BK + BK / 2 - x, yy * BK + BK / 2 - y); inn = d <= max(r * 0.7, BK); ring = (d > r + 12) & (d < r + 44)
    a_in, a_ring = a[inn & np.isfinite(a)], a[ring & np.isfinite(a)]
    return round(float(1 - np.median(a_in) / np.median(a_ring)), 4) if len(a_in) >= 2 and len(a_ring) >= 8 else None


if __name__ == '__main__':
    t00 = time.time()
    cvs = make_canvas(); X0, Y0, HC, WC = cvs['X0'], cvs['Y0'], cvs['HC'], cvs['WC']; jdump(cvs, 'canvas.json')
    print('canvas %d x %d px, origin on the reference grid (%d, %d) (the reference frame is %d x %d)' % (WC, HC, X0, Y0, w2, h2), flush=True)
    # coverage, exactly, on the canvas: frames per pixel
    cover = np.zeros((HC, WC), np.uint16)
    acc = np.zeros((HC, WC), np.float64); wacc = np.zeros((HC, WC), np.float64)
    Gs = {}
    def p1(s):
        a = pass1(s); return s, a
    allcov = None
    # first a quick pass for the area every frame covers (from the outlines), then the constants
    for s in stamps:
        R, t = RT(s); mx, my = CV.maps(R, t, X0, Y0, HC, WC)
        v = (mx >= 0) & (mx <= w2 - 1) & (my >= 0) & (my <= h2 - 1); cover += v.astype(np.uint16)
    allcov = cover == len(stamps)
    np.save(W('pass1_cover.npy'), cover)
    print('area covered by every used frame: %.1f%% of the canvas; %.0fs' % (100 * allcov.mean(), time.time() - t00), flush=True)
    yy, xx = np.nonzero(allcov[::4, ::4]); samp = (yy * 4, xx * 4)
    consts = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        for s, a in ex.map(p1, stamps):
            c = float(np.nanmedian(a[samp])); consts[s] = c
            ok = np.isfinite(a); w = wts[s]
            acc[ok] += w * (a[ok] - c); wacc[ok] += w
    T1 = np.where(wacc > 0, acc / np.maximum(wacc, 1e-12), np.nan).astype(np.float32); del acc
    T1 += np.float32(np.nanmedian(list(consts.values())))       # back to a positive level so that k T + c is well posed
    np.save(W('pass1_green.npy'), T1)
    print('pass 1 (first green stack) done; %.0fs' % (time.time() - t00), flush=True)
    res = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        for s, r in zip(stamps, ex.map(pass2, stamps)): res[s] = r
    print('pass 2 (each frame against the first stack) done; %.0fs' % (time.time() - t00), flush=True)
    out = dict(flat_from=dict(dir=FLAT_DIR, made_from=fj.get('made_from', {}).get('target'), formula=fj.get('formula')), canvas=cvs, constants_pass1=consts,
               fits={s: dict(k=res[s][1][0], c=res[s][1][1], median_abs_dev=res[s][2]) for s in stamps}, nights={})
    yy, xx = np.mgrid[0:nby, 0:nbx]
    F0b = blocks(F0g).mean(2)
    for nt, halves in (('18oct', (('turn 1', ('1a', '1b')), ('turn 2', ('2',)))), ('13oct', None)):
        ss = [s for s in stamps if night[s] == nt]
        if not ss: continue
        cube = np.stack([res[s][0] for s in ss])
        if halves: idx = [np.array([i for i, s in enumerate(ss) if turn[s] in h[1]]) for h in halves]; hn = [h[0] for h in halves]
        else: idx = [np.arange(len(ss))[1::2], np.arange(len(ss))[0::2]]; hn = ['odd frames', 'even frames']
        Rr, Ds = remainder(cube); _, Da = remainder(cube[idx[0]]); _, Db = remainder(cube[idx[1]])
        n, lab, stats, cent = cv2.connectedComponentsWithStats((np.nan_to_num(Ds, nan=1.0) < 1 - DUST_MIN).astype(np.uint8), connectivity=8)
        corr = np.ones((nby, nbx), np.float32); found, turned = [], []
        for i in range(1, n):
            m = lab == i; area = int(m.sum()); x, y = cent[i][0] * BK + BK / 2, cent[i][1] * BK + BK / 2
            d = dict(plane_px=[round(float(x), 1), round(float(y), 1)], sensor_px=[round(2 * float(x)), round(2 * float(y))], blocks=area, size_arcsec=round(2 * np.sqrt(area / np.pi) * BK * 0.776, 0),
                     left_by_the_flat=round(float(1 - np.nanmin(Ds[m])), 4), **{'in_' + hn[0].replace(' ', '_'): round(float(1 - np.nanmedian(Da[m])), 4), 'in_' + hn[1].replace(' ', '_'): round(float(1 - np.nanmedian(Db[m])), 4)})
            da, db = d['in_' + hn[0].replace(' ', '_')], d['in_' + hn[1].replace(' ', '_')]
            if area < DUST_MIN_BLOCKS or not (da >= DUST_MIN_HALF and db >= DUST_MIN_HALF) or min(x, y, w2 - x, h2 - y) < 24:
                turned.append(d); continue
            g = cv2.dilate(m.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            corr[g] = np.minimum(corr[g], np.clip(np.nan_to_num(Ds, nan=1.0)[g], 0.8, 1.0))
            d['depth_before_any_flat'] = depth_at(Rr * F0b, x, y, max(20, d['size_arcsec'] / 0.776 / 2))
            found.append(d)
        CF = np.ones((h2, w2), np.float32); CF[:nby * BK, :nbx * BK] = cv2.resize(corr, (nbx * BK, nby * BK), interpolation=cv2.INTER_LINEAR)
        FL = F0 * CF[None] if OWN_DUST else F0.copy()
        np.save(W('flat_%s.npy' % nt), FL)
        Fu = blocks(0.5 * (FL[1] + FL[2])).mean(2)
        named = []
        for nm, (sx, sy) in dict(crescent=(3522, 848)).items():
            x, y = sx / 2, sy / 2
            named.append(dict(name=nm, sensor_px=[sx, sy], depth_in_own_sky_no_flat=depth_at(Rr * F0b, x, y), left_by_the_13oct_flat=depth_at(Rr, x, y), left_after_own_correction=depth_at(Rr * F0b / Fu, x, y)))
            print('%s: named shadow %s sensor (%d, %d): %s deep in the own sky with no flat, %s left by the 13 October flat, %s after this night\'s own correction' % (nt, nm, sx, sy, named[-1]['depth_in_own_sky_no_flat'], named[-1]['left_by_the_13oct_flat'], named[-1]['left_after_own_correction']), flush=True)
        for d in sorted(found, key=lambda d_: -d_['left_by_the_flat']):
            print('%s: dust at sensor (%4d, %4d), about %.0f arcsec: %.3f deep after the 13 Oct flat (%s %.3f, %s %.3f), %s before any flat -> divided out' % (nt, *d['sensor_px'], d['size_arcsec'], d['left_by_the_flat'], hn[0], d['in_' + hn[0].replace(' ', '_')], hn[1], d['in_' + hn[1].replace(' ', '_')], d['depth_before_any_flat']), flush=True)
        q = Rr[np.isfinite(Rr)]
        out['nights'][nt] = dict(frames=len(ss), halves=dict(zip(hn, [len(i) for i in idx])), divided_out=found, turned_down=turned, named_shadows=named, sensor_fraction_changed=float((CF < 0.999).mean()), deepest_factor=float(CF.min()),
                                 remainder_robust_rms_8px=float(1.4826 * np.median(np.abs(q - np.median(q)))), applied=OWN_DUST)
        print('%s: %d frames, %d shadows divided out (%.2f%% of the sensor, deepest factor %.3f), %d candidates turned down; remainder rms (8 px blocks) %.4f' % (nt, len(ss), len(found), 100 * (CF < 0.999).mean(), CF.min(), len(turned), out['nights'][nt]['remainder_robust_rms_8px']), flush=True)
        v2 = np.clip((np.nan_to_num(Ds, nan=0.96) - 0.94) / 0.08, 0, 1)
        cv2.imwrite(W('v_dust_%s.png' % nt), cv2.resize((v2 * 255).astype(np.uint8), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    out['what'] = __doc__.split('\n\n')[2]
    jdump(out, 'step7_dust.json')
    print('%.0f s' % (time.time() - t00))
