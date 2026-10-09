"""Step 11: recipe.json beside the pictures: every number that shaped them, which frames and why the others were
dropped, the flat and its checks, the registration, the weights, the sky constants, the zero and how uncertain it is,
the stretch, the finish, the tools. Also measures, from the comparison stacks of step 8 (A: no flat; L: no dust model;
S: the dropped green-shaped colour flats), what the flat and the dust model do, and the flat check (first third of the
run against the last third)."""
import os, sys, json, datetime, platform, subprocess
import numpy as np, cv2, rawpy, scipy, tifffile, PIL
from common import *

S1 = {f['stamp']: f for f in jload('step1.json')['frames']}; S2 = jload('step2.json'); S2f = {f['stamp']: f for f in S2['frames']}
S4 = jload('step4_transforms.json'); tr = {o['stamp']: o for o in S4['transforms']}
S5 = {o['stamp']: o for o in jload('step5_quality.json')['quality']}
S6 = jload('step6_flat.json'); S6b = jload('step6b_dustcheck.json'); S7 = jload('step7_select.json')
S8 = jload('step8_F.json'); S9 = jload('step9.json'); S9b = jload('step9b_solve.json'); S10 = jload('step10.json')
used = {u['stamp']: u for u in S7['used']}; rej = {r['stamp']: r for r in S7['rejected']}
x0, y0, x1, y1 = S9['rect_plane_px']; lev = S9['zero']['levels_subtracted_dn']
wb_r, wb_b = S9['wb']['R'], S9['wb']['B']


def glow(ver, levels=None):
    st = np.load(W('%s_mean.npy' % ver))[:, y0:y1, x0:x1]
    G = (st[1] + st[2]) / 2
    if levels is None:
        small = cv2.resize(G, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA); sm = cv2.GaussianBlur(cv2.medianBlur(small, 5), (0, 0), 4)
        ok = np.zeros_like(sm, bool); e = 100 // 8; ok[e:-e, e:-e] = True
        dark = cv2.resize(((sm <= np.percentile(sm[ok], 1)) & ok).astype(np.uint8), (G.shape[1], G.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool)
        levels = [float(clipped_stats(st[p][dark][::2])[0]) for p in range(4)]
    R = (st[0] - levels[0]) * wb_r; Gg = (st[1] + st[2] - levels[1] - levels[2]) / 2; B = (st[3] - levels[3]) * wb_b
    b = 244; ny, nx = Gg.shape[0] // b, Gg.shape[1] // b
    bm = lambda a: np.median(a[:ny * b, :nx * b].reshape(ny, b, nx, b).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    g, r, bb = bm(Gg).astype(np.float64), bm(R).astype(np.float64), bm(B).astype(np.float64)
    return dict(levels_dn=[round(v, 2) for v in levels], green_dn=np.round(g, 1).tolist(), red_minus_green_dn=np.round(r - g, 1).tolist(), blue_minus_green_dn=np.round(bb - g, 1).tolist())


comparisons = {}
for ver, what in (('A', 'no flat at all (as recorded)'), ('S', 'red and blue flats shaped like green (dropped)'), ('F', 'delivered')):
    if os.path.exists(W('%s_mean.npy' % ver)): comparisons[ver] = dict(what=what, **glow(ver))
# the dust model: the light it put back where the confirmed shadows sit (the reference frame's sensor = the stack grid)
dust_effect = None
if os.path.exists(W('L_mean.npy')):
    F = np.load(W('F_mean.npy'))[1:3].mean(0); L = np.load(W('L_mean.npy'))[1:3].mean(0)
    dm = np.load(W('dust_model.npz')); bs = int(dm['bs']); conf = dm['confirmed']
    tot = F + (lev['G1'] + lev['G2']) / 2 * 0          # F and L both carry the sky (no zero subtracted yet): a ratio of totals
    ratio = []
    lab_n, lab = cv2.connectedComponents(conf.astype(np.uint8))
    for i in range(1, lab_n):
        ys, xs = np.nonzero(lab == i); cx, cy = xs.mean() * bs + (bs - 1) / 2, ys.mean() * bs + (bs - 1) / 2
        if not (x0 + 20 < cx < x1 - 20 and y0 + 20 < cy < y1 - 20): continue
        sl = (slice(int(cy) - 6, int(cy) + 7), slice(int(cx) - 6, int(cx) + 7))
        ratio.append(float(np.median(L[sl] / F[sl])))
    ratio = np.array(ratio)
    dust_effect = dict(what='at the centre of each confirmed shadow inside the crop (13 x 13 px), the stack without the dust model over the delivered stack (both with the sky in): how much light the dust model put back. In the stack a shadow is smeared by the field drift (about 84 sensor px over the series) and the turn',
                       shadows=int(len(ratio)), light_restored_pct=dict(median=round(float(100 * (1 - np.median(ratio))), 2), largest=round(float(100 * (1 - ratio.min())), 2)) if len(ratio) else None)
    del F, L
# flat check: first third against last third, 244 px blocks, green
flatcheck = None
if os.path.exists(W('F_early.npy')):
    e = np.load(W('F_early.npy'))[1:3].mean(0)[y0:y1, x0:x1]; l_ = np.load(W('F_late.npy'))[1:3].mean(0)[y0:y1, x0:x1]
    d = e - l_; b = 244; ny, nx = d.shape[0] // b, d.shape[1] // b
    with np.errstate(all='ignore'):
        db = np.nanmedian(d[:ny * b, :nx * b].reshape(ny, b, nx, b).transpose(0, 2, 1, 3).reshape(ny, nx, -1), axis=2)
    flatcheck = dict(what='green, (stack of the first third of the run) - (last third), 244 px block medians, DN: the field sits differently on the sensor in the two (about 50 to 80 sensor px apart and turned 0.4 degrees), so a flat error would show as a pattern here; small drift makes this a weak test',
                     rms_dn=round(float(np.sqrt(np.nanmean((db - np.nanmedian(db)) ** 2))), 2), min_dn=round(float(np.nanmin(db - np.nanmedian(db))), 2), max_dn=round(float(np.nanmax(db - np.nanmedian(db))), 2))

frames = []
for s in sorted(S1):
    f = S1[s]; q = S5.get(s, {}); t = tr.get(s, {})
    row = dict(file=f['name'], shutter_pressed_utc=f['t'], seq=f['seq'], exposure_s=f['exif_exposure_s'], iso=f['exif_iso'], sidecar_exposure_s=f['sidecar_exposure_s'], sidecar_iso=f['sidecar_iso'],
               altitude_deg=round(f['alt_deg'], 1), seconds_after_last_slew=f['since_slew_s'], had_box_plate_solve=f['had_plate_solve'], arw_sha256=f['arw_sha256'],
               used=s in used, rejected_because=rej[s]['why'] if s in rej else None,
               transparency=round(q.get('flux_rel'), 4) if q.get('flux_rel') is not None else None, hfd_arcsec=round(q.get('hfd_arcsec', 0), 2), elongation=round(q.get('elong_median', 0), 3), coherent_ellipticity=round(q.get('coherent_ellipticity', 0), 3),
               registration=dict(rotation_deg=round(t['rotation_deg'], 4), shift_at_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], stars_used=t['used'], wrms_px=round(t['wrms_px'], 3), started_from=t['start']) if 'R' in t else None,
               weight=round(used[s]['weight'], 4) if s in used else None, sky_constant_dn_R_G1_G2_B=[round(v, 2) for v in S8['constants'][s]] if s in S8['constants'] else None,
               white_balance_as_shot=f['wb'][:3], black_level=f['black'], darkest_corner_level_dn=[round(v, 2) for v in f['corners']['top_left']['planes']],
               single_frame_spikes_replaced=S2f[s]['transient_spikes_replaced'], nucleus_brightest_green_dn=max(S2f[s]['nucleus_max_dn_above_black_repaired'][1:3]))
    frames.append(row)

tools = dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=list(rawpy.libraw_version), tifffile=tifffile.__version__, pillow=PIL.__version__,
             astrometry_net=subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip() + ' (Homebrew): image2xy, solve-field, wcs-rd2xy, wcs-xy2rd, wcsinfo; index files in ~/.observatory/astrometry',
             scripts='hack/stacks/2026-10-08/m31 in the observatory repository (run_all.sh)', note='deterministic array arithmetic only: averages, medians, measured blurs; nothing generative or learned, no neural denoise, sharpening or upscaling')
nU = len(used); expo = sum(S1[s]['exif_exposure_s'] for s in used)
n9 = S9['numbers']
recipe = dict(
    what='M31, the core of the Andromeda Galaxy, with its dust lanes: %d x 15 s at ISO 3200 (%.1f minutes), Sony a6000 at the prime focus of a Celestron 8SE (2,083 mm by plate solve, f/10.3) on an EQ6-R driven from a pointing model, night of 8/9 October 2026, clear. Stacked from the RAW colour planes with deterministic steps only.' % (nU, expo / 60),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), tools=tools,
    pictures={
        'm31.jpg': 'THE PICTURE. %d x %d px, one pixel per 2 x 2 colour cell of the sensor (%.3f arcsec), %.1f x %.1f arcmin; sensor orientation (north points left and 22 degrees up, east down; not mirrored). No metadata.' % (S9['size_px'][0], S9['size_px'][1], S9b['pixel_scale_arcsec'], *S9b['field_arcmin']),
        'm31-1600.jpg': 'the same, 1600 px wide (area average down). No metadata.',
        'm31-stack.tif': '16-bit linear R, G, B: DN above the zero region (see zero) plus a pedestal of %d, white balanced (R x %.4f, B x %.4f), same crop and scale as m31.jpg, zlib, no metadata. Nothing in it is stretched; %d pixels at 65535.' % (S9['pedestal'], wb_r, wb_b, S9['tiff_pixels_at_65535']),
        'm31-deconvolved.jpg, m31-deconvolved-1600.jpg': 'EXTRA, NOT RECOMMENDED: the stack restored with a blur measured from its own stars (see deconvolution). Kept apart, labelled; the delivered picture is m31.jpg.'},
    source=dict(folder=STILLS, window_utc_hhmmss=[T0, T1], frames_found=len(S1), frames_used=nU, frames_rejected=len(rej), total_exposure_s=expo, summed_weights=round(S7['effective_frames'], 2),
                originals='read in place, never written; sha256 of each RAW from its sidecar is in frames[]'),
    selection=dict(rule=S7['limits'], hfd_clear_median_arcsec=round(S7['hfd_clear_median_arcsec'], 2), rejected=[dict(file=S1[r['stamp']]['name'], why=r['why']) for r in S7['rejected']],
                   weights='frames x 1/transparency, averaged with weight (transparency / noise)^2, noise = the frame\'s darkest-corner noise over the median: all between %.3f and %.3f tonight (clear)' % (min(u['weight'] for u in S7['used']), max(u['weight'] for u in S7['used']))),
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (6024 x 4024, RGGB), the RAW\'s own black level (512) subtracted; four colour planes R, G1, G2, B of 3012 x 2012 kept apart, no demosaic. Exposure and ISO from the RAW\'s EXIF (all 15 s, ISO 3200; the sidecars agree). The orientation flag is ignored.'),
        dict(step='hot pixels', detail='no darks: fixed hot pixels from the per-plane median of all 33 frames WITHOUT registration (each minus its darkest-corner level; the field drifts about 80 px over the series and the centring frames sit 200 to 700 px away, so stars do not survive the median); hot = above the 5 x 5 median of that by more than max(6 sigma, 25% of the level) AND above its highest neighbour by half that. Single-frame spikes: above the 3 x 3 median by 8 sigma + 50% of the level. Both replaced by the 3 x 3 median of the same plane.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in S2['hot']}, spikes_per_frame=[min(f['transient_spikes_replaced'] for f in S2['frames']), max(f['transient_spikes_replaced'] for f in S2['frames'])]),
        dict(step='stars', detail='as on 3 October (hack/stacks/2026-10-03/m31/step3_stars.py): green planes averaged, the galaxy\'s smooth light taken off, detection at 6 sigma of the local noise, Gaussian-windowed centroids, 28 sensor px aperture.'),
        dict(step='registration', detail='rotation + shift (similarity, scale held at 1) on stars more than 400 sensor px from the nucleus, unsaturated, isolated; walked outward in time from the reference %s, each frame starting from its neighbour\'s solution; a coarse shift vote where the neighbour\'s solution did not fit (the centring frames). Match radius 30, 12, 4, 4 px; 3.5 sigma rejection.' % REF_STAMP,
             reference=REF_STAMP, stars_in_reference=len(S4['reference_stars_flux']), motion=n9['motion']),
        dict(step='transparency and star size', detail='52 stars (more than 400 px from the nucleus, unsaturated, isolated, 30000 DN or more): aperture flux over each star\'s clear-frame median, median over stars; half-flux diameter, elongation, and the coherent ellipticity (stars drawn out in one shared direction = the mount moving).'),
        dict(step='flat field', detail=S6['method'], runs={k: {kk: vv for kk, vv in v.items() if kk != 'frames'} for k, v in S6['runs'].items()}, frames_m76=S6['runs']['m76']['frames'], m76_disc=dict(sensor_xy=S6['m76_sensor_xy'], radius_px=S6['m76_disc_radius_px']),
             per_colour={c: dict(large_scale_flat=v['large_scale_flat'], radial_fit_per_run=v['radial_fit'], rings_flat_radialfit_3october=v['rings_flat_radialfit_3oct'], top_centre_bottom=v['top_middle_bottom_at_centre_column'], left_right=v['left_right_at_centre_row'], corners_tl_tr_bl_br=v['corners_tl_tr_bl_br']) for c, v in S6['colours'].items()},
             tried_and_dropped=dict(what='red and blue shaped like green, differing only by their ring ratio to green', ring_ratio_to_green=S6['colour_ratio_to_green'], why_dropped='the faint glow then came out 4 to 8 DN too red (white balanced), rising away from the top of the sensor (R/G up to 2): see comparisons S against F'),
             check_against_3_october='the delivered flat\'s ring medians against the 3 October cloud-glow profile (an independent measurement, same optics): green and blue within 1% at every radius, red within 2 to 3% (rings_flat_radialfit_3october: [r0, r1, tonight, radial fit, 3 October])'),
        dict(step='dust', detail=S6b['method'], shadows_checked=S6b['shadows'], model=S6b['dust_model'], effect_in_the_stack=dust_effect),
        dict(step='stack', detail='per frame and plane: repaired planes / (large-scale flat of the colour x dust model) x 1/transparency, resampled onto the reference frame\'s grid of colour cells (rotation + shift + the plane\'s place in the cell, Lanczos-4; output pixel (X, Y) = reference sensor (2X + 0.5, 2Y + 0.5)), minus ONE constant per frame and plane matching it to the reference in the reference\'s darkest quarter. Then per pixel: 3 sigma clip about the median (sigma = 1.4826 MAD, floor 0.4 x one frame\'s noise), 3 sigma clip about the weighted mean, weighted mean.',
             kappa=S8['kappa'], dark_region_percentile=S8['dark_region_percentile'], per_plane=S8['planes'],
             sky_constants='one per frame per colour (frames[].sky_constant_dn_R_G1_G2_B), relative to the reference frame; they fall in steps of about 4 DN (blue near 0 or -4, the others similar), the size of one step of the a6000\'s black offset at ISO 3200: the camera\'s offset moving between frames, plus the sky changing by a few DN. No surface fitted: the galaxy fills the frame.'),
        dict(step='crop', detail='the largest rectangle in which every pixel is covered by at least 80%% of the used frames: colour-cell px x %d..%d, y %d..%d (sensor x %d..%d, y %d..%d) of the reference frame.' % (x0, x1, y0, y1, 2 * x0, 2 * x1, 2 * y0, 2 * y1)),
        dict(step='zero level', detail='THE ABSOLUTE ZERO IS UNKNOWN: the galaxy fills the frame and the sky under it cannot be measured. One constant per colour plane is subtracted so that the darkest part of the field sits at zero: the median of each plane where the smoothed green (1/8 scale, Gaussian 4 there) is in its lowest 1%, at least 100 px inside the crop; the same pixels for every plane, so that region is neutral by construction. Everything in the pictures is brightness ABOVE that region.',
             levels_subtracted_dn=lev, region=dict(px=S9['zero']['region_px'], centre_crop_px=S9['zero']['region_centre_crop_px'], distance_from_nucleus_arcmin=S9['zero']['uncertainty']['zero_region_distance_arcmin']),
             how_uncertain=dict(estimate='the galaxy still in the zero region, from the glow\'s own fall-off along the minor axis: green(r) = A exp(-r/h) - Z fitted from 6.5 to 22 arcmin out on both sides gives Z = %.1f +- %.1f DN (scale length %.1f arcmin; fit rms %.1f DN), against a green sky of %.0f DN there: consistent with nothing left, to about +-2%% of the sky.' % (
                 S9['zero']['uncertainty']['exponential_fit']['Z_dn'], S9['zero']['uncertainty']['exponential_fit']['Z_error_dn'], S9['zero']['uncertainty']['exponential_fit']['h_arcmin'], S9['zero']['uncertainty']['exponential_fit']['rms_dn'], S9['zero']['uncertainty']['green_sky_level_at_zero_region_dn']),
                 caveat='a disc that falls more slowly beyond the frame than inside it (galaxy discs do) leaves more than that; the flat\'s own uncertainty across the field (M76\'s sky slope, under 1.6% per 3000 px in green, divided out) is about +-1 DN of the 99 DN sky. So the zero is a floor, good to a few DN, not the sky.', details=S9['zero']['uncertainty'])),
        dict(step='colour', detail='G = mean of G1 and G2; R x %.4f and B x %.4f: the camera\'s as-shot white balance from the RAWs (median over the used frames). No colour matrix. In the finish the faint glow is made neutral (see finish); the bulge stays warm against it.' % (wb_r, wb_b), as_shot_raw=S9['wb']['raw']),
        dict(step='stretch', detail='arcsinh on brightness (green) about the zero level, f = (asinh(v/soft) - asinh(-floor/soft)) / (asinh(white/soft) - asinh(-floor/soft)), v clipped to -floor..white: noise below the zero is kept down to -floor (about 3 sigma of the stack) instead of being cut; colour ratios kept, from a copy blurred by a Gaussian of %.0f px, ratio = (C + colour_pedestal) / (G + colour_pedestal); then the sRGB curve, 16 bits. White is set from the nucleus: the first of a fixed list of places for it (fraction of white) that leaves it at 250 of 255 or less after the finish. Tried first: soft 25 (more compression of the bulge, more grain in the faint parts); 3 October used 45.' % S9['stretch']['chroma_sigma_px'],
             **{k: v for k, v in S9['stretch'].items()}),
        dict(step='finish', detail='finish16.py: the finish-pictures tool (.claude/skills/finish-pictures/tools/finish.py) reading the 16-bit stretch instead of cutting it to 8 bits first, and with --white-abs (white point as a value) so that the core stays below white. Options: %s. Neutral band chosen with skycheck.py: 0-40 left the 10-40%% band at R-G +1.9, 10-50 at +1.1, 20-60 at +0.5 (the faint glow is warmer the brighter it is).' % ' '.join(S9['finish']),
             options=S9['finish'], record=S9['finish_record'], skycheck=S9['skycheck']),
    ],
    numbers=dict(noise=n9['noise'], stars_in_the_stack=n9['stars_in_the_stack'], raw_clipping=n9['raw_clipping'], glow_blocks_delivered=n9['glow_blocks'], flat_check_early_late=flatcheck, comparison_stacks=comparisons),
    plate_solve=dict(S9b, note='astrometry.net on the delivered stack: M31\'s catalogue nucleus lands %.2f arcsec from the nucleus measured in the stack. M32 is %.1f arcmin outside the right edge.' % (S9b['measured_minus_catalogue_arcsec'], S9b['m32_outside_by_arcmin'] or 0)),
    deconvolution=dict({k: v for k, v in S10.items() if k not in ('stretch',)}, stretch=S10['stretch'],
                       verdict='NOT RECOMMENDED. Stars %.2f -> %.2f arcsec FWHM (%.2f -> %.2f half-flux diameter), but a dark moat round every star (median %.0f DN, worst %.0f DN, against a galaxy of %.0f DN round them; concentric rings round the brighter stars, saturated or not: the blur is not the same everywhere in the field and the filter overshoots) and %d%% more grain at the 1 px scale it shows; the dust lanes do not gain visibly. As on 3 October: the lanes are limited by noise, not by blur.' % (
                           S10['check_before']['fwhm_arcsec'], S10['check_after']['fwhm_arcsec'], S10['check_before']['hfd_arcsec'], S10['check_after']['hfd_arcsec'], -S10['check_after']['ring_deepest_dn']['median'], -S10['check_after']['ring_deepest_dn']['worst'], S10['check_after']['local_galaxy_level_dn_median'],
                           round(100 * (S10['grain_rgb']['gauss_1_px']['after'][1] / S10['grain_rgb']['gauss_1_px']['before'][1] - 1)))),
    compared_with_3_october=dict(
        three_october='38 x 20 s (12.7 min; 11.6 min of clear sky after weights) through thin cloud, stars 4.1 arcsec half-flux diameter, flat from cloud glow and twilight, top 2.3 arcmin cropped for a chaff shadow; observations/2026-10-03/images/andromeda-core.jpg',
        tonight='%d x 15 s (%.1f min; clear, weights all about 1), stars %.2f arcsec half-flux diameter in the stack (%.2f FWHM), flat from M76\'s sky 25 to 55 minutes earlier with dust shadows divided out, full field (%.1f x %.1f arcmin)' % (nU, expo / 60, n9['stars_in_the_stack']['half_flux_diameter_arcsec'], n9['stars_in_the_stack']['fwhm_arcsec'], *S9b['field_arcmin']),
        sky='about the same brightness: 3 October\'s clear corner level was 101 DN green in 20 s at a corner where the optics pass 75% (about 100 DN per 15 s at the centre); tonight 99 DN per 15 s at the centre',
        expectation='with the same sky, the noise at a given surface brightness goes as 1/sqrt(clear exposure): tonight about sqrt(696/450) = 1.24 times 3 October\'s',
        measured_noise='one picture pixel (0.776 arcsec), green, white balanced, stack: tonight %.2f DN per 15 s frame scale; 3 October 6.00 DN per 20 s frame scale (its stack was resampled to the sensor grid and binned 2 x 2, which smooths pixel noise more, so the two are not strictly comparable)' % n9['noise']['stack_white_balanced']['G'])
    , frames=frames)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('recipe.json written:', os.path.getsize(os.path.join(OUT, 'recipe.json')), 'bytes; frames', len(frames), '; comparisons', list(comparisons), '; dust effect', dust_effect and dust_effect['light_restored_pct'], '; flat check', flatcheck)
