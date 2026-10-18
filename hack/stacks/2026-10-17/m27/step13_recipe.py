"""Step 13: recipe.json, every number that shaped the picture, gathered from the steps' own JSON (work/) and written to
final/recipe.json beside the picture (and ./recipe.json). Also checks final/m27.jpg carries no EXIF / XMP / comment."""
import datetime, json, os, shutil, subprocess
import numpy as np
from common import *

j = jload
s1, s3, s4, s5, s6, s7, s7a = j('step1.json'), j('step3_transforms.json'), j('step4_quality.json'), j('step5_select.json'), j('step6_solve_ref.json'), j('step7_flat.json'), j('step7a_flats.json')
s8, s8c, s9, s9b, s10, s12 = j('step8_stack.json'), j('step8_coadd.json'), j('step9_solve.json'), j('step9b_colour.json'), j('step10_deliver.json'), j('step12_halves.json')
fin = json.load(open(os.path.join(FINAL, NAME + '.json'))); crop = json.load(open(W('m27-crop.json')))
used = s5['used']; N = len(used)
def strip(d, drop=('frames', 'psf_R', 'pairs', 'hfd_px_middle', 'hfd_px_outer', 'sky_noise_per_frame_dn', 'reference_stars_xy', 'reference_stars_flux', 'worst')):
    if isinstance(d, dict): return {k: strip(v, drop) for k, v in d.items() if k not in drop}
    if isinstance(d, list) and len(d) > 40: return '%d values (see work/)' % len(d)
    if isinstance(d, list): return [strip(v, drop) for v in d]
    return d
def skycheck(p):
    return subprocess.run([os.path.expanduser('~/.observatory/pyenv/bin/python'), os.path.join(SCR, 'skycheck.py'), p], capture_output=True, text=True).stdout.strip()
jpg = open(os.path.join(FINAL, NAME + '.jpg'), 'rb').read(); meta_free = not any(m in jpg[:4096] for m in (b'Exif', b'http://ns.adobe.com/xap', b'\xff\xfe'))
hal = s12['sectors']; ears = [r for r in hal if r['ring_arcmin'] == [3.0, 4.0] and r['seen']]
named = s7['dust']['named_shadows']
rec = dict(
    target='Messier 27 (NGC 6853), the Dumbbell Nebula, a planetary nebula in Vulpecula', night='2026-10-17 (frames of 18 October UTC, 03:46 to 04:22)',
    made=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    reproduce='hack/stacks/2026-10-17/m27/run_all.sh (hooks M27_*, see common.py); with none set it reproduces this run. RAWs ~/.observatory/stills/2026-10-18/ read in place, never written',
    template='hack/stacks/2026-10-12/m77-calibrated (calibrated flat, Gaia star colours, darks.subtract) with the combine of hack/stacks/2026-10-12/ngc891-coadd (proper coaddition, keep_phase="mean"; the old sigma-clipped weighted mean made from the same cube as a control, work/control_*.npy)',
    files=dict(picture=[os.path.join(FINAL, NAME + e) for e in ('.png', '.jpg', '.json')], stack_linear_tif=os.path.join(OUT, 'm27-stack.tif'), full_field=[os.path.join(OUT, 'm27-field' + e) for e in ('.png', '.jpg')], share=os.path.join(SCR, 'share'), logs=os.path.join(SCR, 'logs')),
    summary=dict(
        frames='%d taken in the run (15 s, ISO 3200 by the RAW\'s own EXIF; every one plate-solved on M27 by its sidecar); %d used, %d dropped' % (len(s1['frames']), N, len(s5['rejected'])),
        dropped={r['stamp']: r['why'] for r in s5['rejected']},
        not_in_the_run='before 03:46 UTC: centring frames (2 s at ISO 6400, a 1/60 s frame) and the focusing frames on Vega (2 s, 03:06 to 03:25); from 04:23 UTC, M33 (another target, used only for a candidate flat). None of these is in the stack',
        integration_s=N * EXPOSURE_S, integration='%d x 15 s = %.1f minutes' % (N, N * EXPOSURE_S / 60),
        transparency='%.3f to %.3f of the run\'s typical star flux: no cloud' % (min(u['transparency'] for u in used), max(u['transparency'] for u in used)),
        star_size='half-flux diameter, green, %d compact unsaturated stars: %.2f arcsec in the stack, %.2f in the reference frame alone; the run\'s frames %.2f (median, step 4). The box\'s own figure (the 960 px JPEG preview) read 6.2 to 7.3 arcsec for the same frames: a coarser measure of the same stars' % (s10['star_size']['stars'], s10['star_size']['hfd_stack_arcsec'], s10['star_size']['hfd_single_arcsec'], s5['hfd_run_median_arcsec']),
        flat='the 13 October hybrid flat (~/.observatory/nights/2026-10-12-a6000/flat-hybrid-m77: large scale from that night\'s open sky of NGC 891, NGC 2261, NGC 2419 and M1; dust from the 13 October twilight flats), chosen over two others on this run\'s own sky (step 7a), times this run\'s own measure of the dust that moved since (step 7)',
        dust=('three shadows named for tonight, their depth in this run\'s own sky before any flat / after the 13 October flat / after this run\'s own correction: ' + '; '.join('%s at sensor (%d, %d): %.1f%% / %.1f%% / %.1f%%' % (d['name'], *d['sensor_px'], 100 * d['depth_in_own_sky_no_flat'], 100 * d['left_by_the_flat'], 100 * d['left_after_own_correction']) for d in named)
              + '. The crescent is new since 13 October (the twilight flat has only a 3%% shadow there) and is taken out by this run\'s own measure; the two spots were already in the 13 October flat. %d shadows in all were measured on this run\'s sky (seen in the odd and in the even frames alone) and divided out, %.2f%% of the sensor' % (len(s7['dust']['divided_out']), 100 * s7['dust']['sensor_fraction_changed'])),
        darks='none taken tonight: darks.subtract changed nothing and said so; hot pixels found from the run itself and repaired by the 3 x 3 median of their colour plane',
        combine='proper coaddition (Zackay & Ofek 2017; tools/coadd.py, keep_phase="mean"), %d PSF stars per plane, one PSF per frame and plane; theory S/N gain over the old weighted mean %.4f (green). The old combine is made from the same cube as a control' % (s8c['planes']['G1']['psf_stars'], s8c['planes']['G1']['theory_with_the_control_weights']['gain_of_proper']),
        noise='sky noise per stack pixel %.1f to %.1f DN against %.1f to %.1f for one frame: %.2f to %.2f times lower (%.2f expected from the weights)' % (min(s10['noise_faint_region']['planes_stack'].values()), max(s10['noise_faint_region']['planes_stack'].values()), min(s10['noise_faint_region']['planes_single'].values()), max(s10['noise_faint_region']['planes_single'].values()), min(s10['noise_faint_region']['improvement'].values()), max(s10['noise_faint_region']['improvement'].values()), s10['noise_faint_region']['ideal']),
        is_it_the_thing='yes: the reference frame and the stack plate-solved (astrometry.net); M27\'s central star\'s catalogue place falls %.1f arcsec from the light\'s centroid in the stack' % s9['catalogue']['M27']['offset_arcsec'],
        ears='the faint outer lobes ("ears", filling the nebula out along its long axis, position angle about 90 to 150 and 270 to 330 degrees) are real: 3 to 4 arcmin from the star they are %s sigma above blank sky in the odd and in the even frames alone (step 12). Beyond 4 arcmin no sector passes in either half: the faint outer halo seen in deep pictures (out to about 7 arcmin) is NOT seen in %.1f minutes from this sky' % (', '.join('%.0f/%.0f' % (r['odd_sigma'], r['even_sigma']) for r in ears), N * EXPOSURE_S / 60),
        followed='the nebula followed (ring median of green above 3 x the blank-sky spread, unbroken from the star) to %.2f arcmin from the star, %.1f arcmin across' % (s10['galaxy']['followed_to']['radius_arcmin'], s10['galaxy']['followed_to']['diameter_arcmin']),
        colour='the camera\'s daylight white balance times Gaia DR3 star colours (kR %.4f, kB %.4f from %s stars), the camera\'s own colour matrix. The nebula\'s blue-green (doubly ionised oxygen, 501 nm) is outside sRGB; colour shown only above 8 DN, grey below. No saturation beyond x 1.2' % (s9b['factors']['R'], s9b['factors']['B'], s9b.get('fit', {}).get('stars', '93')),
        picture='a %d x %d px cut at the stack\'s own pixels (0.777 arcsec per px, %.1f x %.1f arcmin), nothing resampled after the stack, never enlarged; north %.1f degrees clockwise from up (the camera\'s orientation)' % (crop.get('w', 1200), crop.get('h', 1000), 1200 * s9['pixscale_arcsec'] / 60, 1000 * s9['pixscale_arcsec'] / 60, s9['north_angle_from_up_deg_clockwise']),
        sky='dark sky neutral: ' + skycheck(os.path.join(FINAL, NAME + '.png')),
        jpeg_metadata_free=meta_free,
        altitude='about 60 to 70 degrees up during the run (sidecars: %.0f to %.0f); no clock time goes with it anywhere published' % (s1['frames'][-1]['alt_deg'], s1['frames'][0]['alt_deg'])),
    steps=[
        dict(step='1 frames and hot pixels', numbers=strip(dict(window=[T0, T1], left_out=s1['left_out'], hot=s1['hot'], hot_from_frames=len(s1['hot_from'])))),
        dict(step='2-3 stars and registration (rotation + shift on the stars)', numbers=dict(reference=REF_STAMP, rotation_deg_range=[min(o['rotation_deg'] for o in s3['transforms']), max(o['rotation_deg'] for o in s3['transforms'])], wrms_px_max=max(o['wrms_px'] for o in s3['transforms']))),
        dict(step='4-5 quality and selection', numbers=strip(dict(limits=s5['limits'], hfd_run_median_arcsec=s5['hfd_run_median_arcsec'], effective_frames=s5['effective_frames'], used={u['stamp']: dict(transparency=u['transparency'], weight=u['weight'], hfd_arcsec=u['hfd_arcsec'], smear=u['smear']) for u in used}, rejected=s5['rejected']), drop=())),
        dict(step='6 is it the thing (reference frame plate solve)', numbers=strip(s6, drop=('wcs_header', 'corners_ra_dec'))),
        dict(step='7a candidate flats on this run\'s own sky (flatcheck.py)', numbers=strip(dict(m27_sky=s7a['m27_sky'], m33_run={k: v for k, v in s7a['m33_run'].items() if k != 'frames'}, on_m27_sky=[dict(flat=r['flat'], large={k: dict(rms=v['robust_rms'], after_plane=v['robust_rms_after_plane']) for k, v in r['large'].items()}, dust_left=dict(shadows=r['small']['shadows_left'], deepest=r['small']['deepest'], correlation=r['small']['dust_correlation']), depth_sky_over_flat={k: v['depth_in_sky_over_depth_in_flat'] for k, v in r['per_colour_slope'].items()}) for r in s7a['on_m27_sky']]), drop=('frames',)),
             said='hybrid13 leaves the least on this sky after a plane (green 0.57%, against 0.80% for the M33 flat and 1.98% for the twilight flat as measured). M33 is bigger than the frame, so its run is not open sky; its flat is kept as a candidate only. Every flat leaves this run\'s dust about 70% as deep as it carries it (correlation 0.35): the dust moved since 13 October, so step 7 measures it here'),
        dict(step='7 flat check and this run\'s own dust', numbers=strip(s7, drop=('frames', 'the_flats_fitted_shadows'))),
        dict(step='8 combine (proper coadd) and air dispersion', numbers=strip(dict(stack=dict(faint_region=s8['faint_region'], air_dispersion=s8.get('air_dispersion'), subsets={k: len(v) for k, v in s8['subsets'].items()}, control_planes=s8['planes']), coadd={p: strip(v) for p, v in s8c['planes'].items()}))),
        dict(step='9 plate solve of the stack and the crop', numbers=strip(s9, drop=('wcs_header',))),
        dict(step='9b star colours (Gaia DR3)', numbers=strip(s9b)),
        dict(step='10 deliver: TIF, stretch, sky plane in the picture only, measures', numbers=strip(s10, drop=('rgb_xyz_matrix', 'rgb_cam'))),
        dict(step='11 picture: crop (crop.py) and finish (finish16.py)', numbers=dict(crop=crop, finish=fin)),
        dict(step='12 half stacks: are the ears real?', numbers=s12)])
for p in (os.path.join(FINAL, 'recipe.json'), os.path.join(SCR, 'recipe.json')):
    json.dump(rec, open(p, 'w'), indent=1, default=float)
for k, v in rec['summary'].items(): print('%s: %s' % (k, v))
