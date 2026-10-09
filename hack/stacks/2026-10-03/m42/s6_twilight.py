"""Step 6, twilight version: a master flat from this morning's twilight sky flats (mount not tracking).

Frames: every RAW still after 1347 UTC whose camera settings (EXIF) are an exposure of 2 s or less at ISO 100
to 1600, and whose level says it is a flat: the median of green between 6% and 80% of the ceiling (the flat run aimed at mid-scale in the camera's JPEG,
which is 7 to 15% of the RAW range; at ISO 100 to 400 that is still 1200 to 2500 electrons per pixel), fewer than
1 pixel in 10000 at the ceiling, and smooth (99th minus 1st percentile of the 16x-shrunk green under 0.8 of its median; the
Moon and other targets taken in between fail this). (The log of the flat run, flats-log.json, is read if it is there and recorded;
the test above is what decides.)

Per colour plane: black subtracted; hot pixels (the map of step 2) and pixels more than 10% off the 3x3 median
replaced by that median; each frame divided by its own level (the median of the central 400 x 400
plane px); the master is the pixel-wise MEDIAN over the frames (stars, which trail and move between frames,
and any passing thing drop out); divided by its value at the sensor centre, so each plane is 1 there.
The master is then blurred very slightly (Gaussian sigma 0.7 plane px) to keep its own pixel noise out of the
picture; dust rings are 20 px and wider and are not touched by that.

The hair's shadow in the flats is where the hair was at dawn, not where it was during the M42 frames. It is
found in the master as in a frame (hair.py); inside its mask (grown by 60 sensor px) the flat is replaced by
its own smooth part (8x shrink, 5x5 median, Gaussian, grown back), so nothing false is divided into the frames.

Checked against tonight's cloud-glow flat (M31 core run): ratio of the two smooth parts (radial run, tilt,
edges) and the depth of the dust shadows in both."""
import glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *
import hair as hairmod

LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(SCR))), 'tonight', 'flats-log.json')
T_FROM = '134700'


def candidates():
    out = []
    for f in sorted(glob.glob(os.path.join(STILLS, '20261004-1[3-5]*.ARW'))):
        b = os.path.basename(f)
        if b[9:15] < T_FROM: continue
        e, iso = exif_settings(f[:-4] + '.JPG')
        if e is None:
            try:
                j = json.load(open(f[:-4] + '.json')); e = j['camera'].get('exposure_s'); iso = j['camera'].get('iso')
            except Exception: continue
        if e is None or iso is None or e > 2.01 or not (100 <= iso <= 1600): continue
        out.append(dict(path=f, stamp=b[:15], exposure_s=float(e), iso=int(iso)))
    return out


def smooth_part(a):
    small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (0, 0), 2, borderType=cv2.BORDER_REPLICATE)
    return cv2.resize(small, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)


def read(fr):
    planes, ceil, meta = load_planes(fr['path'])
    c = (slice(H2 // 2 - 200, H2 // 2 + 200), slice(W2 // 2 - 200, W2 // 2 + 200))
    lev = [float(np.median(planes[p][c])) for p in range(4)]
    frac_ceil = float(ceil.mean())
    g = (lev[1] + lev[2]) / 2
    small = cv2.resize(planes[1], None, fx=1 / 16, fy=1 / 16, interpolation=cv2.INTER_AREA)
    contrast = float((np.percentile(small, 99) - np.percentile(small, 1)) / max(np.median(small), 1.0))      # a flat is smooth: vignetting alone gives about 0.4
    ok = 0.06 * 15500 <= g <= 0.80 * 15500 and frac_ceil < 1e-4 and contrast < 0.8
    info = dict(fr, level=lev, at_ceiling_fraction=frac_ceil, contrast_p99_minus_p1_over_median=contrast, used=bool(ok), corner_over_centre=float(np.median(planes[1][20:220, 20:220]) / lev[1]), wb=meta['wb'][:3])
    if not ok: return info, None
    # hot pixels of the long-exposure map, and any pixel more than 10% off the 3x3 median of its plane (four times a flat frame's
    # pixel noise): replaced by that median, as in the frames, so that no defect of a flat frame is divided into the pictures
    hot = np.load(W('hot_long.npy')); nrep = 0
    for p in range(4):
        med3 = cv2.medianBlur(planes[p], 3)
        bad = hot[p] | (np.abs(planes[p] - med3) > 0.10 * np.maximum(med3, 1.0))
        planes[p][bad] = med3[bad]; nrep += int(bad.sum())
    info['pixels_repaired'] = nrep
    return info, np.stack([planes[p] / lev[p] for p in range(4)]).astype(np.float32)


def main():
    cand = candidates()
    print(len(cand), 'candidate flat frames (after %s UTC, <= 2 s, ISO 100..1600)' % T_FROM)
    assert len(cand) >= 5, 'no twilight flats yet'
    with ProcessPoolExecutor(6) as ex: res = list(ex.map(read, cand))
    infos = [r[0] for r in res]; cubes = [r[1] for r in res if r[1] is not None]; used = [r[0] for r in res if r[1] is not None]
    for i in infos: print('  %s %7.4f s ISO %4d  level R %.0f G %.0f %.0f B %.0f  corner/centre %.3f  %s' % (i['stamp'], i['exposure_s'], i['iso'], *i['level'], i['corner_over_centre'], 'USED' if i['used'] else 'not a flat (level, clipping or contrast %.2f)' % i['contrast_p99_minus_p1_over_median']))
    assert len(cubes) >= 5, 'too few usable flats'
    N = len(cubes); cube = np.stack(cubes); del cubes, res            # (N, 4, H2, W2)
    master = np.empty((4, H2, W2), np.float32)
    for p in range(4):
        master[p] = np.median(cube[:, p], axis=0)
    # pixel noise of the master: from two half-medians
    a = np.median(cube[0::2, 1], axis=0); b = np.median(cube[1::2, 1], axis=0)
    c = (slice(H2 // 2 - 200, H2 // 2 + 200), slice(W2 // 2 - 200, W2 // 2 + 200))
    noise_px = float(clipped_stats((a - b)[c])[1] / 2)
    # shutter check: frames of 1/100 s and shorter against the longer ones
    fast = [i for i, u in enumerate(used) if u['exposure_s'] < 0.011]; slow = [i for i, u in enumerate(used) if u['exposure_s'] >= 0.011]
    shutter = None
    if len(fast) >= 3 and len(slow) >= 3:
        r = smooth_part(np.median(cube[fast, 1], axis=0) / np.median(cube[slow, 1], axis=0))
        shutter = dict(fast_frames=len(fast), slow_frames=len(slow), ratio_min=float(r[40:-40, 40:-40].min()), ratio_max=float(r[40:-40, 40:-40].max()), top_over_bottom=float(np.median(r[60:260]) / np.median(r[-260:-60])), left_over_right=float(np.median(r[:, 60:260]) / np.median(r[:, -260:-60])))
    # first and last third of the run: did the sky's own gradient change?
    k = max(N // 3, 2)
    r2 = smooth_part(np.median(cube[:k, 1], axis=0) / np.median(cube[-k:, 1], axis=0))
    drift = dict(frames_each=k, ratio_min=float(r2[40:-40, 40:-40].min()), ratio_max=float(r2[40:-40, 40:-40].max()), top_over_bottom=float(np.median(r2[60:260]) / np.median(r2[-260:-60])), left_over_right=float(np.median(r2[:, 60:260]) / np.median(r2[:, -260:-60])))
    del cube
    for p in range(4):
        master[p] = cv2.GaussianBlur(master[p], (0, 0), 0.7)
        master[p] /= np.float32(np.median(master[p][H2 // 2 - 50:H2 // 2 + 50, W2 // 2 - 50:W2 // 2 + 50]))
    smooth = np.stack([smooth_part(master[p]) for p in range(4)])
    hm, hinfo = hairmod.find_hair(master, np.ones_like(master))
    flat = master.copy()
    if hm is not None:
        for p in range(4): flat[p] = np.where(hm, smooth[p], master[p])
    np.save(W('flat_twilight.npy'), flat); np.save(W('flat.npy'), flat); np.save(W('flat_smooth.npy'), smooth.astype(np.float32)); np.save(W('flat_leaveout.npy'), np.zeros((H2, W2), bool))
    # ---- against the cloud flat ----
    CF = np.load(os.path.join(CLOUD_CAL, 'flat2d.npy')); CR = np.load(os.path.join(CLOUD_CAL, 'dustratio.npy')); CD = np.load(os.path.join(CLOUD_CAL, 'dustmask.npy'))
    cmp_ = {}
    yy, xx = np.mgrid[0:H2, 0:W2]; rr = np.hypot(2 * xx + 0.5 - CENTRE[0], 2 * yy + 0.5 - CENTRE[1])
    for p in range(4):
        q = smooth[p] / CF[p]; q = q / np.median(q[H2 // 2 - 50:H2 // 2 + 50, W2 // 2 - 50:W2 // 2 + 50])
        A = np.column_stack([np.ones(q[::16, ::16].size), ((2 * xx - CENTRE[0]) / 3000)[::16, ::16].ravel(), ((2 * yy - CENTRE[1]) / 3000)[::16, ::16].ravel()])
        co, *_ = np.linalg.lstsq(A, q[::16, ::16].ravel(), rcond=None)
        rad = [float(np.median(q[(rr >= a_) & (rr < a_ + 400)][::9])) for a_ in range(0, 3600, 400)]
        cmp_[PLANE_NAMES[p]] = dict(twilight_over_cloud_min=float(q[30:-30, 30:-30].min()), max=float(q[30:-30, 30:-30].max()), tilt_per_3000px_x_y=[float(co[1]), float(co[2])], by_radius_400px_rings=rad,
                                    twilight_flat_corner_min=float(smooth[p].min()), cloud_flat_corner_min=float(CF[p].min()))
    def wide(a):          # the smooth part as the M31 dust map took it: 8x shrink, 5x5 median twice, 31-block box blur (250 plane px)
        small = cv2.resize(a, None, fx=1 / 8, fy=1 / 8, interpolation=cv2.INTER_AREA)
        low = cv2.blur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (31, 31), borderType=cv2.BORDER_REFLECT)
        return cv2.resize(low, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_CUBIC)
    tw_small = cv2.GaussianBlur((master[1] / wide(master[1]) + master[2] / wide(master[2])) / 2, (0, 0), 2.5)
    deep = CD & (CR < 0.97) & ~(hm if hm is not None else np.zeros((H2, W2), bool))
    x0, y0, x1, y1 = [v // 2 for v in HAIR_BOX]; deep[y0:y1, x0:x1] = False
    quiet = ~CD; quiet[:60] = False; quiet[-60:] = False; quiet[:, :60] = False; quiet[:, -60:] = False
    dust = dict(pixels_where_the_cloud_map_is_deeper_than_3pct=int(deep.sum()), cloud_map_median_there=float(np.median(CR[deep])), twilight_median_there=float(np.median(tw_small[deep])),
                correlation_of_depth=float(np.corrcoef(1 - CR[CD][::5], 1 - tw_small[CD][::5])[0, 1]), slope_twilight_over_cloud=float(((1 - CR[CD]) * (1 - tw_small[CD])).sum() / ((1 - CR[CD]) ** 2).sum()),
                scatter_outside_dust_twilight=float(1.4826 * np.median(np.abs(tw_small[quiet][::7] - 1))), scatter_outside_dust_cloud=float(1.4826 * np.median(np.abs(CR[quiet][::7] - np.median(CR[quiet][::7])))))
    log = json.load(open(LOG)) if os.path.exists(LOG) else None
    info = dict(source='twilight', what='master flat from %d twilight sky flats of this morning: per plane, median of level-normalised frames, 1 at the sensor centre, Gaussian sigma 0.7 px; hair zone of the flats replaced by the flat\'s smooth part' % N,
                frames=infos, frames_used=N, exposures_s=sorted(set(u['exposure_s'] for u in used)), isos=sorted(set(u['iso'] for u in used)), first=used[0]['stamp'], last=used[-1]['stamp'],
                master_pixel_noise_before_blur=noise_px, hair_in_the_flats=hinfo, shutter_check=shutter, first_third_over_last_third=drift, against_cloud_flat=cmp_, dust_against_cloud_map=dust,
                flat_min_max=[[float(f.min()), float(f.max())] for f in flat], leave_out_fraction=0.0, flats_log=log)
    json.dump(info, open(W('s6_flat.json'), 'w'), indent=1)
    print('master flat from %d frames (%s .. %s); pixel noise %.4f; hair in the flats: %s' % (N, used[0]['stamp'][9:], used[-1]['stamp'][9:], noise_px, hinfo))
    print('shutter check', shutter); print('first third over last third', drift)
    for k_, v in cmp_.items(): print('  %s twilight / cloud: %.3f..%.3f, tilt per 3000 px x %+.4f y %+.4f; by radius %s; corner min twilight %.3f cloud %.3f' % (k_, v['twilight_over_cloud_min'], v['max'], *v['tilt_per_3000px_x_y'], np.round(v['by_radius_400px_rings'], 3).tolist(), v['twilight_flat_corner_min'], v['cloud_flat_corner_min']))
    print('dust', dust)
    v = np.clip((np.hstack([cv2.resize(tw_small, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_AREA), cv2.resize(CR, None, fx=0.3, fy=0.3, interpolation=cv2.INTER_AREA)]) - 0.90) / 0.13, 0, 1)
    cv2.imwrite(W('v_dust_twilight_vs_cloud.png'), (v * 255).astype(np.uint8))
    v = np.clip((cv2.resize(smooth[1], None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA) - 0.6) / 0.45, 0, 1); cv2.imwrite(W('v_flat_twilight_G1.png'), (v * 255).astype(np.uint8))


if __name__ == '__main__':
    main()
