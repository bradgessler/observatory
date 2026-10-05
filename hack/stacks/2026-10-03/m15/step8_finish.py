"""Step 8 (run with M15_RUN=sharp after step 7): the extra comparison picture from the run before the refocus,
its own recipe, and the last sections of the main recipe (deconvolution trial, comparison, caveats)."""
import json, os, sys, shutil, datetime
import numpy as np, cv2
from PIL import Image
from common import *
from render import *
import measure, step2_stars as st2

DRY = len(sys.argv) > 1 and sys.argv[1] == 'dry'
DEST = W('out_dry') if DRY else OUT
SOFT = os.path.join(SCR, 'soft')
def Wsoft(n): return os.path.join(SOFT, n)
core = json.load(open(W('recipe_core.json')))
STRETCH = core['outputs']['m15-stack.png / .jpg']['stretch']; ST = {k: STRETCH[k] for k in ('white', 'soft', 'pedestal', 'smooth_sigma')}
CROP = core['outputs']['m15-stack.png / .jpg']['crop_sensor_px']['width']; half = CROP // 2

# ---------- the run before the refocus ----------
fl = np.load(Wsoft('stack_flat.npy')); s1 = json.load(open(Wsoft('step1.json'))); s3 = json.load(open(Wsoft('step3_transforms.json'))); s4 = json.load(open(Wsoft('step4_quality.json')))
s4b = json.load(open(Wsoft('step4b_dust.json'))); s5 = json.load(open(Wsoft('step5.json'))); s6 = json.load(open(Wsoft('step6.json'))); C = json.load(open(Wsoft('centres.json'))); sel = json.load(open(Wsoft('step4c_select.json')))
x0, y0 = s5['origin_sensor_xy']; USED = s5['used']; f1 = {f['stamp']: f for f in s1['frames']}
wb = np.median(np.array([f1[s]['wb'] for s in USED]), axis=0); wb_r, wb_b = float(wb[0] / wb[1]), float(wb[2] / wb[1])
rgb = rgb_from_planes(fl, wb_r, wb_b); hh, ww = rgb.shape[:2]
cx, cy = int(round(C['cluster'][0])), int(round(C['cluster'][1]))
assert cy - half >= 0 and cx - half >= 0 and cy + half <= hh and cx + half <= ww
crop = rgb[cy - half:cy + half, cx - half:cx + half]; c8 = asinh_stretch(crop, **ST)
im = Image.fromarray(c8, 'RGB'); im.save(os.path.join(DEST, 'm15-before-refocus-stack.png'), optimize=True); im.save(os.path.join(DEST, 'm15-before-refocus-stack.jpg'), quality=92, subsampling=0)
G = np.ascontiguousarray(rgb[:, :, 1])
Gb = G[:hh // 2 * 2, :ww // 2 * 2].reshape(hh // 2, 2, ww // 2, 2).mean((1, 3))
qxy = [np.array(v) - [x0, y0] for v in s4['star_xy'].values()]
pl = [st2.measure(Gb, (p[0] - 0.5) / 2, (p[1] - 0.5) / 2) for p in qxy]; pl = [r for r in pl if r]
PATCHES = [(1500, 1900), (2700, 600), (300, 500), (3000, 4300)]
def noise(a): return float(np.median([clipped_stats(a[r:r + 500, c:c + 500])[1] for r, c in PATCHES]))
xy, val, sig = measure.count_stars(G, (slice(1500, 2000), slice(1900, 2400)))
incrop = (np.abs(xy[:, 0] - cx) < half) & (np.abs(xy[:, 1] - cy) < half)
qs = s4['quality']; rot = np.array([o['rotation_deg'] for o in s3]); sh = np.array([o['shift_at_centre_px'] for o in s3])
soft_numbers = dict(frames=len(USED), total_exposure_s=15 * len(USED),
    star_half_flux_diameter_arcsec=dict(single_frames_median=round(float(np.median([q['hfd_arcsec'] for q in qs])), 2), single_frames_range=[round(min(q['hfd_arcsec'] for q in qs), 2), round(max(q['hfd_arcsec'] for q in qs), 2)],
                                        stack=round(float(np.median([4 * r['hfr'] for r in pl])) * SCALE, 2), method='as step 4: half-size green planes, 28 px aperture; the stack 2 x 2 binned to the same grid', stars=len(pl)),
    elongation=dict(single_frames_median=round(float(np.median([q['elong_median'] for q in qs])), 3), stack=round(float(np.median([r['elong'] for r in pl])), 3)),
    sky_noise_white_balanced_stack=dict(zip('RGB', [round(noise(rgb[:, :, k]), 2) for k in range(3)])),
    stars_detected_stack=dict(whole_field=int(len(xy)), in_the_16_arcmin_crop=int(incrop.sum()), threshold_dn=round(5 * sig, 2)),
    rotation_total_deg=round(float(rot[-1] - rot[0]), 4), drift_net_px=round(float(np.hypot(*(sh[-1] - sh[0]))), 1))
soft_recipe = dict(
    what='M15 BEFORE the refocus, %d x 15 s at ISO 1600: an extra, quick stack made only to show what the refocus changed. Not the delivered picture.' % len(USED),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tools=core['tools'],
    source=dict(folder=STILLS, window_utc=[RUNS['soft']['t0'], RUNS['soft']['t1']], frames_found_in_window=len(s1['all_in_window']), frames_at_15s_iso1600=len(s1['frames']), frames_used=len(USED), frames_rejected=[dict(file=f1[r['stamp']]['name'], why=r['why']) for r in sel['rejected']],
                files=[dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], used=f['stamp'] in USED) for f in s1['frames']], originals='read in place, not modified'),
    pipeline='the same scripts and the same parameters as m15-recipe.json (see its steps): black level, per-frame sky, hot pixels, star registration with rotation, dust division (fixed dust only: the moving hair-like shadow is not in these frames), 3-sigma clipped mean, 2nd-order sky surface with the cluster left out, camera white balance R x %.4f, B x %.4f' % (wb_r, wb_b),
    reference_frame=RUNS['soft']['ref'], rejection=dict(limits=sel['limits'], result='no frame crossed a limit'),
    per_frame=[dict(stamp=q['stamp'], half_flux_diameter_arcsec=round(q['hfd_arcsec'], 2), elongation=round(q['elong_median'], 3), brightness_relative=round(q['flux_rel'], 4), rotation_deg=round(o['rotation_deg'], 4), shift_at_frame_centre_px=[round(v, 2) for v in o['shift_at_centre_px']], registration_weighted_rms_px=round(o['wrms_px'], 3)) for q, o in zip(qs, s3)],
    dust=dict(fixed_patches=len(s4b['fixed']['patches']), corrected_fraction=s4b['fixed']['corrected_fraction'], moving_shadow=None), combine=dict(kappa=s5['kappa'], per_plane=s5['planes']), sky_surface=s6,
    white_balance_multipliers=dict(R=wb_r, G=1.0, B=wb_b), numbers=soft_numbers,
    output={'m15-before-refocus-stack.png / .jpg': dict(crop_sensor_px=dict(centre=[cx + x0, cy + y0], width=CROP, height=CROP), field_arcmin=[round(CROP * SCALE / 60, 2)] * 2, resampling='none', pixel_scale_arcsec=SCALE, size_px=[CROP, CROP], stretch=STRETCH,
                                                 note='same crop size and the same stretch as m15-stack; its own reference frame, so the field is turned about 1.9 degrees and shifted against m15-stack; 14 frames against 23, so the sky is also noisier', jpg='quality 92, 4:4:4, no metadata')},
    orientation=core['orientation'], scripts='scripts/ beside this file, run with M15_RUN=soft')
json.dump(soft_recipe, open(os.path.join(DEST, 'm15-before-refocus-recipe.json'), 'w'), indent=1)
print('before the refocus:', json.dumps(soft_numbers, indent=1))

# ---------- the main recipe ----------
dr = json.load(open(W('decon_report.json'))); n = core['numbers']; shp = n['star_shape_same_stars']
core['deconvolution'] = dict(delivered=False, tried='Richardson-Lucy, 5 and 10 rounds, pedestal 100 DN, on the 16 arcmin crop; blur = median of 13 isolated unsaturated stars of this stack (per channel, 32 px radius, each centred and scaled to unit flux); checked on 9 other isolated stars',
    result={k: dict(half_flux_diameter_arcsec=round(v['hfd_arcsec'], 2), fwhm_arcsec=round(v['fwhm_arcsec'], 2), sky_noise_green_dn=round(v['sky_noise_green'], 2), deepest_point_of_ring_profile_as_fraction_of_peak=dict(median=round(v['deepest_fraction_of_peak']['median'], 4), worst=round(v['deepest_fraction_of_peak']['worst'], 4)))
            for k, v in (('plain', dr['0']), ('5_rounds', dr['5']), ('10_rounds', dr['10']))},
    why_not='it draws a dark moat around every star that is not in the plain stack: the ring profile around the check stars dips to 1.9% of the star\'s peak below the sky after 5 rounds and 2.5% after 10 (worst 3.0% and 6.7%), against 0.2% (noise) in the plain stack. For a star peaking at 2000 DN that is a ring 40 DN below a sky whose noise is 4.5 DN: black rings, plain to see in the core. Cause: the star shape is not the same across the field (the stars lean different ways), so one measured blur does not fit all of them. Not delivered.')
core['before_refocus_comparison'] = dict(file='m15-before-refocus-stack.png / .jpg, recipe m15-before-refocus-recipe.json', **soft_numbers,
    what_the_refocus_did='half-flux diameter of single frames %.2f arcsec before, %.2f after (%.0f%% smaller); stacks %.2f against %.2f' % (soft_numbers['star_half_flux_diameter_arcsec']['single_frames_median'], shp['single_frames_of_the_run_planes']['half_flux_diameter_arcsec']['median'],
        100 * (1 - shp['single_frames_of_the_run_planes']['half_flux_diameter_arcsec']['median'] / soft_numbers['star_half_flux_diameter_arcsec']['single_frames_median']), soft_numbers['star_half_flux_diameter_arcsec']['stack'], shp['on_the_plane_grid_as_in_step_4']['stack']['half_flux_diameter_arcsec']))
s1s = json.load(open(W('step1.json'))); use = core['frames']; fu = [f for f in s1s['frames'] if f['stamp'] in [l.strip() for l in open(W('use.txt'))]]
sky = np.array([[b['clipped_mean'] for b in x['bg']] for x in fu]).mean(0); var = (np.array([[b['clipped_std'] for b in x['bg']] for x in fu]) ** 2).mean(0)
(rn2, inv_g), *_ = np.linalg.lstsq(np.stack([np.ones(4), sky], 1), var, rcond=None)
core['numbers']['noise_budget_estimate'] = dict(method='rough: per-plane sky noise squared against sky level over R, G1, G2, B (four points, straight line): intercept = read noise, slope = 1/gain', read_noise_dn=round(float(rn2 ** 0.5), 1), gain_e_per_dn=round(float(1 / inv_g), 3),
    sky_shot_noise_dn=dict(zip(PLANE_NAMES, [round(float(v), 1) for v in np.sqrt(sky * inv_g)])), reading='at 15 s the camera\'s read noise (about 21 DN) is as large as the sky\'s own noise in green and larger in red and blue: the frames are too short to be limited by the sky')
d4 = json.load(open(W('step4b_dust.json')))
core['caveats'] = [
    'Short: %d frames, %.2f minutes in all. The sky noise fell %.2f times (ideal %.2f). The faint outer stars are there but grainy; colour noise in red and blue is 2 to 3 times the green.' % (len(core['frames']) - len(core['source']['frames_rejected']), (len(core['frames']) - len(core['source']['frames_rejected'])) * 0.25, n['sky_noise']['improvement_mean_of_rgb'], n['sky_noise']['ideal_sqrt_frames']),
    'Stars are %.1f arcsec across (half-flux diameter; FWHM %.1f) and not round: elongation %.2f in the stack, %.2f in single frames. They do not all lean the same way (common-direction ellipticity %.3f), and the mean drift during 15 s (about 1.1 to 1.6 arcsec) is too small to explain it: the shape is mostly the optics (collimation or tilt) and seeing, not trailing. The inner 30 arcsec of the cluster is an unresolved glow.' % (shp['stack']['half_flux_diameter_arcsec'], shp['stack']['fwhm_arcsec'], shp['stack']['elongation'], shp['single_frames_of_the_run_planes']['elongation']['median'], shp['stack']['common_direction_ellipticity']),
    'No dark frames and no flat field. Hot pixels were replaced as described. Dust shadows were divided out using the run\'s own sky (%.1f%% of the sensor in %d patches: mostly small dust rings 3 to 6%% deep, a few spots up to %.0f%% deep; and one hair-like shadow up to %.0f%% deep that moved %.0f px across the sensor during the run and was followed frame by frame). Inside 5.2 arcmin of the cluster centre dust cannot be measured from these frames and is not corrected; small rings there would dim stars by a few percent along short streaks. Vignetting is not corrected.' % (100 * d4['fixed']['corrected_fraction'], len(d4['fixed']['patches']), 100 * (1 - d4['fixed']['smallest_divisor']), 100 * (1 - d4['moving']['deepest_transmission']), d4['moving']['moved_sensor_px']),
    'Left in the sky after all that: mottling of about +-1 DN on scales of hundreds of pixels (sky noise per pixel is 4.5 DN in green), and a few faint streaks about 1 DN deep from dust rings below the threshold. The hair-like shadow was not on the sensor in the run before the refocus (0659 to 0706 UTC) nor in the NGC 7662 run an hour earlier.',
    'Cluster light is measurable out to about 7 arcmin from the centre; the sky fit leaves out everything inside 8.1 arcmin, so the outer halo beyond that, if any, was treated as sky (under 0.1 DN).',
    'Colour is the camera\'s white balance only, with no camera-to-sRGB matrix: hues are camera-native and a colour-managed rendering would be more saturated.',
    'Four field stars reach the sensor ceiling in the RAW (two of them inside the crop: 6.6 and 7.7 arcmin from the cluster centre). Their cores are flat-topped; in the pictures each channel is capped at the white point so they come out white. The cluster itself is not clipped anywhere: its brightest pixel is %.0f DN above black, %.0f%% of the ceiling.' % (n['raw_clipping']['cluster']['brightest_pixel_dn_above_black']['highest'], 100 * n['raw_clipping']['cluster']['fraction_of_ceiling']),
    'The single comparison frame had the same hot-pixel repair, dust division and sky surface, so the comparison shows the gain from averaging only. It is one of the sharper frames (%.2f arcsec against a run median of %.2f).' % (shp['on_the_plane_grid_as_in_step_4']['single_reference_frame']['half_flux_diameter_arcsec'], shp['single_frames_of_the_run_planes']['half_flux_diameter_arcsec']['median']),
    'The two rejected end frames (first and last of the run) had dimmer stars and a brighter sky at the same time, the first with a 26 DN left-to-right gradient: stray light or something in front of the tube, not seeing. The first came 32 s after the last focusing frame; the last was followed by a slew.',
]
core['scripts'] = 'scripts/ beside this file: common.py, step1_hot.py, step2_stars.py, step3_register.py, step4_quality.py, step4b_dust.py, step4c_select.py, step5_stack.py, step6_flatten.py, step7_deliver.py, step8_finish.py, render.py, measure.py; decon.py and try_decon.py are the rejected deconvolution trial. Adapted from ../ngc7662/scripts. Run order as numbered; M15_RUN=soft repeats steps 1 to 6 for the run before the refocus.'
json.dump(core, open(os.path.join(DEST, 'm15-recipe.json'), 'w'), indent=1)
if not DRY:
    os.makedirs(os.path.join(OUT, 'scripts'), exist_ok=True)
    for f in ('common.py', 'step1_hot.py', 'step2_stars.py', 'step3_register.py', 'step4_quality.py', 'step4b_dust.py', 'step4c_select.py', 'step5_stack.py', 'step6_flatten.py', 'step7_deliver.py', 'step8_finish.py', 'render.py', 'measure.py', 'decon.py', 'try_decon.py'):
        shutil.copyfile(os.path.join(SCR, f), os.path.join(OUT, 'scripts', f))
print('wrote', DEST)
