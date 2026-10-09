"""Step 6, the flat that is used: the twilight master flat (s6_twilight.py) with its LARGE-SCALE shape taken
from tonight's cloud-glow flat.

Why not the twilight flat as it is. The whole pipeline was run with it, and the same sky seen through different
parts of the sensor did not agree: against the centred stack every clear panel needed a tilt of 2 to 5 DN per
1000 px, and carried outward those tilts put the far ends of the panels 5 to 20 DN below the zero (black areas
in the mosaic). The same run with the cloud flat needed no tilts (the clear panels agreed with constants alone to
1.5 to 1.9 DN). The two flats differ smoothly: the twilight flat is 2% (green), 3.5% (red), 0.7% (blue) brighter
at the corners and tilted by 1.7% per 3000 px, and its own tilt changed by 1% while it was being taken. A sky
flat taken in twilight sees a bright sky over the whole hemisphere: light that reaches the sensor without going
through the imaging path fills the corners, and the dawn sky has a gradient of its own. Both act on the large
scale only. The cloud flat was made at night from this telescope's own frames (clouded minus clear), and it is
the one under which the night sky comes out flat. What the cloud flat could NOT give is the dust: its map was
hours old and noisy; the twilight flat shows every shadow sharply and as it was this morning.

So:  flat = twilight master x LS,   LS = the smooth ratio (cloud flat's smooth part / twilight master):
     the ratio shrunk 16x (block mean), 5x5 median twice (dust and the hair drop out), Gaussian sigma 10 blocks
     (160 plane px, 320 sensor px), grown back (bicubic); per colour plane; each plane 1 at the sensor centre.
Everything smaller than about 300 plane px (dust shadows, edge shading, pixel-to-pixel response) is the twilight
flat's; everything larger (vignetting, tilt) is the cloud flat's. No pixel is left out for dust."""
import json
import numpy as np, cv2
from common import *
import s6_twilight


def main():
    s6_twilight.main()                               # writes flat_twilight.npy, flat.npy, flat_smooth.npy, s6_flat.json
    tw = np.load(W('flat_twilight.npy')); info = json.load(open(W('s6_flat.json')))
    CF = np.load(os.path.join(CLOUD_CAL, 'flat2d.npy'))
    out = np.empty_like(tw); smooth = np.empty_like(tw); rep = []
    for p in range(4):
        q = (CF[p] / tw[p]).astype(np.float32)
        small = cv2.resize(q, None, fx=1 / 16, fy=1 / 16, interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(cv2.medianBlur(cv2.medianBlur(small, 5), 5), (0, 0), 10, borderType=cv2.BORDER_REPLICATE)
        LS = cv2.resize(small, (W2, H2), interpolation=cv2.INTER_CUBIC)
        out[p] = tw[p] * LS
        out[p] /= np.float32(np.median(out[p][H2 // 2 - 50:H2 // 2 + 50, W2 // 2 - 50:W2 // 2 + 50]))
        smooth[p] = s6_twilight.smooth_part(out[p])
        LSn = LS / np.median(LS[H2 // 2 - 50:H2 // 2 + 50, W2 // 2 - 50:W2 // 2 + 50])
        rep.append(dict(plane=PLANE_NAMES[p], large_scale_factor_min=float(LSn.min()), large_scale_factor_max=float(LSn.max()), corners=[float(LSn[40, 40]), float(LSn[40, -40]), float(LSn[-40, 40]), float(LSn[-40, -40])],
                        flat_min=float(out[p].min()), flat_max=float(out[p].max()), ratio_to_cloud_flat_after=dict(p01=float(np.percentile(out[p] / CF[p], 1)), p99=float(np.percentile(out[p] / CF[p], 99)))))
        print(rep[-1])
    np.save(W('flat.npy'), out); np.save(W('flat_smooth.npy'), smooth); np.save(W('flat_leaveout.npy'), np.zeros((H2, W2), bool))
    info.update(source='twilight, with the large-scale shape of the cloud flat',
                what='master flat from %d twilight sky flats of this morning (per plane, median of level-normalised frames, Gaussian sigma 0.7 px, hair zone of the flats replaced by the smooth part), multiplied by a smooth large-scale factor (scales above about 300 plane px) that gives it the vignetting and tilt of tonight\'s cloud-glow flat; dust shadows, edge shading and pixel response are the twilight flat\'s' % info['frames_used'],
                large_scale_factor=rep, large_scale_smoothing='ratio cloud / twilight: 16x block mean, 5x5 median twice, Gaussian sigma 10 blocks (160 plane px), bicubic', flat_min_max=[[float(f.min()), float(f.max())] for f in out],
                why=__doc__)
    json.dump(info, open(W('s6_flat.json'), 'w'), indent=1)


if __name__ == '__main__':
    main()
