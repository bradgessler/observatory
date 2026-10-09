"""Step 4: inside each panel, match every frame's stars to the panel's reference frame and fit rotation + shift
(rigid; the scale left free is reported as a check). Method of the night's M31 pipeline (step4_register.py).
The reference of a panel is its frame with the most usable stars (its clearest). Coordinates are SENSOR pixels
(plane px * 2 + 0.5). Frames are walked outward in time from the reference, each starting from its neighbour's
solution; match radius 40, 12, 4 px. Usable: not saturated, no detected neighbour within 40 px."""
import json
import numpy as np
from c import *

F = json.load(open(W('p1.json')))['frames']
res = json.load(open(W('p3_stars.json'))); by = {r['stamp']: r for r in res}
MINFLUX, SIG_FLOOR, CEN_K = 3000.0, 0.25, 4000.0
ISOLATION = 40.0
def usable(r, minflux=MINFLUX): return [s for s in r['stars'] if not s['saturated'] and s['nearest'] > ISOLATION and s['flux'] >= minflux]


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


def solve(stamp, refxy, refflux, R0, t0):
    r = by[stamp]
    us = usable(r, 0.0)
    if len(us) < 6: return None
    xy = np.array([nat(s) for s in us]); fl = np.array([s['flux'] for s in us])
    R, t = R0.copy(), t0.copy()
    for tol in (40.0, 12.0, 4.0, 4.0):
        pred = refxy @ R.T + t
        pairs = []
        for i, p in enumerate(pred):
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol and 0.02 < fl[j] / refflux[i] < 3.0: pairs.append((i, j))
        if len(pairs) < 6: return None
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        Fm = np.minimum(refflux[[i for i, j in pairs]], fl[[j for i, j in pairs]])
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
    return dict(stamp=stamp, usable_stars=len(us), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                similarity_scale=float(scale), pairs=[[int(i), int(j)] for (i, j), k in zip(pairs, keep) if k])


out = {}
for name in PANELS:
    stamps = [f['stamp'] for f in F if f['panel'] == name]
    ref_stamp = max(stamps, key=lambda s: len(usable(by[s])))
    ref = usable(by[ref_stamp]); refxy = np.array([nat(s) for s in ref]); refflux = np.array([s['flux'] for s in ref])
    print('panel', name, 'reference', ref_stamp, 'usable stars', len(ref))
    i0 = stamps.index(ref_stamp); sol = {}
    for direction in (1, -1):
        R, t = np.eye(2), np.zeros(2); k = i0
        while 0 <= k < len(stamps):
            o = solve(stamps[k], refxy, refflux, R, t)
            if o is None:
                sol.setdefault(stamps[k], dict(stamp=stamps[k], failed=True, usable_stars=len(usable(by[stamps[k]], 0.0))))
            else:
                sol[stamps[k]] = o; R, t = np.array(o['R']), np.array(o['t'])
            k += direction
    tr = [sol[s] for s in stamps]
    for o in tr:
        if o.get('failed'): print('  ', o['stamp'], 'NOT REGISTERED: usable stars', o['usable_stars']); continue
        print('   %s usable %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px [scale %.5f]' % (o['stamp'], o['usable_stars'], o['matched'], o['used'], *o['shift_at_centre_px'], o['rotation_deg'], o['rms_px'], o['wrms_px'], o['similarity_scale']))
    out[name] = dict(reference=ref_stamp, reference_stars_xy=refxy.tolist(), reference_stars_flux=refflux.tolist(), transforms=tr)
json.dump(out, open(W('p4_transforms.json'), 'w'), indent=1)
