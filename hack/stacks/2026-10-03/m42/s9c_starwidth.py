"""Step 9c: how wide the stars are in the finished stacks (for the record; nothing is changed).
The detector of step 3 on the green of the deep stack and of the short stack; isolated stars with no pixel near
the ceiling in any frame, no wider than a star can be (half-flux radius under 4.5 px: knots of nebula are left
out). Half-flux diameter inside the 28 px (sensor) aperture, and elongation; medians."""
import json
import numpy as np, cv2
from common import *
from s3_stars import detect_image

out = {}
for name in ('deep', 'short'):
    P = np.load(W(name + '_planes.npy')); G = (P[1] + P[2]) / 2; ok = np.isfinite(G)
    fill = cv2.blur(np.where(ok, G, 0).astype(np.float32), (201, 201)) / np.maximum(cv2.blur(ok.astype(np.float32), (201, 201)), 1e-3)
    stars, _, _ = detect_image(np.where(ok, G, fill).astype(np.float32))
    clip = cv2.dilate((np.load(W(name + '_clip.npy')) > 0).astype(np.uint8), np.ones((33, 33), np.uint8)).astype(bool)
    minflux = 30000 if name == 'deep' else 1500
    sel = [s for s in stars if s['nearest'] > 60 and s['flux'] >= minflux and s['hfr'] and s['hfr'] < 4.5 and not clip[int(round(s['y'])), int(round(s['x']))]]
    out[name] = dict(stars=len(sel), half_flux_diameter_arcsec=round(float(np.median([2 * s['hfr'] for s in sel])) * HS, 2), elongation=round(float(np.median([s['elong'] for s in sel])), 3),
                     quartiles_arcsec=[round(float(np.percentile([2 * s['hfr'] for s in sel], q)) * HS, 2) for q in (25, 75)])
    print(name, out[name])
json.dump(out, open(W('s9c_starwidth.json'), 'w'), indent=1)
