"""Step 14c: the plain-words part of the recipe: what in the pictures is nebula, what is glare, what is a
calibration artefact; what not to trust; what more data would help most; what each delivered picture shows.
The sentences were written after looking at every delivered picture; the numbers in them are read from the
work files of the steps, so they follow the data if the pipeline is run again. Nothing here changes a picture."""
import json, os
import numpy as np
from common import *

L = lambda n: json.load(open(W(n)))
SEL = L('s5_select.json'); FL = L('s6_flat.json'); HDR = L('s9_hdr.json'); PL = L('s10_place.json'); BG = L('s12_background.json'); S13 = L('s13_mosaic.json'); D14 = L('s14_deliver.json'); SW = L('s9c_starwidth.json')
S7 = {k: L('s7_%s.json' % k) for k in SEL}
SH = L('sharpen_report.json') if os.path.exists(W('sharpen_report.json')) else {}
tw = FL['source'].startswith('twilight'); hybrid = 'cloud flat' in FL['source']
Z = S13['zero_taken_off_dn']; dz = S13['darkest_part_of_the_centred_stack_alone']['above_the_mosaic_zero_dn']
wbR, wbB = D14['white_balance']['as_shot']['R'], D14['white_balance']['as_shot']['B']
import cv2 as _cv2
NWHITE = _cv2.connectedComponents(((np.load(W('short_clip.npy')) > 0) & (np.load(W('hdr_w.npy')) > 0)).astype(np.uint8), connectivity=8)[0] - 1
nd = S7['deep']['noise_of_stack_dn_per_half_grid_px']; nG = float(np.hypot(nd['G1'], nd['G2']) / 2)
m42 = D14['outputs']['m42.png / .jpg']; mos = D14['outputs']['m42-mosaic.png / .jpg']; core = D14['outputs']['m42-core.png / .jpg']
used = {k: len(SEL[k]['used']) for k in SEL}
mult = PL['photometric_multipliers']['G']
bgB = {c: BG[c]['B_constants_and_planes'] for c in 'RGB'}
near = {k: v.get('near_the_core_median') for k, v in bgB['G']['overlaps'].items() if k.startswith('deep-')}
diag = D14['outputs']['m42-mosaic-diagnostic.png']['difference_in_overlaps_dn']
R11 = L('s11_resample.json'); R11_noise = lambda k: R11[k]['noise_green_per_mosaic_px_deep_units']['median']
# the hair's patch in the centred picture: where fewer than half of the deep frames reach, inside the crop
import cv2
from PIL import Image
n_ = np.load(W('deep_n.npy')); cx0, cy0, cx1, cy1 = m42['crop_of_stack_grid_px']; nc = n_[cy0:cy1, cx0:cx1]
thin = (nc < 0.5 * nc.max()); thin[:, :40] = False; thin[:, -40:] = False; thin[-40:] = False
nl_, lab_, st_, ce_ = cv2.connectedComponentsWithStats(thin.astype(np.uint8), connectivity=8)
hp = max(range(1, nl_), key=lambda i: st_[i, 4]) if nl_ > 1 else None
HAIRP = dict(x=int(st_[hp, 0]), y=int(st_[hp, 1]), w=int(st_[hp, 2]), h=int(st_[hp, 3]), frames=int(np.median(nc[lab_ == hp])), noisier=float(np.sqrt(nc.max() / max(np.median(nc[lab_ == hp]), 1)))) if hp else dict(x=0, y=0, w=0, h=0, frames=int(nc.max()), noisier=1.0)
# the brightest nebula of the core in the delivered picture (8 bit), stars left out by a 15 px median
try:
    im_ = np.array(Image.open(os.path.join(D14['destination'], 'm42.png')))
    core8 = cv2.medianBlur(im_[620:1220, 1080:1680].max(2), 15); CORE_TOP = float(np.percentile(core8, 99.5)) / 255
except Exception:
    CORE_TOP = float('nan')
# the lowest ground of the mosaic: 192 px block medians of green, zero taken off
import warnings
mg = np.load(W('mosaic_rgb.npy'), mmap_mode='r')[:, :, 1]; BSn = 192; ny_, nx_ = mg.shape[0] // BSn, mg.shape[1] // BSn
with warnings.catch_warnings():
    warnings.simplefilter('ignore'); bmed = np.nanmedian(np.asarray(mg[:ny_ * BSn, :nx_ * BSn]).reshape(ny_, BSn, nx_, BSn).transpose(0, 2, 1, 3).reshape(ny_, nx_, -1), axis=2)
cpm_ = np.load(W('mosaic_cp.npy'), mmap_mode='r'); cpb = np.asarray(cpm_[:ny_ * BSn, :nx_ * BSn]).reshape(ny_, BSn, nx_, BSn).max((1, 3))
bmed = np.where(cpb < 80, bmed, np.nan)          # only where the deep stack and the clear panels carry the weight
iy_, ix_ = np.unravel_index(np.nanargmin(bmed), bmed.shape); X0_, Y0_ = PL['grid']['trapezium_pixel']
mrgb = np.load(W('mosaic_rgb.npy'), mmap_mode='r'); LOWRGB = [float(np.nanmedian(np.asarray(mrgb[iy_ * BSn:(iy_ + 1) * BSn, ix_ * BSn:(ix_ + 1) * BSn, c]))) for c in range(3)]
LOW = dict(dn=float(bmed[iy_, ix_]), east_arcmin=float((X0_ - (ix_ + 0.5) * BSn) * HS / 60), north_arcmin=float((Y0_ - (iy_ + 0.5) * BSn) * HS / 60), blocks_below_minus_3=int((bmed < -3).sum()))
second = [q for q in SEL['deep']['quality'] if q['stamp'][9:] >= '124000']; second_used = [u for u in SEL['deep']['used'] if u['stamp'][9:] >= '124000']
bmin, bmax = min(HDR['offsets_b_dn'].values()), max(HDR['offsets_b_dn'].values())
def side(e, n): return ('%.0f arcmin %s and %.0f arcmin %s of the Trapezium' % (abs(e), 'east' if e > 0 else 'west', abs(n), 'north' if n > 0 else 'south'))

FC = L('s12b_flatcheck.json') if os.path.exists(W('s12b_flatcheck.json')) else None
CL = dict(place=L('s10_place_cloud.json'), bg=L('s12_background_cloud.json')) if os.path.exists(W('s10_place_cloud.json')) else None
TW = dict(place=L('s10_place_twilight.json'), bg=L('s12_background_twilight.json'), chk=L('s12b_flatcheck_twilight.json')) if os.path.exists(W('s12b_flatcheck_twilight.json')) else None
if tw:
    ac = FL['against_cloud_flat']; dr = FL['first_third_over_last_third']
    mins = round((tsec('2026-10-04T' + FL['last'][9:11] + ':' + FL['last'][11:13] + ':00Z') - tsec('2026-10-04T' + FL['first'][9:11] + ':' + FL['first'][11:13] + ':00Z')) / 60)
    flat_words = 'this morning\'s twilight sky flats (%d frames, %s to %s UTC, %s s at ISO %s): every dust shadow, the edge shading and the pixel response as they were at dawn; the hair\'s place in the flats (top edge) replaced by the flat\'s smooth part' % (
        FL['frames_used'], FL['first'][9:13], FL['last'][9:13], ' to '.join('%g' % v for v in (max(FL['exposures_s']), min(FL['exposures_s']))), ' to '.join(str(v) for v in (min(FL['isos']), max(FL['isos']))))
    differ = 'at the corners the twilight flat is %.1f%% (green), %.1f%% (red) and %.1f%% (blue) brighter than tonight\'s cloud-glow flat, and it is tilted against it by %.1f%% per 3000 px in x and %.1f%% in y; its own tilt changed by about %.1f%% during the %d minutes the flats took' % (
        100 * (ac['G1']['by_radius_400px_rings'][-1] - 1), 100 * (ac['R']['by_radius_400px_rings'][-1] - 1), 100 * (ac['B']['by_radius_400px_rings'][-1] - 1), 100 * abs(ac['G1']['tilt_per_3000px_x_y'][0]), 100 * abs(ac['G1']['tilt_per_3000px_x_y'][1]),
        100 * max(abs(dr['top_over_bottom'] - 1), abs(dr['left_over_right'] - 1)), mins)
    if hybrid:
        flat_words += '. Its LARGE-SCALE shape (vignetting and tilt, everything wider than about 300 px) was replaced by that of tonight\'s cloud-glow flat'
        flat_trust = 'The flat\'s large-scale shape, to about 2% (3.5% in red at the corners). Everything was made three times: with the cloud flat, with the twilight flat as it is, and with the twilight flat carrying the cloud flat\'s large-scale shape (the delivered one). The twilight and cloud flats agree at the centre and part toward the edges: ' + differ + '. '
        if TW and FC:
            flat_trust += ('With the twilight flat as it is, the same sky seen through different parts of the sensor did not agree: the clear panels needed tilts of up to %.0f DN per 1000 px against the centre, the overlaps fitted a term that had not come through the optics (%+.0f DN red, %+.0f green, %+.0f blue in the centred stack), and the far ends of the panels fell 5 to 20 DN below the zero. With the delivered flat the clear stacks agree with constants alone to %.1f DN (green; %.1f with the twilight shape) and that term is gone (%+.0f, %+.0f, %+.0f). ' % (
                max(abs(t) for k in ('p00', 'p10', 'stray1') for t in TW['bg']['G']['B_constants_and_planes']['parameters'][k]['terms'][1:]), TW['chk']['R']['pedestal_per_stack_dn']['deep']['d'], TW['chk']['G']['pedestal_per_stack_dn']['deep']['d'], TW['chk']['B']['pedestal_per_stack_dn']['deep']['d'],
                FC['G']['rms_dn']['constants_only'], TW['chk']['G']['rms_dn']['constants_only'], FC['R']['pedestal_per_stack_dn']['deep']['d'], FC['G']['pedestal_per_stack_dn']['deep']['d'], FC['B']['pedestal_per_stack_dn']['deep']['d']))
            flat_trust += 'A twilight sky lights the whole hemisphere and some of that light reaches the sensor round the imaging path, which fills a flat\'s corners; that is the likely reason, not a proven one. Against it: the stars of the right-hand panel agree better with the centre under the twilight shape (%.1f%% off) than under the delivered one (%.1f%%). So the BRIGHTNESS of the nebula toward the corners of any frame is uncertain by those 2 to 3%%; the faint ground is consistent to 1 to 2 DN where clear stacks overlap.' % (100 * abs(TW['place']['photometric_multipliers']['G']['p10'] - 1), 100 * abs(mult['p10'] - 1))
    else:
        flat_trust = 'The flat\'s large-scale shape: ' + differ + '.'
else:
    flat_words = 'the CLOUD flat of tonight\'s M31 run (0736 to 0846 UTC, three to five hours before these frames): the twilight flats had not arrived when this was calibrated'
    flat_trust = 'The flat. The cloud flat is three to five hours older than these frames. Its smooth part (vignetting, tilt) rests on the cloud\'s glow having been even; its dust map shows the dust where it was then. Shadows that moved or came since are not corrected: on the bright nebula a 3 to 6% ring is 10 to 200 DN. None stands out in the pictures, but faint rings and smudges a few tens of pixels wide, above all in the outer panels of the mosaic, should not be read as nebula.'

what_is_what = dict(
    nebula=[
        'The bright fan round the Trapezium (the Huygens region), blue-white in these pictures: oxygen and hydrogen-beta light in green and blue, hydrogen-alpha in red. A stock camera passes only part of the red line, so the eye-true balance would be pinker; nothing was done to make up for that.',
        'The pink ridge below the Trapezium (the Orion Bar) and the pink wings and loops to the right and below it: hydrogen-alpha where the oxygen light is weak. They are 100 to 400 DN above the zero against a pixel noise of %.0f DN in green: solid.' % nG,
        'M43, the round patch upper left of the core with a dark lane across it, round the star NU Orionis; the dark bay that cuts in from the left to the Trapezium (the Fish\'s Mouth) and the dark cloud left of it: dust in front of the nebula, real.',
        'The mottled texture below the Bar: real. The stray group\'s stack, taken with the field 1500 px elsewhere on the sensor, shows the same pattern at the same place on the sky.',
        'The four Trapezium stars, separate, and the structure of the core between and round them: from the 2 s frames, where the 20 s frames were at the ceiling.',
        'The grey ground of the whole field, %.0f DN (green) above the zero even at its darkest inside the centred picture: the outer glow of the nebula and of the Orion cloud. It is there (the wider mosaic finds darker sky to the north-north-west), but how much of it is sky and how much nebula cannot be told from these frames.' % dz['G'],
    ],
    glare=[
        'Round every bright star a soft glow several star-widths wide (clearest round the star lower right of centre and round the three bright stars below the Bar): light scattered in the telescope and the air, not nebula. The blue cast of those glows is the stars\' own colour.',
        'The stars are teardrops with a short tail toward the upper left: collimation. It is in every frame and in the stack; it is not motion.',
        'In the mosaic, the two panels taken through thin cloud (the lower one and the left one) carry core light scattered by the cloud: against the deep stack they read %s DN (green) bright within 6 arcmin of the Trapezium. Where the deep stack lies it outweighs them %.0f to %.0f times; just outside its edge on those two sides the ground is a little too bright.' % (' and '.join('%+.0f' % -near[k] for k in ('deep-p01', 'deep-p11') if near.get(k) is not None), (R11_noise('p11') / R11_noise('deep')) ** 2, (R11_noise('p01') / R11_noise('deep')) ** 2),
    ],
    calibration_artefacts=[
        'Flat field: every frame was divided by ' + flat_words + '.' + (' About 200 dust shadows, 3 to 6% deep, and several hundred fainter ones are in that flat and are divided out; I can find none in the pictures.' if tw else ''),
        ('The hair on the sensor sat near the top edge, a little right of centre, and crept by about 90 sensor px during the two hours. It was found in each frame and cut out. In the centred picture its place (about %d x %d px at the top edge, from x = %d of m42.png) is filled by the frames of the shifted groups only, about %d frames instead of %d: the patch is %.1f times noisier and was smoothed more. In the mosaic two notches in the upper edge are the hair\'s holes in the panels that nothing else covers.' % (HAIRP['w'], HAIRP['h'], HAIRP['x'], HAIRP['frames'], int(nc.max()), HAIRP['noisier'])),
        'Panel seams in the mosaic: after one constant and one plane per panel and colour, the stacks differ in their overlaps by %.1f DN (green, median; %.0f DN at the 90th percentile; the large values are star cores and the core\'s cloud halo). Seams of that size are in the mosaic\'s faint ground.' % (diag['median_abs'], diag['p90_abs']),
        'Outside the deep stack a panel\'s background is a plane carried outward from its overlap; for the two clouded panels (left and lower) that plane is steep (up to %.0f DN across the panel in green) and their far ends can be off by 5 to 10 DN.' % (2 * max(abs(v) for k in ('p01', 'p11') for v in bgB['G']['parameters'][k]['surface_min_max_over_the_panel_dn'])),
        'The right-hand panel (clear sky, 12 frames, tied to the centre by a constant and an almost level plane) falls smoothly westward to %+.0f DN (green) against the zero at its far end, %s; in the white-balanced colours that is %+.0f, %+.0f, %+.0f DN in R, G, B: the same in all three. So this is most likely real, darker sky away from the nebula, and it says that the region where the zero was taken still holds about %.0f DN of grey light (outer nebula, or the core\'s light scattered in the air and the telescope). The mosaic picture uses a pedestal of 14 DN so that this part is not cut to black.' % (
            LOW['dn'], side(LOW['east_arcmin'], LOW['north_arcmin']), LOWRGB[0] * wbR, LOWRGB[1], LOWRGB[2] * wbB, -LOW['dn']),
        'The zero is one constant per colour (R %.1f, G %.1f, B %.1f DN of the camera planes): the darkest part of the mosaic that at least two clear stacks cover, which is thereby black and grey by construction. No plane and no surface was taken off anything but the panels (each against the centre).' % (Z['R'], Z['G'], Z['B']),
        'Star cores marked white (%d px in the centred picture, in %d stars: the four of the Trapezium, the two bright theta-2 stars below the Bar and the star of M43) were at the ceiling even in 2 s: their values are lower limits and their colour is not known, so they are shown white.' % (HDR['pixels']['white_marked'], NWHITE),
        'Replaced star cores: in the %d places where a long frame came within 7%% of the ceiling the picture holds the short stack, blurred to the long stack\'s star width (not at the Trapezium and the brightest stars). In 2 s the air spreads a star\'s colours by about an arcsecond (the target was 43 degrees up), so those cores can be a little bluer or greener than the star round them; the colour of a bright star\'s very centre is not to be read.' % HDR['regions_with_short_share_above_half'],
    ])

do_not_trust = [
    'The zero, and with it the faintest glow. The nebula and the Orion cloud fill the field; the pictures show brightness above the darkest part of the mosaic that two clear stacks cover (north-north-west of M43), where the moonlit sky, a camera offset (the short-to-deep fit leaves %.0f DN or more per plane in the long frames that the short ones do not have) and whatever nebula there is were all taken off together. The clear panel to the west reads %.0f DN darker still at its far end, so the true sky is at least that much below the zero, and every faint glow in the pictures is at least that much brighter than shown. Anything fainter than about 10 DN above the ground is as likely zero error as nebula.' % (bmin, -LOW['dn']),
    'The HUE of the faint ground. Red is multiplied by %.2f: 2 DN of error in the red zero is 6 DN of pink or green. Below about 25 DN the colour is faded to grey on purpose (colour pedestal); between 25 and 100 DN the pink of the outer wings is probably real (it follows the loops) but its strength is not measured.' % wbR,
    'The white balance itself. It is the camera\'s automatic choice for the 20 s frames (R x %.3f, B x %.3f), and the camera chose differently for the 2 s frames (R x 2.746, B x 1.688) and for the panels: it is a convention, not a measurement. Under it the average field star is orange (R/G %.2f, B/G %.2f). The star-white extra makes those stars neutral; they are reddened young stars of the Orion cluster, so that version errs toward blue. The truth lies between the two.' % (wbR, wbB, D14['star_colour']['colour_of_the_average_star_under_as_shot']['R_over_G'], D14['star_colour']['colour_of_the_average_star_under_as_shot']['B_over_G']),
    flat_trust,
    'The hair\'s patch at the top edge of the centred picture (see above): thin data, smoothed.',
    'The left panel of the mosaic: 2 frames survived the cloud (of 13), taken through cloud that still passed %.0f%% of the light. It is %.0f times noisier than the centre, smoothed hard, shown in grey, and its level is tied to the centre only through a plane. The lower panel: 5 frames of 13, transparency %.0f%%. Treat both as a sketch of what is there.' % (100 / mult['p01'], R11_noise('p01') / R11_noise('deep'), 100 / mult['p11']),
    'The mosaic\'s outer ground in general: the planes of the panel backgrounds are extrapolated beyond the overlaps; smooth differences of 5 to 10 DN between one end of the mosaic and the other are not measured.',
    'Star shapes and the smallest detail: stars are %.1f arcsec across in the deep stack (%.1f in the short one), teardrop-shaped. Nothing finer than that is real, and nothing was sharpened (every sharpening tried drew dark rings round the stars; see sharpening).' % (SW['deep']['half_flux_diameter_arcsec'], SW['short']['half_flux_diameter_arcsec']),
    'Brightness inside the white-marked star cores, and the exact brightness of the brightest few pixels of each Trapezium star: at the ceiling even in 2 s.',
    'Grain round the bright stars: where the short stack takes over (the cores of the %d stars that came within 7%% of the ceiling in a long frame) the pixel noise is about %.0f DN (%.0f at the Trapezium and the brightest stars, where the short stack is left sharp) instead of %.0f; it is hidden by the star\'s own light but it is there in m42-linear.tif.' % (HDR['regions_with_short_share_above_half'], max(HDR['short_stack_rim']['noise_dn_in_deep_units'].values()) / (2 * np.sqrt(np.pi) * HDR['star_width_match']['sigma_applied_px']), max(HDR['short_stack_rim']['noise_dn_in_deep_units'].values()), nG),
]

what_would_help_most = [
    ('Dark frames at 20 s ISO 3200 and at 2 s ISO 800 (cap on, same night): the short-to-deep fit says the long frames carry %.0f to %.0f DN per plane that %.0f x the short frames do not (dark signal of the long frames, or a black level a DN or two off in the short ones). With darks that becomes a measured number instead of part of the zero.' % (bmin, bmax, HDR['factor_applied'])),
    'Empty sky for the zero: a few 20 s frames two degrees off the nebula, taken in between. Without them the true extent of the outer glow cannot be read.',
    'A clear half hour for the mosaic: the left panel has %d frames and the lower one %d, both through cloud; the second deep run lost %d of %d frames to cloud. The same panels under a clear sky, 13 frames each, would make the outer loops as solid as the centre.' % (used['p01'], used['p11'], len(second) - len(second_used), len(second)),
    'Collimation: the teardrop stars cost perhaps a third of the resolution, and the Trapezium region shows it most.',
    'Moving the field on purpose by 300 px or more between groups of frames (it happened here by accident, and it is what filled the hair\'s hole).',
    'Cleaning the sensor: the hair costs a notch in every panel, and about 200 dust shadows rest on the flat being right.',
    'For the colour: a longer-red-pass (modified) camera or a hydrogen-alpha filter. A stock a6000 records a fraction of the red line that makes most of this nebula\'s light.',
    'No Moon and more time: the sky was moonlit (about %.0f DN in green per frame). Longer frames once guiding allows (at 20 s the read noise, 42 DN, is close to the sky\'s shot noise in green and above it in red and blue).' % SEL['deep']['sky_green_clear_median'],
] + ([] if tw else ['The twilight flats: when they are in the stills folder, run_all.sh from step 6 (FLAT=twilight) remakes everything with them in about five minutes.'])

pictures_as_seen = {
    'm42.png': 'The Orion Nebula filling the frame, north up to within 24 degrees, east left. Blue-white core with the four Trapezium stars separate and white, dark mottling and the Bar (pink) below them; M43 upper left with its dark lane; the dark Fish\'s Mouth from the left; grey-blue wings sweeping down to the lower left and up to the upper right; pink veils and a pink loop on the right; a dark, slightly warm-grey ground with orange and white stars. The core is not burnt out: its brightest nebula sits at %.0f%% of white. No hair shadow, no vignetted corners, no dust rings that I can see. Not to be trusted: the hue of the darkest ground, the top-edge patch where the hair was, the glows round the bright stars.' % (100 * CORE_TOP),
    'm42-core.png': 'Six arcmin round the Trapezium at the sensor\'s scale, from the 2 s frames only: four separate white stars (measured separations %s arcsec; the closest pair, A and B, with the light between them falling to %.0f%% of the fainter star\'s peak), the mottled blue-grey core, the dark bay at left, the pink Bar at the bottom with the theta-2 stars. The fifth and sixth Trapezium stars (E and F, 4 arcsec from A and C) are NOT resolved: with stars %.1f arcsec across they are inside their neighbours\' light. The grain is that of 32 seconds of exposure. Stars are teardrops (collimation).' % (', '.join('%.1f' % s_['separation_arcsec'] for s_ in core['trapezium']['separations']), 100 * core['trapezium']['separations'][0]['lowest_between_over_fainter_peak'], SW['short']['half_flux_diameter_arcsec']),
    'm42-mosaic.png': 'The nebula in a wider field, north up, east left, a tilted rectangle of data on black (%.0f%% of the picture has data; %.2f square degrees). The centre is the HDR picture; round it the four panels and the stray group add the ground out to 40 arcmin: darker sky to the north-north-west (where the zero was taken), the star field north toward NGC 1977, faint grey extensions south. The outer parts are shown in grey on purpose. The left third is grainy (2 frames); the ground darkens toward the far right end (probably real: sky farther from the nebula); two notches in the upper edge are the hair. Seams between panels are faint but can be found.' % (100 * mos['fraction_of_picture_with_data'], mos['area_with_data_sq_deg']),
    'm42-starwhite.png': 'The centred picture with the field stars made neutral: stars white to pale, the nebula bluer and cooler, the pink weaker. Same data, same curve.',
    'm42-colour-boost.png': 'The centred picture with every colour pushed away from grey by a factor of %.1f (one global operation): the pink wings and the blue core stand apart clearly, stars are more orange. It is the more striking picture; m42.png is the plain one.' % D14['saturation_boost_of_the_extra'],
    'm42-mosaic-diagnostic.png': 'A map, not a picture: flat colours where one stack alone has data, grey where two overlap (their difference), with dots at the stars and a bright blotch at the core where the clouded panels carry scattered light.',
}
json.dump(dict(what_is_what=what_is_what, do_not_trust=do_not_trust, what_would_help_most=what_would_help_most, pictures_as_seen=pictures_as_seen), open(W('notes.json'), 'w'), indent=1)
print('notes written')
