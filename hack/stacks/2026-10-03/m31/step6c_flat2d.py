"""Step 6c (for the extra version C only): the smooth part of the cloud-glow flat in two dimensions, per colour
plane. The radial profile of step 6a leaves in the frames what the cloud-glow flat also shows: a tilt of about
4% across the frame, and strips at the top and bottom edge that are 1 to 4% dark and differ between the two
row pairs of the colour cell (R/G1 rows against G2/B rows). Version C divides by all of the smooth flat instead
of only its radial part. This goes beyond what was asked for (radial, centred only) and is delivered as an
extra, named as such.

Per plane: flat / (radial profile of its colour x fitted tilt) = the part that is not radial. Medians of 16 px
blocks; blocks under a dust shadow or in the zone near the nucleus where the flat is blind are filled by a
normalised Gaussian (sigma 2.5 blocks = 80 sensor px, widened to 8 blocks where there is no support); the same
Gaussian smooths the rest. Grown back to the plane grid (bicubic) and multiplied by radial x tilt.
Dust shadows are NOT in this flat: they are left out of the average as in version B."""
import json, numpy as np, cv2
from common import *
BS = 16
flat = np.load(W('cloudflat.npy')); vig = json.load(open(W('vignette.json'))); rg = np.array(vig['r_px']); dust = np.load(W('dustmask.npy'))
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
h, w = flat.shape[1:]; yy, xx = np.mgrid[0:h, 0:w]
blind = np.zeros((h, w), bool)
for fr in vig['frames']:
    nuc = s1[fr['clear']]['nucleus_sensor_xy']; blind |= np.hypot(2 * xx + 0.5 - nuc[0], 2 * yy + 0.5 - nuc[1]) < 480      # 400 px blind zone plus a margin
bad = dust | blind
out = np.zeros((4, h, w), np.float32); rep = []
ny, nx = -(-h // BS), -(-w // BS)
for p in range(4):
    c = 'RGGB'[p]; r = radius_plane(p); V = np.interp(r, rg, np.array(vig['V'][c])); t = vig['tilt_not_applied_per_3000px'][c]
    ox, oy = OFFS[p]
    model = (V * (1 + t[0] * (2 * xx + ox - CENTRE[0]) / 3000 + t[1] * (2 * yy + oy - CENTRE[1]) / 3000)).astype(np.float32)
    res = np.where(bad, np.nan, flat[p] / model)
    pad = np.full((ny * BS, nx * BS), np.nan, np.float32); pad[:h, :w] = res
    blk = pad.reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
    with np.errstate(all='ignore'):
        n = np.isfinite(blk).sum(2); b = np.nanmedian(blk, axis=2)
    ok = (n >= BS * BS // 4) & np.isfinite(b)
    norm = float(np.median(b[ok])); b = b / norm
    def nconv(sig):
        num = cv2.GaussianBlur(np.where(ok, b, 0).astype(np.float32), (0, 0), sig, borderType=cv2.BORDER_REPLICATE); den = cv2.GaussianBlur(ok.astype(np.float32), (0, 0), sig, borderType=cv2.BORDER_REPLICATE)
        return num / np.maximum(den, 1e-6), den
    s1_, d1 = nconv(2.5); s2_, d2 = nconv(8.0)
    wgt = np.clip((d1 - 0.15) / 0.25, 0, 1)                       # where the narrow Gaussian has little support, lean on the wide one
    sm = s1_ * wgt + s2_ * (1 - wgt)
    # block centres -> plane pixels
    mapx = ((xx + 0.5) / BS - 0.5).astype(np.float32); mapy = ((yy + 0.5) / BS - 0.5).astype(np.float32)
    full = cv2.remap(sm.astype(np.float32), mapx, mapy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    out[p] = full * model
    out[p] /= np.float32(np.median(out[p][h // 2 - 50:h // 2 + 50, w // 2 - 50:w // 2 + 50]))       # 1 at the sensor centre, like the radial profile
    rep.append(dict(plane=PLANE_NAMES[p], non_radial_part_min=float(full.min()), non_radial_part_max=float(full.max()), flat_min=float(out[p].min()), flat_max=float(out[p].max()),
                    blocks_measured=int(ok.sum()), blocks_filled=int((~ok).sum())))
    print(rep[-1])
np.save(W('flat2d.npy'), out)
json.dump(dict(block_px=BS, sigma_blocks=2.5, sigma_wide_blocks=8.0, planes=rep), open(W('flat2d.json'), 'w'), indent=1)
v = np.clip((out[1] / np.interp(radius_plane(1), rg, np.array(vig['V']['G'])) - 0.93) / 0.14, 0, 1)
cv2.imwrite(W('v_flat2d_nonradial_G1.png'), (cv2.resize(v, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA) * 255).astype(np.uint8))
