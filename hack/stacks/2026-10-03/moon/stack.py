"""Local alignment, per-patch grading, and the stack.

  ref      every placed frame laid on the common Moon (rotation + shift only) and averaged: soft, but
           geometrically neutral, because the air's wobble averages out. It is only a yardstick.
  local    per frame: a grid of patches, each matched against the yardstick to find how far the air
           (and the Moon's slow turning as the Earth carried the telescope) moved that patch; then,
           with the patch in its true place, how much real detail it holds there (noise subtracted).
  combine  per patch, the sharpest KEEP of the frames that cover it are averaged, each resampled once,
           straight from its RAW planes. Clipped pixels and pixels off a frame's edge count for nothing.

  photo    (new, for a mosaic under passing cloud) one number per frame: how much of the Moon's light
           got through, from where frames overlap. The clearest frames are 1.0.

Changed for the last-quarter mosaic: the yardstick is built from frames scaled to the same
brightness, weighted by their transparency squared and faded out at their sensor edges, so four
panels make one even Moon with no step where a panel ends; a frame's brightness map against the
yardstick falls back to its one number where there is no light to compare (the sky is at 0 now);
cloud is judged patch by patch against the clearest frame over the patch (see weights).

Usage: stack.py <raw dir> photo|ref|local|combine [KEEP]
"""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
import moonlib

SRC = os.path.expanduser(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
# an experiment can keep its own patch grid, yardstick and results beside the standard ones
LOCAL = os.path.join(HERE, os.environ.get("MOON_LOCAL", "local"))
REF = os.path.join(HERE, os.environ.get("MOON_REF", "ref.npz"))
SUFFIX = os.environ.get("MOON_TAG", "")
T = json.load(open(os.path.join(HERE, "transforms.json")))
REJECT = json.load(open(os.path.join(HERE, "reject.json"))) if os.path.exists(os.path.join(HERE, "reject.json")) else {}
NAMES = sorted(n for n in T["placed"] if n not in REJECT)
PHOTO = json.load(open(os.path.join(HERE, "photo.json"))) if os.path.exists(os.path.join(HERE, "photo.json")) else {}
MIN_K = int(os.environ.get("MOON_MINK", 4))   # a patch is never the average of fewer frames than this
CLEAR = float(os.environ.get("MOON_CLEAR", 1.5))   # a patch takes no frame that needs more than this times the gain of the clearest frame covering it...
AT_LEAST = int(os.environ.get("MOON_ATLEAST", 6))  # ...unless that leaves fewer than this many: then this many of the clearest
CUT = float(os.environ.get("MOON_CUT", 4.0))       # a frame that lost three quarters of its light (gain over 4) is not used at all
EPS = 0.01                         # brightness below which a frame's local gain leans on its one number (the lit face is 0.1 to 0.6)


def scalar(name):
    """What the frame is multiplied by to match the clearest frames (1 / its transparency)."""
    return float(PHOTO[name]["scale"]) if name in PHOTO else 1.0
H, W = T["shape"]
STEP, BOX, SEARCH = int(os.environ.get("MOON_STEP", 24)), int(os.environ.get("MOON_BOX", 48)), 7      # patch grid, patch size, how far a patch may have moved (px)
MIN_CORR = 0.45                    # a patch match weaker than this is not believed
FEATHER = 32                       # px over which a frame's contribution fades out at its edges


CROP = os.path.join(HERE, "crop.json")


def canvas():
    """The common Moon's frame. First big enough for every placed frame's sensor area; once the
    yardstick exists, cut down to the lit Moon plus a margin (crop.json)."""
    if os.path.exists(CROP):
        c = json.load(open(CROP)); return c["x0"], c["y0"], c["w"], c["h"]
    pts = []
    for n in NAMES:
        M = np.array(T["placed"][n]["M"])
        c = np.array([[0, 0, 1], [W, 0, 1], [0, H, 1], [W, H, 1]], float) @ M.T
        pts.append(c)
    pts = np.vstack(pts)
    x0, y0 = np.floor(pts.min(0)).astype(int)
    x1, y1 = np.ceil(pts.max(0)).astype(int)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


X0, Y0, CW, CH = canvas()


def placed(name):
    """Frame -> canvas matrix (2x3)."""
    M = np.array(T["placed"][name]["M"], np.float64)
    M[:, 2] -= (X0, Y0)
    return M


def warp(img, M, interp=cv2.INTER_LANCZOS4):
    return cv2.warpAffine(img, M, (CW, CH), flags=interp, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def usable(f):
    """Where a frame has real data: on the sensor, and not at its ceiling (grown a little)."""
    return (cv2.dilate(f["clip"].astype(np.uint8), np.ones((5, 5), np.uint8)) == 0).astype(np.float32)


# -- ref ---------------------------------------------------------------------------------------------

def edge_fade(shape, px):
    """1 inside a frame, falling to 0 over its last `px` at the sensor's edge."""
    h, w = shape
    y = np.minimum(np.arange(h), np.arange(h)[::-1])[:, None]; x = np.minimum(np.arange(w), np.arange(w)[::-1])[None, :]
    return np.clip(np.minimum(x, y) / float(px), 0, 1).astype(np.float32)


def ref_part(names):
    s = np.zeros((CH, CW), np.float64); c = np.zeros((CH, CW), np.float64); d = np.zeros((CH, CW), np.float32)
    for n in names:
        f = moonlib.load(moonlib.raw_path(SRC, n)); M = placed(n)
        k = scalar(n)
        ok = warp(usable(f) * edge_fade(f["g"].shape, 2 * FEATHER), M, cv2.INTER_LINEAR)
        w = ok / k ** 2                       # a frame that lost half its light counts a quarter
        s += warp(f["g"], M) * k * w; c += w; d += (ok > 0.5)
    return s, c, d


def build_ref():
    clear = [n for n in NAMES if scalar(n) < CUT]   # a frame that lost three quarters of its light doesn't shape the yardstick; the rest count by transparency squared
    with ProcessPoolExecutor(6) as ex:
        parts = list(ex.map(ref_part, [clear[i::6] for i in range(6)]))
    s = sum(p[0] for p in parts); c = sum(p[1] for p in parts); d = sum(p[2] for p in parts)
    ref = (s / np.maximum(c, 1e-6)).astype(np.float32); ref[d < 0.5] = 0; c = d
    # cut the canvas down to the lit Moon, with room for patches at its edge
    ys, xs = np.where(cv2.GaussianBlur(ref, (0, 0), 3) > 0.02); m = 96
    x0, x1 = max(xs.min() - m, 0), min(xs.max() + m, CW); y0, y1 = max(ys.min() - m, 0), min(ys.max() + m, CH)
    json.dump(dict(x0=int(X0 + x0), y0=int(Y0 + y0), w=int(x1 - x0), h=int(y1 - y0)), open(CROP, "w"))
    np.savez_compressed(os.path.join(HERE, "ref.npz"), ref=ref[y0:y1, x0:x1], count=c[y0:y1, x0:x1].astype(np.float32))
    print("canvas %dx%d (the lit Moon plus a margin); yardstick from %d clear frames of %d; up to %d frames deep" % (x1 - x0, y1 - y0, len(clear), len(NAMES), c.max()))


# -- photo -------------------------------------------------------------------------------------------

def photo_one(name):
    """A frame on the common Moon at a quarter of the working scale: (brightness, weight)."""
    f = moonlib.load(moonlib.raw_path(SRC, name)); M = placed(name) / 4.0
    size = (CW // 4 + 1, CH // 4 + 1)
    g = cv2.warpAffine(cv2.GaussianBlur(f["g"], (0, 0), 2.0), M, size, flags=cv2.INTER_LINEAR)
    w = cv2.warpAffine(usable(f) * edge_fade(f["g"].shape, 2 * FEATHER), M, size, flags=cv2.INTER_LINEAR)
    return name, g, w


def photo():
    """One number per frame so that overlapping frames agree in brightness: each frame against the
    average of all of them, round and round (20 rounds). Then scaled so the clearest frames are 1."""
    with ProcessPoolExecutor(6) as ex:
        F = {n: (g, w) for n, g, w in ex.map(photo_one, NAMES)}
    k = {n: 1.0 for n in NAMES}
    for rnd in range(20):
        num = sum(F[n][0] * k[n] * F[n][1] / k[n] ** 2 for n in NAMES); den = sum(F[n][1] / k[n] ** 2 for n in NAMES)
        ref = num / np.maximum(den, 1e-6)
        for n in NAMES:
            g, w = F[n]; m = (w > 0.5) & (ref > 0.05) & (g > 0.01)
            k[n] = float((ref[m] * g[m]).sum() / (g[m] ** 2).sum()) if m.sum() > 500 else k[n]
        lo = np.percentile(list(k.values()), 10)
        k = {n: v / lo for n, v in k.items()}
    # how well each frame then agrees with the rest, place by place (cloud across the frame shows here)
    out = {}
    for n in NAMES:
        g, w = F[n]; m = (w > 0.5) & (ref > 0.05) & (g > 0.01)
        r = cv2.GaussianBlur(np.where(m, ref, 0), (0, 0), 8) / np.maximum(cv2.GaussianBlur(np.where(m, g * k[n], 0), (0, 0), 8), 1e-6)
        out[n] = dict(scale=k[n], transparency=1 / k[n], uneven=float(np.percentile(r[m], 95) - np.percentile(r[m], 5)) if m.sum() > 500 else 0.0)
    json.dump(out, open(os.path.join(HERE, "photo.json"), "w"), indent=1)
    for n in NAMES:
        print(n[9:15], "transparency %.2f   uneven across the frame %.2f" % (out[n]["transparency"], out[n]["uneven"]))


# -- local -------------------------------------------------------------------------------------------

def grid():
    ys = np.arange(BOX // 2 + SEARCH, CH - BOX // 2 - SEARCH, STEP); xs = np.arange(BOX // 2 + SEARCH, CW - BOX // 2 - SEARCH, STEP)
    return ys, xs


def fill(dx, dy, w):
    """A smooth field through the patches that were believed, weighted by how well each matched."""
    def smooth(v, sig):
        return cv2.GaussianBlur(v * w, (0, 0), sig) / np.maximum(cv2.GaussianBlur(w, (0, 0), sig), 1e-6)
    near_w = cv2.GaussianBlur(w, (0, 0), 1.2)
    fx, fy = smooth(dx, 1.2), smooth(dy, 1.2)
    wide_x, wide_y = smooth(dx, 5.0), smooth(dy, 5.0)
    a = np.clip(near_w / 0.15, 0, 1)   # where few patches nearby were believed, lean on the wider neighbourhood
    return (a * fx + (1 - a) * wide_x).astype(np.float32), (a * fy + (1 - a) * wide_y).astype(np.float32)


DOG = (1.0, 2.5)


def band(img):
    return cv2.GaussianBlur(img, (0, 0), DOG[0]) - cv2.GaussianBlur(img, (0, 0), DOG[1])


def band_noise_gain():
    """How much of a pixel's white noise gets through the detail band (measured, once)."""
    rng = np.random.default_rng(1); z = rng.standard_normal((512, 512)).astype(np.float32)
    return float(band(z)[32:-32, 32:-32].var())


def maps_for(name, dxg, dyg):
    """Canvas pixel -> where to read in the original frame, through the patch field and the placement."""
    ys, xs = grid()
    gy0, gx0 = ys[0], xs[0]
    # the field on every canvas pixel (bicubic through the grid; held constant beyond its edge)
    yy = ((np.arange(CH) - gy0) / STEP).astype(np.float32); xx = ((np.arange(CW) - gx0) / STEP).astype(np.float32)
    mx, my = np.meshgrid(np.clip(xx, 0, len(xs) - 1), np.clip(yy, 0, len(ys) - 1))
    dx = cv2.remap(dxg, mx, my, cv2.INTER_CUBIC); dy = cv2.remap(dyg, mx, my, cv2.INTER_CUBIC)
    px, py = np.meshgrid(np.arange(CW, dtype=np.float32), np.arange(CH, dtype=np.float32))
    px += dx; py += dy
    Mi = cv2.invertAffineTransform(placed(name)).astype(np.float32)
    return (Mi[0, 0] * px + Mi[0, 1] * py + Mi[0, 2]).astype(np.float32), (Mi[1, 0] * px + Mi[1, 1] * py + Mi[1, 2]).astype(np.float32)


def local_one(name):
    out = os.path.join(LOCAL, name + ".npz")
    if os.path.exists(out):
        return name
    z = np.load(REF); ref = z["ref"]; deep = z["count"]
    f = moonlib.load(moonlib.raw_path(SRC, name)); M = placed(name)
    ok = warp(usable(f), M, cv2.INTER_LINEAR)
    g = warp(f["g"], M)
    refr = moonlib.relief(ref); gr = moonlib.relief(g)
    lit = ((ref > 0.02) & (deep >= 2)).astype(np.float32)
    ys, xs = grid(); b, s = BOX // 2, SEARCH
    dx = np.zeros((len(ys), len(xs)), np.float32); dy = np.zeros_like(dx); w = np.zeros_like(dx)
    for i, cy in enumerate(ys):
        for j, cx in enumerate(xs):
            if lit[cy - b:cy + b, cx - b:cx + b].mean() < 0.9 or ok[cy - b - s:cy + b + s, cx - b - s:cx + b + s].min() < 0.99:
                continue
            tmpl = refr[cy - b:cy + b, cx - b:cx + b]
            if tmpl.std() < 0.004:      # nothing to hold on to (smooth mare)
                continue
            res = cv2.matchTemplate(gr[cy - b - s:cy + b + s, cx - b - s:cx + b + s], tmpl, cv2.TM_CCOEFF_NORMED)
            _, peak, _, (u, v) = cv2.minMaxLoc(res)
            if peak < MIN_CORR or u in (0, 2 * s) or v in (0, 2 * s):
                continue
            # the peak to a fraction of a pixel: a parabola through it and its neighbours
            su = 0.5 * (res[v, u - 1] - res[v, u + 1]) / (res[v, u - 1] - 2 * peak + res[v, u + 1] - 1e-9)
            sv = 0.5 * (res[v - 1, u] - res[v + 1, u]) / (res[v - 1, u] - 2 * peak + res[v + 1, u] - 1e-9)
            dx[i, j] = u - s + np.clip(su, -0.5, 0.5); dy[i, j] = v - s + np.clip(sv, -0.5, 0.5); w[i, j] = peak - MIN_CORR
    believed = w > 0
    if believed.sum() < 20:
        np.savez_compressed(out, dx=dx, dy=dy, w=w, q=np.zeros_like(dx), cover=np.zeros_like(dx), gain=np.ones_like(dx), moved=0.0, believed=0)
        return name
    fx, fy = fill(dx, dy, w)
    # the frame in its true place: one resampling, from the RAW planes
    mx, my = maps_for(name, fx, fy)
    gl = cv2.remap(f["g"], mx, my, cv2.INTER_LANCZOS4)
    okl = cv2.remap(usable(f), mx, my, cv2.INTER_LINEAR)
    nz = cv2.remap(f["noise"] ** 2, mx, my, cv2.INTER_LINEAR) / 4.0          # noise variance of the green mean
    mean = cv2.GaussianBlur(gl, (0, 0), 12) + 1e-4
    sig = cv2.GaussianBlur(band(gl / mean) ** 2, (0, 0), BOX / 4)             # power in the detail band
    noi = band_noise_gain() * cv2.GaussianBlur(nz, (0, 0), BOX / 4) / mean ** 2  # what noise alone puts there
    qmap = np.maximum(sig - noi, 0)
    # how much brighter the yardstick is than this frame, place by place (cloud is not even). Where
    # there is no light to compare (sky, beyond the terminator) it becomes the frame's one number.
    k = scalar(name)
    gmap = (np.maximum(cv2.GaussianBlur(ref, (0, 0), 30), 0) + EPS * k) / (np.maximum(cv2.GaussianBlur(gl * okl, (0, 0), 30) / np.maximum(cv2.GaussianBlur(okl, (0, 0), 30), 1e-3), 0) + EPS)
    q = np.zeros_like(dx); cover = np.zeros_like(dx); gain = np.ones_like(dx)
    for i, cy in enumerate(ys):
        for j, cx in enumerate(xs):
            cover[i, j] = okl[cy - b:cy + b, cx - b:cx + b].min()   # sky counts too: its glow is real, and a patch grid shouldn't show
            q[i, j] = qmap[cy, cx]; gain[i, j] = gmap[cy, cx]
    moved = float(np.sqrt(((fx - np.median(fx[believed])) ** 2 + (fy - np.median(fy[believed])) ** 2)[believed].mean()))
    np.savez_compressed(out, dx=fx, dy=fy, w=w, q=q, cover=cover, gain=gain, moved=moved, believed=int(believed.sum()))
    return name


# -- combine -----------------------------------------------------------------------------------------

def weights(keep, names=None):
    """Per patch: which frames are used. The sharpest `keep` of those covering it (at least 4).
    `names` limits the choice to some of the frames (half of them, to test what the halves agree on)."""
    Z = {n: np.load(os.path.join(LOCAL, n + ".npz")) for n in NAMES}
    used = [n for n in (names or NAMES) if int(Z[n]["believed"]) >= 20]
    q = np.stack([np.where(Z[n]["cover"] > 0.99, Z[n]["q"], -1) for n in used])
    gain = np.stack([np.clip(Z[n]["gain"], 0.2, 20) for n in used])
    q = np.where(gain > CUT, -1, q)                      # under cloud: a quarter of the light or less, not used
    # (new) nor a frame much dimmer than the clearest one that covers the patch: the southern panels
    # were all under some cloud, so "clear" has to mean the clearest there is, patch by patch. Where
    # the yardstick is dark (sky, beyond the terminator) a frame's one number stands in for its gain.
    ys, xs = grid(); z = np.load(REF)
    lit = cv2.GaussianBlur(z["ref"], (0, 0), 30)[np.ix_(ys, xs)] > 3 * EPS
    geff = np.where(lit[None], gain, np.array([scalar(n) for n in used])[:, None, None])
    gq = np.where(q >= 0, geff, np.inf)
    best = np.min(gq, axis=0)
    nth = np.sort(gq, axis=0)[min(AT_LEAST, len(used)) - 1]          # the gain of the AT_LEAST-th clearest frame here
    q = np.where(geff > np.maximum(CLEAR * best, nth)[None], -1, q)
    n_cover = (q >= 0).sum(0)
    k = np.clip(np.ceil(keep * n_cover), MIN_K, None).astype(int)
    order = np.argsort(-q, axis=0); rank = np.empty_like(order); np.put_along_axis(rank, order, np.arange(len(used))[:, None, None], axis=0)
    sel = (rank < k[None]) & (q >= 0)
    return used, Z, sel.astype(np.float32), n_cover


def combine_part(args):
    names, sels = args
    acc = np.zeros((CH, CW, 3), np.float64); wsum = np.zeros((CH, CW), np.float64); depth = np.zeros((CH, CW), np.float32)
    ys, xs = grid()
    yy = ((np.arange(CH) - ys[0]) / STEP).astype(np.float32); xx = ((np.arange(CW) - xs[0]) / STEP).astype(np.float32)
    gmx, gmy = np.meshgrid(np.clip(xx, 0, len(xs) - 1), np.clip(yy, 0, len(ys) - 1))
    for n, sel in zip(names, sels):
        if sel.sum() == 0:
            continue
        z = np.load(os.path.join(LOCAL, n + ".npz")); f = moonlib.load(moonlib.raw_path(SRC, n))
        mx, my = maps_for(n, z["dx"], z["dy"])
        okl = cv2.remap(usable(f), mx, my, cv2.INTER_LINEAR)
        gain = cv2.remap(np.clip(z["gain"], 0.2, 20).astype(np.float32), gmx, gmy, cv2.INTER_LINEAR)
        # a frame fades out over its last FEATHER px (its sensor edge, a clipped patch): no seams
        feather = np.clip(cv2.distanceTransform((okl > 0.99).astype(np.uint8), cv2.DIST_L2, 3) / FEATHER, 0, 1)
        wm = cv2.remap(cv2.GaussianBlur(sel, (0, 0), 0.7), gmx, gmy, cv2.INTER_LINEAR) * feather / gain ** 2
        for c, key in enumerate(("r", "g", "b")):
            acc[:, :, c] += cv2.remap(f[key], mx, my, cv2.INTER_LANCZOS4) * gain * wm * f["wb"][c]
        wsum += wm; depth += (wm > 0)
    return acc, wsum, depth


def combine(keep):
    # MOON_HALF=a or b: every other frame in time order (as stack2x.py), for half-against-half tests
    half = os.environ.get("MOON_HALF")
    used, Z, sel, n_cover = weights(keep, None if not half else sorted(NAMES)[(0 if half == "a" else 1)::2])
    jobs = [([used[i] for i in range(k, len(used), 6)], [sel[i] for i in range(k, len(used), 6)]) for k in range(6)]
    with ProcessPoolExecutor(6) as ex:
        parts = list(ex.map(combine_part, jobs))
    acc = sum(p[0] for p in parts); wsum = sum(p[1] for p in parts); depth = sum(p[2] for p in parts)
    img = (acc / np.maximum(wsum, 1e-9)[:, :, None]).astype(np.float32); img[wsum <= 0] = 0
    tag = "keep%02d%s%s" % (round(keep * 100), SUFFIX, "-half-" + half if half else "")
    np.savez_compressed(os.path.join(HERE, "stack-%s.npz" % tag), img=img, depth=depth)
    share = {n: float(sel[i].sum() / max(sel.sum(), 1)) for i, n in enumerate(used)}
    recipe = dict(tool="stack.py combine", keep=keep, at_least_frames_per_patch=MIN_K,
                  cloud=dict(not_used_if_gain_over=CUT, not_used_if_gain_over_times_the_clearest=CLEAR, unless_fewer_than=AT_LEAST, weight="1 / gain squared"),
                  yardstick=os.path.basename(REF), grid=dict(step=STEP, box=BOX, search=SEARCH, min_corr=MIN_CORR), feather_px=FEATHER, detail_band_px=DOG,
                  canvas=[CW, CH], reference=T["reference"], frames_placed=len(NAMES), frames_with_believed_patches=len(used),
                  frames_contributing=int(sum(1 for v in share.values() if v > 0)), patch_share=share,
                  depth=dict(median=float(np.median(depth[depth > 0])), max=float(depth.max())),
                  versions=dict(opencv=cv2.__version__, numpy=np.__version__, libraw=".".join(map(str, __import__("rawpy").libraw_version))))
    json.dump(recipe, open(os.path.join(HERE, "recipe-%s.json" % tag), "w"), indent=1)
    print("stack %s: %d frames contribute; a patch is the average of %d frames (median), up to %d" % (tag, recipe["frames_contributing"], recipe["depth"]["median"], recipe["depth"]["max"]))


if __name__ == "__main__":
    stage = sys.argv[2]
    if stage == "photo":
        photo()
    elif stage == "ref":
        build_ref()
    elif stage == "local":
        os.makedirs(LOCAL, exist_ok=True)
        with ProcessPoolExecutor(6) as ex:
            list(ex.map(local_one, NAMES))
        Z = [np.load(os.path.join(LOCAL, n + ".npz")) for n in NAMES]
        b = np.array([int(z["believed"]) for z in Z]); m = np.array([float(z["moved"]) for z in Z])
        print("%d frames: patches believed per frame median %d (min %d); the air moved patches %.2f px rms (median), up to %.2f" % (len(Z), np.median(b), b.min(), np.median(m), m.max()))
    elif stage == "combine":
        combine(float(sys.argv[3]) if len(sys.argv) > 3 else 0.3)
