"""Step 8 (from hack/stacks/2026-10-03/m31/step8_stack.py, on the colour-cell grid): put every used frame's four colour
planes onto the reference frame's grid of 2 x 2 colour cells and combine.

Versions (argument; F is delivered):
  F  each plane divided by the large-scale flat of its colour (step 6: vignetting and edge shading, from M76's sky,
     each colour from its own map)
     and by the dust model (step 6b: the shadows confirmed on two skies).
  L  the large-scale flat only: dust left in (to see what the dust model does).
  A  as recorded: no flat at all.
  S  the trial NOT delivered: as F with red and blue flats shaped like green (step 6 says why it was dropped).

Per frame and plane: (black-subtracted, hot pixels repaired) [/ flat] x 1/transparency -> resampled onto the
reference grid (rotation + shift + the plane's own place in the 2 x 2 cell; Lanczos-4; output pixel (X, Y) is
reference sensor (2X + 0.5, 2Y + 0.5); no demosaic, nothing enlarged) -> minus ONE constant, chosen so that the frame
matches the reference frame in the darkest quarter of the reference (3-sigma clipped mean of the difference). The
absolute zero is unknown here: the galaxy fills the frame (step 9 sets it).

Combine, per pixel and plane: values further than 3 sigma from the median are dropped (sigma = 1.4826 x MAD across
the frames, floor 0.4 x the single-frame noise, widened by each frame's own noise factor), then again 3 sigma about
the weighted mean of the survivors, then the weighted mean (weights from step 7).
Also kept: frames used per pixel, frames covering each pixel, the same combine from the odd and the even frames
(their half-difference is the stack's noise with the sky cancelled), from the first and the last third (the field
sits differently on the sensor in the two, so their difference tests the flat), the reference frame alone on the
same grid, and the difference of two neighbouring frames / sqrt 2 (the noise of one frame)."""
import os, sys, time
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *

VERSION = sys.argv[1] if len(sys.argv) > 1 else 'F'
assert VERSION in ('F', 'L', 'A', 'S')
KAPPA = 3.0
sel = jload('step7_select.json'); USE = sel['used']
tr = {o['stamp']: o for o in jload('step4_transforms.json')['transforms']}
s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
DARK = jload('step2.json')['dark_corner']
N = len(USE); stamps = [u['stamp'] for u in USE]
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32); scale = {u['stamp']: u['scale'] for u in USE}
iref = stamps.index(REF_STAMP)
COLOUR_OF = ['R', 'G', 'G', 'B']


def up(blocks, bs):
    """A block map (block centres at plane px b*bs + (bs-1)/2) to the full plane grid, bilinear; edges held."""
    ny, nx = blocks.shape
    f = cv2.resize(blocks.astype(np.float32), (nx * bs, ny * bs), interpolation=cv2.INTER_LINEAR)
    return np.pad(f, ((0, h2 - ny * bs), (0, w2 - nx * bs)), mode='edge')


FLAT = None
if VERSION in ('F', 'L', 'S'):
    fb = np.load(W('flat_blocks_greenshape.npz' if VERSION == 'S' else 'flat_blocks.npz')); bs = int(fb['bs'])
    FLAT = [up(fb[COLOUR_OF[p]], bs) for p in range(4)]
    if VERSION in ('F', 'S'):
        dm = np.load(W('dust_model.npz')); D = up(dm['model'], int(dm['bs']))
        FLAT = [f * D for f in FLAT]


def prep(stamp, p):
    P = np.array(np.load(W('planes/' + stamp + '.npy'), mmap_mode='r')[p])
    if FLAT is not None: P /= FLAT[p]
    P *= np.float32(scale[stamp])
    return P


Y, X = np.mgrid[0:h2, 0:w2].astype(np.float32)
SX, SY = 2 * X + 0.5, 2 * Y + 0.5                               # reference sensor px of each output pixel


def maps(stamp, p):
    R = np.array(tr[stamp]['R'], np.float64); t = np.array(tr[stamp]['t'], np.float64); ox, oy = OFFS[p]
    fx = R[0, 0] * SX + R[0, 1] * SY + t[0]; fy = R[1, 0] * SX + R[1, 1] * SY + t[1]
    return ((fx - ox) / 2).astype(np.float32), ((fy - oy) / 2).astype(np.float32)


def warp_raw(stamp, p, interp=cv2.INTER_LANCZOS4):
    mx, my = maps(stamp, p)
    return cv2.remap(prep(stamp, p), mx, my, interp, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan'))


# ---------------- constants: every frame matched to the reference in the reference's darkest quarter ----------------
refW = [warp_raw(REF_STAMP, p) for p in range(4)]
G0 = np.nan_to_num((refW[1] + refW[2]) / 2, nan=0.0)
Gs = cv2.GaussianBlur(cv2.medianBlur(G0, 5), (0, 0), 10)
inner = np.zeros((h2, w2), bool); inner[100:-100, 100:-100] = True; inner &= np.isfinite(refW[1])
DARK_Q = 25.0
dark = (Gs < np.percentile(Gs[inner], DARK_Q)) & inner
print('version', VERSION, 'frames', N, 'dark region: %.1f%% of the grid, green there %.1f..%.1f DN' % (100 * dark.mean(), Gs[dark].min(), Gs[dark].max()), flush=True)


def offsets(i):
    s = stamps[i]
    if s == REF_STAMP: return [0.0] * 4
    out = []
    for p in range(4):
        Wp = warp_raw(s, p, cv2.INTER_LINEAR)
        ok = dark & np.isfinite(Wp)
        out.append(float(clipped_stats((Wp - refW[p])[ok][::3])[0]))
    return out


with ThreadPoolExecutor(WORKERS) as ex: CONST = np.array(list(ex.map(offsets, range(N))), np.float32)
for i, s in enumerate(stamps): print(s, 'T %.3f' % USE[i]['transparency'], 'constants R G1 G2 B', np.round(CONST[i], 2).tolist(), flush=True)
del refW


def warp(i, p):
    out = warp_raw(stamps[i], p); out -= CONST[i, p]; return out


order = np.arange(N)
SUB = dict(odd=order[1::2], even=order[0::2], early=order[:N // 3], late=order[N - N // 3:])


def take(s, k): return np.take_along_axis(s, k[None], 0)[0]


def combine(c, valid, floor):
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
        out = dict(mean=mean, used=keep.sum(0).astype(np.uint8))
        for name, idx in SUB.items():
            k = keep[idx]; ww = w[idx] * k; wsum = ww.sum(0)
            out[name] = np.where(wsum > 0, (ww * c0[idx]).sum(0) / np.maximum(wsum, 1e-9), np.nan).astype(np.float32)
    return out


names = ['mean', 'used'] + list(SUB)
store = {k: np.zeros((4, h2, w2), np.uint8 if k == 'used' else np.float32) for k in names}
cover = np.zeros((h2, w2), np.uint8); pair = np.zeros((4, h2, w2), np.float32); single = np.zeros((4, h2, w2), np.float32); info = []
for p in range(4):
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex: cube = np.stack(list(ex.map(lambda i: warp(i, p), range(N))))
    geo = np.isfinite(cube)
    if p == 1: cover[:] = geo.sum(0)
    single[p] = cube[iref]; pair[p] = (cube[iref] - cube[iref + 1]) / np.sqrt(2.0)
    floor = np.float32(0.4 * s1[REF_STAMP]['corners'][DARK]['std'][p])
    rows = [(a, min(a + 64, h2)) for a in range(0, h2, 64)]
    def work(ab):
        a, b = ab
        return ab, combine(cube[:, a:b], geo[:, a:b], floor)
    with ThreadPoolExecutor(WORKERS) as ex:
        for (a, b), o in ex.map(work, rows):
            for k, v in o.items(): store[k][p, a:b] = v
    seen = int(geo.sum()); usedn = int(store['used'][p].sum())
    info.append(dict(plane=PLANE_NAMES[p], sigma_floor=float(floor), samples_in_coverage=seen, samples_dropped_by_the_clip=seen - usedn, dropped_fraction=float((seen - usedn) / max(seen, 1)),
                     pixels_with_no_frame=int((store['used'][p] == 0).sum())))
    print(PLANE_NAMES[p], info[-1], '%.0fs' % (time.time() - t0), flush=True)
    del cube, geo
for k, v in store.items(): np.save(W('%s_%s.npy' % (VERSION, k)), v)
np.save(W('%s_cover.npy' % VERSION), cover); np.save(W('%s_pairdiff.npy' % VERSION), pair); np.save(W('%s_single.npy' % VERSION), single)
jdump(dict(version=VERSION, frames=stamps, reference=REF_STAMP, kappa=KAPPA, dark_region_percentile=DARK_Q, constants={s: CONST[i].tolist() for i, s in enumerate(stamps)},
           subsets={k: [stamps[i] for i in v] for k, v in SUB.items()}, pair=[stamps[iref], stamps[iref + 1]], planes=info), 'step8_%s.json' % VERSION)
