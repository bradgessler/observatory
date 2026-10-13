"""Step 2: read the 13 RAW crops and make them ready, without ever writing a RAW.
  * crop: a 1000 x 1100 sensor-pixel box (500 x 550 per colour plane) that holds the pair through the whole run
  * clipping check: the highest value in each frame and plane against the sensor's ceiling (14 bit: 16383 - black 512)
  * pedestal: the dark sky reads a few DN below the nominal black and a different few in each colour plane; the median
    of each plane of each frame (the star covers well under 1% of the crop) is taken out. That is a constant, not a surface.
  * hot pixels from the run itself (no darks tonight): a pixel that stands more than 6 noise sigmas above the 5 x 5
    median of its own colour plane in at least 12 of the 13 frames, while the star wanders over 60 px, is the sensor's.
    Repaired with the 3 x 3 median of its plane's neighbours (the same colour).
  * per-plane noise sigma (robust, from the sky).
Writes work/crops.npy (13, 4, 550, 500) float32 and step2_prepare.json."""
import numpy as np, cv2, rawpy
from common import *

def sky_level(p):
    """Mean of the plane's sky pixels: within 4 robust sigmas of the median (the median alone is on the 4 DN grid)."""
    m = np.median(p); s = max(1.4826 * np.median(np.abs(p - m)), 5.0)
    return float(p[np.abs(p - m) < 4 * s].mean())


if __name__ == '__main__':
    fs = frames(); n = len(fs)
    raw = []; clip = []; ped = []
    for f in fs:
        a, info = read_crop(os.path.join(NIGHT, f)); P = planes(a)
        mx = [float(P[i].max()) for i in range(4)]
        top = (info['white_level'] - 512)
        clip.append(dict(file=f, max_dn_above_black=mx, fraction_of_ceiling=[round(m / top, 3) for m in mx],
                         pixels_at_ceiling=int((a >= top - 1).sum()), white_level=info['white_level']))
        pd = np.array([sky_level(P[i]) for i in range(4)]); ped.append(pd)
        raw.append(P - pd[:, None, None])
    raw = np.stack(raw).astype(np.float32)                        # (n, 4, h2, w2)
    # hot pixels
    h2, w2 = raw.shape[2:]
    sigma = np.array([1.4826 * np.median(np.abs(raw[:, i] - np.median(raw[:, i]))) for i in range(4)])
    # the data come in steps of 4 DN: a MAD of the pixel values alone can read near 0; use the spread of neighbour differences too
    sig2 = np.array([np.std(raw[0, i][:150, :150]) for i in range(4)])
    sigma = np.maximum(sigma, sig2)
    hot = np.zeros((4, h2, w2), bool); count = np.zeros((4, h2, w2), np.int16)
    for i in range(4):
        for k in range(n):
            loc = cv2.medianBlur(raw[k, i], 5) if False else cv2.medianBlur(np.clip(raw[k, i] + 2000, 0, 65535).astype(np.uint16), 5).astype(np.float32) - 2000
            count[i] += (raw[k, i] - loc > 6 * sigma[i])
        hot[i] = count[i] >= n - 1
    nh = hot.reshape(4, -1).sum(1)
    for i in range(4):
        ys, xs = np.nonzero(hot[i])
        for k in range(n):
            m3 = cv2.medianBlur(np.clip(raw[k, i] + 2000, 0, 65535).astype(np.uint16), 3).astype(np.float32) - 2000
            # a hot pixel's own value is in its 3 x 3 median window; with isolated hot pixels the median ignores it
            raw[k, i][ys, xs] = m3[ys, xs]
    print('frames', n, 'crop planes', raw.shape[1:], '| hot pixels per plane R,G1,G2,B:', nh.tolist(), '| noise sigma DN:', np.round(sigma, 2).tolist())
    print('pedestal (DN below nominal black) per plane, mean over frames:', np.round(np.mean(ped, 0), 1).tolist())
    cmax = max(max(c['max_dn_above_black']) for c in clip)
    print('highest value in any plane of any frame: %.0f DN above black = %.0f%% of the %d DN ceiling; pixels at the ceiling: %d' % (cmax, 100 * cmax / (16383 - 512), 16383 - 512, sum(c['pixels_at_ceiling'] for c in clip)))
    np.save(W('crops.npy'), raw)
    r = rawpy.imread(os.path.join(NIGHT, fs[0]))
    jdump(dict(crop=CROP, hot_pixels_per_plane=dict(zip(PLANE_NAMES, nh.tolist())), hot_rule='> 6 sigma over the 5 x 5 same-colour median in at least 12 of 13 frames; repaired with the 3 x 3 median',
               noise_sigma_dn=dict(zip(PLANE_NAMES, sigma.round(3).tolist())), pedestal_dn=dict(zip(PLANE_NAMES, np.mean(ped, 0).round(2).tolist())),
               clipping=clip, highest_dn_above_black=cmax, ceiling_dn_above_black=16383 - 512,
               daylight_wb=[float(v) for v in r.daylight_whitebalance], camera_wb=[float(v) for v in r.camera_whitebalance],
               rgb_xyz_matrix=np.array(r.rgb_xyz_matrix).tolist(), white_level=int(r.white_level)), 'step2_prepare.json')
