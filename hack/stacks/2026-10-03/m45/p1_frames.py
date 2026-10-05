"""Step 1: find the frames, group them into panels, measure each frame's levels.
Frames in the window at 10 s ISO 1600 are kept (the 2 s ISO 6400 finder frames are left out). A new group starts
when the mount's pointing in the sidecar moves by more than 0.03 degrees or more than 60 s pass between shutter
presses; the groups are then named in the order of the plan (centre check, (0,0) first try, (1,0) ... (2,2), (0,0)
retake) and the mount's declination is checked against the plan (the mount's own pointing is only good to about
6 arcmin here; the plate solve of each stack places it later).
Per frame: 3-sigma clipped mean and scatter of each colour plane in the top-left corner, the plane medians, a
12 x 8 grid of block levels, the as-shot white balance, the count of pixels at the ceiling."""
import json
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from c import *


def probe(fr):
    planes, ceil, meta = load_planes(fr['path'])
    G = (planes[1] + planes[2]) / 2
    corner = [clipped_stats(planes[p][CORNER]) for p in range(4)]
    meta['corner'] = [dict(clipped_mean=c[0], clipped_std=c[1]) for c in corner]
    meta['corner_green'] = clipped_stats(G[CORNER])[0]
    bs = 251
    meta['blocks'] = [[[clipped_stats(planes[p][i * bs:(i + 1) * bs:2, j * bs:(j + 1) * bs:2], k=2.5)[0] for j in range(W2 // bs)] for i in range(H2 // bs)] for p in range(4)]
    meta['median_plane'] = [float(np.median(planes[p][::4, ::4])) for p in range(4)]
    meta['ceiling_pixels'] = [int(ceil[p].sum()) for p in range(4)]
    return meta


if __name__ == '__main__':
    allf = frame_list()
    ok = [f for f in allf if f['exposure_s'] == EXPOSURE_S and f['iso'] == ISO]
    left = [f for f in allf if f not in ok]
    print(len(allf), 'stills in the window;', len(ok), 'at 10 s ISO 1600; left out (finder frames):', [(f['stamp'][9:], f['exposure_s'], f['iso']) for f in left])
    groups = []
    for f in ok:
        if groups and abs(f['dec_deg'] - groups[-1][-1]['dec_deg']) < 0.03 and abs(f['ra_deg'] - groups[-1][-1]['ra_deg']) * np.cos(np.radians(DEC0)) < 0.03 and tsec(f['t']) - tsec(groups[-1][-1]['t']) < 60:
            groups[-1].append(f)
        else:
            groups.append([f])
    assert len(groups) == len(PLAN), [(g[0]['stamp'], len(g)) for g in groups]
    table = []
    for g, (name, e, n) in zip(groups, PLAN):
        dd = (np.mean([f['dec_deg'] for f in g]) - DEC0) * 60; de = (np.mean([f['ra_deg'] for f in g]) - RA0) * 60 * np.cos(np.radians(DEC0))
        for f in g: f['panel'] = name
        table.append(dict(panel=name, frames=len(g), first=g[0]['stamp'], last=g[-1]['stamp'], plan_offset_arcmin=[e, n], mount_offset_arcmin=[float(de), float(dd)]))
        print('%-5s %2d frames %s .. %s  plan %+6.1f E %+6.1f N   mount says %+6.1f E %+6.1f N' % (name, len(g), g[0]['stamp'][9:], g[-1]['stamp'][9:], e, n, de, dd))
    with ProcessPoolExecutor(8) as ex:
        metas = list(ex.map(probe, ok))
    out = []
    for f, m in zip(ok, metas):
        d = dict(f); d.update(m); out.append(d)
        b = np.array(m['blocks'][1])
        print('%s %-5s corner G %.1f R %.1f B %.1f std G1 %.1f | median R %.0f G %.0f B %.0f | G1 blocks min %.0f med %.0f max %.0f | ceiling px %s | wb %s alt %.1f' % (
            f['stamp'], f['panel'], m['corner_green'], m['corner'][0]['clipped_mean'], m['corner'][3]['clipped_mean'], m['corner'][1]['clipped_std'], m['median_plane'][0], m['median_plane'][1], m['median_plane'][3],
            b.min(), np.median(b), b.max(), m['ceiling_pixels'], [int(v) for v in m['wb'][:3]], f['alt_deg']), flush=True)
    json.dump(dict(frames=out, left_out=left, groups=table), open(W('p1.json'), 'w'), indent=1)
