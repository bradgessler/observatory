"""Step 5: the planet stack. The sharpest KEEP frames (step 4's choice; SAT_KEEP overrides), each laid on the fine grid
(3 per sensor px) once: its colour planes at their own places in the cell, turned back for the field's turn, and moved by
its registration shift, all in one Lanczos resampling. Then red and blue are slid onto green by least squares
(atmospheric dispersion). Also the two halves (odd and even ranks), stacked the same way, for the "is it real" test.
KEEP is 25, not step 4's 5. Step 4 measured plain stacks: 5 frames (all from 05:40 to 05:56, a better spell) had a
13 percent higher gap contrast than 8 to 25, which sit on one plateau within 3 percent. But the delivered picture is the
restored one, and restored, 25 frames beat 5 (gap contrast 0.359 against 0.313, ansa 2.29 against 2.30 arcsec) with less
than half the grain (0.0059 against 0.0135 of the globe per fine px) and Titan measured at 18 sigma instead of 8: the
blur is known better. So 25 is the largest count that is not softer where it counts, the top of step 4's plateau.
checks/k5-vs-k25-rounds-0-8-12-20.png shows both. SAT_KEEP=5 makes the other one.
Writes work/stack.npy, work/half0.npy, work/half1.npy, work/stack.json."""
from concurrent.futures import ProcessPoolExecutor
from common import *
from planetlib import tile, ls_shift, shift, turn_of, phase_shift
from metrics import measure

if __name__ == '__main__':
    sel = jload('select.json'); g = {r['name']: r for r in jload('grades.json')}
    KEEP = int(os.environ.get('SAT_KEEP', '25')); rate, ref_min = sel['turn_deg_per_minute'], sel['reference_minute_utc']
    use = sel['ranked'][:KEEP]
    args = [(r['name'], g[r['name']]['x'], g[r['name']]['y'], turn_of(r['name'], rate, ref_min), r['shift_fine_px'][0], r['shift_fine_px'][1]) for r in use]
    with ProcessPoolExecutor(WORKERS) as ex: T = list(ex.map(tile, args))
    # a last check of the registration on the one-resampling tiles: each against the mean of the others
    ref = np.mean([t[:, :, 1] for t in T], 0); resid = [phase_shift(ref, t[:, :, 1]) for t in T]
    def finish(tiles):
        s = np.mean(tiles, 0).astype(np.float32); disp = {}
        for c, nm in ((0, 'red'), (2, 'blue')):
            dx, dy = ls_shift(s[:, :, 1], s[:, :, c]); disp[nm] = [round(dx / 3, 3), round(dy / 3, 3)]; s[:, :, c] = shift(s[:, :, c], dx, dy)
        return s, disp
    stack, disp = finish(T); h0, d0 = finish(T[0::2]); h1, d1 = finish(T[1::2])
    np.save(W('stack.npy'), stack); np.save(W('half0.npy'), h0); np.save(W('half1.npy'), h1)
    m, _ = measure(stack[:, :, 1])
    info = dict(keep=KEEP, frames=[r['name'] for r in use], each=[dict(name=a[0], planet_cell_px=[a[1], a[2]], turned_back_deg=round(a[3], 4), shift_fine_px=[a[4], a[5]]) for a in args],
                residual_shift_after_fine_px_rms=round(float(np.sqrt(np.mean([x * x + y * y for x, y in resid]))), 3), dispersion_native_px=disp, dispersion_halves=[d0, d1],
                fine_px_per_sensor_px=3, arcsec_per_fine_px=SCALE / 3, tile_fine_px=stack.shape[0], metrics=m,
                times_utc=['%02d:%02d:%02d' % (int(minute(n) // 60), int(minute(n) % 60), round(minute(n) * 60 % 60)) for n in [r['name'] for r in use]])
    jsave('stack.json', info)
    print('kept %d frames; registration residual %.3f fine px rms; red moved %s, blue %s sensor px onto green' % (KEEP, info['residual_shift_after_fine_px_rms'], disp['red'], disp['blue']))
    print('stack: polar limb %.3f", ansa %.3f", gap contrast %.4f, ring line %.2f deg, centre %s' % (m['polar_limb_10_90_arcsec'], m['ansa_width_fwhm_arcsec'], m['gap_contrast'], m['ring_line_deg'], m['centre']))
