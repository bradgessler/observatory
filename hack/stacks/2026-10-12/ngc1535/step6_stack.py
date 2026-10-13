"""Step 6: flat-field every used frame, put its four colour planes onto the reference frame's grid of colour cells,
and combine. Each RAW is read in place for each plane (nothing cached), hot pixels repaired on the fly.

Flat: the night's flat (<night>/flat/flat_planes.npz, made by the NGC 891 stack from that run's sky: a vignetting
profile per colour and 13 measured dust shadows), divided into each plane before resampling. Why it matters here: the
nebula sat 45 px from the sensor centre in the first run and about 1,190 px from it in the second (the hold re-centred
the field elsewhere after the restart), where the flat is 0.95: without it the two runs would disagree by 5%.
What it cannot do: the sky in a 4 s frame is 16 DN in green and 4 in red, so this run cannot check the flat's dust the
way the M77 stack did on its own sky. Instead this step lists every dust shadow the flat carries, every candidate it
turned down and every shadow the M77 stack found uncorrected, with its distance from where the nebula sat in each run
(step6_stack.json: dust_near_the_nebula). A 5% shadow on a 16 DN sky is 0.8 DN, under the stack's noise per pixel; on
the nebula it would be 5% of the light of the frames of one run.

Output pixel (X, Y) is the centre of the reference frame's 2 x 2 colour cell (sensor 2X + 0.5, 2Y + 0.5): one picture
pixel per colour cell, 0.777 arcsec, nothing enlarged. For each frame and plane: where the cell centre falls in that
frame (step 3's rotation and shift), then in that plane (its own place in the cell), read with Lanczos-4 (OpenCV remap)
straight from the half-size plane: ONE resampling. Multiplied by 1 / transparency (step 4); minus ONE constant per
colour per frame: the 3-sigma clipped mean of that frame in a ring of sky around the nebula (SKY_R0 to SKY_R1 cells from
it, stars masked). No surface is fitted anywhere.

Atmospheric dispersion (the nebula was 37 degrees up): after a first pass, red and blue star images are measured
against green on the stack's own stars; the red and blue planes are then stacked again with that offset inside the
same single resampling, and the offsets are measured again (they should be about 0). The nebula's own colour centroids
are recorded too: its light is in emission lines ([O III] 501 nm falls in both the green and the blue filter), so the
shift measured on starlight is not exactly right for it; the difference is a fraction of a pixel against stars 7.7 px wide.

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD across the
frames, floor 0.4 x the single-frame noise), then again 3 sigma about the weighted mean of the survivors, then the
weighted mean (weights from step 4). Also kept: the frames used per pixel, the coverage, and the odd and even frames
combined alone (two independent halves, each with frames of both runs: their agreement says what is real)."""
import os, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
from step2_stars import measure

KAPPA = 3.0
SKY_R0, SKY_R1 = int(os.environ.get('N1535_SKY_R0', '110')), int(os.environ.get('N1535_SKY_R1', '480'))   # cells: 85 to 373 arcsec from the nebula (its shell ends at 25 to 30)
USE_FLAT = os.environ.get('N1535_FLAT', '1') == '1'
sel = jload('step4_select.json'); USE = sel['used']
T3 = jload('step3_transforms.json'); REF = T3['reference']; tr = {o['stamp']: o for o in T3['transforms']}
s5 = jload('step5_solve_ref.json'); NEB = np.array(s5['nearest_source']['px'])                # the nebula on the output grid (cells)
ref_stars = [r for r in json.load(open(W('step2_stars.json'))) if r['stamp'] == REF][0]['stars']
N = len(USE); stamps = [u['stamp'] for u in USE]; paths = [path_of(s) for s in stamps]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = np.array([u['scale'] for u in USE], np.float32)
FLAT = np.load(os.path.join(FLAT_DIR, 'flat_planes.npz')) if USE_FLAT else None
gy, gx = np.mgrid[0:h2, 0:w2].astype(np.float32)
SX, SY = 2 * gx + 0.5, 2 * gy + 0.5                        # sensor position of each output cell centre (reference frame)
rr = np.hypot(gx - NEB[0], gy - NEB[1])
SKY = (rr >= SKY_R0) & (rr < SKY_R1)
starmask = np.zeros((h2, w2), np.uint8)
for s in ref_stars:
    cv2.circle(starmask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
SKY &= starmask == 0
del gx, gy, rr
DISP = {}                         # plane -> (dx, dy) in output px: where that colour's star images sit against green


def warp(i, p):
    o = tr[stamps[i]]; R = np.array(o['R'], np.float32); t = np.array(o['t'], np.float32)
    dx, dy = DISP.get(p, (0.0, 0.0))
    sx, sy = SX + np.float32(2 * dx), SY + np.float32(2 * dy)
    fx = R[0, 0] * sx + R[0, 1] * sy + t[0]; fy = R[1, 0] * sx + R[1, 1] * sy + t[1]
    ox, oy = OFFS[p]
    P = load_clean_plane(paths[i], p)
    if FLAT is not None: P /= FLAT[PLANE_NAMES[p]].astype(np.float32)
    out = cv2.remap(P, (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    out *= scale[i]
    ok = SKY & np.isfinite(out)
    c = clipped_stats(out[ok])[0]
    out -= np.float32(c)
    return out, c


def take(s, k): return np.take_along_axis(s, k[None], 0)[0]


def combine(c, valid, floor, subs):
    f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        lo = np.clip((n - 1) // 2, 0, N - 1); hi = np.clip(n // 2, 0, N - 1)
        s = np.sort(cv_, axis=0); med = 0.5 * (take(s, lo) + take(s, hi)); del s
        dev = np.abs(cv_ - med); sd = np.sort(dev, axis=0); mad = 0.5 * (take(sd, lo) + take(sd, hi)); del sd
        sig = np.maximum(1.4826 * mad, floor)
        keep = valid & (dev <= KAPPA * sig * f); del dev
        c0 = np.where(valid, c, 0)
        ws = (w * keep).sum(0); m1 = (w * keep * c0).sum(0) / np.maximum(ws, 1e-9)
        r = np.where(keep, (c0 - m1) / f, 0); nk = keep.sum(0)
        sd1 = np.maximum(np.sqrt((r ** 2).sum(0) / np.maximum(nk - 1, 1)), floor); del r
        keep = valid & (np.abs(c0 - m1) <= KAPPA * sd1 * f)
        ws = (w * keep).sum(0)
        out = dict(mean=np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32), used=keep.sum(0).astype(np.uint8))
        for name, idx in subs.items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


order = np.arange(N); SUB = dict(odd=order[1::2], even=order[0::2])


def plane_noise(p):
    """Single-frame pixel noise of plane p (DN): neighbouring-pixel differences of the reference frame, / sqrt(2)."""
    P = load_clean_plane(path_of(REF), p)[300:-300:2, 300:-300]
    return clipped_stats(((P[:, 1:] - P[:, :-1]) / np.sqrt(2))[:, ::3])[1]


def stack_plane(p):
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex: res = list(ex.map(lambda i: warp(i, p), range(N)))
    cube = np.stack([r[0] for r in res]); const = [r[1] for r in res]; del res
    geo = np.isfinite(cube); cov = geo.sum(0).astype(np.uint8)
    noise = plane_noise(p); floor = np.float32(0.4 * noise)
    out = {k: np.zeros((h2, w2), np.uint8 if k == 'used' else np.float32) for k in ('mean', 'used', 'odd', 'even')}
    rows = [(a, min(a + 64, h2)) for a in range(0, h2, 64)]
    def work(ab):
        a, b = ab
        return ab, combine(cube[:, a:b], geo[:, a:b], floor, SUB)
    with ThreadPoolExecutor(WORKERS) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): out[k][a:b] = v
    seen = int(geo.sum()); usedn = int(out['used'].sum())
    info = dict(plane=PLANE_NAMES[p], single_frame_noise_dn=float(noise), sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=(seen - usedn) / seen,
                offset_against_green_px=[float(v) for v in DISP.get(p, (0.0, 0.0))])
    print(PLANE_NAMES[p], info, 'sky constants %.1f..%.1f' % (min(const), max(const)), '%.0fs' % (time.time() - t0), flush=True)
    return out, cov, const, info


def offsets(st, ok):
    """Red and blue star centroids against green on the stack (output px), and the nebula's own."""
    def flat(G):
        G = np.where(ok, G, 0).astype(np.float32)
        small = cv2.GaussianBlur(cv2.medianBlur(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), 5), (0, 0), 2)
        return G - cv2.resize(small, (w2, h2), interpolation=cv2.INTER_CUBIC)
    D = [flat(st[0]), flat((st[1] + st[2]) / 2), flat(st[3])]
    sm = cv2.GaussianBlur(D[1], (0, 0), 2.5); m, s, _ = clipped_stats(sm[ok][::7])
    n_, lab, stats, cent = cv2.connectedComponentsWithStats(((sm > m + 15 * s) & ok).astype(np.uint8), connectivity=8)
    rows, neb = [], None
    for i in range(1, n_):
        if stats[i, cv2.CC_STAT_AREA] < 10: continue
        r = [measure(d, float(cent[i][0]), float(cent[i][1])) for d in D]
        if any(v is None for v in r) or r[1]['flux'] < 3000: continue
        row = [r[0]['x'] - r[1]['x'], r[0]['y'] - r[1]['y'], r[2]['x'] - r[1]['x'], r[2]['y'] - r[1]['y'], r[1]['flux']]
        if np.hypot(r[1]['x'] - NEB[0], r[1]['y'] - NEB[1]) < 20: neb = row; continue
        if r[1]['hfr'] > 6 or min(r[0]['flux'], r[2]['flux']) < 800: continue
        rows.append(row)
    rows = np.array(rows); med = np.median(rows[:, :4], axis=0); sc = 1.4826 * np.median(np.abs(rows[:, :4] - med), axis=0) / np.sqrt(len(rows))
    return dict(stars=len(rows), red_minus_green_px=med[:2].tolist(), blue_minus_green_px=med[2:].tolist(), standard_error_px=sc.tolist(),
                red_blue_apart_arcsec=float(np.hypot(*(med[:2] - med[2:])) * s5['pixscale_arcsec']),
                nebula_own=dict(red_minus_green_px=neb[:2], blue_minus_green_px=neb[2:4]) if neb else None)


def dust_report():
    fj = json.load(open(os.path.join(FLAT_DIR, 'flat.json'))); d = fj['dust']
    places = {'run 1 (reference frame)': NEB}
    u2 = [u for u in USE if u['run'] == 2]
    if u2:
        o = tr[u2[len(u2) // 2]['stamp']]; places['run 2 (%s)' % o['stamp']] = ((np.array(o['R']) @ (2 * NEB + 0.5) + np.array(o['t'])) - 0.5) / 2
    lists = dict(in_the_flat=d.get('shadows', []), turned_down_by_the_flat=d.get('candidates_turned_down', []))
    m77 = os.path.join(NIGHT, 'm77', 'work', 'step7_flat.json')
    if os.path.exists(m77):
        mj = json.load(open(m77))
        def find(o, path=''):
            if isinstance(o, dict):
                for k, v in o.items(): yield from find(v, path + '/' + k)
            elif isinstance(o, list) and o and isinstance(o[0], dict) and 'plane_px' in o[0]: yield path, o
        for path, lst in find(mj): lists['m77_stack' + path.replace('/', '.')] = lst
    out = {}
    for run, xy in places.items():
        rep = dict(nebula_plane_px=[float(xy[0]), float(xy[1])], distance_from_sensor_centre_px=float(np.hypot(2 * xy[0] + 0.5 - CENTRE[0], 2 * xy[1] + 0.5 - CENTRE[1])),
                   flat_there={n: float(FLAT[n][int(round(xy[1])), int(round(xy[0]))]) for n in PLANE_NAMES} if FLAT is not None else None, nearest={})
        for name, lst in lists.items():
            if not lst: continue
            dd = [float(np.hypot(s['plane_px'][0] - xy[0], s['plane_px'][1] - xy[1])) for s in lst]; k = int(np.argmin(dd))
            rep['nearest'][name] = dict(count=len(lst), plane_px=lst[k]['plane_px'], distance_plane_px=dd[k], depth=lst[k].get('depth', lst[k].get('depth_early')), radius_plane_px=lst[k].get('radius_plane_px'))
        if FLAT is not None:
            x, y = int(round(xy[0])), int(round(xy[1])); g = FLAT['G1'][y - 60:y + 61, x - 60:x + 61].astype(np.float32)
            rep['flat_green_range_within_60px'] = [float(g.min()), float(g.max())]
        out[run] = rep
    return out


if __name__ == '__main__':
    names = ['mean', 'used', 'odd', 'even']
    store = {k: np.zeros((4, h2, w2), np.uint8 if k == 'used' else np.float32) for k in names}
    cover = np.zeros((h2, w2), np.uint8); CONST = np.zeros((N, 4)); info = [None] * 4
    hot = np.load(W('hotmap.npy')); x, y = int(round(NEB[0])), int(round(NEB[1]))
    hot_near = [int(hot[p, y - 30:y + 31, x - 30:x + 31].sum()) for p in range(4)]
    dust = dust_report()
    print('frames', N, 'sky ring pixels', int(SKY.sum()), 'flat', USE_FLAT, '; fixed hot pixels within 30 px of the nebula (run 1 place):', hot_near, flush=True)
    for run, rep in dust.items(): print(run, json.dumps(rep), flush=True)
    for p in range(4):
        out, cov, CONST[:, p], info[p] = stack_plane(p)
        for k in names: store[k][p] = out[k]
        if p == 1: cover[:] = cov
    ok = cover == N
    before = offsets(store['mean'], ok); print('colour offsets before', before, flush=True)
    if os.environ.get('N1535_DISPERSION', '1') == '1':
        DISP[0] = tuple(before['red_minus_green_px']); DISP[3] = tuple(before['blue_minus_green_px'])
        for p in (0, 3):
            out, cov, CONST[:, p], info[p] = stack_plane(p)
            for k in names: store[k][p] = out[k]
        after = offsets(store['mean'], ok); print('colour offsets after', after, flush=True)
    else: after = None
    for k, v in store.items(): np.save(W('stack_%s.npy' % k), v)
    np.save(W('cover.npy'), cover)
    jdump(dict(frames=stamps, reference=REF, kappa=KAPPA, grid='reference frame colour cells: output (X, Y) = sensor (2X + 0.5, 2Y + 0.5)', nebula_px=NEB.tolist(),
               flat=dict(applied=USE_FLAT, file=os.path.join(FLAT_DIR, 'flat_planes.npz'), how='each colour plane divided by the night\'s flat of that colour before resampling', dust_near_the_nebula=dust),
               fixed_hot_pixels_within_30px_of_the_nebula=dict(zip(PLANE_NAMES, hot_near)),
               sky=dict(how='3-sigma clipped mean of the resampled, transparency-scaled frame in a ring around the nebula, stars masked; one constant per colour per frame', ring_cells=[SKY_R0, SKY_R1], pixels=int(SKY.sum())),
               constants_dn={s: dict(zip(PLANE_NAMES, [round(float(c), 3) for c in CONST[i]])) for i, s in enumerate(stamps)},
               weights={s: float(wts[i]) for i, s in enumerate(stamps)}, scales={s: float(scale[i]) for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, planes=info,
               colour_offsets=dict(why='atmospheric dispersion: each colour\'s star images sit apart; red and blue resampled onto green in the one resampling', before=before, applied_px={'R': list(DISP.get(0, (0, 0))), 'B': list(DISP.get(3, (0, 0)))}, after=after,
                                   caveat='measured on starlight; the nebula shines in emission lines ([O III] 501 nm is in both the green and the blue filter), so for the nebula itself the blue shift is not exactly right: see nebula_own'),
               frames_covering_every_pixel=int(cover.min()), full_coverage_fraction=float(ok.mean())), 'step6_stack.json')
