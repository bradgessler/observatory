"""Step 9: Saturn and its moons, one picture from two exposures, north up and east left, one picture pixel per sensor
pixel (0.388 arcsec): never enlarged. The turn and scale come from the similarity fit of step 6 (five moons against JPL
Horizons, 0.07 arcsec rms), for both parts: the planet stack is turned back to the same moment (05:22:35 UTC).
  the planet   step 8's restored stack, binned 3 x 3 from the fine grid to sensor pixels (a box mean), then turned north up
               in one linear resampling; set in where the long frames are blown out (step 6's patch, grown by GROW px,
               feathered over FEATHER px).
  the moons    step 6's moon field (glare off), turned north up in one Lanczos resampling.
Brightness is not to one scale, and the picture says so: each part has its own white. The levels here are linear
(white points, a gamma, an arcsinh for the moon field so Titan and Iapetus both show); they are in the recipe.
Writes final/saturn.png (16-bit) and final/saturn-linear.json, and checks/planet-plain-vs-restored.png."""
import cv2
from common import *
GROW, FEATHER = int(os.environ.get('SAT_GROW', '28')), int(os.environ.get('SAT_FEATHER', '8'))
PLANET_WHITE_PCT, PLANET_GAMMA = 99.95, float(os.environ.get('SAT_PLANET_GAMMA', '1.25'))
MOON_SOFT = float(os.environ.get('SAT_MOON_SOFT', '12'))      # arcsinh softening, in multiples of the open sky's noise
MOON_WHITE = float(os.environ.get('SAT_MOON_WHITE', '0.85'))  # Titan's peak, arcsinh-stretched, lands here
MARGIN = 70

if __name__ == '__main__':
    mo = jload('moons.json'); R = np.load(W('restored.npy')); P0 = np.load(W('stack.npy')); MF = np.load(W('moonfield.npy')); clip = np.load(W('clipmask.npy'))
    from metrics import measure
    m, _ = measure(P0[:, :, 1]); fcx, fcy = m['centre']
    Ms = np.array(mo['similarity_fit']['matrix']); A = Ms[:, :2]; t = Ms[:, 2]; s = 1 / mo['similarity_fit']['arcsec_per_px']   # px per arcsec
    # the canvas: every found moon and the star with a margin, north up (y = -N), east left (x = -E), in sensor px
    pts = [v['found'] for v in mo['moons'].values() if v['state'] == 'found'] + [dict(x=t[0], y=t[1])]     # the moons set the frame; a star inside it is labelled
    EN = [np.linalg.solve(A, np.array([p['x'], p['y']]) - t) for p in pts]
    X = [-e * s for e, n in EN]; Y = [-n * s for e, n in EN]
    x0, x1, y0, y1 = int(np.floor(min(X))) - MARGIN, int(np.ceil(max(X))) + MARGIN, int(np.floor(min(Y))) - MARGIN, int(np.ceil(max(Y))) + MARGIN
    Wc, Hc = x1 - x0, y1 - y0
    # output (X, Y) -> (E, N) = (-(X + x0) / s, -(Y + y0) / s) -> moon field px = A (E, N) + t
    O2EN = np.array([[-1 / s, 0, -x0 / s], [0, -1 / s, -y0 / s]]); M_moon = A @ O2EN[:, :2]; M_moon = np.hstack([M_moon, (A @ O2EN[:, 2] + t)[:, None]])
    moons = cv2.warpAffine(MF, M_moon, (Wc, Hc), flags=cv2.INTER_LANCZOS4 | cv2.WARP_INVERSE_MAP, borderValue=0)
    cl = cv2.warpAffine(clip.astype(np.float32), M_moon, (Wc, Hc), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP) > 0.5
    # the planet: fine grid -> sensor px (3 x 3 box mean), then the same map; the planet's middle (fcx, fcy) sits on the moon field's t
    def planet(S):
        B = cv2.blur(S, (3, 3)); M = 3 * A @ O2EN[:, :2]; off = 3 * (A @ O2EN[:, 2] + t - np.array(mo['planet_middle_px'])) + np.array([fcx, fcy])
        return cv2.warpAffine(B, np.hstack([M, off[:, None]]), (Wc, Hc), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=0)
    pl = planet(R); pl0 = planet(P0)
    np.save(W('planet_sensor.npy'), pl); np.save(W('moons_sensor.npy'), moons)
    # levels
    L = pl.sum(2); pw = float(np.percentile(L[L > 0], PLANET_WHITE_PCT)) / 3
    planet_disp = np.clip(pl / pw, 0, 1) ** (1 / PLANET_GAMMA)
    g = moons[:, :, 1]; sky_sd = float(1.4826 * np.median(np.abs(g[::3, ::3] - np.median(g[::3, ::3])))); soft = MOON_SOFT * sky_sd
    ti = mo['moons']['Titan']['found']; tX, tY = [int(round(v)) for v in (-(np.linalg.solve(A, np.array([ti['x'], ti['y']]) - t) * s) - [x0, y0])]
    tpk = float(moons[tY - 3:tY + 4, tX - 3:tX + 4].sum(2).max() / 3)
    moon_disp = np.clip(np.arcsinh(np.clip(moons, 0, None) / soft) / np.arcsinh(tpk / soft) * MOON_WHITE, 0, 1)
    mask = cv2.dilate(cl.astype(np.uint8), np.ones((2 * GROW + 1, 2 * GROW + 1), np.uint8)).astype(np.float32)
    mask = np.clip(cv2.GaussianBlur(mask, (0, 0), FEATHER / 2), 0, 1); mask = np.maximum(mask, cl.astype(np.float32))
    img = mask[:, :, None] * planet_disp + (1 - mask[:, :, None]) * moon_disp
    os.makedirs(FINAL, exist_ok=True); cv2.imwrite(os.path.join(FINAL, 'saturn.png'), (np.clip(img, 0, 1)[:, :, ::-1] * 65535 + 0.5).astype(np.uint16))
    pc = [float(-(np.linalg.solve(A, t - t) * s)[0] - x0), float(-(np.linalg.solve(A, t - t) * s)[1] - y0)]
    def where(p): e, n = np.linalg.solve(A, np.array([p['x'], p['y']]) - t); return [round(float(-e * s - x0), 1), round(float(-n * s - y0), 1)]
    lab = {n: where(v['found']) for n, v in mo['moons'].items() if v['state'] == 'found'}
    star = [dict(where=where(p), g=p['gaia']['g']) for p in mo['stars'] if p.get('gaia') and 0 <= where(p)[0] < Wc and 0 <= where(p)[1] < Hc]
    jsave('compose.json', dict(size=[Wc, Hc], arcsec_per_px=1 / s, planet_px=pc, moons_px=lab, stars_px=star, planet_white_per_colour=pw, planet_gamma=PLANET_GAMMA, planet_white_percentile=PLANET_WHITE_PCT,
                               moon_sky_noise=sky_sd, moon_arcsinh_soft=soft, moon_white_at_titan_peak=MOON_WHITE, titan_peak=tpk, grow_px=GROW, feather_px=FEATHER,
                               north_up=dict(moon_field_map=M_moon.tolist(), from_='step 6 similarity fit'), planet_from='restored stack, 3x3 box mean, one linear resampling'))
    # check: plain vs restored at the sensor's scale, same stretch, the planet only
    cx, cy = int(round(pc[0])), int(round(pc[1])); h = 40; w = 75
    c1 = np.clip(pl0[cy - h:cy + h, cx - w:cx + w] / pw, 0, 1) ** (1 / PLANET_GAMMA); c2 = planet_disp[cy - h:cy + h, cx - w:cx + w]
    cv2.imwrite(os.path.join(HERE, 'checks', 'planet-plain-vs-restored.png'), (np.hstack([c1, np.zeros((2 * h, 6, 3)), c2])[:, :, ::-1] * 255).astype(np.uint8))
    print('canvas %d x %d sensor px (%.1f x %.1f arcmin), north up, east left; planet at (%.0f, %.0f); moons: %s' % (Wc, Hc, Wc / s / 60, Hc / s / 60, *pc, ', '.join(lab)))
