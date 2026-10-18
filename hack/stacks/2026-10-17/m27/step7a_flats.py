"""Step 7a: candidate flats, and what each leaves on THIS run's own open sky (.claude/skills/stack-pictures/tools/
flatcheck.py), before step 7 picks one and measures the dust it leaves. No twilight flats and no darks were taken tonight.

Candidates (all read only; only m33 is built here, into <night>/flat-sky-m33/):
  hybrid13    13 October: the large scale from that night's open sky (NGC 891, NGC 2261, NGC 2419, M1; skyflat.py), the dust
              and pixel response from that dawn's twilight flats (twilight_flat.py). <2026-10-12 night>/flat-hybrid-m77.
  twilight13  the 13 October twilight flats as measured (their large scale is the parked telescope's: the light centred
              880 px off the middle, the skill says). <2026-10-12 night>/flat-twilight.
  m33         tonight's other open-sky run, M33 (04:24 to 05:20 UTC, 15 s ISO 3200, same optics; dithered from about
              05:00), through skyflat.py: its sky's large scale with the galaxy's bright middle masked, times the 13 October
              twilight dust. M33 is 70 x 40 arcmin and this frame 39 x 26, so its disc lies under all of that sky: the
              check below says whether that matters.
The check: flatcheck.own_sky on this run's used frames (step 5), M27 masked as a circle of MASK_R arcmin round the
reference frame's central star, grown by the run's wander (the field drifted about 250 sensor px each way); then
flatcheck.against for each candidate: large-scale remainder (rms, after a plane), dust left (green, shadows the flat leaves,
the dust maps' correlation and shift) and per-colour shadow depth. The same is done on M33's own sky (dithered, a second,
independent look at tonight's dust). Written to work/step7a_flats.json and ./logs."""
import glob, json, os, sys
import numpy as np
from common import *
import flatcheck as fc, skyflat, twilight_flat as tf, rawplanes as rp

M33 = dict(ra_deg=23.462042, dec_deg=30.660222)
M33_T0, M33_T1 = '042400', '052000'
M33_MASK_R_PX = float(os.environ.get('M27_M33_MASK_R', '700'))      # plane px (9 arcmin) round the frame centre: M33's bright middle
TWILIGHT = FLAT_DIRS['twilight13']


def m33_frames():
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, DATE + '-??????-*.ARW'))):
        st = os.path.basename(f)[9:15]
        if not (M33_T0 <= st <= M33_T1): continue
        j = json.load(open(f[:-4] + '.json')); sv = f[:-4] + '.solve.json'
        sol = (json.load(open(sv)).get('solution') or {}) if os.path.exists(sv) else {}
        if not sol.get('ra_deg'): continue
        sep = np.hypot((sol['ra_deg'] - M33['ra_deg']) * np.cos(np.radians(M33['dec_deg'])), sol['dec_deg'] - M33['dec_deg'])
        e, iso = raw_exif(f)
        if (e, iso) != (EXPOSURE_S, ISO) or sep > 0.5 or j.get('settling') or ((j.get('settle') or {}).get('since_slew_s') or 99) < 10: continue
        out.append(f)
    return out


if __name__ == '__main__':
    os.makedirs(W('flatcheck'), exist_ok=True)
    sel = jload('step5_select.json'); used = [path_of(u['stamp']) for u in sel['used']]
    s6 = jload('step6_solve_ref.json'); cx, cy = s6['galaxy_ellipse']['centre_px']
    sh = np.array([o['shift_at_centre_px'] for o in jload('step3_transforms.json')['transforms']]) / 2
    grow = float(np.ceil(np.abs(sh).max() + 20))
    m27 = [dict(centre_px=[cx, cy], semi_major_px=s6['galaxy_ellipse']['semi_major_px'], semi_minor_px=s6['galaxy_ellipse']['semi_minor_px'], major_axis_angle_deg=0.0)]
    print('M27 run: %d used frames; M27 masked as a circle of %.0f px round (%.0f, %.0f), grown %.0f px for the wander' % (len(used), m27[0]['semi_major_px'], cx, cy, grow), flush=True)
    cache = W('flatcheck/sky_m27.npz')
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True); sky = dict(big=z['big'], small=z['small'], levels=z['levels'], masked=list(z['masked']), frames=list(z['frames']))
    else:
        sky = fc.own_sky(used, m27, grow, WORKERS); np.savez(cache, **sky)
    # ---- M33's sky: the flat candidate, and an independent look at tonight's dust
    mf = m33_frames()
    m33obj = [dict(centre_px=[w2 / 2, h2 / 2], semi_major_px=M33_MASK_R_PX, semi_minor_px=M33_MASK_R_PX, major_axis_angle_deg=0.0)]
    print('M33 run: %d frames (%s to %s)' % (len(mf), os.path.basename(mf[0])[:15], os.path.basename(mf[-1])[:15]), flush=True)
    out_m33 = FLAT_DIRS['m33']
    # skyflat.py needs two runs or more (with one, the run-against-joint plane fit has nothing to fit and returns no
    # blocks): the M33 run is given as its two halves, before and after the dithering began (05:00 UTC)
    half = [f for f in mf if os.path.basename(f)[9:15] < '050000'], [f for f in mf if os.path.basename(f)[9:15] >= '050000']
    rec = skyflat.build([dict(name='m33-still', frames=half[0], objects=m33obj, grow=60.0), dict(name='m33-dithered', frames=half[1], objects=m33obj, grow=60.0)],
                        TWILIGHT, out_m33, cache_dir=W('flatcheck'), workers=WORKERS)
    zz = [np.load(W('flatcheck/sky_%s.npz' % n), allow_pickle=True) for n in ('m33-still', 'm33-dithered')]
    s33 = dict(big=np.nanmedian(np.stack([z['big'] for z in zz]), 0), small=np.nanmedian(np.stack([z['small'] for z in zz]), 0), levels=np.concatenate([z['levels'] for z in zz]), frames=sum((list(z['frames']) for z in zz), []))
    flats = {n: tf.load(FLAT_DIRS[n]) for n in ('hybrid13', 'twilight13', 'm33')}
    res = dict(m27_sky=dict(frames=sky['frames'], object=m27, grow_px=grow, sky_level_dn=dict(zip(PLANE_NAMES, np.median(sky['levels'], 0).round(2).tolist())), masked_fraction_median=float(np.median(sky['masked']))),
               m33_run=dict(frames=[os.path.basename(f) for f in mf], halves=[len(half[0]), len(half[1])], mask=m33obj, sky_level_dn=dict(zip(PLANE_NAMES, np.median(s33['levels'], 0).round(2).tolist()))),
               on_m27_sky=[fc.against(sky, F, n) for n, F in flats.items()],
               on_m33_sky=[fc.against(s33, F, n) for n, F in flats.items() if n != 'm33'])
    fc.picture(sky, flats, W('v_flatcheck_m27sky.png'))
    for where in ('on_m27_sky', 'on_m33_sky'):
        print('==== %s' % where)
        for r in res[where]:
            g = r['large']['G1']; s = r['small']
            print('%-10s large (G1): rms %.4f, after plane %.4f (1-99%% %.3f..%.3f), rings %s | R after plane %.4f, B %.4f | dust: %d shadows left (%d deeper than 2%%, deepest %.3f), correlation %.2f, shift %s | depth sky/flat %s' % (
                r['flat'], g['robust_rms'], g['robust_rms_after_plane'], *g['range_after_plane_1_99_pct'], ' '.join('%.3f' % x['after_plane'] if x['after_plane'] else '-' for x in g['rings']),
                r['large']['R']['robust_rms_after_plane'], r['large']['B']['robust_rms_after_plane'], s['shadows_left'], s['deeper_than_2pct'], s['deepest'], s['dust_correlation'], s['shift_flat_to_sky_plane_px'],
                {k: v['depth_in_sky_over_depth_in_flat'] for k, v in r['per_colour_slope'].items()}), flush=True)
            for w_ in s['worst'][:6]: print('     left: plane px (%.0f, %.0f) = sensor (%.0f, %.0f), %.3f deep, r %.0f px' % (*w_['plane_px'], 2 * w_['plane_px'][0], 2 * w_['plane_px'][1], w_['depth'], w_['radius_plane_px']), flush=True)
    jdump(res, 'step7a_flats.json')
