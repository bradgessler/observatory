"""Step 7a (M42: the long frames, the Trapezium masked MASK_R_PX round its place): the candidate flats on this run's own sky, with .claude/skills/stack-pictures/tools/flatcheck.py, before step 7
measures the dust. M33 fills every frame (70 x 40 arcmin against 39 x 26), so this run's sky is not open sky: the large
scale cannot be judged on it (the galaxy's slope is in every frame) and none is built from it. As the M27 pipeline of
tonight did (its step 7a, 'on_m33_sky'), M33's bright middle is masked as a circle of MASK_R_PX plane px round each
frame's own centre and the dithered frames' sky is used for the small scale (dust), where the sky moved under the
dithers. The candidates: hybrid13 (13 October: large scale from that night's open sky, dust from its twilight flats;
scored best on M27's open sky tonight) and twilight13 (the 13 October twilight flats as measured). Written to
work/step7a_flats.json."""
import os, numpy as np
from common import *
import flatcheck as fc, twilight_flat as tf

MASK_R_PX = float(os.environ.get('M42_FLATCHECK_MASK_R', '700'))
EVERY = int(os.environ.get('M42_FLATCHECK_EVERY', '2'))

if __name__ == '__main__':
    sel = jload('step5_select.json'); s1 = {f['stamp']: f for f in jload('step1.json')['frames']}
    frames = [path_of(u['stamp']) for u in sel['used'] if u['kind'] == 'long'][::EVERY]
    obj = [dict(centre_px=jload('step6_solve_ref.json')['galaxy_ellipse']['centre_px'], semi_major_px=MASK_R_PX, semi_minor_px=MASK_R_PX, major_axis_angle_deg=0.0)]   # round the Trapezium's place in the reference (the dithers move it by up to 116 px)
    print('flatcheck on %d dithered long frames (every %d), M42 masked %.0f px round the Trapezium' % (len(frames), EVERY, MASK_R_PX), flush=True)
    sky = fc.own_sky(frames, obj, 60.0, WORKERS)
    flats = {n: tf.load(FLAT_DIRS[n]) for n in ('hybrid13', 'twilight13')}
    res = dict(frames=sky['frames'], mask=obj, sky_level_dn=dict(zip(PLANE_NAMES, np.median(sky['levels'], 0).round(2).tolist())), masked_fraction_median=float(np.median(sky['masked'])),
               on_m42_sky=[fc.against(sky, F, n) for n, F in flats.items()],
               caveat='the large-scale numbers include the nebula\'s own light outside the mask (M42\'s glow fills the frame); only the small scale (dust) is a fair test here')
    for r in res['on_m42_sky']:
        g = r['large']['G1']; s = r['small']
        print('%-10s large (G1, nebula included): after plane %.4f | dust: %d shadows left (%d deeper than 2%%, deepest %.3f), correlation %.2f, shift %s | depth sky/flat %s' % (
            r['flat'], g['robust_rms_after_plane'], s['shadows_left'], s['deeper_than_2pct'], s['deepest'], s['dust_correlation'], s['shift_flat_to_sky_plane_px'],
            {k: v['depth_in_sky_over_depth_in_flat'] for k, v in r['per_colour_slope'].items()}), flush=True)
        for w_ in s['worst'][:8]: print('     left: plane px (%.0f, %.0f) = sensor (%.0f, %.0f), %.3f deep, r %.0f px' % (*w_['plane_px'], 2 * w_['plane_px'][0], 2 * w_['plane_px'][1], w_['depth'], w_['radius_plane_px']), flush=True)
    fc.picture(sky, flats, W('v_flatcheck_m42sky.png'))
    jdump(res, 'step7a_flats.json')
