"""Step 3: register every frame on the stars, with rotation. Coordinates are SENSOR pixels (green plane px * 2 + 0.5).

Reference: the frame with the most stars found in step 2 (clear sky and sharp stars give the most), unless N1514_REF is set.
First guess: the centring frames sit up to about 1000 px from the rest, so the brightest 80 stars of the
frame and of the reference are paired by a vote: for each trial rotation (-2.5 to +2.5 degrees in 0.05 degree steps)
every pair's offset goes into a 4 px histogram over +-1600 px; the rotation and offset with the most votes win.
Then every reference star is paired with the nearest frame star (within 8 px, later 4 px) and a weighted least-squares
rotation + shift (no scale) is fitted with 3.5-sigma rejection; weights 1/(0.25^2 + (k/flux)^2) px^-2 (centroid error
model as in the 3 October scripts, with the floor and k measured on this night's M57 frames, same camera and telescope: bright stars scatter by 0.5 px per axis
from frame to frame, stars of 5000 DN by about 1.7 px; seeing at 5-6 arcsec moves each star on its own).
The rigid fit leaves a smooth pattern of about 1 px (a shear and quadratic terms that change from frame to frame, even
between neighbouring frames), so the transform used for resampling is a 2nd-order polynomial in each coordinate
(1, u, v, u^2, uv, v^2 with u, v = (x - 3012, y - 2012) / 3000), fitted the same way, when 50 or more stars are used;
an affine one (1, u, v) with 20 to 49 stars; the rigid one below 20. Rotation and shift are reported from the rigid fit.
A similarity fit (scale left free) is kept as a check.
Copied from this night's m57/step3_register.py; the only changes are the wider vote window and the hook name."""
import os
import numpy as np
from common import *

res = jload('step2_stars.json'); by = {r['stamp']: r for r in res}
REF = os.environ.get('N1514_REF') or max(res, key=lambda r: len(r['stars']))['stamp']
ref = by[REF]
CENTRE = np.array([W / 2, H / 2])
def nat(s): return np.array([2 * s['x'] + 0.5, 2 * s['y'] + 0.5])
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']]); refsat = np.array([s['saturated'] for s in ref['stars']])
SIG_FLOOR, CEN_K = 0.5, 9000.0
UC = np.array([3012.0, 2012.0]); US = 3000.0
TERMS = 6


def rot(th):
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    return np.array([[c, -s], [s, c]])


def vote(xy, fl):
    A = refxy[np.argsort(-refflux)[:80]]; B = xy[np.argsort(-fl)[:80]]
    best = (-1, 0, None)
    for th in np.arange(-2.5, 2.5001, 0.05):
        Ar = (A - CENTRE) @ rot(th).T + CENTRE
        d = (B[None, :, :] - Ar[:, None, :]).reshape(-1, 2)
        Hh, xe, ye = np.histogram2d(d[:, 0], d[:, 1], bins=800, range=[[-1600, 1600], [-1600, 1600]])
        Hs = Hh.copy(); Hs[1:] += Hh[:-1]; Hs[:-1] += Hh[1:]; Hs2 = Hs.copy(); Hs2[:, 1:] += Hs[:, :-1]; Hs2[:, :-1] += Hs[:, 1:]
        i, j = np.unravel_index(np.argmax(Hs2), Hs2.shape)
        if Hs2[i, j] > best[0]:
            sel = (np.abs(d[:, 0] - (xe[i] + 2)) < 8) & (np.abs(d[:, 1] - (ye[j] + 2)) < 8)
            best = (Hs2[i, j], th, np.median(d[sel], axis=0))
    return best


def poly_terms(A, n):
    u = (A - UC) / US
    T = [np.ones(len(A)), u[:, 0], u[:, 1], u[:, 0] ** 2, u[:, 0] * u[:, 1], u[:, 1] ** 2]
    return np.column_stack(T[:n])


def poly_fit(A, B, w, n):
    keep = np.ones(len(A), bool)
    for _ in range(6):
        X = poly_terms(A, n); sw = np.sqrt(w[keep])
        cx, *_ = np.linalg.lstsq(X[keep] * sw[:, None], B[keep, 0] * sw, rcond=None); cy, *_ = np.linalg.lstsq(X[keep] * sw[:, None], B[keep, 1] * sw, rcond=None)
        r = np.hypot(*(B - np.column_stack([X @ cx, X @ cy])).T); keep = r * np.sqrt(w) < 3.5
    pad = lambda c: np.concatenate([c, np.zeros(TERMS - n)])
    return pad(cx), pad(cy), keep, r


def rigid_as_poly(R, t):
    """x' = R (UC + US u) + t  ->  coefficients on (1, u, v, ...)"""
    c0 = R @ UC + t
    return np.array([c0[0], US * R[0, 0], US * R[0, 1], 0, 0, 0]), np.array([c0[1], US * R[1, 0], US * R[1, 1], 0, 0, 0])


def similarity(A, B, w):
    w = w / w.sum(); ca = (A * w[:, None]).sum(0); cb = (B * w[:, None]).sum(0)
    a = A - ca; b = B - cb
    az = a[:, 0] + 1j * a[:, 1]; bz = b[:, 0] + 1j * b[:, 1]
    z = (w * np.conj(az) * bz).sum() / (w * np.abs(az) ** 2).sum()
    return abs(z), np.degrees(np.angle(z))


out = []
for r in res:
    xy = np.array([nat(s) for s in r['stars']]); fl = np.array([s['flux'] for s in r['stars']])
    votes, th0, sh0 = vote(xy, fl)
    R = rot(th0); t = CENTRE - R @ CENTRE + sh0
    ok = True
    for tol in (8.0, 4.0, 4.0):
        pred = refxy @ R.T + t; pairs = []
        for i, p in enumerate(pred):
            if refsat[i]: continue
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol: pairs.append((i, j))
        if len(pairs) < 8: ok = False; break
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        F = np.minimum(refflux[[i for i, j in pairs]], fl[[j for i, j in pairs]] / max(np.median(fl[[j for i, j in pairs]] / refflux[[i for i, j in pairs]]), 1e-3))
        w = 1.0 / (SIG_FLOOR ** 2 + (CEN_K / F) ** 2); keep = np.ones(len(A), bool)
        for _ in range(5):
            R, t = rigid(A[keep], B[keep], w[keep])
            resid = np.hypot(*(B - (A @ R.T + t)).T)
            keep = resid * np.sqrt(w) < 3.5
        R, t = rigid(A[keep], B[keep], w[keep])
    if not ok:
        out.append(dict(stamp=r['stamp'], failed=True, votes=float(votes), matched=len(pairs)))
        print(r['stamp'], 'FAILED', votes, len(pairs)); continue
    resid = B - (A @ R.T + t)
    nused = int(keep.sum()); nterm = 6 if nused >= 50 else (3 if nused >= 20 else 0)
    if nterm:
        cx, cy, pk, pr = poly_fit(A, B, w, nterm)
        model = 'quadratic' if nterm == 6 else 'affine'
        p_wrms = float(np.sqrt((pr[pk] ** 2 * w[pk]).sum() / w[pk].sum())); p_used = int(pk.sum())
    else:
        cx, cy = rigid_as_poly(R, t); model = 'rigid'; p_wrms = None; p_used = nused
    bright = keep & (refflux[[i for i, j in pairs]] > 3e4)
    rotd = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    out.append(dict(stamp=r['stamp'], failed=False, votes=float(votes), vote_rotation_deg=float(th0), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rotd,
                    shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())),
                    wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                    similarity_scale=float(scale), similarity_rotation_deg=float(rot_s),
                    model=model, cx=cx.tolist(), cy=cy.tolist(), model_used=p_used, model_wrms_px=p_wrms,
                    rigid_bright_rms_px=float(np.sqrt((np.hypot(*resid.T)[bright] ** 2).mean())) if bright.any() else None))
    o = out[-1]
    print('%s votes %3d matched %3d used %3d  shift at centre (%+7.2f, %+7.2f) px  rot %+.4f deg  rigid wrms %.3f px [scale free: %.5f, %+.4f deg] | %s used %d wrms %s' % (
        o['stamp'], votes, o['matched'], o['used'], cshift[0], cshift[1], rotd, o['wrms_px'], scale, rot_s, model, p_used, '%.3f' % p_wrms if p_wrms else '-'), flush=True)
jsave(dict(reference=REF, reference_rule='the frame with the most stars found' if not os.environ.get('N1514_REF') else 'N1514_REF', transforms=out), 'step3_transforms.json')
good = [o for o in out if not o['failed']]
sh = np.array([o['shift_at_centre_px'] for o in good]); rots = np.array([o['rotation_deg'] for o in good])
print('reference', REF, '; shift range x %.1f..%.1f  y %.1f..%.1f ; rotation %.4f..%.4f deg' % (sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), rots.min(), rots.max()))
