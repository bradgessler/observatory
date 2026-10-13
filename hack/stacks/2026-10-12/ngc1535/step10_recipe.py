"""Step 10: recipe.json beside the stack, with every number that shaped the picture, and a copy of the finished JPEG
beside it. Gathers what the earlier steps wrote (their JSON in the work folder) and the finish tool's own recipe."""
import datetime, hashlib, json, os, platform, shutil, subprocess, sys
import numpy as np, cv2, rawpy, tifffile
from common import *

s1 = jload('step1.json'); s3 = jload('step3_transforms.json'); s4 = jload('step4_select.json'); s5 = jload('step5_solve_ref.json')
s6 = jload('step6_stack.json'); s7 = jload('step7_measure.json'); s8 = jload('step8_render.json')
fin = json.load(open(os.path.join(FINAL, 'ngc1535.json')))
tr = {o['stamp']: o for o in s3['transforms']}; used = {u['stamp']: u for u in s4['used']}; rej = {r['stamp']: r for r in s4['rejected']}
sha = lambda p: hashlib.sha256(open(p, 'rb').read()).hexdigest()
shutil.copyfile(os.path.join(FINAL, 'ngc1535.jpg'), os.path.join(OUT, 'ngc1535.jpg'))
sky = subprocess.run([sys.executable, os.path.join(SCR, 'skycheck.py'), os.path.join(FINAL, 'ngc1535.png')], capture_output=True, text=True).stdout.strip()
try: an = subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip().splitlines()[-1]
except Exception: an = None
frames = []
for f in s1['frames']:
    s = f['stamp']; o = tr[s]; q = s4['quality'].get(s, {})
    frames.append(dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'], run=1 if s < '20261013-094430' else 2, used=s in used,
                       why_dropped=rej[s]['why'] if s in rej else None, weight=used[s]['weight'] if s in used else None, transparency=q.get('transparency'), half_flux_diameter_arcsec=q.get('hfd_arcsec'),
                       elongation_median=q.get('elong'), common_ellipticity=q.get('coh'), since_slew_s=f['since_slew_s'], mount_axes_turned_arcsec=f['mount_axes_turned_arcsec'], box_star_size_arcsec=f['box_star_size_arcsec'],
                       shift_at_centre_sensor_px=o.get('shift_at_centre_px'), rotation_deg=o.get('rotation_deg'), registration_wrms_px=o.get('wrms_px'), registration_stars=o.get('used'),
                       sky_constants_dn=s6['constants_dn'].get(s), pixels_at_sensor_ceiling_whole_frame=f['ceiling_pixels'], transient_note='hot pixels repaired on the fly, see steps'))
G, B, R = (s7['shell'][c]['shell_summary'] for c in 'GBR')
sol = s7['solve']; PS = sol['pixscale_arcsec']; n_used = len(used)
profile = s7['shell']['G']['mean']['profile_dn_per_px']
recipe = dict(
    what='NGC 1535 ("Cleopatra\'s Eye", a planetary nebula in Eridanus): %d of %d frames of 4 s at ISO 1600 (Sony a6000 on a Celestron 8SE at f/10, EQ6-R tracking), stacked from RAW colour planes with rotation, flat-fielded with the night\'s flat' % (n_used, len(s1['frames'])),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), owner='Brad Gessler',
    verdict=dict(
        identity=s5['verdict'] + '; the brightest source in the field is a star %.1f arcmin away' % s5['brightest_source']['from_catalogue_arcmin'],
        total_exposure_s=n_used * EXPOSURE_S,
        star_size_in_the_stack_arcsec=s7['star_size']['half_flux_diameter_arcsec'],
        clipping=s7['clipping']['verdict'] + ' (highest raw value %d of 16,372: %.0f%% of the range above black)' % (max(s7['clipping']['highest_raw_value_in_any_frame'].values()), 100 * max(s7['clipping']['highest_as_fraction_of_ceiling'].values())),
        inner_disc='seen: a blue-green disc; in the stack its green light is %.0f DN per pixel at the centre and 80 to 110 DN from 5 to 8 arcsec out' % G['peak_dn_per_px'],
        central_star='seen as a star-wide peak at the middle of the disc (%.0f DN at the centre against about 100 DN of disc around it; fitted as a point of %.0f DN on a disc of %.0f DN in green). At a star size of %.1f arcsec it is a bright core, not a separate point.' % (
            profile[0], s7['shell']['G']['no_shell_model']['point_flux_dn'], s7['shell']['G']['no_shell_model']['disc_flux_dn'], s7['star_size']['half_flux_diameter_arcsec']),
        outer_shell='seen and proven: in the ring %.0f to %.0f arcsec from the central star the green light is %.2f DN per pixel (odd frames %.2f, even frames %.2f; noise of the same ring on blank sky %.3f), where the bright disc and central star blurred by the stack\'s own star profile would leave %.2f: %.1f sigma above that in the whole stack, %.1f and %.1f in the two halves; in blue %.1f sigma (%.1f and %.1f), in red %.1f. The light ends between 28 and 34 arcsec from the centre.' % (
            G['observed_dn'] and s7['shell']['G']['mean']['shell']['arcsec'][0], s7['shell']['G']['mean']['shell']['arcsec'][1], G['observed_dn'], G['odd_dn'], G['even_dn'], s7['shell']['G']['mean']['shell']['blank_sky_sigma_dn'], G['spilled_from_the_disc_model_dn'],
            G['excess_sigma'], G['odd_excess_sigma'], G['even_excess_sigma'], B['excess_sigma'], B['odd_excess_sigma'], B['even_excess_sigma'], R['excess_sigma']),
        not_seen='no structure inside the disc (no rim, no inner ring, no filaments) and no sharp boundary between disc and shell: at 5.8 arcsec stars the two run into each other; the shell shows as a dimmer zone with an outer edge. A brighter spot in the shell about 17 arcsec from the centre repeats in both halves; it is not identified (a field star or a knot).'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=rawpy.libraw_version if hasattr(rawpy, 'libraw_version') else None, tifffile=tifffile.__version__, astrometry_net=an,
               note='deterministic array arithmetic only: averages, medians, fitted rotations and planes, Gaussian, median and bilateral filters, an arcsinh curve. Nothing generative, learned or predictive. No deconvolution. Nothing painted or repaired by hand.'),
    scripts='hack/stacks/2026-10-12/ngc1535/ in the observatory repository: run_all.sh runs step1_frames.py ... step10_recipe.py (common.py, solvelib.py, fitsmin.py; finish16.py and skycheck.py are the finish-pictures tools), then step11_clean.py',
    source=dict(folder=STILLS, window_utc=[T0, T1], frames_found=len(s1['frames']), frames_used=n_used, frames_dropped=len(s1['frames']) - n_used, total_exposure_s=n_used * EXPOSURE_S,
                dropped={r['stamp']: r['why'] for r in s4['rejected']}, left_out_before_the_count=s1['left_out'], originals='read in place, never modified', darks='none: hot pixels come from the run itself (step 1)',
                all_frames_present_at_start='yes: all 33 RAWs of the run were on this Mac when the stack was made (the last, DSC01289, finished copying a few minutes before)'),
    selection=dict(limits=s4['limits'], quality_stars=s4['quality_stars'], tracking_turn_median_arcsec=s4['tracking_turn_median_arcsec'], clear_frames_median_star_size_arcsec=s4['hfd_clear_median_arcsec'], sum_of_weights=s4['sum_of_weights'],
                   note='the first frame after the restart (09:45:09) was taken while the mount was moving (its axes turned -207 and +98 arcsec during the exposure); its stars measure round all the same, and it is dropped on the mount\'s word'),
    frames=frames,
    steps=[
        dict(step=1, script='step1_frames.py', what='the run by the RAWs\' own EXIF and the sidecars\' pointing; hot pixels from the unregistered median of the run', hot=s1['hot']),
        dict(step=2, script='step2_stars.py', what='sources in every frame on the mean of the green planes (5 sigma), centroids, flux, half-flux radius, shape'),
        dict(step=3, script='step3_register.py', what='rotation + shift per frame on the stars (no scale, no shear)', reference=s3['reference'], reference_rule=s3['reference_rule'],
             shift_between_the_runs_sensor_px='the second run sits about (+870, -760) sensor px from the first', rotation_range_deg=[min(o['rotation_deg'] for o in s3['transforms'] if not o['failed']), max(o['rotation_deg'] for o in s3['transforms'] if not o['failed'])]),
        dict(step=4, script='step4_select.py', what='quality per frame and the selection rule (see selection)'),
        dict(step=5, script='step5_solve_ref.py', what='plate solve of the reference frame before stacking: is it the thing?', result={k: v for k, v in s5.items() if k not in ('wcs_header', 'corners_ra_dec')}),
        dict(step=6, script='step6_stack.py', what='flat, one Lanczos-4 resampling per plane onto the reference frame\'s colour cells, one sky constant per colour per frame, sigma-clipped weighted mean; odd and even halves; atmospheric dispersion measured on stars and removed in the same resampling',
             **{k: s6[k] for k in ('grid', 'kappa', 'flat', 'fixed_hot_pixels_within_30px_of_the_nebula', 'sky', 'planes', 'colour_offsets', 'subsets', 'frames_covering_every_pixel', 'full_coverage_fraction')}),
        dict(step=7, script='step7_measure.py', what='plate solve of the stack, star size, clipping from the RAWs, the shell test', **{k: s7[k] for k in ('star_size', 'psf_stars', 'blank_sky_placements')},
             clipping={k: v for k, v in s7['clipping'].items()}, shell=s7['shell']),
        dict(step=8, script='step8_render.py', what='the linear TIF; the crop (quarter turns only), a sky plane per colour fitted away from the nebula (in the picture only), camera matrix, luminance and colour blurs, arcsinh stretch', **s8),
        dict(step=9, script='step9_finish.sh', what='finish16.py (levels, quiet sky, colour) and skycheck.py', finish=fin, skycheck=sky),
    ],
    plate_solution=dict(of='the stack (ngc1535-stack.tif is the stack\'s area x0, y0 = %d, %d: subtract these from stack px)' % (s8['tif']['area_stack_px']['x0'], s8['tif']['area_stack_px']['y0']),
                        scale_arcsec_per_stack_px=PS, scale_arcsec_per_sensor_px=PS / 2, focal_length_mm=sol['focal_length_mm'], mirrored=sol['mirrored'],
                        north_deg_clockwise_from_up_in_the_stack=sol['north_angle_from_up_deg_clockwise'], east_deg_clockwise_from_up_in_the_stack=sol['east_angle_from_up_deg_clockwise'],
                        stack_centre_ra_dec=sol['centre_ra_dec'], wcs_header=sol['wcs_header'],
                        nebula=dict(catalogue_ra_dec=[TARGET['ra_deg'], TARGET['dec_deg']], catalogue_place_stack_px=sol['nebula_catalogue_px'], light_centre_stack_px=sol['nebula_light_centre_px'], light_centre_ra_dec=sol['nebula_light_centre_ra_dec'],
                                    light_centre_from_catalogue_arcsec=sol['light_centre_from_catalogue_arcsec'], centre_in_tif_px=s8['tif']['nebula_centre_in_tif_px']),
                        picture=dict(file='final/ngc1535.png', size_px=s8['picture_size'], scale_arcsec_per_px=PS, field_arcmin=s8['picture_field_arcmin'], nebula_centre_px=s8['nebula_centre_in_picture_px'],
                                     north_deg_clockwise_from_up=s8['north_deg_clockwise_from_up_after'], east_deg_clockwise_from_up=s8['east_deg_clockwise_from_up_after'], mirrored=sol['mirrored'],
                                     made_from_stack_px=s8['crop_stack_px'], quarter_turns_counter_clockwise=s8['quarter_turns_counter_clockwise'],
                                     inner_disc_20_arcsec_is_px=INNER_DIAMETER_ARCSEC / PS, outer_shell_50_arcsec_is_px=OUTER_DIAMETER_ARCSEC / PS)),
    scale_of_the_picture=dict(arcsec_per_px=PS, which='one picture pixel per 2 x 2 colour cell of the sensor (not the 0.388 arcsec sensor pixel)',
                              why='as the Ring Nebula and the Crystal Ball last week: the stack is made from the four RAW colour planes without a demosaic, and each plane has one sample per 2 x 2 cell, so the cell is the finest grid on which every colour is measured and nothing is interpolated. A picture at 0.388 arcsec would be this one enlarged twice, and the stars are 5.8 arcsec wide: nothing would be gained.',
                              enlargement='none; the crop is turned by quarter turns only (no resampling after the stack)'),
    not_done=dict(deconvolution='not tried (last week it was tried on five targets and delivered on none)', demosaic='none', darks='none taken', retouching='none: nothing painted, cloned or repaired',
                  dust_check_on_this_run='not possible on a 16 DN sky in 4 s frames: see steps[5].flat'),
    outputs={'ngc1535-stack.tif': dict(what='the linear stack, 16-bit RGB, the area every used frame covers', sha256=sha(os.path.join(OUT, 'ngc1535-stack.tif')), **s8['tif']),
             'ngc1535.jpg': dict(what='copy of final/ngc1535.jpg'),
             'final/ngc1535.png': dict(what='the finished picture, %d x %d px at %.3f arcsec per px' % (*s8['picture_size'], PS), sha256=sha(os.path.join(FINAL, 'ngc1535.png'))),
             'final/ngc1535.jpg': dict(what='the same as JPEG', sha256=sha(os.path.join(FINAL, 'ngc1535.jpg'))),
             'final/ngc1535.json': dict(what='the finish tool\'s recipe (levels, quiet sky, colour)')},
    caveats=[
        'The nebula is 60 px across in a 720 x 480 picture: small, because nothing is enlarged.',
        'Red is at zero across the disc in the finished picture: the nebula\'s [O III] light at 501 nm lies outside sRGB, the camera matrix gives it a negative red, and the picture clips that at 0. This is the colour space, not the sensor.',
        'The colour offsets for atmospheric dispersion were measured on starlight; for the nebula\'s line emission the blue plane is then off by about 0.2 px (0.15 arcsec): see steps[5].colour_offsets.nebula_own.',
        'The flat\'s dust could not be checked against this run (sky too faint in 4 s). The nearest shadow the flat carries is 266 plane px from where the nebula sat in the first run and 147 in the second; the M77 stack turned down a candidate 32 px from the first-run place (its list: steps[5].flat.dust_near_the_nebula). The odd and even halves each hold frames of both runs, which sat 435 px apart on the sensor, and agree to 1% on the nebula.',
        'The shell\'s outer edge is grainy at full size: there the signal is 3 to 8 DN against about 1 DN of noise per pixel. The finish tool\'s smoothing was kept below it on purpose.',
        'The sky plane fitted in the crop (under 1.5 DN across it) is in the picture only; the stack has one constant per colour per frame.',
        'The first frame after the restart is dropped on the sidecar\'s record of the mount moving, although its stars look round; one frame is dropped for star size 6.55 arcsec against a limit of 6.5 (a hair), one for trailing (common ellipticity 0.23).'],
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
v = recipe['verdict']
print('recipe.json written:', os.path.join(OUT, 'recipe.json'))
for k in v: print(' ', k, ':', v[k])
print(sky)
