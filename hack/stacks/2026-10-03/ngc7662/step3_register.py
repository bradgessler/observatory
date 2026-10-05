"""Step 3: match each frame's stars to the reference frame, fit a rigid transform (rotation + shift)
and, as a check, a similarity (with scale). Coordinates here are SENSOR pixels (plane px * 2 + 0.5)."""
import json, os
import numpy as np
from common import *

res = json.load(open(os.path.join(SCR, 'step2_stars.json')))
by = {r['stamp']: r for r in res}
ref = by[REF_STAMP]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])

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
    # complex least squares b = z a
    az = a[:, 0] + 1j * a[:, 1]; bz = b[:, 0] + 1j * b[:, 1]
    z = (w * np.conj(az) * bz).sum() / (w * np.abs(az) ** 2).sum()
    return abs(z), np.degrees(np.angle(z))

MINFLUX, SIG_FLOOR, CEN_K = 5000.0, 0.25, 7000.0   # centroid error model: sqrt(floor^2 + (k/flux)^2) px
out = []
CENTRE = np.array([3012.0, 2012.0])
for r in res:
    xy = np.array([nat(s) for s in r['stars']]); fl = np.array([s['flux'] for s in r['stars']])
    coarse = xy[0] - refxy[0]           # brightest unsaturated-ish blob = the bright star in every frame
    pairs = []
    for i, p in enumerate(refxy):
        d = np.hypot(*(xy - coarse - p).T); j = int(np.argmin(d))
        if refflux[i] >= MINFLUX and d[j] < 12 and 0.5 < fl[j] / refflux[i] < 2.0: pairs.append((i, j))
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
    # where the reference frame's centre, nebula and star land in this frame
    cshift = (CENTRE @ R.T + t) - CENTRE
    out.append(dict(stamp=r['stamp'], matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                    shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())), bright_resid_px=[float(np.hypot(*resid[k])) for k in range(min(4, len(resid)))],
                    similarity_scale=float(scale), similarity_rotation_deg=float(rot_s),
                    used_ref_index=[int(pairs[k][0]) for k in range(len(pairs)) if keep[k]],
                    resid=[[float(a), float(b)] for a, b in resid[keep]]))
    o = out[-1]
    print('%s matched %3d used %3d  shift at centre (%+7.2f, %+7.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px bright %s [similarity: scale %.5f rot %+.4f]' % (o['stamp'], o['matched'], o['used'], cshift[0], cshift[1], rot, o['rms_px'], o['wrms_px'], np.round(o['bright_resid_px'], 2).tolist(), scale, rot_s))
json.dump(out, open(os.path.join(SCR, 'step3_transforms.json'), 'w'), indent=1)
sh = np.array([o['shift_at_centre_px'] for o in out]); rots = np.array([o['rotation_deg'] for o in out])
print('shift range x %.1f..%.1f  y %.1f..%.1f ; path length %.1f px ; rot range %.4f..%.4f deg' % (sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), np.hypot(*np.diff(sh, axis=0).T).sum(), rots.min(), rots.max()))
print('frame-to-frame steps (px):', np.round(np.hypot(*np.diff(sh, axis=0).T), 1).tolist())
