"""Step 2: grade every planet frame once. In each: where the planet is (colour-cell px, to a fraction, the centroid of the
light above a quarter of the peak), how much light (cloud), the brightest pixel (clipping), the long axis of the rings
(second moments of the planet's outskirts: it measures the field's turn), and the sharpness: how much of the light sits
in fine detail (gradient energy over the planet per unit light squared, as saturn2.py of 3 October). Writes work/grades.json."""
from concurrent.futures import ProcessPoolExecutor
import cv2
from common import *

def grade(name):
    path = os.path.join(STILLS, name)
    try: P, wb = planes(path)
    except Exception as e: return dict(name=name, ok=False, why=str(e))
    g = (P[1] + P[2]) / 2; sm = cv2.GaussianBlur(g, (0, 0), 4); cy, cx = np.unravel_index(np.argmax(sm), sm.shape); h, w = g.shape
    bgd = float(np.median(g[::16, ::16])); noise = float(1.4826 * np.median(np.abs(g[::16, ::16] - bgd)))
    if sm[cy, cx] - bgd < 0.01: return dict(name=name, ok=False, why='no planet in the frame')
    if not (HALF + 8 < cx < w - HALF - 8 and HALF + 8 < cy < h - HALF - 8): return dict(name=name, ok=False, why='planet at the edge')
    t = g[cy - HALF:cy + HALF, cx - HALF:cx + HALF]; t0 = np.clip(t - bgd, 0, None); yy, xx = np.mgrid[0:2 * HALF, 0:2 * HALF]; m = t0 > 0.25 * t0.max()
    fx = float((xx * t0 * m).sum() / (t0 * m).sum()) + cx - HALF; fy = float((yy * t0 * m).sum() / (t0 * m).sum()) + cy - HALF
    gx_, gy_ = np.gradient(cv2.GaussianBlur(t0, (0, 0), 0.8)); sharp = float(((gx_ ** 2 + gy_ ** 2) * m).sum() / (t0 * m).sum() ** 2 * 1e4)
    s2 = cv2.GaussianBlur(t0, (0, 0), 2); wgt = ((s2 > 0.08 * s2.max()) & (s2 < 0.5 * s2.max())).astype(np.float64)
    dx, dy = xx + cx - HALF - fx, yy + cy - HALF - fy; cxx = (wgt * dx * dx).sum(); cyy = (wgt * dy * dy).sum(); cxy = (wgt * dx * dy).sum()
    ang = 0.5 * np.degrees(np.arctan2(2 * cxy, cxx - cyy)); lam = np.linalg.eigvalsh([[cxx, cxy], [cxy, cyy]])
    pk = P[:, (cy - HALF) * 1:(cy + HALF), (cx - HALF):(cx + HALF)].max(axis=(1, 2))
    return dict(name=name, ok=True, x=round(fx, 3), y=round(fy, 3), flux=round(float(t0[m].sum()), 3), sharp=round(sharp, 5), ring_line_deg=round(float(ang), 3),
                elongation=round(float(np.sqrt(lam[1] / lam[0])), 3), peak_green=round(float(t.max()), 4), peak_planes=[round(float(v), 4) for v in pk],
                clipped=int((P[:, cy - HALF:cy + HALF, cx - HALF:cx + HALF] >= 0.98).sum()), sky=round(bgd, 6), sky_noise=round(noise, 6))

if __name__ == '__main__':
    names = jload('frames.json')['planet']
    with ProcessPoolExecutor(WORKERS) as ex: rows = list(ex.map(grade, names))
    jsave('grades.json', rows)
    ok = [r for r in rows if r['ok']]; print('%d graded, %d with the planet whole in the frame' % (len(rows), len(ok)))
    for r in rows:
        if not r['ok']: print('  not usable:', r['name'], r['why'])
    f = np.array([r['flux'] for r in ok]); s = np.array([r['sharp'] for r in ok]); a = np.array([r['ring_line_deg'] for r in ok])
    print('flux: median %.2f, 5-95%% %.2f to %.2f; sharpness median %.4f, best %.4f, worst %.4f; brightest pixel (any plane) %.3f of full scale; clipped pixels in total %d'
          % (np.median(f), *np.percentile(f, [5, 95]), np.median(s), s.max(), s.min(), max(max(r['peak_planes']) for r in ok), sum(r['clipped'] for r in ok)))
    print('ring line: first %.2f deg, last %.2f deg; planet moved on the sensor from (%.0f, %.0f) to (%.0f, %.0f) colour-cell px' % (a[:20].mean(), a[-20:].mean(), ok[0]['x'], ok[0]['y'], ok[-1]['x'], ok[-1]['y']))
