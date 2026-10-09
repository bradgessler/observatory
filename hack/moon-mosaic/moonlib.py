"""Shared pieces of the Moon mosaic: reading a RAW without interpolation, and making a picture of
its relief that features can be matched on. Everything here is plain arithmetic on the camera's
numbers; nothing is invented, and the RAW files are only ever read.
"""
import os
import cv2
import numpy as np
import rawpy

ARCSEC_PER_PX = 0.3955 * 2  # 3.9 um pixels at 2032 mm, binned 2x2 into colour cells


def raw_path(src, jpg_name):
    """g007.JPG's RAW is g008.ARW: the camera's two files were numbered one after the other."""
    stem = os.path.splitext(jpg_name)[0]
    prefix, num = stem[0], stem[1:]
    return os.path.join(src, "%s%0*d.ARW" % (prefix, len(num), int(num) + 1))


def load(path):
    """One RAW as four half-size planes, linear, 0 (black) to 1 (the sensor's ceiling).

    Each 2x2 colour cell of the sensor (R G / G B) becomes one pixel: R, the two greens, B. No
    demosaicing, so no pixel is interpolated from its neighbours. Returns
    {g: mean of the two greens, r, b, noise: the greens' difference (pure noise: see spectrum.py),
     clip: where any of the four is at the ceiling, wb: the camera's white balance (r, g, b)}.
    """
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32)
        pat, desc = r.raw_pattern, r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32)
        white = float(r.white_level)
        wb = np.array(r.camera_whitebalance[:3], np.float32)
    planes = {}
    for y in (0, 1):
        for x in (0, 1):
            c = desc[pat[y, x]]
            p = (raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]])
            planes.setdefault(c, []).append(p)
    g1, g2 = planes["G"]
    r_, b_ = planes["R"][0], planes["B"][0]
    clip = (np.maximum(np.maximum(g1, g2), np.maximum(r_, b_)) >= 0.98)
    return dict(g=(g1 + g2) / 2, r=r_, b=b_, noise=(g1 - g2), clip=clip, wb=wb / wb[1])


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
    return g / (cv2.GaussianBlur(g, (0, 0), sigma) + 1e-4)


def relief8(g, mask):
    """`relief` as an 8-bit picture for the feature finder, grey (128) off the Moon."""
    rel = np.clip((relief(g) - 1.0) * 400 + 128, 0, 255)
    rel[mask == 0] = 128
    return rel.astype(np.uint8)
