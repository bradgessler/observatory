"""Check flats against a run's own open sky ("check the flat against the hour"), before anything is stacked.

What it does: from the RAW frames of one run (read in place), the sky as the optics delivered it that hour, per colour
plane, with the stars (rawplanes.star_mask, per frame) and the target (ellipses in plane px, grown for the field's
wander) left out:
  large scale  each frame's plane / its clipped mean level (inside 1200 plane px of the centre, outside the masks);
               16 px clipped block means; the median over the frames, without registration (the stars are masked and
               the field wanders by tens of px; the optics do not).
  small scale  each frame's plane over its own large scale (twilight_flat.large_scale), 2 x 2 px bin means; the median
               over the frames. Dust shadows show here.
Then, for each flat given, what it leaves on that sky:
  large        remainder = sky / flat (16 px blocks), median 1: robust rms, 1st to 99th percentile, the medians in rings
               of sensor radius and on the four sides; a plane a + b x + c y fitted (a real slope of the sky is not a flat
               error) and the rms after it. A perfect flat under an even sky leaves 1 everywhere.
  small        green: (sky small scale) / (flat small scale), Gaussian 2 bins: shadows the flat left (connected places
               below 0.99, at least 12 bins), how many, the deepest; the dust map's correlation; the shift that best
               lays the flat's dust on the sky's (phase correlation, 2 x 2 bins).
  per colour   the flat's own deep shadows (over 4%): their depth in this sky over their depth in the flat, per colour.
               1 means the shadows are as deep in this sky as in the flat. A ratio s < 1 in one colour only is what light
               the dust does not shadow, or a black level set too low, of about sky x (1 - s) DN does (an additive term
               changes the depth of a shadow on a faint sky); s > 1 the opposite. So this is also the check that a flat
               made at another ISO fits.

Inputs:  frames (RAW paths), objects (list of dict(centre_px=[x, y], semi_major_px, semi_minor_px, major_axis_angle_deg)
         in plane px), grow (px), flats {name: (4, 2012, 3012) array}.
Outputs: a dict (JSON-able) of the numbers above; optionally a picture of the green remainders.
Recipe entries: flatcheck{frames, masks, sky_level_dn, per flat: large{...}, small{...}, per_colour_slope{...}}.

CLI:  python flatcheck.py --frames <glob or @list.txt> --flat name=<dir>[:smallscale] ... [--object x y a b angle]
      [--grow 60] [--out check.json] [--png check.png]"""
import argparse, glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawplanes as rp
import twilight_flat as tf

BK = 32             # large scale on 32 px clipped block means (a 16 px block of the red sky is 3% noise even over 30 frames)
SMALL_SIGMA = 4.0   # bins of 2 x 2 px: the night sky's small scale is noisy (red: 2 electrons a pixel), so shadows are searched after this Gaussian
NORM_R = 1200


def ellipse_mask(e, shape, grow=0.0):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    a = np.radians(e['major_axis_angle_deg']); dx = xx - e['centre_px'][0]; dy = yy - e['centre_px'][1]
    u = dx * np.cos(a) + dy * np.sin(a); v = -dx * np.sin(a) + dy * np.cos(a)
    return (u / (e['semi_major_px'] + grow)) ** 2 + (v / (e['semi_minor_px'] + grow)) ** 2 <= 1


def _bin2(a):
    h, w = a.shape[0] // 2 * 2, a.shape[1] // 2 * 2
    with np.errstate(all='ignore'):
        return np.nanmean(a[:h, :w].reshape(h // 2, 2, w // 2, 2).transpose(0, 2, 1, 3).reshape(h // 2, w // 2, 4), axis=2).astype(np.float32)


def _one(args):
    path, objects, grow = args
    P, meta = rp.read_planes(path)
    m = rp.star_mask(0.5 * (P[1] + P[2]))
    for e in objects: m |= ellipse_mask(e, m.shape, grow)
    yy, xx = np.mgrid[0:rp.H2, 0:rp.W2]
    near = np.hypot(xx - rp.W2 / 2, yy - rp.H2 / 2) < NORM_R
    big = np.empty((4, rp.H2 // BK, rp.W2 // BK), np.float32); small = []; lev = []
    for p in range(4):
        L = rp.clipped_mean(P[p][near & ~m])[0]; lev.append(L)
        Q = np.where(m, np.nan, P[p] / np.float32(L))
        big[p] = rp.block_means(Q, BK)
        small.append(_bin2(Q / tf.large_scale(Q)))
    return big, np.stack(small), lev, float(m.mean())


def own_sky(frames, objects=(), grow=60.0, workers=4):
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_one, [(f, list(objects), grow) for f in frames]))
    with np.errstate(all='ignore'):
        big = np.nanmedian(np.stack([r[0] for r in res]), axis=0)
        cube = np.stack([r[1] for r in res]); small = np.nanmedian(cube, axis=0); n = np.isfinite(cube).sum(0)
    small[n < max(3, len(frames) // 3)] = np.nan
    return dict(big=big, small=small, levels=np.array([r[2] for r in res]), masked=[r[3] for r in res], frames=[os.path.basename(f) for f in frames])


def _sensor_xy(ny, nx, bk):
    yy, xx = np.mgrid[0:ny, 0:nx]
    return (xx * bk + bk / 2) * 2 - rp.CENTRE[0], (yy * bk + bk / 2) * 2 - rp.CENTRE[1]


def describe_large(Q):
    ny, nx = Q.shape; X, Y = _sensor_xy(ny, nx, BK); ok = np.isfinite(Q)
    Q = Q / np.nanmedian(Q); z = Q[ok]
    A = np.stack([np.ones(ok.sum()), X[ok] / 3000, Y[ok] / 3000], 1); keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], z[keep], rcond=None); r = z - A @ co; s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3.5 * s
    rr = np.hypot(X, Y)[ok]; rings = []
    for a, b in ((0, 600), (600, 1200), (1200, 1800), (1800, 2400), (2400, 3000), (3000, 3700)):
        mm = (rr >= a) & (rr < b)
        rings.append(dict(r_sensor_px=[a, b], blocks=int(mm.sum()), remainder=round(float(np.median(z[mm])), 4) if mm.sum() > 5 else None,
                          after_plane=round(float(np.median(r[mm]) + 1), 4) if mm.sum() > 5 else None))
    side = lambda sel: round(float(np.median(z[sel[ok]])), 4) if sel[ok].sum() > 5 else None
    lo, hi = np.percentile(z, [1, 99]); lo2, hi2 = np.percentile(r, [1, 99])
    return dict(blocks=int(ok.sum()), robust_rms=float(1.4826 * np.median(np.abs(z - np.median(z)))), range_1_99_pct=[float(lo), float(hi)],
                plane=dict(at_centre=float(co[0]), across_the_long_side=float(co[1] * 6024 / 3000), across_the_short_side=float(co[2] * 4024 / 3000)),
                robust_rms_after_plane=float(1.4826 * np.median(np.abs(r - np.median(r)))), range_after_plane_1_99_pct=[float(lo2 + 1), float(hi2 + 1)], rings=rings,
                sides=dict(left=side(X < -1500), right=side(X > 1500), top=side(Y < -1000), bottom=side(Y > 1000)))


def _smooth(a, s=2.0):
    ok = np.isfinite(a).astype(np.float32); f = np.where(ok > 0, a, 0).astype(np.float32)
    w = cv2.GaussianBlur(ok, (0, 0), s)
    out = cv2.GaussianBlur(f, (0, 0), s) / np.maximum(w, 1e-3); out[w < 0.5] = np.nan
    return out


def _depth(S, x, y, r):
    """1 - mean inside 0.7 r over the median of the ring r + 8 .. r + 30 (plane px) of a 2 x 2-bin map."""
    i0, j0 = int(max((y - r - 32) // 2, 0)), int(max((x - r - 32) // 2, 0)); i1, j1 = int((y + r + 32) // 2) + 1, int((x + r + 32) // 2) + 1
    sub = S[i0:i1, j0:j1]
    yy, xx = np.mgrid[i0:i0 + sub.shape[0], j0:j0 + sub.shape[1]]
    d = np.hypot(xx * 2 + 0.5 - x, yy * 2 + 0.5 - y)
    inn = (d <= max(0.7 * r, 4)) & np.isfinite(sub); ring = (d > r + 8) & (d < r + 30) & np.isfinite(sub)
    if inn.sum() < 3 or ring.sum() < 10: return None
    return float(1 - np.mean(sub[inn]) / np.median(sub[ring]))


def against(sky, F, name='flat'):
    """What flat F (4, 2012, 3012) leaves on this sky."""
    out = dict(flat=name, large={}, per_colour_slope={})
    Fs = []
    for p in range(4):
        out['large'][rp.PLANE_NAMES[p]] = describe_large(sky['big'][p] / rp.block_means(F[p], BK))
        Fs.append(_bin2(F[p] / tf.large_scale(F[p])))
    Fs = np.stack(Fs)
    gs = 0.5 * (sky['small'][1] + sky['small'][2]); gf = 0.5 * (Fs[1] + Fs[2])
    R = _smooth(gs / gf, SMALL_SIGMA); Rs = np.nan_to_num(R, nan=1.0)
    noise = float(1.4826 * np.nanmedian(np.abs(R - np.nanmedian(R))))
    t = min(0.99, 1 - 4 * noise)
    found = tf.find_shadows(Rs, t, 12); found2 = [s_ for s_ in found if s_['depth'] > 0.02]
    ok = np.isfinite(gs) & np.isfinite(gf)
    a = np.where(ok, 1 - gs, 0).astype(np.float32); b = np.where(ok, 1 - gf, 0).astype(np.float32)
    win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
    (dx, dy), resp = cv2.phaseCorrelate(b, a, win)
    a2, b2 = _smooth(gs, 1.0), _smooth(gf, 1.0); ok2 = np.isfinite(a2) & np.isfinite(b2)
    out['small'] = dict(what='green: sky small scale / flat small scale, Gaussian %.0f bins of 2 x 2 plane px; a shadow left = a connected place below 1 - max(1%%, 4 x the map noise) over at least 12 bins' % SMALL_SIGMA,
                        map_noise=noise, threshold=t, shadows_left=len(found), deeper_than_2pct=len(found2), deepest=found[0]['depth'] if found else 0.0, area_fraction_below_threshold=float((Rs < t).mean()),
                        worst=found[:10], robust_rms=noise,
                        dust_correlation=float(np.corrcoef(1 - a2[ok2], 1 - b2[ok2])[0, 1]), shift_flat_to_sky_plane_px=[round(2 * dx, 2), round(2 * dy, 2)], shift_response=float(resp))
    # per colour: the flat's own deep shadows (found in its green small scale), their depth in this sky and in the flat
    S2f = cv2.GaussianBlur(gf, (0, 0), 2.0)
    deep = [s_ for s_ in tf.find_shadows(np.nan_to_num(S2f, nan=1.0), 0.97, 20) if s_['depth'] > 0.04][:40]
    for p in range(4):
        sp, fp = sky['small'][p], Fs[p]
        ratios = []
        for s_ in deep:
            ds, df = _depth(sp, *s_['plane_px'], s_['radius_plane_px']), _depth(fp, *s_['plane_px'], s_['radius_plane_px'])
            if ds is not None and df and df > 0.02: ratios.append(ds / df)
        L = float(np.median(sky['levels'][:, p])); r_ = float(np.median(ratios)) if ratios else None
        out['per_colour_slope'][rp.PLANE_NAMES[p]] = dict(depth_in_sky_over_depth_in_flat=round(r_, 3) if r_ else None, spread=round(float(1.4826 * np.median(np.abs(np.array(ratios) - r_))) / np.sqrt(len(ratios)), 3) if ratios else None,
                                                       shadows=len(ratios), sky_dn=round(L, 1), unshadowed_light_dn_if_additive=round(L * (1 - r_), 2) if r_ else None)
    out['per_colour_slope_what'] = ('the flat\'s deep shadows (over 4%%, at least 20 bins; up to 40): depth = 1 - mean inside 0.7 r / median of the ring r + 8 .. r + 30 px, in this sky and in the flat; '
                                    'the median ratio per colour. 1: as deep here as in the flat. Below 1 in one colour only: light in that colour that the dust does not shadow, '
                                    'or a black level set too low, by about sky x (1 - ratio) DN; above 1: the opposite')
    return out


def picture(sky, flats, path):
    rows = []
    for name, F in flats.items():
        Q = 0.5 * (sky['big'][1] / rp.block_means(F[1], BK) + sky['big'][2] / rp.block_means(F[2], BK)); Q /= np.nanmedian(Q)
        rows.append(cv2.resize((np.clip((np.nan_to_num(Q, nan=0.96) - 0.96) / 0.08, 0, 1) * 255).astype(np.uint8), None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    cv2.imwrite(path, np.vstack([np.vstack([r, np.full((6, r.shape[1]), 128, np.uint8)]) for r in rows]))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--frames', required=True); ap.add_argument('--flat', action='append', required=True)
    ap.add_argument('--object', nargs=5, type=float, action='append', default=[]); ap.add_argument('--grow', type=float, default=60)
    ap.add_argument('--out'); ap.add_argument('--png'); ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--cache', help='an .npz to keep the measured sky in (read if it exists): a scratch file, delete it after')
    a = ap.parse_args()
    frames = [l.strip() for l in open(a.frames[1:])] if a.frames.startswith('@') else sorted(glob.glob(os.path.expanduser(a.frames)))
    objs = [dict(centre_px=[o[0], o[1]], semi_major_px=o[2], semi_minor_px=o[3], major_axis_angle_deg=o[4]) for o in a.object]
    if a.cache and os.path.exists(a.cache):
        z = np.load(a.cache, allow_pickle=True); sky = dict(big=z['big'], small=z['small'], levels=z['levels'], masked=list(z['masked']), frames=list(z['frames']))
    else:
        sky = own_sky(frames, objs, a.grow, a.workers)
        if a.cache: np.savez(a.cache, **sky)
    flats = {}
    for spec in a.flat:
        n, d = spec.split('=', 1)
        flats[n] = tf.load(os.path.expanduser(d)) if not d.endswith('.npz') else np.stack([np.load(os.path.expanduser(d))[k].astype(np.float32) for k in rp.PLANE_NAMES])
    res = dict(frames=sky['frames'], objects=objs, grow_px=a.grow, sky_level_dn=dict(zip(rp.PLANE_NAMES, np.median(sky['levels'], 0).round(2).tolist())),
               masked_fraction_median=float(np.median(sky['masked'])), flats=[against(sky, F, n) for n, F in flats.items()])
    for r in res['flats']:
        print('== %s' % r['flat'])
        for k, v in r['large'].items():
            print('  %-2s large: rms %.4f (1-99%% %.3f..%.3f); plane %+.3f long side %+.3f short side; after plane rms %.4f (%.3f..%.3f); rings %s; sides L %s R %s T %s B %s' % (
                k, v['robust_rms'], *v['range_1_99_pct'], v['plane']['across_the_long_side'], v['plane']['across_the_short_side'], v['robust_rms_after_plane'], *v['range_after_plane_1_99_pct'],
                ' '.join('%.3f' % x['after_plane'] if x['after_plane'] else '-' for x in v['rings']), v['sides']['left'], v['sides']['right'], v['sides']['top'], v['sides']['bottom']))
        s = r['small']
        print('  small: map noise %.4f; %d shadows left below %.3f (%d deeper than 2%%, deepest %.3f), %.2f%% of the sensor; dust correlation %.2f; shift flat->sky %s plane px' % (s['map_noise'], s['shadows_left'], s['threshold'], s['deeper_than_2pct'], s['deepest'], 100 * s['area_fraction_below_threshold'], s['dust_correlation'], s['shift_flat_to_sky_plane_px']))
        print('  shadow depth sky / flat per colour (ratio, +-, shadows, sky DN, unshadowed DN):', {k: (v['depth_in_sky_over_depth_in_flat'], v['spread'], v['shadows'], v['sky_dn'], v['unshadowed_light_dn_if_additive']) for k, v in r['per_colour_slope'].items()})
    if a.out: json.dump(res, open(a.out, 'w'), indent=1)
    if a.png: picture(sky, flats, a.png)
