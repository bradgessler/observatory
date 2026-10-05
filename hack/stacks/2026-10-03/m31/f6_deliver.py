"""Rerun step f6: the main picture again from the stack made with the twilight-based flat (version F), with the
core run's colour, crop, zero rule and stretch (step10_deliver.py), and the numbers for the recipe.
Written:  m31-core.png / .jpg, m31-core-dust.png / .jpg, m31-core-linear.tif, m31-core-coverage.tif,
          m31-core-sensor-dust-map.png.
NOT written again (they do not depend on the flat that was added, and stay as the core run made them):
          m31-core-as-recorded.* (A) and the m31-core-cloudflat* files (C).

The diagnostic map (m31-core-sensor-dust-map.png) now shows the only sensor shadows still in the picture: the hair
(left out frame by frame; where fewer than 12 frames are clear of it the combine with it left in is blended in, as
the core run did for dust) and the few places where the dawn flat is not this hour's response (step f3). Per used
frame: the hair's transmission as measured in that frame and its neighbours (step f2) inside that frame's hair mask,
and 1 - |mismatch - 1| inside the f3 mask (a place the flat brightens falsely is marked like a shadow of the same
size), 1 elsewhere; carried onto the picture grid, weighted mean = what a combine with those samples left in holds;
x (1 - blend weight) = what the finished picture holds. Nothing is divided by it.

Usage: f6_deliver.py [dry]"""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor
import numpy as np, cv2, tifffile
from PIL import Image
from common import *
from final import *
from render import *
import measure

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry_F') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
OLD = os.environ.get('M31_OLD_WORK')
STRETCH = dict(white=14000.0, soft=45.0, pedestal=4.0); CHROMA_SIGMA_SENSOR_PX = 4.0; DUST_CROP = (2500, 1650, 4900, 3250)
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
T4 = json.load(open(W('step4_transforms.json'))); tr = {o['stamp']: o for o in T4['transforms']}
Q = json.load(open(W('step5_quality.json')))
sel = json.load(open(W('step7_select.json'))); USE = sel['used']; USED = [u['stamp'] for u in USE]; n_used = len(USED)
s10 = json.load(open(W('step10.json'))); wb_r, wb_b = s10['wb']['as_shot']['R'], s10['wb']['as_shot']['B']
h2, w2 = H // 2, Wd // 2
rect = cover_rect('F', n_used); x0, y0, x1, y1 = rect
assert list(rect) == list(s10['rect']), (rect, s10['rect'])          # the same grid as the core run's files
used = np.load(W('F_used.npy'))[1]
clean = used[y0:y1, x0:x1] >= CLEAN_MIN; notedge = not_edge_mask(rect)

# ---------------- what is left of the hair and of the flat's mismatches ----------------
hz = np.load(W('f2_hair.npz')); hj = json.load(open(W('f2_hair.json'))); wx0, wy0, wx1, wy1 = hj['trans_window_plane']
MIS = np.load(W('f3_mismatch.npy')); LO = np.load(W('f3_leaveout.npy'))
gy, gx = np.mgrid[0:H, 0:Wd].astype(np.float32)
def one(u):
    s = u['stamp']; D = np.where(LO, 1.0 - np.abs(MIS - 1.0), 1.0).astype(np.float32)
    D[wy0:wy1, wx0:wx1] = np.minimum(D[wy0:wy1, wx0:wx1], hz['t_' + s].astype(np.float32))
    R = np.array(tr[s]['R']); t = np.array(tr[s]['t'])
    fx = (R[0, 0] * gx + R[0, 1] * gy + t[0]).astype(np.float32); fy = (R[1, 0] * gx + R[1, 1] * gy + t[1]).astype(np.float32)
    return cv2.remap(D, (fx - 0.5) / 2, (fy - 0.5) / 2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=float('nan')), u['weight']
num = np.zeros((H, Wd), np.float64); den = np.zeros((H, Wd), np.float64)
with ThreadPoolExecutor(6) as ex:
    for d, w in ex.map(one, USE):
        ok = np.isfinite(d); num += np.where(ok, d, 0) * w; den += ok * w
left_in = (num / np.maximum(den, 1e-9)).astype(np.float32); del num, den
wgt = np.clip((used.astype(np.float32) - BLEND_LO) / float(BLEND_HI - BLEND_LO), 0, 1)
pred = (1 - (1 - left_in) * (1 - wgt)).astype(np.float32)
np.save(W('F_pred.npy'), pred)
# check of the prediction against the stack: (left in - left out) / level where both exist and the prediction is deeper than 1%
m = np.load(W('F_mean.npy'))[1:3].mean(0); li = np.load(W('F_mean_dust_left_in.npy'))[1:3].mean(0)
ok = np.isfinite(m) & np.isfinite(li) & (used >= 12)
meas = cv2.GaussianBlur(np.where(ok, li - m, 0).astype(np.float32), (0, 0), 8) / np.maximum(cv2.GaussianBlur(np.where(ok, m, 1).astype(np.float32), (0, 0), 8), 1)
prd = cv2.GaussianBlur(left_in, (0, 0), 8) - 1
sel_ = ok & (prd < -0.01) & (cv2.GaussianBlur(ok.astype(np.float32), (0, 0), 8) > 0.95)
a = prd[sel_][::11]; b = meas[sel_][::11]; chk = dict(measured_over_predicted=float((a * b).sum() / (a * a).sum()), correlation=float(np.corrcoef(a, b)[0, 1]), pixels=int(sel_.sum()))
print('prediction of what a left-in combine holds, against the stack: measured = %.2f x predicted, correlation %.2f, %d px' % (chk['measured_over_predicted'], chk['correlation'], chk['pixels']))
p = pred[y0:y1, x0:x1]
n, lab, stats, cent = cv2.connectedComponentsWithStats((cv2.GaussianBlur(p, (0, 0), 4) < 0.985).astype(np.uint8), connectivity=8)
left = []
for i in range(1, n):
    if stats[i, 4] < 400: continue
    left.append(dict(centre_sensor_xy=[round(float(cent[i][0]) + x0), round(float(cent[i][1]) + y0)], centre_in_whole_field_picture_px=[round(float(cent[i][0]) / 2), round(float(cent[i][1]) / 2)], size_sensor_px=[int(stats[i, 2]), int(stats[i, 3])], area_sensor_px=int(stats[i, 4]), deepest_transmission=round(float(p[lab == i].min()), 3)))
left.sort(key=lambda d: d['deepest_transmission'])
for d in left: print('  still in the picture:', d)
nohole = int((used[y0:y1, x0:x1] < BLEND_LO).sum())
shadow = dict(check_against_stack=chk, shadows_left=left, pixels_with_fewer_than_4_clean_frames=nohole, pixels_with_fewer_than_12_clean_frames=int((used[y0:y1, x0:x1] < BLEND_HI).sum()),
              fraction_of_field_with_shadow_deeper_than=dict(p005=float((p < 0.995).mean()), p01=float((p < 0.99).mean()), p02=float((p < 0.98).mean()), p05=float((p < 0.95).mean())))

# ---------------- zero, pictures ----------------
c = np.load(W('F_final.npy'))[:, y0:y1, x0:x1].copy()
lev, dark, cen = zero_levels(c, clean, notedge); ys, xs = np.nonzero(dark)
planes = c - np.array(lev, np.float32)[:, None, None]
zinfo = dict(levels_subtracted_dn=dict(zip(PLANE_NAMES, [round(float(v), 2) for v in lev])), region_px=int(dark.sum()), region_bbox_sensor_px=[int(xs.min() + x0), int(ys.min() + y0), int(xs.max() + x0), int(ys.max() + y0)], region_centre_sensor_px=[round(float(np.median(xs)) + x0), round(float(np.median(ys)) + y0)])
print('F zero', zinfo, flush=True)
def save(img8, stem):
    im = Image.fromarray(img8, 'RGB'); im.save(os.path.join(DEST, stem + '.png'), optimize=True); im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)
def half(rgb): return cv2.resize(rgb, (rgb.shape[1] // 2, rgb.shape[0] // 2), interpolation=cv2.INTER_AREA)
outs = {}
rgb = rgb_from_planes(planes, wb_r, wb_b)
img = asinh_stretch(half(rgb), chroma_sigma=CHROMA_SIGMA_SENSOR_PX / 2, **STRETCH); save(img, 'm31-core')
outs['m31-core'] = dict(size_px=[img.shape[1], img.shape[0]], pixels_at_255_in_any_channel=int((img == 255).any(2).sum()), median_8bit=[int(v) for v in np.median(img.reshape(-1, 3)[::7], axis=0)])
cx0, cy0, cx1, cy1 = DUST_CROP
img = asinh_stretch(rgb[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0], chroma_sigma=CHROMA_SIGMA_SENSOR_PX, **STRETCH); save(img, 'm31-core-dust')
outs['m31-core-dust'] = dict(size_px=[img.shape[1], img.shape[0]], pixels_at_255_in_any_channel=int((img == 255).any(2).sum()))
tifffile.imwrite(os.path.join(DEST, 'm31-core-linear.tif'), rgb, photometric='rgb', compression='zlib', metadata=None)
tifffile.imwrite(os.path.join(DEST, 'm31-core-coverage.tif'), used[y0:y1, x0:x1], compression='zlib', metadata=None)
dm = cv2.resize(p, (p.shape[1] // 2, p.shape[0] // 2), interpolation=cv2.INTER_AREA)
Image.fromarray((np.clip((dm - 0.80) / 0.20, 0, 1) * 255 + 0.5).astype(np.uint8), 'L').save(os.path.join(DEST, 'm31-core-sensor-dust-map.png'), optimize=True)
print('files written to', DEST, flush=True)

# ---------------- numbers (as step 10) ----------------
G = np.ascontiguousarray(rgb[:, :, 1])
def cs(a): return clipped_stats(a)[1]
pair = np.load(W('F_pairdiff.npy')); odd = np.load(W('F_odd.npy')); even = np.load(W('F_even.npy')); hd = (odd - even) / 2
def to_rgb(a): return [a[0] * wb_r, (a[1] + a[2]) / 2, a[3] * wb_b]
def half2(a): return a[:a.shape[0] // 2 * 2, :a.shape[1] // 2 * 2].reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean((1, 3))
PATCH = (1020, 304)          # the core run's patch (sensor px, top-left), 500 x 500: the same place, so the numbers compare
Pfull = (slice(PATCH[1], PATCH[1] + 500), slice(PATCH[0], PATCH[0] + 500)); Pc = (slice(PATCH[1] - y0, PATCH[1] - y0 + 500), slice(PATCH[0] - x0, PATCH[0] - x0 + 500))
noise = dict(where='the core run\'s patch: sensor px x %d..%d, y %d..%d; %.0f%% of it has at least %d of %d frames; galaxy there %.1f DN (green) above the zero region' % (PATCH[0], PATCH[0] + 500, PATCH[1], PATCH[1] + 500, 100 * float((used[Pfull] >= n_used - 2).mean()), n_used - 2, n_used, float(np.median(G[Pc][::4, ::4]))),
             how='as the core run: 3-sigma clipped standard deviation; one frame = two neighbouring clear frames through the whole pipeline, difference / sqrt 2; stack = (odd - even) / 2; on the sensor grid and after 2 x 2 binning',
             sensor_grid=dict(one_frame_planes=dict(zip(PLANE_NAMES, [round(cs(pair[q][Pfull]), 2) for q in range(4)])), stack_planes=dict(zip(PLANE_NAMES, [round(cs(hd[q][Pfull]), 2) for q in range(4)])),
                              one_frame_white_balanced=dict(zip('RGB', [round(cs(v[Pfull]), 2) for v in to_rgb(pair)])), stack_white_balanced=dict(zip('RGB', [round(cs(v[Pfull]), 2) for v in to_rgb(hd)]))),
             binned_2x2=dict(one_frame_white_balanced=dict(zip('RGB', [round(cs(half2(v[Pfull])), 2) for v in to_rgb(pair)])), stack_white_balanced=dict(zip('RGB', [round(cs(half2(v[Pfull])), 2) for v in to_rgb(hd)]))),
             ideal_improvement_sqrt_of_summed_weights=round(float(np.sqrt(sum(u['weight'] for u in USE))), 2), plain_sqrt_of_frames=round(n_used ** 0.5, 2))
for k in ('sensor_grid', 'binned_2x2'):
    noise[k]['improvement'] = dict(zip('RGB', [round(noise[k]['one_frame_white_balanced'][c_] / noise[k]['stack_white_balanced'][c_], 2) for c_ in 'RGB']))
del pair, odd, even, hd
rows = []
for xy in Q['star_xy'].values():
    a = measure.star(G, xy[0] - x0, xy[1] - y0)
    if a and a['fwhm']: rows.append(a)
stars = dict(stars=len(rows), half_flux_diameter_arcsec=round(float(np.median([r['hfd'] for r in rows])) * SCALE, 2), fwhm_arcsec=round(float(np.median([r['fwhm'] for r in rows])) * SCALE, 2), fwhm_px=round(float(np.median([r['fwhm'] for r in rows])), 1), elongation=round(float(np.median([r['elong'] for r in rows])), 3))
def blocks(rgb_):
    b = 384; ny_, nx_ = rgb_.shape[0] // b, rgb_.shape[1] // b
    return np.median(rgb_[:ny_ * b, :nx_ * b].reshape(ny_, b, nx_, b, 3).transpose(0, 2, 1, 3, 4).reshape(ny_, nx_, -1, 3), axis=2)
b = blocks(rgb)
glow = dict(green_dn=[[round(float(v), 1) for v in row] for row in b[:, :, 1]], red_over_green=[[round(float(v), 2) if g_ > 6 else None for v, g_ in zip(r_, g)] for r_, g in zip(b[:, :, 0] / np.maximum(b[:, :, 1], 1e-3), b[:, :, 1])],
            blue_over_green=[[round(float(v), 2) if g_ > 6 else None for v, g_ in zip(r_, g)] for r_, g in zip(b[:, :, 2] / np.maximum(b[:, :, 1], 1e-3), b[:, :, 1])])
# the colour of the outer glow, the same blocks for every version (green 6 to 30 DN in F): red / green and blue / green, median and spread
cmp_ = {}
far = (b[:, :, 1] > 6) & (b[:, :, 1] < 30)
old = s10['numbers']['glow_block_medians']
for ver, tab in (('F', glow), ('B', old['B']), ('C', old['C'])):
    rg = np.array([[np.nan if v is None else v for v in row] for row in tab['red_over_green']], float); bg = np.array([[np.nan if v is None else v for v in row] for row in tab['blue_over_green']], float)
    cmp_[ver] = dict(blocks=int(np.isfinite(rg[far]).sum()), red_over_green=dict(median=float(np.nanmedian(rg[far])), p10=float(np.nanpercentile(rg[far], 10)), p90=float(np.nanpercentile(rg[far], 90))), blue_over_green=dict(median=float(np.nanmedian(bg[far])), p10=float(np.nanpercentile(bg[far], 10)), p90=float(np.nanpercentile(bg[far], 90))))
    print('outer glow (blocks with 6 to 30 DN of green in F), version %s: R/G median %.2f (10..90%%: %.2f..%.2f), B/G median %.2f (%.2f..%.2f), %d blocks' % (ver, cmp_[ver]['red_over_green']['median'], cmp_[ver]['red_over_green']['p10'], cmp_[ver]['red_over_green']['p90'], cmp_[ver]['blue_over_green']['median'], cmp_[ver]['blue_over_green']['p10'], cmp_[ver]['blue_over_green']['p90'], cmp_[ver]['blocks']))
bulge = b[:, :, 1] > 300
print('bulge blocks (green over 300 DN) in F: R/G %.2f B/G %.2f' % (float(np.median((b[:, :, 0] / b[:, :, 1])[bulge])), float(np.median((b[:, :, 2] / b[:, :, 1])[bulge]))))
json.dump(dict(zero=zinfo, outputs=outs, rect=rect, noise=noise, stars_in_the_stack=stars, glow_block_medians=glow, outer_glow_colour=cmp_, bulge_colour=dict(red_over_green=float(np.median((b[:, :, 0] / b[:, :, 1])[bulge])), blue_over_green=float(np.median((b[:, :, 2] / b[:, :, 1])[bulge]))),
               shadows=shadow, stretch=STRETCH, destination=DEST), open(W('f6_deliver%s.json' % ('_dry' if DRY else '')), 'w'), indent=1)
print(json.dumps(dict(noise=noise, stars=stars, outs=outs), indent=1))
