"""Step 15: the recipe. Everything that went in, everything that was left out and why, every number that was
used, in one JSON beside the pictures; and a copy of these scripts. Nothing is computed here that changes a picture."""
import datetime, glob, json, os, shutil, sys
import numpy as np, cv2, rawpy, scipy, tifffile, PIL
from common import *

L = lambda n: json.load(open(W(n)))
s1 = L('s1.json'); s2 = L('s2.json'); T4 = L('s4_transforms.json'); SEL = L('s5_select.json'); FL = L('s6_flat.json'); HDR = L('s9_hdr.json'); CORE = L('s9b_core.json')
S8 = L('s8_solve.json'); PL = L('s10_place.json'); R11 = L('s11_resample.json'); BG = L('s12_background.json'); S13 = L('s13_mosaic.json'); D14 = L('s14_deliver.json')
S7 = {k: L('s7_%s.json' % k) for k in SEL}
SWID = L('s9c_starwidth.json')
FCHK = L('s12b_flatcheck.json') if os.path.exists(W('s12b_flatcheck.json')) else None
CLOUD = {k: L(k + '_cloud.json') for k in ('s10_place', 's12_background', 's13_mosaic', 's9_hdr', 's6_flat')} if os.path.exists(W('s10_place_cloud.json')) and FL['source'].startswith('twilight') else None
TWI = {k: L(k + '_twilight.json') for k in ('s10_place', 's12_background', 's13_mosaic', 's9_hdr', 's12b_flatcheck')} if os.path.exists(W('s12b_flatcheck_twilight.json')) and 'cloud flat' in FL['source'] else None
SH = L('sharpen_report.json') if os.path.exists(W('sharpen_report.json')) else None
NOTES = L('notes.json') if os.path.exists(W('notes.json')) else {}
F = {f['stamp']: f for f in s1['frames']}
SETNAME = dict(deep='deep centred (20 s ISO 3200)', short='short centred (2 s ISO 800)', p00='mosaic panel (0,0)', p10='mosaic panel (1,0)', p11='mosaic panel (1,1)', p01='mosaic panel (0,1)', stray1='stray group at 1123 (20 s ISO 3200, 2.2 arcmin E 7.6 arcmin N of the Trapezium)')

# ---------------- frames ----------------
frames = {}; counts = {}
for k in SEL:
    used = {u['stamp']: u for u in SEL[k]['used']}; rej = {r['stamp']: r for r in SEL[k]['rejected']}; q = {r['stamp']: r for r in SEL[k]['quality']}
    tr = {o['stamp']: o for o in T4[k]['transforms']}
    rows = []
    for st in sorted(q):
        f = F[st]; o = q[st]; t = tr[st]
        row = dict(file=f['name'], sha256=f['arw_sha256'], utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], altitude_deg=round(f['alt_deg'], 1), sky_green_dn=round(f['sky_green'], 1), noise_dn=round(f['noise_g1'], 1),
                   as_shot_wb=[v / 1024 for v in f['wb'][:3]], pixels_at_ceiling=f['ceiling_pixels'],
                   transparency=None if o.get('flux_rel') is None else round(o['flux_rel'], 3), star_hfd_arcsec=None if o.get('hfd_arcsec') is None else round(o['hfd_arcsec'], 2), elongation=None if o.get('elong_median') is None else round(min(o['elong_median'], 99.0), 2),
                   registered=not t.get('failed', False), shift_at_centre_px=None if t.get('failed') else [round(v, 1) for v in t['shift_at_centre_px']], rotation_deg=None if t.get('failed') else round(t['rotation_deg'], 4), registration_rms_px=None if t.get('failed') else round(t['wrms_px'], 2))
        if f.get('settings_mismatch'): row['note'] = 'sidecar says %s s ISO %s, the camera\'s EXIF says %s s ISO %s: EXIF believed (the levels agree with it)' % (f['sidecar_exposure_s'], f['sidecar_iso'], f['exif_exposure_s'], f['exif_iso'])
        if st in used: row.update(used=True, weight=round(used[st]['weight'], 3), multiplied_by=round(used[st]['scale'], 4))
        else: row.update(used=False, why=rej[st]['why'])
        rows.append(row)
    frames[k] = rows
    why = {}
    for r in rows:
        if not r['used']: key = r['why'].split(':')[0]; why[key] = why.get(key, 0) + 1
    counts[k] = dict(what=SETNAME.get(k, k), found=len(rows), used=len(used), rejected=len(rej), rejected_by_reason=why, exposure_used_s=round(sum(F[s]['exposure_s'] for s in used), 1), summed_weights=round(SEL[k]['summed_weights'], 2),
                     first=min(used) if used else None, last=max(used) if used else None, registration_reference=T4[k]['reference'], clearest_frame=SEL[k]['background_reference'],
                     clear_sky_green_dn=round(SEL[k]['sky_green_clear_median'], 1), clear_frame_star_hfd_arcsec=round(SEL[k]['hfd_clear_median_arcsec'], 2), stack_noise_dn_per_half_grid_px=S7[k]['noise_of_stack_dn_per_half_grid_px'])
left = [dict(file=f['name'], utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], why=f['why']) for f in s1['left_out']]

hair = {k: [v['centre_sensor_xy'] for v in S7[k]['hair'].values() if v] for k in S7}
flat_twilight = FL['source'] == 'twilight'
steps = [
    dict(step='read', detail='RAW (.ARW) read with rawpy/LibRaw as the sensor recorded it: 6024 x 4024, RGGB, black 512 subtracted; no demosaic, no colour matrix, no curve. The four colour planes (R, G1, G2, B; 3012 x 2012 each) are kept apart to the end. Settings taken from the camera\'s EXIF and checked against the sidecar.'),
    dict(step='group', detail='by settings and by the mount pointing in the sidecar; finder frames (2 s ISO 6400) left out; names checked afterwards by plate solving each stack', groups={k: counts[k]['what'] for k in counts}, plate_solutions={k: dict(centre_arcmin_east_north_of_trapezium=PL['catalogue_after_joint_solve'][k]['centre_arcmin_east_north'], catalogue_stars=PL['catalogue_after_joint_solve'][k]['stars'], rms_arcsec=PL['catalogue_after_joint_solve'][k]['rms_arcsec']) for k in PL['images']}),
    dict(step='hot pixels', detail='fixed: per-plane median, without registration, of clear 20 s frames from several pointings (each minus its sky level); a pixel is hot if it stands above the 5x5 median of that by more than max(6 sigma, 25% of the level) AND above its highest neighbour by half that. A separate map for the 2 s frames. Single-frame spikes: above the 3x3 median by more than 8 sigma + 50% of the level. Both replaced by the 3x3 median of the same plane.', maps=s2),
    dict(step='stars', detail='per frame, on the mean of the two green planes: smooth light removed (8x shrink, 5x5 median, Gaussian), 6 sigma detection in units of the local noise, windowed centroid, 28 px (sensor) aperture; nothing within 300 sensor px of the brightest nebula is used for registration or quality'),
    dict(step='register', detail='rotation + shift (scale held at 1) of every frame to its set\'s reference frame, from matched star centroids; first guess from the most common offset between the bright stars of the two frames; the 2 s frames are registered to the deep set\'s reference so both stacks share one grid', rms_px={k: [round(float(np.median([o['wrms_px'] for o in T4[k]['transforms'] if not o.get('failed') and o['wrms_px'] > 0] or [0])), 2)] for k in T4},
         deep_set_motion=dict(rotation_range_deg=[round(min(o['rotation_deg'] for o in T4['deep']['transforms'] if not o.get('failed') and o['stamp'] in {u['stamp'] for u in SEL['deep']['used']}), 3), round(max(o['rotation_deg'] for o in T4['deep']['transforms'] if not o.get('failed') and o['stamp'] in {u['stamp'] for u in SEL['deep']['used']}), 3)],
                              shift_x_range_px=[round(min(o['shift_at_centre_px'][0] for o in T4['deep']['transforms'] if not o.get('failed') and o['stamp'] in {u['stamp'] for u in SEL['deep']['used']}), 1), round(max(o['shift_at_centre_px'][0] for o in T4['deep']['transforms'] if not o.get('failed') and o['stamp'] in {u['stamp'] for u in SEL['deep']['used']}), 1)],
                              note='the centred frames were taken in four groups, re-centred in between: the main run within 40 px of the reference, the others about 360 px to one side. That shift is what lets the frames of one group fill the hair\'s hole of the other.')),
    dict(step='select', detail='transparency = each star\'s flux over its flux in the set\'s clear frames, median over the stars. Used if transparency >= 0.80, even across the field (under 10% per 3000 px), stars no wider than 1.30 x the clear median, elongation <= 1.60, registration rms <= 1 px, weight >= 0.30. Used frames are multiplied by 1 / transparency and weighted by (transparency / noise)^2.', limits=SEL['deep']['limits']),
    dict(step='flat field', source=FL['source'], detail=FL['what'], numbers={k: v for k, v in FL.items() if k not in ('what', 'frames', 'flats_log')}, frames=FL.get('frames')),
    dict(step='flat field: checked against the sky and against the cloud flat', flat_check_from_overlaps=FCHK, detail=open(os.path.join(SCR, 's12b_flatcheck.py')).read().split('"""')[1],
         the_same_pipeline_with_the_other_flats=None if CLOUD is None else dict(
             what='the whole pipeline was run three times: with tonight\'s cloud flat (flat2d x dust map of the M31 core run, dust-mask pixels left out), with the twilight master flat as it is, and with the delivered flat. Numbers of the first two runs, for comparison:',
             photometric_multipliers_green=dict(cloud_flat=CLOUD['s10_place']['photometric_multipliers']['G'], twilight_flat_as_it_is=None if TWI is None else TWI['s10_place']['photometric_multipliers']['G'], delivered=PL['photometric_multipliers']['G']),
             panel_background_terms_green=dict(cloud_flat={k: v['terms'] for k, v in CLOUD['s12_background']['G']['B_constants_and_planes']['parameters'].items()}, twilight_flat_as_it_is=None if TWI is None else {k: v['terms'] for k, v in TWI['s12_background']['G']['B_constants_and_planes']['parameters'].items()},
                                               delivered={k: v['terms'] for k, v in BG['G']['B_constants_and_planes']['parameters'].items()}),
             rms_of_overlap_differences_dn=dict(cloud_flat={c: dict(constants=CLOUD['s12_background'][c]['A_constants']['rms_faint_blocks_away_from_core'], constants_and_planes=CLOUD['s12_background'][c]['B_constants_and_planes']['rms_faint_blocks_away_from_core']) for c in 'RGB'},
                                                twilight_flat_as_it_is=None if TWI is None else {c: dict(constants=TWI['s12_background'][c]['A_constants']['rms_faint_blocks_away_from_core'], constants_and_planes=TWI['s12_background'][c]['B_constants_and_planes']['rms_faint_blocks_away_from_core']) for c in 'RGB'},
                                                delivered={c: dict(constants=BG[c]['A_constants']['rms_faint_blocks_away_from_core'], constants_and_planes=BG[c]['B_constants_and_planes']['rms_faint_blocks_away_from_core']) for c in 'RGB'}),
             flat_check_with_the_twilight_flat_as_it_is=None if TWI is None else TWI['s12b_flatcheck'],
             zero_dn=dict(cloud_flat=CLOUD['s13_mosaic']['zero_taken_off_dn'], delivered=S13['zero_taken_off_dn']),
             short_to_deep_factor=dict(cloud_flat=CLOUD['s9_hdr']['factor_applied'], twilight_flat_as_it_is=None if TWI is None else TWI['s9_hdr']['factor_applied'], delivered=HDR['factor_applied']))),
    dict(step='the hair', detail='found in every 20 s frame from the frame itself (green / smooth flat, blurred, over its grey closing with a 61 px ellipse; largest patch below 0.86 in the search zone, grown by 60 sensor px) and left out of the average. The 2 s frames cannot show it (3 DN of sky): its place is taken from the 20 s frames nearest in time. Where no frame of a set is clear of it the stack has no data; in the centred stack the frames of the shifted groups fill the hole of the main run, with fewer frames.',
         search_zone_sensor_px=HAIR_BOX, hair_centre_sensor_px_first_and_last={k: [v[0], v[-1]] for k, v in hair.items() if v}, pixels_without_data_for_the_hair={k: S7[k]['flags']['hair_no_data'] for k in S7}),
    dict(step='resample', detail='each plane onto the half grid of its set\'s reference frame (rotation + shift + the plane\'s place in the 2x2 colour cell), Lanczos-4; one sample per plane per half-grid pixel, nothing interpolated up'),
    dict(step='frame backgrounds', detail='20 s frames: minus a second-order surface (six numbers per plane) fitted to (frame - the set\'s clearest frame) on 64 px block medians, blocks weighted down where the nebula is bright; the nebula cancels in the difference, so none of it is fitted. 2 s frames: one constant per plane (which also takes up the camera\'s black level, which jumps by about 4.4 DN between frames in single planes at ISO 800).',
         largest_surface_range_dn_green={k: [round(min([s_[1]['surface_min_max_dn'][0] for s_ in S7[k]['surfaces_taken_off'].values() if 'surface_min_max_dn' in s_[1]] or [0]), 1), round(max([s_[1]['surface_min_max_dn'][1] for s_ in S7[k]['surfaces_taken_off'].values() if 'surface_min_max_dn' in s_[1]] or [0]), 1)] for k in S7 if k != 'short'}),
    dict(step='combine', detail='per pixel and plane: values further than 3 sigma from the median dropped (sigma = 1.4826 x MAD, floor 0.4 x single-frame noise), then 3 sigma about the weighted mean, then the weighted mean. Two samples: if they differ by more than 5 sigma the lower is kept.', per_set={k: dict(planes=S7[k]['planes'], flags=S7[k]['flags']) for k in S7}),
    dict(step='clipping masks', detail='per frame, after the hot-pixel repair: any of the four planes of a 2x2 cell at or above %.0f DN over black (the ceiling is about 15500), grown by one cell, carried onto the grid and counted' % NEAR_CEILING, near_ceiling_dn=NEAR_CEILING, ceiling_dn=CEILING_RAW - BLACK,
         pixels_near_ceiling_in_any_frame={k: S7[k]['pixels_near_ceiling_in_any_frame'] for k in S7}),
    dict(step='HDR blend', detail=open(os.path.join(SCR, 's9_hdr.py')).read().split('"""')[1], numbers=HDR),
    dict(step='place on the sky', detail='each stack plate-solved (astrometry.net, Tycho-2 indexes, 2 degree hint), then all affine maps solved jointly with the stars the stacks share', overlaps=PL['overlaps_after_joint_solve'], catalogue=PL['catalogue_after_joint_solve'], grid=PL['grid']),
    dict(step='photometric scale of the panels', detail='one multiplier per panel from the aperture fluxes of shared unsaturated stars (green; applied to all three colours), the deep stack held at 1', multipliers=PL['photometric_multipliers'], pairs_green=PL['photometric_pairs']['G']),
    dict(step='panel backgrounds', detail='one constant and one plane per panel and colour, solved over all overlaps at once against the deep stack (64 px block medians of the differences, bright nebula weighted down, blocks within %.0f arcmin of the Trapezium kept out); no free-form surface' % BG['near_core_arcmin'],
         model='B_constants_and_planes', parameters={c: BG[c]['B_constants_and_planes']['parameters'] for c in 'RGB'}, overlaps_left_dn={c: BG[c]['B_constants_and_planes']['overlaps'] for c in 'RGB'},
         rms_constants_only={c: BG[c]['A_constants']['rms_faint_blocks_away_from_core'] for c in 'RGB'}, rms_constants_and_planes={c: BG[c]['B_constants_and_planes']['rms_faint_blocks_away_from_core'] for c in 'RGB'}),
    dict(step='mosaic combine', detail='weighted mean, weight = feather x inverse variance x quality, the same for the three colours; the deep stack\'s feather is 300 px (fourth power), the panels\' 200 px; a panel\'s clipped star cores get a thousandth of their weight', numbers={k: v for k, v in S13.items() if k not in ('zero_region',)}, per_stack=R11),
    dict(step='background (the zero)', detail='ONE CONSTANT PER COLOUR, no plane, no surface. The three constants are the levels of R, G and B (camera planes, before white balance) in the darkest well-covered part of the whole mosaic: the 3-sigma clipped mean over the 64 px blocks whose smoothed green is in the lowest 2%. The same three numbers are taken off the centred picture. No plane was subtracted: no part of the field is certainly free of nebula, so nothing supports one.',
         constants_dn=S13['zero_taken_off_dn'], zero_region=S13['zero_region'], darkest_part_of_the_centred_stack_alone=S13['darkest_part_of_the_centred_stack_alone'],
         what_is_in_the_constant='the moonlit sky of the clearest frame (115711 UTC), the dark signal of a 20 s ISO 3200 frame (the short-to-deep fit puts 45 to 78 DN per plane in the deep frames that 41 x the short frames do not have), and whatever the nebula and the Orion cloud give in the darkest part of the field'),
    dict(step='colour', detail='G = mean of G1 and G2; R x %.4f and B x %.4f: the camera\'s as-shot white balance, median over the deep frames used. No colour matrix, no saturation change in m42.png. The camera\'s automatic white balance moved with the scene: the 2 s frames carry R x 2.746, B x 1.688, the panels about R x 2.90, B x 1.55; ONE pair (the deep frames\') is used for everything. Extras: star-white (R x %.4f, B x %.4f, from %d unsaturated field stars) and one global saturation factor of %.2f.' % (D14['white_balance']['as_shot']['R'], D14['white_balance']['as_shot']['B'], D14['white_balance']['star_white']['R'], D14['white_balance']['star_white']['B'], D14['star_colour']['stars'], D14['saturation_boost_of_the_extra']),
         as_shot_multipliers=D14['white_balance']['as_shot'], star_white_multipliers=D14['white_balance']['star_white'], field_stars=D14['star_colour'], colour_pedestal_dn=dict(centred=D14['colour_pedestal_deep_dn'], mosaic=S13['colour_pedestal_dn']),
         white_rule='pixels near the ceiling even in a 2 s frame (and a panel\'s clipped star cores) are given equal R, G and B: the largest of the three recorded values, never multiplied by the white balance'),
    dict(step='tone', detail=open(os.path.join(SCR, 'render.py')).read().split('"""')[1], centred=D14['stretch'], grain=D14['grain'], core=D14['core_stretch'], mosaic=D14['outputs']['m42-mosaic.png / .jpg']['stretch'],
         curve_samples_dn_to_8bit_grey=None),
]
# the curve, sampled, so it can be read without the code
from render import curve
st = D14['stretch']
steps[-1]['curve_samples_dn_to_8bit_grey'] = {str(v): int(round(float(curve(np.array([float(v)]), st['white'], st['soft'], st['pedestal'], st['gamma'])[0]) * 255)) for v in (-3, 0, 3, 10, 30, 100, 300, 1000, 3000, 10000, 20000, 40000)}

noise = dict(deep_stack_dn_per_half_grid_px=S7['deep']['noise_of_stack_dn_per_half_grid_px'], short_stack_dn=S7['short']['noise_of_stack_dn_per_half_grid_px'], short_stack_in_deep_units_dn={k: round(v * HDR['factor_applied'], 1) for k, v in S7['short']['noise_of_stack_dn_per_half_grid_px'].items()},
             single_deep_frame_dn=round(SEL['deep']['noise_clear_median'], 1), how='(stack of the odd frames - stack of the even frames), scaled, in the faintest quarter of the fully covered field; 3-sigma clipped standard deviation')
recipe = dict(
    what='M42, the Orion Nebula, with M43: a centred HDR picture (%d x 20 s ISO 3200 = %.1f min, with %d x 2 s ISO 800 blended in where the long frames clip) and a mosaic round it (four panels and a stray group, %d more 20 s frames), Sony a6000 on a Celestron 8SE at f/10, stacked from RAW colour planes' % (
        counts['deep']['used'], counts['deep']['exposure_used_s'] / 60, counts['short']['used'], sum(counts[k]['used'] for k in counts if k not in ('deep', 'short'))),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=sys.version.split()[0], numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=list(rawpy.libraw_version), tifffile=tifffile.__version__, pillow=PIL.__version__, astrometry='astrometry.net solve-field, image2xy (Tycho-2 indexes 4107..4114)',
               note='deterministic array arithmetic only: averages, medians, Gaussian and Lanczos filters, least squares. Nothing generative or learned; no denoiser, upscaler, star remover or inpainting. Where there is no data the picture is black.'),
    source=dict(folder=STILLS, window_utc=[T0, T1], date='2026-10-04', originals='read in place, not modified, moved or deleted', frames_in_window=len(s1['frames']) + len(s1['left_out']), sets=counts, left_out=left,
                settings_mismatch=[dict(file=f['name'], sidecar=[f['sidecar_exposure_s'], f['sidecar_iso']], exif=[f['exif_exposure_s'], f['exif_iso']]) for f in s1['frames'] if f.get('settings_mismatch')]),
    frames=frames,
    steps=steps,
    numbers=dict(short_to_deep=dict(expected=40.0, measured=HDR['factor_applied'], measured_over_expected=HDR['measured_over_expected'], per_plane={f['plane']: dict(factor=f['a'], error=f['a_error'], offset_dn=f['b'], pixels=f['pixels'], by_brightness=f['bins']) for f in HDR['per_plane']}, stars=HDR['stars_check'],
                                    reading='the four planes agree within their errors and the factor is the same from 800 to 6000 DN: the sensor is linear there. It is 2.5% above 40; the camera\'s "20 s" is 2^(13/3) = 20.16 s against a true 2.0 s, which makes 40.3 expected, and the rest is within what the ISO steps and 1% of transparency can do.'),
                 noise=noise, stars_in_the_stacks=SWID, trapezium=D14['outputs']['m42-core.png / .jpg']['trapezium'], zero_dn=S13['zero_taken_off_dn'], hdr_pixels=HDR['pixels']),
    sharpening=SH if SH else dict(delivered=False, tried=False),
    outputs=D14['outputs'],
    orientation=dict(centred_and_core=D14['outputs']['m42.png / .jpg']['orientation'], mosaic='north up, east left (tangent plane about RA %.4f Dec %+.4f)' % (TRAP_RA, TRAP_DEC),
                     frame_on_sky=dict(x_6000px_arcmin_east_north=S8['deep']['x_axis_arcmin_per_6000_sensor_px_east_north'], y_4000px_arcmin_east_north=S8['deep']['y_axis_arcmin_per_4000_sensor_px_east_north'], scale_arcsec_per_sensor_px=round(S8['deep']['scale_arcsec_per_half_px'][0] / 2, 4))),
    what_is_what=NOTES.get('what_is_what'), do_not_trust=NOTES.get('do_not_trust'), what_would_help_most=NOTES.get('what_would_help_most'), pictures_as_seen=NOTES.get('pictures_as_seen'),
    scripts='scripts/ beside this file; run_all.sh runs them in order: ' + ', '.join(sorted(os.path.basename(p) for p in glob.glob(os.path.join(SCR, '*.py')) if not os.path.basename(p).startswith('x_'))) + '. Adapted from ../m31/mosaic/scripts (tonight\'s M31 mosaic pipeline).',
)
dest = W('out_dry') if (len(sys.argv) > 1 and sys.argv[1] == 'dry') else OUT
os.makedirs(os.path.join(dest, 'scripts'), exist_ok=True)
if os.path.isdir(os.path.join(dest, 'calibration')):
    recipe['calibration'] = dict(folder='calibration/ beside this file (copies of the pipeline\'s work files, kept because they serve any other target of this night)',
                                 files={'flat-delivered.npy': 'the flat every frame was divided by: float32 (4, 2012, 3012), planes R, G1, G2, B, each 1 at the sensor centre',
                                        'flat-twilight-master.npy': 'the twilight master flat as it is (before the cloud flat\'s large-scale shape was put on it), same layout; the hair\'s place at dawn (top edge) holds the smooth part',
                                        'flat.json': 'how both were made, every flat frame with its level, and the comparison with the cloud flat',
                                        'hotmap-20s-iso3200.npy': 'boolean (4, 2012, 3012): the fixed hot pixels of the 20 s ISO 3200 frames'})
json.dump(recipe, open(os.path.join(dest, 'm42-recipe.json'), 'w'), indent=1)
for p in glob.glob(os.path.join(SCR, '*.py')) + glob.glob(os.path.join(SCR, '*.sh')):
    if os.path.basename(p).startswith('x_'): continue
    shutil.copy2(p, os.path.join(dest, 'scripts', os.path.basename(p)))
print('recipe written:', os.path.join(dest, 'm42-recipe.json'), os.path.getsize(os.path.join(dest, 'm42-recipe.json')), 'bytes')
print(json.dumps(counts, indent=1)[:3000])
