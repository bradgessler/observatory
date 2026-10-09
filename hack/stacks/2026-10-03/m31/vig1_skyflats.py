"""Vignetting, part 1: sky flats from the two runs tonight that have real empty sky.
M15 (23 x 15 s ISO 1600, 0720-0733 UTC, just before the M31 run, same focus): sky outside 1250 px (8.1 arcmin)
of the cluster. NGC 7662 (25 x 6 s ISO 1600, 0633-0643, before the refocus): sky everywhere but 260 px round
the nebula and its bright star; its sky is only 16 DN, so it is a check, not the source.
Per run and per colour plane: each frame (hot pixels repaired, black subtracted, sky level put back) divided by
its own sky level, median over the frames WITHOUT registration (stars drift and drop out), then medians of
16 x 16 plane-px blocks where at least half the block is unmasked sky. Written as block tables for part 2."""
import json, os, sys, numpy as np, cv2
from common import *
SP = os.path.dirname(os.path.dirname(WORK))            # the scratchpad that holds the earlier runs' work folders
BS = 16
def blocks(F, mask):
    h, w = F.shape; ny, nx = h // BS, w // BS
    Fb = np.where(mask, F, np.nan)[:ny * BS, :nx * BS].reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(Fb).sum(2); v = np.nanmedian(Fb, axis=2)
    v[n < BS * BS // 2] = np.nan
    return v

out = {}
# ---------------- M15 ----------------
wk = os.path.join(SP, 'm15', 'sharp')
s1 = json.load(open(os.path.join(wk, 'step1.json')))['frames']; use = open(os.path.join(wk, 'use.txt')).read().split()
fr = [f for f in s1 if f['stamp'] in use]
h, w = 2012, 3012; yy, xx = np.mgrid[0:h, 0:w]
mask = np.ones((h, w), bool)
for f in fr:
    c = f['cluster_sensor_xy']; b = f['bright_star_sensor_xy']
    mask &= np.hypot(2 * xx + 0.5 - c[0], 2 * yy + 0.5 - c[1]) > 1250
    mask &= np.hypot(2 * xx + 0.5 - b[0], 2 * yy + 0.5 - b[1]) > 300
div = np.load(os.path.join(wk, 'dustdiv.npy')); dust = cv2.dilate((div < 1).astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)
bar = np.zeros((h, w), bool); bar[20:340, 1750:2210] = True
mask_m15 = mask & ~dust & ~bar
print('M15: %d frames, sky mask %.1f%% of the plane' % (len(fr), 100 * mask_m15.mean()))
cube = [np.load(os.path.join(wk, 'planes', f['stamp'] + '.npy'), mmap_mode='r') for f in fr]
for p in range(4):
    N = np.stack([(np.asarray(c[p]) + f['bg'][p]['clipped_mean']) / f['bg'][p]['clipped_mean'] for c, f in zip(cube, fr)])
    F = np.median(N, axis=0); del N
    out['m15_' + PLANE_NAMES[p]] = blocks(F, mask_m15)
    out['m15_sky_' + PLANE_NAMES[p]] = np.array(float(np.median([f['bg'][p]['clipped_mean'] for f in fr])))
    print('  M15', PLANE_NAMES[p], 'sky %.1f DN' % out['m15_sky_' + PLANE_NAMES[p]], 'blocks', int(np.isfinite(out['m15_' + PLANE_NAMES[p]]).sum()), flush=True)
del cube
# ---------------- NGC 7662 ----------------
wk = os.path.join(SP, 'ngc7662')
s1 = json.load(open(os.path.join(wk, 'step1.json')))['frames']
tr = {o['stamp']: o for o in json.load(open(os.path.join(wk, 'step3_transforms.json')))} if os.path.exists(os.path.join(wk, 'step3_transforms.json')) else {}
mask = np.ones((h, w), bool)
NEB, STAR = (3466.0, 2270.0), (2316.0, 2812.0)
for c in (NEB, STAR): mask &= np.hypot(2 * xx + 0.5 - c[0], 2 * yy + 0.5 - c[1]) > 500      # 260 px plus the drift over the run
mask_ngc = mask & ~dust
cube = [np.load(os.path.join(wk, 'planes', f['stamp'] + '.npy'), mmap_mode='r') for f in s1]
print('NGC 7662: %d frames' % len(s1))
for p in range(4):
    # the sky is only 16 DN in green and about 1 DN in red: normalise by the run's level, not each frame's
    lev = float(np.median([f['bg'][p]['clipped_mean'] for f in s1]))
    N = np.stack([np.asarray(c[p]) + f['bg'][p]['clipped_mean'] for c, f in zip(cube, s1)])
    # clipped mean over frames (the values step in 4 DN and the sky is 16 DN: a median would be quantised)
    med = np.median(N, axis=0); sd = 1.4826 * np.median(np.abs(N - med), axis=0) + 4.0
    keep = np.abs(N - med) < 3 * sd
    F = (N * keep).sum(0) / np.maximum(keep.sum(0), 1) / lev; del N, keep
    out['ngc_' + PLANE_NAMES[p]] = blocks(F, mask_ngc)
    out['ngc_sky_' + PLANE_NAMES[p]] = np.array(lev)
    print('  NGC', PLANE_NAMES[p], 'sky %.2f DN' % lev, 'blocks', int(np.isfinite(out['ngc_' + PLANE_NAMES[p]]).sum()), flush=True)
np.savez(W('vig_skyflats.npz'), bs=BS, **out)
