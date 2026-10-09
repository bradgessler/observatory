"""Step 3: stars in every frame (green planes averaged, half-size grid): centroids, fluxes, widths, elongation.
The detector of the night's M31 pipeline: the smooth light (sky, glare, nebulosity, cloud glow) is taken off first
(plane shrunk 8x, 5x5 median, Gaussian sigma 2, grown back), detection on the remainder blurred with sigma 2.5 in
units of the local noise (variance = a + b x level fitted to the frame's own 64 px blocks), 6 sigma, blobs of 8 px
or more. Gaussian-windowed centroid; 28 px (sensor) aperture, ring 38 to 54 px for the local level.
Hot pixels and single-frame spikes are repaired first (step 2's map; spikes: above the 3x3 median of the plane by
more than 8 sigma + 50% of the level)."""
import json
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from c import *

F = json.load(open(W('p1.json')))['frames']


def detect(fr):
    P, ceil, meta, trans = repaired(fr['path'], [c_['clipped_std'] for c_ in fr['corner']])
    G = (P[1] + P[2]) / 2
    stars, nm, zs = detect_image(G, P)
    return dict(stamp=fr['stamp'], panel=fr['panel'], z_sigma=zs, noise_model=nm, spikes=trans, stars=stars)


if __name__ == '__main__':
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(detect, F))
    json.dump(res, open(W('p3_stars.json'), 'w'))
    for r in res:
        b = [k for k in r['stars'] if not k['saturated']][:2]
        print(r['stamp'], r['panel'], 'n', len(r['stars']), 'sat', sum(k['saturated'] for k in r['stars']), 'spikes', r['spikes'], 'noise a %.0f b %.2f' % (r['noise_model']['a'], r['noise_model']['b']),
              ' | '.join('(%.1f,%.1f) F=%.0f pk=%.0f el=%.2f hfr=%.1f' % (s['x'], s['y'], s['flux'], s['peak'], s['elong'], s['hfr']) for s in b))
