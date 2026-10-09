"""Rerun step f4: the stack again, as step8_stack.py version C, with the twilight-based flat. Version name F.

What is the same as step 8 (version C): the frames, their weights and registration (step 7, step 4), the scaling by
1 / transparency, the resampling (Lanczos-4 onto the reference frame's sensor grid, each plane from its own place in
the colour cell), ONE constant per frame and plane (matched to the reference frame in the reference's darkest
quarter), the clip (3 sigma about the median, then about the weighted mean), the weighted mean, and the side
products (clear-only, odd, even, first third, last third, the pair difference).

What is different:
  flat      every plane is divided by the MASTER FLAT of real flat frames (M31_MASTER_FLAT: the twilight master with
            the cloud flat's large-scale shape, m42/calibration/flat-delivered.npy), dust shadows included, instead
            of the smooth cloud-glow flat. No sensor pixel is left out for dust as such.
  left out  (a) the hair, per frame: the mask of step f2 for that frame (never a fixed map, never divided);
            (b) the sensor pixels of step f3, where the dawn flat is not the sensor's response of this hour.
            As before, the same combine with these samples LEFT IN is kept beside it (final planes blend it in
            where fewer than 12 clean frames exist).

'K' is a control, not a product: this same code with the core run's flat2d.npy and dustmask.npy, which must
reproduce the core run's version C (it does: see f4_control.json)."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

VERSION = sys.argv[1]; assert VERSION in ('F', 'K')
PLANES = [int(v) for v in os.environ.get('PLANES', '0,1,2,3').split(',')]
KAPPA = 3.0
CAL = os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-from-core-run')
sel = json.load(open(W('step7_select.json'))); USE = sel['used']
tr = {o['stamp']: o for o in json.load(open(W('step4_transforms.json')))['transforms']}
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
iref = stamps.index(REF_STAMP)
h2, w2 = H // 2, Wd // 2
if VERSION == 'F':
    VMAP = list(np.load(os.environ['M31_MASTER_FLAT']).astype(np.float32)); assert VMAP[0].shape == (h2, w2)
    STATIC = np.load(W('f3_leaveout.npy')); hz = np.load(W('f2_hair.npz'))
    LEAVE = {s: (STATIC | np.unpackbits(hz['m_' + s])[:h2 * w2].reshape(h2, w2).astype(bool)).astype(np.float32) for s in stamps}
else:
    VMAP = list(np.load(os.path.join(CAL, 'flat2d.npy'))); D0 = np.load(os.path.join(CAL, 'dustmask.npy')).astype(np.float32)
    LEAVE = {s: D0 for s in stamps}

def prep(stamp, p):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p])
    P /= VMAP[p]; P *= np.float32(scale[stamp])
    return P

def plane_maps(stamp, p):
    R = np.array(tr[stamp]['R']); t = np.array(tr[stamp]['t']); ox, oy = OFFS[p]
    Y, X = np.mgrid[0:h2, 0:w2].astype(np.float32)
    sx = 2 * X + ox; sy = 2 * Y + oy
    return (((R[0, 0] * sx + R[0, 1] * sy + t[0]) - ox) / 2).astype(np.float32), (((R[1, 0] * sx + R[1, 1] * sy + t[1]) - oy) / 2).astype(np.float32)

refP = {p: prep(REF_STAMP, p) for p in set(PLANES) | {1, 2}}
Gs = cv2.GaussianBlur(cv2.medianBlur((refP[1] + refP[2]) / 2, 5), (0, 0), 10)
inner = np.zeros((h2, w2), bool); inner[100:-100, 100:-100] = True
DARK_Q = 25.0
dark = (Gs < np.percentile(Gs[inner], DARK_Q)) & inner
dark &= LEAVE[REF_STAMP] < 0.5
print('version', VERSION, 'frames', N, 'planes', PLANES, 'dark region: %.1f%% of the reference plane, green there %.1f..%.1f DN' % (100 * dark.mean(), Gs[dark].min(), Gs[dark].max()), flush=True)

def offsets(i):
    s = stamps[i]; out = [0.0] * 4; slope = None
    if s == REF_STAMP: return [0.0, 0.0, 0.0, 0.0], 1.0
    for p in PLANES:
        mx, my = plane_maps(s, p)
        Wp = cv2.remap(prep(s, p), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
        ok = dark & np.isfinite(Wp)
        ok &= cv2.remap(LEAVE[s], mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1.0) < 0.02
        c = clipped_stats((Wp - refP[p])[ok])[0]; out[p] = float(c)
        if p == 1:
            bs = 64; ny, nx = h2 // bs, w2 // bs
            a = (Wp - c)[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1); b = refP[p][:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1)
            good = np.isfinite(a).all(1); am = np.median(a[good], 1); bm = np.median(b[good], 1)
            sel_ = (bm < 3000)
            A = np.column_stack([bm[sel_], np.ones(sel_.sum())]); co, *_ = np.linalg.lstsq(A, am[sel_], rcond=None); slope = float(co[0])
    return out, slope
with ThreadPoolExecutor(6) as ex: res = list(ex.map(offsets, range(N)))
CONST = np.array([r[0] for r in res], np.float32); SLOPE = [r[1] for r in res]
for i, s in enumerate(stamps): print(s, 'T %.3f' % USE[i]['transparency'], 'constants R G1 G2 B', np.round(CONST[i], 2).tolist(), 'slope against the reference (green blocks) %s' % SLOPE[i], flush=True)
del refP

gy, gx = np.mgrid[0:H, 0:Wd].astype(np.float32)
def warp(i, p):
    s = stamps[i]; R = np.array(tr[s]['R'], np.float64); t = np.array(tr[s]['t'], np.float64); ox, oy = OFFS[p]
    fx = (R[0, 0] * gx + R[0, 1] * gy + t[0]).astype(np.float32); fy = (R[1, 0] * gx + R[1, 1] * gy + t[1]).astype(np.float32)
    out = cv2.remap(prep(s, p), (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    out -= CONST[i, p]
    d = cv2.remap(LEAVE[s], (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
    return out, d

order = np.arange(N)
SUB = dict(clear=(np.array([i for i in order if USE[i]['clear']]), False), odd=(order[1::2], True), even=(order[0::2], True), early=(order[:N // 3], True), late=(order[N - N // 3:], True))
def take(s, k): return np.take_along_axis(s, k[None], 0)[0]
def combine(c, valid, floor, subs):
    f = nfac[:, None, None]; w = wts[:, None, None]
    with np.errstate(invalid='ignore', divide='ignore'):
        cv_ = np.where(valid, c, np.nan); n = valid.sum(0)
        lo = np.clip((n - 1) // 2, 0, N - 1); hi = np.clip(n // 2, 0, N - 1)
        s = np.sort(cv_, axis=0); med = 0.5 * (take(s, lo) + take(s, hi)); del s
        dev = np.abs(cv_ - med); sd = np.sort(dev, axis=0); mad = 0.5 * (take(sd, lo) + take(sd, hi)); del sd
        sig = np.maximum(1.4826 * mad, floor)
        keep = valid & (dev <= KAPPA * sig * f); del dev
        c0 = np.where(valid, c, 0)
        ws = (w * keep).sum(0); m1 = (w * keep * c0).sum(0) / np.maximum(ws, 1e-9)
        r = np.where(keep, (c0 - m1) / f, 0); nk = keep.sum(0)
        sd1 = np.maximum(np.sqrt((r ** 2).sum(0) / np.maximum(nk - 1, 1)), floor); del r
        keep = valid & (np.abs(c0 - m1) <= KAPPA * sd1 * f)
        ws = (w * keep).sum(0)
        mean = np.where(ws > 0, (w * keep * c0).sum(0) / np.maximum(ws, 1e-9), np.nan).astype(np.float32)
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint8), wsum=ws.astype(np.float32))
        for name, (idx, weighted) in (subs or {}).items():
            k = keep[idx]; ww = (w[idx] if weighted else 1.0) * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out

names = ['mean', 'used', 'wsum'] + list(SUB)
store = {k: np.zeros((4, H, Wd), np.uint8 if k == 'used' else np.float32) for k in names}
store['mean_dust_left_in'] = np.zeros((4, H, Wd), np.float32)
cover = np.zeros((H, Wd), np.uint8); pair = np.zeros((4, H, Wd), np.float32); info = []
for p in PLANES:
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda i: warp(i, p), range(N)))
    cube = np.stack([r[0] for r in res]); dust = np.stack([r[1] for r in res]); del res
    geo = np.isfinite(cube)
    if p == 1: cover[:] = geo.sum(0)
    pair[p] = (cube[iref] - cube[iref + 1]) / np.sqrt(2.0)
    floor = np.float32(0.4 * s1[REF_STAMP]['corner'][p]['clipped_std'])
    rows = [(a, min(a + 64, H)) for a in range(0, H, 64)]
    def work(ab):
        a, b = ab; c = cube[:, a:b]; g = geo[:, a:b]
        o = combine(c, g & ~dust[:, a:b], floor, SUB); o['mean_dust_left_in'] = combine(c, g, floor, None)['mean']
        return ab, o
    with ThreadPoolExecutor(8) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): store[k][p, a:b] = v
    seen = geo.sum(); usedn = int(store['used'][p].sum()); dustn = int((geo & dust).sum())
    info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=int(seen), samples_left_out=dustn, samples_dropped_by_the_clip=int(seen - dustn - usedn), dropped_fraction=float((seen - dustn - usedn) / max(seen - dustn, 1)),
                     pixels_with_no_frame=int((store['used'][p] == 0).sum())))
    print(PLANE_NAMES[p], info[-1], '%.0fs' % (time.time() - t0), flush=True)
    del cube, geo, dust
if VERSION == 'K':
    np.save(W('K_mean.npy'), store['mean'][PLANES]); np.save(W('K_mean_dust_left_in.npy'), store['mean_dust_left_in'][PLANES]); np.save(W('K_used.npy'), store['used'][PLANES])
else:
    for k, v in store.items(): np.save(W('%s_%s.npy' % (VERSION, k)), v)
    np.save(W('%s_cover.npy' % VERSION), cover); np.save(W('%s_pairdiff.npy' % VERSION), pair)
json.dump(dict(version=VERSION, frames=stamps, reference=REF_STAMP, kappa=KAPPA, dark_region_percentile=DARK_Q, constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, slope_against_reference_green={s: SLOPE[i] for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v[0]] for k, v in SUB.items()}, pair=[stamps[iref], stamps[iref + 1]], planes=info, flat=os.environ.get('M31_MASTER_FLAT') if VERSION == 'F' else 'flat2d.npy'), open(W('step8_%s.json' % VERSION), 'w'), indent=1)
