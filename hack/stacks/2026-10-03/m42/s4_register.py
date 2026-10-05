"""Step 4: inside each set, match every frame's stars to the set's reference frame and fit rotation + shift
(similarity with the scale held at 1; the scale left free is reported as a check). The method of the M31 runs
(m4_register.py), with one addition: the sets here hold groups that were re-centred in between (shifts of 100
px and more), so each frame's first guess is found from the stars themselves: the most common offset between its
bright stars and the reference's (a histogram of all pairwise offsets, 16 px bins), then match radius 40, 12, 4 px.
The reference of a set is its frame with the most usable stars. The SHORT frames (2 s) are registered to the DEEP
set's reference frame, so that both stacks are made on one grid.
Coordinates are SENSOR pixels (plane px * 2 + 0.5)."""
import json
import numpy as np
from common import *

s1l = json.load(open(W('s1.json')))['frames']; s1 = {f['stamp']: f for f in s1l}
res = json.load(open(W('s3_stars.json'))); by = {r['stamp']: r for r in res}
MINFLUX, SIG_FLOOR, CEN_K = 8000.0, 0.25, 14000.0
ISOLATION = 40.0
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
def usable(r, minflux=MINFLUX, sat_ok=False): return [s for s in r['stars'] if s['r_core'] > CORE_RADIUS and (sat_ok or not s['saturated']) and s['nearest'] > ISOLATION and s['flux'] >= minflux]


def rigid(A, B, w):
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    Hm = ((A - ca) * w[:, None]).T @ (B - cb)
    U, S_, Vt = np.linalg.svd(Hm); d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, d]) @ U.T
    return R, cb - R @ ca


def similarity(A, B, w):
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    a = A - ca; b = B - cb
    az = a[:, 0] + 1j * a[:, 1]; bz = b[:, 0] + 1j * b[:, 1]
    z = (w * np.conj(az) * bz).sum() / (w * np.abs(az) ** 2).sum()
    return abs(z), np.degrees(np.angle(z))


def first_guess(refxy, xy, span=2600, bin_=16):
    """The most common offset xy - refxy among all pairs of the brightest stars."""
    a = refxy[:120]; b = xy[:120]
    d = (b[None, :, :] - a[:, None, :]).reshape(-1, 2)
    n = int(2 * span / bin_)
    Hh, xe, ye = np.histogram2d(d[:, 0], d[:, 1], bins=n, range=[[-span, span], [-span, span]])
    import cv2
    Hs = cv2.GaussianBlur(Hh.astype(np.float32), (0, 0), 1.0)
    i, j = np.unravel_index(np.argmax(Hs), Hs.shape)
    t = np.array([(xe[i] + xe[i + 1]) / 2, (ye[j] + ye[j + 1]) / 2])
    near = d[np.hypot(*(d - t).T) < 2 * bin_]
    return (np.median(near, axis=0) if len(near) >= 3 else t), float(Hs[i, j])


def solve(stamp, refxy, refflux, fmin, fmax, sat_ok=False):
    r = by[stamp]
    us = usable(r, 0.0, sat_ok)
    if len(us) < 6: return None
    xy = np.array([nat(s) for s in us]); fl = np.array([s['flux'] for s in us])
    t0, votes = first_guess(refxy, xy[np.argsort(-fl)])
    R, t = np.eye(2), t0.copy()
    for tol in (40.0, 12.0, 4.0, 4.0):
        pred = refxy @ R.T + t
        pairs = []
        for i, p in enumerate(pred):
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol and fmin < fl[j] / refflux[i] < fmax: pairs.append((i, j))
        if len(pairs) < 6: return None
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        Fm = np.minimum(refflux[[i for i, j in pairs]], fl[[j for i, j in pairs]] / max(fmin, 1e-9) * 0.02) if fmin < 0.02 else np.minimum(refflux[[i for i, j in pairs]], fl[[j for i, j in pairs]])
        w = 1.0 / (SIG_FLOOR ** 2 + (CEN_K / Fm) ** 2); keep = np.ones(len(A), bool)
        for _ in range(5):
            if keep.sum() < 5: return None
            R, t = rigid(A[keep], B[keep], w[keep])
            resid = np.hypot(*(B - (A @ R.T + t)).T)
            keep = resid * np.sqrt(w) < 3.5
        if keep.sum() < 5: return None
        R, t = rigid(A[keep], B[keep], w[keep])
    resid = B - (A @ R.T + t)
    rot = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    return dict(stamp=stamp, usable_stars=len(us), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot, first_guess_px=t0.tolist(),
                shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                similarity_scale=float(scale), pairs=[[int(i), int(j)] for (i, j), k in zip(pairs, keep) if k])


out = {}
sets = sorted(set(f['set'] for f in s1l), key=lambda s: (s != 'deep', s))
for name in sets:
    stamps = [f['stamp'] for f in s1l if f['set'] == name]
    if name == 'short':
        ref_stamp = out['deep']['reference']
        # the reference's stars for the short frames: its bright ones, saturated or not (a flat-topped star still has a centre)
        ref = usable(by[ref_stamp], 20000.0, sat_ok=True); fmin, fmax, sat_ok = 0.004, 0.2, True
    else:
        ref_stamp = max([s for s in stamps if s1[s]['sky_green'] < 1.3 * min(s1[x]['sky_green'] for x in stamps)], key=lambda s: len(usable(by[s])))
        ref = usable(by[ref_stamp]); fmin, fmax, sat_ok = 0.02, 3.0, False
    refxy = np.array([nat(s) for s in ref]); refflux = np.array([s['flux'] for s in ref])
    o_ = np.argsort(-refflux); refxy, refflux = refxy[o_], refflux[o_]
    print('set', name, 'reference', ref_stamp, 'usable stars', len(ref))
    tr = []
    for s in stamps:
        o = solve(s, refxy, refflux, fmin, fmax, sat_ok)
        if o is None: o = dict(stamp=s, failed=True, usable_stars=len(usable(by[s], 0.0)))
        tr.append(o)
        if o.get('failed'): print('  ', o['stamp'], 'NOT REGISTERED: usable stars', o['usable_stars']); continue
        print('   %s usable %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px [scale %.5f]' % (o['stamp'], o['usable_stars'], o['matched'], o['used'], *o['shift_at_centre_px'], o['rotation_deg'], o['rms_px'], o['wrms_px'], o['similarity_scale']))
    out[name] = dict(reference=ref_stamp, reference_stars_xy=refxy.tolist(), reference_stars_flux=refflux.tolist(), transforms=tr)
json.dump(out, open(W('s4_transforms.json'), 'w'), indent=1)
