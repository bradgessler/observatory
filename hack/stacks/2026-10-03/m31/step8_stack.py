"""Step 8: put every used frame's four colour planes onto the reference frame's sensor grid and combine.

Two versions (argument A or B), same frames, same weights, same registration:
  A  'as recorded': nothing is done about the flat field.
  B  each colour plane is first divided by the smooth, radially symmetric, centred vignetting profile of its
     colour (step 6a), and sensor pixels under a known dust shadow (step 6b) are left out of the average.
     The same combine without leaving the dust out is kept beside it, to show what that does.
  C  (an extra, beyond what was asked for) as B, but divided by the whole smooth cloud-glow flat of its plane
     (step 6c: radial part, tilt and edge shading) instead of the radial profile alone.

Per frame and plane: (black-subtracted, hot pixels repaired) [/ V(r) in B]  x 1/transparency  ->  resampled onto
the reference sensor grid (rotation + shift + the plane's own place in the 2x2 colour cell, Lanczos-4, no
demosaic)  ->  minus ONE constant, chosen so that the frame matches the reference frame in the darkest quarter
of the reference (3-sigma clipped mean of the difference, measured on the half-size grid).
The absolute zero is unknown: the galaxy fills the frame, so every plane of the stack still carries the reference
frame's sky.

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD
across the frames, floor 0.4 x the single-frame noise, widened by each frame's own noise factor), then again
3 sigma about the weighted mean of the survivors, then the weighted mean (weights from step 7).
Also kept: the count of frames used per pixel, the count of frames covering each pixel, the same combine from
the clear frames only with equal weights, from the odd and the even frames (their half-difference is the
stack's noise with the sky cancelled), from the first and last third of the run (the field sits differently on
the sensor in the two, so their difference tests the flat field), and the difference of two neighbouring
clear frames (the noise of one frame)."""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

VERSION = sys.argv[1]
assert VERSION in ('A', 'B', 'C')
FLATTENED = VERSION in ('B', 'C')
KAPPA = 3.0
sel = json.load(open(W('step7_select.json'))); USE = sel['used']
tr = {o['stamp']: o for o in json.load(open(W('step4_transforms.json')))['transforms']}
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
iref = stamps.index(REF_STAMP)
vig = json.load(open(W('vignette.json'))); rgrid = np.array(vig['r_px'])
VMAP = [np.interp(radius_plane(p), rgrid, np.array(vig['V']['RGGB'[p]])).astype(np.float32) for p in range(4)] if VERSION == 'B' else (list(np.load(W('flat2d.npy'))) if VERSION == 'C' else None)
DUST = np.load(W('dustmask.npy')).astype(np.float32) if FLATTENED else None
h2, w2 = H // 2, Wd // 2

def prep(stamp, p):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p])
    if FLATTENED: P /= VMAP[p]
    P *= np.float32(scale[stamp])
    return P

# ---------------- constants: match every frame to the reference in the reference's darkest quarter ----------------
def plane_maps(stamp, p):
    """Where each pixel of the reference's colour plane p falls in this frame's plane p (plane px)."""
    R = np.array(tr[stamp]['R']); t = np.array(tr[stamp]['t']); ox, oy = OFFS[p]
    Y, X = np.mgrid[0:h2, 0:w2].astype(np.float32)
    sx = 2 * X + ox; sy = 2 * Y + oy
    return (((R[0, 0] * sx + R[0, 1] * sy + t[0]) - ox) / 2).astype(np.float32), (((R[1, 0] * sx + R[1, 1] * sy + t[1]) - oy) / 2).astype(np.float32)

refP = [prep(REF_STAMP, p) for p in range(4)]
Gs = cv2.GaussianBlur(cv2.medianBlur((refP[1] + refP[2]) / 2, 5), (0, 0), 10)
inner = np.zeros((h2, w2), bool); inner[100:-100, 100:-100] = True
DARK_Q = 25.0
dark = (Gs < np.percentile(Gs[inner], DARK_Q)) & inner
if FLATTENED: dark &= DUST < 0.5
print('version', VERSION, 'frames', N, 'dark region: %.1f%% of the reference plane, green there %.1f..%.1f DN' % (100 * dark.mean(), Gs[dark].min(), Gs[dark].max()), flush=True)
cv2.imwrite(W('v_dark_region_%s.png' % VERSION), (cv2.resize(dark.astype(np.uint8) * 255, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)))

def offsets(i):
    s = stamps[i]; out = []; slope = None
    if s == REF_STAMP: return [0.0, 0.0, 0.0, 0.0], 1.0          # the reference is the level every other frame is matched to
    for p in range(4):
        mx, my = plane_maps(s, p)
        Wp = cv2.remap(prep(s, p), mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
        ok = dark & np.isfinite(Wp)
        if FLATTENED: ok &= cv2.remap(DUST, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=1.0) < 0.02
        c = clipped_stats((Wp - refP[p])[ok])[0]; out.append(float(c))
        if p == 1:   # does the frame follow the reference in the bright parts too? slope of 64 px block means
            bs = 64; ny, nx = h2 // bs, w2 // bs
            a = (Wp - c)[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1); b = refP[p][:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny * nx, -1)
            good = np.isfinite(a).all(1); am = np.median(a[good], 1); bm = np.median(b[good], 1)
            sel_ = (bm < 3000)
            A = np.column_stack([bm[sel_], np.ones(sel_.sum())]); co, *_ = np.linalg.lstsq(A, am[sel_], rcond=None); slope = float(co[0])
    return out, slope
with ThreadPoolExecutor(6) as ex: res = list(ex.map(offsets, range(N)))
CONST = np.array([r[0] for r in res], np.float32); SLOPE = [r[1] for r in res]
for i, s in enumerate(stamps): print(s, 'T %.3f' % USE[i]['transparency'], 'constants R G1 G2 B', np.round(CONST[i], 2).tolist(), 'slope against the reference (green blocks) %.4f' % SLOPE[i], flush=True)
del refP

# ---------------- the stack ----------------
gy, gx = np.mgrid[0:H, 0:Wd].astype(np.float32)
def warp(i, p):
    s = stamps[i]; R = np.array(tr[s]['R'], np.float64); t = np.array(tr[s]['t'], np.float64); ox, oy = OFFS[p]
    fx = (R[0, 0] * gx + R[0, 1] * gy + t[0]).astype(np.float32); fy = (R[1, 0] * gx + R[1, 1] * gy + t[1]).astype(np.float32)   # where each output pixel falls in this frame, sensor px
    out = cv2.remap(prep(s, p), (fx - ox) / 2, (fy - oy) / 2, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))
    out -= CONST[i, p]
    d = None
    if FLATTENED:
        d = cv2.remap(DUST, (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
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
if FLATTENED: store['mean_dust_left_in'] = np.zeros((4, H, Wd), np.float32)
cover = np.zeros((H, Wd), np.uint8); pair = np.zeros((4, H, Wd), np.float32); info = []
for p in range(4):
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex: res = list(ex.map(lambda i: warp(i, p), range(N)))
    cube = np.stack([r[0] for r in res]); dust = np.stack([r[1] for r in res]) if FLATTENED else None; del res
    geo = np.isfinite(cube)
    if p == 1: cover[:] = geo.sum(0)
    pair[p] = (cube[iref] - cube[iref + 1]) / np.sqrt(2.0)
    floor = np.float32(0.4 * s1[REF_STAMP]['corner'][p]['clipped_std'])
    rows = [(a, min(a + 64, H)) for a in range(0, H, 64)]
    def work(ab):
        a, b = ab; c = cube[:, a:b]; g = geo[:, a:b]
        if FLATTENED:
            o = combine(c, g & ~dust[:, a:b], floor, SUB); o['mean_dust_left_in'] = combine(c, g, floor, None)['mean']
        else:
            o = combine(c, g, floor, SUB)
        return ab, o
    with ThreadPoolExecutor(8) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): store[k][p, a:b] = v
    seen = geo.sum(); usedn = int(store['used'][p].sum()); dustn = int((geo & dust).sum()) if FLATTENED else 0
    info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=int(seen), samples_left_out_for_dust=dustn, samples_dropped_by_the_clip=int(seen - dustn - usedn), dropped_fraction=float((seen - dustn - usedn) / max(seen - dustn, 1)),
                     pixels_with_no_frame=int((store['used'][p] == 0).sum())))
    print(PLANE_NAMES[p], info[-1], '%.0fs' % (time.time() - t0), flush=True)
    del cube, geo, dust
for k, v in store.items(): np.save(W('%s_%s.npy' % (VERSION, k)), v)
np.save(W('%s_cover.npy' % VERSION), cover); np.save(W('%s_pairdiff.npy' % VERSION), pair)
json.dump(dict(version=VERSION, frames=stamps, reference=REF_STAMP, kappa=KAPPA, dark_region_percentile=DARK_Q, constants={s: CONST[i].tolist() for i, s in enumerate(stamps)}, slope_against_reference_green={s: SLOPE[i] for i, s in enumerate(stamps)},
               subsets={k: [stamps[i] for i in v[0]] for k, v in SUB.items()}, pair=[stamps[iref], stamps[iref + 1]], planes=info), open(W('step8_%s.json' % VERSION), 'w'), indent=1)
