"""Step 9b: the Trapezium region from the SHORT frames alone, at the sensor's own scale (0.388 arcsec per pixel).

A square of CORE_PX sensor pixels (about 6 arcmin) centred on the Trapezium, on the sensor grid of the deep
set's reference frame. Each of the 16 two-second frames, per colour plane: black-subtracted, hot pixels repaired,
/ flat, x 1 / transparency, minus the frame's constant (step 7), resampled onto the full sensor grid (rotation +
shift + the plane's place in the 2x2 colour cell; Lanczos-4). A colour plane has one sample per 2x2 sensor pixels;
bringing it to the sensor grid is an interpolation of measured samples, and with 16 frames that each fell
differently on the pixel grid the in-between pixels are filled by measurement rather than by one frame's guess.
The stars in a 2 s frame are 3.8 arcsec across (10 sensor px), so the planes are well sampled and nothing is
invented. Combine as in step 7 (3-sigma about the median, then the weighted mean).

The pixels that were near the ceiling in any plane of any short frame are carried along (white mark)."""
import json
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2
from common import *
import prep
import s7_stack as S7

CORE_PX = 960
s1 = prep.s1()
SEL = S7.SEL['short']; USE = SEL['used']; stamps = [u['stamp'] for u in USE]
tr = {o['stamp']: o for o in S7.T4['short']['transforms']}
s7 = json.load(open(W('s7_short.json')))
# the centre: the brightest of the Trapezium stars in the short stack (half grid) -> sensor px
Sh = np.load(W('short_planes.npy')); G = (Sh[1] + Sh[2]) / 2
cxy = prep.s1()[S7.T4['deep']['reference']]['core_sensor_xy']
hx, hy = int(cxy[0] / 2), int(cxy[1] / 2)
box = cv2.GaussianBlur(np.nan_to_num(G[hy - 150:hy + 150, hx - 150:hx + 150]), (0, 0), 6)
yy, xx = np.unravel_index(np.argmax(box), box.shape)
cx, cy = 2 * (hx - 150 + xx) + 0.5, 2 * (hy - 150 + yy) + 0.5
x0, y0 = int(round(cx - CORE_PX / 2)), int(round(cy - CORE_PX / 2))
print('core crop: sensor px x %d..%d, y %d..%d of the reference frame (centre %.0f, %.0f)' % (x0, x0 + CORE_PX, y0, y0 + CORE_PX, cx, cy))
YY, XX = np.mgrid[y0:y0 + CORE_PX, x0:x0 + CORE_PX].astype(np.float32)
loaded = {s: prep.load_repaired(s, masks=True) for s in stamps}
wts = np.array([u['weight'] for u in USE], np.float32); nfac = np.array([u['noise_rel'] for u in USE], np.float32)
iref = stamps.index(SEL['background_reference'])
out = np.zeros((4, CORE_PX, CORE_PX), np.float32); nuse = np.zeros((CORE_PX, CORE_PX), np.uint8)
near = np.zeros((CORE_PX, CORE_PX), np.uint8)
K3 = np.ones((3, 3), np.uint8)
for p in range(4):
    ox, oy = OFFS[p]; cube = []
    for s in stamps:
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t'])
        fx = R[0, 0] * XX + R[0, 1] * YY + t[0]; fy = R[1, 0] * XX + R[1, 1] * YY + t[1]
        T = next(u['transparency'] for u in USE if u['stamp'] == s)
        c0 = 0.0 if s == SEL['background_reference'] else s7['surfaces_taken_off'][s][p]['constant']
        v = (loaded[s][0][p] / S7.FLAT[p] / np.float32(T)).astype(np.float32)
        w = cv2.remap(v, ((fx - ox) / 2).astype(np.float32), ((fy - oy) / 2).astype(np.float32), cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan')) - np.float32(c0)
        cube.append(w)
        if p == 0:
            nm = cv2.dilate(loaded[s][2].any(0).astype(np.uint8), K3).astype(np.float32)
            near += cv2.remap(nm, ((fx - 0.5) / 2).astype(np.float32), ((fy - 0.5) / 2).astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0) > 0.02
    cube = np.stack(cube); valid = np.isfinite(cube)
    dk = s1[SEL['background_reference']]['dark_block']
    floor = np.float32(0.4 * dk['clipped_std'][p]); n0 = np.float32(dk['clipped_std'][p]); L0 = np.float32(max(dk['clipped_mean'][p], 1.0))
    lev = np.maximum(np.nanmedian(cube, axis=0), L0)
    sig1 = n0 * nfac[:, None, None] * np.sqrt(lev / L0)[None]
    o = S7.combine(cube, valid, wts, nfac, floor, sig1, None)
    out[p] = o['mean']
    if p == 1: nuse = o['used']
np.save(W('core_planes.npy'), out); np.save(W('core_near.npy'), near); np.save(W('core_n.npy'), nuse)
json.dump(dict(crop_sensor_px=[x0, y0, x0 + CORE_PX, y0 + CORE_PX], centre_sensor_px=[cx, cy], size_px=CORE_PX, scale_arcsec_per_px=SCALE, field_arcmin=CORE_PX * SCALE / 60, frames=stamps,
               frames_used_per_pixel=dict(min=int(nuse.min()), median=int(np.median(nuse)), max=int(nuse.max())), pixels_near_ceiling_in_any_frame=int((near > 0).sum())), open(W('s9b_core.json'), 'w'), indent=1)
print('core: frames per pixel min %d median %d; near ceiling in any frame %d px' % (nuse.min(), np.median(nuse), (near > 0).sum()))
