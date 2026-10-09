"""Step 7: colour, crops, stretch, files, and the numbers for the recipe."""
import json, os, sys, glob, platform, datetime
import numpy as np, cv2, tifffile, rawpy, scipy, PIL
from PIL import Image
from common import *
from render import *
import measure

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry') if DRY else OUT
os.makedirs(DEST, exist_ok=True)
CROP = 2474                                   # sensor px = 16.0 arcmin at 0.388"/px, no resampling
STRETCH = dict(white=6000.0, soft=100.0, pedestal=8.0, smooth_sigma=0.0)
FIELD_BIN = 2

fl = np.load(W('stack_flat.npy')); sg = np.load(W('single_flat.npy'))
s1 = json.load(open(W('step1.json'))); s2 = {r['stamp']: r for r in json.load(open(W('step2_stars.json')))}; s3 = json.load(open(W('step3_transforms.json'))); s4 = json.load(open(W('step4_quality.json')))
s4b = json.load(open(W('step4b_dust.json'))); sel = json.load(open(W('step4c_select.json'))); s5 = json.load(open(W('step5.json'))); s6 = json.load(open(W('step6.json'))); C = json.load(open(W('centres.json')))
x0, y0 = s5['origin_sensor_xy']; USED = s5['used']; n_used = len(USED)
f1 = {f['stamp']: f for f in s1['frames']}
wb = np.median(np.array([f1[s]['wb'] for s in USED]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
rgb = rgb_from_planes(fl, wb_r, wb_b); rgb1 = rgb_from_planes(sg, wb_r, wb_b)
hh, ww = rgb.shape[:2]
cx, cy = int(round(C['cluster'][0])), int(round(C['cluster'][1])); half = CROP // 2
assert cy - half >= 0 and cx - half >= 0 and cy + half <= hh and cx + half <= ww, 'crop does not fit'

def save(img8, stem):
    im = Image.fromarray(img8, 'RGB')
    im.save(os.path.join(DEST, stem + '.png'), optimize=True)
    im.save(os.path.join(DEST, stem + '.jpg'), quality=92, subsampling=0)

crop = rgb[cy - half:cy + half, cx - half:cx + half]; crop1 = rgb1[cy - half:cy + half, cx - half:cx + half]
c8 = asinh_stretch(crop, **STRETCH); save(c8, 'm15-stack')
c18 = asinh_stretch(crop1, **STRETCH); save(c18, 'm15-single-frame')
fh, fw = hh // FIELD_BIN * FIELD_BIN, ww // FIELD_BIN * FIELD_BIN
fld = cv2.resize(rgb[:fh, :fw], (fw // FIELD_BIN, fh // FIELD_BIN), interpolation=cv2.INTER_AREA)
f8 = asinh_stretch(fld, **STRETCH); save(f8, 'm15-stack-field')
if not DRY:
    tifffile.imwrite(os.path.join(DEST, 'm15-linear.tif'), rgb, photometric='rgb', compression='zlib', metadata=None)

# ---------------- numbers ----------------
G = np.ascontiguousarray(rgb[:, :, 1]); G1 = np.ascontiguousarray(rgb1[:, :, 1])
# 1. noise: four patches of plain sky, each 500 x 500 px, more than 8 arcmin from the cluster
PATCHES = [(1500, 1900), (2700, 600), (300, 500), (3000, 4300)]         # (row, col) of the top-left corner on the stacked grid
def noise(a): return float(np.median([clipped_stats(a[r:r + 500, c:c + 500])[1] for r, c in PATCHES]))
raw1 = [noise(sg[p]) for p in range(4)]; rawN = [noise(fl[p]) for p in range(4)]
n1 = [noise(rgb1[:, :, k]) for k in range(3)]; nN = [noise(rgb[:, :, k]) for k in range(3)]
lum1 = noise(rgb1.mean(2)); lumN = noise(rgb.mean(2))
# 2. the same stars in the stack and in the reference frame alone (same grid, same method)
qxy = [np.array(v) - [x0, y0] for v in s4['star_xy'].values()]
rows = []
for p in qxy:
    a = measure.star(G, p[0], p[1]); b = measure.star(G1, p[0], p[1])
    if a and b and a['fwhm'] and b['fwhm']: rows.append((a, b))
def med(k, i): return float(np.median([r[i][k] for r in rows]))
shape = dict(stars=len(rows),
             stack=dict(half_flux_diameter_px=round(med('hfd', 0), 2), half_flux_diameter_arcsec=round(med('hfd', 0) * SCALE, 2), fwhm_arcsec=round(med('fwhm', 0) * SCALE, 2), elongation=round(med('elong', 0), 3)),
             single_reference_frame=dict(half_flux_diameter_px=round(med('hfd', 1), 2), half_flux_diameter_arcsec=round(med('hfd', 1) * SCALE, 2), fwhm_arcsec=round(med('fwhm', 1) * SCALE, 2), elongation=round(med('elong', 1), 3)))
# the stack measured exactly as the single frames were in step 4: 2 x 2 binned to the colour-plane grid, step-2 code
import step2_stars as st2
Gb = G[:hh // 2 * 2, :ww // 2 * 2].reshape(hh // 2, 2, ww // 2, 2).mean((1, 3))
G1b = G1[:hh // 2 * 2, :ww // 2 * 2].reshape(hh // 2, 2, ww // 2, 2).mean((1, 3))
pl = [(st2.measure(Gb, (p[0] - 0.5) / 2, (p[1] - 0.5) / 2), st2.measure(G1b, (p[0] - 0.5) / 2, (p[1] - 0.5) / 2)) for p in qxy]
pl = [r for r in pl if r[0] and r[1]]
shape['on_the_plane_grid_as_in_step_4'] = dict(stars=len(pl), stack=dict(half_flux_diameter_arcsec=round(float(np.median([4 * r[0]['hfr'] for r in pl])) * SCALE, 2), elongation=round(float(np.median([r[0]['elong'] for r in pl])), 3)),
                                               single_reference_frame=dict(half_flux_diameter_arcsec=round(float(np.median([4 * r[1]['hfr'] for r in pl])) * SCALE, 2), elongation=round(float(np.median([r[1]['elong'] for r in pl])), 3)))
# coherent elongation of the stack: do the stars lean the same way?
e = np.mean([(r[0]['sig_major'] ** 2 - r[0]['sig_minor'] ** 2) / (r[0]['sig_major'] ** 2 + r[0]['sig_minor'] ** 2) * np.exp(2j * np.radians(r[0]['theta'])) for r in rows])
shape['stack']['common_direction_ellipticity'] = round(float(abs(e)), 3); shape['stack']['common_direction_deg_from_x_axis'] = round(float(np.degrees(np.angle(e)) / 2), 1)
qs = s4['quality']; qu = [q for q in qs if q['stamp'] in USED]
shape['single_frames_of_the_run_planes'] = dict(note='per frame, median over the same stars, measured on the half-size green planes in step 4',
    half_flux_diameter_arcsec=dict(median=round(float(np.median([q['hfd_arcsec'] for q in qu])), 2), best=round(min(q['hfd_arcsec'] for q in qu), 2), worst_used=round(max(q['hfd_arcsec'] for q in qu), 2)),
    elongation=dict(median=round(float(np.median([q['elong_median'] for q in qu])), 3), least=round(min(q['elong_median'] for q in qu), 3), most=round(max(q['elong_median'] for q in qu), 3)))
# 3. how many stars
SKYP = (slice(1500, 2000), slice(1900, 2400))
def counts(img):
    xy, val, sig = measure.count_stars(img, SKYP)
    r = np.hypot(xy[:, 0] - C['cluster'][0], xy[:, 1] - C['cluster'][1])
    incrop = (np.abs(xy[:, 0] - cx) < half) & (np.abs(xy[:, 1] - cy) < half)
    return dict(whole_field=int(len(xy)), in_the_16_arcmin_crop=int(incrop.sum()), within_2_arcmin_of_centre=int((r < 120 / SCALE).sum()), from_2_to_8_arcmin=int(((r >= 120 / SCALE) & (r < 480 / SCALE)).sum()),
                beyond_8_arcmin=int((r >= 480 / SCALE).sum()), threshold_dn=round(5 * sig, 2))
cnt = dict(method='local maxima (9 x 9 px) of the green channel blurred with a Gaussian of sigma 4 px minus the same blurred with sigma 16 px, above 5 x the robust scatter of that image in a 500 px patch of plain sky; same code on the stack and on the reference frame resampled to the same grid',
           stack=counts(G), single_reference_frame=counts(G1))
# 4. clipping in the RAW
ceil_cl = {s: sum(f1[s]['ceiling_pixels_in_cluster'].values()) for s in f1}; ceil_br = {s: sum(f1[s]['ceiling_pixels_in_bright_star'].values()) for s in f1}
clmax = {s: max(f1[s]['cluster_max_dn_above_black'].values()) for s in f1}
clip = dict(ceiling='raw values of 16000 or more (the clipped clump sits at 16116 to 16596; black is 512, so about 15600 to 16084 DN above black)',
            cluster=dict(region='within 800 sensor px (5.2 arcmin) of the cluster centre, fixed hot pixels and single-frame spikes left out', pixels_at_ceiling_per_frame=ceil_cl, total=int(sum(ceil_cl.values())),
                         brightest_pixel_dn_above_black=dict(median_over_frames=float(np.median(list(clmax.values()))), highest=float(max(clmax.values()))), fraction_of_ceiling=round(float(max(clmax.values())) / 16084, 3)),
            stars_within_1500_dn_of_the_ceiling_in_the_reference_frame=[dict(sensor_xy=[round(2 * k['x'] + 0.5), round(2 * k['y'] + 0.5)], plane_max_dn=[int(v) for v in k['plane_max']], arcmin_from_cluster=round(k['r_cluster'] * SCALE / 60, 1),
                                                                             in_the_crop=bool(abs(2 * k['x'] + 0.5 - x0 - cx) < half and abs(2 * k['y'] + 0.5 - y0 - cy) < half)) for k in s2[REF_STAMP]['stars'] if k['saturated']],
            bright_field_star=dict(where_sensor_xy=[round(v, 0) for v in f1[REF_STAMP]['bright_star_sensor_xy']], colour_plane_pixels_at_ceiling_per_frame=ceil_br, median=float(np.median(list(ceil_br.values())))))
# 5. leftover sharp points in the sky
left = []
for p in range(4):
    a = fl[p]; m5 = cv2.medianBlur(a, 5); e_ = a - m5; s = clipped_stats(e_[::3, ::3])[1]
    left.append(dict(plane=PLANE_NAMES[p], above_6_sigma=int(((e_ > 6 * s) & (m5 < 50)).sum()), pixels=int(a.size)))
# 6. cluster light profile (green), ring means
yy, xx = np.mgrid[0:hh:2, 0:ww:2]; rr = np.hypot(xx - C['cluster'][0], yy - C['cluster'][1]); g2 = G[::2, ::2]
prof = []
for a, b in ((0, 20), (20, 50), (50, 100), (100, 200), (200, 300), (300, 450), (450, 600), (600, 800), (800, 1000), (1000, 1250), (1250, 1500), (1500, 2000)):
    m = (rr >= a) & (rr < b); prof.append(dict(r_px=[a, b], r_arcmin=[round(a * SCALE / 60, 2), round(b * SCALE / 60, 2)], green_mean_dn=round(float(g2[m].mean()), 2), green_median_dn=round(float(np.median(g2[m])), 2)))

# ---------------- per-frame table ----------------
sidecars = {}
for f in s1['all_in_window']:
    j = json.load(open(f['path'][:-4] + '.json')); sidecars[f['stamp']] = {x['format']: x['sha256'] for x in j['files']}
tq = {o['stamp']: o for o in qs}; tt = {o['stamp']: o for o in s3}; why = {r['stamp']: r['why'] for r in sel['rejected']}
bar = (s4b.get('moving') or {}).get('place_per_frame_sensor_xy', {})
frames = []
for f in s1['frames']:
    o = tt[f['stamp']]; q = tq[f['stamp']]
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], altitude_deg=round(f['alt_deg'], 1) if f.get('alt_deg') else None, arw_sha256=sidecars[f['stamp']].get('arw'),
                       used=f['stamp'] in USED, rejected_because=why.get(f['stamp']),
                       black_level=f['black'], sky_subtracted_dn=dict(zip(PLANE_NAMES, [round(b['clipped_mean'], 3) for b in f['bg']])), sky_noise_dn=dict(zip(PLANE_NAMES, [round(b['clipped_std'], 2) for b in f['bg']])),
                       white_balance_as_shot=f['wb'], orientation_flag=f['flip'], transient_spikes_replaced=f['transient_spikes_replaced'],
                       cluster_centre_sensor_xy=[round(v, 0) for v in f['cluster_sensor_xy']], moving_shadow_sensor_xy=bar.get(f['stamp']),
                       shift_at_frame_centre_px=[round(v, 3) for v in o['shift_at_centre_px']], rotation_deg=round(o['rotation_deg'], 4), transform_R=o['R'], transform_t=o['t'],
                       registration=dict(stars_used=o['used'], weighted_rms_px=round(o['wrms_px'], 3), scale_if_left_free=round(o['similarity_scale'], 5)),
                       stars_detected=q['stars_detected'], half_flux_diameter_arcsec=round(q['hfd_arcsec'], 2), elongation_median=round(q['elong_median'], 3), common_direction_ellipticity=round(q['coherent_ellipticity'], 3),
                       brightness_relative=round(q['flux_rel'], 4), peak_relative=round(q['peak_rel'], 3),
                       cluster_pixels_at_ceiling=ceil_cl[f['stamp']], bright_star_pixels_at_ceiling=ceil_br[f['stamp']]))
left_out = [dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='in the time window but a 2 s ISO 6400 focusing frame, not 15 s ISO 1600') for f in s1['all_in_window'] if not (f['exposure_s'] == EXPOSURE_S and f['iso'] == ISO)]
sh = np.array([o['shift_at_centre_px'] for o in s3]); rot = np.array([o['rotation_deg'] for o in s3])
tsec = lambda s: datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
span = tsec(s1['frames'][-1]['t']) - tsec(s1['frames'][0]['t'])
iu = [i for i, o in enumerate(s3) if o['stamp'] in USED]; span_u = tsec(f1[USED[-1]]['t']) - tsec(f1[USED[0]]['t'])
net = float(np.hypot(*(sh[-1] - sh[0]))); path = float(np.hypot(*np.diff(sh, axis=0).T).sum())
motion = dict(all_frames_at_15s=dict(span_s=round(span, 1), rotation_first_deg=round(float(rot[0]), 4), rotation_last_deg=round(float(rot[-1]), 4), rotation_total_deg=round(float(rot[-1] - rot[0]), 4), rotation_deg_per_minute=round(float((rot[-1] - rot[0]) / span * 60), 4),
                  drift_net_px=round(net, 1), drift_net_arcsec=round(net * SCALE, 1), drift_net_arcsec_per_s=round(net * SCALE / span, 4), drift_path_px=round(path, 1), drift_path_arcsec_per_s=round(path * SCALE / span, 4),
                  frame_to_frame_px=[round(float(v), 1) for v in np.hypot(*np.diff(sh, axis=0).T)], shift_x_range_px=[round(float(sh[:, 0].min()), 1), round(float(sh[:, 0].max()), 1)], shift_y_range_px=[round(float(sh[:, 1].min()), 1), round(float(sh[:, 1].max()), 1)]),
              used_frames=dict(span_s=round(span_u, 1), rotation_total_deg=round(float(rot[iu[-1]] - rot[iu[0]]), 4), drift_net_px=round(float(np.hypot(*(sh[iu[-1]] - sh[iu[0]]))), 1)),
              corner_smear_if_not_rotated_px=round(float(np.radians(abs(rot[iu[-1]] - rot[iu[0]])) * np.hypot(3012, 2012)), 1), rotation_during_one_15s_frame_at_corner_px=round(float(np.radians(abs(rot[-1] - rot[0]) / span * 15) * np.hypot(3012, 2012)), 2))
tools = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=getattr(rawpy, 'libraw_version', None), tifffile=tifffile.__version__, pillow=PIL.__version__,
             note='deterministic array arithmetic only; nothing generative or learned')
numbers = dict(
    star_shape_same_stars=dict(note='%d stars outside the crowded core, not saturated, no neighbour within 40 px, present in every frame; green channel; 28 px aperture, sky ring 38 to 54 px' % len(rows), **shape),
    sky_noise=dict(units='DN per sensor-grid pixel, 3-sigma clipped standard deviation, median of four 500 px patches of plain sky; single = the reference frame %s through the same repair, dust division and resampling' % REF_STAMP,
                   raw_planes_single=dict(zip(PLANE_NAMES, [round(v, 2) for v in raw1])), raw_planes_stack=dict(zip(PLANE_NAMES, [round(v, 2) for v in rawN])),
                   white_balanced_single=dict(zip('RGB', [round(v, 2) for v in n1])), white_balanced_stack=dict(zip('RGB', [round(v, 2) for v in nN])),
                   mean_of_rgb_single=round(lum1, 2), mean_of_rgb_stack=round(lumN, 2), improvement=dict(zip('RGB', [round(a / b, 2) for a, b in zip(n1, nN)])), improvement_mean_of_rgb=round(lum1 / lumN, 2), ideal_sqrt_frames=round(n_used ** 0.5, 2)),
    stars_detected=cnt, raw_clipping=clip, cluster_green_profile=prof, cluster_centre_sensor_px=[round(C['cluster'][0] + x0, 1), round(C['cluster'][1] + y0, 1)], leftover_sharp_points_in_sky=left,
    sky_brightness_dn_per_15s=dict(zip(PLANE_NAMES, [round(float(np.median([f1[s]['bg'][p]['clipped_mean'] for s in USED])), 1) for p in range(4)])))
recipe = dict(
    what='M15 (globular cluster in Pegasus), %d x 15 s at ISO 1600 (%.2f minutes), Sony a6000 on a Celestron 8SE at f/10, stacked from RAW colour planes' % (n_used, n_used * 15 / 60),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tools=tools,
    source=dict(folder=STILLS, window_utc=[T0, T1], frames_found_in_window=len(s1['all_in_window']), frames_at_15s_iso1600=len(s1['frames']), frames_used=n_used,
                frames_rejected=[dict(file=f1[r['stamp']]['name'], why=r['why'], half_flux_diameter_arcsec=round(r['hfd_arcsec'], 2), elongation=round(r['elongation'], 3), brightness_relative=round(r['brightness_rel'], 3), stars_detected=r['stars_detected']) for r in sel['rejected']],
                left_out=left_out, not_used='the earlier M15 run 0659 to 0706 UTC (before the refocus) is not in this stack', originals='read in place, not modified'),
    frames=frames,
    rejection=dict(rule='reject a frame if its stars are dimmer than 0.90 x the run median, or its half-flux diameter is more than 1.10 x the run median, or its median elongation is above 1.40, or its registration weighted rms is above 1.0 px',
                   limits=sel['limits'], half_flux_diameter_run_median_arcsec=round(sel['hfd_run_median_arcsec'], 2), quality_stars=s4['quality_stars']),
    motion=motion,
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (sensor orientation, 6024 x 4024, RGGB), black level 512 subtracted; four colour planes R, G1, G2, B kept apart at 3012 x 2012, no demosaic'),
        dict(step='sky', detail='per frame and per plane: 3-sigma clipped mean of the plane outside %d px of the cluster and %d px of the saturated field star, subtracted (clipped mean rather than median because the RAW values step in 4 DN)' % (CLUSTER_SKY_RADIUS, BRIGHT_SKY_RADIUS)),
        dict(step='hot pixels', detail='fixed: per-plane median of all frames without registration, pixels standing above the 5x5 median of that by more than max(6 sigma, 25% of the level); transient: per frame, pixels above the 3x3 median by more than 8 sigma + 50% of the level. Both replaced by the 3x3 median of the same colour plane before resampling.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s1['hot']}, fraction_of_plane={h['plane']: round(h['frac'], 5) for h in s1['hot']}),
        dict(step='stars', detail='green planes averaged (half-size grid), Gaussian blur sigma 2.5, 6-sigma threshold, connected blobs; Gaussian-windowed centroid (sigma 5 plane px); 28 px (sensor) aperture for flux, second moments and half-flux radius. Each star is tagged with its distance from the cluster centre, the distance to its nearest neighbour and whether it is within 1500 DN of the ceiling.'),
        dict(step='register', detail='reference frame %s. Only stars more than %d px (%.1f arcmin) from the cluster centre, not saturated, with no neighbour within 40 px and brighter than 5000 DN. Coarse offset from a vote over all pairs of the 80 brightest (8 px bins); then weighted least-squares rotation + shift, match radius tightened 30, 12, 4 px, weights 1/(0.25^2 + (7000/flux)^2) px^-2, 3.5-sigma rejection. This is a similarity transform with the scale held at 1: with the scale left free it came out between %.5f and %.5f.' % (REF_STAMP, CORE_RADIUS, CORE_RADIUS * SCALE / 60, min(o['similarity_scale'] for o in s3), max(o['similarity_scale'] for o in s3)),
             stars_used_range=[min(o['used'] for o in s3 if o['stamp'] != REF_STAMP), max(o['used'] for o in s3 if o['stamp'] != REF_STAMP)], weighted_rms_px_range=[round(min(o['wrms_px'] for o in s3 if o['stamp'] != REF_STAMP), 3), round(max(o['wrms_px'] for o in s3), 3)]),
        dict(step='shadows on the sensor', detail='no flat field exists. Shadows were measured in the run\'s own sky and divided out before resampling: (value + frame sky) / transmission - frame sky. Fixed dust: unregistered median of the green planes, 5x5 median, Gaussian blur, over its own large-scale version; patches below 0.97 of at least 100 plane px, grown 6 px; none within 800 px of the cluster (cannot be measured there). One hair-like shadow moved across the sensor during the run and was followed frame by frame; its transmission is the median of the frames lined up on it. Leaving the shadowed pixels out instead was tried first and left sky positions with no clean frame.', measured=s4b),
        dict(step='resample', detail='each plane of each frame mapped straight onto the reference frame sensor grid (rotation + shift + the plane\'s own place in the 2x2 colour cell) with OpenCV remap, Lanczos-4. The stacked area is the rectangle that every used frame covers.',
             stacked_area_sensor_px=dict(x0=x0, y0=y0, width=ww, height=hh)),
        dict(step='combine', detail='per pixel, per plane: reject values more than 3 sigma from the median (sigma = 1.4826 x MAD, floor half the single-frame noise), then again 3 sigma about the mean of the survivors, then the mean. Equal weights; no brightness scaling (the used frames agree to %.1f%%).' % (100 * max(abs(q['flux_rel'] - 1) for q in qu)),
             kappa=s5['kappa'], per_plane=s5['planes']),
        dict(step='subtract sky', detail='the sky left over is a shallow dome (vignetted sky glow). A 2nd-order polynomial surface fitted to 2.5-sigma-clipped means of 128 px blocks is subtracted from each plane. Blocks within %d px (%.1f arcmin) of the cluster centre and near bright stars take no part; under the cluster the surface is the polynomial carried across. Cluster light is measurable in the block means out to about 7 arcmin (+0.9 DN at 4.5 to 5.8 arcmin, +0.4 DN at 5.8 to 7.1, under 0.1 DN beyond), so the exclusion radius is outside it. No flat field: star brightness is not corrected for vignetting.' % (CLUSTER_SKY_RADIUS, CLUSTER_SKY_RADIUS * SCALE / 60), fit=s6),
        dict(step='colour', detail='G = mean of G1 and G2; R x %.4f and B x %.4f: the camera\'s as-shot white balance from the RAW (median over the used frames). No colour matrix, no saturation change: white-balanced camera-native colours.' % (wb_r, wb_b),
             white_balance_multipliers=dict(R=wb_r, G=1.0, B=wb_b), as_shot_raw=[float(v) for v in wb]),
    ],
    numbers=numbers,
    outputs={
        'm15-stack.png / .jpg': dict(crop_sensor_px=dict(centre=[cx + x0, cy + y0], width=CROP, height=CROP), field_arcmin=[round(CROP * SCALE / 60, 2), round(CROP * SCALE / 60, 2)], resampling='none: one image pixel is one sensor pixel', pixel_scale_arcsec=SCALE, size_px=[c8.shape[1], c8.shape[0]],
                                     stretch=dict(kind='arcsinh, same gain for R, G and B of a pixel (colour ratios kept), then the sRGB transfer curve', formula='each channel capped at white; I = max(R,G,B) + pedestal; out = (RGB + pedestal) * asinh(I/soft) / (I * asinh((white + pedestal)/soft)); clip 0..1; sRGB OETF; 8 bit', **STRETCH),
                                     brightest_value_dn=float(crop.max()), pixels_at_255_in_any_channel=int((c8 == 255).any(2).sum()), sky_level_8bit=[int(v) for v in np.median(c8[:300, :300].reshape(-1, 3), axis=0)], jpg='quality 92, 4:4:4, no metadata'),
        'm15-single-frame.png / .jpg': dict(what='extra, for comparison: the reference frame %s alone, same hot-pixel repair, same dust division, same grid, same sky surface, same crop, same stretch' % REF_STAMP),
        'm15-stack-field.png / .jpg': dict(area='the whole stacked area, %d x %d sensor px (%.1f x %.1f arcmin)' % (fw, fh, fw * SCALE / 60, fh * SCALE / 60), resampling='2x2 block mean (cv2.resize INTER_AREA)', pixel_scale_arcsec=SCALE * FIELD_BIN, size_px=[f8.shape[1], f8.shape[0]],
                                           stretch=dict(kind='same arcsinh formula and numbers as the crop', **STRETCH), pixels_at_255_in_any_channel=int((f8 == 255).any(2).sum())),
        'm15-linear.tif': dict(what='the stack, linear, 32-bit float RGB, white balance applied, sky at 0, not stretched', units='DN of the 14-bit RAW scale per 15 s frame (green as measured; R and B multiplied by the white balance)', size_px=[ww, hh], pixel_scale_arcsec=SCALE,
                               origin='pixel (0,0) is sensor pixel (%d,%d) of the reference frame' % (x0, y0), compression='zlib, lossless', note='the saturated field star is not valid above the ceiling: its core is flat-topped and takes a false tint from the white-balance multipliers'),
    },
    orientation='sensor orientation of the RAW (as rawpy raw_image_visible); not rotated to north and not plate solved here',
    scripts='scripts/ beside this file: common.py, step1_hot.py, step2_stars.py, step3_register.py, step4_quality.py, step4b_dust.py, step4c_select.py, step5_stack.py, step6_flatten.py, step7_deliver.py, render.py, measure.py (adapted from ../ngc7662/scripts)',
)
json.dump(recipe, open(W('recipe_core.json'), 'w'), indent=1)
if DRY: json.dump(recipe, open(os.path.join(DEST, 'm15-recipe.json'), 'w'), indent=1)
print(json.dumps(numbers['star_shape_same_stars'], indent=1)); print(json.dumps(numbers['sky_noise'], indent=1)); print(json.dumps(numbers['stars_detected'], indent=1))
print(json.dumps({k: v for k, v in clip['cluster'].items() if k != 'pixels_at_ceiling_per_frame'}, indent=1)); print('bright star ceiling median', clip['bright_field_star']['median'])
print(json.dumps(motion, indent=1)); print(json.dumps(left, indent=1)); print(json.dumps(recipe['outputs'], indent=1))
