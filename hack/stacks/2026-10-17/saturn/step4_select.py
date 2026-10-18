"""Step 4: how many frames to keep. The field turns (the ring line in each frame, step 2, fitted against time: one rate);
the frames are ranked by sharpness and stacked in that order, the sharpest first, each turned back to the reference time
(the moon frames', so the planet and moons share one orientation), registered on a reference made from the sharpest 50
(phase correlation, two passes), and the stack is measured at each keep count in COUNTS with the 3 October metrics (green
only): polar limb 10-90 width, ansa width, gap contrast between globe and ring, gradient energy, noise. The count chosen is
the largest that is not softer: polar limb and ansa width within SOFT (3 percent) of the sharpest count's, and gap contrast
within SOFT of the best. Writes work/select.json and checks/keepcounts.png (the stacks side by side at one stretch)."""
from concurrent.futures import ProcessPoolExecutor
import cv2
from common import *
from planetlib import tile, phase_shift, shift, turn_of, N_FINE
from metrics import measure
COUNTS = [int(x) for x in os.environ.get('SAT_COUNTS', '5,8,10,12,15,20,25,30,40,60,80,100,130,160,200,250,300,400,488').split(',')]
SOFT = float(os.environ.get('SAT_SOFT', '0.03'))
REF_MIN = 5 * 60 + 22 + 35 / 60          # 05:22:35 UTC, between the two moon frames
NREF = 50

if __name__ == '__main__':
    g = [r for r in jload('grades.json') if r['ok'] and r['clipped'] == 0]
    med = np.median([r['flux'] for r in g]); other = [r for r in g if not 0.8 * med < r['flux'] < 1.25 * med]; g = [r for r in g if 0.8 * med < r['flux'] < 1.25 * med]
    t = np.array([minute(r['name']) for r in g]); a = np.array([r['ring_line_deg'] for r in g])
    A = np.vstack([t - REF_MIN, np.ones_like(t)]).T; coef = np.linalg.lstsq(A, a, rcond=None)[0]
    for _ in range(3):                                   # drop frames more than 3 sigma off the line, refit
        res = a - A @ coef; s = 1.4826 * np.median(np.abs(res)); k = np.abs(res) < 3 * s; coef = np.linalg.lstsq(A[k], a[k], rcond=None)[0]
    rate, a0 = float(coef[0]), float(coef[1]); scatter = float(1.4826 * np.median(np.abs(a - A @ coef)))
    print('ring line turns %.5f deg per minute (%.2f deg over the run), %.2f deg at 05:22:35; one frame scatters %.2f deg about the line' % (rate, rate * (t.max() - t.min()), a0, scatter))
    g.sort(key=lambda r: -r['sharp']); names = [r['name'] for r in g]
    args = lambda rows, sh=None: [(r['name'], r['x'], r['y'], turn_of(r['name'], rate, REF_MIN), 0.0, 0.0) for r in rows]
    with ProcessPoolExecutor(WORKERS) as ex: T = list(ex.map(tile, args(g[:NREF])))
    ref = np.mean([x[:, :, 1] for x in T], 0)
    for _ in range(2):
        sh = [phase_shift(ref, x[:, :, 1]) for x in T]; ref = np.mean([shift(x[:, :, 1], *s) for x, s in zip(T, sh)], 0)
    del T
    acc = np.zeros((N_FINE, N_FINE, 3), np.float64); shifts = []; stacks = {}; i = 0
    with ProcessPoolExecutor(WORKERS) as ex:
        for c0 in range(0, len(g), 48):
            for x in ex.map(tile, args(g[c0:c0 + 48])):
                s = phase_shift(ref, x[:, :, 1]); shifts.append(s); acc += shift(x, *s); i += 1
                if i in COUNTS or i == len(g): stacks[i] = (acc / i).astype(np.float32)
    rows = []
    for n, st in sorted(stacks.items()):
        m, _ = measure(st[:, :, 1]); np.save(W('keep%03d.npy' % n), st)
        rows.append(dict(keep=n, polar_limb_10_90_arcsec=m['polar_limb_10_90_arcsec'], ansa_width_fwhm_arcsec=m['ansa_width_fwhm_arcsec'], gap_contrast=m['gap_contrast'],
                         gradient_energy=m['gradient_energy'], noise_of_globe=round(m['noise_of_globe'], 6), sharpness_of_last_frame=g[n - 1]['sharp']))
        print('keep %3d: polar limb %.3f"  ansa %.3f"  gap contrast %.4f  gradient energy %.4f  noise %.5f of globe  (last frame in: sharpness %.4f)' % (n, rows[-1]['polar_limb_10_90_arcsec'], rows[-1]['ansa_width_fwhm_arcsec'], rows[-1]['gap_contrast'], rows[-1]['gradient_energy'], rows[-1]['noise_of_globe'], rows[-1]['sharpness_of_last_frame']))
    bl = min(r['polar_limb_10_90_arcsec'] for r in rows); ba = min(r['ansa_width_fwhm_arcsec'] for r in rows); bg = max(r['gap_contrast'] for r in rows)
    for r in rows: r['not_softer'] = bool(r['polar_limb_10_90_arcsec'] <= bl * (1 + SOFT) and r['ansa_width_fwhm_arcsec'] <= ba * (1 + SOFT) and r['gap_contrast'] >= bg * (1 - SOFT))
    chosen = max(r['keep'] for r in rows if r['not_softer'])
    print('not softer than the sharpest (within %.0f%%): %s; chosen: %d' % (SOFT * 100, [r['keep'] for r in rows if r['not_softer']], chosen))
    # the stacks side by side, one stretch
    os.makedirs(os.path.join(HERE, 'checks'), exist_ok=True); show = [n for n in sorted(stacks) if n in (15, 40, 100, chosen, 300, len(g))]
    white = float(np.percentile(stacks[show[0]][:, :, 1], 99.9)); c = N_FINE // 2; half = 200
    pan = [np.clip(stacks[n][c - half:c + half, c - half:c + half, 1] / white, 0, 1) ** (1 / 2.2) for n in show]
    img = (np.hstack([np.pad(p, ((30, 0), (0, 8))) for p in pan]) * 255).astype(np.uint8)
    for j, n in enumerate(show): cv2.putText(img, 'keep %d' % n, (j * (2 * half + 8) + 8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, 255, 1)
    cv2.imwrite(os.path.join(HERE, 'checks', 'keepcounts.png'), img)
    jsave('select.json', dict(usable=len(g), dropped_for_flux=[r['name'] for r in other], flux_median=float(med), flux_band=[0.8, 1.25], turn_deg_per_minute=rate, ring_line_at_ref_deg=a0, ring_line_scatter_deg=scatter,
                              reference_minute_utc=REF_MIN, ranked=[dict(name=r['name'], sharp=r['sharp'], rank=i + 1, shift_fine_px=[round(s[0], 3), round(s[1], 3)]) for i, (r, s) in enumerate(zip(g, shifts))],
                              counts=rows, soft=SOFT, chosen=chosen, registration=dict(reference='mean of the sharpest %d, green, two passes of phase correlation' % NREF)))
