"""Step 7 (calibrated): the flat, chosen by N891_FLAT, and checked against this run's own open sky.

  hybrid (default)  <night>/flat-hybrid-ngc891/flat_planes.npz, made by .claude/skills/stack-pictures/tools/skyflat.py:
                    the large scale from the night's own open sky of the M77, NGC 2261, NGC 2419 and M1 runs (this run
                    left out, so nothing of NGC 891's own faint light can be in its flat), the small scale (dust and
                    pixel response) from the twilight flats of 13 October 14:03 to 14:14 UTC (twilight_flat.py).
  twilight          <night>/flat-twilight/flat_planes.npz as measured (its large scale is the dawn optics': a test only).
  night             the original step 7 (step7_flat_night.py): the flat built from this run's own sky, as published.
                    It writes into the work folder (FLAT_DIR), never into <night>/flat/. The control.

The check (flatcheck.py, "check the flat against the hour"): this run's frames, stars and the galaxy's generous ellipse
(grown by the field's wander) left out, normalised, 32 px block means and the median over the frames; then what the
flat leaves on that sky: large-scale remainder (rms, rings, sides, after a plane), dust shadows left, the dust's
depth per colour against the flat's. The night's flat (<night>/flat/, as it was used by the other targets) is checked
beside it for the comparison. Nothing is changed by the check.

Writes work/flat.npy (4, 2012, 3012) float32 for step 8 and work/step7_flat.json."""
import json, os, runpy, sys
import numpy as np
from common import *

if __name__ == '__main__':
    if FLAT_SOURCE == 'night':
        sys.argv = [os.path.join(SCR, 'step7_flat_night.py')]
        runpy.run_path(sys.argv[0], run_name='__main__')
        raise SystemExit(0)
    import twilight_flat, flatcheck
    src = FLAT_SOURCES[FLAT_SOURCE]
    F = twilight_flat.load(src)
    assert F.shape == (4, h2, w2), F.shape
    np.save(W('flat.npy'), F)
    fj = json.load(open(os.path.join(src, 'flat.json')))
    sel = jload('step5_select.json'); frames = [path_of(u['stamp']) for u in sel['used']]
    ELL = jload('step6_solve_ref.json')['galaxy_ellipse']
    sky = flatcheck.own_sky(frames, [ELL], grow=60.0, workers=WORKERS)
    night = twilight_flat.load(os.path.join(NIGHT, 'flat'))
    checks = [flatcheck.against(sky, F, FLAT_SOURCE), flatcheck.against(sky, night, 'the night\'s flat (<night>/flat, as published)')]
    for r in checks:
        print('== %s' % r['flat'])
        for k, v in r['large'].items():
            print('  %-2s large: rms %.4f (1-99%% %.3f..%.3f); after a plane rms %.4f; rings %s' % (k, v['robust_rms'], *v['range_1_99_pct'], v['robust_rms_after_plane'], ' '.join('%.3f' % x['after_plane'] if x['after_plane'] else '-' for x in v['rings'])))
        s = r['small']
        print('  small: %d shadows left below %.3f (%d deeper than 2%%, deepest %.3f); dust depth here / in the flat per colour %s' % (s['shadows_left'], s['threshold'], s['deeper_than_2pct'], s['deepest'], {k: v['depth_in_sky_over_depth_in_flat'] for k, v in r['per_colour_slope'].items()}), flush=True)
    flatcheck.picture(sky, {FLAT_SOURCE: F, 'night': night}, W('v_flat_check.png'))
    jdump(dict(flat_source=FLAT_SOURCE, flat_dir=src, flat_made_from=fj['made_from'] if 'made_from' in fj else None, flat_large_scale=fj.get('large_scale'), flat_small_scale_from=fj.get('small_scale_from'),
               flat_dust=dict((k, v) for k, v in fj.get('dust', {}).items() if k != 'shadows'), flat_range={PLANE_NAMES[p]: [float(F[p].min()), float(F[p].max())] for p in range(4)},
               check=dict(frames=sky['frames'], galaxy_ellipse_grown_px=60.0, sky_level_dn=dict(zip(PLANE_NAMES, np.median(sky['levels'], 0).round(2).tolist())), results=checks)), 'step7_flat.json')
