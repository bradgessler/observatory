"""Step 3: match each frame's stars to the reference frame and fit rotation + shift (and, as a check, a
similarity with the scale left free). Coordinates here are SENSOR pixels (plane px * 2 + 0.5).
Only stars outside the cluster's crowded core, not saturated and with no detected neighbour within 40 px
are used. The coarse offset comes from a vote over all pairs of the 80 brightest such stars (8 px bins), so no
single star has to be found first; the fit then tightens the match radius from 30 px to 4 px."""
import json, os
import numpy as np
from common import *

res = json.load(open(W('step2_stars.json')))
by = {r['stamp']: r for r in res}
MINFLUX, SIG_FLOOR, CEN_K = 5000.0, 0.25, 7000.0   # centroid error model: sqrt(floor^2 + (k/flux)^2) px
ISOLATION = 40.0
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
def usable(r): return [s for s in r['stars'] if s['r_cluster'] > CORE_RADIUS and not s['saturated'] and s['nearest'] > ISOLATION and s['flux'] >= MINFLUX]
ref = usable(by[REF_STAMP])
refxy = np.array([nat(s) for s in ref]); refflux = np.array([s['flux'] for s in ref])

def rigid(A, B, w):
    """Least-squares R, t with B ~ R A + t (weighted)."""
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    H = ((A - ca) * w[:, None]).T @ (B - cb)
    U, S_, Vt = np.linalg.svd(H); d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1, d]) @ U.T
    return R, cb - R @ ca

def similarity(A, B, w):
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    a = A - ca; b = B - cb
    az = a[:, 0] + 1j * a[:, 1]; bz = b[:, 0] + 1j * b[:, 1]
    z = (w * np.conj(az) * bz).sum() / (w * np.abs(az) ** 2).sum()
    return abs(z), np.degrees(np.angle(z))

def vote(A, B, nmax=80, bin_px=8.0, span=400.0):
    d = (B[:nmax, None, :] - A[None, :nmax, :]).reshape(-1, 2)
    d = d[(np.abs(d) < span).all(1)]
    nb = int(2 * span / bin_px)
    Hh, xe, ye = np.histogram2d(d[:, 0], d[:, 1], bins=nb, range=[[-span, span], [-span, span]])
    Hh = Hh + np.roll(Hh, 1, 0) + np.roll(Hh, 1, 1) + np.roll(np.roll(Hh, 1, 0), 1, 1)   # 2x2 bins, so a peak on a bin edge is not split
    i, j = np.unravel_index(np.argmax(Hh), Hh.shape)
    near = d[(np.abs(d[:, 0] - xe[i]) < bin_px * 1.5) & (np.abs(d[:, 1] - ye[j]) < bin_px * 1.5)]
    return np.median(near, axis=0), int(Hh[i, j])

out = []
CENTRE = np.array([3012.0, 2012.0])
for r in res:
    us = usable(r)
    xy = np.array([nat(s) for s in us]); fl = np.array([s['flux'] for s in us])
    coarse, votes = vote(refxy, xy)
    R = np.eye(2); t = coarse.copy()
    for tol in (30.0, 12.0, 4.0, 4.0):
        pred = refxy @ R.T + t
        pairs = []
        for i, p in enumerate(pred):
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol and 0.5 < fl[j] / refflux[i] < 2.0: pairs.append((i, j))
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        F = refflux[[i for i, j in pairs]]
        w = 1.0 / (SIG_FLOOR ** 2 + (CEN_K / F) ** 2); keep = np.ones(len(A), bool)
        for _ in range(5):
            R, t = rigid(A[keep], B[keep], w[keep])
            resid = np.hypot(*(B - (A @ R.T + t)).T)
            keep = resid * np.sqrt(w) < 3.5
        R, t = rigid(A[keep], B[keep], w[keep])
    resid = B - (A @ R.T + t)
    rot = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    cl = np.array(json.load(open(W('step1.json')))['frames'][0]['cluster_sensor_xy']) if False else None
    out.append(dict(stamp=r['stamp'], usable_stars=len(us), coarse_votes=votes, coarse_shift_px=coarse.tolist(), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                    shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                    bright_resid_px=[float(np.hypot(*resid[k])) for k in np.argsort(-F)[:4]],
                    similarity_scale=float(scale), similarity_rotation_deg=float(rot_s),
                    used_ref_xy=[[float(a), float(b)] for a, b in A[keep]],
                    resid=[[float(a), float(b)] for a, b in resid[keep]]))
    o = out[-1]
    print('%s usable %3d votes %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px bright %s [similarity: scale %.5f rot %+.4f]' % (o['stamp'], len(us), votes, o['matched'], o['used'], cshift[0], cshift[1], rot, o['rms_px'], o['wrms_px'], np.round(o['bright_resid_px'], 2).tolist(), scale, rot_s))
json.dump(out, open(W('step3_transforms.json'), 'w'), indent=1)
sh = np.array([o['shift_at_centre_px'] for o in out]); rots = np.array([o['rotation_deg'] for o in out])
print('shift range x %.1f..%.1f  y %.1f..%.1f ; path length %.1f px ; rot range %.4f..%.4f deg' % (sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), np.hypot(*np.diff(sh, axis=0).T).sum(), rots.min(), rots.max()))
print('frame-to-frame steps (px):', np.round(np.hypot(*np.diff(sh, axis=0).T), 1).tolist())
