"""Step 4: match each frame's stars to the reference frame's and fit a rigid transform (rotation + shift; scale left
free only as a check). The frames jump by up to 270 sensor px (the box re-centred twice during the run) and turn by
about a degree, so the first match is a vote: for every trial rotation (-2 to +2 degrees, 0.05 degree steps) every
pair of the brightest 150 stars votes for a shift, and the best (rotation, shift) seeds a nearest-neighbour match.
Coordinates here are SENSOR pixels (plane px * 2 + 0.5). Adapted from ../../2026-10-03/ngc7662/step3_register.py."""
import json, os
import numpy as np
from common import *

res = json.load(open(W('step3_stars.json')))
by = {r['stamp']: r for r in res}
ref = by[REF_STAMP]
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])
CENTRE = np.array([Wd / 2, H / 2])


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


def vote(A, B, nb=150, bin_px=6.0, span=1200.0):
    """Best rotation (about the sensor centre) and shift taking the A stars onto the B stars, by counting pairs."""
    A = A[:nb]; B = B[:nb]; best = (-1, 0.0, None)
    edges = np.arange(-span, span + bin_px, bin_px)
    for ang in np.arange(-2.0, 2.0001, 0.05):
        c, s = np.cos(np.radians(ang)), np.sin(np.radians(ang)); R = np.array([[c, -s], [s, c]])
        Ar = (A - CENTRE) @ R.T + CENTRE
        d = (B[None, :, :] - Ar[:, None, :]).reshape(-1, 2)
        hist, _, _ = np.histogram2d(d[:, 0], d[:, 1], bins=[edges, edges])
        k = np.unravel_index(np.argmax(hist), hist.shape)
        if hist[k] > best[0]:
            best = (int(hist[k]), float(ang), np.array([edges[k[0]] + bin_px / 2, edges[k[1]] + bin_px / 2]), R)
    n, ang, shift, R = best
    return n, ang, R, CENTRE - R @ CENTRE + shift


MINFLUX, SIG_FLOOR, CEN_K = 10000.0, 0.25, 7000.0   # centroid error model: sqrt(floor^2 + (k/flux)^2) sensor px
out = []
for r in res:
    xy = np.array([nat(s) for s in r['stars']]); fl = np.array([s['flux'] for s in r['stars']])
    nvote, ang0, R0, t0 = vote(refxy, xy)
    pairs = []
    pred = refxy @ R0.T + t0
    for i, p in enumerate(pred):
        d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
        if refflux[i] >= MINFLUX and d[j] < 16 and 0.4 < fl[j] / refflux[i] < 2.5: pairs.append((i, j))
    A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
    F = refflux[[i for i, j in pairs]]
    w = 1.0 / (SIG_FLOOR ** 2 + (CEN_K / F) ** 2); keep = np.ones(len(A), bool)
    for _ in range(6):
        R, t = rigid(A[keep], B[keep], w[keep])
        resid = np.hypot(*(B - (A @ R.T + t)).T)
        keep = resid * np.sqrt(w) < 3.5
    R, t = rigid(A[keep], B[keep], w[keep])
    resid = B - (A @ R.T + t)
    rot = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    out.append(dict(stamp=r['stamp'], vote=dict(pairs=nvote, rotation_deg=ang0), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                    shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                    similarity_scale=float(scale), similarity_rotation_deg=float(rot_s),
                    used_ref_index=[int(pairs[k][0]) for k in range(len(pairs)) if keep[k]]))
    o = out[-1]
    print('%s vote %3d @ %+.2f deg | matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px [similarity: scale %.5f rot %+.4f]' % (
        o['stamp'], nvote, ang0, o['matched'], o['used'], cshift[0], cshift[1], rot, o['rms_px'], o['wrms_px'], scale, rot_s))
json.dump(out, open(W('step4_transforms.json'), 'w'), indent=1)
sh = np.array([o['shift_at_centre_px'] for o in out]); rots = np.array([o['rotation_deg'] for o in out])
print('reference', REF_STAMP)
print('shift range x %.1f..%.1f  y %.1f..%.1f ; path length %.1f px ; rot range %.4f..%.4f deg' % (sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), np.hypot(*np.diff(sh, axis=0).T).sum(), rots.min(), rots.max()))
print('frame-to-frame steps (px):', np.round(np.hypot(*np.diff(sh, axis=0).T), 1).tolist())
