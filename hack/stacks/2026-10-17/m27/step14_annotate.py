"""Step 14: the share set for Messier 27 (night of 17 October 2026): three JPEGs, as the annotate-pictures skill says.

  <name>.jpg            the picture as it is, nothing on it
  <name>-annotated.jpg  names, a scale bar and north on the picture; underneath, what it is, how far, how big
  <name>-how.jpg        for photographers: exposures, frames kept and lost, sampling, calibration, stacking and finishing

The caption band is added underneath; it never covers the picture. All drawing is plain text and lines.
JPEGs are full resolution, quality 93, no chroma subsampling, no metadata.

Usage: annotate.py [name ...]           (no names: all) -> share/
       annotate.py --site <folder>      the same pictures and words for the website: <folder>/images and <folder>/objects.json

ADDING A PICTURE: add one entry to targets(), keyed by its website slug, and run both lines again. The page shows the
pictures in the order of the entries. Nothing else in this file changes.

Copied from hack/stacks/2026-10-12/annotate.py (itself from the 8 October 2026 script (itself from .claude/skills/annotate-pictures/tools/annotate.py) with tonight's
targets() table. Four changes for tonight:
  - a finished picture and its stack no longer share a name: final/<file>.json is the finish recipe only, and each
    stack's own recipe is <folder>/recipe.json, so an entry reads both (finish(), stack());
  - an entry may give the words under its scale bar (bar_sub): a double star's bar is a round angle, with what that
    angle is at the star's distance underneath, where a nebula's bar is a round length with its angle underneath;
  - an entry may say how far short of a thing its leaders stop (gap, in drawing units): a bright star's glow is wider
    than the 0.9 that suits a nebula; and one label may carry its own as a fifth value (a dust lane is a thin thing, and
    a leader that stops 0.9 short of it ends on the light beside it); and a label with no words draws only its leader,
    so that one set of words can point at two things (the two stars of Messier 78) when both leaders end at one place;
  - the page order is the order of the entries.
Small pictures (a 640 px crop at the sensor's own scale, never enlarged) are handled as on 8 October: the drawing unit
has a floor (UMIN) and the share versions sit at their own size in the middle of a band wide enough for the words.
Every number in targets() is copied from that picture's recipe files; the arithmetic for the facts is beside them.

Nothing here gives a clock time, and never the measured altitude: together with the object they would place the
telescope. The words carry the part of the night ("after midnight") and "nearly overhead" or an altitude rounded to
the nearest ten degrees, nothing finer.
"""
import json, math, os, re, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); os.makedirs("share", exist_ok=True)   # m27/: reads final/m27.png, final/m27.json, final/recipe.json; writes share/
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
def font(size, weight="regular"): return ImageFont.truetype(AVENIR, max(8, int(round(size))), index={"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight])
INK, SOFT, DIM, BAND, RULE = (244, 244, 240), (198, 198, 194), (140, 140, 138), (10, 10, 12), (62, 62, 64)
# f/10.3: every stack's plate solve tonight gives 2,084 to 2,089 mm on 203 mm of aperture (10.27 to 10.29); each picture's own focal length is in its rows
GEAR = "© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  night of 17 October 2026"
TRUE = "Stacked from the camera's RAW frames. Nothing generated."
CAMERA = ("CAMERA", "Sony a6000, stock, at prime focus: APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW")
MOUNT = ("MOUNT", "Sky-Watcher EQ6-R, unguided, not dithered on this target. Set down about 10 degrees off the pole; aligned from four plate-solved photos (under 1 arcminute), both axes driven from that model")
MADE = "Capture and mount: Observatory (Elixir on a Raspberry Pi 3).  Stacking: numpy, OpenCV, rawpy.  Plate solving: astrometry.net.  " + TRUE
STACK = "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered on stars with rotation, proper coaddition (Zackay and Ofek: each frame weighted by its own measured blur and noise)"
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

def targets():
    T = {}
    rec = json.load(open("final/recipe.json")); fin = finish("m27"); s9 = step(rec, "9 plate solve of the stack and the crop")["numbers"]
    S = s9["pixscale_arcsec"]; FL = s9["focal_length_mm"]; NORTH = s9["north_angle_from_up_deg_clockwise"]
    # -- Messier 27, the Dumbbell Nebula (final/m27.png, final/m27.json, final/recipe.json) -----------------------------
    # picture 1200 x 1000 at 0.7766 arcsec/px = 15.5 x 12.9 arcmin, cut from the stack and not turned: north 116.2 deg
    # clockwise of up (so -116.2 here), east 26.2 deg clockwise of up, not mirrored. The central star at (601, 500).
    # Distance roughly 1,300 ly (Gaia's parallax of the central star; estimates run 1,200 to 1,400), a soft number.
    # Spans 1300 x 15.5 x 2.909e-4 = 5.9 ly ("about 6"). The nebula as followed in the stack, ears included: 8.1 arcmin
    # across (recipe: followed to 4.04 arcmin from the star): 1300 x 8.1 x 2.909e-4 = 3.06 ly ("about 3").
    # One pixel: 1300 x 0.7766 x 4.848e-6 = 0.0049 ly = 0.0049 x 63,241 = 310 times the Earth-Sun distance.
    # Light left 2026 - 1300 = about the year 700 (1200 to 1400 ly: 600 to 800): the Maya were raising the great temples of
    # Tikal (Temple I about 732), and that holds over the whole range. The nebula's own age, about 10,000 years, is from
    # its expansion (published), not from this picture.
    # Bar: 2 ly = 2 / (1300 x 2.909e-4) = 5.29 arcmin = 408 px.
    # Labels, each looked at in a full-size crop. Brightness (grey, Gaussian 6 px) along four directions from the star,
    # every 30 px: PA 30 and 210 (left and right in the picture) the bright body runs to 240 px (3.1 arcmin) and stops;
    # PA 120 and 300 (up and down) a fainter grey light runs on to 300 to 330 px (4 arcmin): the ears, which step 12 found
    # in both halves at 11 to 12 sigma, 3 to 4 arcmin out. Ear leaders end at 280 px from the star: (580, 220), (620, 780), one label each.
    #   central star   peak() at (601, 500)
    #   bright lobes   the body along PA 210 (left), 150 px out: (451, 510)
    #   the orange star at (490, 668), 2.6 arcmin from the centre: a foreground star, not part of the nebula (it is in
    #                  Gaia with a parallax; the label only says it is in front, which is all the picture shows).
    D = 1300.0
    T["m27"] = dict(src="final/m27.png", scale=S, north=-NORTH, title="The Dumbbell Nebula", sub="Messier 27, a planetary nebula in Vulpecula",
        what="This is what a star like the Sun does at the end: it puffs its outer layers off into space, and the bare, hot core left behind, one of the hottest stars known, makes them glow. The cloud has been growing for about 10,000 years. Charles Messier found it in 1764: the first nebula of its kind anyone saw.",
        facts=[("DISTANCE", "roughly 1,300 light-years (not exactly known: 1,200 to 1,400)"),
               ("THIS PICTURE SPANS", "about 6 light-years; the nebula with its faint outer lobes is about 3 across, and one pixel is about 300 times the distance from the Earth to the Sun"),
               ("THE LIGHT LEFT", "around the year 700, while the Maya were raising the great temples of Tikal"),
               ("HONEST NOTE", "the glow from oxygen is a blue-green purer than any screen can show, so the screen's nearest colour stands in for it. The faint halo deep pictures show further out is not reached in 16 minutes from a suburban sky")],
        bar=(bar(2, D, S), "2 light-years"), frames="66 of 70 frames of 15 s",
        labels=lambda im: [(peak(im, (601, 500), 8, 1.5), "The central star, a dying star's hot core", 9, 13, 1.2),
                           ((451, 510), "Bright lobes of glowing gas", -14, -15),
                           ((580, 220), "Faint outer lobe", 10, -6),
                           ((620, 780), "Faint outer lobe", 10, 6),
                           ((490, 668), "A star in front, not part of the nebula", -12, 13, 1.6)],
        how_sub="16.5 minutes of light on a clear evening, the first target of the night",
        tech=[("EXPOSURES", "66 x 15 s at ISO 3200: 16.5 minutes. Nothing clipped on the nebula: its brightest pixel reached 12 percent of the sensor's range in a frame"),
              ("FRAMES", "70 taken, 66 kept. The first after the slew was dropped by rule; three were smeared (every star stretched the same way, ellipticity 0.20 to 0.21). No cloud: every frame's stars within 2 percent of the run's typical brightness"),
              ("SAMPLING", "%.3f arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars %.1f arcsec wide (half-flux) in the stack" % (S, float(rec["summary"]["star_size"].split("arcsec in the stack")[0].split(": ")[-1]))),
              ("FIELD", "15.5 x 12.9 arcmin: a 1200 x 1000 crop from a stack of 36.9 x 24.3 arcmin, nothing resampled after the stack, not turned (north 116 degrees clockwise of up)"),
              ("WHEN", "The evening of 17 October 2026, over 36 minutes. About 60 degrees up"),
              ("REGISTRATION", "Rotation and shift on the stars; the field drifted 3 arcmin across the sensor and turned 0.05 degrees. Red and blue star images sat 0.3 sensor px off green (the air's prism): measured and taken out in the one resampling"),
              ("CALIBRATION", "No darks and no flat frames tonight. The flat of 13 October (large scale from that night's open sky, dust from its twilight frames), picked over two others on this run's own sky; dust that moved since was measured on this run's own sky, seen in the odd and the even frames alone, and divided out: 11 shadows, among them a new crescent 13 percent deep, left at under 2. Hot pixels from the run itself"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour, about 3 DN across it. The old sigma-clipped mean was made beside it as a control"),
              ("WHAT IS REAL", "The bright body and the faint outer lobes that fill it out to its apple shape: 3 to 4 arcmin from the star they stand 11 to 12 times above blank sky in the odd and the even frames each alone. The nebula is followed 8.1 arcmin across"),
              ("NOT SEEN", "The faint outer halo of deep pictures: beyond 4 arcmin from the star nothing passes the half-stack test. Nor the fine knots inside the nebula: the stars are 4.5 arcsec wide"),
              ("COLOUR", "The camera's colour matrix with its white balance set by the colours of %s Gaia stars in the field (red x 1.01, blue x 1.15). The oxygen glow is outside what a screen shows; the faint lobes are grey, because their colour there is set by sky and flat, not the nebula" % rec["steps"][9]["numbers"].get("fit", {}).get("stars", 93) if isinstance(rec["steps"][9]["numbers"], dict) else 93),
              ("FINISH", "Arcsinh stretch; black at the 50th percentile, S-curve 0.15, saturation x 1.2; the dark sky smoothed (bilateral 4 px) and set near black, by choice: %.1f percent of the picture is exactly black" % fin.get("clipped_to_black_pct", 0)),
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
        if text: words(tx, ty, text)                              # no words: a second leader to the label before it
    if kind == "story":
        for pt, text, dx, dy, *gap in t["labels"](rgb):           # a label may carry its own gap as a fifth value
            if 0 <= pt[0] < W and 0 <= pt[1] < H: label(pt, text, dx, dy, leader=text not in t.get("plain", ()), gap=gap[0] if gap else None)
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
