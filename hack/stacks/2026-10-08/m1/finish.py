"""(Copied from .claude/skills/finish-pictures/tools/finish.py; the one change: it reads 16-bit PNGs at full depth, so the
stretch made in step 10 is not cut to 8 bits before the levels. Output is 8-bit as before. Taken from this night's m57 copy.)

Levels and colour for a finished picture, the plain photographic way. Every step is one global, documented operation
on the pixels that are there; nothing is drawn, generated or locally retouched.

  1. sky to neutral (optional): shift each colour so the dark sky's median is the same grey in R, G and B
  2. levels: black point and white point from percentiles of brightness, the same scale for all three colours
  3. midtones: a gamma, then an S-curve, applied to brightness with each pixel's colour ratios kept
  4. grain (optional): where the picture is dark, brightness is smoothed with an edge-keeping (bilateral) filter and
     colour with a Gaussian; where it is bright nothing is smoothed. Faint detail is traded for a quiet sky, by choice
  5. saturation: chroma (CIELAB a*, b*) times one factor; the darkest sky and near-white star cores are left alone
     so noise does not turn into coloured speckle and star cores do not fringe

Usage: finish.py <in.png> <out stem> [--sat 1.4] [--black-pct 5] [--black 0.03] [--white-pct 99.95] [--gamma 1.0]
                 [--curve 0.0] [--neutral] [--neutral-band 2 30] [--quiet 3 12 45] [--chroma-blur 4] [--shadow-l 6 20] [--grey-below 6 16]
"""
import sys, json
import numpy as np, cv2

def opt(name, default, n=1, cast=float):
    if name not in sys.argv: return default
    i = sys.argv.index(name); v = [cast(x) for x in sys.argv[i + 1:i + 1 + n]]; return v[0] if n == 1 else v

src, stem = sys.argv[1], sys.argv[2]
SAT, BPCT, BLACK, WPCT, GAMMA, CURVE = opt("--sat", 1.4), opt("--black-pct", 5.0), opt("--black", 0.03), opt("--white-pct", 99.95), opt("--gamma", 1.0), opt("--curve", 0.0)
L0, L1 = opt("--shadow-l", [6.0, 20.0], 2); NEUTRAL = "--neutral" in sys.argv
QUIET = opt("--quiet", None, 3)                 # sigma px, full smoothing below this L, none above this L
MEDIAN = opt("--median", 0, 1, int)              # 3 or 5: a median over that many pixels before the smoothing, in the dark parts only
CBLUR = opt("--chroma-blur", 0.0)               # sigma px for colour in the dark parts (same L range as --quiet, or 12..45)
BAND = opt("--neutral-band", [2.0, 30.0], 2)   # which part of the brightness range counts as dark sky, in percentiles
GREY = opt("--grey-below", None, 2)      # the darkest sky shown without colour: there its colour is only noise
bgr = cv2.imread(src, cv2.IMREAD_UNCHANGED)[..., :3]; nodata = bgr.max(2) == 0
rgb = bgr[..., ::-1].astype(np.float32) / (65535.0 if bgr.dtype == np.uint16 else 255.0)
luma = lambda v: v[..., 0] * 0.2126 + v[..., 1] * 0.7152 + v[..., 2] * 0.0722
rec = dict(what="levels and colour", source=src, steps=[])

Y = luma(rgb); have = ~nodata
if NEUTRAL:
    lo, hi = np.percentile(Y[have], BAND); sky = have & (Y >= lo) & (Y <= hi)
    med = np.array([np.mean(rgb[..., c][sky]) for c in range(3)]); shift = med - med.min()
    rgb = np.clip(rgb - shift, 0, 1); Y = luma(rgb)
    rec["steps"].append(dict(step="sky to neutral", sky_is_percentiles=BAND, sky_mean_rgb_before=[round(float(m) * 255, 2) for m in med], subtracted_rgb=[round(float(s) * 255, 2) for s in shift]))

b = float(np.percentile(Y[have], BPCT)) - BLACK; w = float(np.percentile(Y[have], WPCT)); scale = 1.0 / max(w - b, 1e-6)
rgb = np.clip((rgb - b) * scale, 0, None); Y = np.clip(luma(rgb), 1e-6, None)
rec["steps"].append(dict(step="levels", black_point=round(b * 255, 2), white_point=round(w * 255, 2), from_percentiles=[BPCT, WPCT], sky_set_to=round(BLACK * 255, 1)))

Y2 = np.clip(Y, 0, 1) ** GAMMA
Y2 = (1 - CURVE) * Y2 + CURVE * (3 * Y2 ** 2 - 2 * Y2 ** 3)
rgb = np.clip(rgb * (Y2 / Y)[..., None], 0, 1)
rec["steps"].append(dict(step="midtones", gamma=GAMMA, s_curve=CURVE, how="brightness changed, each pixel's colour ratios kept"))

lab = cv2.cvtColor(rgb.astype(np.float32), cv2.COLOR_RGB2Lab); L = lab[..., 0]
sm = lambda x, a, c: np.clip((x - a) / max(c - a, 1e-6), 0, 1) ** 2 * (3 - 2 * np.clip((x - a) / max(c - a, 1e-6), 0, 1))
if QUIET or CBLUR:
    sg, qa, qb = QUIET if QUIET else (0.0, 12.0, 45.0)
    dark = 1 - sm(cv2.GaussianBlur(L, (0, 0), max(sg, 2.0) * 1.5), qa, qb)      # 1 in the dark sky, 0 on anything bright (stars keep their edges)
    if QUIET:
        Lm = cv2.medianBlur(L, MEDIAN) if MEDIAN else L                        # salt-and-pepper grain first, if asked
        Ls = cv2.bilateralFilter(Lm, 0, 7.0, sg); lab[..., 0] = dark * Ls + (1 - dark) * L; L = lab[..., 0]
    if CBLUR:
        for c in (1, 2): lab[..., c] = dark * cv2.GaussianBlur(lab[..., c], (0, 0), CBLUR) + (1 - dark) * lab[..., c]
    rec["steps"].append(dict(step="grain", brightness=("median %d px, then " % MEDIAN if MEDIAN else "") + "bilateral filter, sigma %.1f px, 7 L units" % sg if QUIET else None, colour="Gaussian sigma %.1f px" % CBLUR if CBLUR else None,
                             where="full below L %.0f, none above L %.0f (brightness judged on a blurred copy)" % (qa, qb)))
k = 1 + (SAT - 1) * sm(L, L0, L1) * (1 - sm(L, 93.0, 99.5))
if GREY: k = k * sm(cv2.GaussianBlur(L, (0, 0), 2.0), GREY[0], GREY[1])       # judged on brightness smoothed over 2 px, so single noisy pixels do not keep their colour
lab[..., 1] *= k; lab[..., 2] *= k
rgb = np.clip(cv2.cvtColor(lab, cv2.COLOR_Lab2RGB), 0, 1)
rec["steps"].append(dict(step="saturation", factor=SAT, space="CIELAB chroma", left_alone="below L %.0f (fading in to L %.0f) and above L 93" % (L0, L1),
                         sky_without_colour=("colour fades to grey below L %.0f (full colour from L %.0f): the dark sky's colour is noise" % tuple(GREY)) if GREY else None))

out = (rgb[..., ::-1] * 255 + 0.5).astype(np.uint8); out[nodata] = 0
cv2.imwrite(stem + ".png", out); cv2.imwrite(stem + ".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 93])
rec["clipped_to_white_pct"] = round(float((out.min(2) >= 255).mean() * 100), 3); rec["clipped_to_black_pct"] = round(float(((out.max(2) == 0) & ~nodata).mean() * 100), 3)
json.dump(rec, open(stem + ".json", "w"), indent=1)
print("%s: black %.1f white %.1f gamma %.2f curve %.2f sat %.2f | white-clipped %.3f%% black-clipped %.3f%%" % (stem.split("/")[-1], b * 255, w * 255, GAMMA, CURVE, SAT, rec["clipped_to_white_pct"], rec["clipped_to_black_pct"]))
