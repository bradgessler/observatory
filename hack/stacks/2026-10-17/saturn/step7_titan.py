"""Step 7: the blur, measured on Titan in the same frames as the planet. Titan is a point at this scale (its disc is
0.8 arcsec, under a fifth of the blur, and adds about 1 percent to it in quadrature, not taken off). In each kept frame
Titan is found where the moon frames' fit (step 6: catalogue offsets to sensor px, 0.07 arcsec rms) and JPL Horizons put
it at that frame's time, turned by the field's turn; each frame is laid on the fine grid there, with the planet's own
registration shift, in one resampling (planetlib.tile), and the frames are averaged. An elliptical Gaussian is fitted
to green; red and blue are measured against green (dispersion at Titan). Writes work/titan.npy and work/titan.json."""
from concurrent.futures import ProcessPoolExecutor
from scipy.optimize import curve_fit
from common import *
from planetlib import tile, turn_of, N_FINE

def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c

def fit(p):
    r = p.shape[0] // 2; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]
    (a, x0, y0, s1, s2, th, c), cov = curve_fit(f3, (gx.ravel(), gy.ravel()), p.ravel(), p0=(p.max(), 0, 0, 10, 9, 0.5, 0), maxfev=40000)
    s1, s2 = abs(s1), abs(s2)
    if s2 > s1: s1, s2, th = s2, s1, th + np.pi / 2
    e = np.sqrt(np.diag(cov)); return dict(amp=a, x=x0, y=y0, s1=s1, s2=s2, th=float(np.degrees(th) % 180), err_s=[float(e[3]), float(e[4])])

if __name__ == '__main__':
    st = jload('stack.json'); sel = jload('select.json'); mo = jload('moons.json'); eph = jload('ephemeris.json')
    Ms = np.array(mo['similarity_fit']['matrix'])[:, :2]; rate, ref_min = sel['turn_deg_per_minute'], sel['reference_minute_utc']
    tit = np.array(eph['moons']['Titan']); m0 = eph['minutes'][0]
    def titan_at(name):
        t = minute(name) + 0.5 / 60 - m0; i = int(t); f = t - i; return (1 - f) * tit[i] + f * tit[i + 1]
    args = []
    for e in st['each']:
        d = Ms @ titan_at(e['name']); a = np.radians(e['turned_back_deg']); R = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        dc = R @ d / 2                                              # sensor px -> colour cells, turned as this frame is
        args.append((e['name'], e['planet_cell_px'][0] + dc[0], e['planet_cell_px'][1] + dc[1], e['turned_back_deg'], e['shift_fine_px'][0], e['shift_fine_px'][1]))
    with ProcessPoolExecutor(WORKERS) as ex: T = list(ex.map(tile, args))
    S = np.mean(T, 0); c = N_FINE // 2; r = 45; box = S[c - 90:c + 91, c - 90:c + 91]
    bg = np.median(box, axis=(0, 1)); sm = cv2.GaussianBlur(box[:, :, 1] - bg[1], (0, 0), 4) if False else None
    import cv2
    g = cv2.GaussianBlur(box[:, :, 1] - bg[1], (0, 0), 4); py, px = np.unravel_index(np.argmax(g), g.shape)
    cy, cx = c - 90 + py, c - 90 + px; P = S[cy - r:cy + r + 1, cx - r:cx + r + 1] - bg
    ring = np.hypot(*np.mgrid[-r:r + 1, -r:r + 1]) > r - 6; sky_sd = float(P[:, :, 1][ring].std())
    fits = {nm: fit(P[:, :, k]) for k, nm in ((0, 'red'), (1, 'green'), (2, 'blue'))}; G = fits['green']; k = 2 * np.sqrt(2 * np.log(2)) * SCALE / 3
    np.save(W('titan.npy'), P.astype(np.float32))
    out = dict(frames=len(T), found_fine_px_from_prediction=[int(px - 90), int(py - 90)], sigma_peak=round(float(G['amp'] / sky_sd), 1),
               fwhm_arcsec=[round(G['s1'] * k, 3), round(G['s2'] * k, 3)], fwhm_err_arcsec=[round(G['err_s'][0] * k, 3), round(G['err_s'][1] * k, 3)], long_axis_deg_in_picture=round(G['th'], 1),
               sigma_fine_px=[G['s1'], G['s2']], red_from_green_sensor_px=[round((fits['red']['x'] - G['x']) / 3, 3), round((fits['red']['y'] - G['y']) / 3, 3)],
               blue_from_green_sensor_px=[round((fits['blue']['x'] - G['x']) / 3, 3), round((fits['blue']['y'] - G['y']) / 3, 3)],
               red_fwhm_arcsec=[round(fits['red']['s1'] * k, 3), round(fits['red']['s2'] * k, 3)], blue_fwhm_arcsec=[round(fits['blue']['s1'] * k, 3), round(fits['blue']['s2'] * k, 3)],
               titan_disc_arcsec=0.8, note='colours were not slid in this tile: the red and blue offsets are the air\'s prism at Titan, to compare with step 5\'s on the planet')
    jsave('titan.json', out)
    print('Titan in %d frames: %.0f sigma; found %s fine px from where predicted; blur (green) %.2f x %.2f arcsec FWHM (+- %.2f), long axis %.0f deg; red %s, blue %s sensor px from green (planet: red %s, blue %s)'
          % (len(T), out['sigma_peak'], out['found_fine_px_from_prediction'], *out['fwhm_arcsec'], max(out['fwhm_err_arcsec']), out['long_axis_deg_in_picture'], out['red_from_green_sensor_px'], out['blue_from_green_sensor_px'], st['dispersion_native_px']['red'], st['dispersion_native_px']['blue']))
