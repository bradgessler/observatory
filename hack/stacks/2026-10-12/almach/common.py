"""Shared pieces for the Almach (Gamma Andromedae) picture of 12/13 October 2026: Sony a6000 on the 8SE (2,084 mm, 3.92 um pixels,
0.388 arcsec per sensor pixel), 13 short frames at ISO 400, 1/60 s, EQ6-R tracking. The pair (a gold primary, a fainter blue
companion about 10 arcsec away) is about 25 sensor pixels apart, so everything here works on a small crop of the RAW around the star.

RAWs are read in place and never written. Every knob is an environment variable; with none set the scripts reproduce the delivered run.
Plane order everywhere: R, G1, G2, B. RAW colour planes, no demosaic. The a6000's 2 x 2 cell is  R G1 / G2 B  (rawpy: pattern
[[0, 1], [3, 2]], colours 'RGBG'), so sensor pixel (x, y) with (x % 2, y % 2) = (0,0) is R, (1,0) G1, (0,1) G2, (1,1) B.
Plane pixel (X, Y) of a plane with cell offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy)."""
import glob, json, os
import numpy as np, rawpy

NIGHT = os.path.expanduser(os.environ.get('ALMACH_NIGHT', '~/.observatory/nights/2026-10-12-a6000'))
OUT = os.environ.get('ALMACH_OUT', os.path.join(NIGHT, 'almach'))
WORK = os.environ.get('ALMACH_WORK', os.path.join(OUT, 'work'))
SCR = os.path.dirname(os.path.abspath(__file__))
TARGET = dict(name='Almach (Gamma Andromedae)', ra_deg=30.9748, dec_deg=42.3298)
# catalogue double star (WDS 02039+4220, STF 205 AB): about 9.6 arcsec at about 63 degrees. Quoted from memory; the recipe says so.
CATALOGUE = dict(separation_arcsec=9.6, position_angle_deg=63.0, note='approximate, remembered not looked up; the pair is slowly widening/closing so epoch matters')
ISO, SHUTTER = 400, '1/60'
T0, T1 = '20261013-083800', '20261013-084700'      # file-name time window (UTC), inclusive
POINT_RADIUS_DEG = 1.5
SCALE = 0.388                                       # arcsec per sensor pixel
BLACK = 512.0
CEILING = 16383.0                                   # 14-bit RAW; the ADC cannot read more than white_level - black
# the crop: a box on the sensor (sensor px) that holds the star through the whole run (it drifts about 60 px)
CROP = dict(x0=2500, y0=1500, w=1000, h=1100)       # even numbers so the 2 x 2 cells line up
NPX = 2                                             # colour cell size


def W(name):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def jload(name):
    return json.load(open(W(name)))


def jdump(obj, name):
    with open(W(name), 'w') as f:
        json.dump(obj, f, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))


def frames():
    return jload('step1_frames.json')['used_files']


def planes(a):
    """a: (h, w) sensor array whose first pixel is the R of a cell; returns (4, h/2, w/2): R, G1, G2, B."""
    return np.stack([a[0::2, 0::2], a[0::2, 1::2], a[1::2, 0::2], a[1::2, 1::2]])


OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]             # (ox, oy) of R, G1, G2, B in the cell
PLANE_NAMES = ['R', 'G1', 'G2', 'B']


def read_crop(path, box=None):
    """The black-subtracted RAW crop (float32), plus the file's own white level and black level."""
    b = box or CROP
    r = rawpy.imread(path)
    img = r.raw_image_visible
    assert list(map(list, r.raw_pattern)) == [[0, 1], [3, 2]] and r.color_desc == b'RGBG', 'unexpected colour pattern'
    a = img[b['y0']:b['y0'] + b['h'], b['x0']:b['x0'] + b['w']].astype(np.float32) - BLACK
    return a, dict(white_level=int(r.white_level), black=[int(x) for x in r.black_level_per_channel])
