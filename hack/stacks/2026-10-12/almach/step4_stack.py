"""Step 4: grade the frames, choose how many to keep, and stack them at the sensor's own scale.

  grade      every frame by the half-flux diameter of its primary (step 3), smallest first.
  place      every colour plane of every frame is dropped onto a grid of SENSOR pixels (0.388 arcsec; the output is not
             finer or coarser than the sensor), each sample at its true sensor position minus the frame's measured shift
             for that plane (R, G, B each on its own primary centroid; the sub-pixel shifts are what fill the gaps between
             the sparse samples of a colour). A sample is a square drop of side DROP sensor px (1.0 = the pixel's own size),
             shared out between the output pixels it covers by area ("drizzle", Fruchter and Hook 2002).
  scale      each frame to the median primary flux of the run (1/60 s scintillation moves a bright star's light 10 percent
             between frames), so no frame counts more because the air happened to brighten the star.
  combine    plain weighted mean of what lands in each output pixel; no clipping needed with 13 frames and no stray hot pixel left.
  how many   N = 3, 5, 7, 9, 11, 13 sharpest frames: the stack's own primary half-flux diameter and compactness are measured for
             each, and the largest N whose primary is no softer than the best (within TOL) is kept. Writes work/stack.npz.
Hooks: ALMACH_N (force a count), ALMACH_DROP (drop size in sensor px, default 1.0), ALMACH_TOL (default 0.10)."""
import numpy as np, cv2
from common import *

DROP = float(os.environ.get('ALMACH_DROP', '1.0'))
TOL = float(os.environ.get('ALMACH_TOL', '0.10'))
REF = np.array([CROP['w'] / 2, CROP['h'] / 2 + 0.0])          # where the primary lands on the output canvas (sensor px)
CAN = (CROP['h'], CROP['w'])


def drizzle(A, reg, idx, drop=DROP, scale_flux=True):
    """A: (n, 4, h2, w2) cleaned planes. reg: step 3 rows. idx: frames to use. Returns (4, H, W) planes R, G, B (G = G1 + G2 together), coverage (3, H, W)."""
    fl = np.array([reg[i]['flux'] for i in idx]); f0 = np.median([r['flux'] for r in reg])
    num = np.zeros((3,) + CAN); den = np.zeros((3,) + CAN)
    h2, w2 = A.shape[2:]; Y, X = np.mgrid[0:h2, 0:w2]
    for i in idx:
        s = f0 / reg[i]['flux'] if scale_flux else 1.0
        for ci, (plane_ids, key) in enumerate((([0], 'R'), ([1, 2], 'G'), ([3], 'B'))):
            sh = REF - np.array(reg[i]['plane_sensor_xy'][key])      # shift to apply, sensor px
            for p in plane_ids:
                ox, oy = OFFS[p]
                u = 2 * X + ox + sh[0]; v = 2 * Y + oy + sh[1]        # position on the canvas of each sample's centre
                val = A[i, p] * s
                ux = u - drop / 2; vy = v - drop / 2                  # the drop's left / top edge
                ix = np.floor(ux + 0.5).astype(int); iy = np.floor(vy + 0.5).astype(int)   # output pixel j covers [j - 0.5, j + 0.5]
                for dy in range(0, int(np.ceil(drop)) + 2):
                    j = iy + dy; wy = np.clip(np.minimum(vy + drop, j + 0.5) - np.maximum(vy, j - 0.5), 0, None)
                    for dx in range(0, int(np.ceil(drop)) + 2):
                        k = ix + dx; wx = np.clip(np.minimum(ux + drop, k + 0.5) - np.maximum(ux, k - 0.5), 0, None)
                        w = wx * wy; ok = (w > 0) & (j >= 0) & (j < CAN[0]) & (k >= 0) & (k < CAN[1])
                        np.add.at(num[ci], (j[ok], k[ok]), (w * val)[ok]); np.add.at(den[ci], (j[ok], k[ok]), w[ok])
    return num / np.maximum(den, 1e-9), den


def measure(st):
    """Primary half-flux diameter (sensor px -> arcsec) and compactness of a stack's luminance (R + G + B), companion masked."""
    lum = cv2.GaussianBlur((st[0] + 2 * st[1] + st[2]).astype(np.float32) * 0.25, (0, 0), 0.01)
    c = lum[int(REF[1]) - 40:int(REF[1]) + 40, int(REF[0]) - 40:int(REF[0]) + 40]; yy, xx = np.mgrid[0:80, 0:80]
    m = (c - np.median(c)); y0, x0 = np.unravel_index(cv2.GaussianBlur(m, (0, 0), 3).argmax(), m.shape)
    for _ in range(8):
        w = np.clip(m, 0, None) * ((xx - x0) ** 2 + (yy - y0) ** 2 <= 14 ** 2); x0, y0 = (w * xx).sum() / w.sum(), (w * yy).sum() / w.sum()
    # the companion lies to the lower left (about -22, +12 sensor px)
    d2 = (xx - x0) ** 2 + (yy - y0) ** 2; dc2 = (xx - (x0 - 22)) ** 2 + (yy - (y0 + 12)) ** 2
    a = (d2 <= 14 ** 2) & (dc2 > 9 ** 2); v = np.clip(m[a], 0, None); r = np.sqrt(d2[a]); o = np.argsort(r); cum = np.cumsum(v[o]) / v.sum()
    hfd = 2 * r[o][np.searchsorted(cum, 0.5)]; comp = (v ** 2).sum() / v.sum() ** 2
    return float(hfd), float(hfd * SCALE), float(comp * 1000), (float(x0), float(y0))


if __name__ == '__main__':
    A = np.load(W('crops.npy')); reg = jload('step3_register.json')['frames']
    order = sorted(range(len(reg)), key=lambda i: reg[i]['hfd_cell_px'])
    print('order, sharpest first:', [(i, round(reg[i]['hfd_cell_px'] * 2 * SCALE, 2)) for i in order])
    table = []
    for N in (3, 5, 7, 9, 11, 13):
        st, cov = drizzle(A, reg, order[:N]); h, ha, cp, _ = measure(st)
        table.append(dict(n=N, primary_hfd_arcsec=round(ha, 3), compactness_x1000=round(cp, 3), frames=order[:N]))
        print('N=%2d  primary HFD %.2f"  compactness x1000 %.2f' % (N, ha, cp))
    best = min(t['primary_hfd_arcsec'] for t in table)
    N = int(os.environ.get('ALMACH_N', max(t['n'] for t in table if t['primary_hfd_arcsec'] <= best * (1 + TOL))))
    print('choose N = %d (largest count whose primary is within %.0f%% of the sharpest, %.2f")' % (N, TOL * 100, best))
    use = order[:N]; st, cov = drizzle(A, reg, use)
    c = cov[:, int(REF[1]) - 150:int(REF[1]) + 150, int(REF[0]) - 150:int(REF[0]) + 150]
    print('drop %.2f sensor px; coverage (sum of drop weights per output pixel) in the 300 px box round the pair: R min %.2f mean %.2f, G min %.2f mean %.2f, B min %.2f mean %.2f' % (
        DROP, c[0].min(), c[0].mean(), c[1].min(), c[1].mean(), c[2].min(), c[2].mean()))
    np.savez_compressed(W('stack.npz'), planes=st.astype(np.float32), coverage=cov.astype(np.float32), ref=REF, frames=np.array(use))
    jdump(dict(order_sharpest_first=order, comparison=table, chosen_n=N, tolerance=TOL, used_frames=[reg[i]['file'] for i in use], dropped_frames=[dict(file=reg[i]['file'], hfd_arcsec=round(reg[i]['hfd_cell_px'] * 2 * SCALE, 2)) for i in order[N:]],
               drop_sensor_px=DROP, coverage_300px_box=dict(min=[float(x.min()) for x in c], mean=[float(x.mean()) for x in c]), output='sensor pixels, 0.388 arcsec; primary placed at canvas (%.0f, %.0f)' % tuple(REF)), 'step4_stack.json')
