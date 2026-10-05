"""Global alignment: where each frame sits on one common Moon.

Craters are found in every frame (SIFT, a classical corner-and-blob detector) on the relief picture,
matched between frames, and each frame's rotation + shift onto the reference is solved from the
matches that agree (RANSAC). Scale is solved too and must come out 1: the same telescope took them all.
Frames that don't overlap the reference enough are matched to frames already placed.

Changed for a real mosaic (four panels that share only a fifth of their area):
  - the frames a new frame is matched against are spread over every pointing already placed (two per
    pointing), not the twelve that show the most Moon, which would all be one panel;
  - then two rounds in which every frame is solved again, against all its placed neighbours at once
    (matches to up to eight overlapping frames, pooled, one RANSAC fit): a frame placed through a
    thin strip of overlap is held by everything it overlaps instead.

Reads grades.csv and the RAWs; writes features/<name>.npz (cache) and transforms.json.
"""
import csv, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
import moonlib

SRC = os.path.expanduser(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
FEAT = os.path.join(HERE, "features")
MIN_INLIERS = 25


def features(name):
    out = os.path.join(FEAT, name + ".npz")
    if os.path.exists(out):
        return name
    f = moonlib.load(moonlib.raw_path(SRC, name))
    mask = moonlib.lit_mask(f["g"])
    lit = float(mask.mean())
    inner = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25)))
    inner[cv2.dilate(f["clip"].astype(np.uint8), np.ones((9, 9), np.uint8)) > 0] = 0
    sift = cv2.SIFT_create(nfeatures=6000, contrastThreshold=0.02)
    kp, des = sift.detectAndCompute(moonlib.relief8(f["g"], mask), inner)
    pts = np.array([k.pt for k in kp], np.float32).reshape(-1, 2)
    face = float(np.median(f["g"][mask > 0])) if lit > 0 else 0.0
    np.savez_compressed(out, pts=pts, des=des if des is not None else np.zeros((0, 128), np.float32), lit=lit,
                        clip=float((f["clip"] & (mask > 0)).sum()) / max(int(mask.sum()), 1), face=face, shape=f["g"].shape)
    return name


def load_feat(name):
    z = np.load(os.path.join(FEAT, name + ".npz"))
    return dict(name=name, pts=z["pts"], des=z["des"], lit=float(z["lit"]), clip=float(z["clip"]), face=float(z["face"]), shape=tuple(z["shape"]))


def pairs(a, b):
    """Matched points of frame a and frame b (the ratio test), or None."""
    if len(a["pts"]) < 30 or len(b["pts"]) < 30:
        return None
    kn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(a["des"], b["des"], k=2)
    good = [m for m, n in kn if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return None
    return np.float32([a["pts"][m.queryIdx] for m in good]), np.float32([b["pts"][m.trainIdx] for m in good])


def fit(pa, pb):
    M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=5000, confidence=0.999)
    if M is None or int(inl.sum()) < MIN_INLIERS:
        return None
    k = inl.ravel() > 0
    res = (pa[k] @ M[:, :2].T + M[:, 2]) - pb[k]
    return M, int(k.sum()), float(np.sqrt((res ** 2).sum(1).mean()))


def solve(a, b):
    """Frame a onto frame b: (2x3 matrix, inliers, rms px) or None."""
    p = pairs(a, b)
    return fit(*p) if p else None


def describe(M):
    scale = float(np.hypot(M[0, 0], M[1, 0])); rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    return scale, rot


def compose(M_ab, M_bc):
    A = np.vstack([M_ab, [0, 0, 1]]); B = np.vstack([M_bc, [0, 0, 1]])
    return (B @ A)[:2]


def centre(M, shape):
    h, w = shape
    return np.asarray(M, float) @ np.array([w / 2, h / 2, 1.0])


def spread(placed, feats, per=2, apart=200.0):
    """Anchors: for every pointing already placed (frame centres within `apart` px), the `per`
    frames with the most features."""
    chosen = []
    for n in sorted(placed, key=lambda n: -len(feats[n]["pts"])):
        c = centre(placed[n]["M"], feats[n]["shape"])
        near = sum(1 for m in chosen if np.hypot(*(centre(placed[m]["M"], feats[m]["shape"]) - c)) < apart)
        if near < per:
            chosen.append(n)
    return chosen


def refine_one(args):
    n, others, Ms = args
    fa = load_feat(n); PA, PB, used = [], [], 0
    for o in others:
        p = pairs(fa, load_feat(o))
        if p is None:
            continue
        pa, pb = p
        PA.append(pa); PB.append(pb @ np.asarray(Ms[o], np.float32)[:, :2].T + np.asarray(Ms[o], np.float32)[:, 2]); used += 1
    if not PA:
        return n, None, 0
    s = fit(np.vstack(PA), np.vstack(PB))
    return n, s, used


if __name__ == "__main__":
    os.makedirs(FEAT, exist_ok=True)
    rows = [r for r in csv.DictReader(open(os.path.join(HERE, "grades.csv"))) if float(r["lit"]) >= 0.03]
    names = [r["name"] for r in rows if os.path.exists(moonlib.raw_path(SRC, r["name"]))]
    print(len(rows), "frames show the Moon;", len(names), "have their RAW here")
    with ProcessPoolExecutor(6) as ex:
        list(ex.map(features, names))
    feats = {n: load_feat(n) for n in names}

    # the reference: the most Moon in one frame, not badly clipped, with plenty to match on
    forced = os.environ.get("MOON_REFERENCE")
    ref = feats[forced] if forced else max((f for f in feats.values() if f["clip"] < 0.06), key=lambda f: f["lit"] * min(len(f["pts"]), 3000))
    print("reference:", ref["name"], "lit %.0f%%" % (100 * ref["lit"]), "clipped %.1f%% of the face" % (100 * ref["clip"]), len(ref["pts"]), "features")

    placed = {ref["name"]: dict(M=np.float32([[1, 0, 0], [0, 1, 0]]), inliers=0, rms=0.0, via=None)}
    todo = [n for n in names if n != ref["name"]]
    for rnd in range(6):
        anchors = spread(placed, feats)
        left = []; new = {}
        for n in todo:
            best = None
            for a in anchors:
                s = solve(feats[n], feats[a])
                if s and (best is None or s[1] > best[1][1]):
                    best = (a, s)
            if best is None:
                left.append(n); continue
            a, (M, inl, rms) = best
            new[n] = dict(M=compose(M, placed[a]["M"]), inliers=inl, rms=rms, via=a)
        placed.update(new)
        print("round", rnd + 1, "anchors", len(anchors), "placed", len(placed), "left", len(left))
        todo = left
        if not todo or not new:
            break

    # every frame again, against all its neighbours at once
    for rnd in range(2):
        Ms = {n: np.asarray(p["M"], float).tolist() for n, p in placed.items()}
        C = {n: centre(placed[n]["M"], feats[n]["shape"]) for n in placed}
        jobs = []
        for n in placed:
            if n == ref["name"]:
                continue
            by = sorted((m for m in placed if m != n), key=lambda m: np.hypot(*(C[m] - C[n])))
            same = [m for m in by if np.hypot(*(C[m] - C[n])) < 200][:4]
            other = [m for m in spread({m: placed[m] for m in by if m not in same}, feats)]
            jobs.append((n, same + other, Ms))
        with ProcessPoolExecutor(6) as ex:
            res = list(ex.map(refine_one, jobs))
        moved = []
        for n, s, used in res:
            if s is None:
                continue
            M, inl, rms = s
            moved.append(float(np.hypot(*(centre(M, feats[n]["shape"]) - C[n]))))
            placed[n].update(M=M, inliers=inl, rms=rms, via="%d neighbours" % used)
        print("refine", rnd + 1, ": frames moved by median %.2f px, most %.2f px" % (np.median(moved), np.max(moved)))

    out = {}
    for n, p in placed.items():
        sc, rot = describe(p["M"])
        out[n] = dict(M=np.asarray(p["M"], float).tolist(), scale=sc, rot_deg=rot, inliers=p["inliers"], rms_px=p["rms"], via=p["via"],
                      lit=feats[n]["lit"], clip=feats[n]["clip"], face=feats[n]["face"], features=int(len(feats[n]["pts"])))
    json.dump(dict(reference=ref["name"], shape=[int(v) for v in ref["shape"]], placed=out,
                   unplaced={n: dict(lit=feats[n]["lit"], face=feats[n]["face"], features=int(len(feats[n]["pts"]))) for n in todo}),
              open(os.path.join(HERE, "transforms.json"), "w"), indent=1)
    sc = np.array([v["scale"] for v in out.values()]); ro = np.array([v["rot_deg"] for v in out.values()])
    il = np.array([v["inliers"] for k, v in out.items() if k != ref["name"]]); rm = np.array([v["rms_px"] for k, v in out.items() if k != ref["name"]])
    print("scale: min %.4f max %.4f   rotation: min %.2f max %.2f deg" % (sc.min(), sc.max(), ro.min(), ro.max()))
    print("matches that agree per frame: median %d, min %d   fit error: median %.2f px, worst %.2f px" % (np.median(il), il.min(), np.median(rm), rm.max()))
    print("not placed:", todo)
