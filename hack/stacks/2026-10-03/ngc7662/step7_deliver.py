"""Step 7: colour, crops, stretch, files, numbers for the recipe."""
import json, os, sys, glob, hashlib, platform
import numpy as np, cv2, tifffile, rawpy, scipy, PIL
from PIL import Image
from scipy.signal import fftconvolve
from common import *
from render import *
from decon import psf_from_star

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = os.path.join(SCR, 'out_dry') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
CLOSE_W, CLOSE_H, CLOSE_UP = 774, 516, 2          # sensor px (5.0 x 3.3 arcmin at 0.388"/px), then 2x Lanczos-4
CLOSE = dict(white=1400.0, soft=420.0, pedestal=8.0)
FIELD_BIN = 2
FIELD = dict(white=None, soft=60.0, pedestal=5.0)   # white is set to 1.05 x the brightest value in the field
SCALE = 0.388

fl = np.load('stack_flat.npy'); sg = np.load('single_flat.npy')
s1 = json.load(open('step1.json')); s3 = json.load(open('step3_transforms.json')); s4 = json.load(open('step4_quality.json')); s5 = json.load(open('step5.json')); s6 = json.load(open('step6.json')); C = json.load(open('centres.json'))
x0, y0 = s5['origin_sensor_xy']
wb = np.median(np.array([f['wb'] for f in s1['frames']]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
rgb = rgb_from_planes(fl, wb_r, wb_b); rgb1 = rgb_from_planes(sg, wb_r, wb_b)
hh, ww = rgb.shape[:2]
neb = C['neb']; cx, cy = int(round(neb[0])), int(round(neb[1]))

def save(img8, stem):
    im = Image.fromarray(img8, 'RGB')
    im.save(os.path.join(DEST, stem + '.png'), optimize=True)
    im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)

def close(a):
    c = a[cy - CLOSE_H // 2:cy + CLOSE_H // 2, cx - CLOSE_W // 2:cx + CLOSE_W // 2]
    c = cv2.resize(c, None, fx=CLOSE_UP, fy=CLOSE_UP, interpolation=cv2.INTER_LANCZOS4)
    return c, asinh_stretch(c, **CLOSE)
c_lin, c8 = close(rgb); save(c8, 'ngc7662-stack-close')
c1_lin, c18 = close(rgb1); save(c18, 'ngc7662-single-frame-close')
fh, fw = hh // FIELD_BIN * FIELD_BIN, ww // FIELD_BIN * FIELD_BIN
fld = cv2.resize(rgb[:fh, :fw], (fw // FIELD_BIN, fh // FIELD_BIN), interpolation=cv2.INTER_AREA)
FIELD['white'] = float(1.05 * fld.max())
f8 = asinh_stretch(fld, **FIELD); save(f8, 'ngc7662-stack-field')
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'ngc7662-linear.tif'), rgb, photometric='rgb', compression='zlib', metadata=None)

# ---- numbers ----
yy, xx = np.mgrid[0:hh, 0:ww]
rr = np.hypot(xx - neb[0], yy - neb[1]); ann = (rr > 150) & (rr < 400)
def noise(a):
    return [clipped_stats(a[:, :, k][ann])[1] for k in range(3)]
n1, n25 = noise(rgb1), noise(rgb)
raw1 = [clipped_stats(sg[p][ann])[1] for p in range(4)]; raw25 = [clipped_stats(fl[p][ann])[1] for p in range(4)]
lum1 = clipped_stats(rgb1.mean(2)[ann])[1]; lum25 = clipped_stats(rgb.mean(2)[ann])[1]
G = rgb[:, :, 1]; G1 = rgb1[:, :, 1]
halo = []
for a, b in ((0, 10), (10, 20), (20, 28), (28, 36), (36, 40), (40, 45), (45, 50), (50, 55), (55, 60), (60, 70), (70, 80), (80, 100)):
    m = (rr >= a) & (rr < b); v = float(G[m].mean())
    halo.append(dict(r_px=[a, b], r_arcsec=[round(a * SCALE, 1), round(b * SCALE, 1)], green_mean_dn=v, snr_per_px_single=v / n1[1], snr_per_px_stack=v / n25[1]))
# scattered light: the nebula's core spread by the star's measured wings, against what is seen
def radial_kernel(img, c, rmax=200, bg_ring=(250, 300)):
    """The star as a round kernel: median in rings (1 px wide to r = 60, 10 px wide beyond), sky ring removed, sum 1."""
    cx_, cy_ = int(round(c[0])), int(round(c[1])); Rk = bg_ring[1] + 2
    t_ = img[cy_ - Rk:cy_ + Rk + 1, cx_ - Rk:cx_ + Rk + 1].astype(np.float64)
    yk, xk = np.mgrid[-Rk:Rk + 1, -Rk:Rk + 1]; rk = np.hypot(xk - (c[0] - cx_), yk - (c[1] - cy_))
    bg = np.median(t_[(rk >= bg_ring[0]) & (rk < bg_ring[1])])
    edges_ = list(range(0, 61)) + list(range(70, rmax + 11, 10))
    mid = []; val = []
    for a, b in zip(edges_[:-1], edges_[1:]):
        m = (rk >= a) & (rk < b); mid.append((a + b) / 2); val.append(np.median(t_[m]) - bg)
    yk2, xk2 = np.mgrid[-rmax:rmax + 1, -rmax:rmax + 1]; r2 = np.hypot(xk2, yk2)
    K = np.interp(r2, mid, val) * (r2 <= rmax)
    return K / K.sum(), float(bg), float((K * (r2 > 40)).sum() / K.sum())
K200, star_ring_bg, wing_fraction = radial_kernel(G, C['star'])
R = 260; t = G[cy - R:cy + R + 1, cx - R:cx + R + 1].astype(np.float64)
ty, tx = np.mgrid[-R:R + 1, -R:R + 1]; tr_ = np.hypot(tx - (neb[0] - cx), ty - (neb[1] - cy))
pred = fftconvolve(np.where(tr_ < 50, t, 0), K200, mode='same')
wings = []
for a, b in ((70, 80), (80, 100), (100, 140), (140, 200)):
    m = (tr_ >= a) & (tr_ < b)
    wings.append(dict(r_px=[a, b], seen_median_dn=float(np.median(t[m])), scattered_light_predicted_dn=float(np.median(pred[m]))))
# star width in the stack against the reference frame alone (same grid), half-flux diameter
def hfd(img, c, rmax=28):
    cx_, cy_ = int(round(c[0])), int(round(c[1])); t = img[cy_ - 40:cy_ + 41, cx_ - 40:cx_ + 41]
    yy_, xx_ = np.mgrid[-40:41, -40:41]; r = np.hypot(xx_ - (c[0] - cx_), yy_ - (c[1] - cy_))
    bg = np.median(t[(r > 34) & (r < 40)]); a = r <= rmax; o = np.argsort(r[a]); cum = np.cumsum((t - bg)[a][o])
    return float(2 * r[a][o][np.searchsorted(cum, cum[-1] / 2)])
hfds = {k: dict(stack=hfd(G, C[k]), single=hfd(G1, C[k])) for k in ('star', 's1', 's3')}
# is the bright star clipped in any frame? count plane pixels at the sensor's ceiling near it
clip = {}
for f in s1['frames']:
    P = np.load(os.path.join(SCR, 'planes', f['stamp'] + '.npy'), mmap_mode='r'); o = [o for o in s3 if o['stamp'] == f['stamp']][0]
    p = np.array(o['R']) @ np.array([2316.9, 2800.9]) + np.array(o['t']); px, py = int(p[0] / 2), int(p[1] / 2); n = 0
    for k in range(4):
        n += int((P[k, py - 14:py + 15, px - 14:px + 15] + f['bg'][k]['clipped_mean'] >= 15840).sum())
    clip[f['stamp']] = n
# leftover hot pixels in the stack: isolated sharp points in sky
left = []
for p in range(4):
    a = fl[p]; m5 = cv2.medianBlur(a, 5); e = a - m5; s = clipped_stats(e[::3, ::3])[1]
    left.append(dict(plane=PLANE_NAMES[p], above_6_sigma=int(((e > 6 * s) & (m5 < 50)).sum()), pixels=int(a.size)))

sidecars = {}
for f in s1['all_in_window']:
    j = json.load(open(f['path'][:-4] + '.json'))
    sidecars[f['stamp']] = {x['format']: x['sha256'] for x in j['files']}
tq = {o['stamp']: o for o in s4['quality']}; tt = {o['stamp']: o for o in s3}
frames = []
for f in s1['frames']:
    o = tt[f['stamp']]; q = tq[f['stamp']]
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=sidecars[f['stamp']].get('arw'), used=f['stamp'] in s5['used'],
                       black_level=f['black'], sky_subtracted_dn=dict(zip(PLANE_NAMES, [round(b['clipped_mean'], 3) for b in f['bg']])), sky_median_dn=dict(zip(PLANE_NAMES, [b['median'] for b in f['bg']])),
                       sky_noise_dn=dict(zip(PLANE_NAMES, [round(b['clipped_std'], 2) for b in f['bg']])), white_balance_as_shot=f['wb'], orientation_flag=f['flip'],
                       transient_spikes_replaced=f['transient_spikes_replaced'],
                       shift_at_frame_centre_px=[round(v, 3) for v in o['shift_at_centre_px']], rotation_deg=round(o['rotation_deg'], 4), transform_R=o['R'], transform_t=o['t'],
                       registration=dict(stars_used=o['used'], weighted_rms_px=round(o['wrms_px'], 3), scale_if_left_free=round(o['similarity_scale'], 5)),
                       star_width_relative=round(q['width_rel'], 4), half_flux_radius_relative=round(q['hfr_rel'], 4), elongation_median=round(q['elong_median'], 4), common_direction_ellipticity=round(q['coherent_ellipticity'], 4),
                       brightness_relative=round(q['flux_rel'], 4), bright_star_half_flux_diameter_px=round(q['bright_star']['hfr_px'] * 2, 2), bright_star_pixels_at_ceiling=clip[f['stamp']]))
sh = np.array([o['shift_at_centre_px'] for o in s3]); rot = np.array([o['rotation_deg'] for o in s3])
t_first, t_last = s1['frames'][0]['t'], s1['frames'][-1]['t']
others = sorted(glob.glob(os.path.join(STILLS, '20261004-06[23]*.json')))
left_out = []
for p in others:
    if p.endswith('.solve.json'): continue
    b = os.path.basename(p)[:-5]; j = json.load(open(p)); cam = j.get('camera') or {}
    if b[9:15] < T0: left_out.append(dict(file=b + '.ARW', exposure_s=cam.get('exposure_s'), iso=cam.get('iso'), why='before the run; not 6 s at ISO 1600 (left out as asked)'))
recipe = dict(
    what='NGC 7662 (Blue Snowball), %d x 6 s at ISO 1600, Sony a6000 on a Celestron 8SE, stacked from RAW colour planes' % len(s5['used']),
    made_utc=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, pillow=PIL.__version__,
               note='deterministic array arithmetic only; nothing generative or learned'),
    source=dict(folder=STILLS, window_utc=[T0, T1], frames_found=len(s1['all_in_window']), frames_at_6s_iso1600=len(s1['frames']), frames_used=len(s5['used']), frames_rejected=[],
                left_out=left_out, originals='read in place, not modified'),
    frames=frames,
    rejection=dict(rule='reject a frame if star width > 1.10 x the run median, or median elongation > 1.20, or common-direction ellipticity > 0.15 (trailing), or brightness < 0.90 x median (cloud), or registration weighted rms > 1.0 px',
                   measured_ranges=dict(star_width_relative=[min(f['star_width_relative'] for f in frames), max(f['star_width_relative'] for f in frames)], elongation_median=[min(f['elongation_median'] for f in frames), max(f['elongation_median'] for f in frames)],
                                        common_direction_ellipticity=[min(f['common_direction_ellipticity'] for f in frames), max(f['common_direction_ellipticity'] for f in frames)], brightness_relative=[min(f['brightness_relative'] for f in frames), max(f['brightness_relative'] for f in frames)],
                                        registration_weighted_rms_px=[min(f['registration']['weighted_rms_px'] for f in frames if f['file'][:15] != REF_STAMP), max(f['registration']['weighted_rms_px'] for f in frames)]),
                   result='no frame crossed any limit; all %d used' % len(s5['used']), quality_stars=len(s4['quality_star_ref_index'])),
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (sensor orientation, 6024 x 4024, RGGB), black level 512 subtracted; four colour planes R, G1, G2, B kept apart at 3012 x 2012, no demosaic'),
        dict(step='sky', detail='per frame and per plane: 3-sigma clipped mean of the plane outside 260 px of the nebula and the bright star, subtracted (clipped mean rather than median because the RAW values step in 4 DN; both are recorded per frame)'),
        dict(step='hot pixels', detail='fixed: per-plane median of all frames without registration, pixels standing above the 5x5 median of that by more than max(6 sigma, 25% of the level); transient: per frame, pixels above the 3x3 median by more than 8 sigma + 50% of the level. Both replaced by the 3x3 median of the same colour plane before resampling.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s1['hot']}, fraction_of_plane={h['plane']: round(h['frac'], 5) for h in s1['hot']}),
        dict(step='stars', detail='green planes averaged (half-size grid), Gaussian blur sigma 2.5, 6-sigma threshold, connected blobs; Gaussian-windowed centroid (sigma 5 plane px); 28 px (sensor) aperture for flux, second moments and half-flux radius'),
        dict(step='register', detail='reference frame %s. Stars brighter than 5000 DN (and the nebula) matched to the reference; weighted least-squares rotation + shift (no scale), weights 1/(0.25^2 + (7000/flux)^2) px^-2, 3.5-sigma rejection. Scale left free came out within 0.00015 of 1.' % REF_STAMP,
             shift_at_frame_centre_px=dict(x_range=[round(float(sh[:, 0].min()), 2), round(float(sh[:, 0].max()), 2)], y_range=[round(float(sh[:, 1].min()), 2), round(float(sh[:, 1].max()), 2)], path_length=round(float(np.hypot(*np.diff(sh, axis=0).T).sum()), 1),
                                           frame_to_frame=[round(float(v), 1) for v in np.hypot(*np.diff(sh, axis=0).T)]),
             rotation_deg=dict(first=round(float(rot[0]), 4), last=round(float(rot[-1]), 4), total=round(float(rot[0] - rot[-1]), 4), span_s=582, per_minute=round(float((rot[0] - rot[-1]) / 582 * 60), 4), corrected=True)),
        dict(step='resample', detail='each plane of each frame mapped straight onto the reference frame sensor grid (rotation + shift + the plane\'s own place in the 2x2 colour cell) with OpenCV remap, Lanczos-4. %d px trimmed from each edge so every pixel has every frame.' % s5['margin'],
             stacked_area_sensor_px=dict(x0=x0, y0=y0, width=ww, height=hh)),
        dict(step='combine', detail='per pixel, per plane: reject values more than 3 sigma from the median (sigma = 1.4826 x MAD, floor half the single-frame noise), then again 3 sigma about the mean of the survivors, then the mean. Equal weights; no brightness scaling (frames agree to 2%).',
             kappa=s5['kappa'], per_plane=s5['planes']),
        dict(step='flatten sky', detail='the sky left over is a shallow dome (vignetted sky glow, about +2 DN at centre to -4 DN in the corners in green). A 2nd-order polynomial surface fitted to 3-sigma-clipped means of 128 px blocks (blocks near bright stars and the nebula left out) is subtracted from each plane; the same surface from the single comparison frame. No flat field was available: star and nebula brightness are not corrected for vignetting.', fit=s6),
        dict(step='colour', detail='G = mean of G1 and G2; R x %.4f and B x %.4f: the camera\'s as-shot white balance from the RAW (median over the frames; it wobbles by 0.3%% frame to frame). No colour matrix, no saturation change: these are white-balanced camera-native colours, as in saturn.py.' % (wb_r, wb_b),
             white_balance_multipliers=dict(R=wb_r, G=1.0, B=wb_b), as_shot_raw=[float(v) for v in wb]),
    ],
    numbers=dict(
        noise_sky_ring_r150_400px=dict(units='DN per sensor-grid pixel, 3-sigma clipped std; single frame = the reference frame %s through the same hot-pixel repair and resampling' % REF_STAMP,
                                       raw_planes_single=dict(zip(PLANE_NAMES, [round(v, 2) for v in raw1])), raw_planes_stack=dict(zip(PLANE_NAMES, [round(v, 2) for v in raw25])),
                                       white_balanced_single=dict(zip('RGB', [round(v, 2) for v in n1])), white_balanced_stack=dict(zip('RGB', [round(v, 2) for v in n25])),
                                       mean_of_rgb_single=round(lum1, 2), mean_of_rgb_stack=round(lum25, 2), improvement=dict(zip('RGB', [round(a / b, 2) for a, b in zip(n1, n25)])), improvement_mean_of_rgb=round(lum1 / lum25, 2), ideal=round(len(s5['used']) ** 0.5, 2)),
        nebula_green_profile=halo,
        nebula_centre_sensor_px=[round(neb[0] + x0, 1), round(neb[1] + y0, 1)],
        scattered_light_check=dict(method='nebula inside r < 50 px convolved with the bright star\'s ring-median profile out to 200 px (green), against the stack', star_light_beyond_40px_fraction=wing_fraction, sky_uncertainty_dn=0.2, rings=wings),
        star_half_flux_diameter_px=hfds,
        leftover_sharp_points_in_sky=left,
    ),
    outputs={
        'ngc7662-stack-close.png / .jpg': dict(crop_sensor_px=dict(centre=[round(neb[0] + x0, 1), round(neb[1] + y0, 1)], width=CLOSE_W, height=CLOSE_H), field_arcmin=[round(CLOSE_W * SCALE / 60, 2), round(CLOSE_H * SCALE / 60, 2)],
                                           resampling='2x, Lanczos-4 (cv2.resize) on the linear data', pixel_scale_arcsec=SCALE / CLOSE_UP, size_px=[c8.shape[1], c8.shape[0]],
                                           stretch=dict(kind='arcsinh, same gain for R, G and B of a pixel (colour ratios kept), then the sRGB transfer curve', formula='I = max(R,G,B) + pedestal; out = (RGB + pedestal) * asinh(I/soft) / (I * asinh(white/soft)); clip 0..1; sRGB OETF; 8 bit', **CLOSE),
                                           brightest_value_dn=float(c_lin.max()), clipped_pixels_at_white=int((c8 == 255).any(2).sum())),
        'ngc7662-single-frame-close.png / .jpg': dict(what='the reference frame %s alone, same hot-pixel repair, same grid, same crop, same stretch, for comparison' % REF_STAMP),
        'ngc7662-stack-field.png / .jpg': dict(area='the whole stacked area, %d x %d sensor px (%.1f x %.1f arcmin)' % (fw, fh, fw * SCALE / 60, fh * SCALE / 60), resampling='2x2 block mean (cv2.resize INTER_AREA)', pixel_scale_arcsec=SCALE * FIELD_BIN, size_px=[f8.shape[1], f8.shape[0]],
                                           stretch=dict(kind='same arcsinh formula as the close crop', **FIELD), clipped_pixels_at_white=int((f8 == 255).any(2).sum())),
        'ngc7662-linear.tif': dict(what='the stack, linear, 32-bit float RGB, white balance applied, sky at 0', units='DN of the 14-bit RAW scale per 6 s frame (green as measured; R and B multiplied by the white balance)', size_px=[ww, hh], pixel_scale_arcsec=SCALE,
                                   origin='pixel (0,0) is sensor pixel (%d,%d) of the reference frame' % (x0, y0), compression='zlib, lossless'),
    },
    orientation='sensor orientation of the RAW (as rawpy raw_image_visible); not rotated to north and not plate solved here',
    caveats=[
        'Out of focus. Every star is a ring, not a point: the bright star has its ring peak 8.5 px from centre, a centre about 40%% as bright as the ring, and a half-flux diameter of %.1f px (%.1f arcsec). The nebula is blurred by that ring. The shallow dark dimple just right of the centre of the disc is the size of the ring\'s hole and is not to be read as the nebula\'s own structure.' % (hfds['star']['stack'], hfds['star']['stack'] * SCALE),
        'The ring changes across the field (its bright side moves, and it grows toward the edges), so one star cannot stand for the blur everywhere.',
        'No dark frames and no flat field. Hot pixels were replaced as described; vignetting and dust shadows are not corrected. About a dozen 32 px blocks of sky sit 1.5 to 2.6 DN low in a few smudges roughly 80 px across (probably dust shadows); the nearest is 1300 px from the nebula.',
        'Colour is the camera\'s white balance only, with no camera-to-sRGB matrix (as saturn.py): hues are camera-native and a colour-managed rendering would be more saturated.',
        'The bright star touches the sensor ceiling in 2 plane pixels of one frame (%s); elsewhere it is below it (peak 10800 to 15000 DN of 15860).' % ', '.join(k for k, v in clip.items() if v),
        'Light further than about 27 arcsec (70 px) from the nebula\'s centre is 1 DN or less and agrees, within the 0.2 DN uncertainty of the sky level, with the nebula\'s own light scattered by the telescope and air. No separate faint outer halo is detected.',
        'The single comparison frame had its hot pixels repaired the same way, so the comparison shows the gain from averaging, not from hot-pixel removal.',
    ],
    scripts='scripts/ beside this file: common.py, step1_hot.py, step2_stars.py, step3_register.py, step4_quality.py, step5_stack.py, step6_flatten.py, step7_deliver.py, render.py (decon.py and try_decon.py are the rejected deconvolution trial)',
    deconvolution=dict(delivered=False, tried='Richardson-Lucy, 5 / 10 / 20 / 40 rounds, blur measured from the bright star in this stack (per channel, 40 px radius)',
                       why_not='already at 5 to 10 rounds it drew a dark crescent on the lower-left edge of the nebula and of the faint star beside it, and a faint arc outside the nebula, none of which are in the plain stack. The blur is an out-of-focus ring whose bright side changes across the field, so the bright star 1270 px away is not the blur at the nebula, and no star near the nebula is bright enough to measure it.'),
)
json.dump(recipe, open(os.path.join(DEST, 'ngc7662-recipe.json'), 'w'), indent=1)
print(json.dumps(recipe['numbers'], indent=1)); print(json.dumps(recipe['outputs'], indent=1))
print('clip', {k: v for k, v in clip.items() if v})
