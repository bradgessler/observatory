"""Rerun with the twilight-based flat, step f1: the repaired, black-subtracted planes of the USED frames again
(the core run's cache was deleted). Same rule and same hot-pixel map as step2_hot.py; the count of single-frame
spikes per frame is compared with the count the core run recorded (step2.json), as a check that the planes are
the same ones."""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np, cv2
from common import *
CAL = os.path.join(NIGHT, 'm31', 'mosaic', 'calibration-from-core-run')
s1 = {f['stamp']: f for f in json.load(open(W('step1.json')))['frames']}
s2 = {f['stamp']: f for f in json.load(open(W('step2.json')))['frames']}
USED = [u['stamp'] for u in json.load(open(W('step7_select.json')))['used']]
hot = np.load(os.path.join(CAL, 'hotmap.npy'))

def one(stamp):
    fr = s1[stamp]
    P4, ceil, meta = load_planes(fr['path']); trans = 0
    for p in range(4):
        P = P4[p]; med3 = cv2.medianBlur(P, 3)
        s0 = fr['corner'][p]['clipped_std']; l0 = max(fr['corner'][p]['clipped_mean'], 1.0)
        s = s0 * np.sqrt(np.maximum(med3, l0) / l0)
        spike = (P - med3) > (8 * s + 0.5 * np.clip(med3, 0, None)); spike &= ~hot[p]
        trans += int(spike.sum()); bad = hot[p] | spike; P[bad] = med3[bad]
    np.save(W('planes/' + stamp + '.npy'), P4)
    return stamp, trans

if __name__ == '__main__':
    os.makedirs(W('planes'), exist_ok=True)
    with ProcessPoolExecutor(6) as ex: res = list(ex.map(one, USED))
    bad = [(s, t, s2[s]['transient_spikes_replaced']) for s, t in res if t != s2[s]['transient_spikes_replaced']]
    print(len(res), 'frames; spike counts differing from the core run:', bad)
    json.dump(dict(frames=[dict(stamp=s, transient_spikes_replaced=t, core_run=s2[s]['transient_spikes_replaced']) for s, t in res], all_equal=not bad), open(W('f1_planes.json'), 'w'), indent=1)
