"""Step 6: the flat field, measured from tonight's own sky. There are no flat frames. The galaxy fills the M31 frames,
so their sky cannot show the optics' fall-off without assuming the galaxy's shape. But the same camera on the same
telescope shot M76 (25 x 15 s, 0546-0600 UTC) and M57 (33 x 15 s, 0603-0622 UTC) just before the M31 run, at the
same exposure and ISO, with nothing moved in between but the mount: two small nebulae on open sky. That sky, seen
through the optics, is a sky flat.

Per frame and colour plane: hot pixels (step 2's map) and everything brighter than the smooth sky (stars, the
nebula: green above the frame's 64 px median-filtered level by 2.5 sigma, grown by 6 plane px) are left out; the
plane is divided by its own clipped sky level; 8 x 8 plane-px block medians (16 x 16 sensor px). Per run: the
median of those over the frames, WITHOUT registration (stars are masked in every frame).

What is used (the 'large-scale flat'), per colour (R; G1 and G2 together; B), each from its own map, from M76 ONLY: M57 sat low in the west
and its sky slopes by 10 to 20% across the frame, not in a straight line (stray light; there is a tree there), while
M76's sky slopes by under 2.5% per 3000 px. M76's block map with the straight-line slope of a radial + slope fit
divided out (that slope is sky, or a slightly decentred vignette: the two cannot be told apart, and it is the
uncertainty of the flat across the field); blocks more than 2.5 sigma off a smooth version of the map rejected (the
nebula, star halos, dust shadows) and the gaps filled; Gaussian smoothing, sigma 6 blocks (96 sensor px).
Normalised to 1 at the sensor centre. It holds the radially symmetric vignetting AND the extra shading along the top
and bottom edges of the sensor that the 3 October run found (2 to 5%) and a radial profile cannot hold.

Checks written beside it: the radial + slope fit per run and colour (as hack/stacks/2026-10-03/m31/vig2_fit.py) and
its profile against the 3 October one; the dust: each run's block map over its own smooth version (the high-pass
ratio: dust shadows and noise), both runs combined; whether the dust is applied is decided in step 8 by looking."""
import os, glob, json
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from scipy.optimize import least_squares
from scipy.ndimage import median_filter
from common import *

BS = 8
RUNS = dict(m76=('054500', '060030'), m57=('060200', '062200'))
SMOOTH_BLOCKS = float(os.environ.get('M31_FLAT_SMOOTH', '6'))
REJECT_K = 2.5
FILL_BLOCKS = 25.0                                           # Gaussian sigma (blocks) that fills rejected blocks before the smoothing
NEB_R = 500                                                  # sensor px left out round M76 (2.7 x 1.8 arcmin, with its halo)
hot = np.load(W('hotmap.npy'))
COLOURS = dict(R=[0], G=[1, 2], B=[3])


def frames_of(run):
    a, b = RUNS[run]; out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))):
        s = os.path.basename(f)[9:15]
        if not (a <= s <= b): continue
        e, iso = raw_exif(f)
        if (e, iso) == (EXPOSURE_S, ISO): out.append(f)
    return out


def one(path):
    P, ceil, meta = load_planes(path)
    G = (P[1] + P[2]) / 2
    bg = median_filter(cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA), size=9, mode='nearest')
    bg = cv2.resize(bg, (G.shape[1], G.shape[0]), interpolation=cv2.INTER_LINEAR)
    D = cv2.GaussianBlur(G - bg, (0, 0), 1.5)
    s = 1.4826 * np.median(np.abs(D[::4, ::4] - np.median(D[::4, ::4])))
    mask = cv2.dilate((D > 2.5 * s).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13))).astype(bool)
    mask |= hot.any(0)
    ny, nx = h2 // BS, w2 // BS
    out = []; lev = []
    for p in range(4):
        v = np.where(mask, np.nan, P[p])
        l = clipped_stats(v[200:-200:2, 300:-300:2])[0]; lev.append(l)
        b = (v / l)[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
        with np.errstate(all='ignore'):
            n = np.isfinite(b).sum(2); m = np.nanmedian(b, axis=2)
        m[n < BS * BS // 2] = np.nan
        out.append(m.astype(np.float32))
    return os.path.basename(path)[:15], np.stack(out), lev, float(mask.mean())


def radial(c, rho): return 1 + c[0] * rho ** 2 + c[1] * rho ** 4 + c[2] * rho ** 6


def block_xy(shape):
    """Sensor px of block centres (the 2 x 2 cell centre)."""
    ny, nx = shape
    Y, X = np.mgrid[0:ny, 0:nx]
    return 2 * (X * BS + (BS - 1) / 2) + 0.5, 2 * (Y * BS + (BS - 1) / 2) + 0.5


def fit(x, y, v):
    """radial (centred) x straight-line slope, robust."""
    def model(q, x, y):
        rho = np.hypot(x - CENTRE[0], y - CENTRE[1]) / 3000
        return q[0] * radial(q[1:4], rho) * (1 + q[4] * (x - CENTRE[0]) / 3000 + q[5] * (y - CENTRE[1]) / 3000)
    q0 = np.array([np.nanmedian(v), -0.2, 0, 0, 0, 0], float); keep = np.isfinite(v)
    for _ in range(4):
        r = least_squares(lambda q: model(q, x[keep], y[keep]) - v[keep], q0, x_scale=[1, 1, 1, 1, 0.1, 0.1])
        q0 = r.x; res = v - model(q0, x, y); s = 1.4826 * np.nanmedian(np.abs(res[keep] - np.nanmedian(res[keep])))
        keep = np.isfinite(v) & (np.abs(res) < 3 * s)
    return q0, float(np.sqrt(np.mean(res[keep] ** 2)))


def normconv(B, valid, sigma):
    num = cv2.GaussianBlur(np.where(valid, B, 0).astype(np.float32), (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    den = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    return num / np.maximum(den, 1e-6)


def smooth_reject(B, sigma, k=REJECT_K, iters=4):
    """Smooth version of a block map with outlying blocks (both signs) rejected and grown by one block."""
    base = np.isfinite(B); valid = base.copy()
    for _ in range(iters):
        S = normconv(B, valid, sigma)
        r = B / S - 1
        s = 1.4826 * np.nanmedian(np.abs(r[valid] - np.nanmedian(r[valid])))
        bad = ~(np.abs(np.nan_to_num(r, nan=0.0)) < k * s) | ~base
        valid = base & ~cv2.dilate(bad.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    # where the kernel is nearly empty (inside the M76 disc, 31 blocks in radius, wider than the kernel) the smooth
    # value comes from a wide kernel instead, blended in as the kernel's valid weight falls below 0.3
    den = cv2.GaussianBlur(valid.astype(np.float32), (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    wgt = np.clip(den / 0.3, 0, 1)
    return wgt * normconv(B, valid, sigma) + (1 - wgt) * normconv(B, valid, FILL_BLOCKS), valid, float(s)


if __name__ == '__main__':
    tables = {}; info = {}
    for run in RUNS:
        fl = frames_of(run)
        with ProcessPoolExecutor(WORKERS) as ex:
            res = list(ex.map(one, fl))
        cube = np.stack([r[1] for r in res])                    # (n, 4, ny, nx)
        with np.errstate(all='ignore'):
            tables[run] = np.nanmedian(cube, axis=0)
        levs = np.array([r[2] for r in res])
        info[run] = dict(frames=[r[0] for r in res], n=len(res), sky_dn_median=dict(zip(PLANE_NAMES, [round(float(v), 2) for v in np.median(levs, 0)])),
                         sky_dn_range_green=[round(float(levs[:, 1:3].mean(1).min()), 1), round(float(levs[:, 1:3].mean(1).max()), 1)], masked_fraction_median=round(float(np.median([r[3] for r in res])), 3))
        print(run, {k: v for k, v in info[run].items() if k != 'frames'}, flush=True)
        del cube
    np.savez(W('runs_blocks.npz'), **tables)
    shape = tables['m76'].shape[1:]; bx, by = block_xy(shape)
    # M76 itself and its faint halo: a disc of NEB_R sensor px round the brightest smooth blob of the M76 map (its
    # halo is too faint to be rejected block by block, but adds up in the smoothing); filled from round about
    with np.errstate(all='ignore'):
        g76 = np.nanmean(tables['m76'][1:3], axis=0)
    gsm = cv2.GaussianBlur(np.nan_to_num(g76 / np.nanmedian(g76), nan=1.0).astype(np.float32), (0, 0), 3)
    cyb, cxb = np.unravel_index(np.argmax(gsm[20:-20, 20:-20]), gsm[20:-20, 20:-20].shape); cyb += 20; cxb += 20
    neb_xy = [float(bx[cyb, cxb]), float(by[cyb, cxb])]
    neb = np.hypot(bx - neb_xy[0], by - neb_xy[1]) < NEB_R
    tables['m76'][:, neb] = np.nan
    print('M76 found at sensor', np.round(neb_xy).astype(int).tolist(), '; disc of', NEB_R, 'px left out of the flat', flush=True)
    RR = np.arange(0, 3700, 100)
    rep = dict(method=__doc__, runs=info, fill_sigma_blocks=FILL_BLOCKS, m76_sensor_xy=neb_xy, m76_disc_radius_px=NEB_R, block_plane_px=BS, smooth_sigma_blocks=SMOOTH_BLOCKS, reject_k=REJECT_K, colours={})
    flat_blocks = {}; hp = {}
    try:
        old = json.load(open(os.path.expanduser('~/.observatory/nights/2026-10-03-a6000/m31/mosaic/calibration-from-core-run/vignette.json')))
    except Exception:
        old = None
    for cname, plist in COLOURS.items():
        crep = dict(radial_fit={})
        for run in RUNS:
            with np.errstate(all='ignore'):
                B = np.nanmean(tables[run][plist], axis=0)
            q, rms = fit(bx.ravel(), by.ravel(), B.ravel())
            crep['radial_fit'][run] = dict(k=round(float(q[0]), 5), a=[round(float(c), 5) for c in q[1:4]], slope_per_3000px=[round(float(q[4]), 5), round(float(q[5]), 5)], rms=round(rms, 5),
                                           V_at_r={str(r_): round(float(radial(q[1:4], r_ / 3000)), 4) for r_ in (500, 1000, 1500, 2000, 2500, 3000, 3500)})
            slope = 1 + q[4] * (bx - CENTRE[0]) / 3000 + q[5] * (by - CENTRE[1]) / 3000
            Bs = B / slope
            S, valid, s = smooth_reject(Bs, SMOOTH_BLOCKS)
            hp[(cname, run)] = (Bs / S, valid, s)
            if run == 'm76':
                c0 = S[(np.abs(by - CENTRE[1]) < 160) & (np.abs(bx - CENTRE[0]) < 160)].mean()
                flat_blocks[cname] = (S / c0).astype(np.float32)
                crep['large_scale_flat'] = dict(source='m76', blocks_used_fraction=round(float(valid.mean()), 3), block_noise_fraction=round(s, 4),
                                                noise_of_smooth_flat_fraction_estimate=round(s / np.sqrt(2 * np.pi * SMOOTH_BLOCKS ** 2), 5),
                                                slope_divided_out_per_3000px=[round(float(q[4]), 5), round(float(q[5]), 5)])
            print(cname, run, crep['radial_fit'][run], flush=True)
        # the large-scale flat along the centre row and column, and in rings, against the radial fit and 3 October
        F = flat_blocks[cname]; r = np.hypot(bx - CENTRE[0], by - CENTRE[1]); q = crep['radial_fit']['m76']
        rings = []
        for a_ in range(0, 3600, 300):
            m = (r >= a_) & (r < a_ + 300)
            if m.sum() > 10:
                row = [a_, a_ + 300, round(float(np.median(F[m])), 4), round(float(radial(q['a'], (a_ + 150) / 3000)), 4)]
                if old: row.append(round(float(np.interp(a_ + 150, old['r_px'], old['V'][cname])), 4))
                rings.append(row)
        crep['rings_flat_radialfit_3oct'] = rings
        ny, nx = F.shape
        crep['top_middle_bottom_at_centre_column'] = [round(float(F[2:6, nx // 2 - 3:nx // 2 + 3].mean()), 4), 1.0, round(float(F[-6:-2, nx // 2 - 3:nx // 2 + 3].mean()), 4)]
        crep['left_right_at_centre_row'] = [round(float(F[ny // 2 - 3:ny // 2 + 3, 2:6].mean()), 4), round(float(F[ny // 2 - 3:ny // 2 + 3, -6:-2].mean()), 4)]
        crep['corners_tl_tr_bl_br'] = [round(float(F[2:6, 2:6].mean()), 4), round(float(F[2:6, -6:-2].mean()), 4), round(float(F[-6:-2, 2:6].mean()), 4), round(float(F[-6:-2, -6:-2].mean()), 4)]
        print(cname, 'rings (r0, r1, flat, radial fit, 3 Oct):', rings)
        print(cname, 'top/centre/bottom', crep['top_middle_bottom_at_centre_column'], 'left/right', crep['left_right_at_centre_row'], 'corners', crep['corners_tl_tr_bl_br'], flush=True)
        rep['colours'][cname] = crep
    # Tried and NOT used (kept for the record, flat_blocks_greenshape.npz): red and blue shaped like green, differing
    # only by their radial ring ratio, on the guess that red's top-to-bottom tilt (0.80 at the top, 0.86 at the
    # bottom; green and blue 0.88 / 0.89) was a colour gradient in M76's sky. The M31 stack said otherwise: with it,
    # the faint glow came out 4 to 8 DN too red (white balanced) in a pattern that follows the sensor, not the galaxy
    # (work/trial_flat_colour_shape.json). With each colour's own map the red excess goes. So the tilt is in the
    # optics or the sensor, and each colour is divided by its own map (flat_blocks.npz).
    rr = np.hypot(bx - CENTRE[0], by - CENTRE[1]); per_colour = {c: flat_blocks[c].copy() for c in flat_blocks}
    edges = np.arange(0, 3601, 150); mids = (edges[:-1] + edges[1:]) / 2
    ringmed = {c: np.array([np.median(per_colour[c][(rr >= a_) & (rr < b_)]) for a_, b_ in zip(edges[:-1], edges[1:])]) for c in per_colour}
    rep['colour_ratio_to_green'] = {}; greenshape = dict(G=flat_blocks['G'])
    for c in ('R', 'B'):
        ratio = ringmed[c] / ringmed['G']; rho2 = (mids / 3000) ** 2
        A = np.column_stack([rho2, rho2 ** 2]); co, *_ = np.linalg.lstsq(A, ratio - 1, rcond=None)
        model = 1 + co[0] * (rr / 3000) ** 2 + co[1] * (rr / 3000) ** 4
        greenshape[c] = (flat_blocks['G'] * model).astype(np.float32)
        rep['colour_ratio_to_green'][c] = dict(c1=round(float(co[0]), 5), c2=round(float(co[1]), 5), rings_ratio=[[int(m), round(float(v), 4), round(float(1 + co[0] * (m / 3000) ** 2 + co[1] * (m / 3000) ** 4), 4)] for m, v in zip(mids, ratio)])
        print(c, '/ G ring ratio: at r 1500, 3000, 3500: %s' % [round(float(np.interp(r_, mids, ratio)), 4) for r_ in (1500, 3000, 3500)], flush=True)
    np.savez(W('flat_blocks_greenshape.npz'), bs=BS, **greenshape)
    np.savez(W('flat_blocks.npz'), bs=BS, **flat_blocks)
    # dust: high-pass ratio of green, both runs, inverse-variance combined, smoothed by one block
    num = 0; den = 0; dust_info = {}
    for run in RUNS:
        Rr, valid, s = hp[('G', run)]
        w = 1.0 / s ** 2; ok = np.isfinite(Rr)
        num = num + np.where(ok, Rr, 0) * w; den = den + ok * w
        dust_info[run] = dict(block_noise=round(s, 4))
    D = num / np.maximum(den, 1e-9); D[den == 0] = 1.0
    sD = 1.0 / np.sqrt(np.max(den))
    Ds = cv2.GaussianBlur(D.astype(np.float32), (0, 0), 1.0)
    sDs = 1.4826 * np.median(np.abs(Ds - np.median(Ds)))
    np.savez(W('dust_blocks.npz'), D=D.astype(np.float32), Ds=Ds, sigma_Ds=sDs)
    rep['dust'] = dict(runs=dust_info, smoothed_map_noise=round(float(sDs), 4), deepest_smoothed=round(float(Ds.min()), 3),
                       blocks_below_4_sigma=int((Ds < 1 - 4 * sDs).sum()), blocks_below_6_sigma=int((Ds < 1 - 6 * sDs).sum()))
    print('dust map: smoothed noise %.4f, deepest %.3f, blocks below 4 sigma %d, below 6 sigma %d' % (sDs, Ds.min(), rep['dust']['blocks_below_4_sigma'], rep['dust']['blocks_below_6_sigma']))
    img = np.clip((Ds - 0.90) / 0.15, 0, 1)
    cv2.imwrite(W('dust_map_G.png'), cv2.resize((img * 255).astype(np.uint8), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    for c in COLOURS:
        cv2.imwrite(W('flat_%s.png' % c), (np.clip((flat_blocks[c] - 0.6) / 0.45, 0, 1) * 255).astype(np.uint8))
    jdump(rep, 'step6_flat.json')
