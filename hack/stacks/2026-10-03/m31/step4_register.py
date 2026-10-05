"""Step 4: match each frame's stars to the reference frame and fit rotation + shift (a similarity transform
with the scale held at 1; the scale left free is reported as a check). Coordinates are SENSOR pixels
(plane px * 2 + 0.5). Only stars more than CORE_RADIUS from the nucleus, not saturated, with no detected
neighbour within 40 px and brighter than MINFLUX. The field turns 5 degrees over the run, so a plain offset
vote would fail far from the reference: instead the frames are walked outward in time from the reference and
each starts from its neighbour's solution (the field moves a few px between neighbours); the match radius is
tightened 30, 12, 4 px."""
import json, os
import numpy as np
from common import *

res = json.load(open(W('step3_stars.json')))
by = {r['stamp']: r for r in res}
stamps = [r['stamp'] for r in res]
MINFLUX, SIG_FLOOR, CEN_K = 8000.0, 0.25, 14000.0   # centroid error model: sqrt(floor^2 + (k/flux)^2) px
ISOLATION = 40.0
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
def usable(r, minflux=MINFLUX): return [s for s in r['stars'] if s['r_nucleus'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > ISOLATION and s['flux'] >= minflux]
ref = usable(by[REF_STAMP])
refxy = np.array([nat(s) for s in ref]); refflux = np.array([s['flux'] for s in ref])
print('reference', REF_STAMP, 'usable stars', len(ref))

def rigid(A, B, w):
    """Least-squares R, t with B ~ R A + t (weighted)."""
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

def solve(stamp, R0, t0):
    r = by[stamp]
    us = usable(r, 0.0)                     # clouded frames have dim stars: the flux floor is applied on the reference side only
    if len(us) < 5: return None
    xy = np.array([nat(s) for s in us]); fl = np.array([s['flux'] for s in us])
    R, t = R0.copy(), t0.copy()
    for tol in (30.0, 12.0, 4.0, 4.0):
        pred = refxy @ R.T + t
        pairs = []
        for i, p in enumerate(pred):
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol and 0.02 < fl[j] / refflux[i] < 3.0: pairs.append((i, j))
        if len(pairs) < 5: return None
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        F = np.minimum(refflux[[i for i, j in pairs]], fl[[j for i, j in pairs]])
        w = 1.0 / (SIG_FLOOR ** 2 + (CEN_K / F) ** 2); keep = np.ones(len(A), bool)
        for _ in range(5):
            if keep.sum() < 4: return None
            R, t = rigid(A[keep], B[keep], w[keep])
            resid = np.hypot(*(B - (A @ R.T + t)).T)
            keep = resid * np.sqrt(w) < 3.5
        if keep.sum() < 4: return None
        R, t = rigid(A[keep], B[keep], w[keep])
    resid = B - (A @ R.T + t)
    rot = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    # the point of the reference grid that does not move between the reference and this frame (centre of the turn)
    try: fixed = np.linalg.solve(np.eye(2) - R, t).tolist()
    except np.linalg.LinAlgError: fixed = None
    return dict(stamp=stamp, usable_stars=len(us), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                similarity_scale=float(scale), similarity_rotation_deg=float(rot_s), fixed_point_ref_xy=fixed,
                pairs=[[int(i), int(j)] for (i, j), k in zip(pairs, keep) if k])

i0 = stamps.index(REF_STAMP)
sol = {}
for direction in (1, -1):
    R, t = np.eye(2), np.zeros(2)
    k = i0
    while 0 <= k < len(stamps):
        o = solve(stamps[k], R, t)
        if o is None:
            sol.setdefault(stamps[k], dict(stamp=stamps[k], failed=True, usable_stars=len(usable(by[stamps[k]], 0.0))))
        else:
            sol[stamps[k]] = o; R, t = np.array(o['R']), np.array(o['t'])
        k += direction
out = [sol[s] for s in stamps]
for o in out:
    if o.get('failed'): print(o['stamp'], 'NOT REGISTERED: usable stars', o['usable_stars']); continue
    print('%s usable %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px [scale %.5f] fixed point %s' % (o['stamp'], o['usable_stars'], o['matched'], o['used'], *o['shift_at_centre_px'], o['rotation_deg'], o['rms_px'], o['wrms_px'], o['similarity_scale'], np.round(o['fixed_point_ref_xy']).astype(int).tolist() if o['fixed_point_ref_xy'] and abs(o['rotation_deg']) > 0.05 else '-'))
json.dump(dict(reference=REF_STAMP, reference_stars_xy=refxy.tolist(), reference_stars_flux=refflux.tolist(), minflux=MINFLUX, transforms=out), open(W('step4_transforms.json'), 'w'), indent=1)
good = [o for o in out if not o.get('failed')]
sh = np.array([o['shift_at_centre_px'] for o in good]); rots = np.array([o['rotation_deg'] for o in good])
print('registered %d of %d; shift range x %.1f..%.1f  y %.1f..%.1f ; rot range %.4f..%.4f deg' % (len(good), len(out), sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), rots.min(), rots.max()))
