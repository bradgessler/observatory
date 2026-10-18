"""Step 3: match each frame's stars to the reference frame and fit rotation + shift (a similarity transform with the
scale held at 1; the scale left free is reported as a check). Coordinates are SENSOR pixels (plane px * 2 + 0.5).
Only sources that are not saturated, have no detected neighbour within 40 px and are brighter than MINFLUX.

The first guess for every frame comes from its own plate solve (the sidecar .solve.json, made by the box from the JPEG):
its centre put on the reference frame's grid through the reference's astrometry.net solution (step 6), and its
rotation against the reference's (both from the box's solver; SIGN is found on the frames that turned most). The
frames are dithered up to 1.5 arcmin apart (plus the drift) and the field turned 5.6 degrees over the run, so a chain from neighbour to
neighbour would not do. A frame with no plate solve starts from its time-neighbour's solution. If the guess fails, a
coarse vote (every pair of bright stars votes for a shift, 400 px either way) moves it. The match radius is tightened
30, 12, 4 px. As hack/stacks/2026-10-17/m27/step3_register.py otherwise.

M42: the long (30 s ISO 1600) and the short (2 s ISO 400) frames are registered onto the same long reference frame, on
the stars that are unsaturated in the reference; a star's flux in a frame is compared with the reference's times the
frame's exposure x ISO over the reference's (1/60 for a short frame), so the flux test (0.2 to 5 x) means the same for
both kinds."""
import json, os
import numpy as np
from common import *
import solvelib

res = json.load(open(W('step2_stars.json')))
by = {r['stamp']: r for r in res}
stamps = [r['stamp'] for r in res]
MINFLUX, SIG_FLOOR, CEN_K = 8000.0, 0.25, 14000.0   # centroid error model: sqrt(floor^2 + (k/flux)^2) px
ISOLATION = 40.0


def usable(r, minflux=MINFLUX):
    return [s for s in r['stars'] if not s['saturated'] and s['nearest'] > ISOLATION and s['flux'] >= minflux]


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


def vote(xy, pred, nb=40, binpx=6.0, span=400.0):
    """Coarse extra shift: every pair of the brightest nb reference stars (where the current guess puts them) and the
    brightest nb frame stars votes for their difference; the densest 3 x 3 bins win; their mean is the shift."""
    d = (xy[:nb, None, :] - pred[None, :nb, :]).reshape(-1, 2)
    d = d[(np.abs(d) < span).all(1)]
    n = int(2 * span / binpx)
    Hh, ex, ey = np.histogram2d(d[:, 0], d[:, 1], bins=n, range=[[-span, span], [-span, span]])
    Hs = sum(np.roll(np.roll(Hh, a, 0), b, 1) for a in (-1, 0, 1) for b in (-1, 0, 1))
    i, j = np.unravel_index(np.argmax(Hs), Hs.shape)
    c = np.array([(ex[i] + ex[i + 1]) / 2, (ey[j] + ey[j + 1]) / 2])
    near = d[np.hypot(*(d - c).T) < 2 * binpx]
    return near.mean(0), int(Hs[i, j])


def solve(stamp, R0, t0, coarse=False):
    r = by[stamp]
    us = usable(r, 0.0)
    if len(us) < 5: return None
    xy = np.array([nat(s) for s in us]); fl = np.array([s['flux'] for s in us])
    R, t = R0.copy(), t0.copy()
    if coarse:
        o = np.argsort(-fl); dv, votes = vote(xy[o], refxy @ R.T + t)
        t = t + dv
        print('  %s: chained guess failed; coarse vote moves it by (%+.1f, %+.1f) px (%d votes)' % (stamp, dv[0], dv[1], votes))
    for tol in (30.0, 12.0, 4.0, 4.0):
        pred = refxy @ R.T + t
        pairs = []
        for i, p in enumerate(pred):
            d = np.hypot(*(xy - p).T); j = int(np.argmin(d))
            if d[j] < tol and 0.2 < fl[j] / (refflux[i] * FS[stamp]) < 5.0: pairs.append((i, j))
        if len(pairs) < 5: return None
        A = refxy[[i for i, j in pairs]]; B = xy[[j for i, j in pairs]]
        F = np.minimum(refflux[[i for i, j in pairs]] * FS[stamp], fl[[j for i, j in pairs]])
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
    try: fixed = np.linalg.solve(np.eye(2) - R, t).tolist()
    except np.linalg.LinAlgError: fixed = None
    return dict(stamp=stamp, usable_stars=len(us), matched=len(pairs), used=int(keep.sum()), R=R.tolist(), t=t.tolist(), rotation_deg=rot,
                shift_at_centre_px=cshift.tolist(), rms_px=float(np.sqrt((resid[keep] ** 2).sum(1).mean())), wrms_px=float(np.sqrt(((resid[keep] ** 2).sum(1) * w[keep]).sum() / w[keep].sum())),
                similarity_scale=float(scale), similarity_rotation_deg=float(rot_s), fixed_point_ref_xy=fixed,
                pairs=[[int(i), int(j)] for (i, j), k in zip(pairs, keep) if k])


def guess(stamp, sign):
    """R, t from the frame's own plate solve, or None."""
    f = S1[stamp]; r0 = S1[REF_STAMP]
    if not f.get('had_plate_solve') or f.get('solve_rotation_deg') is None: return None
    x, y = solvelib.rd2xy('ref', *f['solve_centre_ra_dec'])           # the frame's centre on the reference's plane grid
    c_ref = np.array([2 * x + 0.5, 2 * y + 0.5])
    th = np.radians(sign * (f['solve_rotation_deg'] - r0['solve_rotation_deg']))
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    return R, CENTRE - R @ c_ref


S1 = {f['stamp']: f for f in jload('step1.json')['frames']}
FS = {k: v['exposure_s'] * v['iso'] / (S1[REF_STAMP]['exposure_s'] * S1[REF_STAMP]['iso']) for k, v in S1.items()}   # flux scale against the reference

if __name__ == '__main__':
    # the sign of the box's rotation against the sensor's: try both on the frames that turned most from the reference
    rots = sorted(stamps, key=lambda s_: -abs((S1[s_].get('solve_rotation_deg') or S1[REF_STAMP]['solve_rotation_deg']) - S1[REF_STAMP]['solve_rotation_deg']))[:6]
    score = {}
    for sg in (1, -1):
        score[sg] = sum((solve(s_, *guess(s_, sg)) or {}).get('used', 0) for s_ in rots if guess(s_, sg) is not None)
    SIGN = 1 if score[1] >= score[-1] else -1
    print('rotation sign from the 6 frames that turned most (%s): stars used with +1 %d, with -1 %d -> %+d' % (', '.join(rots), score[1], score[-1], SIGN), flush=True)
    sol = {}
    prev = (np.eye(2), np.zeros(2))
    i0 = stamps.index(REF_STAMP)
    order = [i0] + list(range(i0 + 1, len(stamps))) + list(range(i0 - 1, -1, -1))
    last = {}
    for k in order:
        st = stamps[k]
        g = guess(st, SIGN); how = 'plate solve'
        if g is None:
            nb = min(last, key=lambda s_: abs(stamps.index(s_) - k)) if last else REF_STAMP
            g = last.get(nb, (np.eye(2), np.zeros(2))); how = 'neighbour %s' % nb
        o = solve(st, *g)
        if o is None:
            o = solve(st, *g, coarse=True)
            if o is not None: o['coarse_vote'] = True
        if o is None:
            sol[st] = dict(stamp=st, failed=True, usable_stars=len(usable(by[st], 0.0)), first_guess=how)
        else:
            o['first_guess'] = how
            if how == 'plate solve':
                o['guess_error_at_centre_px'] = float(np.hypot(*((CENTRE @ np.array(o['R']).T + np.array(o['t'])) - (CENTRE @ g[0].T + g[1]))))
            sol[st] = o; last[st] = (np.array(o['R']), np.array(o['t']))
    out = [sol[s] for s in stamps]
    for o in out:
        if o.get('failed'): print(o['stamp'], 'NOT REGISTERED: usable stars', o['usable_stars']); continue
        print('%s %-5s usable %3d matched %3d used %3d  shift at centre (%+8.2f, %+8.2f) px  rot %+.4f deg  rms %.3f wrms %.3f px [scale %.5f] guess off %s' % (o['stamp'], S1[o['stamp']]['turn'], o['usable_stars'], o['matched'], o['used'], *o['shift_at_centre_px'], o['rotation_deg'], o['rms_px'], o['wrms_px'], o['similarity_scale'], '%.1f px' % o['guess_error_at_centre_px'] if 'guess_error_at_centre_px' in o else o['first_guess']))
    json.dump(dict(reference=REF_STAMP, rotation_sign=SIGN, rotation_sign_score=score, reference_stars_xy=refxy.tolist(), reference_stars_flux=refflux.tolist(), minflux=MINFLUX, transforms=out), open(W('step3_transforms.json'), 'w'), indent=1)
    good = [o for o in out if not o.get('failed')]
    sh = np.array([o['shift_at_centre_px'] for o in good]); rots = np.array([o['rotation_deg'] for o in good])
    print('registered %d of %d; shift range x %.1f..%.1f  y %.1f..%.1f ; rot range %.4f..%.4f deg' % (len(good), len(out), sh[:, 0].min(), sh[:, 0].max(), sh[:, 1].min(), sh[:, 1].max(), rots.min(), rots.max()))
    print('frame-to-frame steps at the centre (px):', np.round(np.hypot(*np.diff(sh, axis=0).T), 1).tolist())
