"""Step 12b: what round the bright stars is glare and what is nebulosity. Measured, not judged by eye.

For each named star, on the linear mosaic (green, 1.5526 arcsec per px): the median level in rings round the star,
split into eight 45 degree sectors (medians, so field stars drop out). Glare from the optics is round and scales
with the star's brightness; a reflection nebula is neither. So two numbers per ring:
  level per unit of star light: ring level x 10^(0.4 (V - 4.18)), i.e. scaled to a star of Merope's magnitude.
      The same optics give every star the same curve. Alcyone, the brightest star in the clear stacks (so the
      best measured), has the lowest curve per unit of light in the inner rings: its curve is taken as the most
      the optics can be giving (an UPPER limit to glare: Alcyone has nebulosity of its own). What a star shows
      above Alcyone's curve scaled to its own brightness is not glare.
  lopsidedness: (brightest sector - faintest sector) of a ring. Glare has none beyond noise.
Stars in the two cloud stacks have an extra round glow from the cloud itself; they are listed, not used for the limit."""
import json
import numpy as np
from c import *

VMAG = dict(Alcyone=2.87, Atlas=3.63, Electra=3.70, Maia=3.87, Merope=4.18, Taygeta=4.30, Pleione=5.09, Celaeno=5.45, Asterope=5.76)
D = json.load(open(W('p12_deliver.json'))); g = D['m45-mosaic.png / .jpg']; ps = g['pixel_scale_arcsec']
b2 = np.load(W('deliver_b2.npy'))[..., 1]; rgb = np.load(W('deliver_b2.npy')); n2 = np.load(W('deliver_n2.npy')); cl2 = np.load(W('deliver_cloud2.npy'))
RINGS = [(0.5, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, 8.0)]
SECT = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
out = {}
for nm, st in D['named_stars'].items():
    cx, cy = st['core_centroid_px'] or st['predicted_px']
    r = int(8.5 * 60 / ps)
    x0, x1, y0, y1 = int(cx) - r, int(cx) + r + 1, int(cy) - r, int(cy) + r + 1
    yy, xx = np.mgrid[max(y0, 0):min(y1, b2.shape[0]), max(x0, 0):min(x1, b2.shape[1])]
    sub = b2[max(y0, 0):min(y1, b2.shape[0]), max(x0, 0):min(x1, b2.shape[1])]; subc = rgb[max(y0, 0):min(y1, b2.shape[0]), max(x0, 0):min(x1, b2.shape[1])]
    rr = np.hypot(xx - cx, yy - cy) * ps / 60
    ang = (np.degrees(np.arctan2(-(xx - cx), -(yy - cy))) + 360 + 22.5) % 360        # 0 = north, 90 = east (east is left: -x)
    sec = (ang // 45).astype(int)
    rings = []
    for a, b in RINGS:
        m = (rr >= a) & (rr < b) & np.isfinite(sub)
        secs = [float(np.median(sub[m & (sec == i)])) if (m & (sec == i)).sum() > 200 else None for i in range(8)]
        v = [s for s in secs if s is not None]
        col = [float(np.median(subc[..., c_][m])) for c_ in range(3)] if m.sum() > 500 else None
        rings.append(dict(ring_arcmin=[a, b], level_dn_by_sector=dict(zip(SECT, secs)), mean_of_sectors_dn=float(np.mean(v)) if v else None, brightest_minus_faintest_sector_dn=float(max(v) - min(v)) if v else None,
                          brightest_sector=SECT[int(np.argmax([s if s is not None else -1e9 for s in secs]))] if v else None, level_scaled_to_merope_magnitude_dn=float(np.mean(v) * 10 ** (0.4 * (VMAG[nm] - 4.18))) if v else None,
                          median_rgb_dn=col, b_over_g=float(col[2] / col[1]) if col and col[1] > 2 else None, r_over_g=float(col[0] / col[1]) if col and col[1] > 2 else None))
    out[nm] = dict(v_mag=VMAG[nm], cloud_stack_share_at_star=st['cloud_stack_share'], stacks=st['stacks'], rings=rings)
REF = 'Alcyone'
limit = [dict(ring_arcmin=list(RINGS[i]), alcyone_level_scaled_to_merope_magnitude_dn=out[REF]['rings'][i]['level_scaled_to_merope_magnitude_dn']) for i in range(len(RINGS))]
for nm in out:
    for i, rg in enumerate(out[nm]['rings']):
        if rg['mean_of_sectors_dn'] is None: continue
        glare = limit[i]['alcyone_level_scaled_to_merope_magnitude_dn'] * 10 ** (-0.4 * (VMAG[nm] - 4.18))
        rg['glare_upper_limit_dn'] = float(glare); rg['above_glare_limit_dn'] = float(rg['mean_of_sectors_dn'] - glare)
        rg['share_that_is_not_glare_at_least'] = float(max(0.0, 1 - glare / rg['mean_of_sectors_dn'])) if rg['mean_of_sectors_dn'] > 1.0 else None
json.dump(dict(rings_arcmin=RINGS, sectors=SECT, glare_upper_limit=limit, reference_star=REF, stars=out, noise_note='one sector of the 1 to 2 arcmin ring holds about 2000 px; the median of that many pixels is good to about 0.15 DN in a clear stack; unevenness between stacks is 1 to 3 DN'), open(W('p12b_glare.json'), 'w'), indent=1)
print('green level in rings (DN above the zero): mean of 8 sectors | brightest - faintest sector (which) | scaled to Merope\'s magnitude | glare limit (Alcyone\'s curve scaled to the star) | above it | B/G R/G')
for nm in out:
    print('%-9s V %.2f cloud share %.2f' % (nm, VMAG[nm], out[nm]['cloud_stack_share_at_star'] or 0))
    for rg in out[nm]['rings']:
        if rg['mean_of_sectors_dn'] is None: continue
        print('    %3.1f-%3.1f\'  %7.1f | %6.1f (%-2s) | scaled %7.1f | glare <= %6.1f  above %6.1f %s | B/G %s R/G %s' % (*rg['ring_arcmin'], rg['mean_of_sectors_dn'], rg['brightest_minus_faintest_sector_dn'], rg['brightest_sector'], rg['level_scaled_to_merope_magnitude_dn'],
              rg['glare_upper_limit_dn'], rg['above_glare_limit_dn'], ('(>= %2.0f%% not glare)' % (100 * rg['share_that_is_not_glare_at_least'])) if rg['share_that_is_not_glare_at_least'] is not None else '', '%.2f' % rg['b_over_g'] if rg['b_over_g'] else '  - ', '%.2f' % rg['r_over_g'] if rg['r_over_g'] else '  - '))
