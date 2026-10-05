"""Exploration: inside a panel, how does (frame / T - clearest frame) look on large scales? The galaxy cancels."""
import json, sys, numpy as np, cv2
from mcommon import *
sel = json.load(open(W('m5_select.json'))); T4 = json.load(open(W('m4_transforms.json')))
FLAT = np.load(CW('flat2d.npy')); DUST = np.load(CW('dustmask.npy'))
def blocks(a, bs=128):
    ny, nx = a.shape[0] // bs, a.shape[1] // bs
    with np.errstate(all='ignore'):
        return np.nanmedian(a[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
for name in sys.argv[1:]:
    q = {r['stamp']: r for r in sel[name]['quality']}; tr = {o['stamp']: o for o in T4[name]['transforms']}
    cand = [s for s in q if q[s]['flux_rel'] is not None and q[s]['flux_rel'] >= 0.6]
    ref = max(cand, key=lambda s: q[s]['flux_rel'] / s_ if (s_ := 1) else 0)
    ref = min([s for s in cand if q[s]['flux_rel'] >= 0.97], key=lambda s: q[s]['corner_green'])
    def warped(s, p=1):
        P = np.load(W('planes/' + s + '.npy'), mmap_mode='r')[p] / FLAT[p] / q[s]['flux_rel']
        P = np.where(DUST, np.nan, P).astype(np.float32)
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t']); ox, oy = OFFS[p]
        Y, X = np.mgrid[0:H2, 0:W2].astype(np.float32); sx = 2 * X + 0.5; sy = 2 * Y + 0.5
        fx = R[0, 0] * sx + R[0, 1] * sy + t[0]; fy = R[1, 0] * sx + R[1, 1] * sy + t[1]
        return cv2.remap(P, ((fx - ox) / 2).astype(np.float32), ((fy - oy) / 2).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    Wr = warped(ref); br = blocks(Wr)
    print('panel', name, 'reference', ref, 'T', round(q[ref]['flux_rel'], 3), 'corner', round(q[ref]['corner_green']), 'ref blocks G1: min %.0f med %.0f max %.0f' % (np.nanmin(br), np.nanmedian(br), np.nanmax(br)))
    ny, nx = br.shape; YY, XX = np.mgrid[0:ny, 0:nx]; xn = (XX - (nx - 1) / 2) / (nx / 2); yn = (YY - (ny - 1) / 2) / (ny / 2)
    for s in cand:
        if s == ref: continue
        d = blocks(warped(s) - Wr)
        ok = np.isfinite(d) & (br < np.nanmin(br) + 150)
        A = np.column_stack([np.ones(ok.sum()), xn[ok], yn[ok]]); v = d[ok]; keep = np.ones(len(v), bool)
        for _ in range(4):
            co, *_ = np.linalg.lstsq(A[keep], v[keep], rcond=None); r = v - A @ co; sd = 1.4826 * np.median(np.abs(r[keep])); keep = np.abs(r) < 3 * sd
        r0 = v - np.median(v)
        A2 = np.column_stack([np.ones(ok.sum()), xn[ok], yn[ok], xn[ok] ** 2, xn[ok] * yn[ok], yn[ok] ** 2]); co2, *_ = np.linalg.lstsq(A2[keep], v[keep], rcond=None); r2 = v - A2 @ co2
        print('   %s T %.3f tilt %+.3f %+.3f corner %4.0f | diff const %+7.1f  slope x %+6.1f y %+6.1f DN per half-frame | rms: const only %.2f, plane %.2f, quadratic %.2f (block noise ~%.2f) | quad terms %s' % (
            s, q[s]['flux_rel'], *q[s]['tilt'], q[s]['corner_green'], co[0], co[1], co[2], np.sqrt(np.mean(r0[keep] ** 2)), np.sqrt(np.mean(r[keep] ** 2)), np.sqrt(np.mean(r2[keep] ** 2)), 1.25 * 80 * np.sqrt(2) / 128, np.round(co2[3:], 1).tolist()))
