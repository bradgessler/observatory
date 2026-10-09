"""Grade every Moon frame: what is in it and how good it is. Reads only, writes grades.csv.

Per frame (sensor orientation, EXIF rotation ignored), measured on the camera JPEG at half size:
  lit        fraction of the frame the Moon's lit face covers
  cx, cy     middle of the lit face (full-size pixels)
  cut        which frame edges the lit face runs into (L R T B), '-' if none
  face       median brightness of the lit face (0-255): clouds dim it
  sky        median brightness of the sky away from the Moon: haze and thin cloud lift it
  clip       fraction of the lit face at 250 or more in the JPEG
  detail     fine-detail contrast on the face: mean |Laplacian of Gaussian| / face brightness, x1000,
             measured away from the limb and from clipped areas. Higher is sharper, but it also
             depends on which part of the Moon is in view, so frames are compared patch by patch later.
"""
import csv, glob, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np

SRC = os.path.expanduser(sys.argv[1])
OUT = sys.argv[2]


def grade(path):
    g = cv2.imread(path, cv2.IMREAD_REDUCED_GRAYSCALE_2 | cv2.IMREAD_IGNORE_ORIENTATION)
    if g is None:
        return None
    h, w = g.shape
    f = g.astype(np.float32)
    sky0 = float(np.percentile(f, 5))
    top = float(np.percentile(f, 99.5))
    name = os.path.basename(path)
    if top - sky0 < 40:
        return dict(name=name, lit=0.0, cx=-1, cy=-1, cut="-", face=0, sky=round(sky0, 1), clip=0, detail=0)
    thr = sky0 + 0.35 * (top - sky0)
    lit = (f > thr).astype(np.uint8)
    # the largest lit piece is the Moon; specks and reflections are not
    n, lab, st, cen = cv2.connectedComponentsWithStats(lit, 8)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    moon = (lab == k).astype(np.uint8)
    x, y, bw, bh, area = st[k]
    m = 6
    cut = "".join(c for c, hit in (("L", x <= m), ("R", x + bw >= w - m), ("T", y <= m), ("B", y + bh >= h - m)) if hit) or "-"
    face = float(np.median(f[moon > 0]))
    far = cv2.dilate(moon, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (301, 301)))
    sky = float(np.median(f[far == 0])) if (far == 0).sum() > 1000 else sky0
    clipped = ((f >= 250) & (moon > 0)).astype(np.uint8)
    clip = float(clipped.sum()) / max(int(area), 1)
    inner = cv2.erode(moon, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (61, 61)))
    inner[cv2.dilate(clipped, np.ones((15, 15), np.uint8)) > 0] = 0
    if inner.sum() < 5000:
        detail = 0.0
    else:
        log = cv2.Laplacian(cv2.GaussianBlur(f, (0, 0), 1.2), cv2.CV_32F)
        detail = 1000.0 * float(np.abs(log[inner > 0]).mean()) / float(f[inner > 0].mean())
    return dict(name=name, lit=round(area / (w * h), 4), cx=round(2 * cen[k][0]), cy=round(2 * cen[k][1]), cut=cut,
                face=round(face, 1), sky=round(sky, 1), clip=round(clip, 4), detail=round(detail, 3))


if __name__ == "__main__":
    # this night: only the frames frames.py sorted as Moon exposures (MOON_ROLES can add the 1/160 s test)
    roles = os.environ.get("MOON_ROLES", "moon").split(",")
    sel = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "frames.json")))
    files = [os.path.join(SRC, r["name"]) for r in sel if r["role"] in roles and r["has_jpg"]]
    with ProcessPoolExecutor(8) as ex:
        rows = [r for r in ex.map(grade, files) if r]
    with open(OUT, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)
    print(len(rows), "frames graded ->", OUT)
