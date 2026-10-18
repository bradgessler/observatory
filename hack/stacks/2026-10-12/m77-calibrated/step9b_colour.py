"""Step 9b (new): the star colours calibrated against Gaia DR3 (.claude/skills/stack-pictures/tools/star_colour.py).

On the linear stack (step 8's planes, cut to step 9's well-covered rectangle; camera R, mean of G1 and G2, B, times the
camera's daylight white balance as step 10 uses it; sky at zero), with step 9's plate solution of that rectangle: the
per-channel scale (kR, 1, kB) that makes the field's stars, through the camera matrix, the colour Gaia's BP - RP says
(white for the Sun's colour). Stars inside the galaxy's catalogue ellipse (grown 30%, +30 px) are left out. Adapted from hack/stacks/2026-10-12/ngc891-calibrated. The Gaia cone is
cached under ~/.observatory/catalogs/gaia-dr3/ (fetched once from VizieR; the recipe says exactly what).

Writes work/step9b_colour.json; step 10 multiplies R by kR and B by kB on top of the daylight balance when
M77_COLOUR_CAL=1 (the default). With M77_COLOUR_CAL=0 this step still measures (the 'before' numbers) and step 10
leaves the daylight balance."""
import json, os
import numpy as np, rawpy
from common import *
import star_colour
from wcs_tan import TanSip

if __name__ == '__main__':
    s9 = jload('step9_solve.json'); c = s9['crop_on_reference_grid']; x0, y0, x1, y1 = c['x0'], c['y0'], c['x1'], c['y1']
    st = np.load(W('stack_mean.npy'))[:, y0:y1, x0:x1]
    ref = [f for f in jload('step1.json')['frames'] if f['stamp'] == REF_STAMP][0]
    with rawpy.imread(ref['path']) as r:
        rgb_xyz = np.array(r.rgb_xyz_matrix).tolist()
    wbd = np.array(ref['wb_daylight'][:3]); wb = wbd / wbd[1]
    img = np.dstack([st[0] * wb[0], 0.5 * (st[1] + st[2]), st[3] * wb[2]]).astype(np.float32)
    wcs = TanSip(os.path.join(WORK, 'solve', 'stack.wcs'))
    h, w = img.shape[:2]
    e = s9['galaxy_ellipse_catalogue']
    yy, xx = np.mgrid[0:h, 0:w]; t = np.radians(e['major_axis_angle_deg'])
    u = (xx - e['centre_px'][0]) * np.cos(t) + (yy - e['centre_px'][1]) * np.sin(t); v = -(xx - e['centre_px'][0]) * np.sin(t) + (yy - e['centre_px'][1]) * np.cos(t)
    mask = (u / (1.3 * e['semi_major_px'])) ** 2 + (v / (1.3 * e['semi_minor_px'] + 30)) ** 2 <= 1
    ra0, dec0 = wcs.pix2world(w / 2, h / 2)
    radius = 0.5 * np.hypot(*s9['field_arcmin']) / 60 + 0.02
    sky = jload('step8_stack.json')['constants']; raw_sky = np.median(np.array(list(sky.values())), 0)
    raw_sky3 = [float(raw_sky[0]), float(0.5 * (raw_sky[1] + raw_sky[2])), float(raw_sky[3])]
    year = 2026 + (285 + 0.5) / 365.25
    res = star_colour.calibrate(img, wcs, rgb_xyz, wb.tolist(), (float(ra0), float(dec0)), float(radius), mask, year,
                                sensor_xy=lambda x, y: (2 * (x + x0) + 0.5, 2 * (y + y0) + 0.5), raw_sky_dn=raw_sky3)
    res['applied_in_step_10'] = COLOUR_CAL
    res['input'] = dict(what='step 8 stack_mean planes cut to step 9\'s rectangle (x %d..%d, y %d..%d of the reference grid); camera R, mean of G1 and G2, B, times the daylight balance; sky at zero' % (x0, x1, y0, y1),
                        wcs='work/solve/stack.wcs (step 9)', galaxy_left_out='the catalogue ellipse of step 9, semi-axes x 1.3 (+30 px across)')
    print(star_colour.summary(res))
    print('catalogue: %s, %d stars in the cone (%s)%s' % (res['catalogue']['table'], res['catalogue']['rows'], res['catalogue']['cache_file'], ', from the cache' if res['catalogue']['used_from_cache'] else ', fetched now'))
    print('stars: %s; catalogue to stack offset median %s px, rms %.2f px' % (res['selection'], res['catalogue_to_stack_offset_px']['median'], res['catalogue_to_stack_offset_px']['rms']))
    print('radial term', json.dumps(res.get('radial_term')))
    jdump(res, 'step9b_colour.json')
