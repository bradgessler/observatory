"""Step 10: recipe.json beside the stack, with every number that shaped the picture, and a copy of the finished JPEG
beside it. Gathers what the earlier steps wrote (their JSON in the work folder) and the finish tool's own recipe."""
import datetime, hashlib, json, os, platform, shutil, subprocess, sys
import numpy as np, cv2, rawpy, tifffile
from common import *

s1 = jload('step1.json'); s3 = jload('step3_transforms.json'); s4 = jload('step4_select.json'); s5 = jload('step5_solve_ref.json')
s6 = jload('step6_stack.json'); s7 = jload('step7_measure.json'); s8 = jload('step8_render.json')
fin = json.load(open(os.path.join(FINAL, 'ngc2392.json')))
tr = {o['stamp']: o for o in s3['transforms']}; used = {u['stamp']: u for u in s4['used']}; rej = {r['stamp']: r for r in s4['rejected']}
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
shutil.copyfile(os.path.join(FINAL, 'ngc2392.jpg'), os.path.join(OUT, 'ngc2392.jpg'))
sky = subprocess.run([sys.executable, os.path.join(SCR, 'skycheck.py'), os.path.join(FINAL, 'ngc2392.png')], capture_output=True, text=True).stdout.strip()
try: an = subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip().splitlines()[-1]
except Exception: an = None
frames = []
for f in s1['frames']:
    s = f['stamp']; o = tr[s]; q = s4['quality'].get(s, {})
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'], run=1, used=s in used,
                       why_dropped=rej[s]['why'] if s in rej else None, weight=used[s]['weight'] if s in used else None, transparency=q.get('transparency'), half_flux_diameter_arcsec=q.get('hfd_arcsec'),
                       elongation_median=q.get('elong'), common_ellipticity=q.get('coh'), since_slew_s=f['since_slew_s'], mount_axes_turned_arcsec=f['mount_axes_turned_arcsec'], box_star_size_arcsec=f['box_star_size_arcsec'],
                       shift_at_centre_sensor_px=o.get('shift_at_centre_px'), rotation_deg=o.get('rotation_deg'), registration_wrms_px=o.get('wrms_px'), registration_stars=o.get('used'),
                       sky_constants_dn=s6['constants_dn'].get(s), pixels_at_sensor_ceiling_whole_frame=f['ceiling_pixels'], transient_note='hot pixels repaired on the fly, see steps'))
# what was on this Mac when: the RAWs are copied over Wi-Fi about ten minutes behind the camera
ARRIVAL = dict(run='32 frames, DSC01408 to DSC01439, shutter 11:16:23 to 11:31:24 UTC on 13 October',
               at_start='8 of the 32 RAWs were here at 11:33:38 UTC, when this work began (the last one present was DSC01415, 11:19:49)',
               waited='all 32 were here by 11:42:18 UTC (the last, DSC01439, was shot at 11:31:24), about nine minutes after the start; the stack was made then, from all 32, each checked whole by size and SHA-256')
CAVEATS = [
    'The nebula is about 60 px across in a 720 x 480 picture: small, because nothing is enlarged.',
    'Red is at or near zero across the outer disc in the finished picture: the nebula\'s [O III] light at 501 nm lies outside sRGB, the camera matrix gives it a negative red, and the picture clips that at 0. This is the colour space, not the sensor.',
    'The colour offsets for atmospheric dispersion were measured on starlight; for the nebula\'s line emission they are not exactly right: see steps[5].colour_offsets.nebula_own.',
    'The flat\'s dust could not be checked against this run (sky too faint in 4 s). The nebula sat within 60 px of the sensor centre throughout, on the same pixels to within the drift (see the frames\' shifts), so a dust shadow there would not average out; the nearest shadows the flat and the M77 stack list are in steps[5].flat.dust_near_the_nebula.',
    'The star images are slightly lopsided (peak off centroid by up to 1 px) and 1.15 long by their moments: anything said about shape inside 10 arcsec, and about which side of the outer disc is brighter, carries that.',
    'The sky plane fitted in the crop is in the picture only; the stack has one constant per colour per frame.',
    'Cloud thickened through the run: the stars fell from full brightness to about half by 11:26 and to under a third by the end. The last ten frames (stars under 50% of the clearest frame) are left out, and the frames between are scaled up and weighted down: the stack is worth about 15 clear frames (one minute), not 32.',
    'The picture\'s luminance is blurred by a Gaussian of 1.5 px (NGC 1535: 1.0): the stars and the central star are about 14% wider in the picture than in the stack. At 1.0 the outer disc\'s edge showed scallops of grain at full size.',
    'The 8th magnitude star north of the nebula is five times brighter than the nebula\'s centre and its core is at full scale in green (a few pixels); it and the other stars read slightly green-yellow, as in tonight\'s other pictures (the camera\'s daylight balance and matrix on this telescope), not a property of the stars.',
    'The first frame of the series is dropped by the rule (first after the slew) although it was taken 44 s after the slew and measures like its neighbours.',
]
G, B, R = (s7['shell'][c]['shell_summary'] for c in 'GBR')
sol = s7['solve']; PS = sol['pixscale_arcsec']; n_used = len(used)
profile = s7['shell']['G']['mean']['profile_dn_per_px']; cs = s7['central_star']['G']; stc = s7['structure']
# what star size and star brightness did over the run: thirds of the series in time order
qs = [(f['stamp'], s4['quality'][f['stamp']]) for f in s1['frames'] if f['stamp'] in s4['quality']]
third = [qs[i * len(qs) // 3:(i + 1) * len(qs) // 3] for i in range(3)]
med = lambda rows, k: float(np.median([q[k] for _, q in rows]))
over_run = dict(frames=len(qs), star_size_arcsec=dict(first_third=med(third[0], 'hfd_arcsec'), middle_third=med(third[1], 'hfd_arcsec'), last_third=med(third[2], 'hfd_arcsec'), smallest=min(q['hfd_arcsec'] for _, q in qs), largest=max(q['hfd_arcsec'] for _, q in qs)),
                star_brightness_against_the_clearest_frame=dict(first_third=med(third[0], 'transparency'), middle_third=med(third[1], 'transparency'), last_third=med(third[2], 'transparency'), lowest=min(q['transparency'] for _, q in qs),
                                                                clearest_frame=max(qs, key=lambda x: x[1]['transparency'])[0], dimmest_frame=min(qs, key=lambda x: x[1]['transparency'])[0]),
                common_ellipticity=dict(median=med(qs, 'coh'), largest=max(q['coh'] for _, q in qs)),
                box_star_size_arcsec=dict(first_third=float(np.median([f['box_star_size_arcsec'] for f in s1['frames'][:len(s1['frames']) // 3]])), last_third=float(np.median([f['box_star_size_arcsec'] for f in s1['frames'][-(len(s1['frames']) // 3):]])),
                                          note='the telescope\'s own measure on its 960 px preview, the median of the stars it finds; it found fewer stars as the run went on (29 at the start, 9 at the end)'),
                green_sky_dn=dict(first_used=s6['constants_dn'][s6['frames'][0]]['G1'], last_used=s6['constants_dn'][s6['frames'][-1]]['G1']))
sz = over_run['star_size_arcsec']; tb = over_run['star_brightness_against_the_clearest_frame']
ring = stc['round_the_circle']['outer_disc_18_30px']; pkn = stc['central_star_peak_against_light_centroid']
inn = stc['inner_against_stars']
shoulder = [profile[k] for k in (6, 9, 12)]
recipe = dict(
    what='NGC 2392 (a planetary nebula in Gemini): %d of %d frames of 4 s at ISO 1600 (Sony a6000 on a Celestron 8SE at f/10, EQ6-R tracking), stacked from RAW colour planes with rotation, flat-fielded with the night\'s flat' % (n_used, len(s1['frames'])),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds') if os.environ.get('N2392_STAMP', '1') == '1' else None, owner='Brad Gessler',
    verdict=dict(
        identity=s5['verdict'] + '; the brightest source in the field is a star %.1f arcmin away (to the north: the 8th magnitude star beside the nebula)' % s5['brightest_source']['from_catalogue_arcmin'],
        total_exposure_s=n_used * EXPOSURE_S,
        star_size_in_the_stack_arcsec=s7['star_size']['half_flux_diameter_arcsec'],
        over_the_run='star size (half-flux diameter, the same stars in every frame): %.2f arcsec in the first third of the run, %.2f in the middle, %.2f in the last (%.2f to %.2f over all frames). Star brightness against the clearest frame: %.2f, %.2f, %.2f (lowest %.2f, frame %s).' % (
            sz['first_third'], sz['middle_third'], sz['last_third'], sz['smallest'], sz['largest'], tb['first_third'], tb['middle_third'], tb['last_third'], tb['lowest'], tb['dimmest_frame']),
        clipping=s7['clipping']['verdict'] + ' (highest raw value %d of 16,372: %.0f%% of the range above black)' % (max(s7['clipping']['highest_raw_value_in_any_frame'].values()), 100 * max(s7['clipping']['highest_as_fraction_of_ceiling'].values())),
        central_star='seen as a star-like point in the middle of the nebula, far stronger than in NGC 1535 earlier tonight: green %.0f DN per pixel at the centre against %.0f, %.0f and %.0f DN at 4.7, 7 and 9.3 arcsec out (fitted as a point of %.0f DN on a disc of %.0f DN). %s' % (
            cs['mean']['centre_dn'], *shoulder, s7['shell']['G']['no_shell_model']['point_flux_dn'], s7['shell']['G']['no_shell_model']['disc_flux_dn'],
            'A darker gap between star and shell is there in the whole stack and in both halves.' if cs['separate_point'] else 'It is not separated from the shell by a darker gap: the brightness falls all the way from the star to the shell with no minimum between (whole stack and both halves alike). At a star size of %.1f arcsec the star\'s own image reaches the shell.' % s7['star_size']['half_flux_diameter_arcsec']),
        inner_shell='seen as a blue-green shoulder of light round the star from about 4 to 10 arcsec out (green %.0f DN per pixel at 4.7 arcsec, %.0f at 9.3), not as a ring: its rim is not resolved from the star. Colour in linear sRGB (R, G, B, brightest = 1): %s inside 9 arcsec, %s in the outer disc' % (
            shoulder[0], shoulder[2], [round(v, 2) for v in s8['linear_srgb_colour_of_the_disc_r_lt_12px']], [round(v, 2) for v in s8['linear_srgb_colour_of_the_shell_18_28px']]),
        outer_disc='seen and proven: in the ring %.0f to %.0f arcsec from the central star the green light is %.2f DN per pixel (odd frames %.2f, even frames %.2f; noise of the same ring on blank sky %.3f), where the star and inner shell blurred by the stack\'s own star profile would leave %.2f: %.0f sigma above that in the whole stack, %.0f and %.0f in the two halves; in blue %.0f sigma (%.0f and %.0f), in red %.1f. The light ends between 28 and 34 arcsec from the centre.' % (
            s7['shell']['G']['mean']['shell']['arcsec'][0], s7['shell']['G']['mean']['shell']['arcsec'][1], G['observed_dn'], G['odd_dn'], G['even_dn'], s7['shell']['G']['mean']['shell']['blank_sky_sigma_dn'], G['spilled_from_the_disc_model_dn'],
            G['excess_sigma'], G['odd_excess_sigma'], G['even_excess_sigma'], B['excess_sigma'], B['odd_excess_sigma'], B['even_excess_sigma'], R['excess_sigma']),
        structure='inside 10 arcsec: none that can safely be told from the stars\' own shape (what is not round there, the part the two halves share, is %.3f of the centre for the nebula and %.3f for plain stars, which range %.3f to %.3f). '
                  'Outer disc (14 to 23 arcsec out): it is not even round the circle, and that repeats: green is %.0f%% brighter towards position angle %.0f (odd frames %.0f%% towards %.0f, even %.0f%% towards %.0f; blue %.0f%% towards %.0f), and %.0f%% brighter along the axis at position angle %.0f than across it (odd %.0f%% at %.0f, even %.0f%% at %.0f). '
                  'How much of the one-sidedness is the nebula is not settled: the stars of this stack are lopsided (peak %.1f arcsec from centroid at the median; the central star\'s peak is %.1f arcsec from the centre used, towards position angle %.0f), and that alone moves light round a star to one side. No knots, filaments or rim are seen.' % (
            inn['nebula_common_part_over_centre'], inn['stars_common_part_over_centre_median'], min(inn['stars']), max(inn['stars']),
            100 * ring['G']['mean']['one_side_fraction'], ring['G']['mean']['bright_side_position_angle_deg'], 100 * ring['G']['odd']['one_side_fraction'], ring['G']['odd']['bright_side_position_angle_deg'], 100 * ring['G']['even']['one_side_fraction'], ring['G']['even']['bright_side_position_angle_deg'],
            100 * ring['B']['mean']['one_side_fraction'], ring['B']['mean']['bright_side_position_angle_deg'],
            100 * ring['G']['mean']['oval_fraction'], ring['G']['mean']['oval_long_axis_position_angle_deg'], 100 * ring['G']['odd']['oval_fraction'], ring['G']['odd']['oval_long_axis_position_angle_deg'], 100 * ring['G']['even']['oval_fraction'], ring['G']['even']['oval_long_axis_position_angle_deg'],
            pkn['plain_stars_median_arcsec'], pkn['nebula']['mean']['arcsec'], pkn['nebula']['mean']['towards_position_angle_deg']),
        not_seen='no dark gap between the central star and the inner shell, no ring-shaped rim, no knots or filaments in the outer disc, no sharp boundary between inner shell and outer disc (a shoulder, then a dimmer zone with an outer edge)'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, astrometry_net=an,
               note='deterministic array arithmetic only: averages, medians, fitted rotations and planes, Gaussian, median and bilateral filters, an arcsinh curve. Nothing generative, learned or predictive. No deconvolution. Nothing painted or repaired by hand.'),
    scripts='hack/stacks/2026-10-12/ngc2392/ in the observatory repository (copied from ngc1535/ of the same night and adapted): run_all.sh runs step1_frames.py ... step10_recipe.py (common.py, solvelib.py, fitsmin.py; finish16.py and skycheck.py are the finish-pictures tools), then step11_clean.py',
    source=dict(folder=STILLS, window_utc=[T0, T1], frames_found=len(s1['frames']), frames_used=n_used, frames_dropped=len(s1['frames']) - n_used, total_exposure_s=n_used * EXPOSURE_S,
                dropped={r['stamp']: r['why'] for r in s4['rejected']}, left_out_before_the_count=s1['left_out'], originals='read in place, never modified', darks='none: hot pixels come from the run itself (step 1)',
                copies_checked='each RAW\'s size and SHA-256 against the camera\'s own (the sidecar) before it is counted', arrival=ARRIVAL),
    selection=dict(limits=s4['limits'], quality_stars=s4['quality_stars'], tracking_turn_median_arcsec=s4['tracking_turn_median_arcsec'], clear_frames_median_star_size_arcsec=s4['hfd_clear_median_arcsec'], sum_of_weights=s4['sum_of_weights'],
                   over_the_run=over_run,
                   note='the first frame of the series is dropped by rule (the first after the slew), whatever it measures; its numbers are in frames[0]'),
    frames=frames,
    steps=[
        dict(step=1, script='step1_frames.py', what='the run by the RAWs\' own EXIF and the sidecars\' pointing, each copy checked whole; hot pixels from the unregistered median of the run', hot=s1['hot']),
        dict(step=2, script='step2_stars.py', what='sources in every frame on the mean of the green planes (5 sigma), centroids, flux, half-flux radius, shape'),
        dict(step=3, script='step3_register.py', what='rotation + shift per frame on the stars (no scale, no shear)', reference=s3['reference'], reference_rule=s3['reference_rule'],
             rotation_range_deg=[min(o['rotation_deg'] for o in s3['transforms'] if not o['failed']), max(o['rotation_deg'] for o in s3['transforms'] if not o['failed'])]),
        dict(step=4, script='step4_select.py', what='quality per frame and the selection rule (see selection)'),
        dict(step=5, script='step5_solve_ref.py', what='plate solve of the reference frame before stacking: is it the thing?', result={k: v for k, v in s5.items() if k not in ('wcs_header', 'corners_ra_dec')}),
        dict(step=6, script='step6_stack.py', what='flat, one Lanczos-4 resampling per plane onto the reference frame\'s colour cells, one sky constant per colour per frame, sigma-clipped weighted mean; odd and even halves; atmospheric dispersion measured on stars and removed in the same resampling',
             **{k: s6[k] for k in ('grid', 'kappa', 'flat', 'fixed_hot_pixels_within_30px_of_the_nebula', 'sky', 'planes', 'colour_offsets', 'subsets', 'frames_covering_every_pixel', 'full_coverage_fraction')}),
        dict(step=7, script='step7_measure.py', what='plate solve of the stack, star size, clipping from the RAWs, the outer-disc test, the central star, what repeats in both halves', **{k: s7[k] for k in ('star_size', 'psf_stars', 'blank_sky_placements')},
             clipping={k: v for k, v in s7['clipping'].items()}, shell=s7['shell'], central_star=s7['central_star'], structure=s7['structure']),
        dict(step=8, script='step8_render.py', what='the linear TIF; the crop (quarter turns only), a sky plane per colour fitted away from the nebula (in the picture only), camera matrix, luminance and colour blurs, arcsinh stretch', **s8),
        dict(step=9, script='step9_finish.sh', what='finish16.py (levels, quiet sky, colour) and skycheck.py', finish=fin, skycheck=sky),
    ],
    plate_solution=dict(of='the stack (ngc2392-stack.tif is the stack\'s area x0, y0 = %d, %d: subtract these from stack px)' % (s8['tif']['area_stack_px']['x0'], s8['tif']['area_stack_px']['y0']),
                        scale_arcsec_per_stack_px=PS, scale_arcsec_per_sensor_px=PS / 2, focal_length_mm=sol['focal_length_mm'], mirrored=sol['mirrored'],
                        north_deg_clockwise_from_up_in_the_stack=sol['north_angle_from_up_deg_clockwise'], east_deg_clockwise_from_up_in_the_stack=sol['east_angle_from_up_deg_clockwise'],
                        stack_centre_ra_dec=sol['centre_ra_dec'], wcs_header=sol['wcs_header'],
                        nebula=dict(catalogue_ra_dec=[TARGET['ra_deg'], TARGET['dec_deg']], catalogue_place_stack_px=sol['nebula_catalogue_px'], light_centre_stack_px=sol['nebula_light_centre_px'], light_centre_ra_dec=sol['nebula_light_centre_ra_dec'],
                                    light_centre_from_catalogue_arcsec=sol['light_centre_from_catalogue_arcsec'], centre_in_tif_px=s8['tif']['nebula_centre_in_tif_px']),
                        picture=dict(file='final/ngc2392.png', size_px=s8['picture_size'], scale_arcsec_per_px=PS, field_arcmin=s8['picture_field_arcmin'], nebula_centre_px=s8['nebula_centre_in_picture_px'],
                                     north_deg_clockwise_from_up=s8['north_deg_clockwise_from_up_after'], east_deg_clockwise_from_up=s8['east_deg_clockwise_from_up_after'], mirrored=sol['mirrored'],
                                     made_from_stack_px=s8['crop_stack_px'], quarter_turns_counter_clockwise=s8['quarter_turns_counter_clockwise'],
                                     inner_shell_diameter_arcsec=INNER_DIAMETER_ARCSEC, inner_shell_diameter_px=INNER_DIAMETER_ARCSEC / PS, outer_disc_diameter_arcsec=OUTER_DIAMETER_ARCSEC, outer_disc_diameter_px=OUTER_DIAMETER_ARCSEC / PS)),
    scale_of_the_picture=dict(arcsec_per_px=PS, which='one picture pixel per 2 x 2 colour cell of the sensor (not the 0.388 arcsec sensor pixel)',
                              why='as NGC 1535 earlier tonight and the Ring Nebula and the Crystal Ball last week: the stack is made from the four RAW colour planes without a demosaic, and each plane has one sample per 2 x 2 cell, so the cell is the finest grid on which every colour is measured and nothing is interpolated. A picture at 0.388 arcsec would be this one enlarged twice, and the stars are %.1f arcsec wide: nothing would be gained.' % s7['star_size']['half_flux_diameter_arcsec'],
                              enlargement='none; the crop is turned by quarter turns only (no resampling after the stack)'),
    not_done=dict(deconvolution='not tried (last week it was tried on five targets and delivered on none)', demosaic='none', darks='none taken', retouching='none: nothing painted, cloned or repaired',
                  dust_check_on_this_run='not possible on a 16 DN sky in 4 s frames: see steps[5].flat'),
    outputs={'ngc2392-stack.tif': dict(what='the linear stack, 16-bit RGB, the area every used frame covers', sha256=sha(os.path.join(OUT, 'ngc2392-stack.tif')), **s8['tif']),
             'ngc2392.jpg': dict(what='copy of final/ngc2392.jpg'),
             'final/ngc2392.png': dict(what='the finished picture, %d x %d px at %.3f arcsec per px' % (*s8['picture_size'], PS), sha256=sha(os.path.join(FINAL, 'ngc2392.png'))),
             'final/ngc2392.jpg': dict(what='the same as JPEG', sha256=sha(os.path.join(FINAL, 'ngc2392.jpg'))),
             'final/ngc2392.json': dict(what='the finish tool\'s recipe (levels, quiet sky, colour)')},
    caveats=CAVEATS,
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
v = recipe['verdict']
print('recipe.json written:', os.path.join(OUT, 'recipe.json'))
for k in v: print(' ', k, ':', v[k])
print(sky)
