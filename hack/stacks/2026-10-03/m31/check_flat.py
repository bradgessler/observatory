"""Check of the vignetting profile inside the M31 data itself, with no assumption about the galaxy:
the first third and the last third of the used frames see the same sky through different parts of the optics
(the field sits about 170 px away and is turned 2.3 degrees). If the frames are flat, first-third stack minus
last-third stack is zero everywhere; uncorrected vignetting leaves a slope across the field.
Green, medians of 256 px blocks, well-covered area only."""
import json, numpy as np
from common import *
np.set_printoptions(linewidth=250, precision=1, suppress=True)
out = {}
for ver in ('A', 'B', 'C'):
    e = np.load(W('%s_early.npy' % ver))[1:3].mean(0); l = np.load(W('%s_late.npy' % ver))[1:3].mean(0); m = np.load(W('%s_mean.npy' % ver))[1:3].mean(0)
    cover = np.load(W('%s_cover.npy' % ver)); bs = 256
    d = np.where(cover >= len(json.load(open(W('step8_%s.json' % ver)))['frames']), e - l, np.nan)
    ny, nx = H // bs, Wd // bs
    with np.errstate(all='ignore'):
        b = np.nanmedian(d[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
        lev = np.nanmedian(m[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    Y, X = np.mgrid[0:ny, 0:nx]; ok = np.isfinite(b) & (lev < 400)      # leave the bulge out: small scale errors there are not about the flat
    A = np.column_stack([np.ones(ok.sum()), (X[ok] - (nx - 1) / 2) * bs / 3000, (Y[ok] - (ny - 1) / 2) * bs / 3000])
    co, *_ = np.linalg.lstsq(A, b[ok], rcond=None); res = b[ok] - A @ co
    print('version %s: first third minus last third, green DN, 256 px blocks:' % ver); print(b)
    print('   blocks %d: rms %.2f DN, min %.2f max %.2f; best straight slope %.2f DN per 3000 px in x, %.2f in y; rms after the slope %.2f; level of these blocks %.0f..%.0f DN' % (ok.sum(), np.sqrt((b[ok] ** 2).mean()), b[ok].min(), b[ok].max(), co[1], co[2], np.sqrt((res ** 2).mean()), lev[ok].min(), lev[ok].max()))
    out[ver] = dict(blocks=int(ok.sum()), rms_dn=float(np.sqrt((b[ok] ** 2).mean())), min_dn=float(b[ok].min()), max_dn=float(b[ok].max()), slope_x_dn_per_3000px=float(co[1]), slope_y_dn_per_3000px=float(co[2]), rms_after_slope_dn=float(np.sqrt((res ** 2).mean())))
json.dump(out, open(W('check_flat.json'), 'w'), indent=1)
