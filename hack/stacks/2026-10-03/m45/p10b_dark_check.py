"""Step 10b: a second look at the sensor pattern of step 10, by a different road (it is NOT used for the mosaic).
Every frame's sky is a lamp of a different brightness (the sky was 28 DN of green in the clearest frames and up to
130 under cloud). Per 64 px block of the sensor and colour plane, over all 72 frames (hot pixels repaired, block
level = mean of the pixels within 2.5 sigma of the block's median):
        raw level = S x F(block) + D(block),      S = the frame's sky level (median of plane / flat)
F is what the light does (it should be the flat), D is what is there without light. A robust straight-line fit
per block (2.5 sigma rejection: frames in which a star or a glow sits on the block drop out) gives D. D is then
described by the same second-order form as step 10's pattern, plus the tilt terms the overlaps cannot see.
Caveat: under cloud the sky is not even, and the tilt of D is tangled with a tilt of F (they come out equal and
opposite at the mean sky level); the second-order terms are not tangled that way."""
import json, os
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from c import *
F = json.load(open(W('p1.json')))['frames']
FLATS = stack_flats()[0]                         # the flat the stacks were divided by
BS = 64; ny, nx = H2 // BS, W2 // BS
def bl(a):
    b = a[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    med = np.median(b, axis=2); d = b - med[..., None]; s = 1.4826 * np.median(np.abs(d), axis=2) + 4.0
    m = np.abs(d) < 2.5 * s[..., None]
    return (b * m).sum(2) / np.maximum(m.sum(2), 1)
def load(fr):
    P, ceil, meta, tr = repaired(fr['path'], [c_['clipped_std'] for c_ in fr['corner']])
    return np.stack([bl(P[p]) for p in range(4)])
with ThreadPoolExecutor(8) as ex: B = np.stack(list(ex.map(load, F)))
FB = np.stack([bl(FLATS[p]) for p in range(4)])
BY, BX = np.mgrid[0:ny, 0:nx]; u = ((BX + 0.5) * BS - W2 / 2) / (W2 / 2); v_ = ((BY + 0.5) * BS - H2 / 2) / (H2 / 2)
out = dict(frames=len(F), block_px=BS, planes={})
for p in range(4):
    v = B[:, p]; S = np.array([np.median(v[i] / FB[p]) for i in range(len(F))])
    Fm = np.zeros((ny, nx)); Dm = np.zeros((ny, nx))
    for y in range(ny):
        for x in range(nx):
            yv = v[:, y, x]; keep = np.ones(len(S), bool)
            for _ in range(6):
                A = np.column_stack([S[keep], np.ones(keep.sum())]); co, *_ = np.linalg.lstsq(A, yv[keep], rcond=None)
                r = yv - (co[0] * S + co[1]); sd = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 2.5 * max(sd, 0.3)
            Fm[y, x], Dm[y, x] = co[0], co[1]
    A = np.column_stack([np.ones(u.size), u.ravel(), v_.ravel(), (u * u).ravel(), (u * v_).ravel(), (v_ * v_).ravel()]); d = Dm.ravel(); keep = np.ones(d.size, bool)
    for _ in range(5):
        co, *_ = np.linalg.lstsq(A[keep], d[keep], rcond=None); r = d - A @ co; sd = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * sd
    cov = np.linalg.inv(A[keep].T @ A[keep]) * sd ** 2; sg = np.sqrt(np.diag(cov))
    out['planes'][PLANE_NAMES[p]] = dict(sky_range_dn=[float(S.min()), float(S.max())], slope_over_flat_median=float(np.median(Fm / FB[p])), d_median_dn=float(np.median(Dm)),
                                         d_fit_dn={k: [float(c_), float(s_)] for k, c_, s_ in zip(['1', 'u', 'v', 'u^2', 'u v', 'v^2'], co, sg)}, d_by_row_band_dn=[float(np.median(Dm[i])) for i in range(ny)], blocks_kept=int(keep.sum()))
    print('%-2s sky %.0f..%.0f DN; D = %s (rms %.2f)' % (PLANE_NAMES[p], S.min(), S.max(), '  '.join('%s %+.2f+-%.2f' % (k, c_, s_) for k, c_, s_ in zip(['1', 'u', 'v', 'u^2', 'uv', 'v^2'], co, sg)), sd))
json.dump(out, open(W('p10b_dark_check.json'), 'w'), indent=1)
