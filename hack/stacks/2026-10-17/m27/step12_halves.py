"""Step 12: are the faint outer lobes (the "ears", the grey halo that fills the Dumbbell out to an apple shape round the
bright cyan body) real? The skill's test: two independent stacks, the odd and the even frames alone (step 8, coadded and
brought to one common PSF), and the same measure on blank sky.

  light       green (mean of G1 and G2), the stack's own sky at zero; stars taken out by a 9 x 9 median of the 4 x shrunk
              picture (stars are 6 px across, the halo hundreds), back to full size.
  places      sectors of 30 degrees (position angle north through east, from step 9's plate solution) in rings round the
              central star: 2 to 3, 3 to 4, 4 to 5 and 5 to 6.5 arcmin (the bright body is 8 x 5.6 arcmin: along its long
              axis the ears reach about 4, across it the waist about 2.8; beyond is the faint halo).
  sky         a plane fitted to the light further than 9 arcmin from the star is taken off first (step 10 does the same
              for the picture), so the sky's own slope is not read as light or as a hole.
  floor       the same sector shapes laid on BLANK_N places of blank sky in the same stack (at least 11 arcmin from the
              star, inside the well-covered rectangle): their spread is what sky, flat and noise leave at that size.
  verdict     a sector is SEEN when its mean is above 3 x that spread in the odd AND in the even frames alone.
Writes work/step12_halves.json and v_halves.png (the odd and even halves side by side, same stretch)."""
import json, os
import numpy as np, cv2
from common import *

RINGS = [(2.0, 3.0), (3.0, 4.0), (4.0, 5.0), (5.0, 6.5)]
BLANK_N = 24
rng = np.random.default_rng(27)

if __name__ == '__main__':
    s9 = jload('step9_solve.json'); c = s9['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
    scale = s9['pixscale_arcsec']; north = np.radians(s9['north_angle_from_up_deg_clockwise']); east = np.radians(s9['east_angle_from_up_deg_clockwise'])
    cx, cy = s9['catalogue'][TARGET['name']]['nucleus_centroid_within_12px']

    def clean(a):
        g = np.nan_to_num(0.5 * (a[1] + a[2])[y0:y1, x0:x1]).astype(np.float32)
        from scipy.ndimage import median_filter
        sm = median_filter(cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA), size=9, mode='nearest').astype(np.float32)
        return cv2.resize(sm, (g.shape[1], g.shape[0]), interpolation=cv2.INTER_LINEAR)
    H_, W_ = y1 - y0, x1 - x0
    imgs = {k: clean(np.load(W('stack_%s.npy' % k))) for k in ('mean', 'odd', 'even')}
    yy, xx = np.mgrid[0:H_, 0:W_].astype(np.float32)
    # the sky's own slope across the field (step 10 fits the same for the picture): a plane a + b x + c y fitted to the mean
    # stack's star-cleaned light further than 9 arcmin from the star (64 px block medians, 3-sigma clipped), taken off all three
    far = np.hypot(xx - cx, yy - cy) * scale / 60 > 9
    BK = 64; ny, nx = H_ // BK, W_ // BK
    bm = lambda a_: a_[:ny * BK, :nx * BK].reshape(ny, BK, nx, BK).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    fz = bm(np.where(far, imgs['mean'], np.nan)); ok = np.isfinite(fz).mean(2) > 0.8
    with np.errstate(all='ignore'): med = np.nanmedian(fz, 2)
    by, bx = np.mgrid[0:ny, 0:nx]; A = np.stack([np.ones(ok.sum()), bx[ok] * BK + BK / 2, by[ok] * BK + BK / 2], 1); z = med[ok]; keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], z[keep], rcond=None); rr = z - A @ co; sd_ = 1.4826 * np.median(np.abs(rr[keep] - np.median(rr[keep]))); keep = np.abs(rr) < 3 * sd_
    plane = (co[0] + co[1] * xx + co[2] * yy).astype(np.float32)
    for k in imgs: imgs[k] = imgs[k] - plane
    print('sky plane taken off (green, DN): %+.2f at the origin, %+.2f across the width, %+.2f down the height; block rms after %.2f' % (co[0], co[1] * W_, co[2] * H_, np.std(rr[keep])))

    def sector_masks(px, py):
        dx, dy = xx - px, yy - py; r = np.hypot(dx, dy) * scale / 60
        # position angle: the angle from north towards east, in the picture's own axes (up = -y)
        nv = np.array([np.sin(north), -np.cos(north)]); ev = np.array([np.sin(east), -np.cos(east)])
        pa = (np.degrees(np.arctan2(dx * ev[0] + dy * ev[1], dx * nv[0] + dy * nv[1])) + 360) % 360
        return r, pa
    r0, pa0 = sector_masks(cx, cy)
    blank = []
    while len(blank) < BLANK_N:
        bx, by = rng.uniform(0, W_), rng.uniform(0, H_)
        if np.hypot(bx - cx, by - cy) * scale / 60 >= 11 + 6.5 * 0 and 6.5 * 60 / scale < bx < W_ - 6.5 * 60 / scale and 6.5 * 60 / scale < by < H_ - 6.5 * 60 / scale:
            blank.append((bx, by))
    # blank sky: whole sectors would reach back to the nebula; instead the same AREA as each sector, as a disc of equal area
    rows = []
    for a, b in RINGS:
        for s in range(0, 360, 30):
            m = (r0 >= a) & (r0 < b) & (pa0 >= s) & (pa0 < s + 30)
            area = int(m.sum()); rad = np.sqrt(area / np.pi)
            vals = {k: float(v[m].mean()) for k, v in imgs.items()}
            fl = []
            for bx, by in blank:
                d = np.hypot(xx - bx, yy - by) <= rad
                if np.hypot(bx - cx, by - cy) - rad > 9 * 60 / scale: fl.append([float(imgs[k][d].mean()) for k in ('odd', 'even')])
            fl = np.array(fl); sd = float(1.4826 * np.median(np.abs(fl - np.median(fl, 0)), 0).mean()) if len(fl) >= 6 else float('nan')
            seen = vals['odd'] > 3 * sd and vals['even'] > 3 * sd
            rows.append(dict(ring_arcmin=[a, b], pa_deg=[s, s + 30], px=area, mean_dn=round(vals['mean'], 3), odd_dn=round(vals['odd'], 3), even_dn=round(vals['even'], 3), blank_spread_dn=round(sd, 3), blank_places=len(fl),
                             odd_sigma=round(vals['odd'] / sd, 1), even_sigma=round(vals['even'] / sd, 1), seen=bool(seen)))
            print('ring %.1f-%.1f arcmin, PA %3d-%3d: stack %6.2f DN | odd %6.2f even %6.2f | blank spread %.2f (%d places) -> %5.1f / %5.1f sigma %s' % (a, b, s, s + 30, vals['mean'], vals['odd'], vals['even'], sd, len(fl), vals['odd'] / sd, vals['even'] / sd, 'SEEN in both halves' if seen else ''), flush=True)
    sm = [r_ for r_ in rows if r_['ring_arcmin'] == [4.0, 5.0]]; so = [r_ for r_ in rows if r_['ring_arcmin'] == [5.0, 6.5]]
    verdict = ('the halo (4 to 5 arcmin from the star): seen in both halves in %d of 12 sectors; 5 to 6.5 arcmin: %d of 12.' % (sum(r_['seen'] for r_ in sm), sum(r_['seen'] for r_ in so)))
    print(verdict)
    jdump(dict(what=__doc__.split('\n')[0], rings=RINGS, sectors=rows, blank_places=[[round(a, 1), round(b, 1)] for a, b in blank], sky_plane_dn=dict(a=float(co[0]), across_width=float(co[1] * W_), down_height=float(co[2] * H_)), verdict=verdict), 'step12_halves.json')
    v = np.hstack([imgs['odd'], imgs['even']]); v = np.clip(np.arcsinh(v / 2) / np.arcsinh(60), 0, 1)
    cv2.imwrite(W('v_halves.png'), cv2.resize((v * 255).astype(np.uint8), None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA))
