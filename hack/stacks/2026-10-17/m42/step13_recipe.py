"""Step 13: final/recipe.json, every number that shaped the picture, gathered from the steps' own JSON in work/."""
import json, os, datetime, collections
import numpy as np
from common import *

if __name__ == '__main__':
    s1 = jload('step1.json'); s3 = jload('step3_transforms.json'); s4 = jload('step4_quality.json'); s5 = jload('step5_select.json'); s6 = jload('step6_solve_ref.json')
    s7a = jload('step7a_flats.json'); s7 = jload('step7_dust.json'); s8 = jload('step8_stack.json'); s8c = jload('step8_coadd.json'); s8b = jload('step8b_join.json')
    s9 = jload('step9_solve.json'); s9d = jload('step9_deliver.json'); s11 = jload('step11_halves.json'); fin = json.load(open(os.path.join(FINAL, NAME + '.json')))
    col = jload('step9b_colour.json') if os.path.exists(W('step9b_colour.json')) else None
    turns = collections.OrderedDict((t, dict(taken=0, used=0, dropped={})) for t in ('pre', 'long', 'short'))
    for f in s1['frames']: turns[f['turn']]['taken'] += 1
    for u in s5['used']: turns[u['turn']]['used'] += 1
    for r in s5['rejected']: turns[r['turn']]['dropped'][r['stamp']] = r['why']
    NL = sum(u['kind'] == 'long' for u in s5['used']); NS = sum(u['kind'] == 'short' for u in s5['used'])
    nz = s8['noise_faint_region_dn']; g = lambda k: 0.5 * (nz[k][1] + nz[k][2])
    tr = {o['stamp']: o for o in s3['transforms']}
    nd = s7['nights']['long']; cr = nd['named_shadows'][0]
    rej = s5['rejected']; why_count = collections.Counter()
    for r in rej:
        for k, key in (('smeared', 'smeared'), ('wider', 'stars too wide'), ('usual brightness', 'stars dimmed (cloud or haze)'), ('after a move', 'within 10 s of a move'), ('first frame after the slew', 'first frame after the slew'), ('registration', 'registration')):
            if k in r['why']: why_count['%s %s' % (r['kind'], key)] += 1
    cvc = s8['coadd_vs_control']
    summary = dict(
        frames='%d frames on M42 in the windows (by the RAW\'s own EXIF and each frame\'s own plate solve): %d long (30 s ISO 1600, the one before the firmware flash included), %d short (2 s ISO 400); used %d long and %d short' % (len(s1['frames']), turns['pre']['taken'] + turns['long']['taken'], turns['short']['taken'], NL, NS),
        turns={t: dict(taken=v['taken'], used=v['used'], dropped=len(v['dropped'])) for t, v in turns.items()},
        dropped_why=dict(why_count), dropped_note='a frame can be dropped for more than one reason; every frame\'s own reasons are under "dropped"',
        not_in_the_run=s1['left_out'] + ['centring frames (2 s, ISO 6400, 09:00 and 09:01 UTC) and the 15 s ISO 3200 frames of M33 before 08:56 lie outside the windows', 'the last short frame (12:16:18) has a sidecar but no RAW on disk; it was never read'],
        integration_s=NL * 30.0 + NS * 2.0, integration='long %d x 30 s = %.1f minutes; short %d x 2 s = %.0f s' % (NL, NL * 0.5, NS, NS * 2.0),
        star_size='half-flux diameter, green: %.2f arcsec in the joined stack (%d compact stars), %.2f in the reference frame alone; median of the unsmeared long frames %.2f, short %.2f; the proper coadd\'s PSF %.2f px = %.2f arcsec against the control\'s %.2f px' % (
            s9d['star_size']['stack_arcsec'], s9d['star_size']['stack_stars'], s9d['star_size']['reference_frame_arcsec'], s5['hfd_kind_median_arcsec']['long'], s5['hfd_kind_median_arcsec']['short'], cvc['G1']['hfd_px']['proper'], cvc['G1']['hfd_px']['proper'] * 0.7765, cvc['G1']['hfd_px']['control']),
        registration='every frame\'s first guess from its own plate solve (the pre-flash frame from its neighbour, then a coarse vote); rotation + shift on the stars onto one long reference frame (%s), the short frames too (their star fluxes compared at 1/60); weighted rms at most %.2f px long, %.2f px short; the field turned %.1f degrees over the used frames' % (
            REF_STAMP, max(tr[u['stamp']]['wrms_px'] for u in s5['used'] if u['kind'] == 'long'), max(tr[u['stamp']]['wrms_px'] for u in s5['used'] if u['kind'] == 'short'), max(tr[u['stamp']]['rotation_deg'] for u in s5['used']) - min(tr[u['stamp']]['rotation_deg'] for u in s5['used'])),
        flat='the 13 October hybrid flat (%s: large scale from that night\'s open sky, dust from the 13 October twilight flats), as tonight\'s M27 and M33 pipelines chose it. On this run\'s dithered sky (flatcheck.py, the Trapezium masked 700 px) the large-scale remainder cannot be judged: M42\'s glow is in every frame (G1 after a plane %.3f for the hybrid, %.3f for the twilight flat alone, nebula light included). Times this run\'s own dust measure (step 7). The short frames, 20 minutes later, get the same flat' % (FLAT_DIR, s7a['on_m42_sky'][0]['large']['G1']['robust_rms_after_plane'], s7a['on_m42_sky'][1]['large']['G1']['robust_rms_after_plane']),
        dust='%d shadows measured on this run\'s own long frames (each frame against the first stack put back on its sensor grid, so the nebula cancels; each seen in the first and in the second half of the run alone, 0.6%% deep at least in both) and divided out, %.2f%% of the sensor, deepest factor %.3f; %d candidates turned down. The crescent at sensor (3522, 848): %.1f%% deep with no flat, %.1f%% left by the 13 October flat (new since then), %.1f%% after this run\'s own correction. Not judged within 5 arcmin of the Trapezium (too bright and structured). Remainder rms on 8 px blocks %.4f' % (
            len(nd['divided_out']), 100 * nd['sensor_fraction_changed'], nd['deepest_factor'], len(nd['turned_down']), 100 * cr['depth_in_own_sky_no_flat'], 100 * cr['left_by_the_13oct_flat'], 100 * cr['left_after_own_correction'], nd['remainder_robust_rms_8px']),
        darks='none: darks.subtract changed nothing and said so; hot pixels found from the frames, one map per kind (long, short), repaired by the 3 x 3 median of their colour plane',
        combine=dict(long='proper coaddition (Zackay & Ofek 2017; tools/coadd.py, keep_phase="mean"), one PSF per frame and plane from %d stars (green), outlier mask; delivered: %s' % (s8c['planes']['G1']['psf_stars'], s8c['deliver']),
                     control='the old 3-sigma clipped weighted mean from the same cube, in the same pass',
                     coadd_vs_control={P: dict(point_source_snr_ratio=round(v['snr_ratio_median'], 4), stars=v['stars'], quartiles=[round(x, 4) for x in v['snr_ratio_quartiles']], pixel_noise_dn=dict((k, round(x, 3)) for k, x in v['pixel_noise_faint_region'].items()), hfd_px=dict((k, round(x, 3)) for k, x in v['hfd_px'].items()), theory_gain=round(v['theory_gain_over_control_weights'], 4)) for P, v in cvc.items()},
                     short='the 3-sigma clipped weighted mean (the control\'s code) of the %d short frames' % NS),
        join=dict(rule='the short stack replaces the long one wherever any long frame came within 7 percent of the ceiling (any plane), grown one colour cell, with a smooth ramp in brightness (10,000 to 14,000 DN as the sensor saw it) so there is no step',
                  expected_ratio=s8b['expected'], nebula_factor=round(s8b['factor_applied'], 3), nebula_over_expected=round(s8b['factor_over_expected'], 4),
                  per_plane={f['plane']: dict(a=round(f['a'], 3), error=round(f['a_error'], 3), bins=[round(b['ratio_with_the_common_offset'], 2) for b in f['bins']]) for f in s8b['nebula_fits']},
                  stars=dict(n=s8b['star_check']['stars'], median_ratio=round(s8b['star_check']['median_ratio'], 2), error_of_median=round(s8b['star_check']['error_of_median'], 2), spread=round(s8b['star_check']['spread'], 2), brighter_half=round(s8b['star_check']['brighter_half_median'], 2), fainter_half=round(s8b['star_check']['fainter_half_median'], 2)),
                  star_width_blur_px=s8b['star_width']['blur_applied_px'], area_from_the_short_stack_arcmin2=round(s8b['blend']['w_gt_0_arcmin2'], 2), white_px=s8b['blend']['white_pixels']),
        sky='ONE constant per colour per frame: the clipped mean over the darkest 30% of the area every long frame covers. M42 fills the field: the zero is the faintest part of the field, not the true sky; no surface fitted',
        air_dispersion='red - green %s, blue - green %s sensor px measured in the frames and taken out in the one resampling; left in the stack: red %s, blue %s' % (s8['air_dispersion']['measured_in_the_frames']['red_minus_green_sensor_px'], s8['air_dispersion']['measured_in_the_frames']['blue_minus_green_sensor_px'], s8['air_dispersion']['left_in_the_stack']['red_minus_green_sensor_px'], s8['air_dispersion']['left_in_the_stack']['blue_minus_green_sensor_px']),
        noise='green per pixel in the faint region (stars masked; this region is faint nebula, so its own texture is in these numbers): proper coadd %.2f DN, control %.2f, the reference frame alone %.2f; the noise alone, from half the difference of the odd and even coadds, %.2f DN (%.1f x under the single frame, against sqrt(%d) = %.1f); the short stack %.2f in its own units' % (g('proper'), g('control'), g('single'), g('half_difference_proper'), g('single') / g('half_difference_proper'), NL, NL ** 0.5, g('short')),
        coverage=dict(all_frames=s9['coverage']['all'], at_least_half=s9['coverage']['most (at least half)'], picture='%d x %d px = %.1f x %.1f arcmin, the largest upright rectangle where at least half the long frames have data; inside it %.0f%% of pixels have every long frame and %.0f%% at least three quarters' % (
            s9['crop_on_canvas']['width'], s9['crop_on_canvas']['height'], *s9['coverage']['picture (at least 50%)']['rect_arcmin'], 100 * s9['fraction_inside_with_every_frame'], 100 * s9['fraction_inside_with_three_quarters'])),
        is_it_the_thing='yes: the reference frame and the stack plate-solved (astrometry.net); theta1 Orionis C\'s catalogue place falls %.1f arcsec from the brightest point near it in the stack; the brightest 2%% of the reference frame\'s light is centred %.2f arcmin from the Trapezium; M43\'s star is in the frame' % (s9['catalogue']['Trapezium']['offset_arcsec'], s6['brightest_2pct_centroid_from_trapezium_arcmin']),
        half_stacks='odd against even long frames (each proper-coadded, at one common PSF), green, stars removed (median), band-passed (3 to 20 px): %d of %d tiles of %.0f arcmin repeat above 5 x the spread of a turned null; the faintest third of the tiles: %d of %d (median correlation %.2f); by distance from the Trapezium: %s. Tiles touching the joined core are left out' % (
            s11['odd_vs_even']['passing'], s11['odd_vs_even']['tiles'], float(os.environ.get('M42_TILE_ARCMIN', '3.0')), s11['odd_vs_even']['faintest_third']['passing'], s11['odd_vs_even']['faintest_third']['tiles'], s11['odd_vs_even']['faintest_third']['median_corr'],
            '; '.join('%d-%d arcmin %d/%d (median correlation %.2f)' % (*b['arcmin'], b['passing'], b['tiles'], b['median_corr']) for b in s11['odd_vs_even']['by_distance'])),
        colour=('camera daylight white balance x Gaia DR3 star colours (kR %.4f, kB %.4f from %d stars), the camera\'s own colour matrix; colour only where the light carries it; where even the short frames came near the ceiling, white' % (col['factors']['R'], col['factors']['B'], col['used'])) if col else 'camera daylight white balance (Gaia calibration failed)',
        picture='%d x %d px at the stack\'s own pixels (%.4f arcsec per px, %.1f x %.1f arcmin), never enlarged; north %.1f degrees clockwise from up' % (s9['crop_on_canvas']['width'], s9['crop_on_canvas']['height'], s9['pixscale_arcsec'], *s9['field_arcmin'], s9['north_angle_from_up_deg_clockwise']),
        altitude='%.0f to %.0f degrees up over the long run, %.0f for the short (sidecars); published words say "30 to 50 degrees up" and no clock time' % (min(f['alt_deg'] for f in s1['frames'] if f['kind'] == 'long'), max(f['alt_deg'] for f in s1['frames'] if f['kind'] == 'long'), np.median([f['alt_deg'] for f in s1['frames'] if f['kind'] == 'short'])))
    rec = dict(target='Messier 42, the Orion Nebula, with Messier 43', night='2026-10-17 (frames of 18 October UTC)', made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
               reproduce='hack/stacks/2026-10-17/m42/run_all.sh (hooks M42_*, see common.py); with none set it reproduces this run (the pictures and the stack bit for bit; this file differs only in "made"). RAWs read in place, never written',
               template='hack/stacks/2026-10-17/m33 (calibration on a canvas), hack/stacks/2026-10-17/m27 (proper coaddition with the old mean as a control), hack/stacks/2026-10-03/m42 (the long + short join)', tools=dict(note='deterministic array arithmetic only: averages, medians, measured fits, fixed curves and matrices. Nothing generative, learned or upscaled'),
               files=dict(picture=[os.path.join(FINAL, NAME + e) for e in ('.png', '.jpg')], stack_tif=s9d['tif']['path']), summary=summary,
               frames=[dict(stamp=f['stamp'], turn=f['turn'], kind=f['kind'], file=f['name'], arw_sha256=f.get('arw_sha256'), since_slew_s=f.get('since_slew_s'), dither=f.get('dither'), pointing_from=f.get('pointing_from')) for f in s1['frames']],
               dropped={t: v['dropped'] for t, v in turns.items()},
               steps=[dict(step='1 frames and hot pixels', numbers=dict(hot=s1['hot'], hot_from=s1['hot_from'], left_out=s1['left_out'])),
                      dict(step='3 registration', numbers=dict(reference=s3['reference'], rotation_sign=s3['rotation_sign'], transforms={o['stamp']: dict(R=o.get('R'), t=o.get('t'), rotation_deg=o.get('rotation_deg'), wrms_px=o.get('wrms_px'), first_guess=o.get('first_guess'), guess_error_at_centre_px=o.get('guess_error_at_centre_px')) for o in s3['transforms']})),
                      dict(step='4 quality', numbers=dict(quality=s4['quality'], quality_stars=s4['quality_stars'])),
                      dict(step='5 selection', numbers=s5), dict(step='6 is it the thing (reference frame plate solve)', numbers=s6),
                      dict(step='7a flatcheck on the dithered sky', numbers={k: v for k, v in s7a.items() if k != 'frames'}), dict(step='7 canvas and dust', numbers={k: v for k, v in s7.items() if k not in ('fits', 'constants_pass1')}),
                      dict(step='8 combine (proper coadd, control, short stack)', numbers=dict(stack={k: v for k, v in s8.items() if k not in ('frames', 'short_frames')}, coadd=s8c)),
                      dict(step='8b join long and short', numbers=s8b),
                      dict(step='9 coverage, plate solve of the stack, star colours, render', numbers=dict(solve=s9, deliver=s9d, colour=col)),
                      dict(step='10 finish (finish16.py)', numbers=fin), dict(step='11 half stacks', numbers=s11)])
    os.makedirs(FINAL, exist_ok=True)
    json.dump(rec, open(os.path.join(FINAL, 'recipe.json'), 'w'), indent=1, default=float)
    print(json.dumps(summary, indent=1, default=float))
