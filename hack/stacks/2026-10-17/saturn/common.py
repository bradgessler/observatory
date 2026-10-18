"""SATURN, night of 17/18 October 2026 (frames of 18 October UTC). The reshoot Brad asked for.

The planet from about 490 frames at 1/60 s, ISO 800 (05:23:50 to 07:23:17 UTC), Sony a6000 at prime focus of the
Celestron 8SE (2,084 mm by plate solve, 0.388 arcsec per sensor px), EQ6-R unguided, not dithered. The moons from the two
centring frames at 2 s, ISO 6400 taken just before (05:22:15 and 05:22:54), in which the planet is blown out.

Template: hack/stacks/2026-10-03/saturn (saturn2.py: each colour plane laid on a grid 3x finer than the sensor at its own
place in the 2x2 cell, the field's turn taken back, red and blue slid onto green by least squares; finish2.py: Titan's
blur measured in the same frames and divided out by Richardson-Lucy; rlmodel.py: the model planet that says when to stop;
moons2.py: the long frames' glare taken off ring by ring; composite3.py: the planet set into the moon field, north up, at
the sensor's scale). That night's work was a heap of scripts; here it is one numbered pipeline.

Geometry: plane pixel (X, Y) of a plane with cell offset (ox, oy) sits at sensor pixel (2X + ox, 2Y + oy). The RAW's own
grid (rawpy raw_image_visible) is used everywhere, never the JPEG's EXIF orientation.

RAWs are read in place, never written; nothing is cached per frame. Every knob is an environment variable (SAT_*); with
none set the scripts reproduce the delivered run."""
import glob, json, os, sys
import numpy as np, rawpy

STILLS = os.path.expanduser(os.environ.get('SAT_STILLS', '~/.observatory/stills/2026-10-18'))   # read only
NIGHT = os.path.expanduser(os.environ.get('SAT_NIGHT', '~/.observatory/nights/2026-10-17-a6000'))
WORK = os.environ.get('SAT_WORK', os.path.join(NIGHT, 'saturn', 'work'))   # small intermediates (stacks, JSON); deleted at the end
HERE = os.path.dirname(os.path.abspath(__file__))
FINAL = os.environ.get('SAT_FINAL', os.path.join(HERE, 'final'))
DATE = '20261018'
T0, T1 = '052000', '072500'                 # the Saturn session, characters 10-15 of the file name, inclusive
SATURN_POINTING = (10.15, 1.45)             # RA, Dec deg (sidecar pointing); a frame within 0.5 deg of it is at Saturn
WORKERS = int(os.environ.get('SAT_WORKERS', '6'))   # the night's frames still arrive on this Mac
SCALE = 0.388                               # arcsec per sensor px (2,084 mm, 3.92 um); the long frames' plate solves refine it
FL_MM = 2084.0
H, Wd = 4024, 6024
OFFS = [(0, 0), (1, 0), (0, 1), (1, 1)]     # (ox, oy) of R, G1, G2, B
UP = 3                                      # fine grid: 3 per sensor px (6 per colour cell)
HALF = 60                                   # half-size (colour-cell) px kept each side of the planet for the stack: 93 arcsec square
TOOLS = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '.claude', 'skills', 'stack-pictures', 'tools'))
FTOOLS = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..', '.claude', 'skills', 'finish-pictures', 'tools'))


def W(name):
    os.makedirs(WORK, exist_ok=True)
    return os.path.join(WORK, name)


def jload(name): return json.load(open(W(name)))
def jsave(name, obj): json.dump(obj, open(W(name), 'w'), indent=1)


def minute(name):
    """Minutes since 00:00 UTC, from the file name (the time the shutter was pressed, to the second)."""
    b = os.path.basename(name); return int(b[9:11]) * 60 + int(b[11:13]) + int(b[13:15]) / 60


def raw_exif(path):
    """Exposure and ISO from the RAW's own EXIF (the sidecar can be wrong when settings changed)."""
    import tifffile
    with tifffile.TiffFile(path) as t:
        ex = t.pages[0].tags['ExifTag'].value
    e = ex.get('ExposureTime'); e = e[0] / e[1] if isinstance(e, tuple) else float(e)
    return float(e), int(ex.get('ISOSpeedRatings'))


def planes(path):
    """Black-subtracted colour planes R, G1, G2, B as fractions of full scale (4, 2012, 3012) float32, the white balance
    (as shot, green = 1), and how many raw pixels sit at the ceiling per plane."""
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32); pat = r.raw_pattern; desc = r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32); white = float(r.white_level); wb = np.array(r.camera_whitebalance[:3], np.float32)
    assert desc == 'RGBG' and pat.tolist() == [[0, 1], [3, 2]] and raw.shape == (H, Wd), (desc, pat.tolist(), raw.shape)
    P = np.stack([(raw[oy::2, ox::2] - black[pat[oy, ox]]) / (white - black[pat[oy, ox]]) for ox, oy in OFFS])
    return P, wb / wb[1]
