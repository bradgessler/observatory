"""Rerun step f5: is the stack with the twilight-based flat (F) better than the core run's versions (A as recorded,
B radial profile + dust left out, C cloud flat + dust left out + five shadow cores divided)? In numbers.

1. Sensor dust left in the picture. The twilight flat shows every dust shadow (its green over its own wide smooth
   part = the dust transmission D, sensor coordinates). Carried onto the picture grid with each used frame's
   registration and averaged with the frames' weights it is the shadow pattern T a stack would hold with nothing
   done about dust. For each version: its green, high-passed (minus a Gaussian sigma 60 px of its 5x5 median), over
   its level, fitted against T high-passed the same way: slope = the fraction of the dust pattern still in the
   picture (1 = all of it, 0 = none); also the rms and deepest of what is left, in DN. Outside the bulge (level
   under 400 DN), full coverage, 200 px inside the frame.
2. The flat-field test of check_flat.py: first third minus last third of the frames (the field sits 170 px away and
   turned by 2.3 degrees), green, 256 px blocks.
3. Noise: (odd - even) / 2 in the core recipe's patch (sensor px x 1020..1520, y 304..804), 3-sigma clipped.
4. Large scale against C: 256 px block medians of F - C and F - B (after each version's zero)."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
from final import BLEND_LO, BLEND_HI, cover_rect, zero_levels, CLEAN_MIN, EDGE_SHADE
OLD = os.environ['M31_OLD_WORK']
np.set_printoptions(linewidth=250, precision=2, suppress=True)
sel = json.load(open(W('step7_select.json')))['used']; tr = {o['stamp']: o for o in json.load(open(W('step4_transforms.json')))['transforms']}
HY = np.load(os.environ['M31_MASTER_FLAT'])
def wide(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
    return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
g = ((HY[1] + HY[2]) / 2).astype(np.float32); D = cv2.GaussianBlur(g / wide(g), (0, 0), 1.5); D = np.minimum(D, 1.0).astype(np.float32)
D[0:350, 1600:2200] = 1.0          # the hair zone: not dust
gy, gx = np.mgrid[0:H, 0:Wd].astype(np.float32)
def one(u):
    R = np.array(tr[u['stamp']]['R']); t = np.array(tr[u['stamp']]['t'])
    fx = (R[0, 0] * gx + R[0, 1] * gy + t[0]).astype(np.float32); fy = (R[1, 0] * gx + R[1, 1] * gy + t[1]).astype(np.float32)
    return cv2.remap(D, (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan')), u['weight']
num = np.zeros((H, Wd), np.float64); den = np.zeros((H, Wd), np.float64)
with ThreadPoolExecutor(6) as ex:
    for d, w in ex.map(one, sel):
        ok = np.isfinite(d); num += np.where(ok, d, 0) * w; den += ok * w
T = (num / np.maximum(den, 1e-9)).astype(np.float32); del num, den
np.save(W('f5_dust_pattern.npy'), T)

def final(ver, src):
    st = np.load(os.path.join(src, '%s_mean.npy' % ver))
    if ver in ('B', 'C', 'F'):
        li = np.load(os.path.join(src, '%s_mean_dust_left_in.npy' % ver)); used = np.load(os.path.join(src, '%s_used.npy' % ver)).astype(np.float32)
        wgt = np.clip((used - BLEND_LO) / float(BLEND_HI - BLEND_LO), 0, 1)
        st = np.where(np.isfinite(st), st, li) * wgt + li * (1 - wgt)
    return st
def hp(a, sig=60.0):
    a = np.ascontiguousarray(a, np.float32); lo = cv2.GaussianBlur(cv2.medianBlur(a, 5), (0, 0), sig)
    return a - lo, lo
rect = cover_rect('F', len(sel)); x0, y0, x1, y1 = rect; print('well-covered rectangle', rect)
predC = np.load(os.path.join(OLD, 'dust_pred_final.npy'))
Thp, Tlo = hp(T)
out = dict(rect=rect, dust={}, early_minus_late={}, noise={}, large_scale={})
G = {}; LEV = {}
for ver, src in (('A', OLD), ('B', OLD), ('C', OLD), ('F', WORK)):
    f = final(ver, src)
    if ver == 'C': f = f / predC[None]
    if ver == 'F': np.save(W('F_final.npy'), f)
    g = (f[1] + f[2]) / 2; G[ver] = g
    gg = np.nan_to_num(g, nan=float(np.nanmedian(g)))
    y, lo = hp(gg); rel = y / np.maximum(lo, 1.0)
    inside = np.zeros((H, Wd), bool); inside[y0 + 200:y1 - 200, x0 + 200:x1 - 200] = True
    for nm, cut in (('all shadows deeper than 0.3%', -0.003), ('deeper than 1%', -0.01), ('deeper than 2%', -0.02)):
        m = inside & (lo < 400) & (Thp < cut) & np.isfinite(g)
        x = Thp[m]; yy = rel[m]; slope = float((x * yy).sum() / (x * x).sum())
        # error from the scatter of blocks of 4000 px
        o = np.argsort(np.random.RandomState(1).rand(m.sum())); nb = 40; sl = [float((x[o[i::nb]] * yy[o[i::nb]]).sum() / (x[o[i::nb]] ** 2).sum()) for i in range(nb)]
        left_dn = slope * x * lo[m]
        out['dust'].setdefault(ver, {})[nm] = dict(pixels=int(m.sum()), fraction_of_pattern_left=slope, error=float(np.std(sl) / np.sqrt(nb)), predicted_pattern_rms=float(np.sqrt((x ** 2).mean())), left_rms_dn=float(np.sqrt((left_dn ** 2).mean())), left_deepest_dn=float(left_dn.min()) if slope > 0 else float(left_dn.max()), level_dn_median=float(np.median(lo[m])))
        print('%s dust, %-28s px %8d: fraction of the pattern left %+.3f +- %.3f; pattern rms %.4f; left in the picture rms %.2f DN, deepest %.1f DN (level %.0f DN)' % (ver, nm, m.sum(), slope, np.std(sl) / np.sqrt(nb), np.sqrt((x ** 2).mean()), np.sqrt((left_dn ** 2).mean()), out['dust'][ver][nm]['left_deepest_dn'], np.median(lo[m])))
    LEV[ver] = lo
    # early - late
    e = np.load(os.path.join(src, '%s_early.npy' % ver))[1:3].mean(0); l = np.load(os.path.join(src, '%s_late.npy' % ver))[1:3].mean(0); m_ = np.load(os.path.join(src, '%s_mean.npy' % ver))[1:3].mean(0)
    cover = np.load(os.path.join(src, '%s_cover.npy' % ver)); bs = 256
    d = np.where(cover >= len(sel), e - l, np.nan); ny, nx = H // bs, Wd // bs
    with np.errstate(all='ignore'):
        b = np.nanmedian(d[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2); lev = np.nanmedian(m_[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    Y, X = np.mgrid[0:ny, 0:nx]; ok = np.isfinite(b) & (lev < 400)
    A = np.column_stack([np.ones(ok.sum()), (X[ok] - (nx - 1) / 2) * bs / 3000, (Y[ok] - (ny - 1) / 2) * bs / 3000]); co, *_ = np.linalg.lstsq(A, b[ok], rcond=None); res = b[ok] - A @ co
    out['early_minus_late'][ver] = dict(blocks=int(ok.sum()), rms_dn=float(np.sqrt((b[ok] ** 2).mean())), min_dn=float(b[ok].min()), max_dn=float(b[ok].max()), slope_x_dn_per_3000px=float(co[1]), slope_y_dn_per_3000px=float(co[2]), rms_after_slope_dn=float(np.sqrt((res ** 2).mean())))
    print('%s first third - last third, green, 256 px blocks (%d): rms %.2f DN (%.2f..%.2f), slope %.2f x %.2f y DN per 3000 px, rms after the slope %.2f' % (ver, ok.sum(), out['early_minus_late'][ver]['rms_dn'], b[ok].min(), b[ok].max(), co[1], co[2], out['early_minus_late'][ver]['rms_after_slope_dn']))
    # same test on 64 px blocks high-passed: small-scale flat errors (dust) show as pairs of spots
    bs2 = 64; ny2, nx2 = H // bs2, Wd // bs2
    with np.errstate(all='ignore'): b2 = np.nanmedian(d[:ny2 * bs2, :nx2 * bs2].reshape(ny2, bs2, nx2, bs2).transpose(0, 2, 1, 3).reshape(ny2, nx2, -1), axis=2)
    ok2 = np.isfinite(b2); b2f = np.where(ok2, b2, 0).astype(np.float32); sm = cv2.blur(b2f, (9, 9)) / np.maximum(cv2.blur(ok2.astype(np.float32), (9, 9)), 1e-3)
    lev2 = np.nanmedian(m_[:ny2 * bs2, :nx2 * bs2].reshape(ny2, bs2, nx2, bs2).transpose(0, 2, 1, 3).reshape(ny2, nx2, -1), axis=2)
    r2 = (b2 - sm)[ok2 & (lev2 < 400)]
    out['early_minus_late'][ver]['rms_64px_blocks_about_their_9x9_mean_dn'] = float(np.sqrt((r2 ** 2).mean()))
    print('   64 px blocks about their 9 x 9 block mean: rms %.3f DN (%d blocks)' % (np.sqrt((r2 ** 2).mean()), r2.size))
    # noise
    odd = np.load(os.path.join(src, '%s_odd.npy' % ver)); even = np.load(os.path.join(src, '%s_even.npy' % ver)); hd = (odd - even) / 2
    P = (slice(304, 804), slice(1020, 1520)); out['noise'][ver] = dict(zip(PLANE_NAMES, [float(clipped_stats(hd[p][P])[1]) for p in range(4)]))
    print('%s noise of the stack in the patch, per plane: %s' % (ver, np.round(list(out['noise'][ver].values()), 2)))
    del odd, even, hd, e, l, m_, f
# large scale F against B and C (each minus its own median in the zero region of C, to compare shapes)
bs = 256; ny, nx = (y1 - y0) // bs, (x1 - x0) // bs
def blk(a):
    a = a[y0:y1, x0:x1][:ny * bs, :nx * bs]
    with np.errstate(all='ignore'): return np.nanmedian(a.reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
for other in ('C', 'B'):
    d = blk(G['F'] - G[other]); d = d - np.median(d)
    out['large_scale']['F_minus_' + other] = dict(block_px=bs, rms_dn=float(np.sqrt((d ** 2).mean())), min_dn=float(d.min()), max_dn=float(d.max()), blocks=[[round(float(v), 2) for v in row] for row in d])
    print('F - %s, green, 256 px block medians about their median: rms %.2f DN, %.2f..%.2f' % (other, np.sqrt((d ** 2).mean()), d.min(), d.max())); print(d)
json.dump(out, open(W('f5_evaluate.json'), 'w'), indent=1)
