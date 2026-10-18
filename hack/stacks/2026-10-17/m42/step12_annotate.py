"""Step 12: the share set for Messier 42, the Orion Nebula with Messier 43 (night of 17 October 2026): three JPEGs, as the
annotate-pictures skill says.

  <name>.jpg            the picture as it is, nothing on it
  <name>-annotated.jpg  names, a scale bar and north on the picture; underneath, what it is, how far, how big
  <name>-how.jpg        for photographers: exposures, frames kept and lost, the long + short join, sampling, calibration,
                        stacking and finishing

The caption band is added underneath; it never covers the picture. All drawing is plain text and lines. JPEGs are full
resolution, quality 93, no chroma subsampling, no metadata. A copy of hack/stacks/2026-10-17/m33/step12_annotate.py (the
night's house style: the same drawing code, fonts, band and credit line) with this picture's targets() table. Two
changes: every label's place comes from the stack's own plate solution (sky_px, catalogue places in PLACES), then
peak() (or dark(), its mirror, for the dark bay) finds the thing itself near it; and the calibration is three rows
(Darks, Flats, Calibration) as the night's annotate.py files them.

Nothing here gives a clock time, and never the measured altitude: together with the object they would place the
telescope. The words carry the part of the night ("before dawn") and an altitude rounded to tens of degrees.
"""
import json, math, os, re, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); os.makedirs("share", exist_ok=True)   # m42/: reads final/m42.png, final/m42.json, final/recipe.json; writes share/
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
def font(size, weight="regular"): return ImageFont.truetype(AVENIR, max(8, int(round(size))), index={"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight])
INK, SOFT, DIM, BAND, RULE = (244, 244, 240), (198, 198, 194), (140, 140, 138), (10, 10, 12), (62, 62, 64)
# f/10.3: every stack's plate solve tonight gives 2,084 to 2,089 mm on 203 mm of aperture (10.27 to 10.29); each picture's own focal length is in its rows
GEAR = "© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  night of 17 October 2026"
TRUE = "Stacked from the camera's RAW frames. Nothing generated."
CAMERA = ("CAMERA", "Sony a6000, stock, at prime focus: APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW")
MOUNT = ("MOUNT", "Sky-Watcher EQ6-R, unguided. Set down about 10 degrees off the pole; aligned from four plate-solved photos, both axes driven from that model. Dithered every three frames")
MADE = "Capture and mount: Observatory (Elixir on a Raspberry Pi 3).  Stacking: numpy, OpenCV, rawpy.  Plate solving: astrometry.net.  " + TRUE
STACK = "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered on stars with rotation (each frame first placed by its own plate solve), proper coaddition of the 30 s frames (Zackay and Ofek: each frame weighted by its own measured blur and noise), a clipped mean of the 2 s frames"
UMIN = 10.0     # px. The drawing unit is a hundredth of the picture's width, but never under this: names on a 600 px picture would be set at 9 px

def finish(name): return json.load(open("final/%s.json" % name))             # the finish recipe of final/<name>.png
def stack(folder): return json.load(open("%s/recipe.json" % folder))          # the stack's own recipe
def step(r, name): return [s for s in r["steps"] if s["step"] == name][0]
def mm(fl): whole, _, frac = ("%.1f" % fl).rstrip("0").rstrip(".").partition("."); return format(int(whole), ",") + ("." + frac if frac else "")
def optics(fl): return ("TELESCOPE", "Celestron 8SE Schmidt-Cassegrain: 203 mm aperture, %s mm focal length by plate solve of this stack, f/%.1f" % (mm(fl), fl / 203))
def span(ly, arcmin): return ly * arcmin * 2.909e-4                     # light-years across = distance x angle (arcmin x 2.909e-4 rad)
def bar(ly, dist, scale): return ly / (dist * 2.909e-4) * 60 / scale   # a round length on the sky, in picture pixels

def peak(img, near, radius, blur):
    """The brightest spot near a place, so a name sits on the thing itself and not on a guess."""
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), blur)
    x0, y0 = max(int(near[0] - radius), 0), max(int(near[1] - radius), 0); t = g[y0:y0 + 2 * radius, x0:x0 + 2 * radius]
    y, x = np.unravel_index(np.argmax(t), t.shape); return (x0 + x, y0 + y)

def HALVES_WORDS(rec):
    h = step(rec, "11 half stacks")["numbers"]["odd_vs_even"]; f = h["faintest_third"]
    return "The nebula's loops repeat in the odd and the even 30 s frames alone: %d of %d tiles of 3 arcmin, and %d of the %d faintest" % (h["passing"], h["tiles"], f["passing"], f["tiles"])

FINISH_WORDS = "Arcsinh stretch (soft 12 DN, white 250,000 DN: one curve from the faint loops to the core); black at the faintest part's own level, S-curve 0.25, saturation x 1.2; the dark parts smoothed (bilateral 3 px)"   # step10_finish.sh and render.py

def sky_px(ra, dec):
    """A catalogue place on the picture: through the stack's own plate solution (work/solve/stack.wcs, wcs-rd2xy). The
    picture is the solved rectangle itself (finish16.py neither turns nor crops), so its pixels are the solution's."""
    import subprocess
    wcs = os.path.join(os.path.expanduser(os.environ.get("M42_WORK", "~/.observatory/nights/2026-10-17-a6000/m42/work")), "solve", "stack.wcs")
    r = subprocess.run(["wcs-rd2xy", "-w", wcs, "-r", "%.6f" % ra, "-d", "%.6f" % dec], capture_output=True, text=True, check=True).stdout
    a = r.split("pixel (")[1].split(")")[0].split(","); return (float(a[0]) - 1, float(a[1]) - 1)

def dark(img, near, radius, blur):
    """The darkest spot near a place (for a dark lane), the mirror of peak()."""
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), blur)
    x0, y0 = max(int(near[0] - radius), 0), max(int(near[1] - radius), 0); t = g[y0:y0 + 2 * radius, x0:x0 + 2 * radius]
    y, x = np.unravel_index(np.argmin(t), t.shape); return (x0 + x, y0 + y)

# catalogue places, J2000 (SIMBAD values as remembered; each label is then put on what the picture shows near it and
# looked at in a full-size crop):
PLACES = dict(trapezium=(83.818583, -5.389694),      # theta1 Orionis C, 05 35 16.46 -05 23 22.9
              theta2=(83.845417, -5.416056),         # theta2 Orionis A, 05 35 22.90 -05 24 57.8
              m43=(83.880667, -5.267389),            # NU Orionis (HD 37061), the star inside M43, 05 35 31.36 -05 16 02.6
              bar=(83.828391, -5.419195),            # the Orion Bar: the bright ridge south-east of the Trapezium, between theta1 C and theta2 A; this point is
                                                     # ON the ridge as the picture shows it (picture px (1201, 1151) through the stack's solution), looked at in a 2x crop
              mouth=(83.8460, -5.3600))              # the dark bay ("the fish's mouth") north-east of the Trapezium, about 05 35 23 -05 21 36

def targets():
    T = {}
    rec = json.load(open("final/recipe.json")); fin = finish("m42"); sm = rec["summary"]
    s9 = step(rec, "9 coverage, plate solve of the stack, star colours, render")["numbers"]["solve"]
    S = s9["pixscale_arcsec"]; FL = s9["focal_length_mm"]; NORTH = s9["north_angle_from_up_deg_clockwise"]
    fw, fh = s9["field_arcmin"]
    # -- Messier 42 (final/m42.png, final/m42.json, final/recipe.json) ---------------------------------------------------
    # Distance about 1,350 light-years (414 pc by the parallax of its stars, Menten 2007; Gaia and VLBA give 390 to 410 pc,
    # 1,270 to 1,340 ly): "about 1,350 light-years". A soft number, said so.
    # Spans 1350 x fw x 2.909e-4 light-years (fw arcmin, the picture's width): computed below. One pixel: 1350 x 0.7765 x
    # 4.848e-6 = 0.00508 ly = 321 times the Earth-Sun distance.
    # The light left 1,350 years ago: about the year 680 (2026 - 1350 = 676; the skill's own example, Orion: the year 680).
    # Bar: 5 light-years = 5 / (1350 x 2.909e-4) = 12.73 arcmin.
    D = 1350.0
    span_ly = span(D, fw)
    used = sm["turns"]; nL = used["long"]["used"]; nS = used["short"]["used"]; nT = sum(v["taken"] for v in used.values())
    j = sm["join"]; cvc = sm["combine"]["coadd_vs_control"]["G1"]
    P = {k: sky_px(*v) for k, v in PLACES.items()}
    T["m42"] = dict(src="final/m42.png", scale=S, north=-NORTH, title="The Orion Nebula", sub="Messier 42 and Messier 43, a star nursery in the sword of Orion",
        what="The nearest big nursery of stars to us: a cloud of gas and dust lit from inside by the young, hot stars of the Trapezium, which formed out of it in the last million years or so. Their light carves the cloud into ridges and bays; the dark lanes are dust in front of the glowing gas. The smaller round nebula beside it, Messier 43, is the same cloud lit by one star.",
        facts=[("DISTANCE", "about 1,350 light-years (measurements run 1,270 to 1,400)"),
               ("THIS PICTURE SPANS", "about %d light-years; one pixel is about 320 times the distance from the Earth to the Sun" % int(round(span_ly))),
               ("THE LIGHT LEFT", "about 1,350 years ago, around the year 680"),
               ("HONEST NOTE", "the middle is far too bright for the long frames, so it comes from %d frames of 2 seconds; the glow fills the whole frame, so the darkest part is still nebula, not empty sky" % nS)],
        bar=(bar(5, D, S), "5 light-years"), frames="%d frames of 30 s and %d of 2 s, from one night" % (nL, nS),
        labels=lambda im: [(peak(im, P["trapezium"], 10, 1.5), "The Trapezium, the young stars that light it", 9, -9),
                           (peak(im, P["m43"], 12, 2.0), "Messier 43", 0, -9),
                           (dark(im, P["mouth"], 25, 6.0), "The fish's mouth, dust in front", -3, 11),
                           (P["bar"], "The bright bar, the cloud's lit edge", 10, 9)],
        how_sub="%.0f minutes of 30 s frames for the nebula and %d frames of 2 s for its bright middle" % (nL * 0.5, nS),
        tech=[("EXPOSURES", "%d x 30 s at ISO 1600 (%.1f minutes) and %d x 2 s at ISO 400 for the core" % (nL, nL * 0.5, nS)),
              ("FRAMES", "%d taken on M42, %d kept. Long: %d of %d (and the one frame before a firmware flash, dropped by rule as the first after the slew); short: %d of %d. Dropped: smeared (every star stretched the same way), stars too wide, dimmed by haze, within 10 s of a move" % (nT, nL + nS, used["long"]["used"], used["long"]["taken"], used["short"]["used"], used["short"]["taken"])),
              ("HIGH DYNAMIC RANGE", "The 2 s stack replaces the 30 s one wherever any 30 s frame came within 7 percent of clipping. Scale between them %.1f against the %.0f expected (stars: %.1f)" % (j["nebula_factor"], j["expected_ratio"], j["stars"]["median_ratio"])),
              ("SAMPLING", "%.3f arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars %.1f arcsec wide (half-flux) in the stack" % (S, float(sm["star_size"].split(" arcsec in the joined stack")[0].split(": ")[-1]))),
              ("FIELD", "%.1f x %.1f arcmin, a little wider than one frame: the camera was moved up to 1.5 arcmin between frames" % (fw, fh)),
              ("WHEN", "The night of 17 October 2026, before dawn. 30 to 50 degrees up"),
              ("DARKS", "None. Hot pixels found from the frames themselves and repaired"),
              ("FLATS", "The 13 October flat (large scale from that night's open sky, dust from its twilight frames)"),
              ("CALIBRATION", "Dust that moved since then measured on this run's own frames against the stack and divided out: %d shadows, a new crescent %.0f percent deep left at %.0f" % (len(step(rec, "7 canvas and dust")["numbers"]["nights"]["long"]["divided_out"]), 100 * step(rec, "7 canvas and dust")["numbers"]["nights"]["long"]["named_shadows"][0]["left_by_the_13oct_flat"], 100 * step(rec, "7 canvas and dust")["numbers"]["nights"]["long"]["named_shadows"][0]["left_after_own_correction"])),
              ("STACKING", STACK + ". Against the old weighted mean: point-source signal to noise x %.3f" % cvc["point_source_snr_ratio"]),
              ("WHAT IS REAL", HALVES_WORDS(rec)),
              ("COLOUR", "The camera's colour matrix with its white balance set by %d Gaia stars in the field (red x %.2f, blue x %.2f). Colour only where the light carries it" % (step(rec, "9 coverage, plate solve of the stack, star colours, render")["numbers"]["colour"]["used"], step(rec, "9 coverage, plate solve of the stack, star colours, render")["numbers"]["colour"]["factors"]["R"], step(rec, "9 coverage, plate solve of the stack, star colours, render")["numbers"]["colour"]["factors"]["B"])),
              ("FINISH", FINISH_WORDS),
              optics(FL), CAMERA, MOUNT])
    return T

def sent(text): return text[:1].upper() + text[1:]

def wrap(d, text, f, width):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width or not cur: cur = t
        else: lines.append(cur); cur = w
    return lines + [cur]

def band_layout(W, u, title, sub, what, items, cols, credit, small):
    """Everything under the picture, laid out before drawing so the band is exactly as tall as it needs."""
    pad = 3.2 * u; k = 0.86 if small else 1.0
    fT, fS, fW = font(3.0 * u, "demi"), font(1.45 * u, "medium"), font(1.5 * u)
    fL, fV, fC = font(1.05 * u, "demi"), font(1.5 * u * (0.8 if small else 1.0), "medium" if not small else "regular"), font(0.98 * u)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8))); gap = 2.4 * u; colw = (W - 2 * pad - gap * (cols - 1)) / cols; vh = 2.1 * u * (0.82 if small else 1.0)
    ops = []; y = pad
    for l in wrap(probe, title, fT, W - 2 * pad): ops.append((pad, y, l, fT, INK)); y += 3.7 * u
    ops.append((pad, y - 0.3 * u, sub, fS, DIM)); y += 2.6 * u + 0.6 * u
    if what:
        for l in wrap(probe, what, fW, min(W - 2 * pad, 78 * u)): ops.append((pad, y, l, fW, SOFT)); y += 2.15 * u
        y += 1.2 * u
    rules = []
    for r in range(0, len(items), cols):
        row = items[r:r + cols]; lines = [wrap(probe, sent(v), fV, colw) for _, v in row]; y += 0.9 * u
        for c, ((lab, _), ls) in enumerate(zip(row, lines)):
            x = pad + c * (colw + gap); rules.append((x, y - 0.7 * u, x + colw)); ops.append((x, y, lab.capitalize(), fL, DIM))
            for i, l in enumerate(ls): ops.append((x, y + 1.6 * u + i * vh, l, fV, INK if not small else SOFT))
        y += 1.6 * u + max(len(l) for l in lines) * vh + 1.3 * u
    y += 0.4 * u
    for i, l in enumerate(credit):
        for cl in wrap(probe, l, fC, W - 2 * pad): ops.append((pad, y, cl, fC, SOFT if i == 0 else DIM)); y += 1.6 * u
    return int(math.ceil(y + pad * 0.7)), ops, rules

def load(src): return cv2.cvtColor(cv2.imread(src, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)

def render(name, t, kind, caption=True):
    rgb = load(t["src"]); H, W = rgb.shape[:2]; u = max(W / 100.0, UMIN); pad = 3.2 * u
    # a small picture keeps its own size; its share versions put it in the middle of a band as wide as the words need
    Wc = max(W, int(round(100 * u))) if caption else W; ox = (Wc - W) // 2
    if kind == "story":
        band, ops, rules = band_layout(Wc, u, t["title"], t["sub"], t["what"], t["facts"], len(t["facts"]), [GEAR, t["frames"][0].upper() + t["frames"][1:] + ".  " + TRUE], False)
    else:
        band, ops, rules = band_layout(Wc, u, "How it was made: " + re.sub("^The ", "the ", t["title"].split(":")[0]), t["how_sub"][0].upper() + t["how_sub"][1:], None, t["tech"], 3, [GEAR, MADE], True)
    if not caption: band, ops, rules = 0, [], []
    sky = BAND                                                    # a small picture sits on the band's colour, as on a mat: a near match to grainy sky shows its edge anyway
    canvas = Image.new("RGB", (Wc, H + band), sky); canvas.paste(Image.fromarray(rgb), (ox, 0)); d = ImageDraw.Draw(canvas, "RGBA")
    fN, fC = font(1.5 * u, "medium"), font(0.98 * u); lw = max(2, int(round(u / 9)))
    def words(tx, ty, text, f=fN, fill=INK):
        tw = d.textlength(text, font=f); th = f.size * 1.25
        d.rounded_rectangle([tx - 0.45 * u, ty - 0.1 * u, tx + tw + 0.45 * u, ty + th + 0.1 * u], radius=0.35 * u, fill=(0, 0, 0, 150 if kind == "story" else 235)); d.text((tx, ty), text, font=f, fill=fill)
    def label(pt, text, dx, dy, leader=True, gap=None):
        pt = (pt[0] + ox, pt[1]); tw = d.textlength(text, font=fN); th = fN.size * 1.25
        if dx == 0 and dy == 0: return words(pt[0] - tw / 2, pt[1] - th / 2, text)
        ax, ay = pt[0] + dx * u, pt[1] + dy * u
        tx = ax + 0.4 * u if dx > 0 else (ax - tw - 0.4 * u if dx < 0 else ax - tw / 2); ty = ay - th / 2 if dx != 0 else (ay - th - 0.3 * u if dy < 0 else ay + 0.3 * u)
        if leader:
            L = math.hypot(dx, dy) * u; g0 = min((t.get("gap", 0.9) if gap is None else gap) * u, L * 0.25)   # how far short of the thing a leader stops
            p0 = (pt[0] + dx * u * g0 / L, pt[1] + dy * u * g0 / L); p1 = (ax, ay)
            d.line([p0, p1], fill=(0, 0, 0, 120), width=lw + 2); d.line([p0, p1], fill=(238, 238, 234, 240), width=lw)
        if text:
            words(tx, ty, text)                                   # no words: a second leader to the label before it
            boxes.append((text, (tx - 0.45 * u, ty - 0.1 * u, tx + tw + 0.45 * u, ty + th + 0.1 * u)))
    boxes = []
    if kind == "story":
        for pt, text, dx, dy, *gap in t["labels"](rgb):           # a label may carry its own gap as a fifth value
            if 0 <= pt[0] < W and 0 <= pt[1] < H: label(pt, text, dx, dy, leader=text not in t.get("plain", ()), gap=gap[0] if gap else None)
        # every label's box must sit wholly inside the picture and clear of the others (a label once ran off the left edge)
        bad = []
        for i, (text, (x0, y0, x1, y1)) in enumerate(boxes):
            inside = x0 >= ox and y0 >= 0 and x1 <= ox + W and y1 <= H
            print("label box %-48s x %4.0f..%4.0f  y %4.0f..%4.0f  %s" % (text, x0 - ox, x1 - ox, y0, y1, "inside" if inside else "OUTSIDE"))
            if not inside: bad.append(text)
            for text2, (a0, b0, a1, b1) in boxes[i + 1:]:
                if x0 < a1 and a0 < x1 and y0 < b1 and b0 < y1: bad.append(text + " overlaps " + text2)
        if bad: raise SystemExit("labels not placed: %s" % bad)
    bl, btxt = t["bar"]; ang = bl * t["scale"]; angtxt = "%.1f arcminutes" % (ang / 60) if ang >= 90 else "%.0f arcseconds" % ang
    angtxt = t.get("bar_sub", angtxt)                             # a bar that is already a round angle says underneath what that angle is out there
    if kind == "how": bl = round(ang / 60 if ang >= 90 else ang) * (60 if ang >= 90 else 1) / t["scale"]; ang = bl * t["scale"]; btxt = ("%.0f arcminutes" % (ang / 60) if ang >= 90 else "%.0f arcseconds" % ang); btxt = re.sub(r"^1 (arcminute|arcsecond)s$", r"1 \1", btxt); angtxt = "%.3g arcsec per pixel" % t["scale"]
    bx, by = ox + pad, H - pad
    d.line([(bx, by), (bx + bl, by)], fill=(0, 0, 0, 120), width=lw + 3); d.line([(bx, by), (bx + bl, by)], fill=INK, width=lw + 1)
    for xx in (bx, bx + bl): d.line([(xx, by - 0.5 * u), (xx, by + 0.5 * u)], fill=INK, width=lw + 1)
    tw = d.textlength(btxt, font=fN); words(max(bx, bx + bl / 2 - tw / 2), by - 3.3 * u, btxt)
    tw = d.textlength(angtxt, font=fC); words(max(bx, bx + bl / 2 - tw / 2), by + 0.7 * u, angtxt, f=fC, fill=SOFT)
    if t.get("compass", True):
        a = math.radians(t["north"]); cx, cy, r = ox + W - pad - 4 * u, H - pad - 1.5 * u, 4.2 * u
        nx, ny = -math.sin(a), -math.cos(a); ex, ey = -math.cos(a), math.sin(a)            # north is `north` deg counter-clockwise of up; east is to its left
        for (vx, vy, txt, k) in ((nx, ny, "N", 1.0), (ex, ey, "E", 0.62)):
            tip = (cx + vx * r * k, cy + vy * r * k); d.line([(cx, cy), tip], fill=(0, 0, 0, 120), width=lw + 2); d.line([(cx, cy), tip], fill=INK, width=lw)
            lx, ly = cx + vx * (r * k + 1.4 * u), cy + vy * (r * k + 1.4 * u); d.text((lx - d.textlength(txt, font=fC) / 2, ly - 0.7 * u), txt, font=fC, fill=INK)
    if not caption: return canvas
    d.rectangle([0, H, Wc, H + band], fill=BAND + (255,))
    for x0, y0, x1 in rules: d.line([(x0, H + y0), (x1, H + y0)], fill=RULE, width=max(1, int(u / 14)))
    for x, y, text, f, fill in ops: d.text((x, H + y), text, font=f, fill=fill)
    out = "share/%s-%s.jpg" % (name, "annotated" if kind == "story" else "how"); canvas.save(out, quality=93, subsampling=0, optimize=True); return out

# the order of the night's page is the order of the entries in targets() (ORDER is set from it below)
THUMB = {}           # the part of a picture its small version shows: x, y, width, height (none tonight: all whole)
CARD = {}            # the part a link preview shows, at the picture's own pixels (none tonight; the builder shows a small picture whole)
CARD_TEXT = {}       # where a link preview's words go when the foot of the picture is the busy part (the nebula is in the middle)

def site(out):
    """The same set for the website: pictures at full size and 1600 wide, small ones for the grid, and the words as data
    (objects.json) so the page sets them as text. Pictures carry no caption band here."""
    os.makedirs(out + "/images", exist_ok=True); objects = []
    def put(img, stem, q):
        img.save("%s/images/%s.jpg" % (out, stem), quality=q, subsampling=0, optimize=True)
        if img.width > 1600: img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS).save("%s/images/%s-1600.jpg" % (out, stem), quality=88, subsampling=0, optimize=True)
    for name in ORDER:
        t = T[name]; clean = Image.fromarray(load(t["src"])); put(clean, name, 93)
        x, y, w, h = THUMB.get(name, (0, 0, clean.width, clean.height)); small = clean.crop((x, y, x + w, y + h)); small.thumbnail((900, 900), Image.LANCZOS)
        small.save("%s/images/%s-thumb.jpg" % (out, name), quality=86, subsampling=0, optimize=True)
        put(render(name, t, "story", caption=False), name + "-labels", 93)
        frames = bool(t.get("outlines") or t.get("how_labels")); card = None
        if name in CARD:
            x, y, w, h = CARD[name]; card = name + "-card.jpg"; clean.crop((x, y, x + w, y + h)).save("%s/images/%s" % (out, card), quality=92, subsampling=0, optimize=True)
        if frames: put(render(name, t, "how", caption=False), name + "-frames", 93)
        objects.append(dict(slug=name, title=t["title"], subtitle=t["sub"], what=t["what"], facts=[[k.capitalize(), sent(v)] for k, v in t["facts"]],
                            made=sent(t["frames"]), how=sent(t["how_sub"]), specs=[[k.capitalize(), sent(v)] for k, v in t["tech"]],
                            width=clean.width, height=clean.height, thumb=[small.width, small.height], arcsec_per_px=t["scale"], frames=frames, card=card, card_text=CARD_TEXT.get(name, "bottom")))
        print("site: %-18s %d x %d%s" % (name, clean.width, clean.height, ", with frames" if frames else ""))
    json.dump(dict(credit=GEAR, made_with=MADE, objects=objects), open(out + "/objects.json", "w"), indent=1, ensure_ascii=False)

T = targets(); ORDER = list(T)
if len(sys.argv) > 2 and sys.argv[1] == "--site": site(sys.argv[2]); sys.exit(0)
for name in (sys.argv[1:] or ORDER):
    t = T[name]; rgb = load(t["src"])
    Image.fromarray(rgb).save("share/%s.jpg" % name, quality=93, subsampling=0, optimize=True)
    a, b = render(name, t, "story"), render(name, t, "how")
    print("%-20s %5d x %-5d  clean %4.2f MB  annotated %4.2f MB  how %4.2f MB" % (name, rgb.shape[1], rgb.shape[0], os.path.getsize("share/%s.jpg" % name) / 1e6, os.path.getsize(a) / 1e6, os.path.getsize(b) / 1e6))
