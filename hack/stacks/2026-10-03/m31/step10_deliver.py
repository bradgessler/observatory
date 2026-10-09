"""Step 10: colour, crop, stretch, files, and the numbers for the recipe.
Versions:  B = m31-core (radial vignetting profile removed, dust-shadowed sensor pixels left out)  [as asked]
           A = m31-core-as-recorded (nothing done about the flat field)                             [as asked]
           C = m31-core-cloudflat (the whole smooth cloud-glow flat removed; the few shadow cores that could not
               be left out are divided by their measured transmission)                              [extra]"""
import json, os, sys, platform, datetime
import numpy as np, cv2, tifffile, rawpy, scipy, PIL
from PIL import Image
from common import *
from final import *
from render import *
import measure

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
STRETCH = dict(white=14000.0, soft=45.0, pedestal=4.0)
CHROMA_SIGMA_SENSOR_PX = 4.0
DUST_CROP = (2500, 1650, 4900, 3250)          # sensor px on the reference grid: x0, y0, x1, y1

s1l = json.load(open(W('step1.json'))); s1 = {f['stamp']: f for f in s1l['frames']}
s2 = json.load(open(W('step2.json'))); s2f = {f['stamp']: f for f in s2['frames']}
T4 = json.load(open(W('step4_transforms.json'))); tr = {o['stamp']: o for o in T4['transforms']}
Q = json.load(open(W('step5_quality.json'))); q = {o['stamp']: o for o in Q['quality']}
sel = json.load(open(W('step7_select.json'))); USE = sel['used']; USED = [u['stamp'] for u in USE]; n_used = len(USED); useby = {u['stamp']: u for u in USE}
vig = json.load(open(W('vignette.json'))); dust = json.load(open(W('dust.json'))); dustmap = json.load(open(W('dustmap.json'))); chk = json.load(open(W('check_flat.json')))
star = json.load(open(W('starcolour.json'))); flat2d = json.load(open(W('flat2d.json')))
s8 = {v: json.load(open(W('step8_%s.json' % v))) for v in 'ABC'}
wb = np.median(np.array([s1[s]['wb'] for s in USED]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
sw_r, sw_b = star['star_neutral_multipliers']['R'], star['star_neutral_multipliers']['B']

rect = cover_rect('B', n_used); x0, y0, x1, y1 = rect
assert rect == cover_rect('A', n_used) == cover_rect('C', n_used)
clean = clean_mask(rect); notedge = not_edge_mask(rect)
pred = np.load(W('dust_pred_final.npy'))[y0:y1, x0:x1]

def save(img8, stem):
    im = Image.fromarray(img8, 'RGB')
    im.save(os.path.join(DEST, stem + '.png'), optimize=True)
    im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)

planes, levels, zinfo = {}, {}, {}
for ver in 'ABC':
    c = np.load(W('%s_final.npy' % ver))[:, y0:y1, x0:x1].copy()
    if ver == 'C': c /= pred[None]                       # the shadow cores that could not be left out: divided by the measured transmission
    lev, dark, cen = zero_levels(c, clean, notedge); ys, xs = np.nonzero(dark)
    planes[ver] = c - np.array(lev, np.float32)[:, None, None]; levels[ver] = [float(v) for v in lev]
    zinfo[ver] = dict(levels_subtracted_dn=dict(zip(PLANE_NAMES, [round(float(v), 2) for v in lev])), region_px=int(dark.sum()), region_bbox_sensor_px=[int(xs.min() + x0), int(ys.min() + y0), int(xs.max() + x0), int(ys.max() + y0)],
                      region_centre_sensor_px=[round(float(np.median(xs)) + x0), round(float(np.median(ys)) + y0)])
    print(ver, 'zero', zinfo[ver], flush=True)

def half(rgb): return cv2.resize(rgb, (rgb.shape[1] // 2, rgb.shape[0] // 2), interpolation=cv2.INTER_AREA)
outs = {}
def field(ver, stem, r, b):
    rgb = rgb_from_planes(planes[ver], r, b); h_ = half(rgb)
    img = asinh_stretch(h_, chroma_sigma=CHROMA_SIGMA_SENSOR_PX / 2, **STRETCH); save(img, stem)
    outs[stem] = dict(size_px=[img.shape[1], img.shape[0]], pixels_at_255_in_any_channel=int((img == 255).any(2).sum()), median_8bit=[int(v) for v in np.median(img.reshape(-1, 3)[::7], axis=0)])
    return rgb
def crop(rgb, stem):
    cx0, cy0, cx1, cy1 = DUST_CROP
    c = rgb[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
    img = asinh_stretch(c, chroma_sigma=CHROMA_SIGMA_SENSOR_PX, **STRETCH); save(img, stem)
    outs[stem] = dict(size_px=[img.shape[1], img.shape[0]], pixels_at_255_in_any_channel=int((img == 255).any(2).sum()))
rgbB = field('B', 'm31-core', wb_r, wb_b); crop(rgbB, 'm31-core-dust')
rgbA = field('A', 'm31-core-as-recorded', wb_r, wb_b); del rgbA
rgbC = field('C', 'm31-core-cloudflat', wb_r, wb_b); crop(rgbC, 'm31-core-dust-cloudflat')
_ = field('C', 'm31-core-cloudflat-starwhite', sw_r, sw_b); del _
print('pictures written', flush=True)
used = np.load(W('B_used.npy'))[1][y0:y1, x0:x1]; cover = np.load(W('B_cover.npy'))[y0:y1, x0:x1]
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'm31-core-linear.tif'), rgbB, photometric='rgb', compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm31-core-cloudflat-linear.tif'), rgbC, photometric='rgb', compression='zlib', metadata=None)
    tifffile.imwrite(os.path.join(DEST, 'm31-core-coverage.tif'), used, compression='zlib', metadata=None)
# the diagnostic map of sensor dust left in the picture: same geometry as m31-core.png; 255 = no shadow, 0 = 20% or more of the light lost
dm = cv2.resize(pred, (pred.shape[1] // 2, pred.shape[0] // 2), interpolation=cv2.INTER_AREA)
Image.fromarray((np.clip((dm - 0.80) / 0.20, 0, 1) * 255 + 0.5).astype(np.uint8), 'L').save(os.path.join(DEST, 'm31-core-sensor-dust-map.png'), optimize=True)

# ---------------- numbers ----------------
G = np.ascontiguousarray(rgbB[:, :, 1])
# 1. noise in the faintest clean part of the field: a 500 px patch inside the zero region of version B
zb = zinfo['B']['region_bbox_sensor_px']; best = None
for py in range(zb[1] - y0 - 150, zb[3] - y0 - 350 + 1, 50):
    for px in range(zb[0] - x0, zb[2] - x0 - 500, 50):
        if py < 0: continue
        f = float((used[py:py + 500, px:px + 500] >= n_used - 2).mean()); lv = float(np.median(G[py:py + 500:4, px:px + 500:4]))
        if best is None or (f - 0.01 * lv) > best[0]: best = (f - 0.01 * lv, px, py, f, lv)
_, px, py, pf, plv = best
P = (slice(py, py + 500), slice(px, px + 500)); Pfull = (slice(py + y0, py + y0 + 500), slice(px + x0, px + x0 + 500))
pair = np.load(W('B_pairdiff.npy')); odd = np.load(W('B_odd.npy')); even = np.load(W('B_even.npy'))
hd = (odd - even) / 2
def cs(a): return clipped_stats(a)[1]
single_planes = [cs(pair[p][Pfull]) for p in range(4)]; stack_planes = [cs(hd[p][Pfull]) for p in range(4)]
def to_rgb(a): return [a[0] * wb_r, (a[1] + a[2]) / 2, a[3] * wb_b]
single_rgb = [cs(v[Pfull]) for v in to_rgb(pair)]; stack_rgb = [cs(v[Pfull]) for v in to_rgb(hd)]
def half2(a): return a[:a.shape[0] // 2 * 2, :a.shape[1] // 2 * 2].reshape(a.shape[0] // 2, 2, a.shape[1] // 2, 2).mean((1, 3))
single_rgb_half = [cs(half2(v[Pfull])) for v in to_rgb(pair)]; stack_rgb_half = [cs(half2(v[Pfull])) for v in to_rgb(hd)]
raw_single = [s1[REF_STAMP]['corner'][p]['clipped_std'] for p in range(4)]
# 2. weighted (38 frames) against clear frames only (27, equal weights): same patch, the picture minus its 9x9 median, clipped scatter
mean_all = np.load(W('B_mean.npy')); mean_clear = np.load(W('B_clear.npy'))
def hp(a): return cs((a - cv2.medianBlur(a, 5))[Pfull])
hp_all = [hp(np.ascontiguousarray(mean_all[p])) for p in range(4)]; hp_clear = [hp(np.ascontiguousarray(mean_clear[p])) for p in range(4)]
dg = (mean_all[1:3].mean(0) - mean_clear[1:3].mean(0))[y0:y1, x0:x1]; bs = 256; ny, nx = dg.shape[0] // bs, dg.shape[1] // bs
with np.errstate(all='ignore'): db = np.nanmedian(dg[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
gl = np.median(G[:ny * bs, :nx * bs].reshape(ny, bs, nx, bs).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
far = gl < 100
weighted = dict(what='the delivered stack (38 frames, weights) against the same combine from the 27 clear frames alone (equal weights)',
                scatter_of_picture_minus_its_5x5_median_dn=dict(weighted_38=dict(zip(PLANE_NAMES, [round(v, 2) for v in hp_all])), clear_27=dict(zip(PLANE_NAMES, [round(v, 2) for v in hp_clear])),
                                                              ratio=dict(zip(PLANE_NAMES, [round(a / b, 3) for a, b in zip(hp_all, hp_clear)]))),
                expected_ratio_from_weights=round(float(np.sqrt(sum(u['clear'] for u in USE) / sum(u['weight'] for u in USE))), 3),
                large_scale_difference_green_dn=dict(blocks_px=bs, blocks=int(far.sum()), where='256 px block medians of (weighted - clear only), blocks with less than 100 DN of galaxy', rms=round(float(np.sqrt(np.nanmean(db[far] ** 2))), 3), min=round(float(np.nanmin(db[far])), 2), max=round(float(np.nanmax(db[far])), 2),
                                                     near_the_nucleus_min_max=[round(float(np.nanmin(db[~far])), 2), round(float(np.nanmax(db[~far])), 2)]))
del mean_all, mean_clear, odd, even, pair, hd
# 3. the stars in the stack
rows = []
for xy in Q['star_xy'].values():
    a = measure.star(G, xy[0] - x0, xy[1] - y0)
    if a and a['fwhm']: rows.append(a)
e = np.mean([(r['sig_major'] ** 2 - r['sig_minor'] ** 2) / (r['sig_major'] ** 2 + r['sig_minor'] ** 2) * np.exp(2j * np.radians(r['theta'])) for r in rows])
stars = dict(stars=len(rows), half_flux_diameter_arcsec=round(float(np.median([r['hfd'] for r in rows])) * SCALE, 2), fwhm_arcsec=round(float(np.median([r['fwhm'] for r in rows])) * SCALE, 2), fwhm_px=round(float(np.median([r['fwhm'] for r in rows])), 1),
             elongation=round(float(np.median([r['elong'] for r in rows])), 3), common_direction_ellipticity=round(float(abs(e)), 3),
             single_frames_used=dict(half_flux_diameter_arcsec_median=round(float(np.median([q[s]['hfd_arcsec'] for s in USED])), 2), best=round(min(q[s]['hfd_arcsec'] for s in USED), 2), worst=round(max(q[s]['hfd_arcsec'] for s in USED), 2), elongation_median=round(float(np.median([q[s]['elong_median'] for s in USED])), 3)))
# 4. motion
def tsec(s): return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
reg = [o for o in T4['transforms'] if not o.get('failed')]
def motion(lst):
    sh = np.array([o['shift_at_centre_px'] for o in lst]); rot = np.array([o['rotation_deg'] for o in lst]); span = tsec(s1[lst[-1]['stamp']]['t']) - tsec(s1[lst[0]['stamp']]['t'])
    net = float(np.hypot(*(sh[-1] - sh[0]))); path = float(np.hypot(*np.diff(sh, axis=0).T).sum())
    return dict(frames=len(lst), first=lst[0]['stamp'], last=lst[-1]['stamp'], span_minutes=round(span / 60, 2), rotation_first_deg=round(float(rot[0]), 4), rotation_last_deg=round(float(rot[-1]), 4), rotation_total_deg=round(float(abs(rot[-1] - rot[0])), 3),
                rotation_deg_per_minute=round(float(abs(rot[-1] - rot[0]) / span * 60), 4), drift_net_px=round(net, 1), drift_net_arcsec=round(net * SCALE, 1), drift_path_px=round(path, 1), drift_path_arcsec_per_s=round(path * SCALE / span, 4),
                shift_x_range_px=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], shift_y_range_px=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)],
                corner_smear_if_not_rotated_px=round(float(np.radians(abs(rot[-1] - rot[0])) * np.hypot(3012, 2012)), 1))
r_early = [o for o in reg if o['stamp'] <= '20261004-074600']; r_late = [o for o in reg if o['stamp'] >= '20261004-083000']
def rate(lst): return round(float(abs(lst[-1]['rotation_deg'] - lst[0]['rotation_deg']) / (tsec(s1[lst[-1]['stamp']]['t']) - tsec(s1[lst[0]['stamp']]['t'])) * 60), 4)
mot = dict(all_registered_frames=motion(reg), used_frames=motion([tr[s] for s in USED]), rotation_rate_first_ten_minutes_deg_per_minute=rate(r_early), rotation_rate_last_quarter_hour_deg_per_minute=rate(r_late),
           rotation_during_one_20s_frame_at_corner_px=round(float(np.radians(rate(r_early) / 3) * np.hypot(3012, 2012)), 2), scale_if_left_free_range=[round(min(o['similarity_scale'] for o in reg if o['stamp'] in USED), 5), round(max(o['similarity_scale'] for o in reg if o['stamp'] in USED), 5)])
# 5. clipping in the RAW
nmax = {s: max(s2f[s]['nucleus_max_dn_above_black_repaired'][1:3]) for s in USED}
clip = dict(ceiling='raw values of 16000 or more (black is 512: about 15500 DN above black)',
            nucleus=dict(region='within 200 sensor px of the nucleus, hot pixels and single-frame spikes left out', pixels_at_ceiling_in_any_used_frame=int(sum(sum(s2f[s]['ceiling_pixels_near_nucleus']) for s in USED)), pixels_at_ceiling_in_any_frame_of_the_run=int(sum(sum(f['ceiling_pixels_near_nucleus']) for f in s2['frames'])),
                         brightest_green_pixel_dn_above_black_used_frames=dict(median=float(np.median(list(nmax.values()))), highest=float(max(nmax.values()))), fraction_of_ceiling=round(float(max(nmax.values())) / 15500, 2),
                         in_the_stack_green_dn_above_zero=round(float(G[2700 - y0:3100 - y0, 2750 - x0:3150 - x0].max()), 0)),
            stars_at_ceiling='green pixels at the ceiling over the whole frame (bright stars only): %d to %d per plane per clear frame' % (min(s2f[s]['ceiling_pixels_whole_frame'][1] for s in USED), max(s2f[s]['ceiling_pixels_whole_frame'][1] for s in USED)))
# 6. the glow: 384 px block medians, DN above the zero region, as-shot white balance (so that the versions can be compared in numbers)
def blocks(rgb):
    b = 384; ny_, nx_ = rgb.shape[0] // b, rgb.shape[1] // b
    return np.median(rgb[:ny_ * b, :nx_ * b].reshape(ny_, b, nx_, b, 3).transpose(0, 2, 1, 3, 4).reshape(ny_, nx_, -1, 3), axis=2)
glow = {}
for ver, rgb in (('B', rgbB), ('C', rgbC)):
    b = blocks(rgb); glow[ver] = dict(green_dn=[[round(float(v), 1) for v in row] for row in b[:, :, 1]], red_over_green=[[round(float(v), 2) if g_ > 6 else None for v, g_ in zip(r_, g)] for r_, g in zip(b[:, :, 0] / np.maximum(b[:, :, 1], 1e-3), b[:, :, 1])],
                                      blue_over_green=[[round(float(v), 2) if g_ > 6 else None for v, g_ in zip(r_, g)] for r_, g in zip(b[:, :, 2] / np.maximum(b[:, :, 1], 1e-3), b[:, :, 1])])
numbers = dict(
    noise=dict(where='500 x 500 px patch of the faintest clean part of the field, sensor px x %d..%d, y %d..%d (version B grid); %.0f%% of it has at least %d of %d frames; galaxy there %.1f DN (green) above the zero region' % (px + x0, px + x0 + 500, py + y0, py + y0 + 500, 100 * pf, n_used - 2, n_used, plv),
               how='3-sigma clipped standard deviation. One frame: two neighbouring clear frames (%s, %s) through the whole pipeline, their difference / sqrt 2 (the sky and the galaxy cancel). Stack: (stack of the odd frames - stack of the even frames) / 2. Both on the sensor grid, where neighbouring pixels share samples (each colour plane is sampled every 2 px), and again after 2 x 2 binning (the scale of the whole-field pictures).' % tuple(s8['B']['pair']),
               raw_plane_single_frame_dn=dict(zip(PLANE_NAMES, [round(v, 1) for v in raw_single])), raw_plane_note='reference frame, top-left corner of the sensor, colour plane pixels straight from the RAW (no resampling)',
               sensor_grid=dict(one_frame_planes=dict(zip(PLANE_NAMES, [round(v, 2) for v in single_planes])), stack_planes=dict(zip(PLANE_NAMES, [round(v, 2) for v in stack_planes])),
                                one_frame_white_balanced=dict(zip('RGB', [round(v, 2) for v in single_rgb])), stack_white_balanced=dict(zip('RGB', [round(v, 2) for v in stack_rgb])), improvement=dict(zip('RGB', [round(a / b, 2) for a, b in zip(single_rgb, stack_rgb)]))),
               binned_2x2=dict(one_frame_white_balanced=dict(zip('RGB', [round(v, 2) for v in single_rgb_half])), stack_white_balanced=dict(zip('RGB', [round(v, 2) for v in stack_rgb_half])), improvement=dict(zip('RGB', [round(a / b, 2) for a, b in zip(single_rgb_half, stack_rgb_half)]))),
               ideal_improvement_sqrt_of_summed_weights=round(float(np.sqrt(sum(u['weight'] for u in USE))), 2), plain_sqrt_of_frames=round(n_used ** 0.5, 2)),
    weighted_against_clear_only=weighted, stars_in_the_stack=stars, motion=mot, raw_clipping=clip, glow_block_medians=glow)
json.dump(dict(numbers=numbers, zero=zinfo, outputs=outs, rect=rect, wb=dict(as_shot=dict(R=wb_r, B=wb_b, raw=[float(v) for v in wb]), star_neutral=dict(R=sw_r, B=sw_b)), stretch=STRETCH, chroma_sigma_sensor_px=CHROMA_SIGMA_SENSOR_PX, dust_crop=DUST_CROP), open(W('step10.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in numbers.items() if k != 'glow_block_medians'}, indent=1)); print(json.dumps(outs, indent=1))
