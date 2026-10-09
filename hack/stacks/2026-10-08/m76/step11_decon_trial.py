"""Step 11 (a trial, judged before anything is delivered): Wiener restoration of the north-up stack with a blur
measured from stars in the same stack, the gain capped. Per colour: the blur is the mean of the isolated,
unsaturated stars of step 9's kind on the north-up grid (each cut out 41 x 41 px, its local sky ring removed, moved
onto the pixel centre by its measured sub-pixel offset (cubic spline: the kernel only, not the picture), scaled to
unit flux inside 16 px). Restoration: G = conj(H) / (|H|^2 + K), |G| capped at CAP, on the crop padded by reflection.
Then the same stretch and finish as the plain picture (step 10). Two caps are tried, 1.5 and 2.5. Written to the work
folder only (m76-wiener-cap*-finished.png); not delivered: see the verdict in recipe.json."""
import json, os, subprocess, sys
import numpy as np, cv2
from scipy import ndimage
from common import *
from render import lum_chroma_stretch
from step3_stars import measure
import step10_finish as s10m          # reuses its sky-corrected, cropped stack (C), sky mask and parameters

CAPS = [1.5, 2.5]; K = 1e-3
S, C, SKY, x0, y0 = s10m.S, s10m.C, s10m.SKY, s10m.x0, s10m.y0
hh, ww = S.shape[:2]; cx, cy = s10m.cx, s10m.cy
yy, xx = np.mgrid[0:hh, 0:ww]; rr = np.hypot(xx - cx, yy - cy)
G = S[:, :, 1]
sm = cv2.GaussianBlur(G, (0, 0), 2.0); m0, s0, _ = clipped_stats(sm[rr > 260])
nl, lab, stats, cent = cv2.connectedComponentsWithStats(((sm - m0) > 4 * s0).astype(np.uint8))
cxs, cys = cent[1:, 0], cent[1:, 1]
R_ = 20; yk, xk = np.mgrid[-R_:R_ + 1, -R_:R_ + 1]; rk = np.hypot(xk, yk)
cuts = [[], [], []]; used = []
for i in range(1, nl):
    x, y = cent[i]
    if rr[int(y), int(x)] < 150 or x < 30 or y < 30 or x > ww - 31 or y > hh - 31: continue
    if np.sort(np.hypot(cxs - x, cys - y))[1] < 30: continue
    a = measure(G, x, y)
    if a is None or a['flux'] < 8000 or a['peak'] > 6000: continue
    xi, yi = int(round(a['x'])), int(round(a['y']))
    for k in range(3):
        t = S[yi - R_:yi + R_ + 1, xi - R_:xi + R_ + 1, k].astype(np.float64)
        t = t - np.median(t[(rk > 16) & (rk <= 20)])
        t = ndimage.shift(t, (yi - a['y'], xi - a['x']), order=3, mode='nearest')
        t = t * (rk <= 16); cuts[k].append(t / t.sum())
    used.append([a['x'], a['y'], a['flux']])
psf = [np.clip(np.mean(c, 0), 0, None) for c in cuts]; psf = [p / p.sum() for p in psf]
print('blur from %d stars' % len(used))

def hfd_of(p):
    o = np.argsort(rk.ravel()); cum = np.cumsum(p.ravel()[o]); return 2 * rk.ravel()[o][np.searchsorted(cum, 0.5 * cum[-1])]
print('blur half-flux diameter px (R, G, B):', [round(hfd_of(p), 2) for p in psf])

def wiener(img, p, cap, k):
    pad = 64; a = np.pad(img.astype(np.float64), pad, mode='reflect'); H_, W_ = a.shape
    kern = np.zeros((H_, W_)); kern[:p.shape[0], :p.shape[1]] = p; kern = np.roll(kern, (-(p.shape[0] // 2), -(p.shape[1] // 2)), (0, 1))
    Hf = np.fft.rfft2(kern); Gf = np.conj(Hf) / (np.abs(Hf) ** 2 + k)
    mag = np.abs(Gf); Gf = Gf * np.minimum(1.0, cap / np.maximum(mag, 1e-12))
    out = np.fft.irfft2(np.fft.rfft2(a) * Gf, s=a.shape)
    return out[pad:-pad, pad:-pad].astype(np.float32)

# checks on the crop: star width, dark rings round stars, sky noise
yc, xc = np.mgrid[0:C.shape[0], 0:C.shape[1]]
skyc = SKY[y0:y0 + C.shape[0], x0:x0 + C.shape[1]]
def ring_check(img):
    out = []
    for x, y, f in used:
        x -= x0; y -= y0
        if not (25 < x < C.shape[1] - 25 and 25 < y < C.shape[0] - 25): continue
        a = measure(img[:, :, 1], x, y)
        if a is None: continue
        r = np.hypot(xc - a['x'], yc - a['y'])
        prof = [float(img[:, :, 1][(r >= q) & (r < q + 1)].mean()) for q in range(0, 16)]
        out.append(dict(hfd=2 * a['hfr'], peak=a['peak'], deepest=min(prof[3:]) / max(prof[0], 1e-9)))
    return out
results = []
for CAP in CAPS:
    D = np.dstack([wiener(C[:, :, k], psf[k], CAP, K) for k in range(3)])
    pl, dc = ring_check(C), ring_check(D)
    noise_p = clipped_stats(C[:, :, 1][skyc])[1]; noise_d = clipped_stats(D[:, :, 1][skyc])[1]
    res = dict(cap=CAP, k=K, stars_in_blur=len(used), blur_hfd_px=[float(hfd_of(p)) for p in psf],
               plain=dict(star_hfd_px=float(np.median([o['hfd'] for o in pl])), deepest_ring_fraction_of_peak=float(np.median([o['deepest'] for o in pl])), sky_noise_green=noise_p),
               wiener=dict(star_hfd_px=float(np.median([o['hfd'] for o in dc])), deepest_ring_fraction_of_peak=float(np.median([o['deepest'] for o in dc])), worst_ring=float(min(o['deepest'] for o in dc)), sky_noise_green=noise_d),
               stars_checked_in_crop=len(dc))
    print(json.dumps(res, indent=1))
    img16 = lum_chroma_stretch(D, sky_sigma_cs=s10m.sky_sigma_cs * noise_d / noise_p, bits=16, **s10m.STRETCH)
    cv2.imwrite(W('m76-wiener-cap%.1f-stretched.png' % CAP), img16[:, :, ::-1])
    r = subprocess.run([sys.executable, os.path.join(SCR, 'finish16.py'), W('m76-wiener-cap%.1f-stretched.png' % CAP), W('m76-wiener-cap%.1f-finished' % CAP)] + s10m.FINISH, capture_output=True, text=True, check=True); print(r.stdout.strip())
    results.append(res)
json.dump(dict(trials=results, delivered=False), open(W('step11_decon.json'), 'w'), indent=1)
