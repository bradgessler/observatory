"""The large scale of a flat from the night's own open sky, over several runs, joined to the twilight flat's dust.

Why: twilight flats carry the dust (hundreds of shadows, measured at 1000 to 4700 DN) but their large scale belongs to
the optics as they were at dawn (on 13 October the telescope was parked at the pole and the light was centred 880 sensor
px right of where it sat all night). A fitted profile from one run's sky (the night flats so far) misses the middle of
the sensor, which every target hides: on 12/13 October it read 1 to 1.5% high there in all four runs that could see it.
So: measure the large scale on the night's sky itself, where several runs together leave little of the sensor unseen.

What it does, per colour plane:
  1. each run's sky as flatcheck.own_sky measures it: frames normalised, stars and the target (ellipses, grown for the
     wander) left out, 32 px clipped block means, the median over the run's frames without registration.
  2. divided by the dust map's own 32 px block means (twilight_flat smallscale_planes.npz), so the dust is not counted
     twice; each run set to median 1.
  3. joined: the median over the runs per block; then each run's own sky slope (a plane fitted to run / median) is
     divided out and the median taken again (twice). A block no run saw is filled from its neighbours (normalised
     Gaussians of growing width). A normalised Gaussian of SMOOTH blocks takes the noise out.
  4. to full size (bilinear between block centres), 1 at the sensor centre (clipped mean of the central 128 x 128 plane
     px), times the twilight small scale: the flat.
The linear part of the result is the mean of the runs' skies; a target's own sky slope is the stack's business (the
picture's sky plane), not the flat's.

Inputs:  runs [dict(name, frames=[RAW paths], objects=[ellipses in plane px], grow=px)], the twilight flat folder
         (its smallscale_planes.npz and flat.json), --exclude a run (leave the target's own run out of its flat),
         --cache-dir for the measured skies (scratch: delete after).
Outputs in --out: flat_planes.npz (R, G1, G2, B float32, 1 at the sensor centre), large_planes.npz (the large scale
         alone), flat_planes.fits (the flat as FITS, IMAGETYP 'MASTER FLAT', every input frame's SHA-256:
         tools/master_fits.py), flat.json (schema observatory.master/1), README.txt, v_skyflat.png (green large scale
         0.6 to 1.05; coverage).
Recipe entries (flat.json): made_from{target, runs{name: frames, sky_level_dn, objects}, excluded, frames},
         formula, large_scale{block_px, smooth_blocks, coverage, runs_per_block, per_run_plane, run_minus_joint_rms},
         dust (the twilight flat's list, so a pipeline's dust check can read it), small_scale_from, made_utc, tool.

CLI:  python skyflat.py --night N --twilight N/flat-twilight --out N/flat-hybrid-m77 --exclude m77
          --run m77 @frames_m77.txt 1551.8,834.5,409.5,347.7,144.16 ...   (name, frames file, ellipses; grow 60 px)"""
import argparse, datetime, json, os, sys
import numpy as np, cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawplanes as rp
import twilight_flat as tf
import flatcheck as fc

SMOOTH = 1.0      # blocks (32 px): the joined map's noise is about 0.2% per block in green before this


def _plane(Q):
    ny, nx = Q.shape; yy, xx = np.mgrid[0:ny, 0:nx]; ok = np.isfinite(Q)
    A = np.stack([np.ones(ok.sum()), (xx[ok] - nx / 2) / nx, (yy[ok] - ny / 2) / ny], 1); z = Q[ok]; keep = np.ones(len(z), bool)
    for _ in range(4):
        co, *_ = np.linalg.lstsq(A[keep], z[keep], rcond=None); r = z - A @ co; s = 1.4826 * np.median(np.abs(r[keep] - np.median(r[keep]))); keep = np.abs(r) < 3.5 * s
    return co[0] + co[1] * (xx - nx / 2) / nx + co[2] * (yy - ny / 2) / ny, co


def _fill(M):
    out = M.copy(); s = 1.0
    while not np.isfinite(out).all() and s < 64:
        ok = np.isfinite(out).astype(np.float32); f = np.where(ok > 0, out, 0).astype(np.float32)
        w = cv2.GaussianBlur(ok, (0, 0), s); v = cv2.GaussianBlur(f, (0, 0), s) / np.maximum(w, 1e-6)
        hole = ~np.isfinite(out) & (w > 0.05); out[hole] = v[hole]; s *= 1.5
    return out


def _nsmooth(M, s):
    return cv2.GaussianBlur(M.astype(np.float32), (0, 0), s, borderType=cv2.BORDER_REFLECT)


def to_full(B, bk=fc.BK, shape=(rp.H2, rp.W2)):
    """Block grid (block (i, j) centred on plane px (j bk + (bk - 1) / 2, i bk + (bk - 1) / 2)) to full size, bilinear."""
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
    return cv2.remap(B.astype(np.float32), (xx - (bk - 1) / 2) / bk, (yy - (bk - 1) / 2) / bk, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def build(runs, twilight, out, exclude=(), cache_dir=None, workers=4):
    os.makedirs(out, exist_ok=True)
    small = tf.load(twilight, 'smallscale_planes.npz'); tj = json.load(open(os.path.join(twilight, 'flat.json')))
    use = [r for r in runs if r['name'] not in exclude]
    skies = {}
    for r in use:
        cp = os.path.join(cache_dir, 'sky_%s.npz' % r['name']) if cache_dir else None
        if cp and os.path.exists(cp):
            z = np.load(cp, allow_pickle=True); skies[r['name']] = dict(big=z['big'], levels=z['levels'], frames=list(z['frames']))
        else:
            s = fc.own_sky(r['frames'], r['objects'], r.get('grow', 60.0), workers); skies[r['name']] = s
            if cp: np.savez(cp, **s)
        print('sky of %s: %d frames, level %s DN' % (r['name'], len(skies[r['name']]['frames']), np.round(np.median(skies[r['name']]['levels'], 0), 1).tolist()), flush=True)
    names = [r['name'] for r in use]
    L = np.empty((4, rp.H2, rp.W2), np.float32); info = dict(per_run_plane={}, run_minus_joint_rms={}, runs_per_block={}, coverage={})
    for p in range(4):
        sb = rp.block_means(small[p], fc.BK)
        maps = []
        for n in names:
            m = skies[n]['big'][p] / sb; maps.append(m / np.nanmedian(m))
        maps = np.stack(maps); planes = {}
        for _ in range(2):
            with np.errstate(all='ignore'): J = np.nanmedian(maps, axis=0)
            for i, n in enumerate(names):
                pl, co = _plane(maps[i] / J); maps[i] /= pl; planes[n] = [float(c) for c in co]
        with np.errstate(all='ignore'): J = np.nanmedian(maps, axis=0)
        cnt = np.isfinite(maps).sum(0)
        info['per_run_plane'][rp.PLANE_NAMES[p]] = planes
        info['run_minus_joint_rms'][rp.PLANE_NAMES[p]] = {n: float(1.4826 * np.nanmedian(np.abs(maps[i] / J - 1))) for i, n in enumerate(names)}
        info['runs_per_block'][rp.PLANE_NAMES[p]] = {str(k): int((cnt == k).sum()) for k in range(len(names) + 1)}
        info['coverage'][rp.PLANE_NAMES[p]] = float((cnt > 0).mean())
        Jf = _nsmooth(_fill(J), SMOOTH)
        full = to_full(Jf)
        c = (slice(rp.H2 // 2 - 64, rp.H2 // 2 + 64), slice(rp.W2 // 2 - 64, rp.W2 // 2 + 64))
        L[p] = full / np.float32(rp.clipped_mean(full[c])[0])
        if p == 1: cnt1 = cnt
        print('%-2s joined %d runs: blocks seen by none %d, by one %d; run against joint rms %s' % (rp.PLANE_NAMES[p], len(names), (cnt == 0).sum(), (cnt == 1).sum(), {n: round(v, 4) for n, v in info['run_minus_joint_rms'][rp.PLANE_NAMES[p]].items()}), flush=True)
    F = tf.compose(L, small)
    c = (slice(rp.H2 // 2 - 64, rp.H2 // 2 + 64), slice(rp.W2 // 2 - 64, rp.W2 // 2 + 64))
    for p in range(4): F[p] /= np.float32(rp.clipped_mean(F[p][c])[0])
    planes = {rp.PLANE_NAMES[p]: {k: v for k, v in tf.describe_plane(L[p], p).items() if not k.endswith('_fit')} for p in range(4)}
    rec = dict(made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tool=os.path.abspath(__file__),
               made_from=dict(target='the night\'s own open sky (%s) for the large scale; twilight flats (%s) for dust and pixel response' % (', '.join(names), twilight),
                              runs={n: dict(frames=skies[n]['frames'], sky_level_dn=dict(zip(rp.PLANE_NAMES, np.median(skies[n]['levels'], 0).round(1).tolist())),
                                            objects=[r for r in use if r['name'] == n][0]['objects'], grow_px=[r for r in use if r['name'] == n][0].get('grow', 60.0)) for n in names},
                              excluded=list(exclude), frames=sum((skies[n]['frames'] for n in names), []),
                              sky_level_dn_median=dict(zip(rp.PLANE_NAMES, np.median(np.concatenate([skies[n]['levels'] for n in names]), 0).round(1).tolist()))),
               formula='flat[p] = large[p] x twilight small scale[p], 1 at the sensor centre; divide plane p (black subtracted) by it',
               large_scale=dict(block_px=fc.BK, smooth_blocks=SMOOTH, **info, fall_off=planes),
               small_scale_from=dict(dir=twilight, frames=tj['made_from']['frames']), dust=tj['dust'])
    np.savez_compressed(os.path.join(out, 'flat_planes.npz'), **{k: F[p] for p, k in enumerate(rp.PLANE_NAMES)})
    np.savez_compressed(os.path.join(out, 'large_planes.npz'), **{k: L[p] for p, k in enumerate(rp.PLANE_NAMES)})
    import master_fits                                         # the same master as FITS (MASTER FLAT), the inputs' SHA-256 in it and in flat.json
    tw_fits = os.path.join(twilight, 'flat_planes.fits')
    master_fits.write(os.path.join(out, 'flat_planes.fits'), F, 'flat', [master_fits.frame_record(p) for r in use for p in r['frames']], rec,
                      'block medians over the runs x the twilight small scale', norm='1 at the sensor centre (central 128 x 128 plane px)',
                      history=[rec['formula'], 'small scale (dust, pixel response) from %s' % twilight] + (['its FITS sha256 %s' % master_fits.om.sha256_file(tw_fits)] if os.path.exists(tw_fits) else []),
                      extra=[('OBS FLAT KIND', 'sky', 'the night\'s open sky x twilight dust')])
    json.dump(rec, open(os.path.join(out, 'flat.json'), 'w'), indent=1)
    g = 0.5 * (L[1] + L[2]); top = np.clip((cv2.resize(g, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA) - 0.6) / 0.45, 0, 1)
    cv = cv2.resize((cnt1 / max(len(names), 1)).astype(np.float32), (top.shape[1], top.shape[0]), interpolation=cv2.INTER_NEAREST)
    cv2.imwrite(os.path.join(out, 'v_skyflat.png'), (np.vstack([top, np.ones((6, top.shape[1])), cv]) * 255).astype(np.uint8))
    lines = ['A flat for the night of %s: the large scale from the night\'s own open sky, the dust from the twilight flats (skyflat.py, %s)' % (os.path.basename(os.path.dirname(out.rstrip('/'))), rec['made_utc']), '',
             'Use: np.load("flat_planes.npz")[name], as the other flats (R, G1, G2, B; 1 at the sensor centre; divide the black-subtracted plane).',
             'Large scale: runs %s (%d frames)%s; 32 px clipped block means of each run\'s sky (stars and targets masked), over the twilight dust map, median over the runs after each run\'s own sky slope was divided out; holes filled from neighbours; Gaussian %.1f blocks.' % (
                 ', '.join(names), len(rec['made_from']['frames']), ' (left out: %s)' % ', '.join(exclude) if exclude else '', SMOOTH),
             'Small scale (dust and pixel response): %s.' % twilight,
             'Blocks no run saw (green): %d of %d; seen by one run only: %d.' % (info['runs_per_block']['G1']['0'], cnt1.size, info['runs_per_block']['G1']['1'])]
    for k, v in planes.items():
        lines.append('  %-2s corners TL %.3f TR %.3f BL %.3f BR %.3f   long side ends %.3f %.3f   short side ends %.3f %.3f' % (k, v['corner_top_left'], v['corner_top_right'], v['corner_bottom_left'], v['corner_bottom_right'], v['long_side_left_end'], v['long_side_right_end'], v['short_side_top_end'], v['short_side_bottom_end']))
    open(os.path.join(out, 'README.txt'), 'w').write('\n'.join(lines) + '\n')
    return rec


def parse_run(spec):
    name, frames, *ells = spec
    fr = [l.strip() for l in open(frames[1:])] if frames.startswith('@') else frames.split(',')
    objs = []
    for e in ells:
        x, y, a, b, ang = [float(v) for v in e.split(',')]
        objs.append(dict(centre_px=[x, y], semi_major_px=a, semi_minor_px=b, major_axis_angle_deg=ang))
    return dict(name=name, frames=fr, objects=objs, grow=60.0)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--twilight', required=True); ap.add_argument('--out', required=True)
    ap.add_argument('--run', nargs='+', action='append', required=True); ap.add_argument('--exclude', nargs='*', default=[])
    ap.add_argument('--cache-dir'); ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    build([parse_run(r) for r in a.run], os.path.expanduser(a.twilight), os.path.expanduser(a.out), a.exclude, a.cache_dir, a.workers)
