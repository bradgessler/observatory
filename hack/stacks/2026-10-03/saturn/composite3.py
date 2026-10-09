"""Saturn and its moons, one picture from two exposures.

  the moons   the long exposures (2 s, ISO 6400), combined, the planet's glare taken off (moons2.py). Saturn itself is blown out in these.
  the planet  the short exposures (1/40 s, ISO 800), the sharpest stacked and the blur measured
              from Titan divided out (saturn2.py, finish2.py).

Both are turned so north is up and east is left, at the sensor's own scale. The planet is set into the moon field where the
long exposure is blown out; an inset shows it three times larger. Brightness is not to one scale, and the picture says so: the
moons are shown about 600 times brighter than they are next to the planet.

composite3.py is composite2.py with these changes, made for the sharp run of 2026-10-04 (08:46 to 09:05 UTC):
  1. The moons' names and places come from whichmoon.py's names.json (seven moons, named from their orbits), not from fixed distances.
  2. The planet is set in where the long exposure is blown out (moons2.py's mask), not inside a circle of 50 arcsec feathered to 62:
     three moons are now seen 24 to 43 arcsec from the planet, inside that circle. The planet's centre is put on the centre of
     symmetry of the glare (moons2.py), to a fraction of a pixel, in one resampling.
  3. Labels are laid out so they do not run into each other (some above, some below, one on a longer line), and checked.
  4. --clean writes the same picture with no words, lines, inset or scale bar, and a closer crop of the same pixels (no resampling).
  5. Captions from this run's numbers and times.
  6. Red and blue are already slid onto green in moons2.py (it needs them registered before it takes the glare off by symmetry);
     the same measurement on Rhea is repeated here and should find almost nothing left to move.
  8. Within 12 px of the blown-out patch (fading out by 16) the moon field is shown grey: the colours of what is left of the glare there
     are not to be trusted (a red patch on the planet's north edge and a blue cast on Dione went with this). Dione and Enceladus are in that band.
  9. Hyperion is named in smaller, dimmer letters with the word "faint": it is measured (about 10 sigma, on its orbit, moving as it
     should) but on this tone curve it is only just there.
  7. "Under three sigma is sky" uses the noise where the pixel is: beside the planet the glare leaves several times the open sky's
     grain, and at the open sky's threshold that grain showed as coloured specks around the planet.

Usage: composite3.py moonfield-stem whois.json names.json saturn-stem out.png [--clean]
"""
import json, sys, os
import numpy as np, cv2
from scipy.optimize import minimize
from PIL import Image, ImageDraw, ImageFont
from metrics import measure

CLEAN = "--clean" in sys.argv; argv = [a for a in sys.argv if a != "--clean"]
mstem = argv[1]; field = np.load(mstem + ".npy"); blown = np.load(mstem + "-blown.npy"); mrec = json.load(open(mstem + ".json")); W_ = json.load(open(argv[2])); NAMES = json.load(open(argv[3])); stem = argv[4]; out = argv[5]
rec = json.load(open(stem + ".json")); who = W_["points"]; named = NAMES["named"]
NATIVE = 0.3955                       # the earlier scripts' arcsec per sensor pixel: kept as the unit of the canvas so the pictures can be laid side by side
TRUE = W_["arcsec_per_sensor_px"]     # what the stars in these frames say
ROT = W_["up_east_of_north_deg"]      # the picture's up is this many deg east of north (negative: west): turn it by that
R = field.shape[0] // 2; SYM = mrec["glare_by_symmetry"]["centre_from_blob_middle_half_px"]

# -- the air spreads colours: red and blue slid onto green, by what Rhea shows (not blown out) ----------------
tx, ty = [int(round(v)) for v in named["Rhea"]["field_half_px"]]
tile = lambda c: np.ascontiguousarray(field[ty - 32:ty + 32, tx - 32:tx + 32, c])
def ls_shift(ref, img, margin=10, blur=1.0):
    """How far img sits from ref (px): the shift that makes smoothed img, scaled, closest to smoothed ref."""
    a = cv2.GaussianBlur(ref, (0, 0), blur); b0 = cv2.GaussianBlur(img, (0, 0), blur); h, w = a.shape; sl = (slice(margin, h - margin), slice(margin, w - margin))
    def cost(p):
        b = cv2.warpAffine(b0, np.float32([[1, 0, -p[0]], [0, 1, -p[1]]]), (w, h), flags=cv2.INTER_LINEAR); k = (a[sl] * b[sl]).sum() / (b[sl] ** 2).sum(); return float(((a[sl] - k * b[sl]) ** 2).sum())
    r = minimize(cost, (0.0, 0.0), method="Nelder-Mead", options=dict(xatol=0.005, fatol=1e-16, initial_simplex=np.array([(0.0, 0.0), (0.7, 0.0), (0.0, 0.7)]))); return float(r.x[0]), float(r.x[1])
moved = {}
for c, name in ((0, "red"), (2, "blue")):
    dx, dy = ls_shift(tile(1), tile(c))
    field[..., c] = cv2.warpAffine(field[..., c], np.float32([[1, 0, -dx], [0, 1, -dy]]), field.shape[1::-1], flags=cv2.INTER_LANCZOS4)
    moved[name] = [round(dx * 2, 2), round(dy * 2, 2)]

# -- the moon field at the sensor's scale, north up ------------------------------------------------
noise = 1.4826 * np.median(np.abs(field[..., 1]))
# Right beside the blown-out patch (within 12 px, fading out by 16: the band where moons2.py took its running median) the colours of what
# is left are not to be trusted: the glare is a little different in each colour and what remains of it is red here and blue there. There the
# field is shown grey, the mean of its three colours. Dione (3 px from the patch) and Enceladus (10 px) are in that band; the other moons are not.
hole_ = cv2.dilate(blown.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0; dist_ = cv2.distanceTransform((~hole_).astype(np.uint8), cv2.DIST_L2, 5)
wg = np.clip((16 - dist_) / 4, 0, 1)[..., None]; field = field * (1 - wg) + field.mean(2, keepdims=True) * wg
big = cv2.resize(field, None, fx=2, fy=2, interpolation=cv2.INTER_LANCZOS4)
c = (big.shape[1] / 2 - 0.5, big.shape[0] / 2 - 0.5)
M = cv2.getRotationMatrix2D(c, ROT, 1.0)
big = cv2.warpAffine(big, M, big.shape[1::-1], flags=cv2.INTER_LANCZOS4)
# The sky's noise is not the same everywhere: near the planet the glare that was taken off leaves its own grain behind (more light, more
# grain), several times the open sky's. "Under three sigma is sky" is kept, with sigma the noise where the pixel is: for each colour, the
# spread (median absolute deviation) of the field in bands of distance from the blown-out patch, as a multiple of that colour's spread far out;
# the largest of the three colours' multiples is used for all three.
hole0 = cv2.dilate(blown.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0; dist = cv2.distanceTransform((~hole0).astype(np.uint8), cv2.DIST_L2, 5)
bands = [1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 18, 22, 27, 33, 40, 50, 60, 80, 100, 130, 170, 220]; mad = lambda x: 1.4826 * float(np.median(np.abs(x - np.median(x)))); grain = np.ones(field.shape, np.float32); GRAIN = {}
for ch in range(3):
    far = mad(field[..., ch][(dist > 220) & (field[..., 1] != 0)]); mids, infl = [], []
    for lo, hi in zip(bands[:-1], bands[1:]):
        sel = (dist >= lo) & (dist < hi); mids.append((lo + hi) / 2); infl.append(max(1.0, mad(field[..., ch][sel]) / far))
    grain[..., ch] = np.interp(dist, mids + [220.0], infl + [1.0]); GRAIN["RGB"[ch]] = [round(x, 2) for x in infl]
grain[:] = grain.max(2, keepdims=True)                       # one threshold for the three colours (the largest), so that the cut does not tint what passes it
grain = cv2.warpAffine(cv2.resize(grain, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR), M, big.shape[1::-1], flags=cv2.INTER_LINEAR, borderValue=(1, 1, 1))
# points only: what is under three sigma is sky; the rest on a curve that keeps faint and bright both in view
v = np.clip(cv2.GaussianBlur(big, (0, 0), 1.2) - 3.0 * noise * grain, 0, None) / (60 * noise)
v = np.arcsinh(v * 6) / np.arcsinh(6 * 8)
moons = np.clip(v, 0, 1)
# where the long exposure is blown out on the planet (and 1 px around, as moons2.py zeroed it): the planet goes in there
hole = cv2.dilate(blown.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))).astype(np.float32)
hole = cv2.warpAffine(cv2.resize(hole, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR), M, big.shape[1::-1], flags=cv2.INTER_LINEAR)
hole = np.clip((cv2.GaussianBlur(hole, (0, 0), 2.0) - 0.5) * 2, 0, 1)        # fades in from the edge of the hole inward, over about 3 px: nothing outside the hole is covered

# -- the canvas: 23.5 x 11 arcmin around the planet ---------------------------------------------------
W, H = int(1410 / NATIVE), int(660 / NATIVE)
cx, cy = int(700 / NATIVE), H // 2
bx, by = int(c[0]), int(c[1]); x0, y0 = bx - cx, by - cy
def to_canvas(xf, yf):
    """A place in the moon field (half-size px) on the canvas."""
    p = M @ np.array([2 * xf + 0.5, 2 * yf + 0.5, 1.0]); return float(p[0] - x0), float(p[1] - y0)
def cut(img):
    o = np.zeros((H, W) + img.shape[2:], np.float32); src = img[max(y0, 0):y0 + H, max(x0, 0):x0 + W]; o[max(-y0, 0):max(-y0, 0) + src.shape[0], max(-x0, 0):max(-x0, 0) + src.shape[1]] = src; return o
canvas = cut(moons); a = cut(hole)[..., None]

# -- the planet at the same scale and turn, its centre on the centre of symmetry of the glare -------------
sat = np.load(stem + ".npy")                      # 3 fine px per sensor px, linear
dec = cv2.cvtColor(cv2.imread(stem + "-deconvolved.png"), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
dec = np.clip((dec - 0.06) / 0.94, 0, 1)          # the sky round the planet to black: what is left there is the filter's ripple, not light
pcx, pcy = measure(sat[:, :, 1])[0]["centre"]     # the planet's middle in its tile (fine px)
gx, gy = to_canvas(R + SYM[0], R + SYM[1]); n = dec.shape[0]; ox, oy = int(round(gx)) - n // 6, int(round(gy)) - n // 6
uc, vc = 3 * (gx - ox + 0.5) - 0.5, 3 * (gy - oy + 0.5) - 0.5                 # where the planet's middle must sit on the fine grid so that it lands on (gx, gy)
Mp = cv2.getRotationMatrix2D((pcx, pcy), ROT, 1.0); Mp[0, 2] += uc - pcx; Mp[1, 2] += vc - pcy
small = cv2.resize(cv2.warpAffine(dec, Mp, (n, n), flags=cv2.INTER_LANCZOS4), None, fx=1 / 3, fy=1 / 3, interpolation=cv2.INTER_AREA)   # sensor scale
def turn(img, scale):
    h, w = img.shape[:2]; m = cv2.getRotationMatrix2D((w / 2 - 0.5, h / 2 - 0.5), ROT, scale)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LANCZOS4)
inset = turn(dec, 1.0)                                                                       # 3x
sh, sw = small.shape[:2]; planet = np.zeros_like(canvas); planet[oy:oy + sh, ox:ox + sw] = small
left_out = float((planet * (1 - a)).sum() / max(planet.sum(), 1e-9))                         # how much of the planet's picture falls outside the hole and is not shown
canvas = canvas * (1 - a) + planet * a

img = Image.fromarray((np.clip(canvas, 0, 1) * 255 + 0.5).astype(np.uint8))
kept, usable = rec["kept"], rec["usable"]; hhmm = lambda name: name[9:11] + ":" + name[11:13]; times = sorted(hhmm(nm) for nm in rec["used"] + mrec.get("used", []))
place = {k: to_canvas(*v["field_half_px"]) for k, v in named.items()}
star = max((q for q in who if not q["star"] and q["arcsec"] > 300 and not any(np.hypot(q["x"] - v["field_half_px"][0], q["y"] - v["field_half_px"][1]) < 6 for v in named.values())), key=lambda q: q["flux"], default=None)
base = dict(what="Saturn and its moons, 2026-10-04, after the refocus", script="composite3.py", size=list(img.size), arcsec_per_px=TRUE, north_up_rotation_deg=ROT,
            orientation_and_scale=dict(source="%d catalogue stars in the moon frames (whois3.py)" % W_["stars_matched"], stars_matched=W_["stars_matched"], match_rms_arcsec=W_["match_rms_arcsec"], plate_solves_of_these_frames_said_deg=W_["plate_solves_up_east_of_north_deg"],
                                       earlier_scripts_assumed_arcsec_per_px=NATIVE, note="the canvas keeps the earlier pictures' pixel size (%d x %d); 1 px is 1 sensor px, %.4f arcsec" % (W, H, TRUE)),
            planet=dict(frames_used=kept, frames_usable=usable, exposure="1/40 s ISO 800", centre_on_canvas_px=[round(gx, 2), round(gy, 2)], centred_on="the centre of symmetry of the glare in the moon field, (%.2f, %.2f) half px from the blown-out patch's middle" % (SYM[0], SYM[1]),
                        set_in="where the long exposure is blown out on the planet (moons2.py's patch, 1 px around it), fading in over about 3 px inward from its edge", share_of_planet_picture_outside_the_hole_not_shown=round(left_out, 5), recipe=rec),
            moons=dict(frames=mrec["frames"], used=mrec.get("used"), exposure="2 s ISO 6400", combine="mean of the two frames, aligned on the planet (moons2.py: a median of two is their mean)", glare="ring-by-ring median, then two-fold symmetry, then a running median along the blown-out edge (moons2.py)",
                       colour_planes_moved_native_px=moved, colour_planes_moved_by="least squares on Rhea", tone="arcsinh above 3 sigma, sigma being the noise where the pixel is", grey_beside_the_blown_out_patch=dict(full_within_half_px=12, none_beyond_half_px=16), noise_near_the_planet=dict(as_multiple_of_open_sky_by_colour=GRAIN, bands_half_px_from_the_blown_out_patch=bands), recipe=mrec, places_on_canvas_px={k: [round(p[0], 1), round(p[1], 1)] for k, p in place.items()}),
            times_utc=[times[0], times[-1]])
if CLEAN:
    img.save(out)
    # a closer view: Saturn out to Titan and Rhea, the same pixels cropped (no resampling), as composite_clean.py framed it
    pts = [(gx, gy), place["Titan"], place["Rhea"]]; xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    w = int(max(max(xs) - min(xs), (max(ys) - min(ys)) * 16 / 9) + 520); h = int(w * 9 / 16)
    xa = int(np.clip(mx - w / 2, 0, W - w)); ya = int(np.clip(my - h / 2, 0, H - h))
    close = img.crop((xa, ya, xa + w, ya + h)); close.save(out.replace(".png", "-close.png"))
    base.update(what="Saturn and its moons, 2026-10-04, after the refocus, no labels", north="up", east="left", close=dict(file=os.path.basename(out).replace(".png", "-close.png"), crop_px=[xa, ya, w, h], resampled=False, holds=[k for k, p in place.items() if xa <= p[0] < xa + w and ya <= p[1] < ya + h]),
                same_pixels_as=os.path.basename(out).replace("-clean", "") + ", without the names, title, inset, scale bar and captions")
    json.dump(base, open(out.replace(".png", ".json"), "w"), indent=1); print(out, img.size, "close", close.size, base["close"]["holds"]); sys.exit()

d = ImageDraw.Draw(img)
def font(size, bold=False):
    for path in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc"):
        try: return ImageFont.truetype(path, size)
        except Exception: pass
    return ImageFont.load_default()
f_label, f_small, f_title = font(44), font(32), font(64, True)
ink, dim = (232, 232, 226), (150, 150, 146)

# -- the names: above each point on a short line, as before; where two would run into each other, one goes below or on a longer line
HOW = dict(Saturn=("below", 58, 38), Tethys=("below", 24, 32), Dione=("above", 24, 96))        # side, gap from the point, length of the line
boxes = []
FAINT = [k for k, v in named.items() if v["snr"] < 30]                                          # measured, but only just there on this tone curve
def label(name, x, y):
    side, gap, length = HOW.get(name, ("above", 24, 32)); faint = name in FAINT; text = name + ", faint" if faint else name; f = f_small if faint else f_label; tw = d.textlength(text, font=f); s = -1 if side == "above" else 1
    d.line([(x, y + s * gap), (x, y + s * (gap + length))], fill=dim, width=2)
    top = y - (gap + length) - (44 if faint else 56) if side == "above" else y + gap + length + 4
    d.text((x - tw / 2, top), text, font=f, fill=dim if faint else ink); boxes.append((name, x - tw / 2 - 6, top, x + tw / 2 + 6, top + 50))
for name, (x, y) in sorted(place.items(), key=lambda kv: kv[1][0]): label(name, x, y)
label("Saturn", gx, gy)
for i, (na, ax0, ay0, ax1, ay1) in enumerate(boxes):
    for nb, bx0, by0, bx1, by1 in boxes[i + 1:]:
        assert ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0, "labels %s and %s run into each other" % (na, nb)
# the one bright point that is not a moon: say so (Tycho-2, magnitude 8.1; it was in the earlier picture too, and has stayed put among the stars)
if star:
    x, y = to_canvas(star["x"], star["y"]); d.text((x + 34, y - 18), "a star, magnitude 8.1", font=f_small, fill=dim)

# -- the inset: the planet three times larger ----------------------------------------------------------
ih = 420; ins = inset[inset.shape[0] // 2 - ih // 2:inset.shape[0] // 2 + ih // 2, inset.shape[1] // 2 - ih // 2 - 60:inset.shape[1] // 2 + ih // 2 + 60]
ins_img = Image.fromarray((np.clip(ins, 0, 1) * 255 + 0.5).astype(np.uint8))
ix, iy = W - ins_img.width - 70, 70
img.paste(ins_img, (ix, iy)); d.rectangle([ix - 1, iy - 1, ix + ins_img.width, iy + ins_img.height], outline=(70, 70, 68), width=1)
d.text((ix, iy + ins_img.height + 12), "Saturn, three times larger", font=f_small, fill=dim)

# -- what it is ----------------------------------------------------------------------------------------
count = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}[len(named)]
d.text((60, 50), "Saturn and %s of its moons" % count, font=f_title, fill=ink)
d.text((60, 134), "4 October 2026, %s to %s UTC  ·  Celestron 8SE (2080 mm) and Sony a6000 on an EQ6-R" % (times[0], times[-1]), font=f_small, fill=dim)
cloud = sum(1 for f in rec.get("every_frame", []) if "cloud" in f.get("fate", ""))
lines = ["Planet: the %d sharpest of %d frames%s, 1/40 s at ISO 800, stacked; blur measured from Titan divided out." % (kept, usable, (" (%d more were dimmed by cloud)" % cloud) if cloud else ""),
         "Moons: %d frames, 2 s at ISO 6400 (640 times the planet's exposure), averaged, the planet's glare subtracted, on a curve that lifts faint points." % mrec["frames"],
         "North is up, east is left. Sky, planet and moons are the camera's own RAW pixels, stacked and filtered; nothing is generated."]
for i, line in enumerate(lines): d.text((60, H - 150 + i * 42), line, font=f_small, fill=dim)
# one arcminute
bar = 60 / TRUE; bx0 = 60; by0 = H - 200
d.line([(bx0, by0), (bx0 + bar, by0)], fill=ink, width=3); d.text((bx0 + bar + 16, by0 - 20), "1 arcminute", font=f_small, fill=dim)
img.save(out)
base["captions"] = ["Saturn and %s of its moons" % count, "4 October 2026, %s to %s UTC" % (times[0], times[-1])] + lines; base["labels"] = dict(named=sorted(named), faint=FAINT, star="a star, magnitude 8.1" if star else None, layout=HOW)
json.dump(base, open(out.replace(".png", ".json"), "w"), indent=1)
print(out, img.size, "named:", sorted(named), "| planet %d of %d frames" % (kept, usable), "| colours moved", moved, "| planet at (%.1f, %.1f), %.4f of its picture outside the hole" % (gx, gy, left_out))
