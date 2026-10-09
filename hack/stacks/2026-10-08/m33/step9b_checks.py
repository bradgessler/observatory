"""Step 9b: checks behind the recipe's words (nothing here changes a picture).

  1. dust: the stack's green around each corrected dust shadow (where the shadow fell in the reference grid for the
     median frame), median in 8 px rings out to 80 px, minus the outermost ring: what is left of the shadow.
  2. colour of the faint glow: green, R/G and B/G (camera RGB, daylight balance) in rings around the nucleus, as stacked
     (one green vignetting profile for all colours) and as it would be with each colour's own profile (joint fit, or
     each flat run alone): the sky (the frame-averaged constant) is put back, the profile ratio applied, the faint
     region re-zeroed. How much the faint glow's colour depends on the flat.
  3. the sky constants: how far they jump from frame to frame, per plane."""
import json
import numpy as np, cv2
from common import *

s5 = jload('step5_select.json'); s6 = jload('step6_vignette.json'); s7 = jload('step7_stack.json'); s8 = jload('step8_solve.json')
tr = {o['stamp']: o for o in jload('step3_transforms.json')['transforms']}
used = [u['stamp'] for u in s5['used']]; wts = np.array([u['weight'] for u in s5['used']])
st = np.load(W('stack_mean.npy')); faint = np.load(W('faint_region.npy'))
G = 0.5 * (st[1] + st[2]); Gs = cv2.GaussianBlur(np.nan_to_num(G), (0, 0), 3)
out = dict(dust=[], colour={}, constants={})
for d in s6['dust']['shadows']:
    S = np.array([2 * d['plane_px'][0] + 0.5, 2 * d['plane_px'][1] + 0.5]); pos = []
    for s in used:
        R = np.array(tr[s]['R']); t = np.array(tr[s]['t']); q = np.linalg.solve(R, S - t); pos.append(((q[0] - 0.5) / 2, (q[1] - 0.5) / 2))
    c = np.median(np.array(pos), 0); x, y = int(round(c[0])), int(round(c[1]))
    x = min(max(x, 80), w2 - 81); y = min(max(y, 80), h2 - 81)
    yy, xx = np.mgrid[y - 80:y + 81, x - 80:x + 81]; rr = np.hypot(xx - c[0], yy - c[1]); t_ = Gs[y - 80:y + 81, x - 80:x + 81]
    prof = np.array([np.median(t_[(rr >= a) & (rr < a + 8)]) for a in range(0, 80, 8)])
    out['dust'].append(dict(plane_px=d['plane_px'], depth_divided_out=d['depth'], picture_px=[round(float(c[0] - s8['crop_on_reference_grid']['x0']), 1), round(float(c[1] - s8['crop_on_reference_grid']['y0']), 1)],
                            left_in_stack_green_dn_rings_0_to_80px=[round(float(v), 2) for v in prof - prof[-1]], centre_left_dn=round(float(prof[:2].mean() - prof[-1]), 2)))
    print('dust', d['plane_px'], 'depth %.3f' % d['depth'], 'left in the stack (DN, rings of 8 px):', ' '.join('%+.1f' % v for v in prof - prof[-1]))
# 2. colour of the glow against the flat's colour
def radial(cf, rho): return 1 + cf[0] * rho ** 2 + cf[1] * rho ** 4 + cf[2] * rho ** 6
Y, X = np.mgrid[0:h2, 0:w2]; rho = np.hypot(2 * X + 0.5 - CENTRE[0], 2 * Y + 0.5 - CENTRE[1]) / 3000
VG = 0.5 * (radial(s6['planes']['G1']['radial_a2_a4_a6'], rho) + radial(s6['planes']['G2']['radial_a2_a4_a6'], rho))
Cm = np.array([s7['constants'][s] for s in s7['frames']]); cbar = (Cm * wts[:, None]).sum(0) / wts.sum()
nx_, ny_ = s8['catalogue']['M33 nucleus']['pixel']; nx_ += s8['crop_on_reference_grid']['x0']; ny_ += s8['crop_on_reference_grid']['y0']
rr = np.hypot(X - nx_, Y - ny_)
rings = ((5, 20), (20, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, 1500))
wb = [2.8993, 1.0, 1.3482]
for label, src in (('as stacked: one green profile', None), ('each colour its own profile (joint fit)', 'joint'), ('each colour its own profile (NGC 1514 run)', 'ngc1514'), ('each colour its own profile (M57 run)', 'm57')):
    ch = []
    for p, nm in ((0, 'R'), (3, 'B')):
        a = st[p].copy()
        if src:
            cf = s6['planes'][nm]['radial_a2_a4_a6'] if src == 'joint' else s6['planes'][nm]['each_run_alone_a2_a4_a6'][src]
            a = (a + cbar[p]) * VG / radial(cf, rho); a -= np.nanmean(a[faint])
        ch.append(a)
    row = []
    for lo, hi in rings:
        m = (rr >= lo) & (rr < hi) & np.isfinite(G); g = float(np.median(G[m]))
        row.append(dict(r_arcmin=[round(lo * 0.776 / 60, 2), round(hi * 0.776 / 60, 2)], green_dn=round(g, 2), R_over_G=round(float(np.median(ch[0][m]) * wb[0] / g), 3), B_over_G=round(float(np.median(ch[1][m]) * wb[2] / g), 3)))
    out['colour'][label] = row
    print('%-45s' % label, ' | '.join('%.1f-%.1f\' R/G %.2f B/G %.2f' % (*r['r_arcmin'], r['R_over_G'], r['B_over_G']) for r in row))
# 3. constants
for i, p in enumerate(PLANE_NAMES):
    v = Cm[:, i]; out['constants'][p] = dict(range=[round(float(v.min()), 2), round(float(v.max()), 2)], spread=round(float(v.max() - v.min()), 2), largest_step=round(float(np.abs(np.diff(v)).max()), 2))
d12 = Cm[:, 1] - Cm[:, 2]; out['constants']['G1_minus_G2'] = dict(range=[round(float(d12.min()), 2), round(float(d12.max()), 2)])
print('constants', out['constants'])
jdump(out, 'step9b_checks.json')
