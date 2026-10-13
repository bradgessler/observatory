"""Step 3: register every frame on the stars, with rotation. Coordinates are SENSOR pixels (plane px * 2 + 0.5).

The polar axis was 5 degrees off the pole, so the field turns. One run, the hold keeping the nebula near the
sensor centre. Reference: N2392_REF, or by rule the frame with the
most stars among those taken 20 s or more after a slew.
First guess by a vote: the brightest 60 sources of the frame and of the reference; for each trial rotation (-1.5 to
+1.5 degrees in 0.05 degree steps, about the sensor centre) every pair's offset goes into a 4 px histogram (+-1600 px);
the rotation and offset with the most votes win. Then every reference source is paired with the nearest frame source
(within 8 px, then 4 px) and a weighted least-squares ROTATION + SHIFT (no scale, no shear) is fitted with 3.5-sigma
rejection; weights 1 / (0.5^2 + (3000 / flux)^2) px^-2 (seeing moves each star by about half a pixel on its own; faint
stars' centroids are noisier). A 4 s frame shows about 60 sources, too few to hold a 2nd-order fit steady, the run is
16 minutes and the nebula is 45 px from the sensor centre, where a rigid fit is exact: so rigid it is (last week's
long runs used a 2nd-order fit). A fit with the scale left free is kept as a check. The nebula itself is one of the
sources (its windowed centroid settles on the central star)."""
import os
import numpy as np
from common import *

res = json.load(open(W('step2_stars.json'))); by = {r['stamp']: r for r in res}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
REF = os.environ.get('N2392_REF') or max((r for r in res if (s1[r['stamp']]['since_slew_s'] or 0) >= 20), key=lambda r: len(r['stars']))['stamp']
ref = by[REF]
refxy = np.array([nat(s) for s in ref['stars']]); refflux = np.array([s['flux'] for s in ref['stars']])
SIG_FLOOR, CEN_K = 0.5, 3000.0


def rot(th):
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    return np.array([[c, -s], [s, c]])


def vote(xy, fl):
    A = refxy[np.argsort(-refflux)[:60]]; B = xy[np.argsort(-fl)[:60]]
    best = (-1, 0, None)
    for th in np.arange(-1.5, 1.5001, 0.05):
        Ar = (A - CENTRE) @ rot(th).T + CENTRE
        d = (B[None, :, :] - Ar[:, None, :]).reshape(-1, 2)
        Hh, xe, ye = np.histogram2d(d[:, 0], d[:, 1], bins=800, range=[[-1600, 1600], [-1600, 1600]])
        Hs = Hh.copy(); Hs[1:] += Hh[:-1]; Hs[:-1] += Hh[1:]; Hs2 = Hs.copy(); Hs2[:, 1:] += Hs[:, :-1]; Hs2[:, :-1] += Hs[:, 1:]
        i, j = np.unravel_index(np.argmax(Hs2), Hs2.shape)
        if Hs2[i, j] > best[0]:
            sel = (np.abs(d[:, 0] - (xe[i] + 2)) < 8) & (np.abs(d[:, 1] - (ye[j] + 2)) < 8)
            best = (Hs2[i, j], th, np.median(d[sel], axis=0))
    return best


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
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol: pairs.append((i, j))
        if len(pairs) < 8: ok = False; break
        ii = [i for i, j in pairs]; jj = [j for i, j in pairs]
        A = refxy[ii]; B = xy[jj]
        F = np.minimum(refflux[ii], fl[jj])
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
    rotd = float(np.degrees(np.arctan2(R[1, 0], R[0, 0])))
    scale, rot_s = similarity(A[keep], B[keep], w[keep])
    cshift = (CENTRE @ R.T + t) - CENTRE
    out.append(dict(stamp=r['stamp'], failed=False, votes=float(votes), vote_rotation_deg=float(th0), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rotd,
                    shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())),
                    wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                    similarity_scale=float(scale), similarity_rotation_deg=float(rot_s), model='rigid'))
    o = out[-1]
    print('%s votes %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  wrms %.3f px (rms %.3f) [scale free: %.5f, %+.4f deg]' % (
        o['stamp'], votes, o['matched'], o['used'], cshift[0], cshift[1], rotd, o['wrms_px'], o['rms_px'], scale, rot_s), flush=True)
jdump(dict(reference=REF, reference_rule='N2392_REF' if os.environ.get('N2392_REF') else 'the frame with the most stars found among those taken 20 s or more after a slew', transforms=out), 'step3_transforms.json')
good = [o for o in out if not o['failed']]
sh = np.array([o['shift_at_centre_px'] for o in good]); rots = np.array([o['rotation_deg'] for o in good])
print('reference', REF, '; shift range x %.1f..%.1f  y %.1f..%.1f px; rotation %.4f..%.4f deg' % (sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), rots.min(), rots.max()))
