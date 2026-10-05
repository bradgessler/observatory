"""The stack at the sensor's own pixel scale (twice the working grid), without demosaicing.

A colour sensor has one colour per pixel: R G / G B in every 2x2 cell. The working stack treats a
cell as one pixel. Here each of the four planes keeps its own place: R sits a quarter of a cell up
and left of the cell's middle, B down and right, the greens on the other diagonal. Every frame's
planes are laid onto a grid twice as fine, each read at its true position (one Lanczos resampling
per plane), and the frames, each landing at a different fraction of a pixel, fill the fine grid in.
Alignment, grading and the choice of frames per patch are the working stack's (stack.py local).

Each plane is sampled at 0.78 arcsec; the optics and the air passed little finer than about 2,
so each plane holds nearly all there is, and reading it between its samples is arithmetic
(the sampling theorem), not a guess. The result has more pixels, not more detail.

Changed for the last-quarter mosaic: the planes come from moonlib.planes (flat, sky level and
cloud glow already taken off, the hair counted as no data), not straight from the RAW.

Usage: stack2x.py <raw dir> [KEEP]
"""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
import rawpy
import stack, moonlib

SRC = os.path.expanduser(sys.argv[1])
CW2, CH2 = stack.CW * 2, stack.CH * 2


def planes(path):
    """The four calibrated colour planes with where each sits in its cell: [(colour, x, y, plane)],
    the white balance, and where the frame has real data."""
    pl, wb, clip = moonlib.planes(path)
    return pl, wb, stack.usable(dict(clip=clip))


def fine(m):
    """A working-grid map on the fine grid (fine pixel X sits at working coordinate (X + 0.5) / 2 - 0.5)."""
    return cv2.resize(m, (CW2, CH2), interpolation=cv2.INTER_LINEAR)


def part(args):
    names, sels = args
    acc = np.zeros((CH2, CW2, 3), np.float32); wsum = np.zeros((CH2, CW2, 3), np.float32)
    ys, xs = stack.grid()
    yy = ((np.arange(stack.CH) - ys[0]) / stack.STEP).astype(np.float32); xx = ((np.arange(stack.CW) - xs[0]) / stack.STEP).astype(np.float32)
    gmx, gmy = np.meshgrid(np.clip(xx, 0, len(xs) - 1), np.clip(yy, 0, len(ys) - 1))
    for n, sel in zip(names, sels):
        if sel.sum() == 0:
            continue
        z = np.load(os.path.join(stack.LOCAL, n + ".npz")); pl, wb, ok = planes(moonlib.raw_path(SRC, n))
        mx, my = stack.maps_for(n, z["dx"], z["dy"])
        okl = cv2.remap(ok, mx, my, cv2.INTER_LINEAR)
        gain = cv2.remap(np.clip(z["gain"], 0.2, 20).astype(np.float32), gmx, gmy, cv2.INTER_LINEAR)
        feather = np.clip(cv2.distanceTransform((okl > 0.99).astype(np.uint8), cv2.DIST_L2, 3) / stack.FEATHER, 0, 1)
        wm = fine(cv2.remap(cv2.GaussianBlur(sel, (0, 0), 0.7), gmx, gmy, cv2.INTER_LINEAR) * feather / gain ** 2)
        gain2, mx2, my2 = fine(gain), fine(mx), fine(my)
        for colour, x, y, p in pl:
            c = "RGB".index(colour)
            # this plane's samples sit (x - 0.5) / 2 of a cell from the cell's middle: read it there
            v = cv2.remap(p, mx2 - (x - 0.5) / 2, my2 - (y - 0.5) / 2, cv2.INTER_LANCZOS4)
            acc[:, :, c] += v * gain2 * wm * wb[c]; wsum[:, :, c] += wm
    return acc, wsum


if __name__ == "__main__":
    keep = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
    # MOON_HALF=a or b: every other frame in time order, for the half-against-half test (frc.py)
    half = os.environ.get("MOON_HALF")
    names = None if not half else sorted(stack.NAMES)[(0 if half == "a" else 1)::2]
    used, Z, sel, n_cover = stack.weights(keep, names)
    jobs = [([used[i] for i in range(k, len(used), 6)], [sel[i] for i in range(k, len(used), 6)]) for k in range(6)]
    with ProcessPoolExecutor(6) as ex:
        parts = list(ex.map(part, jobs))
    acc = sum(p[0] for p in parts); wsum = sum(p[1] for p in parts)
    img = acc / np.maximum(wsum, 1e-9); img[wsum <= 0] = 0
    tag = "keep%02d-2x%s" % (round(keep * 100), "-half-" + half if half else "")
    np.savez_compressed(os.path.join(stack.HERE, "stack-%s.npz" % tag), img=img.astype(np.float32), depth=(wsum[:, :, 1] > 0).astype(np.float32))
    R = json.load(open(os.path.join(stack.HERE, "recipe-keep%02d.json" % round(keep * 100)))); R["frames_in_this_stack"] = len(used)
    R.update(tool="stack2x.py", canvas=[CW2, CH2], scale_arcsec_per_px=moonlib.ARCSEC_PER_PX / 2,
             fine_grid="each of the four colour planes of each RAW read at its own place in the 2x2 cell onto a grid twice as fine (Lanczos-4, once); no demosaicing")
    json.dump(R, open(os.path.join(stack.HERE, "recipe-%s.json" % tag), "w"), indent=1)
    print("stack %s: %dx%d at %.3f arcsec per pixel" % (tag, CW2, CH2, moonlib.ARCSEC_PER_PX / 2))
