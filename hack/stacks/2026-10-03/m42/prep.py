"""Reading one frame for the pipeline: black-subtracted colour planes with the hot pixels and single-frame spikes
repaired (the 3x3 median of the same plane), plus the per-plane masks of pixels at the ceiling and near it."""
import json
import numpy as np, cv2
from common import *

_S1 = None; _HOT = {}


def s1():
    global _S1
    if _S1 is None: _S1 = {f['stamp']: f for f in json.load(open(W('s1.json')))['frames']}
    return _S1


def hot(kind):
    if kind not in _HOT: _HOT[kind] = np.load(W('hot_%s.npy' % kind))
    return _HOT[kind]


def load_repaired(stamp, masks=False):
    fr = s1()[stamp]
    planes, ceil, meta = load_planes(fr['path'])
    corner = list(zip(fr['dark_block']['clipped_mean'], fr['dark_block']['clipped_std']))
    spikes = repair(planes, hot('short' if fr['set'] == 'short' else 'long'), corner)
    # AFTER the repair (a hot pixel is not a clipped star): pixels within a margin of the ceiling, and at it, per plane
    near = planes >= NEAR_CEILING
    ceil = planes >= (CEILING_RAW - BLACK)
    if masks: return planes, ceil, near, spikes
    return planes
