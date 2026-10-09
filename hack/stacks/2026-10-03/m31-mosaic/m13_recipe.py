"""Mosaic step 13: the recipe. Everything that was done, the numbers it gave, what not to trust, how to run it again.
Also copies the scripts beside the results."""
import datetime, glob, hashlib, json, os, platform, shutil, sys
import numpy as np, cv2, scipy, rawpy, tifffile, PIL
from mcommon import *

L = lambda n: json.load(open(W(n)))
m1 = L('m1.json'); m2 = L('m2.json'); T4 = L('m4_transforms.json'); SEL = L('m5_select.json'); DUST = L('m5b_dustcheck.json'); S7 = L('m7_solve.json'); PL = L('m8_place.json')
R9 = L('m9_resample.json'); BG = L('m10_background.json'); CHK = L('m10b_centre_check.json'); M11 = {k: L('m11_%s.json' % k) for k in ('six', 'centre')}; M12 = L('m12_deliver.json')
core_rec = json.load(open(os.path.join(CORE_DIR, 'm31-core-recipe.json')))
s1 = {f['stamp']: f for f in m1['frames']}
MODEL = M11['six']['background_model']
GRIDNAME = dict(p00='(0,0)', p10='(1,0)', p20='(2,0)', p21='(2,1)', p11='(1,1)', p01='(0,1)', centre='centre check', core='core stack')
PLAN = {n: (e, nn) for n, e, nn in PANELS}
core_noise = R9['core']['noise_green_per_mosaic_px_core_units']['median']
core_clear_equiv_s = core_rec['source']['clear_sky_equivalent_exposure_s']

# ---- what each panel holds: the level of the mosaic where the panel is the only image, against its noise ----
mos = np.load(W('six_rgb.npy'), mmap_mode='r'); cov = np.load(W('six_cover.npy'), mmap_mode='r')
BIT = dict(core=1, p00=2, p10=4, p20=8, p21=16, p11=32, p01=64)
BS = 64; ny, nx = mos.shape[0] // BS, mos.shape[1] // BS
G = np.array(mos[:ny * BS, :nx * BS, 1]).reshape(ny, BS, nx, BS).transpose(0, 2, 1, 3).reshape(ny, nx, -1)
import warnings
with warnings.catch_warnings():
    warnings.simplefilter('ignore'); gb = np.nanmedian(G, axis=2); fr = np.isfinite(G).mean(2)
cb = np.array(cov[BS // 2:ny * BS:BS, BS // 2:nx * BS:BS]) & 127
holds = {}
for k in ('p00', 'p10', 'p20', 'p21', 'p11', 'p01'):
    alone = (cb == BIT[k]) & (fr > 0.9); anyk = ((cb & BIT[k]) > 0) & (fr > 0.9)
    v = gb[alone]
    holds[k] = dict(share_of_its_area_under_the_core_stack=float((anyk & ((cb & 1) > 0)).sum() / max(anyk.sum(), 1)), blocks_where_it_is_the_only_image=int(alone.sum()), share_of_its_area_that_no_other_image_covers=float(alone.sum() / max(anyk.sum(), 1)),
                    green_dn_there=dict(p05=float(np.percentile(v, 5)), median=float(np.median(v)), p95=float(np.percentile(v, 95))) if alone.sum() else None)
# the weights against the mosaic itself: scatter of green in 16 px blocks where one image stands alone (or the core carries it), over the expected noise
nzm = np.load(W('six_noise.npy'), mmap_mode='r'); b16 = 16; n16y, n16x = mos.shape[0] // b16, mos.shape[1] // b16
g16 = np.array(mos[:n16y * b16, :n16x * b16, 1]).reshape(n16y, b16, n16x, b16).transpose(0, 2, 1, 3).reshape(n16y, n16x, -1)
sd16 = g16.std(2); ok16 = np.isfinite(g16).all(2); del g16
ne16 = np.array(nzm[:n16y * b16, :n16x * b16]).reshape(n16y, b16, n16x, b16).mean((1, 3)); c16 = np.array(cov[b16 // 2:n16y * b16:b16, b16 // 2:n16x * b16:b16]) & 127
NOISE_CHECK = dict(what='scatter of green in 16 px blocks of the finished mosaic (25th percentile over blocks, so that stars do not count) over the noise expected from the weights, where one image stands alone (core: where it carries the weight)', measured_over_expected={})
for k in ('core', 'p00', 'p10', 'p20', 'p21', 'p11', 'p01'):
    sel16 = ok16 & ((c16 == BIT[k]) if k != 'core' else (((c16 & 1) > 0) & (ne16 < 8)))
    if sel16.sum() > 50: NOISE_CHECK['measured_over_expected'][k] = round(float(np.percentile(sd16[sel16], 25) / np.median(ne16[sel16])), 2)
del mos, cov, G

# ---- per panel ----
panels = {}
for name in ('p00', 'p10', 'p20', 'p21', 'p11', 'p01'):
    sel = SEL[name]; m6 = L('m6_%s.json' % name); q = {r['stamp']: r for r in sel['quality']}; tr = {o['stamp']: o for o in T4[name]['transforms']}
    used = {u['stamp']: u for u in sel['used']}; rej = {r['stamp']: r for r in sel['rejected']}
    frames = []
    for f in [f for f in m1['frames'] if f['panel'] == name]:
        s = f['stamp']; o = q.get(s, {})
        d = dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], altitude_deg=round(f['alt_deg'], 1), arw_sha256=f['arw_sha256'], used=s in used,
                 corner_level_green_dn=round(f['corner_green'], 1), corner_noise_g1_dn=round(f['corner'][1]['clipped_std'], 1),
                 transparency_in_panel=None if o.get('flux_rel') is None else round(o['flux_rel'], 4), stars_detected=o.get('stars_detected'),
                 half_flux_diameter_arcsec=None if o.get('hfd_arcsec') is None else round(o['hfd_arcsec'], 2), elongation_median=None if o.get('elong_median') is None else round(o['elong_median'], 3),
                 transparency_tilt_per_3000px=None if o.get('tilt') is None else [round(v, 3) for v in o['tilt']])
        t = tr.get(s, {})
        if not t.get('failed') and t: d.update(rotation_deg=round(t['rotation_deg'], 4), shift_at_frame_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], registration=dict(stars_used=t['used'], weighted_rms_px=round(t['wrms_px'], 3)))
        if s in used:
            u = used[s]; d.update(multiplied_by=round(u['scale'], 4), weight=round(u['weight'], 4), passes_the_core_runs_star_shape_limits=u['passes_core_star_limits'], is_the_clearest_frame_background_reference=(s == sel['background_reference']),
                                  hair_centre_sensor_px=m6['hair_centre_sensor_px'].get(s), surface_taken_off_against_the_clearest_frame=m6['surfaces_taken_off'].get(s))
        else: d['rejected_because'] = rej[s]['why']
        frames.append(d)
    mult = PL['photometric_multipliers']['G'][name]; nz = R9[name]['noise_green_per_mosaic_px_core_units']
    cen = S7[name]['centre_offset_arcmin_east_north']; Mk = np.array(PL['affine_to_tangent_plane_arcsec'][name]); w, h = PL['size'][name]; cj = Mk @ np.array([w / 2 - 0.5, h / 2 - 0.5, 1.0]) / 60
    nu = len(used)
    panels[name] = dict(
        grid_position=GRIDNAME[name], planned_offset_arcmin_east_north=list(PLAN[name]), found_at_arcmin_east_north=[round(float(cj[0]), 2), round(float(cj[1]), 2)], pointing_error_arcmin=round(float(np.hypot(cj[0] - PLAN[name][0], cj[1] - PLAN[name][1])), 2),
        frames_found=len(frames), frames_used=nu, exposure_taken_s=len(frames) * EXPOSURE_S, exposure_used_s=nu * EXPOSURE_S,
        rejected=dict(cloud=sum('cloud:' in r['why'] and 'uneven' not in r['why'] for r in sel['rejected']), uneven_thin_cloud=sum('uneven' in r['why'] for r in sel['rejected']), other=sum('cloud' not in r['why'] for r in sel['rejected'])),
        used_only_because_star_shape_limits_were_loosened=[s for s, u in used.items() if not u['passes_core_star_limits']],
        transparency=dict(of_used_frames_relative_to_the_panels_clearest=[round(u['transparency'], 3) for u in sel['used']],
                          of_the_panels_clearest_frames_against_the_core_runs_clear_sky=round((CORE_EXPOSURE_S / EXPOSURE_S) / mult, 3),
                          of_used_frames_against_the_core_runs_clear_sky=[round(u['transparency'] * (CORE_EXPOSURE_S / EXPOSURE_S) / mult, 3) for u in sel['used']]),
        photometric_multiplier=dict(green_applied_to_all_colours=round(mult, 4), sigma=round(PL['photometric_multipliers']['G_sigma'][name], 4), red_check=round(PL['photometric_multipliers']['R'][name], 4), blue_check=round(PL['photometric_multipliers']['B'][name], 4)),
        sky=dict(corner_level_green_of_clearest_frame_dn_per_30s=round(s1[sel['background_reference']]['corner_green'], 1), corner_level_green_range_of_used_frames_dn_per_30s=[round(min(u['corner_green'] for u in sel['used']), 1), round(max(u['corner_green'] for u in sel['used']), 1)],
                 corner_level_green_range_of_all_frames_dn_per_30s=[round(min(f['corner_level_green_dn'] for f in frames), 1), round(max(f['corner_level_green_dn'] for f in frames), 1)],
                 core_run_clear_level_dn_per_20s=core_rec['what_the_bright_sky_frames_are']['clear_level_green_dn'],
                 background_taken_off_green_core_units_dn=round(BG['G'][MODEL]['parameters'][name]['terms'][0], 1), note='the last number is the panel\'s sky + cloud glow above the core stack\'s zero at the panel centre, in the core\'s units (DN per 20 s under its clear sky); the core run\'s own sky was 101 DN in its corner'),
        noise=dict(stack_per_half_grid_px_panel_units_dn=m6['noise_of_stack_dn_per_half_grid_px'], green_per_mosaic_px_core_units_dn=dict(median=round(nz['median'], 1), best=round(nz['best'], 1)),
                   times_the_core_stacks=round(nz['median'] / core_noise, 1), depth_as_fraction_of_the_core_stack=round((core_noise / nz['median']) ** 2, 4),
                   equivalent_clear_dark_sky_exposure_s=round((core_noise / nz['median']) ** 2 * core_clear_equiv_s, 0),
                   note='depth = inverse variance per pixel against the core stack (38 x 20 s, worth %d s of clear dark sky)' % core_clear_equiv_s),
        background_fitted=dict(model=MODEL, **{c: BG[c][MODEL]['parameters'][name] for c in 'RGB'}),
        pixels=dict(clean_fraction=round(m6['flags']['clean'] / (H2 * W2), 4), from_dust_divided_combine_fraction=round(m6['flags']['dust_divided'] / (H2 * W2), 4), no_data_fraction=round(m6['flags']['no_data'] / (H2 * W2), 4), no_data_because_of_the_hair_fraction=round(m6['flags']['hair_no_data'] / (H2 * W2), 4)),
        hair_circle_radius_sensor_px=m6['hair_circle_radius_sensor_px'], area_in_mosaic_sq_arcmin=round(R9[name]['area_sq_arcmin'], 0), what_it_holds=holds[name],
        registration_reference=m6['registration_reference'], clearest_frame=m6['background_reference'], frames=frames)

P = panels
def pv(k, txt): P[k]['verdict'] = txt
h = holds
pv('p01', 'THE BEST PANEL, ON THE EMPTIEST SKY: 8 of 11 frames, 240 s, its clear frames at %.0f%% of the core run\'s transparency, %.1f times the core\'s noise. It lies off the south-east flank, about 22 arcmin from the major axis, where the galaxy should be a few DN at most. The mosaic has %.0f to %.0f DN there (median %.0f): most of that grey plateau is background that the panel\'s plane did not take, not galaxy (with planes for every panel, model B, the same panel comes out 11 DN lower, and partly below zero). What it shows for certain: the stars, the edge of the disc along its north-west side, and that nothing with structure is out there. It earns its place as the anchor of the east end, not for what it holds.' % (100 * P['p01']['transparency']['of_the_panels_clearest_frames_against_the_core_runs_clear_sky'], P['p01']['noise']['times_the_core_stacks'], h['p01']['green_dn_there']['p05'], h['p01']['green_dn_there']['p95'], h['p01']['green_dn_there']['median']))
pv('p00', 'EARNS ITS PLACE: 5 of 11 frames, 150 s, %.1f times the core\'s noise. It carries the disc north-east along the major axis (green %.0f to %.0f DN alone) and the continuation of the dust lanes out of the core field. Its far end rests on an extrapolated plane: the lanes are real, the level of the glow at the far north-east is not to be read.' % (P['p00']['noise']['times_the_core_stacks'], h['p00']['green_dn_there']['p05'], h['p00']['green_dn_there']['p95']))
pv('p20', 'EARNS ITS PLACE, thinly: 2 of 11 frames, 60 s (one of them trailed), %.1f times the core\'s noise; nine frames lost to cloud. The dust lane running south-west out of the core field and the disc beyond are there as broad shapes under heavy grain; nothing smaller than about half an arcminute.' % P['p20']['noise']['times_the_core_stacks'])
pv('p21', 'EARNS ITS PLACE: 3 of 11 frames, 90 s, %.1f times the core\'s noise. It holds NGC 206 (the star cloud in the south-west arm, faint but there), the south-west disc, and M32 near its edge, where it is the better of the two panels that have it.' % P['p21']['noise']['times_the_core_stacks'])
pv('p10', 'ADDS ALMOST NOTHING: 3 of 11 frames, 90 s, %.1f times the core\'s noise, and %.0f%% of it lies under the deep core stack, where it carries about 3%% of the weight. What it adds: a strip 4 arcmin wide beyond the core\'s north-west edge (sky), and clean sky under the core\'s own hair and dust shadows, which are now filled from it. It did serve to tie the other panels to the core.' % (P['p10']['noise']['times_the_core_stacks'], 100 * h['p10']['share_of_its_area_under_the_core_stack']))
pv('p11', 'HOLDS LITTLE, AND IT IS THE ONE THAT MATTERED: 2 of 11 frames, 60 s, both through cloud (stars at %.0f%% and %.0f%% of the core run\'s), %.1f times the core\'s noise = %.1f%% of its depth. It is the only cover of the south-east side of the bulge. M32 and the smooth fall of the bulge are recognisable; no dust lane or arm on that side can be trusted from it. Its background needed a second-order surface, not a plane, and near the nucleus it carries the bulge\'s light scattered by the cloud.' % (
    100 * P['p11']['transparency']['of_used_frames_against_the_core_runs_clear_sky'][0], 100 * P['p11']['transparency']['of_used_frames_against_the_core_runs_clear_sky'][1], P['p11']['noise']['times_the_core_stacks'], 100 * P['p11']['noise']['depth_as_fraction_of_the_core_stack']))

gC = BG['G'][MODEL]; gB = BG['G']['B_constants_and_planes']; gA = BG['G']['A_constants']
ov = {}
for key in gC['overlaps']:
    a_, b_ = key.split('-')
    ov[key] = dict(blocks=gC['overlaps'][key]['blocks'],
                   astrometry=dict(shared_stars=PL['overlaps_after_joint_solve'].get(key, {}).get('kept'), rms_arcsec_plate_solutions_alone=PL['overlaps_plate_solutions_alone'].get(key, {}).get('rms_arcsec'), rms_arcsec_after_joint_solve=PL['overlaps_after_joint_solve'].get(key, {}).get('rms_arcsec'),
                                   mean_offset_arcsec_after_joint_solve=PL['overlaps_after_joint_solve'].get(key, {}).get('mean_offset_arcsec')),
                   photometry_green=PL['photometric_pairs']['G'].get(key),
                   background_green_dn=dict(raw_median_difference=gA['overlaps'][key]['raw_median_difference'], rms_after_constants_only=gA['overlaps'][key]['rms'], rms_after_planes=gB['overlaps'][key]['rms'], rms_after_model_used=gC['overlaps'][key]['rms'],
                                            p05_p95_after_model_used=[gC['overlaps'][key]['p05'], gC['overlaps'][key]['p95']], rms_if_this_overlap_were_fitted_alone_with_its_own_plane=gB['each_overlap_fitted_alone_rms'][key],
                                            near_the_nucleus_blocks_left_out=gC['overlaps'][key]['blocks_near_nucleus'], near_the_nucleus_median=gC['overlaps'][key]['near_nucleus_median'], near_the_nucleus_p05_p95=gC['overlaps'][key]['near_nucleus_p05_p95']),
                   background_red_rms_after_model_used=BG['R'][MODEL]['overlaps'][key]['rms'], background_blue_rms_after_model_used=BG['B'][MODEL]['overlaps'][key]['rms'])

n_found = sum(p['frames_found'] for p in P.values()); n_used = sum(p['frames_used'] for p in P.values())
out_files = sorted(glob.glob(os.path.join(OUT, 'm31-mosaic*')))
def sha(path):
    hsh = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''): hsh.update(chunk)
    return hsh.hexdigest()

recipe = dict(
    what='M31, six-panel mosaic of the central 1.3 square degrees joined to the deep core stack: %d x 30 s at ISO 3200 (%d of %d frames; the rest lost to cloud) under a 41%% Moon and passing thin cloud, plus the core stack of the same night (38 x 20 s), Sony a6000 on a Celestron 8SE at f/10, from RAW colour planes' % (n_used, n_used, n_found),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw=list(rawpy.libraw_version), tifffile=tifffile.__version__, pillow=PIL.__version__,
               astrometry_net='solve-field and image2xy (Homebrew), index files in ~/.observatory/astrometry: used only to say where each image lies on the sky',
               note='deterministic array arithmetic only; nothing generative or learned. Every pixel of every output is a weighted average of measured pixels (resampled with Lanczos-4, divided by measured flats, minus fitted constants, planes and one second-order surface); where there is no data the pictures are black and the linear file is 0 with weight 0.'),
    the_short_answer=dict(
        main_picture='m31-mosaic.png / .jpg: all six panels and the core stack. It is the main picture because the four OUTER panels turned out to be the better ones; the two centre panels are the weak ones (one is redundant with the core, one was taken through cloud).',
        extra_picture='m31-mosaic-centre.png / .jpg: the core stack and the two centre panels only.',
        what_is_real=['the bulge, the nucleus and the dust lanes north-west of it: these are the deep core stack, unchanged (it carries 95% of the weight wherever it has data)',
                      'the disc as a band from north-east (upper left) to south-west (lower right) across the whole mosaic, and the dark lanes that run on out of the core field in both directions (panels (0,0) and (2,0))',
                      'M32, south of the nucleus (panels (1,1) and (2,1))', 'NGC 206, the star cloud in the south-west arm, faint (panel (2,1))',
                      'the galaxy ending on both flanks: along the north-west edge and in the south-east the mosaic comes down to within about 3 DN of its darkest part',
                      'the stars, everywhere'],
        what_is_not='see do_not_trust. Above all: the even grey over panel (0,1) and the outer ends of the other outer panels is mostly background, not disc. In one line: outside the core field every smooth brightness is good to about +-3 DN (green) where two images overlap and +-5 to 10 DN at the far ends of the outer panels, against a disc of 5 to 30 DN there; the outer panels are shown without colour because their zero per colour is not known; panel (1,1) is 9 times noisier than the core.'),
    source=dict(folder=STILLS, window_utc=[T0, T1], stills_in_window=len(m1['frames']) + len(m1['left_out']), frames_at_30s_iso3200=len(m1['frames']), in_the_six_panels=n_found, check_frames_on_the_nucleus=2, frames_used=n_used, frames_rejected=n_found - n_used,
                rejected_for_cloud=sum(p['rejected']['cloud'] for p in P.values()), rejected_for_uneven_thin_cloud=sum(p['rejected']['uneven_thin_cloud'] for p in P.values()), rejected_for_other_reasons=sum(p['rejected']['other'] for p in P.values()),
                exposure_taken_s=n_found * EXPOSURE_S, exposure_used_s=n_used * EXPOSURE_S,
                left_out=[dict(file=f['name'], exposure_s=f['exposure_s'], iso=f['iso'], why='2 s ISO 6400 finder frame at a panel change') for f in m1['left_out']],
                grouping='by the mount\'s pointing in the sidecars (a new group when it moves by more than 0.1 degree or after a gap of 4 minutes); each group named by its declination offset from the nucleus, which matched the plan to 0.1 arcmin for all six. The mount\'s RA in the sidecars is 0.11 degree off between finder and long frames and was not used.',
                originals='read in place, not modified',
                core_stack=dict(file=os.environ.get('M31_CORE_TIF', os.path.join(CORE_DIR, 'm31-core-cloudflat-linear.tif')), what=('the core run\'s main stack re-made with the master flat (its version F), 38 x 20 s, 0730 to 0845 UTC, before the Moon; its recipe is m31-core-recipe.json beside it' if os.environ.get('M31_CORE_TIF') else 'version C of the core run (whole smooth cloud-glow flat removed), 38 x 20 s, 0730 to 0845 UTC, before the Moon; its recipe is m31-core-recipe.json beside it'), also_used=['m31-core-coverage.tif', 'm31-core-sensor-dust-map.png', 'm31-core-recipe.json', 'work files flat2d.npy, dustmask.npy, dustratio.npy, hotmap.npy, step1.json, vignette.json']),
                check_frames='the two 30 s frames on the nucleus at 0915 (the plan said one; there are two) were stacked like a panel and used only as a test (centre_check), not in the mosaic'),
    panels=P,
    overlaps=ov,
    steps=[
        dict(step='read', detail='as the core run: rawpy raw_image_visible (6024 x 4024, RGGB), black level 512 subtracted, four colour planes kept apart at 3012 x 2012, no demosaic.'),
        dict(step='hot pixels', detail='the core run\'s rule, map rebuilt for 30 s frames: per-plane median without registration of the 36 frames with the lowest sky (six different pointings, so no star survives), pixel hot if above the 5x5 median by more than max(6 sigma, 25% of the level) and above its highest neighbour by half that; single-frame spikes above the 3x3 median by 8 sigma + 50%. Both replaced by the 3x3 median of the plane.',
             fixed_hot_pixels={h_['plane']: h_['fixed_hot'] for h_ in m2['hot']}, fraction_of_plane={h_['plane']: round(h_['frac'], 5) for h_ in m2['hot']}, also_in_the_core_runs_map={h_['plane']: h_['also_in_core_map'] for h_ in m2['hot']}),
        dict(step='stars, registration inside a panel', detail='the core run\'s detector and fit (rotation + shift, scale held at 1), each panel against its frame with the most stars, frames walked outward in time. Weighted rms 0.38 to 0.61 px for the frames used. Between the used frames of a panel the field moved 23 to 86 px and turned 0.02 to 0.21 degree.'),
        dict(step='transparency and selection', detail='per frame, the median over 41 to 68 stars of flux / that star\'s flux in the panel\'s clear frames. Used if >= 0.80, even across the field (under 10% per 3000 px), registration rms <= 1 px: the core run\'s limits. The core run\'s star-shape limits were LOOSENED (width <= 1.30 x the clear median instead of 1.10, elongation <= 1.60 instead of 1.40) because the mosaic is shown at 4 times the core\'s pixel and a frame is a third to a half of a panel; three frames are in only because of that and are flagged. Weights (transparency / noise)^2 as in the core run.',
             limits=SEL['p00']['limits'], frames_used_only_because_of_the_looser_star_limits={k: P[k]['used_only_because_star_shape_limits_were_loosened'] for k in P if P[k]['used_only_because_star_shape_limits_were_loosened']},
             note='"transparency" inside a panel is relative to the panel\'s clearest frames. Those were themselves under thin cloud in five of six panels: against the core run\'s clear sky (from the stars shared with the core stack, step "photometric scale") the clearest frames were at 0.59 to 0.91.'),
        dict(step='dust and hair', detail='the core run\'s dust map was checked against this hour: the 19 most clouded frames (transparency under 0.33), each divided by the smooth flat and by its own smooth light, median in sensor coordinates. The dust rings are where they were. THE HAIR MOVED: 140 px from its place in the core run, and a further 175 px and 55 degrees during the mosaic hour (centre from sensor (3783, 148) at 0918 to (3701, 303) at 1022). So: mask = the core run\'s mask OR this hour\'s (same thresholds), 7.8% of the sensor, left out of the average as in the core run; the hair is found in every used frame from the frame itself and a circle of 220 px radius round it is left out. And every frame is divided by a small-scale flat (the noise-weighted mean of the two dust-ratio maps), because under a moonlit sky faint rings below the mask threshold are 4 to 7 DN deep and the field does not move enough inside a panel to smear them.',
             numbers=DUST['small_scale_flat'], frames_for_this_hours_map=DUST['frames']),
        dict(step='flat field', detail='each colour plane divided by the core run\'s smooth cloud-glow flat of that plane (flat2d.npy, its version C: radial profile, tilt, edge shading) and by the small-scale flat above. No flat frames exist yet.'),
        dict(step='stack per panel', detail='on the half grid of the panel\'s reference frame (3012 x 2012, 0.776 arcsec/px, one sample per plane per pixel, Lanczos-4). Frames multiplied by 1 / transparency. DEPARTURE FROM THE CORE RUN: instead of one constant per frame, a second-order surface (6 numbers per frame and plane) fitted to (frame - the panel\'s clearest frame) is taken off, because between two frames of one panel the moonlit cloud glow differs by slopes of up to 42 DN and bows of up to 26 DN across half the frame (used frames; more in the rejected ones). The galaxy and sky cancel in that difference; nothing is fitted to the sky of any single frame. Every frame of a panel then carries the background of the panel\'s clearest frame. Combine as the core run (3-sigma about median then mean, weighted mean); with two samples a pair test instead (differ by more than 5 sigma: keep the lower). Dust-masked samples left out; where fewer than half the frames are clean, the combine with them left in (they are divided by the small-scale flat) is used and flagged; where no frame is clear of the hair there is no data.',
             what_the_surfaces_took_off='see panels.<name>.frames[].surface_taken_off_against_the_clearest_frame: slope and second-order terms in DN across half the frame, and the rms of the difference after a constant, after a plane, after the surface (the block noise alone is about 2.2 DN)'),
        dict(step='placing on the sky', detail='each panel stack and the core stack (2 x 2 block mean, 0.776 arcsec/px) plate-solved with astrometry.net; an affine map from pixels to the tangent plane about the nucleus (RA %.4f, Dec %+.4f, J2000) fitted to the matched catalogue stars with this pipeline\'s own centroids; then all seven maps solved again together with the stars the images share in their overlaps (catalogue stars sigma 0.5 arcsec, shared stars 0.2 arcsec, 3-sigma rejection).' % (NUC_RA, NUC_DEC),
             catalogue_stars_and_rms_arcsec={k: dict(stars=PL['catalogue_after_joint_solve'][k]['stars'], rms=round(PL['catalogue_after_joint_solve'][k]['rms_arcsec'], 2)) for k in PL['images']},
             shared_stars_rms_arcsec_after_joint_solve={k: round(v['rms_arcsec'], 2) for k, v in PL['overlaps_after_joint_solve'].items()},
             shared_stars_rms_arcsec_plate_solutions_alone={k: round(v['rms_arcsec'], 2) for k, v in PL['overlaps_plate_solutions_alone'].items()},
             reading='shared stars agree to 0.35 to 0.56 arcsec rms per star (half to three quarters of a mosaic pixel; mostly centroid noise in 2 and 3 frame stacks), mean offsets under 0.2 arcsec in every overlap. With the plate solutions alone it was 0.38 to 0.84 arcsec. The mount put the panels 0.5 to 3.1 arcmin from the plan.',
             frame_on_the_sky={k: dict(x_6000px_arcmin_east_north=S7[k]['x_axis_arcmin_per_6000_sensor_px_east_north'], y_4000px_arcmin_east_north=S7[k]['y_axis_arcmin_per_4000_sensor_px_east_north'], centre_arcmin_east_north=S7[k]['centre_offset_arcmin_east_north']) for k in PL['images']},
             affine_pixels_to_tangent_plane_arcsec=PL['affine_to_tangent_plane_arcsec']),
        dict(step='photometric scale', detail='aperture fluxes (28 px sensor radius) of the stars shared between images, in R, G, B; one multiplier per image, the core held at 1, solved over all overlaps at once in the logarithm, each star weighted by its signal-to-noise. The green multiplier is applied to all three colours of a panel; red and blue are checks.',
             multipliers=PL['photometric_multipliers'], star_pairs_used=dict(R=PL['photometric_multipliers']['R_stars'], G=PL['photometric_multipliers']['G_stars'], B=PL['photometric_multipliers']['B_stars']),
             reading='formal errors 0.5 to 1.2%; what is left per overlap after the multipliers is 0.94 to 1.04 (see overlaps.<pair>.photometry_green), so a panel\'s scale is good to about 3%. The red multipliers are 0.97 to 1.01 of the green ones, the blue 0.99 to 1.04. Transparency of each panel\'s clearest frames against the core run\'s clear sky = (20 / 30) / multiplier: 0.59 to 0.91.'),
        dict(step='one grid', detail='tangent plane about the nucleus, north up, east left, %.3f arcsec/px, %d x %d px (%.1f x %.1f arcmin). Each image resampled once more (affine, Lanczos-4, about 1:1). Weight per image = feather x inverse variance of green x quality, the same for the three colours.' % (PL['grid']['pixel_scale_arcsec'], PL['grid']['width'], PL['grid']['height'], PL['grid']['width'] * PL['grid']['pixel_scale_arcsec'] / 60, PL['grid']['height'] * PL['grid']['pixel_scale_arcsec'] / 60),
             grid=PL['grid'], feather='panels: smoothstep over 200 px from any edge or hole, and the last 39 px left out; core: (distance / 300 px)^4 from its outer edge, 60 px smoothstep round its own masked shadows',
             core_own_shadows='the hair and four dust smudges still in the core stack (its dust map, transmission under 0.985, grown 20 px) are given no weight; the panels fill them', noise_green_per_mosaic_px_core_units_dn={k: R9[k]['noise_green_per_mosaic_px_core_units'] for k in PL['images']},
             noise_check=NOISE_CHECK),
        dict(step='background', detail='ONE additive constant and ONE plane per panel and colour, solved over all overlaps at once by least squares (64 px block medians of the differences between every pair of images; the core stack fixed at zero; weights 1 / (noise^2 + 1 DN^2), weighted down where the galaxy is bright; 3-sigma rejection). The planes ARE demanded: with constants only the overlaps disagree by %.1f DN rms in green, with planes by %.2f. Panel (1,1) alone gets three second-order terms as well, and that too is demanded: with a plane its six overlaps disagree by 2.5 to 4.0 DN and drag its neighbours\' planes (the constant of (0,1) moves by 11 DN); with the second-order terms by 1.8 to 2.5, like the others, and blocks that were NOT in the fit (near the nucleus) are then predicted three times better (median difference against the core %.1f DN instead of %.1f). A second-order surface for every panel fits only a little better (1.5 against 1.7 DN) and runs away at the outer ends, where nothing holds it (by 40 to 70 DN), so it is not used. Nothing is fitted to any panel by itself and no free-form surface is fitted anywhere.' % (
                 gA['rms_all_blocks_away_from_nucleus'], gB['rms_all_blocks_away_from_nucleus'], gC['overlaps']['core-p11']['near_nucleus_median'], gB['overlaps']['core-p11']['near_nucleus_median']),
             model_used=MODEL, surface=BG['surface'], panel_centres_mosaic_px=BG['panel_centres_mosaic_px'], near_nucleus_left_out_arcmin=BG['near_nucleus_arcmin'],
             rms_of_block_differences_all_overlaps_dn={c: {m: round(BG[c][m]['rms_all_blocks_away_from_nucleus'], 2) for m in ('A_constants', 'B_constants_and_planes', 'C_planes_and_second_order_for_p11', 'D_as_C_with_p11_tied_to_the_core_near_the_nucleus')} for c in 'RGB'},
             parameters={c: BG[c][MODEL]['parameters'] for c in 'RGB'}, parameters_if_planes_only={c: BG[c]['B_constants_and_planes']['parameters'] for c in 'RGB'},
             bulge_light_scattered_by_cloud='blocks within 13 arcmin of the nucleus are kept out of the equations: there the centre panels are brighter than the core stack by a smooth halo centred on the nucleus, the bulge\'s own light scattered in the thin cloud the panels were taken through. Panel (1,0): about +19 DN green at 1 to 2 arcmin, +7 at 4 to 6, gone by 8. Panel (1,1) after its second-order surface: about +5 DN median over the zone. The check frames show the same (+17 DN inside 1 arcmin).',
             absolute_zero='UNKNOWN. The constants tie the panels to the core stack\'s zero, which is the darkest part of the core field, not the sky.'),
        dict(step='test on a known field', detail='the two 0915 check frames on the nucleus, stacked like a panel (2 x 30 s, transparency %.2f), against the core stack: after one constant the 64 px blocks disagree by %.1f DN rms in green, after a constant and a plane by %.1f (5 to 95%%: %+.1f to %+.1f). That is what one constant and one plane can and cannot do for a two-frame panel under this sky, measured where the answer is known.' % (
                 CHK['transparency_against_core'], CHK['colours']['G']['rms_after_constant_dn'], CHK['colours']['G']['rms_after_plane_dn'], *CHK['colours']['G']['p05_p95_after_plane']), numbers=CHK),
        dict(step='combine and zero', detail='weighted mean of (image - its background). The core carries a median %.0f%% of the weight where it has data. Then one number, the same for the three colours, is taken off so that the darkest well-covered 2%% of the mosaic sits at zero in green.' % (100 * M11['six']['core_share_of_weight_where_it_has_data']['median']),
             six_panel=M11['six'], centre_only=M11['centre'],
             reading='the darkest part of the whole mosaic turned out to be the core field\'s own north-west corner (17 arcmin west, 9 north of the nucleus, 20 arcmin out along the minor axis), %.1f DN above the core stack\'s zero; the strip of panel (1,0) beyond it is at the same level. With the model used, nothing in 1.3 square degrees comes out darker, which suggests the core stack\'s zero is within a few DN of the sky. It rests on the panels\' fitted backgrounds (under the planes-only model parts of (0,1) and (1,1) come out 11 DN BELOW it, which cannot be) and is not a measurement of the sky.' % M11['six']['zero_taken_off_all_colours_dn']),
        dict(step='pictures', detail='2 x 2 block mean (1.552 arcsec/px); grain evened by a Gaussian whose width follows the expected noise (none in the core, up to 3 px in the noisiest panel); the core run\'s arcsinh curve; colour from a copy blurred by 4 px with a colour pedestal of 25 DN where the core carries the weight and 300 DN where only panels do (so the panels are neutral grey except for stars and M32).',
             stretch=M12['stretch'], colour_pedestal_dn=M12['colour_pedestal'], grain=M12['grain'],
             why_this_scale='1.55 arcsec/px still samples the stars (4.1 arcsec in the core, 2.6 px) and halves the grain of the working grid. The panels would bear a coarser scale (2.5 to 10 times the core\'s noise), the core a finer one (its own pictures are at 0.776): this is the scale both can share. The linear file keeps 0.776.',
             differs_from_the_core_pictures='pedestal 10 DN instead of 4 and colour pedestal 25 instead of 4: the faint end is lifted less steeply and coloured less than in m31-core-cloudflat.png, on purpose, so that the noisy panels are not peppered with black and the faintest glow is not tinted by a zero that is only known to a few DN.')],
    outputs=dict(M12['outputs'], files={os.path.basename(f): dict(bytes=os.path.getsize(f), sha256=sha(f)) for f in out_files if not f.endswith('recipe.json')},
                 jpg='quality 92, 4:4:4, no metadata', png='8-bit RGB, no metadata', marks='nothing is drawn on any picture; the diagnostic is made of flat tones and grey levels only'),
    do_not_trust=[
        'The zero. One number for the whole mosaic, set where the mosaic is darkest; it leans on the panels\' fitted planes. How far the galaxy really reaches cannot be read off.',
        'Any smooth brightness outside the core field. Where two images overlap they agree to 1 to 2.5 DN rms (green) after the fit, 5 to 95% within +-3 to 4 DN; the same fit on the check frames, where the truth is known, left +-6 DN. Beyond the overlaps a panel\'s background is its plane carried outward: the far ends of the four outer panels (more than about 25 arcmin from the nucleus along the long axis of the mosaic) are held only by strips 2.4 to 8 arcmin wide at their inner ends and can be off by 5 to 10 DN. The disc there is 5 to 30 DN.',
        'The grey plateau over panel (0,1) (east end, south-east flank): 3 to 18 DN, median 11, where the galaxy should be a few DN at most. It is what the fitted plane left. The two background models that fit the overlaps (planes for all; planes plus a second-order surface for (1,1), the one used) differ by 11 DN on the level of this panel and by 4 to 5 DN on (0,0) and (2,0): that is the honest uncertainty of the outer panels\' level, and up to 10 DN of the glow in their outer halves may be background too.',
        'Panel (1,1), south-east of the nucleus, most of all: 2 frames through cloud, 9 times the core\'s noise, a second-order background whose middle is constrained by nothing clean (its only overlap there is the bulge, with the cloud\'s scattered light in it). Within about 10 arcmin of the nucleus on that side the smooth light is too bright by an unknown 5 to 20 DN.',
        'The colour of anything outside the core field. The red zero of the panels is off by up to 17 DN in places (south-east side) and blue by up to 8; the pictures show the panels in neutral grey for that reason. The linear file has the colours as they came: do not read them.',
        'The faintest colour inside the core field: unchanged from the core recipe (1 DN of red is 2.75 DN after white balance).',
        'Four black discs: no data, the hair on the sensor. Three on the north-west edge (panels (0,0), (1,0), (2,0)), one half-disc inside panel (0,1) at its edge to (0,0). The hair moved all hour; its circle is cut out of every frame.',
        'Small round dark or light smudges 20 to 60 arcsec across in the panels: sensor dust divided by a map that is good to about 0.3% of a 250 to 500 DN sky (1 to 2 DN), on parts of the sensor where no clean frame existed (2 to 8% of each panel; bit 128 of the coverage file where nothing else covers).',
        'The change of grain at the core field\'s edge and between panels: the noise goes from 5.8 DN per 0.776 arcsec pixel in the core to 15 (panel (0,1)), 24 to 33 (four panels) and 55 ((1,1)). In the pictures the noisy parts are smoothed to match, so their stars are wider (up to 12 arcsec in (1,1)) and nothing finer than that is there.',
        'Star shapes and brightness in panel (2,0) and (1,0): one of two, and one of three, frames is trailed (elongation 1.5).',
        'Photometry between panels to better than 3%: the multipliers come from 4 to 173 stars per overlap, some of them in the corners where the flat is least sure.',
        'Everything the core recipe lists under do_not_trust still holds inside the core field, except its hair and dust smudges, which are replaced here by panel data.'],
    what_the_outer_panels_are_worth=dict(
        in_numbers={k: dict(frames='%d of %d' % (P[k]['frames_used'], P[k]['frames_found']), exposure_s=P[k]['exposure_used_s'], transparency_against_core_clear_sky=P[k]['transparency']['of_the_panels_clearest_frames_against_the_core_runs_clear_sky'],
                            noise_times_core=P[k]['noise']['times_the_core_stacks'], depth_percent_of_core=round(100 * P[k]['noise']['depth_as_fraction_of_the_core_stack'], 1), equivalent_clear_dark_sky_s=P[k]['noise']['equivalent_clear_dark_sky_exposure_s']) for k in P},
        verdicts={GRIDNAME[k]: P[k]['verdict'] for k in P},
        overall='The hour bought %d s of usable exposure out of %d s taken; cloud took %d of %d frames. In depth each panel holds between 1%% and 14%% of what the core stack holds per pixel. As a map of where the galaxy is, where its lanes run and where M32 and NGC 206 sit, the mosaic is real. As a measurement of the outer disc\'s brightness it is not.' % (n_used * EXPOSURE_S, n_found * EXPOSURE_S, n_found - n_used, n_found)),
    dawn_flats=dict(
        would_they_change_the_result='Partly. YES for: (1) the dust: every shadow and faint ring divided out properly on the whole sensor, instead of a map built from clouded frames (the 4 to 8% of each panel now flagged as dust-divided, and the smudges, go away); (2) the smooth flat: the cloud-glow flat is unconfirmed at the 1 to 3% level, which under a 250 to 500 DN moonlit sky is 3 to 15 DN across a frame and is part of what the planes are absorbing now, differently per colour: the red and blue zeros of the panels should come much closer, which may give the panels their colour back; (3) the core stack itself (its version C rests on the same cloud-glow flat). NO for: the depth (2 to 8 frames per panel is what there is), the uneven cloud glow in each panel\'s clearest frame (still needs a constant and a plane per panel, and the second-order surface for (1,1)), the scattered bulge light near the nucleus, the extrapolated far ends of the outer panels, the hair (it will sit somewhere else again in the flats: its place there must be masked, and each frame\'s own hair circle stays cut out).',
        how_to_rerun=['1. Make a master flat: black-subtracted median of the dawn flat frames per colour plane (R, G1, G2, B; 3012 x 2012 each), each plane divided by its value at the sensor centre; save as a .npy of shape (4, 2012, 3012). If the hair shows in it, save a boolean mask of its place there, shape (2012, 3012).',
                      '2. Re-make the core stack with that flat (the core run\'s scripts: its step 8 version C reads flat2d.npy) so that the mosaic is tied to a core made the same way; point M31_CORE_TIF at the new linear file (same grid as m31-core-cloudflat-linear.tif).',
                      '3. PY=/path/to/python M31M_WORK=/some/scratch/folder M31M_MASTER_FLAT=/path/master.npy [M31M_DUST_MASK=/path/hair.npy] [M31_CORE_TIF=/path/core.tif] sh scripts/run_all.sh    (all steps, about 12 minutes, 15 GB of scratch; the caches of this run were deleted). With M31M_MASTER_FLAT set, step 6 divides by it alone and leaves nothing out for dust. The deliverables in this folder are overwritten: move these aside first if both are wanted.',
                      '4. Read step 10\'s table again before believing the result: if the planes shrink and red and blue agree with green, the colour pedestal for the panels in m12_deliver.py (300 DN) can come down.']),
    what_would_help_most=['A clear, moonless hour: the same plan under the core run\'s sky would be 11 frames per panel at transparency 1 and a darker sky, about 3 times the depth of the best panel here and about 30 times that of the worst.',
                          'More overlap, or a second pass offset by half a panel: the outer panels are tied to the rest by strips 2.4 to 8 arcmin wide at one end, which is what leaves their far ends free. A third row of short frames along both long edges, or the same six panels shifted by half a frame, would pin every plane.',
                          'A few frames of empty sky a degree off the galaxy between panels, for the zero.',
                          'The dawn flats (above).',
                          'Getting the hair off the sensor.'],
    calibration_kept='calibration-from-core-run/: copies of the six work files of the core run that this pipeline reads (flat2d.npy the smooth cloud-glow flat per colour plane, dustmask.npy, dustratio.npy, hotmap.npy, step1.json, vignette.json), kept because the core run left them in a temporary folder; with them and the RAWs the mosaic can be made again from nothing.',
    scripts='scripts/ beside this file, in order (sh scripts/run_all.sh; its header lists the settings): mcommon.py, m1_frames.py, m2_hot.py, m3_stars.py, m4_register.py, m5_quality_select.py, m5b_dustcheck.py, m6_stack.py, m7_solve.py, m8_place.py, m9_resample.py, m10_background.py, m10b_centre_check.py, m11_combine.py, m12_deliver.py, m13_recipe.py; fitsmin.py, mrender.py, render.py (the core run\'s) are helpers; x_*.py are the explorations that led to the choices above (frame differences inside a panel, background models) and are not part of the run. Adapted from ../scripts (the core run).')

os.makedirs(OUT, exist_ok=True)
json.dump(recipe, open(os.path.join(OUT, 'm31-mosaic-recipe.json'), 'w'), indent=1)
cal = os.path.join(OUT, 'calibration-from-core-run'); os.makedirs(cal, exist_ok=True)
if os.path.abspath(CORE_WORK) != os.path.abspath(cal):
    for f in ('flat2d.npy', 'dustmask.npy', 'dustratio.npy', 'hotmap.npy', 'step1.json', 'vignette.json'): shutil.copy2(CW(f), cal)
dst = os.path.join(OUT, 'scripts'); os.makedirs(dst, exist_ok=True)
for f in sorted(glob.glob(os.path.join(SCR, '*.py')) + glob.glob(os.path.join(SCR, '*.sh'))): shutil.copy2(f, dst)
print('recipe written:', os.path.join(OUT, 'm31-mosaic-recipe.json'), os.path.getsize(os.path.join(OUT, 'm31-mosaic-recipe.json')), 'bytes; scripts copied:', len(os.listdir(dst)))
print(json.dumps(recipe['what_the_outer_panels_are_worth'], indent=1))
