"""Master darks per exposure time and ISO, and the hook a pipeline calls to subtract one before flat-fielding.

What a dark is here: a RAW taken with the cap on (or the telescope covered) at the lights' exposure and ISO, ideally
at the same temperature (same night, before or after the lights). It holds what the sensor adds without light: the true
black (the RAW says 512; the 1/60 s ISO 400 frames of 12/13 October put R, G2 and B about 5 DN below that), dark
current, amplifier glow and the hot pixels. Subtracting it before the flat makes the sky's zero true, so a flat no
longer bends faint colours (the night's red flat read steeper than green, as an offset of about 5 DN would make it).

Finding the dark frames (in this order; documented for the capture side):
  1. a sidecar (<stem>.json beside the RAW) with "dark": true at its top level, or "frame": {"type": "dark"};
  2. any RAW under <night>/darks/ (a folder the capture script may fill), with or without sidecars.
Exposure and ISO are read from each RAW's own EXIF (not the sidecar). Frames are grouped by (exposure rounded to
0.01 s, ISO).

Master dark, per group and colour plane: the RAW planes minus the RAW's black level (so the master holds the black
offset too), combined per pixel by a sigma-clipped mean (3 sigma about the median, sigma from the MAD across the
frames; a cosmic ray in one frame drops out). Written as <darks_dir>/master_<exp>s_iso<iso>.npz (R, G1, G2, B float32)
with a .json beside it: the frames, their times, the mean offset per plane, the noise per plane, the hot pixels
(more than 8 sigma above the plane's median, counted), and how many frames.

The hook (subtract): planes (4, h, w) black-subtracted the usual way, the frame's exposure and ISO, and the darks
folder -> planes minus the matching master, and a record for the recipe. No master for that exposure and ISO (exposure
within 1% and the same ISO) -> the planes come back unchanged and the record says so: today's behaviour, where the
pipeline's step 1 finds the hot pixels from the run itself, stands. A pipeline keeps its hot-pixel repair either way
(after a dark it finds few). Scaling a dark to another exposure is not done (no bias frames to separate the offset).

Inputs: a night folder (read only) or a list of RAW paths; a darks output folder.
Outputs: master_<exp>s_iso<iso>.npz, .fits (IMAGETYP 'MASTER DARK', tools/master_fits.py) and .json (schema
observatory.master/1, with the inputs' SHA-256) per group; nothing else is written.
Recipe entries (from subtract): dark{used: true/false, master, frames, exposure_s, iso, offset_dn_per_plane,
  made_utc | why}. From build: the .json beside each master.

CLI:  python darks.py build --night N [--darks-dir N/darks]       find, group, write masters
      python darks.py selftest                                     synthetic test (a made-up dark added and taken off)"""
import argparse, datetime, glob, json, os, sys
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rawplanes as rp

KAPPA = 3.0


def is_dark_sidecar(j):
    return j.get('dark') is True or (isinstance(j.get('frame'), dict) and j['frame'].get('type') == 'dark')


def find_darks(night):
    """RAW paths of dark frames in a night folder, and how each was found."""
    out = {}
    for arw in sorted(glob.glob(os.path.join(night, '*.ARW'))):
        sc = arw[:-4] + '.json'
        if os.path.exists(sc):
            try:
                if is_dark_sidecar(json.load(open(sc))): out[arw] = 'sidecar "dark": true'
            except ValueError:
                pass
    for arw in sorted(glob.glob(os.path.join(night, 'darks', '**', '*.ARW'), recursive=True)):
        out.setdefault(arw, 'in the darks/ folder')
    return out


def key_of(exposure_s, iso):
    return '%gs_iso%d' % (round(float(exposure_s), 2), int(iso))


def combine(stack, kappa=KAPPA):
    """Sigma-clipped mean over axis 0 of (n, h, w): kappa x 1.4826 MAD about the median; with n < 3 a plain mean."""
    stack = np.asarray(stack, np.float32)
    if len(stack) < 3: return stack.mean(0), np.zeros(stack.shape[1:], np.int16)
    med = np.median(stack, axis=0); mad = 1.4826 * np.median(np.abs(stack - med), axis=0)
    sig = np.maximum(mad, 0.5 * np.median(mad) + 1e-3)
    keep = np.abs(stack - med) <= kappa * sig
    n = keep.sum(0)
    return (np.where(keep, stack, 0).sum(0) / np.maximum(n, 1)).astype(np.float32), (len(stack) - n).astype(np.int16)


def master_from_planes(frames_planes):
    """frames_planes: list of (4, h, w) black-subtracted planes. Returns master (4, h, w) and numbers."""
    M = np.empty_like(frames_planes[0], dtype=np.float32); stats = {}
    for p in range(M.shape[0]):
        M[p], dropped = combine([f[p] for f in frames_planes])
        med = float(np.median(M[p])); mad = float(1.4826 * np.median(np.abs(M[p] - med)))
        single = float(np.median([1.4826 * np.median(np.abs(f[p][::4, ::4] - np.median(f[p][::4, ::4]))) for f in frames_planes]))
        stats[rp.PLANE_NAMES[p]] = dict(offset_dn_median=round(med, 3), offset_dn_mean=round(float(M[p].mean()), 3), noise_master_dn=round(mad, 3), noise_single_frame_dn=round(single, 3),
                                        hot_px_over_8_sigma=int((M[p] - med > 8 * max(mad, 0.5)).sum()), samples_dropped_by_the_clip=int(dropped.sum()))
    return M, stats


def build(paths, darks_dir, how=None):
    """Group RAW dark frames by (exposure, ISO) and write a master per group. Returns {key: json record}."""
    os.makedirs(darks_dir, exist_ok=True)
    groups = defaultdict(list)
    for p in paths:
        e, iso = rp.raw_exif(p); groups[key_of(e, iso)].append((p, e, iso))
    out = {}
    for k, fr in sorted(groups.items()):
        planes = []; blacks = []
        for p, e, iso in fr:
            P, meta = rp.read_planes(p); planes.append(P); blacks.append(meta['black_dn'])
        M, stats = master_from_planes(planes)
        rec = dict(what='master dark: RAW planes minus the RAW black level, sigma-clipped mean per pixel (kappa %.1f)' % KAPPA, key=k, exposure_s=fr[0][1], iso=fr[0][2],
                   frames=[os.path.basename(p) for p, _, _ in fr], found_by={os.path.basename(p): (how or {}).get(p) for p, _, _ in fr}, black_level_in_the_raws=blacks[0],
                   planes=stats, made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tool=os.path.abspath(__file__))
        np.savez_compressed(os.path.join(darks_dir, 'master_%s.npz' % k), **{n: M[i] for i, n in enumerate(rp.PLANE_NAMES)})
        import master_fits                                     # the same master as FITS (MASTER DARK), the inputs' SHA-256 in it and in the JSON
        master_fits.write(os.path.join(darks_dir, 'master_%s.fits' % k), M, 'dark', [master_fits.frame_record(p) for p, _, _ in fr], rec,
                          'sigma-clipped mean, %.1f x 1.4826 MAD about the median' % KAPPA, hot_n=sum(s['hot_px_over_8_sigma'] for s in stats.values()),
                          exptime_s=fr[0][1], iso=fr[0][2], history=[rec['what']])
        json.dump(rec, open(os.path.join(darks_dir, 'master_%s.json' % k), 'w'), indent=1)
        out[k] = rec
        print('master dark %s from %d frames: offset (DN) %s, hot px %s' % (k, len(fr), {n: s['offset_dn_mean'] for n, s in stats.items()}, {n: s['hot_px_over_8_sigma'] for n, s in stats.items()}), flush=True)
    return out


def master_for(exposure_s, iso, darks_dir):
    """Path of the master dark for this exposure (within 1%) and ISO, or None."""
    if not darks_dir or not os.path.isdir(darks_dir): return None
    for j in sorted(glob.glob(os.path.join(darks_dir, 'master_*.json'))):
        r = json.load(open(j))
        if int(r['iso']) == int(iso) and abs(float(r['exposure_s']) - float(exposure_s)) <= 0.01 * float(exposure_s):
            return j[:-5] + '.npz'
    return None


_CACHE = {}


def subtract(planes, exposure_s, iso, darks_dir=None, master=None):
    """The hook: planes minus the matching master dark, or unchanged with a record that says why not.
    planes: (4, h, w) float32 black-subtracted with the RAW's black level (rawplanes.read_planes / a pipeline's
    load_planes). master: an explicit .npz path (overrides the lookup)."""
    path = master or master_for(exposure_s, iso, darks_dir)
    if not path:
        return planes, dict(used=False, exposure_s=exposure_s, iso=iso, darks_dir=darks_dir,
                            why='no master dark for %g s at ISO %d%s: hot pixels from the run itself stand in for it (the pipeline\'s step 1), as before' % (
                                exposure_s, iso, ' in %s' % darks_dir if darks_dir else ' (no darks folder given)'))
    if path not in _CACHE:
        Z = np.load(path); _CACHE[path] = np.stack([Z[k].astype(np.float32) for k in rp.PLANE_NAMES])
    D = _CACHE[path]
    assert D.shape == planes.shape, (D.shape, planes.shape)
    js = path[:-4] + '.json'; r = json.load(open(js)) if os.path.exists(js) else {}
    return planes - D, dict(used=True, master=path, frames=r.get('frames'), exposure_s=exposure_s, iso=iso,
                            offset_dn_per_plane={k: v['offset_dn_mean'] for k, v in r.get('planes', {}).items()}, made_utc=r.get('made_utc'))


def selftest(light=None, n=16, seed=7, check_files=True):
    """A made-up dark added to a real frame and taken off again. Returns the numbers; raises AssertionError on failure."""
    rng = np.random.default_rng(seed)
    if light is None:
        night = os.path.expanduser('~/.observatory/nights/2026-10-12-a6000')
        light = sorted(glob.glob(os.path.join(night, '20261013-0900*.ARW')))[0]
    L, meta = rp.read_planes(light); h, w = L.shape[1:]
    # the made-up dark: a black offset per plane, an amplifier glow from the right edge, 400 hot pixels, read noise
    offset = np.array([-5.2, -1.3, -5.1, -4.8], np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    glow = (3.0 * np.exp(-(w - 1 - xx) / 150.0) * np.exp(-((yy - h / 2) / (h / 3)) ** 2)).astype(np.float32)
    hot = np.zeros((4, h, w), np.float32); hy = rng.integers(0, h, 400); hx = rng.integers(0, w, 400); hp = rng.integers(0, 4, 400)
    hot[hp, hy, hx] = rng.uniform(30, 2000, 400).astype(np.float32)
    pattern = offset[:, None, None] + glow[None] + hot
    sigma = 13.0
    def realisation():
        return np.round((pattern + rng.normal(0, sigma, (4, h, w)).astype(np.float32)) / 4) * 4   # this camera's RAW comes in steps of 4 DN
    darks = [realisation() for _ in range(n)]
    M, stats = master_from_planes(darks)
    light_with_dark = L + realisation()
    with_ = {}
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        np.savez_compressed(os.path.join(td, 'master_15s_iso3200.npz'), **{k: M[i] for i, k in enumerate(rp.PLANE_NAMES)})
        json.dump(dict(iso=3200, exposure_s=15.0, frames=['synthetic'] * n, planes=stats), open(os.path.join(td, 'master_15s_iso3200.json'), 'w'))
        out, rec = subtract(light_with_dark, 15.0, 3200, td)
        same, rec_none = subtract(light_with_dark, 30.0, 3200, td)            # no master for 30 s: unchanged
        _CACHE.clear()
    res = out - L
    expected = sigma * np.sqrt(1 + 1.0 / n)
    for p in range(4):
        r = res[p]; hp_mask = hot[p] > 0
        with_[rp.PLANE_NAMES[p]] = dict(offset_put_in_dn=float(offset[p]), offset_in_master_dn=round(float(M[p].mean() - glow.mean() - hot[p].mean()), 3),
                                        residual_mean_dn=round(float(r.mean()), 3), residual_rms_dn=round(float(r.std()), 3), expected_rms_dn=round(float(np.sqrt(expected ** 2 + 4 ** 2 / 6)), 3),
                                        hot_px=int(hp_mask.sum()), worst_hot_px_left_dn=round(float(np.abs(r[hp_mask]).max()), 2) if hp_mask.any() else None,
                                        glow_left_at_right_edge_dn=round(float(r[:, -20:].mean()), 3), before_subtraction_mean_dn=round(float((light_with_dark - L)[p].mean()), 3))
    ok = all(abs(v['residual_mean_dn']) < 0.1 and abs(v['glow_left_at_right_edge_dn']) < 0.3 and v['residual_rms_dn'] < 1.1 * v['expected_rms_dn'] and (v['worst_hot_px_left_dn'] or 0) < 6 * expected for v in with_.values())
    result = dict(light=os.path.basename(light), dark_frames=n, read_noise_dn=sigma, planes=with_, subtract_record=rec, fallback_record=rec_none,
                  fallback_unchanged=bool(np.array_equal(same, light_with_dark)), passed=bool(ok and np.array_equal(same, light_with_dark) and rec['used'] and not rec_none['used']))
    if check_files:
        result['files'] = selftest_files()
    return result


def selftest_files():
    """The finding and grouping on real RAW files: the near-black twilight frames of 13 October (30 s, ISO 100, sky under
    5 DN) linked into a scratch night with sidecars marked "dark": true, and two linked under darks/. Nothing in the
    real night folder is touched."""
    import tempfile, shutil
    night = os.path.expanduser('~/.observatory/nights/2026-10-12-a6000')
    pick = [os.path.join(night, f) for f in ('20261013-133110-DSC01731.ARW', '20261013-133252-DSC01732.ARW', '20261013-133434-DSC01733.ARW', '20261013-133616-DSC01734.ARW')]
    pick = [p for p in pick if os.path.exists(p)]
    with tempfile.TemporaryDirectory() as td:
        os.makedirs(os.path.join(td, 'darks'))
        for i, p in enumerate(pick):
            b = os.path.basename(p)
            if i < 2:
                os.symlink(p, os.path.join(td, b)); j = json.load(open(p[:-4] + '.json')); j['dark'] = True
                json.dump(j, open(os.path.join(td, b[:-4] + '.json'), 'w'))
            else:
                os.symlink(p, os.path.join(td, 'darks', b))
        os.symlink(os.path.join(night, '20261013-140302-DSC01748.ARW'), os.path.join(td, '20261013-140302-DSC01748.ARW'))   # a light: must not be found
        found = find_darks(td)
        recs = build(list(found), os.path.join(td, 'masters'), found)
        P, meta = rp.read_planes(pick[0])
        out, rec = subtract(P, 30.0, 100, os.path.join(td, 'masters'))
        _CACHE.clear()
    return dict(found={os.path.basename(k): v for k, v in found.items()}, masters={k: dict(frames=v['frames'], offset_dn=v and {n: s['offset_dn_mean'] for n, s in v['planes'].items()}) for k, v in recs.items()},
                subtract_used=rec['used'], light_not_found='20261013-140302-DSC01748.ARW' not in [os.path.basename(k) for k in found],
                note='these frames are dawn sky at 13:31 to 13:36 UTC with 0 to 5 DN of light, not true darks: the offsets include that light')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build'); b.add_argument('--night', required=True); b.add_argument('--darks-dir')
    t = sub.add_parser('selftest'); t.add_argument('--out')
    a = ap.parse_args()
    if a.cmd == 'build':
        night = os.path.expanduser(a.night); found = find_darks(night)
        if not found: raise SystemExit('no dark frames in %s (sidecar "dark": true, or RAWs under darks/): nothing to build; pipelines keep finding hot pixels from the run' % night)
        build(list(found), os.path.expanduser(a.darks_dir or os.path.join(night, 'darks')), found)
    else:
        r = selftest()
        print(json.dumps(r, indent=1))
        if a.out: json.dump(r, open(a.out, 'w'), indent=1)
        if not r['passed']: raise SystemExit('selftest FAILED')
