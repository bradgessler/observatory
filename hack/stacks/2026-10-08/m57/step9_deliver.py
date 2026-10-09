"""Step 9: the deliverables and the recipe. m57.jpg from finish.py's picture (written by Pillow with no EXIF, GPS, XMP or
ICC block: JFIF only, checked), m57-single-vs-stack.jpg (the reference frame alone through exactly the same steps,
left; the stack, right), the numbers (noise against one frame, star size, the nebula's signal, the odd/even check) and
recipe.json with every frame, used or dropped and why."""
import glob, json, os, platform, subprocess, datetime
import numpy as np, cv2, rawpy, scipy, tifffile, PIL
from PIL import Image
from common import *
from step2_stars import measure

FINISH = os.environ.get('M57_FINISH_ARGS', '')           # run_all.sh passes the finish.py arguments it used, for the recipe
s1 = jload('step1.json'); s3 = jload('step3_transforms.json'); s4 = jload('step4_quality.json'); s5 = jload('step5_select.json')
s6 = jload('step6.json'); s7 = jload('step7_solve.json'); s8 = jload('step8.json')
fin = json.load(open(W_('m57-finished.json'))); fin1 = json.load(open(W_('single-finished.json')))
SCALE = float(np.mean(s7['scale_arcsec_per_px']))
N = len(s6['frames'])


def save_jpeg(rgb8, path):
    Image.fromarray(np.ascontiguousarray(rgb8), 'RGB').save(path, 'JPEG', quality=92, subsampling=0, optimize=True)
    b = open(path, 'rb').read()
    assert b[:2] == b'\xff\xd8' and b'Exif' not in b[:4096] and b'http://ns.adobe.com/xap' not in b and b'ICC_PROFILE' not in b[:4096], 'metadata found in ' + path
    return dict(bytes=len(b), size_px=[int(rgb8.shape[1]), int(rgb8.shape[0])], metadata='none (JFIF header only; no EXIF, GPS, XMP or ICC)')


pic = cv2.imread(W_('m57-finished.png'))[..., ::-1]; pic1 = cv2.imread(W_('single-finished.png'))[..., ::-1]
out_files = {}
out_files['m57.jpg'] = save_jpeg(pic, os.path.join(OUT, 'm57.jpg'))
if pic.shape[1] > 1600:
    h = int(round(pic.shape[0] * 1600 / pic.shape[1]))
    out_files['m57-1600.jpg'] = save_jpeg(cv2.resize(pic, (1600, h), interpolation=cv2.INTER_AREA), os.path.join(OUT, 'm57-1600.jpg'))
gap = np.zeros((pic.shape[0], 8, 3), np.uint8)
out_files['m57-single-vs-stack.jpg'] = save_jpeg(np.hstack([pic1, gap, pic]), os.path.join(OUT, 'm57-single-vs-stack.jpg'))
for old in ('m57-1600.jpg',):
    if old not in out_files and os.path.exists(os.path.join(OUT, old)): os.remove(os.path.join(OUT, old))

# ---------------- numbers ----------------
st = np.load(W_('stack_mean.npy')); sg = np.load(W_('single_planes.npy')); odd = np.load(W_('stack_odd.npy')); even = np.load(W_('stack_even.npy'))
cover = np.load(W_('cover.npy')); ok = cover == N
wb = np.array(s8['white_balance_daylight'])
def cam(P): return [P[0] * wb[0], (P[1] + P[2]) / 2, P[3] * wb[2]]
pc = np.array(s7['m57_catalogue']['stack_px'])
ref_stars = [r for r in jload('step2_stars.json') if r['stamp'] == s3['reference']][0]['stars']
smask = np.zeros((h2, w2), np.uint8)
for s in ref_stars: cv2.circle(smask, (int(round(s['x'])), int(round(s['y']))), int(min(60, 10 + 6 * np.sqrt(max(s['flux'], 0) / 1e4))), 1, -1)
yy, xx = np.mgrid[0:h2, 0:w2]; rr = np.hypot(xx - pc[0], yy - pc[1])
ring_sky = (rr > 200) & (rr < 400) & (smask == 0) & ok
noise = {}
for name, P in (('single', sg), ('stack', st)):
    noise[name] = [clipped_stats(c[ring_sky])[1] for c in cam(P)]
half = [clipped_stats(((a - b) / 2)[ring_sky])[1] for a, b in zip(cam(odd), cam(even))]
gain = [a / b for a, b in zip(noise['single'], noise['stack'])]
sumw = s5['sum_of_weights']
# local sky level (for the profiles): clipped mean in the same sky ring
def prof(P):
    C = cam(P); sky = [clipped_stats(c[ring_sky])[0] for c in C]; rows = []
    for a, b in ((0, 10), (10, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 85), (85, 100), (100, 130), (130, 160)):
        m = (rr >= a) & (rr < b) & (smask == 0) | ((rr >= a) & (rr < b) & (rr < 70))
        rows.append(dict(r_px=[a, b], r_arcsec=[round(a * SCALE, 1), round(b * SCALE, 1)], mean_dn=[round(float(np.mean(c[m]) - s_), 2) for c, s_ in zip(C, sky)], pixels=int(m.sum())))
    return rows
profile = dict(stack=prof(st), single=prof(sg), odd=prof(odd), even=prof(even))
for r_ in profile['stack']:
    r_['snr_per_px_stack'] = [round(v / n, 2) for v, n in zip(r_['mean_dn'], noise['stack'])]
for r_, q in zip(profile['single'], profile['stack']):
    r_['snr_per_px_single'] = [round(v / n, 2) for v, n in zip(r_['mean_dn'], noise['single'])]
# the red rim: is it in both halves? (outer ring r 40-60 px, red minus the scaled green)
def rim(P):
    C = cam(P); sky = [clipped_stats(c[ring_sky])[0] for c in C]
    m = (rr >= 42) & (rr < 58); i = (rr >= 20) & (rr < 34)
    R, G = np.mean(C[0][m]) - sky[0], np.mean(C[1][m]) - sky[1]; Ri, Gi = np.mean(C[0][i]) - sky[0], np.mean(C[1][i]) - sky[1]
    return dict(outer_R_over_G=round(float(R / G), 3), inner_R_over_G=round(float(Ri / Gi), 3))
rimcheck = dict(odd=rim(odd), even=rim(even), stack=rim(st), single=rim(sg),
                err_outer=round(float(np.sqrt(2) * half[0] / np.sqrt(((rr >= 42) & (rr < 58)).sum()) / (np.mean(cam(st)[1][(rr >= 42) & (rr < 58)]) + 1e-9)), 3))
# star size, whole field and near the nebula, stack against the reference frame alone (green, half-flux diameter)
BLK = 64; bh, bw = h2 // BLK, w2 // BLK
def flat(G):
    G = np.where(ok, np.nan_to_num(G), 0).astype(np.float32)
    b = np.median(G[:bh * BLK, :bw * BLK].reshape(bh, BLK, bw, BLK), axis=(1, 3)).astype(np.float32)
    return G - cv2.resize(cv2.medianBlur(b, 3), (w2, h2), interpolation=cv2.INTER_LINEAR)
Dst, Dsg = flat((st[1] + st[2]) / 2), flat((sg[1] + sg[2]) / 2)
sm = cv2.GaussianBlur(Dst, (0, 0), 2.5); m_, s_, _ = clipped_stats(sm[ok][::7])
n_, lab, stats, cent = cv2.connectedComponentsWithStats((sm > m_ + 25 * s_).astype(np.uint8))
hs = []
for i in range(1, n_):
    a_ = measure(Dst, float(cent[i][0]), float(cent[i][1])); b_ = measure(Dsg, float(cent[i][0]), float(cent[i][1]))
    if a_ is None or b_ is None or a_['peak'] > 3000 or a_['flux'] < 15000: continue
    hs.append((a_['x'], a_['y'], 2 * a_['hfr'], 2 * b_['hfr'], a_['elong'], b_['elong']))
hs = np.array(hs); dc = np.hypot(hs[:, 0] - pc[0], hs[:, 1] - pc[1]); near = dc < 700
stars = dict(stars=int(len(hs)), units='half-flux diameter in stack px (%.3f arcsec)' % SCALE,
             whole_field=dict(stack_px=round(float(np.median(hs[:, 2])), 2), single_px=round(float(np.median(hs[:, 3])), 2), stack_arcsec=round(float(np.median(hs[:, 2]) * SCALE), 2), single_arcsec=round(float(np.median(hs[:, 3]) * SCALE), 2),
                              elongation_stack=round(float(np.median(hs[:, 4])), 3), elongation_single=round(float(np.median(hs[:, 5])), 3)),
             within_700px_of_M57=dict(n=int(near.sum()), stack_px=round(float(np.median(hs[near, 2])), 2), single_px=round(float(np.median(hs[near, 3])), 2), stack_arcsec=round(float(np.median(hs[near, 2]) * SCALE), 2), single_arcsec=round(float(np.median(hs[near, 3]) * SCALE), 2)),
             note='the single frame is the reference frame, the sharpest of the run (5.5 arcsec); the stack averages frames of 5.8 to 6.5 arcsec')
numbers = dict(noise_sky_ring_200_400px=dict(units='DN per stack pixel, white-balanced camera R, G, B, 3-sigma clipped std, stars masked; single = the reference frame (local transparency 1.0) through the same hot-pixel repair and resampling',
                                             single=dict(zip('RGB', [round(v, 2) for v in noise['single']])), stack=dict(zip('RGB', [round(v, 2) for v in noise['stack']])),
                                             improvement=dict(zip('RGB', [round(v, 2) for v in gain])), expected_from_weights=round(float(np.sqrt(sumw)), 2),
                                             half_difference_odd_even=dict(zip('RGB', [round(v, 2) for v in half])), half_difference_note='(odd - even) / 2 has the stack\'s noise if the two halves had equal weight; they do not quite, so it is a rough check'),
               nebula_profile=profile, red_rim_check=rimcheck, star_size=stars)
jsave(numbers, 'step9_numbers.json')
print(json.dumps(dict(noise=numbers['noise_sky_ring_200_400px'], stars=stars, rim=rimcheck), indent=1))

# ---------------- recipe ----------------
f1 = {f['stamp']: f for f in s1['frames']}; q4 = {o['stamp']: o for o in s4['quality']}; t3 = {o['stamp']: o for o in s3['transforms']}
used = {u['stamp']: u for u in s5['used']}; rej = {r['stamp']: r for r in s5['rejected']}
frames = []
for f in s1['all_in_window']:
    s = f['stamp']; a = f1.get(s, {}); q = q4.get(s, {}); t = t3.get(s, {})
    d = dict(file=f['name'], shutter_pressed_utc=f['t'], exposure_s=f['exposure_s'], iso=f['iso'], arw_sha256=f['arw_sha256'],
             sidecar=dict(settling=f['settling'], cloud_flag=f['cloud_flag'], box_transparency=f['box_transparency'], since_slew_s=f['since_slew_s']),
             used=s in used, why_dropped=rej[s]['why'] if s in rej else None,
             black_level=a.get('black'), white_balance_as_shot=a.get('wb_as_shot'), pixels_at_sensor_ceiling=a.get('pixels_at_ceiling'), transient_spikes_replaced=a.get('transient_spikes_replaced'),
             sky_provisional_dn=dict(zip(PLANE_NAMES, [round(b['clipped_mean'], 2) for b in a.get('bg_provisional', [])])),
             pixel_noise_dn=dict(zip(PLANE_NAMES, [round(v, 2) for v in q.get('pixel_noise_dn', [])])),
             stars_found=q.get('stars_detected'), transparency_field=round(q['transparency'], 4) if q else None, transparency_tilt_per_3000px=[round(v, 3) for v in q.get('tilt_per_3000px', [])],
             local_transparency=round(s5['local_transparency'][s], 4) if s in s5['local_transparency'] else None,
             half_flux_diameter_arcsec=round(q['hfd_arcsec'], 2) if q else None, elongation_median=round(q['elong_median'], 3) if q else None, common_ellipticity=round(q['coherent_ellipticity'], 3) if q else None,
             registration=dict(rotation_deg=round(t['rotation_deg'], 4), shift_at_frame_centre_px=[round(v, 2) for v in t['shift_at_centre_px']], stars_matched=t['matched'], rigid_wrms_px=round(t['wrms_px'], 3),
                               model=t['model'], model_stars=t['model_used'], model_wrms_px=round(t['model_wrms_px'], 3) if t['model_wrms_px'] else None, scale_if_left_free=round(t['similarity_scale'], 5),
                               cx=t['cx'], cy=t['cy']) if t and not t.get('failed') else dict(failed=True))
    if s in used:
        u = used[s]; d.update(weight=round(u['weight'], 4), scale_applied=round(u['scale'], 4), sky_constant_dn_after_scaling=s6['constants_dn'][s])
    frames.append(d)
rot = [t3[s]['rotation_deg'] for s in sorted(t3)]
TL = s5['local_transparency']; drop_s = sorted(rej); use_s = sorted(used)
t_drop = [min(TL[s] for s in drop_s), max(TL[s] for s in drop_s)] if drop_s else None; t_use = [min(TL[s] for s in use_s), max(TL[s] for s in use_s)]
hms = lambda s: '%s:%s:%s' % (s[9:11], s[11:13], s[13:15])
drop_window = '%s to %s UTC' % (hms(drop_s[0]), hms(drop_s[-1])) if drop_s else 'none'
contiguous = drop_s == [s for s in sorted(TL) if drop_s[0] <= s <= drop_s[-1]] if drop_s else True
shifts = np.array([t3[s]['shift_at_centre_px'] for s in sorted(t3)]); drift_px = float(np.hypot(*(shifts.max(0) - shifts.min(0))))
co_ = s6.get('colour_offsets', {}).get('applied_px', {}); disp = [float(np.hypot(*co_.get('R', [0, 0]))), float(np.hypot(*co_.get('B', [0, 0])))]
recipe = dict(
    what='M57, the Ring Nebula: %d of 33 frames of 15 s at ISO 3200 (Sony a6000 on a Celestron 8SE, EQ6-R tracking), stacked from RAW colour planes, weighted by transparency' % N,
    made_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
    owner='Brad Gessler',
    tools=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__, opencv=cv2.__version__, rawpy=rawpy.__version__, libraw='.'.join(map(str, rawpy.libraw_version)), tifffile=tifffile.__version__, pillow=PIL.__version__,
               astrometry_net=subprocess.run(['solve-field', '--version'], capture_output=True, text=True).stdout.strip(),
               note='deterministic array arithmetic only: averages, medians, fitted straight lines and planes, Gaussian filters, an arcsinh curve. Nothing generative, learned or predictive. No deconvolution in this picture.'),
    scripts='hack/stacks/2026-10-08/m57/ in the observatory repository: run_all.sh runs common.py, step1_hot.py ... step9_deliver.py, finish.py (the finish-pictures tool, reading 16-bit), skycheck.py, fitsmin.py',
    source=dict(folder=STILLS, window=[T0, T1], frames_in_window=len(s1['all_in_window']), frames_used=N, frames_dropped=len(s1['all_in_window']) - N, originals='read in place, never modified',
                no_darks_no_flats='none were taken this night: hot pixels come from the run itself; vignetting and dust are not corrected'),
    frames=frames,
    selection=dict(rule=s5['limits'], how='local transparency = median flux ratio of the 16 stars within 1200 px of the nebula against their own run median, scaled so the clearest frame is 1; weight = (local transparency / relative green noise)^2; each used frame multiplied by 1 / local transparency',
                   sum_of_weights=round(sumw, 3), clearest_frame=s5['clearest'], result='%d used, %d dropped, all for cloud (stars near the nebula below 50%% of the clearest frame), %s%s' % (N, 33 - N, drop_window, ', one run' if contiguous else ', not one run')),
    steps=[
        dict(step='read', detail='rawpy raw_image_visible (6024 x 4024, RGGB), black level 512 subtracted; four colour planes R, G1, G2, B kept apart at 3012 x 2012; no demosaic'),
        dict(step='hot pixels', detail='from the run itself: per-plane median of all 33 frames without registration (stars and nebula move about 190 sensor px over the run, more towards the corners as the field turns); above its 5 x 5 median by max(3.5 sigma, 25% of the level) = hot, below by 5 sigma = cold; per frame, spikes above the 3 x 3 median by 8 sigma + 50% of the level; all replaced by the 3 x 3 median of the same plane', per_plane=s1['hot']),
        dict(step='stars', detail='green planes averaged, smooth background (64 px block medians) taken off, Gaussian sigma 2.5, 6 sigma, Gaussian-windowed centroids, 14 plane-px aperture'),
        dict(step='register', detail='reference %s (most stars). Pairing by a rotation + offset vote, then weighted least squares on matched stars: rigid (rotation + shift) for the record, and for resampling a 2nd-order polynomial (50+ stars), affine (20-49) or rigid (<20): the rigid fit left a smooth 1 px pattern that changes frame to frame' % s3['reference'],
             rotation_deg=dict(min=round(min(rot), 4), max=round(max(rot), 4), span=round(max(rot) - min(rot), 4)), drift='the field drifted %.0f stack px (%.0f arcsec, sensor px = half a stack px) over the 19 minutes, mostly along the sensor\'s y' % (drift_px / 2, drift_px / 2 * SCALE)),
        dict(step='quality and selection', detail='see selection; star width, elongation and trailing were within limits for every frame that passed the transparency test'),
        dict(step='resample', detail='each plane of each used frame read straight onto the reference frame\'s grid of colour cells (one output pixel per 2 x 2 cell, %.3f arcsec), Lanczos-4, with the plane\'s own place in the cell; no enlargement' % SCALE),
        dict(step='sky', detail='one constant per colour per frame: the 3-sigma clipped mean of the resampled, scaled frame in a ring 220-700 px around the nebula, stars masked. No surface fitted in the stack', ring=s6['sky']),
        dict(step='combine', detail='per pixel and plane: 3-sigma clip about the median (sigma = 1.4826 MAD, floor 0.4 x the single-frame noise, widened by each frame\'s noise factor), again about the weighted mean, then the weighted mean', planes=s6['planes']),
        dict(step='atmospheric dispersion', detail='in the stack red and blue star images sat %.2f and %.2f px from green' % tuple(disp) + ' (along the vertical: the air is a prism at 35-39 degrees altitude); red and blue were resampled again with that offset folded into the same single interpolation', offsets=s6.get('colour_offsets')),
        dict(step='plate solve', detail='astrometry.net solve-field on the stack\'s stars (2MASS and Tycho-2 index files), then this pipeline\'s own centroids on the matched catalogue stars, straight-line fit', result={k: s7[k] for k in ('matched_with_own_centroid', 'used_in_fit', 'fit_rms_arcsec', 'scale_arcsec_per_px', 'scale_arcsec_per_sensor_px', 'focal_length_mm', 'parity', 'north_is_deg_clockwise_from_up', 'stack_centre_ra_dec', 'm57_catalogue', 'm57_light_centroid')}),
        dict(step='picture', detail='step 8 (see its docstring): crop centred on the catalogue position, a quarter turn, sky plane per colour fitted outside 200 px of the nebula, camera colour matrix, luminance at Gaussian 1 px and colour at 3.5 px, arcsinh stretch; then finish.py (levels and quiet sky), then skycheck.py', render=s8,
             finish=dict(arguments=FINISH, recipe=fin), skycheck=open(W_('skycheck.txt')).read().strip() if os.path.exists(W_('skycheck.txt')) else None),
    ],
    numbers=numbers,
    outputs={'m57-stack.tif': dict(what='the stack, linear, 16-bit RGB, R = red plane, G = mean of the two green planes, B = blue plane, each times the camera\'s daylight white balance; no colour matrix, no sky plane, no stretch', **s8['tif'],
                                   pixel_scale_arcsec=SCALE, orientation='the reference frame\'s sensor (rawpy raw_image_visible, not turned); north is %.1f deg clockwise from up' % s7['north_is_deg_clockwise_from_up'],
                                   sky_map='step 7: (xi, eta) arcsec about RA %.4f Dec %.4f = affine of ((x + %d - %d) / 1000, (y + %d - %d) / 1000) with x, y TIF pixels' % (TARGET['ra_deg'], TARGET['dec_deg'], s8['tif']['area_stack_px']['x0'], w2 // 2, s8['tif']['area_stack_px']['y0'], h2 // 2), sky_map_coefficients=s7['affine_xi_eta_arcsec']),
             'm57.jpg': dict(**out_files['m57.jpg'], pixel_scale_arcsec=SCALE, field_arcmin=[round(pic.shape[1] * SCALE / 60, 2), round(pic.shape[0] * SCALE / 60, 2)], enlarged=False,
                             orientation='north is %.1f deg clockwise from straight up, east %.1f deg counter-clockwise from up (normal parity, as the sky looks); turned from the sensor by whole quarter turns only' % (s8['north_deg_clockwise_from_up_after'], -s8['east_deg_clockwise_from_up_after']),
                             m57_catalogue_position_px=s8['m57_catalogue_in_picture_px']),
             'm57-single-vs-stack.jpg': dict(**out_files['m57-single-vs-stack.jpg'], what='left: the reference frame %s alone (15 s), right: the stack; both through exactly the same steps and numbers' % s3['reference'])},
    deconvolved_version=None,
    caveats=[
        'Thin cloud came and went: %d of the 33 frames (%s) had the stars near the nebula at %.0f to %.0f percent of the clearest frame and were dropped; the %d used ones were at %.0f to %.0f percent and are weighted by the square of it, worth %.1f clear frames together. The cloud was patchy (star brightness changed by up to 80 percent across one frame) and the sky got darker under it, not brighter.' % (len(drop_s), drop_window, 100 * t_drop[0], 100 * t_drop[1], len(use_s), 100 * t_use[0], 100 * t_use[1], sumw),
        'The sky in the stack has a ramp (light pollution, about 50 DN in green across the whole frame, 13 to 16 DN across the picture). The stack keeps it (one constant per colour per frame); the picture takes off one plane per colour fitted to the sky more than 200 px (2.6 arcmin) from the nebula, outside its known halo.',
        'Colour is the camera\'s own: daylight white balance and colour matrix from the RAW, no colour calibration on stars. The light came through about 1.7 airmasses at 35 to 39 degrees altitude, which dims blue: faint stars\' colours are uncertain (their red is measured in one pixel in four) and some come out yellow-green.',
        'No dark frames, no flat field: vignetting and dust shadows are not corrected; hot pixels are repaired as described.',
        'M57\'s faint outer halo (out to about 1.9 arcmin) is not shown: around the ring the light falls to 2 to 5 DN, under the noise after the sky is set black, and the picture keeps the sky quiet instead. The galaxy IC 1296, 4 arcmin from the ring, is detected in the stack (S/N about 7 within 23 arcsec of its centre) but is not visible in the picture for the same reason.',
        'Seeing was 5.5 to 6.5 arcsec (half-flux diameter): the ring\'s inner hole is clear, but finer structure is not resolved.',
    ],
)
if os.path.exists(W_('step10.json')) and os.path.exists(os.path.join(OUT, 'm57-deconvolved.jpg')):
    d10 = jload('step10.json')
    recipe['deconvolved_version'] = dict(file='m57-deconvolved.jpg', label='deconvolved: a separate version beside the plain m57.jpg, not a replacement',
        how='step10_decon.py: Wiener filter on the luminance only, blur = median of %d stars within 800 px of M57 in this stack (half-flux diameter %.2f px), W = conj(H)(1 + NSR)/(|H|^2 + NSR), NSR %.2f, gain capped at %.1f at every frequency; colour, stretch rule and finish.py numbers as the plain picture' % (d10['blur']['stars'], d10['blur']['half_flux_diameter_px'], d10['wiener']['nsr'], d10['wiener']['gain_max']),
        effect=dict(star_half_flux_diameter_px=d10['star_hfd_median_px'], sky_noise_dn=d10['sky_noise_dn'], ring_and_hole=d10['ring_and_hole']),
        verdict='stars about 30% smaller and the ring\'s hole a little darker against the ring; the sky about 40% noisier; a dark ring of at most -4 DN (under 1 sigma) round the brighter stars. NSR 0.02 with gain 3 was tried first and filled the hole with noise blobs; not kept.',
        details=d10, size_px=[int(pic.shape[1]), int(pic.shape[0])], metadata='none (JFIF header only)')
    recipe['tools']['note'] = recipe['tools']['note'].replace('No deconvolution in this picture.', 'No deconvolution in m57.jpg; m57-deconvolved.jpg is the labelled Wiener version.')
json.dump(recipe, open(os.path.join(OUT, 'recipe.json'), 'w'), indent=1)
print('wrote', sorted(out_files), 'and recipe.json to', OUT)
