"""Shared pieces of the Moon mosaic: reading a RAW without interpolation, and making a picture of
its relief that features can be matched on. Everything here is plain arithmetic on the camera's
numbers; nothing is invented, and the RAW files are only ever read.

Changed for the last-quarter Moon of 2026-10-04 (the list is in run.sh's recipe.json): the RAW's
name is the JPEG's name; each colour plane is divided by the night's master flat and has the
frame's own sky level and its cloud glow taken off; the hair's shadow counts as no data; the
numbers are multiplied by GAIN so the thresholds tuned on the ISO 800 night still mean the same
thing at ISO 100.
"""
import json, os
import cv2
import numpy as np
import rawpy

ARCSEC_PER_PX = 0.3881 * 2  # plate-solved this night: 0.3881 arcsec per sensor pixel, binned 2x2 into colour cells
GAIN = 4.0                  # ISO 100 instead of 800: the lit Moon peaks at 0.19 of the sensor's range. 1.0 here = a quarter of the ceiling.
HERE = os.path.dirname(os.path.abspath(__file__))
FLAT_PATH = os.environ.get("MOON_FLAT", os.path.join(HERE, "flat.npz"))   # MOON_FLAT=none: no flat
SKY_PATH = os.path.join(HERE, "sky.json")
GLOW_DIR = os.environ.get("MOON_GLOW", os.path.join(HERE, "glow"))        # MOON_GLOW=none: the cloud glow is left in
# The hair on the sensor: a shadow at the top edge, a little right of centre, that crept sideways
# through the flats (so no flat can divide it out). These colour cells (x0, x1, y0, y1) count as no data.
HAIR = (1790, 1990, 0, 110)
_flat = None
_sky = None


def raw_path(src, jpg_name):
    """This night the box named both files alike: <stamp>-DSCnnnnn.JPG and .ARW."""
    return os.path.join(src, os.path.splitext(jpg_name)[0] + ".ARW")


def flat():
    """The master flat: four planes keyed by their place in the 2x2 cell ('00', '01', '10', '11'),
    each 1.0 at its own median. None if there is no flat (then nothing is divided)."""
    global _flat
    if _flat is None:
        if FLAT_PATH != "none" and os.path.exists(FLAT_PATH):
            z = np.load(FLAT_PATH); _flat = {k: z[k] for k in ("00", "01", "10", "11")}
        else:
            _flat = {}
    return _flat or None


def sky_table():
    global _sky
    if _sky is None:
        _sky = json.load(open(SKY_PATH)) if os.path.exists(SKY_PATH) else {}
    return _sky


def cells(path):
    """One RAW as its four colour planes, linear, 0 (black) to 1 (the sensor's ceiling), nothing
    else done: [(colour, x, y, plane)], and the camera's white balance (r, g, b)."""
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat, desc = r.raw_pattern, r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = np.array(r.camera_whitebalance[:3], np.float32)
    out = []
    for y in (0, 1):
        for x in (0, 1):
            out.append((desc[pat[y, x]], x, y, (raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]])))
    return out, wb / wb[1]


def measure_sky(pl):
    """The frame's own sky level, per colour plane, from flat-fielded planes (0..1 of the ceiling).
    Sky is what lies more than 500 cells (6.5 arcmin) from the lit Moon; if the Moon leaves less
    than 3% of the frame that far away, the farthest 3%. The level is the mean of the pixels within
    +-12 counts of the median there (the RAW is quantised in steps of 4 counts, so a bare median
    would be too). Also returns the glow: the brightness of the ring 40-120 cells outside the lit
    Moon, above sky, as a share of the lit face's median: cloud lifts it."""
    g = (pl[1][3] + pl[2][3]) / 2 if pl[1][0] == "G" else None
    if g is None:
        g = np.mean([p for c, _, _, p in pl if c == "G"], 0)
    m = (cv2.GaussianBlur(g, (0, 0), 2) > 0.005).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2 or st[1:, cv2.CC_STAT_AREA].max() < 5000:
        far = np.ones(g.shape, bool); moon = np.zeros(g.shape, np.uint8); dist = None
    else:
        k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])); moon = (lab == k).astype(np.uint8)
        dist = cv2.distanceTransform(1 - moon, cv2.DIST_L2, 3)
        far = dist > 500
        if far.mean() < 0.03:
            far = dist >= np.percentile(dist, 97)
    step = 12.0 / (16383 - 512)
    sky = []
    for c, x, y, p in pl:
        v = p[far]; med = float(np.median(v)); sky.append(float(v[np.abs(v - med) <= step].mean()))
    face = float(np.median(g[moon > 0])) if moon.sum() else 0.0
    gsky = (sky[1] + sky[2]) / 2
    glow = 0.0
    if dist is not None:
        ring = (dist > 40) & (dist < 120)
        if ring.sum() > 1000 and face > 0:
            glow = float((np.mean(g[ring]) - gsky) / max(face - gsky, 1e-6))
    return dict(sky=sky, face=face, glow=glow, far_share=float(far.mean()))


def planes(path):
    """The four colour planes ready to stack: [(colour, x, y, plane)], white balance, and where
    the RAW is at its ceiling (or under the hair). Each plane: divided by the master flat's plane,
    the frame's own sky level and its cloud glow taken off, times GAIN."""
    pl, wb = cells(path)
    clip = np.max([p for _, _, _, p in pl], 0) >= 0.98
    clip[HAIR[2]:HAIR[3], HAIR[0]:HAIR[1]] = True
    F = flat()
    if F:
        pl = [(c, x, y, p / F["%d%d" % (y, x)]) for c, x, y, p in pl]
    key = os.path.basename(path)
    sky = sky_table().get(key)
    if sky is None:
        sky = measure_sky(pl)
    pl = [(c, x, y, p - s) for (c, x, y, p), s in zip(pl, sky["sky"])]
    gp = os.path.join(GLOW_DIR, os.path.splitext(key)[0] + ".JPG.npz")
    if GLOW_DIR != "none" and os.path.exists(gp):
        # the cloud's glow over this frame (glow.py): a smooth surface per plane, fitted where the truth is black
        z = np.load(gp); h, w = pl[0][3].shape
        pl = [(c, x, y, p - cv2.resize(z["p%d" % i], (w, h), interpolation=cv2.INTER_LINEAR)) for i, (c, x, y, p) in enumerate(pl)]
    pl = [(c, x, y, p * GAIN) for c, x, y, p in pl]
    return pl, wb, clip


def load(path):
    """One RAW as four half-size planes, linear, sky at 0, 1.0 = a quarter of the sensor's ceiling.

    Each 2x2 colour cell of the sensor (R G / G B) becomes one pixel: R, the two greens, B. No
    demosaicing, so no pixel is interpolated from its neighbours. Returns
    {g: mean of the two greens, r, b, noise: the greens' difference (pure noise),
     clip: where any of the four is at the ceiling, wb: the camera's white balance (r, g, b)}.
    """
    pl, wb, clip = planes(path)
    by = {}
    for c, x, y, p in pl:
        by.setdefault(c, []).append(p)
    g1, g2 = by["G"]
    return dict(g=(g1 + g2) / 2, r=by["R"][0], b=by["B"][0], noise=(g1 - g2), clip=clip, wb=wb)


def lit_mask(g, floor=0.02):
    """The Moon's lit face: the largest piece brighter than `floor` of the sensor's range."""
    m = (cv2.GaussianBlur(g, (0, 0), 2) > floor).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    if n < 2:
        return np.zeros_like(m)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == k).astype(np.uint8)


def relief(g, sigma=12.0):
    """Brightness divided by its own local average: craters and ridges stand out the same whether
    the frame is bright, dimmed by cloud, or near the limb. 1.0 is flat."""
    return g / (np.maximum(cv2.GaussianBlur(g, (0, 0), sigma), 0) + 1e-4)   # sky is at 0 now, so its average can dip below it


def relief8(g, mask):
    """`relief` as an 8-bit picture for the feature finder, grey (128) off the Moon."""
    rel = np.clip((relief(g) - 1.0) * 400 + 128, 0, 255)
    rel[mask == 0] = 128
    return rel.astype(np.uint8)
