"""Step 6: the flat field that every frame is divided by, one per colour plane.

TWILIGHT FLATS, if the morning's sky flats are in the stills folder (s6_twilight.py makes flat_twilight.npy):
they hold vignetting, tilt, edge shading and every dust shadow as they were this morning, so nothing needs to be
left out for dust. The hair's shadow sits elsewhere in the flats than in the frames; where the flats show it the
flat is replaced by its own smooth part (so nothing false is divided in), and each frame's own hair is cut out.
'twilight' (the one used) = that master flat with its large-scale shape taken from the cloud flat (s6_hybrid.py says
why); 'twilight-as-is' = the master flat alone.

CLOUD FLAT otherwise (tonight's M31 core run, 0736..0846 UTC; ../m31/mosaic/calibration-from-core-run):
  smooth part, per plane: flat2d.npy (the cloud's glow seen through the optics: radial fall-off, tilt, edge shading)
  small part, green for all planes: dustratio.npy (the dust shadows as they were then), held to 0.5..1.05, and
  set to 1 (nothing divided) where that map shows the hair, because the hair has moved since.
  Sensor pixels under a mapped dust shadow (dustmask.npy) are also LEFT OUT of the average wherever at least
  half of a set's frames see that sky through clean pixels.

Usage: s6_flat.py cloud | twilight | twilight-as-is"""
import json, sys
import numpy as np, cv2
from common import *

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'cloud'
    if mode == 'cloud':
        FLAT = np.load(os.path.join(CLOUD_CAL, 'flat2d.npy')); RATIO = np.load(os.path.join(CLOUD_CAL, 'dustratio.npy')); DUST = np.load(os.path.join(CLOUD_CAL, 'dustmask.npy'))
        x0, y0, x1, y1 = [v // 2 for v in HAIR_BOX]
        hair = np.zeros((H2, W2), bool); hair[y0:y1, x0:x1] = (RATIO < 0.95)[y0:y1, x0:x1]
        n, lab, stats, cent = cv2.connectedComponentsWithStats(hair.astype(np.uint8), connectivity=8)
        big = max(range(1, n), key=lambda i: stats[i, 4]); hair = lab == big
        hair = cv2.dilate(hair.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (81, 81))).astype(bool)
        small = np.clip(RATIO, 0.5, 1.05).astype(np.float32); small[hair] = 1.0
        flat = (FLAT * small[None]).astype(np.float32)
        dust = DUST & ~hair
        np.save(W('flat.npy'), flat); np.save(W('flat_smooth.npy'), FLAT.astype(np.float32)); np.save(W('flat_leaveout.npy'), dust)
        ys, xs = np.nonzero(hair)
        info = dict(source='cloud', what='cloud-glow flat of tonight\'s M31 core run (0736..0846 UTC): smooth flat per plane x green dust-ratio map; dust-mask pixels left out of the average where possible',
                    files=['flat2d.npy', 'dustratio.npy', 'dustmask.npy'], folder=CLOUD_CAL, hair_in_that_map_sensor_bbox=[int(2 * xs.min()), int(2 * ys.min()), int(2 * xs.max()), int(2 * ys.max())],
                    leave_out_fraction=float(dust.mean()), flat_min_max=[[float(f.min()), float(f.max())] for f in flat])
        json.dump(info, open(W('s6_flat.json'), 'w'), indent=1); print(info)
    elif mode == 'twilight-as-is':
        import s6_twilight
        s6_twilight.main()
    else:
        import s6_hybrid
        s6_hybrid.main()
