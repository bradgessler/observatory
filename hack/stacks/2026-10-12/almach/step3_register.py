"""Step 3: measure every frame. Where the primary is (per colour plane, to a fraction of a sensor pixel), how much light it
carries, and how sharp the frame is. A 1/60 s frame freezes the air: the star is a few speckles and moves about by
a pixel or two from frame to frame, so a frame's sharpness is a thing to measure, not to assume.

  position   a Gaussian-windowed (sigma 4 sensor px) flux centroid of the primary, iterated, on each colour plane's own samples at their
             true sensor positions (R at (2X, 2Y), G1 (2X+1, 2Y), G2 (2X, 2Y+1), B (2X+1, 2Y+1)). G is G1 and G2 together.
  flux       the star's light in a 9-cell-pixel (18 sensor px) radius, all four planes added (the companion's disc is left out)
  sharpness  half-flux diameter of the primary (radius holding half of its light, within 7 cell px of its centroid, the companion's
             disc left out), and compactness sum(v^2)/sum(v)^2 in the same aperture: both on the 2 x 2 cell luminance
  companion  windowed centroid of the fainter star near the expected spot, for the separation and position angle (step 6)
All in the frame's crop coordinates; sensor = crop origin + 2 * cell position (+ the plane's cell offset)."""
import numpy as np, cv2
from common import *

SIG = 4.0                                                    # sensor px
FLUX_R = 9.0                                                 # cell px
COMP_GUESS = (-11.0, 6.0)                                    # cell px from the primary, read off frame 1 by eye
YY, XX = np.mgrid[0:CROP['h'] // 2, 0:CROP['w'] // 2]


def windowed_centroid(samples, x0, y0, sig, it=12):
    """samples: list of (values 2-D, ox, oy) planes; coordinates are sensor px in the crop. Returns (x, y) sensor px."""
    x, y = x0, y0
    for _ in range(it):
        sx = sy = sw = 0.0
        for v, ox, oy in samples:
            gx = 2 * XX[:v.shape[0], :v.shape[1]] + ox; gy = 2 * YY[:v.shape[0], :v.shape[1]] + oy
            w = np.exp(-((gx - x) ** 2 + (gy - y) ** 2) / (2 * sig * sig)) * np.clip(v, 0, None)
            sx += (w * gx).sum(); sy += (w * gy).sum(); sw += w.sum()
        x, y = sx / sw, sy / sw
    return float(x), float(y)


def cell_centroid(img, x, y, r, it=10):
    for _ in range(it):
        m = (XX - x) ** 2 + (YY - y) ** 2 <= r * r; w = np.clip(img, 0, None) * m
        x, y = (w * XX).sum() / w.sum(), (w * YY).sum() / w.sum()
    return float(x), float(y)


if __name__ == '__main__':
    A = np.load(W('crops.npy')); n = len(A); fs = frames(); rows = []
    for k in range(n):
        P = A[k]; lum = P.sum(0)
        s = cv2.GaussianBlur(lum, (0, 0), 2); y0, x0 = np.unravel_index(s.argmax(), s.shape)
        px, py = cell_centroid(lum, x0, y0, 5)                              # cell px, cell (0,0) = sensor (0.5, 0.5) of the crop
        cx, cy = cell_centroid(lum, px + COMP_GUESS[0], py + COMP_GUESS[1], 4)
        # per-plane sensor-px centroids (cell centre convention: sensor px of the first pixel of the cell is 2X)
        gx0, gy0 = 2 * px + 0.5, 2 * py + 0.5
        pos = {}
        pos['R'] = windowed_centroid([(P[0], 0, 0)], gx0, gy0, SIG)
        pos['G'] = windowed_centroid([(P[1], 1, 0), (P[2], 0, 1)], gx0, gy0, SIG)
        pos['B'] = windowed_centroid([(P[3], 1, 1)], gx0, gy0, SIG)
        # aperture photometry and sharpness, companion's disc masked
        d2 = (XX - px) ** 2 + (YY - py) ** 2; dc2 = (XX - cx) ** 2 + (YY - cy) ** 2
        ap = (d2 <= FLUX_R ** 2) & (dc2 > 4.5 ** 2); flux = float(lum[ap].sum())
        a7 = (d2 <= 49) & (dc2 > 4.5 ** 2); v = np.clip(lum[a7], 0, None); r = np.sqrt(d2[a7]); o = np.argsort(r)
        cum = np.cumsum(v[o]) / v.sum(); hfd = float(2 * r[o][np.searchsorted(cum, 0.5)])
        compact = float((v ** 2).sum() / v.sum() ** 2)
        peak = float(lum[int(round(py)), int(round(px))])
        rows.append(dict(i=k, file=fs[k], cell_xy=[px, py], plane_sensor_xy={c: list(v) for c, v in pos.items()}, companion_cell_xy=[cx, cy],
                         flux=flux, hfd_cell_px=hfd, hfd_arcsec=hfd * 2 * SCALE, compactness=compact, peak_cell_dn=peak,
                         brightest_single_pixel_dn=float(P.max())))
        print('%2d %s  pos (%.2f, %.2f)  flux %7.0f  HFD %.2f cell px = %.2f"  compact %.4f  R-G (%.2f, %.2f) B-G (%.2f, %.2f) sensor px' % (
            k, fs[k][9:15], px, py, flux, hfd, hfd * 2 * SCALE, compact, pos['R'][0] - pos['G'][0], pos['R'][1] - pos['G'][1], pos['B'][0] - pos['G'][0], pos['B'][1] - pos['G'][1]))
    rg = np.array([[r['plane_sensor_xy']['R'][j] - r['plane_sensor_xy']['G'][j] for j in (0, 1)] for r in rows])
    bg = np.array([[r['plane_sensor_xy']['B'][j] - r['plane_sensor_xy']['G'][j] for j in (0, 1)] for r in rows])
    print('R - G mean (%.2f, %.2f) sd (%.2f, %.2f); B - G mean (%.2f, %.2f) sd (%.2f, %.2f) sensor px (x right, y down)' % (*rg.mean(0), *rg.std(0), *bg.mean(0), *bg.std(0)))
    jdump(dict(frames=rows, r_minus_g_sensor_px=dict(mean=rg.mean(0).tolist(), sd=rg.std(0).tolist()), b_minus_g_sensor_px=dict(mean=bg.mean(0).tolist(), sd=bg.std(0).tolist()),
               flux_scatter_pct=float(100 * np.std([r['flux'] for r in rows]) / np.mean([r['flux'] for r in rows]))), 'step3_register.json')
