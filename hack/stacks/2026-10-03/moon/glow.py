"""The glow thin cloud puts round the Moon, measured in each frame and taken off it.

Thin cloud does two things to a frame: it dims the Moon, and it scatters some of the Moon's light
into a glow that lies over everything, brightest near the lit ground. The southern panels were all
taken through some cloud, so the glow cannot be avoided by choosing frames: it has to be measured.

The glow is scattered moonlight, so it is modelled as what it is: the lit Moon itself, blurred very
widely. For each frame and each colour plane:

    frame = (Moon, dimmed) + c + a1 * blur(Moon, 75") + a2 * blur(Moon, 2.5') + a3 * blur(Moon, 5') + a4 * blur(Moon, 10') + a5 * blur(Moon, 20')

The Moon that is blurred is the whole mosaic's lit ground (so light from parts of the Moon outside
this frame counts). The six numbers c, a1..a5 (a's not negative) are fitted by least squares ONLY
where the truth is known to be black: sky beyond the limb and the unlit side beyond the terminator,
at least 50" from any lit ground (at 1/60 s ISO 100 earthshine is far below one count). Pixels
that stand above the fit (dim lit ground the mask missed) are dropped and the fit repeated. The
fitted glow, a smooth surface, is then subtracted over the whole frame, lit ground included.

Nothing is fitted to the lit ground and nothing sharp is subtracted from it: the narrowest blur is
75", wider than the 50" margin, so every blur is held by black pixels (a 25" blur was tried: the
black pixels cannot see it, the fit made it up, and it ate the lit ground: glowcheck.py showed it).
A clear frame comes out with a glow of a few counts. The check on lit ground is glowcheck.py: the
same ground seen clear and through cloud must differ by a factor only, with no pedestal left.

Reads transforms.json, photo.json, the RAWs. Writes glow/<name>.npz (the surface per colour plane,
on a grid of 4x4 colour cells) and glow.json (the numbers per frame).

Usage: glow.py <raw dir>
"""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
import cv2
import numpy as np
from scipy.optimize import lsq_linear
import moonlib

SRC = os.path.expanduser(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "glow")
T = json.load(open(os.path.join(HERE, "transforms.json")))
PHOTO = json.load(open(os.path.join(HERE, "photo.json")))
NAMES = sorted(T["placed"])
H, W = T["shape"]
Q = 4                                   # the fit is done on a grid of QxQ colour cells (3.1 arcsec)
SIGMAS = (24, 48, 96, 192, 384)         # blurs, in that grid's pixels: 75", 2.5', 5', 10', 20'
MARGIN = 16                             # 50": how far from lit ground a pixel must be to count as black
LIT = 0.03                              # lit ground: brighter than this share of the lit face's median
ROUNDS = 3


def big_canvas():
    pts = np.vstack([np.array([[0, 0, 1], [W, 0, 1], [0, H, 1], [W, H, 1]], float) @ np.array(T["placed"][n]["M"]).T for n in NAMES])
    x0, y0 = np.floor(pts.min(0)).astype(int) - 8; x1, y1 = np.ceil(pts.max(0)).astype(int) + 8
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


X0, Y0, CW, CH = big_canvas()
SIZE = (CW // Q + 1, CH // Q + 1)


def small_M(name):
    M = np.array(T["placed"][name]["M"], np.float64); M[:, 2] -= (X0, Y0)
    # frame grid (QxQ cells) -> canvas grid (QxQ cells)
    return M * np.array([[1, 1, 1.0 / Q], [1, 1, 1.0 / Q]])


def frame_small(name):
    """A frame's four planes after the flat and its sky level, on the QxQ grid, with what is usable."""
    pl, wb = moonlib.cells(moonlib.raw_path(SRC, name))
    clip = np.max([p for _, _, _, p in pl], 0) >= 0.98
    clip[moonlib.HAIR[2]:moonlib.HAIR[3], moonlib.HAIR[0]:moonlib.HAIR[1]] = True
    F = moonlib.flat(); sky = moonlib.sky_table()[os.path.splitext(name)[0] + ".ARW"]["sky"]
    h, w = pl[0][3].shape; size = (w // Q, h // Q)
    out = []
    for (c, x, y, p), s in zip(pl, sky):
        p = (p / F["%d%d" % (y, x)] if F else p) - s
        out.append(cv2.resize(p, size, interpolation=cv2.INTER_AREA))
    ok = cv2.resize((~clip).astype(np.float32), size, interpolation=cv2.INTER_AREA) > 0.999
    return out, ok, [c for c, _, _, _ in pl]


def lay(name):
    pl, ok, cols = frame_small(name)
    g = (pl[1] + pl[2]) / 2
    gp = os.path.join(OUT, name + ".npz")
    if os.path.exists(gp):                       # the glow found in the round before, taken off
        z = np.load(gp); g = g - (z["p1"] + z["p2"]) / 2
    M = small_M(name)
    return name, cv2.warpAffine(g, M, SIZE, flags=cv2.INTER_LINEAR), cv2.warpAffine(ok.astype(np.float32), M, SIZE, flags=cv2.INTER_LINEAR)


def fit_one(args):
    name, bases_path = args
    z = np.load(bases_path); B = z["bases"]; black = z["black"]; moon = z["moon"]
    pl, ok, cols = frame_small(name)
    h, w = pl[0].shape; M = small_M(name)
    # the canvas's maps read at this frame's pixels
    Bf = [cv2.warpAffine(b, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP) for b in B]
    blk = cv2.warpAffine(black, M, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0.5
    m0 = blk & ok
    m0[:2] = False; m0[-2:] = False; m0[:, :2] = False; m0[:, -2:] = False
    G = []; rec = dict(pixels=int(m0.sum()), planes=[])
    for p, col in zip(pl, cols):
        m = m0.copy(); x = None
        for rnd in range(4):
            A = np.c_[np.ones(int(m.sum())), np.stack([b[m] for b in Bf], 1)]
            x = lsq_linear(A, p[m], bounds=([-np.inf] + [0] * len(Bf), [np.inf] * (len(Bf) + 1))).x
            model = x[0] + sum(a * b for a, b in zip(x[1:], Bf))
            r = p - model; s = 1.4826 * np.median(np.abs(r[m] - np.median(r[m])))
            m = m0 & (r < 2.5 * s)
        G.append(model.astype(np.float32))
        rr = (p - model)[m0]
        rec["planes"].append(dict(colour=col, c=float(x[0]), a=[float(v) for v in x[1:]], left_over_rms=float(rr.std()), used=int(m.sum())))
    np.savez_compressed(os.path.join(OUT, name + ".npz"), **{"p%d" % i: g for i, g in enumerate(G)})
    # the glow, as a share of this frame's own lit face, where it is strongest and typical
    lit = (cv2.warpAffine(moon, M, (w, h), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0) & ok
    g = (G[1] + G[2]) / 2; face = float(np.median(((pl[1] + pl[2]) / 2 - g)[lit])) if lit.sum() > 100 else 0.0
    rec.update(face=face, glow_on_lit_ground_median=float(np.median(g[lit])) if lit.sum() else 0.0, glow_on_lit_ground_max=float(g[lit].max()) if lit.sum() else 0.0)
    return name, rec


if __name__ == "__main__":
    import shutil
    shutil.rmtree(OUT, ignore_errors=True); os.makedirs(OUT)
    k = {n: float(PHOTO[n]["scale"]) if n in PHOTO else 1.0 for n in NAMES}
    counts = 16383 - 512
    # Round 1 knows the lit ground only through frames that still carry their glow, so where cloud
    # was, "lit" spreads into the sky and the fit has less black to hold on to. Each further round
    # lays the frames down with the last round's glow taken off, finds the lit ground again, and fits again.
    for rnd in range(ROUNDS):
        num = np.zeros(SIZE[::-1], np.float64); den = np.zeros_like(num)
        with ProcessPoolExecutor(6) as ex:
            for n, g, w in ex.map(lay, NAMES):
                num += g * k[n] * w / k[n] ** 2; den += w / k[n] ** 2
        Y = (num / np.maximum(den, 1e-9)).astype(np.float32); Y[den <= 0] = 0
        face = float(np.median(Y[Y > 0.25 * np.percentile(Y, 99.5)]))
        lit = (cv2.GaussianBlur(Y, (0, 0), 1.0) > LIT * face).astype(np.uint8)
        n_, lab, st, _ = cv2.connectedComponentsWithStats(lit, 8)
        keep = np.zeros_like(lit)
        for i in range(1, n_):
            if st[i, cv2.CC_STAT_AREA] >= 4:      # a single hot cell is not lit ground
                keep[lab == i] = 1
        src = np.where(keep > 0, Y, 0).astype(np.float32)                       # the Moon that scatters: its lit ground
        black = (cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * MARGIN + 1, 2 * MARGIN + 1))) == 0).astype(np.float32)
        bases = np.stack([cv2.GaussianBlur(src, (0, 0), s, borderType=cv2.BORDER_CONSTANT) for s in SIGMAS])
        bp = os.path.join(OUT, "_bases.npz"); np.savez(bp, bases=bases, black=black, moon=src)
        with ProcessPoolExecutor(6) as ex:
            res = dict(ex.map(fit_one, [(n, bp) for n in NAMES]))
        print("round %d: lit ground %d cells of the mosaic; glow on lit ground, median over frames %.1f counts" % (rnd + 1, int(keep.sum()), np.median([r["glow_on_lit_ground_median"] for r in res.values()]) * counts))
    json.dump(dict(grid_cells=Q, blur_sigmas_arcsec=[round(s * Q * moonlib.ARCSEC_PER_PX, 1) for s in SIGMAS], margin_arcsec=round(MARGIN * Q * moonlib.ARCSEC_PER_PX, 1),
                   lit_ground_threshold=LIT, rounds=ROUNDS, face_of_mosaic=face, frames=res), open(os.path.join(HERE, "glow.json"), "w"), indent=1)
    for n in NAMES:
        r = res[n]; g = [p for p in r["planes"] if p["colour"] == "G"][0]
        print(n[9:15], "transparency %.2f  glow on its lit ground: median %5.1f counts (%5.1f%% of what is left of its face), most %5.1f   fit: c %5.2f a %s  left over %.2f counts rms  (%d px)" % (
            1 / k[n], r["glow_on_lit_ground_median"] * counts, 100 * r["glow_on_lit_ground_median"] / max(r["face"], 1e-9), r["glow_on_lit_ground_max"] * counts,
            g["c"] * counts, " ".join("%.4f" % a for a in g["a"]), g["left_over_rms"] * counts, r["pixels"]))
