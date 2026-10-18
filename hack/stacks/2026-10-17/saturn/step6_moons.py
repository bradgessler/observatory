"""Step 6: the moons, from the two 2 s ISO 6400 frames (the planet blown out in them). Each frame: colour planes, sky
off (one constant per plane), each plane read at its own place onto the sensor's own grid (one sensor px per picture px,
Lanczos: within one frame this is a demosaic, so nothing finer than the 2 x 2 colour cell is claimed in the moon field),
centred on the middle of the planet's blown-out patch. The two frames are averaged; where they disagree by more than
6 sigma the lower is kept (a hot pixel or a cosmic ray is in one only: the field moved 4.6 arcmin across the sensor
between them). Then the planet's glare is taken off ring by ring (the median of each 1 px ring about the planet's middle,
outside the blown-out patch), and every point standing 6 sigma above its ring's scatter is listed. The points are matched
to JPL Horizons' moon positions (step 3) for the frames' mid time through the plate solves' turn and scale; a similarity
fit (turn, scale, shift) on the matched moons says how well they agree. A point that matches no moon is listed as a star.
Writes work/moonfield.npy (R, G, B, glare off), work/clipmask.npy, work/moons.json."""
import cv2
from common import *
RN = int(os.environ.get('SAT_MOONFIELD_R', '800'))   # sensor px kept each side of the planet: 5.2 arcmin
SIG = 6.0
MATCH_ARCSEC = 6.0

def field(name):
    P, wb = planes(os.path.join(STILLS, name)); P = P - np.median(P[:, ::4, ::4], axis=(1, 2))[:, None, None]
    sat = (P[1] + P[2]) / 2; clipped = (P.max(0) >= 0.95); sm = cv2.GaussianBlur(clipped.astype(np.float32), (0, 0), 3)
    cy, cx = np.unravel_index(np.argmax(sm), sm.shape); y0, x0 = cy - 80, cx - 80; m = clipped[y0:cy + 80, x0:cx + 80]; yy, xx = np.mgrid[0:m.shape[0], 0:m.shape[1]]
    fx, fy = float(xx[m].mean()) + x0, float(yy[m].mean()) + y0                  # colour-cell px: the middle of the blown-out patch
    sx, sy = 2 * fx + 0.5, 2 * fy + 0.5                                            # in sensor px
    u, v = np.meshgrid(np.arange(-RN, RN, dtype=np.float32) + sx, np.arange(-RN, RN, dtype=np.float32) + sy)
    out = np.zeros((2 * RN, 2 * RN, 3), np.float32); cl = np.zeros((2 * RN, 2 * RN), bool)
    for k, (ox, oy) in enumerate(OFFS):
        c = (0, 1, 1, 2)[k]; mx, my = ((u - ox) / 2).astype(np.float32), ((v - oy) / 2).astype(np.float32)
        out[:, :, c] += cv2.remap(P[k], mx, my, cv2.INTER_LANCZOS4) * wb[c] * (0.5 if c == 1 else 1)
        cl |= cv2.remap((P[k] >= 0.95).astype(np.float32), mx, my, cv2.INTER_LINEAR) > 0
    return out, cl, dict(name=name, planet_middle_sensor_px=[round(sx, 2), round(sy, 2)], clipped_px=int(clipped.sum()))

def ringmedian(img, mask, cx, cy):
    yy, xx = np.indices(img.shape); r = np.hypot(xx - cx, yy - cy).astype(int); out = np.zeros_like(img); sc = np.zeros_like(img)
    ok = ~mask; rmax = r.max() + 1
    order = np.argsort(r[ok]); rv = r[ok][order]; vv = img[ok][order]; edges = np.searchsorted(rv, np.arange(rmax + 1))
    med = np.zeros(rmax, np.float32); mad = np.zeros(rmax, np.float32)
    for i in range(rmax):
        seg = vv[edges[i]:edges[i + 1]]
        if len(seg) > 8: med[i] = np.median(seg); mad[i] = 1.4826 * np.median(np.abs(seg - med[i]))
    med = cv2.GaussianBlur(med[None], (0, 0), 0.0001)[0]
    return med[r], mad[r]

if __name__ == '__main__':
    fr = jload('frames.json'); names = fr['moons']; rows = {r['name']: r for r in fr['every_frame']}
    F = [field(n) for n in names]; A, B = F[0][0], F[1][0]; clip = F[0][1] | F[1][1]
    noise = float(1.4826 * np.median(np.abs(A[::5, ::5, 1] - np.median(A[::5, ::5, 1])))); d = A - B
    mean = (A + B) / 2; low = np.minimum(A, B); bad = np.abs(d) > SIG * noise * np.sqrt(2); mean[bad] = low[bad]
    # the planet's blown-out patch: the clipped pixels joined to the planet's middle (a moon or star saturated on its own is not masked)
    nlab, lab = cv2.connectedComponents(cv2.dilate(clip.astype(np.uint8), np.ones((5, 5), np.uint8)))
    clipmask = lab == lab[RN, RN]; others_clipped = int(nlab - 2)
    c = RN - 0.5; glare = np.zeros_like(mean); scat = np.zeros(mean.shape[:2], np.float32)
    for k in range(3):
        med, mad = ringmedian(mean[:, :, k], clipmask, c + 0.5, c + 0.5); glare[:, :, k] = med
        if k == 1: scat = mad
    res = mean - glare; res[clipmask] = 0; np.save(W('moonfield.npy'), res.astype(np.float32)); np.save(W('clipmask.npy'), clipmask)
    # points
    g = cv2.GaussianBlur(res[:, :, 1], (0, 0), 1.5); loc = (g == cv2.dilate(g, np.ones((9, 9), np.uint8)))
    sig = np.maximum(scat, noise) / 2.0                         # the blur of 1.5 px lowers the noise by about 2 (measured below on open sky)
    s_open = float(1.4826 * np.median(np.abs(g[::3, ::3] - np.median(g[::3, ::3])))); sig = np.maximum(scat * s_open / noise, s_open)
    pk = np.argwhere(loc & (g > SIG * sig) & ~cv2.dilate(clipmask.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool))
    pts = []
    for y, x in pk:
        if not (12 < x < 2 * RN - 12 and 12 < y < 2 * RN - 12): continue
        p = res[y - 6:y + 7, x - 6:x + 7, 1]; q = np.clip(p, 0, None); yy, xx = np.mgrid[-6:7, -6:7]
        pts.append(dict(x=round(float(x + (xx * q).sum() / q.sum()), 2), y=round(float(y + (yy * q).sum() / q.sum()), 2), snr=round(float(g[y, x] / sig[y, x]), 1), flux_green=round(float(res[y - 5:y + 6, x - 5:x + 6, 1].sum()), 4)))
    pts.sort(key=lambda p: -p['flux_green'])
    # catalogue positions through the plate solves
    eph = jload('ephemeris.json'); tm = np.mean([minute(n) + 1 / 60 for n in names]); i0 = int(np.floor(tm)) - eph['minutes'][0]; fr_ = tm - np.floor(tm)
    pos = {n: (1 - fr_) * np.array(o[i0]) + fr_ * np.array(o[i0 + 1]) for n, o in eph['moons'].items()}
    sol = [rows[n]['solve'] for n in names]; alpha = np.radians(np.mean([s['rotation_deg'] for s in sol]) - 180)
    per_px = float(np.mean([s['pixscale_arcsec'] * s['width_deg'] * 3600 / s['pixscale_arcsec'] / 6000 for s in sol]))
    M = per_px * np.array([[-np.cos(alpha), -np.sin(alpha)], [np.sin(alpha), -np.cos(alpha)]]); Minv = np.linalg.inv(M)     # [E, N] = M [dx, dy] (hack/stacks/2026-10-03/saturn/plan.py)
    pred = {n: Minv @ v + c + 0.5 for n, v in pos.items()}
    def match(T):
        out = {}
        for n, v in pos.items():
            q = T(v); best = min(pts, key=lambda p: np.hypot(p['x'] - q[0], p['y'] - q[1])) if pts else None
            dd = np.hypot(best['x'] - q[0], best['y'] - q[1]) * per_px if best else 1e9
            out[n] = (best, dd, q)
        return out
    m1 = match(lambda v: Minv @ v + c + 0.5)
    good = [(n, b) for n, (b, dd, q) in m1.items() if dd < MATCH_ARCSEC * 2]
    # similarity fit on the matched moons: [x, y] = s R [E, N] + t
    src = np.array([pos[n] for n, _ in good]); dst = np.array([[b['x'], b['y']] for _, b in good])
    Ms, _ = cv2.estimateAffinePartial2D(src.astype(np.float32), dst.astype(np.float32), method=cv2.LMEDS) if len(good) >= 3 else (None, None)
    T2 = (lambda v: Ms[:, :2] @ v + Ms[:, 2]) if Ms is not None else (lambda v: Minv @ v + c + 0.5)
    m2 = match(T2); named = {}; used = set()
    for n, (b, dd, q) in m2.items():
        st = 'found' if dd < MATCH_ARCSEC else ('inside the blown-out patch' if clipmask[int(round(q[1])) % (2 * RN), int(round(q[0])) % (2 * RN)] else 'not found')
        named[n] = dict(predicted_px=[round(float(q[0]), 2), round(float(q[1]), 2)], from_planet_arcsec=round(float(np.hypot(*pos[n])), 1), state=st,
                        found=dict(b, off_arcsec=round(float(dd), 2)) if st == 'found' else None)
        if st == 'found': used.add((b['x'], b['y']))
    stars = [p for p in pts if (p['x'], p['y']) not in used]
    # the points that are no moon: is a catalogue star there? (Gaia DR3 through the stack-pictures catalogue tool, moved to 2026.8)
    sys.path.insert(0, TOOLS); import catalogue
    k0 = eph['minutes'].index(int(np.floor(tm))); sra, sdec = eph['saturn_ra_dec'][k0]
    cat, catrec = catalogue.gaia_field(sra, sdec, 0.1, 16.0); cra, cdec = catalogue.at_epoch(cat, 2026.8)
    E = (cra - sra) * np.cos(np.radians(sdec)) * 3600; N = (cdec - sdec) * 3600
    gaia_px = np.array([T2(np.array([e, n])) for e, n in zip(E, N)])
    for p in stars:
        dd = np.hypot(gaia_px[:, 0] - p['x'], gaia_px[:, 1] - p['y']) * per_px; j = int(np.argmin(dd))
        p['gaia'] = dict(source=int(cat['source'][j]), g=round(float(cat['g'][j]), 2), off_arcsec=round(float(dd[j]), 2)) if dd[j] < 3 else None
        p['from_planet_arcsec'] = round(float(np.hypot(p['x'] - c - 0.5, p['y'] - c - 0.5) * per_px), 1)
    bright = [dict(g=round(float(cat['g'][j]), 2), px=[round(float(gaia_px[j, 0]), 1), round(float(gaia_px[j, 1]), 1)]) for j in np.argsort(cat['g'])[:15] if 0 < gaia_px[j, 0] < 2 * RN and 0 < gaia_px[j, 1] < 2 * RN]
    rms = float(np.sqrt(np.mean([named[n]['found']['off_arcsec'] ** 2 for n in named if named[n]['state'] == 'found'])))
    sc = float(np.hypot(*Ms[:, 0])) if Ms is not None else None; turn = float(np.degrees(np.arctan2(Ms[1, 0], Ms[0, 0]))) if Ms is not None else None
    jsave('moons.json', dict(frames=[f[2] for f in F], mid_minute_utc=tm, noise_green=noise, sigma_cut=SIG, points=pts, moons=named, stars=stars, catalogue_offsets_arcsec={n: [round(float(a), 2) for a in v] for n, v in pos.items()},
                             plate_solve=dict(up_east_of_north_deg=float(np.degrees(alpha)), arcsec_per_px=per_px, sky_to_px=Minv.tolist()),
                             similarity_fit=dict(px_per_arcsec=sc, arcsec_per_px=1 / sc if sc else None, matrix=Ms.tolist() if Ms is not None else None, turn_deg=turn, rms_arcsec=rms),
                             field_px=2 * RN, planet_middle_px=[c + 0.5, c + 0.5], frames_disagreed_px=int(bad.sum()), other_saturated_spots=others_clipped, gaia=dict(cone_deg=0.1, gmax=16.0, epoch=2026.8, record=catrec, brightest_in_field=bright)))
    print('%d points above %.0f sigma; plate solves: up %.2f deg east of north, %.4f arcsec per sensor px' % (len(pts), SIG, np.degrees(alpha), per_px))
    if Ms is not None: print('fit on the matched moons: %.4f arcsec per px, rms %.2f arcsec' % (1 / sc, rms))
    for n, v in named.items(): print('  %-9s %6.1f" from the planet: %s %s' % (n, v['from_planet_arcsec'], v['state'], ('(snr %.0f, %.2f" off the catalogue)' % (v['found']['snr'], v['found']['off_arcsec'])) if v['found'] else ''))
    for p in stars: print('  not a moon: point at (%.0f, %.0f), %.0f" from the planet, snr %.0f, flux %.4f: %s' % (p['x'], p['y'], p['from_planet_arcsec'], p['snr'], p['flux_green'], ('Gaia G %.1f, %.1f" off' % (p['gaia']['g'], p['gaia']['off_arcsec'])) if p['gaia'] else 'no catalogue star'))
    print('  brightest Gaia stars in the field:', bright[:6])
