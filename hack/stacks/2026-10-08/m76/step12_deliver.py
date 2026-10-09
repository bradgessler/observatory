"""Step 12: the deliverables beside the picture in ~/.observatory/nights/2026-10-08-a6000/m76/:
  m76-stack.tif   the registered stack (step 6 ref grid), linear, white-balanced RGB, 16 bit
  m76.jpg         the finished picture (step 10); m76-1600.jpg only if it is wider than 1600 px (it is not)
  recipe.json     every frame used or dropped and why, the registration, weights, sky values, stretch and finish
                  parameters, the numbers of step 9, tool versions
and checks that no JPEG carries EXIF, GPS or XMP."""
import json, os, glob, platform, datetime, subprocess
import numpy as np, cv2, tifffile, rawpy, scipy, PIL
from PIL import Image
from common import *

PEDESTAL = 1000.0          # added before writing 16-bit unsigned, so the sky's negative noise is kept
s1 = json.load(open(W('step1_solve.json'))); s2 = json.load(open(W('step2.json'))); s4 = json.load(open(W('step4_transforms.json')))
s5 = json.load(open(W('step5_quality.json'))); s6r = json.load(open(W('step6_ref.json'))); s6n = json.load(open(W('step6_north.json')))
s7 = json.load(open(W('step7_grid.json'))); s8 = json.load(open(W('step8_sky.json'))); s9 = json.load(open(W('step9_measure.json'))); s10 = json.load(open(W('step10_finish.json')))
s11 = json.load(open(W('step11_decon.json')))
f2 = {f['stamp']: f for f in s2['frames']}; t4 = {o['stamp']: o for o in s4}; q5 = {o['stamp']: o for o in s5['quality']}
USED = s6r['used']
wb = s10['white_balance']; wb_r, wb_b = wb['R'], wb['B']

# ---- the stack, 16 bit ----
st = np.load(W('ref_stack.npy'))
rgb = np.dstack([st[0] * wb_r, (st[1] + st[2]) / 2, st[3] * wb_b])
lo, hi = float(rgb.min()), float(rgb.max())
u16 = np.clip(np.round(rgb + PEDESTAL), 0, 65535).astype(np.uint16)
clipped = int(((rgb + PEDESTAL) < 0).sum() + ((rgb + PEDESTAL) > 65535).sum())
tifffile.imwrite(os.path.join(OUT, 'm76-stack.tif'), u16, photometric='rgb', compression='zlib', metadata=None)

# ---- JPEGs: the finished picture, and a 1600 px one only when the picture is wider ----
outs = {}
im = Image.open(os.path.join(OUT, 'm76.jpg'))
if im.size[0] > 1600:
    h = round(im.size[1] * 1600 / im.size[0])
    fin = Image.open(W('m76-finished.png')).convert('RGB').resize((1600, h), Image.LANCZOS)
    Image.fromarray(np.asarray(fin).copy(), 'RGB').save(os.path.join(OUT, 'm76-1600.jpg'), quality=90, subsampling=0, optimize=True)
def meta_check(path):
    b = open(path, 'rb').read()
    return dict(exif=b'Exif\x00\x00' in b, xmp=b'http://ns.adobe.com/xap' in b, gps=b'GPS' in b, iptc=b'Photoshop 3.0' in b, icc=b'ICC_PROFILE' in b, bytes=len(b))
for p in sorted(glob.glob(os.path.join(OUT, '*.jpg'))):
    mc = meta_check(p); assert not (mc['exif'] or mc['xmp'] or mc['gps'] or mc['iptc']), (p, mc)
    outs[os.path.basename(p)] = dict(size_px=list(Image.open(p).size), **mc)
print('jpegs', outs)

# ---- recipe ----
def r3(v): return None if v is None else round(float(v), 3)
frames = []
for f in s2['all_in_window']:
    s = f['stamp']; d = dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['sha256'].get('arw'),
                             sidecar_flags=dict(settling=f['settling'], cloud=f['cloud'], since_slew_s=f['since_slew_s'], box_transparency=f['transparency_box'], box_star_size_arcsec=f['box_star_size_arcsec']))
    nr = [x for x in s2['not_read'] if x['stamp'] == s]
    if nr:
        d.update(used=False, why_dropped=nr[0]['why'] + '. Not read.'); frames.append(d); continue
    g = f2[s]; o = t4[s]; q = q5[s]
    d.update(used=s in USED, why_dropped=q['why_dropped'] or None, raw_exif=g['raw_exif'], black_level=g['black'],
             sky_constant_subtracted_dn=dict(zip(PLANE_NAMES, [r3(b['clipped_mean']) for b in g['bg']])), sky_median_dn=dict(zip(PLANE_NAMES, [b['median'] for b in g['bg']])),
             sky_noise_dn=dict(zip(PLANE_NAMES, [round(b['clipped_std'], 2) for b in g['bg']])), white_balance_as_shot=g['wb'],
             transient_spikes_replaced=g['transient_spikes_replaced'],
             registration=dict(rotation_deg=round(o['rotation_deg'], 4), shift_at_sensor_centre_px=[round(v, 2) for v in o['shift_at_centre_px']], R=o['R'], t=o['t'], stars_matched=o['matched'], stars_used=o['used'],
                               rms_px=round(o['rms_px'], 3), weighted_rms_px=round(o['wrms_px'], 3), scale_if_left_free=round(o['similarity_scale'], 5)),
             quality=dict(half_flux_diameter_arcsec=round(q['hfd_arcsec'], 2), elongation_median=round(q['elong_median'], 3), common_direction_ellipticity=round(q['coherent_ellipticity'], 3),
                          transparency=round(q['transparency'], 4), sky_noise_green_dn=round(q['sky_noise_green_dn'], 2)),
             weight=round(s5['weights'].get(s, 0.0), 4), divided_by_transparency=round(q['transparency'], 4) if s in USED else None)
    frames.append(d)
rot = np.array([t4[s]['rotation_deg'] for s in sorted(t4)]); stamps = sorted(t4)
def tsec(st_): return int(st_[9:11]) * 3600 + int(st_[11:13]) * 60 + int(st_[13:15])
span = tsec(stamps[-1]) - tsec(stamps[0])
n = s9['noise_dn_per_px']; stars = s9['stars']
recipe = dict(
    what='M76 (NGC 650/651), the Little Dumbbell Nebula: %d x 15 s at ISO 3200 (%.1f minutes), Sony a6000 on a Celestron 8SE (2081 mm by plate solve, f/10), EQ6-R tracking, night of 8 to 9 October 2026; stacked from RAW colour planes' % (len(USED), len(USED) * 0.25),
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw='.'.join(map(str, rawpy.libraw_version)), tifffile=tifffile.__version__, pillow=PIL.__version__,
               astrometry_net=subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip(), index_files='~/.observatory/astrometry (4107-4119, 4204-4207)',
               note='deterministic array arithmetic only: medians, means, measured transforms, fixed formulas; nothing generative, learned or predicted'),
    scripts='hack/stacks/2026-10-08/m76/ in the observatory repository (run_all.sh runs them in order; logs and step JSONs in m76/work/)',
    source=dict(folder=STILLS, window_utc=[T0, T1], frames_in_window=len(s2['all_in_window']), frames_read=len(s2['frames']), frames_used=len(USED), originals='read in place, never written',
                dropped=[dict(file=x['file'], why=x['why_dropped']) for x in frames if not x['used']]),
    frames=frames,
    steps=[
        dict(step='is it the thing', detail='single frames plate-solved before stacking (astrometry.net on the green planes, 3 x 3 median, 2 x 2 mean): M76 catalogue position J2000 RA 25.5821 Dec +51.5753 lands near the middle of every solved frame',
             solves=[dict(frame=x['stamp'], solved=x['solved'], target_sensor_px=[round(v, 1) for v in x['target_sensor_px']] if x.get('solved') else None, arcsec_per_sensor_px=r3(x.get('pixscale_arcsec_per_sensor_px')), focal_length_mm=r3(x.get('focal_length_mm')), note=x.get('note')) for x in s1]),
        dict(step='read', detail='rawpy raw_image_visible (sensor orientation 6024 x 4024, RGGB; the JPEG/EXIF orientation is ignored), black level 512 subtracted; four colour planes R, G1, G2, B kept apart at 3012 x 2012, no demosaic. Exposure and ISO checked in each RAW\'s own EXIF (all 15 s, ISO 3200, as the sidecars say).'),
        dict(step='sky per frame', detail='one constant per plane per frame: the 3-sigma clipped mean of the plane outside %d sensor px of where M76 can be, subtracted (values per frame above)' % s2['sky_mask']['radius_sensor_px']),
        dict(step='hot pixels', detail='no darks: fixed hot pixels from the per-plane median of all 25 frames without registration (the stars move up to 270 px between frames, the sensor\'s defects do not), pixels above the 5 x 5 median of that by more than max(6 sigma, 25% of the level); transient ones per frame above the 3 x 3 median by 8 sigma + 50% of the level. Both replaced by the 3 x 3 median of the same colour plane.',
             fixed_hot_pixels={h['plane']: h['fixed_hot'] for h in s2['hot']}, fraction_of_plane={h['plane']: round(h['frac'], 5) for h in s2['hot']}),
        dict(step='stars', detail='green planes averaged, Gaussian blur sigma 2.5, 6-sigma blobs; Gaussian-windowed centroid (sigma 5 plane px); 14 plane px aperture for flux, moments and half-flux radius; highest raw value per plane for saturation'),
        dict(step='register', detail='reference frame %s (the middle of the run, one of the sharpest). First match by a vote over trial rotations (-2 to +2 deg) and pair shifts of the 150 brightest stars, then nearest-neighbour matching and a weighted least-squares rotation + shift (no scale), weights 1/(0.25^2 + (7000/flux)^2) px^-2, 3.5-sigma rejection. Scale left free came out within 0.0001 of 1.' % REF_STAMP,
             rotation_deg=dict(first=round(float(rot[0]), 4), last=round(float(rot[-1]), 4), total=round(float(rot[0] - rot[-1]), 4), span_s=span, per_minute=round(float((rot[0] - rot[-1]) / span * 60), 4), corrected=True),
             jumps='the field jumped by 165 and 154 sensor px between frames 054745-054820 and 055640-055716 (no slew in the sidecars: the pointing model re-centring); registration takes it in its stride'),
        dict(step='select and weight', detail='fixed limits; a frame is dropped if any is crossed', limits=s5['limits'], quality_stars=len(s5['quality_star_ref_index']), clearest_frame=s5['clearest_frame'],
             run_median_hfd_arcsec=round(s5['hfd_run_median_plane_px'] * 2 * SCALE_SENSOR, 2), weight_rule=s5['weight_rule'], effective_frames=round(s5['effective_frames'], 2),
             result='22 of 25 used; the sky was clear all run (transparency 0.99 to 1.00 in every kept frame), so the weights are all within 2% of 1 and the drops are for the tube moving (wind or a bump), not cloud'),
        dict(step='resample and combine', detail='each plane of each frame mapped straight onto the output grid (rotation + shift + the plane\'s own place in the 2 x 2 colour cell), OpenCV remap Lanczos-4, after dividing the frame by its transparency. Per pixel and plane: values more than 3 sigma from the median rejected (sigma = 1.4826 MAD, floor half the single-frame noise), then 3 sigma about the weighted mean of the survivors, then the weighted mean.',
             kappa=s6r['kappa'], per_plane_ref_grid=s6r['planes'], per_plane_north_grid=s6n['planes']),
        dict(step='grids', ref=dict(what='m76-stack.tif: the reference frame\'s colour-cell grid, 0.776 arcsec per px, sensor orientation, the rectangle every used frame covers', **s6r['grid']),
             north=dict(what='m76.jpg: north up, east left, same 0.776 arcsec per px, centred on the catalogue position, laid out from the stack\'s plate solution; every frame resampled once, straight onto it', size=s7['size'], out_to_stack=s7['out_to_stack'], out_to_ref_sensor=s7['out_to_ref_sensor'])),
        dict(step='colour planes lined up', detail='at 57 to 59 degrees altitude the air is a slight prism: stars sit %.2f px apart in red and blue on the stack. On the north-up grid the red and blue planes are sampled that much further along, inside the one resampling (no extra interpolation). Left after: under 0.01 px.' % float(np.hypot(*(np.array(s7['colour_offsets']['red_minus_green_stack_px']) - np.array(s7['colour_offsets']['blue_minus_green_stack_px'])))),
             measured=s7['colour_offsets'], left_after=stars['colour_offset_left_px']),
        dict(step='plate solution of the stack', **s7['solve'], target_in_stack=s7['target']),
        dict(step='sky dome (picture only)', detail=open(os.path.join(SCR, 'step8_sky.py')).read().split('"""')[1].strip().replace('\n', ' '), fit=s8['fits'], range_on_north_grid_dn=s8['north_grid_range_dn']),
        dict(step='finish (picture only)', detail=open(os.path.join(SCR, 'step10_finish.py')).read().split('"""')[1].strip().replace('\n', ' '), white_balance=wb,
             sky_constant_after_dome_dn=s10['sky_constant_after_dome_dn'], crop=s10['crop'], stretch=s10['stretch'], finish_options=' '.join(s10['finish_options']), finish_steps=s10['finish_recipe']['steps'],
             clipped_to_white_pct=s10['finish_recipe']['clipped_to_white_pct'], clipped_to_black_pct=s10['finish_recipe']['clipped_to_black_pct'], skycheck=s10['skycheck']),
    ],
    numbers=dict(
        sky_noise_dn_per_px=dict(units='white-balanced DN of the 14-bit RAW scale, per 0.776 arcsec px, on the north-up grid, median of 40 x 40 px block standard deviations of masked sky; single = the reference frame alone through the same repair and resampling',
                                 stack=n['stack'], single=n['single'], half_a=n['half_a'], half_b=n['half_b'], improvement=s9['improvement'], ideal_sqrt_effective_frames=round(s9['ideal_sqrt_n_eff'], 2)),
        stars=stars, nebula_green_profile=s9['nebula_green_profile'], outer_loops_half_stacks=s9['outer_loops_half_stacks'], sky_slope_before_dome=s9['sky_slope']),
    deconvolution=dict(delivered=False, how=open(os.path.join(SCR, 'step11_decon_trial.py')).read().split('"""')[1].strip().replace('\n', ' '), trials=s11['trials'],
                       note_on_blur_hfd='the blur half-flux diameters are read at the sampled radii of a 41 x 41 px kernel, so they step (4.47, 5.66 px)',
                       why_not='Both trials make the stars smaller (half-flux diameter %.1f px plain, %.1f px at cap 1.5, %.1f px at cap 2.5) but raise the sky noise %.1f and %.1f times and draw a dark ring round every star (%.1f%% and %.1f%% of the star\'s peak below the sky, against %.1f%% plain); in the nebula the bar picks up salt-and-pepper grain and the faint lobes sink into the noise. The trade goes the wrong way for this stack (about 5 per pixel signal to noise on the bar): less feature, less noise wins. Not delivered; the trial pictures are in work/ (m76-wiener-cap1.5-finished.png, m76-wiener-cap2.5-finished.png).' % (
                           s11['trials'][0]['plain']['star_hfd_px'], s11['trials'][0]['wiener']['star_hfd_px'], s11['trials'][1]['wiener']['star_hfd_px'], s11['trials'][0]['wiener']['sky_noise_green'] / s11['trials'][0]['plain']['sky_noise_green'],
                           s11['trials'][1]['wiener']['sky_noise_green'] / s11['trials'][1]['plain']['sky_noise_green'], -100 * s11['trials'][0]['wiener']['worst_ring'], -100 * s11['trials'][1]['wiener']['worst_ring'], -100 * s11['trials'][0]['plain']['deepest_ring_fraction_of_peak'])),
    caveats=[
        'Short and read-noise limited: at 15 s and ISO 3200 the sky is only 30 (R) to 110 (G) DN above black while each raw pixel\'s noise is 46 to 57 DN, so the frames are dominated by the camera\'s own noise, not the sky. %.1f minutes in all. Sky noise fell %.2f times against a single frame (ideal %.2f for these weights).' % (len(USED) * 0.25, s9['improvement']['mean_of_RGB'], s9['ideal_sqrt_n_eff']),
        'No darks and no flats. Hot pixels were found from the run itself and repaired. Vignetting leaves a dome in the sky about 3.5 DN (green) across the picture\'s area: the picture has it subtracted (a round vignetting model measured from the whole frame outside 4.3 arcmin of M76, step 8); m76-stack.tif does not. After that the sky still has structure of about +-1 DN on arcminute scales, as faint as the nebula\'s outer halo, so nothing fainter than about 2 DN is claimed and the black point sits above it.',
        'The faint outer loops and halo of M76 (beyond about 75 arcsec from the centre) are not confirmed. In the two half stacks the 75 to 150 arcsec ring reads -1.3 to +0.4 DN by sector, the same in both halves, which is the sky\'s own leftover structure, not the nebula. What is shown is real: the bright bar (signal to noise about 5.5 per pixel in the stack against 1.3 in a single frame) and the two fainter lobes either side of it: chosen in one half stack and measured in the other, the lobes are %.1f and %.1f DN, %.0f and %.0f sigma.' % (
            s9['lobes_and_red_cross_check']['chosen_in_a_measured_in_b']['lobes_green_dn'], s9['lobes_and_red_cross_check']['chosen_in_b_measured_in_a']['lobes_green_dn'], s9['lobes_and_red_cross_check']['chosen_in_a_measured_in_b']['lobes_sigma'], s9['lobes_and_red_cross_check']['chosen_in_b_measured_in_a']['lobes_sigma']),
        'Stars in the stack are %.1f arcsec half-flux diameter (%d isolated stars), %.0f%% wider than the same stars in the sharpest single frame (%.1f arcsec): the run median frame is about as wide as the stack. Elongation %.2f in the stack.' % (stars['hfd_stack_arcsec'], stars['n'], 100 * (stars['hfd_stack_arcsec'] / stars['hfd_single_reference_arcsec'] - 1), stars['hfd_single_reference_arcsec'], stars['elong_stack']),
        'Three frames dropped for the tube moving during the exposure (stars stretched 1.47 to 1.55 to 1, all the same way): 05:47:45, 05:53:40 and 05:54:17 UTC. The last frame of the window (06:00:49) was taken as the mount started for M57 and is not M76. The sky was clear: no frame lost to cloud.',
        'Colour is the camera\'s as-shot white balance only, with no camera-to-sRGB matrix, as on 3 October: the oxygen light of the nebula comes out cyan-blue. The pink at the north-east and south-west ends of the bar and on the outer edges of the lobes repeats: chosen as the reddest tenth of the nebula in one half stack, those pixels are %.2f and %.2f in R/G in the other half against %.2f for the rest. That is where the nebula\'s red nitrogen and hydrogen light is usually seen, but this camera cannot tell the two apart.' % (
            s9['lobes_and_red_cross_check']['chosen_in_a_measured_in_b']['red_region_r_over_g'], s9['lobes_and_red_cross_check']['chosen_in_b_measured_in_a']['red_region_r_over_g'], s9['lobes_and_red_cross_check']['chosen_in_a_measured_in_b']['rest_of_nebula_r_over_g']),
        'Dust shadows (dark rings 50 to 100 px across) show in the full field of m76-stack.tif. The nearest to M76 is about 5.5 arcmin east of it, outside the picture\'s crop; none is inside it.',
        'The single comparison frame went through the same hot-pixel repair, resampling, sky dome and finish, so the comparison shows the gain from averaging only.',
    ],
    verdict='Better than a single frame, plainly: the sky noise is 4.5 times lower, and where one frame shows a ragged bar the stack shows the bar, its two lobes and a quiet neutral sky. The stars are a little softer than in the sharpest frame. The outer halo is beyond these %.1f minutes without darks and flats.' % (len(USED) * 0.25),
    outputs={
        'm76-stack.tif': dict(what='the registered stack, linear, 16-bit unsigned RGB: R x %.4f, mean of G1 and G2, B x %.4f (the camera\'s as-shot white balance), per-frame sky constants subtracted, NO sky dome subtracted, no stretch' % (wb_r, wb_b),
                              units='value = white-balanced DN (14-bit RAW scale, per frame of 15 s, scaled to the clearest frame) + %d' % PEDESTAL, size_px=[int(u16.shape[1]), int(u16.shape[0])], pixel_scale_arcsec=round(s7['pixscale_arcsec'], 4),
                              orientation='sensor orientation of %s (not north up): north points %.1f deg counter-clockwise from up, not mirrored' % (REF_STAMP, -s7['solve']['north_on_screen_deg_clockwise_from_up']),
                              origin='pixel (0,0) centre = sensor (%.1f, %.1f) of the reference frame; pixel (u, v) = sensor (2u + %.1f, 2v + %.1f)' % (s6r['grid']['origin_sensor_xy'][0] + 0.5, s6r['grid']['origin_sensor_xy'][1] + 0.5, s6r['grid']['origin_sensor_xy'][0] + 0.5, s6r['grid']['origin_sensor_xy'][1] + 0.5),
                              m76_at_px=[round(v, 1) for v in s7['target']['stack_px']], wcs='work/solve_stack.wcs (astrometry.net, on the 2 x 2 binned stack: stack px = 2 (FITS px - 1) + 0.5)',
                              linear_range_dn=[round(lo, 1), round(hi, 1)], pixels_clipped_by_16_bit=clipped, compression='zlib, lossless'),
        'm76.jpg': dict(what='the finished picture', size_px=outs['m76.jpg']['size_px'], pixel_scale_arcsec=round(s7['pixscale_arcsec'], 4), field_arcmin=[round(v, 2) for v in s10['crop']['arcmin']], orientation='north up, east left',
                        m76_catalogue_position_px=s10['crop']['target_px_in_picture'], resampling='none beyond the one registration resampling; never enlarged', jpeg='Pillow, quality 92, 4:4:4, no EXIF, GPS, XMP or ICC', metadata_check=outs['m76.jpg']),
        'm76-1600.jpg': 'not made: the picture is %d px wide, under 1600' % outs['m76.jpg']['size_px'][0],
    },
)
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('wrote', OUT, 'tif range', lo, hi, 'clipped', clipped)
