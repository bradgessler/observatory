import json, os, sys, numpy as np, cv2
from common import *
from render import *
from decon import *
fl = np.load('stack_flat.npy'); s1j = json.load(open('step1.json')); C = json.load(open('centres.json'))
wb = np.median(np.array([f['wb'] for f in s1j['frames']]), axis=0); wb_r, wb_b = wb[0] / wb[1], wb[2] / wb[1]
chans = [fl[0], (fl[1] + fl[2]) / 2, fl[3]]
c = C['neb']; cx, cy = int(round(c[0])), int(round(c[1]))
Wc, Hc = 774, 516
PED = 100.0
def crop(a, cx, cy, w, h): return a[cy - h // 2:cy + h // 2, cx - w // 2:cx + w // 2]
psfs = {k: [psf_from_star(ch, C[k])[0] for ch in chans] for k in ('star', 's1', 's3')}
np.save('psf_star.npy', np.array(psfs['star']))
out = {}
for rounds in (5, 10, 20, 40):
    dec = [richardson_lucy(crop(ch, cx, cy, Wc, Hc), psfs['star'][k], rounds, PED) for k, ch in enumerate(chans)]
    out[rounds] = dec
    np.save('decon_close_%d.npy' % rounds, np.array(dec))
plain = [crop(ch, cx, cy, Wc, Hc) for ch in chans]
def show(ch3, white, soft, ped=8):
    rgb = np.dstack([ch3[0] * wb_r, ch3[1], ch3[2] * wb_b])
    return asinh_stretch(rgb, white, soft, ped)[:, :, ::-1]
sub = (slice(Hc // 2 - 90, Hc // 2 + 90), slice(Wc // 2 - 190, Wc // 2 + 110))
tiles = [show(plain, 1400, 420)[sub]] + [show(out[r], max(1400, 1.05 * (out[r][2][sub] * wb_b).max()), 0.3 * max(1400, 1.05 * (out[r][2][sub] * wb_b).max()))[sub] for r in (5, 10, 20, 40)]
cv2.imwrite('v_decon.png', np.vstack([np.hstack([cv2.resize(t, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC) for t in tiles[:3]]), np.hstack([cv2.resize(t, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC) for t in tiles[2:5]])]))
# G channel, linear grey, each normalised to its own max
g = [plain[1][sub]] + [out[r][1][sub] for r in (5, 10, 20, 40)]
cv2.imwrite('v_decon_g.png', np.hstack([cv2.resize((np.clip(t / t.max(), 0, 1) * 255).astype(np.uint8), None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC) for t in [g[0], g[2], g[3]]]))
for r in (5, 10, 20, 40):
    d = out[r][1]; print('rounds', r, 'G max', d.max(), 'min', d.min(), 'sum ratio', d.sum() / plain[1].sum(), 'sky std', clipped_stats(d[:120])[1], 'plain', clipped_stats(plain[1][:120])[1])
# cross test: the bright star deconvolved with star s1's blur and with its own; s1 with the bright star's
for nm, target, pk in (('star_with_s1psf', 'star', 's1'), ('s1_with_starpsf', 's1', 'star'), ('s3_with_starpsf', 's3', 'star'), ('star_with_s3psf', 'star', 's3')):
    tc = C[target]; tx, ty = int(round(tc[0])), int(round(tc[1]))
    t = crop(chans[1], tx, ty, 200, 200)
    row = [t] + [richardson_lucy(t, psfs[pk][1], r, PED) for r in (10, 40)]
    cv2.imwrite('v_x_%s.png' % nm, np.hstack([cv2.resize((np.clip(a[60:140, 60:140] / a.max(), 0, 1) ** 0.5 * 255).astype(np.uint8), None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC) for a in row]))
