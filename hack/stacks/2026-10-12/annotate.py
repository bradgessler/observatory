"""The share set for the night of 12 October 2026: three JPEGs for every finished picture.

  <name>.jpg            the picture as it is, nothing on it
  <name>-annotated.jpg  names, a scale bar and north on the picture; underneath, what it is, how far, how big
  <name>-how.jpg        for photographers: exposures, frames kept and lost, sampling, calibration, stacking and finishing

The caption band is added underneath; it never covers the picture. All drawing is plain text and lines.
JPEGs are full resolution, quality 93, no chroma subsampling, no metadata.

Usage: annotate.py [name ...]           (no names: all) -> share/
       annotate.py --site <folder>      the same pictures and words for the website: <folder>/images and <folder>/objects.json

ADDING A PICTURE: add one entry to targets(), keyed by its website slug, and run both lines again. The page shows the
pictures in the order of the entries. Nothing else in this file changes.

Copied from the 8 October 2026 script (itself from .claude/skills/annotate-pictures/tools/annotate.py) with tonight's
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

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); os.makedirs("share", exist_ok=True)
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
def font(size, weight="regular"): return ImageFont.truetype(AVENIR, max(8, int(round(size))), index={"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight])
INK, SOFT, DIM, BAND, RULE = (244, 244, 240), (198, 198, 194), (140, 140, 138), (10, 10, 12), (62, 62, 64)
# f/10.3: every stack's plate solve tonight gives 2,084 to 2,089 mm on 203 mm of aperture (10.27 to 10.29); each picture's own focal length is in its rows
GEAR = "© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  night of 12 October 2026"
TRUE = "Stacked from the camera's RAW frames. Nothing generated."
CAMERA = ("CAMERA", "Sony a6000, stock, at prime focus: APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW")
MOUNT = ("MOUNT", "Sky-Watcher EQ6-R, unguided. Set down without polar alignment, about 5 degrees off the pole; aligned from four plate-solved photos (about 1 arcminute), both axes driven from that model")
MADE = "Capture and mount: Observatory (Elixir on a Raspberry Pi 3).  Stacking: numpy, OpenCV, rawpy.  Plate solving: astrometry.net.  " + TRUE
STACK = "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered on stars with rotation, sigma-clipped weighted mean"
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

    # -- the Triangulum Galaxy, M33 (final/m33.json, m33/recipe.json) ------------------------------------------------
    # picture 2844 x 1892 at 0.776162854644 arcsec/px = 36.79 x 24.48 arcmin (the recipe's plate solve: field_arcmin
    # [36.79, 24.48]), the camera's orientation: north 56 deg anticlockwise of up, east 146 (not mirrored, not turned).
    # Distance about 2.7 million ly (2.7 to 3.0 published; 2.7 as on 8 October).
    # Spans 2.7e6 x 36.79 x 2.909e-4 = 28,900 ly (and 2.7e6 x 24.48 x 2.909e-4 = 19,200 ly tall); the galaxy is about
    # 60,000 ly across: 60,000 / 28,900 = 2.1, "about twice that".
    # Light left 2.7 million years ago (the northern ice ages took hold about 2.7 million years ago).
    # One pixel = 2.7e6 x 0.776163 x 4.848e-6 = 10.2 ly; the nearest star to the Sun is 4.24 ly: 10.2 / 4.24 = 2.4 times.
    # The stars are 3.6 arcsec wide: 2.7e6 x 3.6 x 4.848e-6 = 47 ly, so nothing finer than about 50 ly is shown.
    # Bar: 5,000 ly = 5000 / (2.7e6 x 2.909e-4) = 6.37 arcmin = 492 px.
    # Labels, each from the plate solution's catalogue place in the recipe (step "plate solve", catalogue_check) and then
    # looked at in a full-size crop:
    #   nucleus  catalogue px (1373.7, 782.2), brightest spot (1373, 781), 1.6 arcsec off: the star-like point in the gold glow
    #   NGC 604  catalogue px (505.3, 1033.7), brightest spot (511, 1027), inside the blue and pink cloud (the recipe's own
    #            peak is (504, 1027), 5.3 arcsec off: the cloud is about 60 px wide and has several knots)
    #   NGC 595  catalogue px (1410.1, 467.2), brightest spot (1412, 460), 5.6 arcsec off: the pink knot with a faint ring
    #   NGC 592  catalogue px (1785.8, 284.5): it falls on the lower edge of a clump of haze whose brightest knot is at
    #            (1784, 278). The brightest thing within 12 px, (1790, 297), is a yellow star just under the haze, not the
    #            cloud, so the name points at the haze and peak() is kept to 6 px so that it cannot reach the star.
    #   NGC 588  is off the top of the picture (catalogue px (2032.6, -90.3)): not named.
    #   the bright star at (2543, 1300) is at the sensor's ceiling in the stack (green 18,700 DN over the pedestal, shown
    #            white) where the galaxy's own nucleus, also a point, peaks at 860: over 20 times brighter, 3.3 magnitudes.
    #            M33's nucleus is a cluster of millions of stars; at 2.7 million ly (distance modulus 24.6) a single star
    #            that outshone it 20 times over would be near absolute magnitude -14, brighter than any star is. So it is a
    #            star of our own galaxy, in front. Named because it is the brightest thing in the picture.
    T["triangulum-galaxy"] = dict(src="final/m33.png", scale=0.776162854644, north=56.0, title="The Triangulum Galaxy", sub="Messier 33, a spiral galaxy in Triangulum",
        what="The third-largest galaxy in our small group of neighbours, after Andromeda and our own Milky Way: a loose spiral of some 40 billion stars. The blue knot at the left, NGC 604, is a cloud where new stars are being born, 1,500 light-years across. From this far away, one pixel of the picture is 10 light-years wide: more than twice the way from the Sun to the nearest star.",
        facts=[("DISTANCE", "about 2.7 million light-years"), ("THIS PICTURE SPANS", "29,000 light-years; the whole galaxy is about twice that"), ("THE LIGHT LEFT", "2.7 million years ago, as the ice ages began"),
               ("HONEST NOTE", "the disc is grey on purpose: these frames cannot measure its faint colour. White stars lean a little green")],
        bar=(bar(5000, 2.7e6, 0.776162854644), "5,000 light-years"), frames="66 of 104 frames of 15 s; 34 were trailed by a tracking fault that was fixed during the run",
        labels=lambda im: [(peak(im, (1373.7, 782.2), 12, 2), "Nucleus", 8, 7), (peak(im, (505.3, 1033.7), 14, 3), "NGC 604, a giant star nursery", 7, 6),
                           (peak(im, (1410.1, 467.2), 12, 3), "NGC 595", -8, -4), (peak(im, (1784, 278), 6, 3), "NGC 592", 8, 3),
                           (peak(im, (2543, 1300), 12, 3), "A star in our own galaxy, in front", -6, 5)],
        how_sub="16.5 minutes of light on one field, under a clear sky",
        tech=[("EXPOSURES", "66 x 15 s at ISO 3200: 16.5 minutes"),
              ("FRAMES", "104 taken, 66 kept. 34 frames were trailed by a tracking fault that was fixed during the run: the drive let go of both motors for about 5 s now and then, leaving each star a dot with a tail of 4 to 9 arcsec. 4 more had soft stars (4.4 to 4.7 arcsec). Clear: every untrailed frame within 5 percent of the run's star brightness"),
              ("SAMPLING", "0.776 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 3.6 arcsec wide (half-flux), against 3.9 on 8 October"),
              ("FIELD", "36.8 x 24.5 arcmin: the part of one sensor frame that at least 53 of the 66 frames cover, as the camera saw it (north 56 degrees anticlockwise of up). Not turned: a turn would resample the picture"),
              ("WHEN", "13 October 2026, after midnight, over 72 minutes. High in the sky, about 80 degrees up"),
              ("FIELD ROTATION", "1.7 degrees over the run, because the polar axis is about 5 degrees off; corrected in registration (rotation and shift on 65 to 73 stars, 0.3 to 0.5 px rms)"),
              ("CALIBRATION", "No darks and no flat frames were taken. Vignetting: the radial profile measured on 8 October from open sky, same telescope, camera and settings (corners at 69 percent); the galaxy fills tonight's frames, so it cannot be checked. Dust: 10 shadows found in tonight's own frames and divided out, each only where both halves of the run show it alike. Hot pixels from the run itself (5,700 to 6,500 per colour plane)"),
              ("STACKING", STACK + ". One constant per colour per frame, set where the galaxy is faintest; no surface fitted. Noise 7.8 times lower than one frame (8.1 expected from the weights), and half that of 8 October's picture of this field, which had a third of the light (5.25 minutes)"),
              ("ZERO LEVEL", "The galaxy is bigger than the frame, so the true sky cannot be measured: zero is the galaxy's faintest part in this field. The black point was raised for a quiet sky, which leaves about 2 percent of the picture, the darkest sky, exactly black"),
              ("COLOUR", "Shown only where the light can carry it, 0.4 percent of the picture: the stars, the core, the brightest star-forming clouds such as NGC 604. The disc is grey on purpose. White stars come out slightly green (red : green : blue about 0.91 : 1 : 0.94): the camera's daylight white balance and matrix, with no star-colour calibration"),
              ("FINISH", "The camera's daylight white balance and colour matrix. Brightness smoothed 1 px, arcsinh stretch. Black at the 14th percentile, gamma 0.9, S-curve 0.3, saturation x 1.25. Dark sky smoothed (bilateral, 3 px) and without colour"),
              ("KNOWN FLAWS", "Stars towards the corners have a short flare pointing away from the centre: the optics off axis, not the tracking. Two shallow dust shadows near the middle could not be confirmed tonight and were left alone"),
              optics(step(stack("m33"), "plate solve")["focal_length_mm"]), CAMERA, MOUNT])

    # -- Almach, Gamma Andromedae (final/almach.json, almach/recipe.json) ---------------------------------------------
    # picture 640 x 640 at 0.3881364555 arcsec per px (the sensor's own pixels) = 248.4 arcsec = 4.14 arcmin square,
    # north up, east left (not mirrored). The pair measured 9.55 arcsec apart at position angle 62.3 deg (mean of 13 frames).
    # Distance roughly 350 ly (Hipparcos: 355 ly from the first reduction, 390 from the second; not well known).
    # Spans 350 x 4.14 x 2.909e-4 = 0.42 ly.
    # The gap: 350 x 9.55 x 4.848e-6 = 0.0162 ly; x 63,241 Earth to Sun distances per ly = 1,025; and 0.0162 years of
    # light travel x 365.25 = 5.9 days. We see the gap flat on the sky, so the true distance between them is at least that.
    # Light left 2026 - 350 = 1676, the year Ole Roemer first measured the speed of light (at 390 ly it is 1636: "the 1600s").
    # Bar: 30 arcsec = 30 / 0.3881364555 = 77.3 px; at 350 ly that is 350 x 30 x 4.848e-6 x 63,241 = 3,219 Earth to Sun distances.
    # Labels: the two stars, found with peak(): primary at (330, 325), companion at (308, 314). Check against the measurement:
    # 9.55 arcsec at 62.3 deg east of north = 21.8 px left and 11.4 px up of the primary = (308.2, 313.6).
    T["almach"] = dict(src="final/almach.png", scale=0.3881364555475, north=0.0, title="Almach", sub="Gamma Andromedae, a gold and blue double star in Andromeda",
        what="To the eye it is one star in Andromeda. A telescope splits it in two: a gold giant and a small blue companion, a favourite for the contrast of their colours. The blue one is really three stars, too close together for this picture to separate. Everything here, both stars and the dark between them, would fit in half a light-year.",
        facts=[("DISTANCE", "roughly 350 light-years (not well known)"), ("THE TWO STARS ARE", "at least 1,000 times as far apart as the Earth is from the Sun: six days for light to cross"),
               ("THE LIGHT LEFT", "around 1676, the year the speed of light was first measured"),
               ("HONEST NOTE", "the colours are as the camera recorded them, with nothing added: the gold star is probably a little more orange than this, and the blue one a little bluer")],
        bar=(30 / 0.3881364555475, "30 arcseconds"), bar_sub="about 3,200 times the Earth to Sun distance", gap=1.6, frames="the sharpest 5 of 13 frames of 1/60 s",
        labels=lambda im: [(peak(im, (330, 325), 8, 1.5), "Gold giant", 6, 5), (peak(im, (308, 314), 6, 1.5), "Blue companion", -6, -5)],
        how_sub="the sharpest 5 of 13 frames, each a sixtieth of a second, at the sensor's own scale",
        tech=[("EXPOSURES", "5 x 1/60 s at ISO 400: a twelfth of a second of light. The primary did not clip: the brightest pixel of any colour plane in any frame is 72 percent of the 14-bit ceiling"),
              ("FRAMES", "13 taken, the sharpest 5 kept: the primary 3.03 to 3.46 arcsec wide (half-flux) in those, 3.65 to 4.31 in the 8 left out. A sixtieth of a second freezes the air, so a frame is sharp or it is not, and every frame added softens the star: all 13 give 3.70 arcsec against 3.32 for these 5"),
              ("SAMPLING", "0.388 arcsec per pixel: the sensor's own pixels, never enlarged. The pair is 25 px across; the stars are 3.3 arcsec wide (half-flux)"),
              ("FIELD", "4.1 x 4.1 arcmin: a 640 x 640 crop round the pair, north up and east left by one Lanczos turn of 56.2 degrees. No other star shows in a sixtieth of a second"),
              ("WHEN", "13 October 2026, after midnight, over 5 minutes. Nearly overhead"),
              ("THE PAIR", "9.55 arcsec apart (standard error 0.09) at position angle 62.3 degrees (0.3): two-star fits to each of the 13 frames. With the model's own error, 9.6 plus or minus 0.15 arcsec at 62 plus or minus 1 degrees. The primary is 9.0 times the companion in the camera's green (2.4 magnitudes)"),
              ("CALIBRATION", "No darks and no flat. Each frame's sky median taken off per colour plane, one hot pixel repaired. The pair sits at the middle of the sensor, where a flat would change it by well under a percent"),
              ("STACKING", "RAW colour planes (no demosaic). Shift only: each plane of each frame placed on its own centroid of the primary, at the true sensor position of every sample, as square drops of 1 px (drizzle). Each frame scaled to the run's median brightness first, since the star twinkles 8 percent from frame to frame"),
              ("ORIENTATION", "From a plate-solved 15 s frame of the same field, taken just before with the camera untouched: in a sixtieth of a second there are no other stars to solve on"),
              ("COLOUR", "The camera's daylight white balance (red x 2.67, blue x 1.24) and its own colour matrix, no star-colour calibration, saturation x 1.0. Red over green and blue over green: primary 1.09 and 0.56, companion 0.72 and 1.02. The companion is the bluer star in 13 of 13 frames; the primary's red halo spills onto it, so it is bluer than shown"),
              ("FINISH", "Brightness smoothed 0.8 px, colour 1.5 px, arcsinh stretch. Black at the 60th percentile, white at the brightest channel of the brightest pixel, S-curve 0.15, no saturation added. Dark sky smoothed (bilateral, 2 px) and without colour"),
              ("NOT RESOLVED", "The companion is itself a close pair, about half an arcsecond apart: far inside the 3.3 arcsec blur of the air on this night. A seeing-limited picture; nothing finer than 2 to 3 arcsec is shown"),
              # the recipe carries the focal length only in its opening line: "(2,084 mm, f/10, 0.388 arcsec per sensor pixel by plate solve)"
              optics(float(re.search(r"\(([\d,]+) mm", stack("almach")["what"]).group(1).replace(",", ""))), CAMERA, MOUNT])

    # -- NGC 891 (final/ngc891.json, ngc891/recipe.json) -------------------------------------------------------------
    # picture 1800 x 1200 at 0.776055343688 arcsec/px = 23.28 x 15.52 arcmin (the recipe's crop: 23.3 x 15.5), cut at
    # (616, 340) from the 2952 x 1962 stack with nothing resampled; the camera's orientation: north 56 deg anticlockwise of
    # up, east 146. Distance about 30 million ly, a round figure (27 to 32 published).
    # Spans 3.0e7 x 23.28 x 2.909e-4 = 203,000 ly. The disc is followed for 11.12 arcmin: 3.0e7 x 11.12 x 2.909e-4 =
    # 97,000 ly, "about 100,000" (the catalogue's 13.5 arcmin would be 118,000); our own galaxy's disc is about 100,000 ly.
    # Missing at each end: (13.5 - 11.12) / 2 = 1.19 arcmin = 9 percent of the length, "about a tenth".
    # Light left 30 million years ago, in the Oligocene: Paraceratherium, a hornless rhinoceros of 15 to 20 tonnes and one
    # of the largest land mammals known, lived in Asia from about 34 to 23 million years ago, which covers 27 to 32.
    # One pixel = 3.0e7 x 0.776055 x 4.848e-6 = 113 ly. Bar: 25,000 ly = 25000 / (3.0e7 x 2.909e-4) = 2.86 arcmin = 221 px.
    # Labels. The galaxy's own axes on this picture: centre = the catalogue place on the stack (1515.7, 940.0) less the
    # crop's corner = (899.7, 600.0); long axis at position angle 22 deg, so 56 + 22 = 78 deg anticlockwise of up:
    # u = (-0.978, -0.208) along the disc, v = (0.208, -0.978) across it. Brightness of the picture (3 px blur) across the disc:
    #   through the centre (u = 0):   158 at v = -16, 71 at v = 0, 165 at v = +20: two ridges and the lane between them,
    #                                 as the recipe measured on the stack (ridges at -20 and +22 px, 33 arcsec apart)
    #   60 px along (u = -60):        120 at v = -20, 22 at v = 0, 103 at v = +28: the lane at its darkest
    #   central bulge  the ridge at u = 0, v = +20: (899.7 + 20 x 0.208, 600 - 20 x 0.978) = (904, 580)
    #   dust lane      the dip at u = -60, v = 0: (899.7 + 60 x 0.978, 600 + 60 x 0.208) = (958, 612); its leader runs to
    #                  within 4 px, so that it ends on the lane and not on the light beside it
    #   two stars sit on the disc and could be taken for knots of the galaxy: at (797, 546), on its edge 1.5 arcmin from
    #                  the centre, and at (1225, 662), on its midline 4.3 arcmin out. In the stack their green peaks are
    #                  5,490 and 1,450 DN where the galaxy's brightest ridge is 40. At 30 million ly (distance modulus
    #                  29.8) even the most luminous stars would be near magnitude 21, far below what 7.5 minutes shows:
    #                  every sharp point in this picture is a star of our own galaxy.
    # No companion galaxy is named: the recipe identified none.
    T["ngc-891"] = dict(src="final/ngc891.png", scale=0.776055343688, north=56.0, title="NGC 891", sub="A spiral galaxy in Andromeda, seen edge on",
        what="A spiral galaxy much like our own, seen almost exactly from the side. The dark line down its middle is dust in the disc, the same kind of dust that draws the dark lanes through our Milky Way on a clear night. This is roughly how our own galaxy would look from outside: a thin disc of stars with a warm bulge of older stars at its centre.",
        facts=[("DISTANCE", "about 30 million light-years (a round figure)"), ("THIS PICTURE SPANS", "200,000 light-years; the disc shown is about 100,000 long, the size of our own galaxy"),
               ("THE LIGHT LEFT", "about 30 million years ago, when giant hornless rhinos, among the largest land mammals ever, walked Asia"),
               ("HONEST NOTE", "seven and a half minutes of light is too little for the faint tips of the disc: about a tenth of its length is missing at each end")],
        bar=(bar(25000, 3.0e7, 0.776055343688), "25,000 light-years"), frames="30 of 31 frames of 15 s",
        labels=lambda im: [((904, 580), "Central bulge", 0, -8), ((958, 612), "Dust lane", 5, 6, 0.25),
                           (peak(im, (797, 546), 8, 1.5), "A star in our own galaxy, in front", -3, -7), (peak(im, (1225, 662), 8, 1.5), "Another star in front", 3, 7)],
        how_sub="7.5 minutes of light on one field; no frame trailed",
        tech=[("EXPOSURES", "30 x 15 s at ISO 3200: 7.5 minutes"),
              ("FRAMES", "31 taken, 30 kept. Only the first frame after the slew was dropped, by rule (it measured fine). No frame trailed: stars 3.6 to 4.4 arcsec, every frame within 1.3 percent of the run's star brightness"),
              ("SAMPLING", "0.776 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 3.8 arcsec wide (half-flux)"),
              ("FIELD", "23.3 x 15.5 arcmin: an 1800 x 1200 crop round the galaxy from a stack of 38.2 x 25.4 arcmin, nothing resampled, as the camera saw it (north 56 degrees anticlockwise of up)"),
              ("WHEN", "13 October 2026, after midnight, over 20 minutes. Nearly overhead"),
              ("FIELD ROTATION", "0.5 degrees over the run, because the polar axis is about 5 degrees off; corrected in registration (rotation and shift on about 180 stars, 0.26 to 0.36 px rms)"),
              ("CALIBRATION", "No darks and no flat frames were taken. The flat is built from this run's own open sky, per colour: an elliptical fall-off (light falls off faster along the sensor's short side; green corners at 68 percent) and a measured map of 58 dust shadows over 1.9 percent of the sensor. Dust under the galaxy itself could not be measured. Hot pixels from the run itself (5,900 to 6,600 per colour plane)"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 5.3 times lower than one frame (5.5 expected from the weights)"),
              ("WHAT IS REAL", "The disc, followed for 11.1 arcmin (the catalogue gives 13.5). The dust lane: across the centre two ridges of light 33 arcsec apart with a dip between them 34 times the noise, and the odd and the even frames each show it alone. The warm bulge either side of the lane"),
              ("NOT SEEN", "The lane's fine filaments, the last 1.2 arcmin of each end of the disc, and the halo: 7.5 minutes at f/10 stops at about 3 times the noise. No companion galaxies were identified"),
              ("COLOUR", "Shown only where the light can carry it, 3.3 percent of the picture: the stars and the galaxy's middle. The ends of the disc are grey on purpose. White stars come out slightly green: the camera's daylight white balance and matrix, with no star-colour calibration"),
              ("FINISH", "The camera's daylight white balance and colour matrix. Brightness smoothed 1.2 px, arcsinh stretch. Black at the 60th percentile, gamma 0.9, S-curve 0.2, saturation x 1.15. Faint parts smoothed (bilateral, 4 px), the dark sky without colour; about 0.9 percent of the picture is exactly black"),
              optics(step(stack("ngc891"), "plate solve")["focal_length_mm"]), CAMERA, MOUNT])

    # -- Messier 77, NGC 1068 (final/m77.json, m77/recipe.json) -----------------------------------------------------
    # picture 1200 x 800 at 0.776628058115 arcsec/px = 15.53 x 10.36 arcmin, cut at (932, 414) from the 2968 x 1978 stack
    # with nothing resampled; the camera's orientation: north 55.8 deg anticlockwise of up, east 145.8, not mirrored.
    # Distance about 47 million ly, not well known (published values run roughly 33 to 62).
    # Spans 4.7e7 x 15.53 x 2.909e-4 = 212,000 ly, "roughly 200,000". The bright disc is followed to 1.24 arcmin from the
    # nucleus, 2.49 arcmin across: 4.7e7 x 2.49 x 2.909e-4 = 34,000 ly, "roughly 35,000". The catalogue's 7.1 arcmin for
    # the whole galaxy is 7.1 / 2.49 = 2.9 times that, "about three times as wide" (97,000 ly).
    # Light left 47 million years ago (33 to 62), in the Eocene: the walking ancestors of whales (Pakicetus, Ambulocetus)
    # lived about 50 to 47 million years ago; at any distance in the range it is after the dinosaurs (66 million).
    # One pixel = 4.7e7 x 0.776628 x 4.848e-6 = 177 ly. Bar: 25,000 ly = 25000 / (4.7e7 x 2.909e-4) = 1.83 arcmin = 141 px.
    # The black hole: roughly ten million Suns, from the gas orbiting it. It is hidden from us by dust; what we see at the
    # centre is its light scattered and the gas it lights up, with the stars of the core, so the words say it "helps".
    # Labels, each looked at in a full-size crop:
    #   nucleus  the recipe's place in the picture (599.6, 399.9); brightest spot (599, 400). It sits on a short bright
    #            bar about 30 x 20 px, which the leader stops just short of
    #   a knot   on the oval of the inner arms, to the right of the nucleus: along the row through the nucleus the
    #            picture's brightness falls 187, 169, 167 at 36, 42, 48 px out, rises to 178 at 54 px and falls again;
    #            peak() finds it near (654, 397). The recipe: "the inner spiral arms as a brighter oval with knots"
    #   inner disc  the plain glow between the bar and the edge, up and to the left of the nucleus at (560, 361), 55 px
    #            out, where the picture reads about 148: inside the 96 px the recipe follows the disc to
    #   the star 1.45 arcmin from the nucleus: stack px (1512.8, 924.6) less the crop's corner = (580.8, 510.6); peak()
    #            finds it at (580, 510). Compact like the field stars (half-flux radius 2.9 px; the nucleus 5.9) and in
    #            the stack 3.3 times the nucleus's peak (9,400 against 2,840 DN in green). At 47 million ly (distance
    #            modulus 30.8) a star this bright would outshine the whole galaxy: it is a star of our own, in front.
    # Not named: the outer arms and the outer ring (not seen), NGC 1055 (off the frame).
    T["messier-77"] = dict(src="final/m77.png", scale=0.776628058115, north=55.8, title="Messier 77", sub="NGC 1068, a spiral galaxy in Cetus with an active centre",
        what="A spiral galaxy seen nearly face on, and one of the nearest and brightest galaxies with an active centre. Deep in its middle, gas is falling toward a black hole of roughly ten million Suns and blazing as it falls, which helps make the centre shine like a star. Galaxies like this are called Seyfert galaxies, after Carl Seyfert, who described them in 1943.",
        facts=[("DISTANCE", "about 47 million light-years (not well known: estimates run from 33 to 62 million)"), ("THIS PICTURE SPANS", "roughly 200,000 light-years; the bright disc shown is roughly 35,000 across"),
               ("THE LIGHT LEFT", "roughly 47 million years ago, when the ancestors of whales still walked on land"),
               ("HONEST NOTE", "this picture shows the bright heart of the galaxy only. Its faint outer arms and ring, about three times as wide, are not seen")],
        bar=(bar(25000, 4.7e7, 0.776628058115), "25,000 light-years"), frames="29 of 31 frames of 15 s",
        labels=lambda im: [(peak(im, (599.6, 399.9), 8, 1.5), "Nucleus", 8, -9, 1.6), ((560, 361), "Bright inner disc", -6, -10, 0.5),
                           (peak(im, (654, 397), 6, 1.5), "A knot in the inner arms", 9, 2, 0.8),
                           (peak(im, (580.8, 510.6), 8, 1.5), "A star in our own galaxy, in front", -7, 5, 1.4)],
        how_sub="7.25 minutes of light on one field, lower in the sky than the night's other pictures",
        tech=[("EXPOSURES", "29 x 15 s at ISO 3200: 7.25 minutes. The core did not clip: its brightest pixel in any frame is 24 percent of the ceiling. Nothing painted or repaired"),
              ("FRAMES", "31 taken, 29 kept. The first frame after the slew was dropped by rule; one was trailed as the field jumped across it. The 29 kept are within 2.4 percent of the run's star brightness"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 4.8 arcsec wide (half-flux): softer than the night's other pictures, because this one was lower in the sky"),
              ("FIELD", "15.5 x 10.4 arcmin: a 1200 x 800 crop round the nucleus from a stack of 38.4 x 25.6 arcmin, nothing resampled, as the camera saw it (north 56 degrees anticlockwise of up)"),
              ("WHEN", "13 October 2026, after midnight, over 20 minutes. About 50 degrees up"),
              ("FIELD ROTATION", "0.43 degrees over the run, because the polar axis is about 5 degrees off; corrected in registration (rotation and shift on 45 or 46 stars, 0.24 to 0.41 sensor px rms)"),
              ("DISPERSION", "The air is a prism this low: red sat 0.43 and blue 0.69 sensor px either side of green, measured on stars in ten frames. Taken out in the one resampling; under 0.05 px is left in the stack"),
              ("CALIBRATION", "No darks and no flat frames were taken. The night's flat, built from the open sky of the NGC 891 run, and 94 dust shadows it left, measured on this run's own sky and divided out. Hot pixels from the run itself (5,600 to 6,400 per colour plane)"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 4.8 to 5.2 times lower than one frame (5.4 expected from the weights)"),
              ("WHAT IS REAL", "The star-like nucleus on a short bright bar. The bright inner disc, 2.5 arcmin across: followed while its light is over 3 times the spread of blank sky, the same in the odd and the even frames. The inner arms as a brighter oval with knots"),
              ("NOT SEEN", "The faint outer arms and the outer ring, 2.2 to 3.6 arcmin from the nucleus: the light there measures zero or less. The sky within about 4 arcmin of the galaxy sits about 1 percent low, because the night's flat was fitted where NGC 891 hid the middle of the sensor. That is what hides the outer disc"),
              ("FINISH", "The camera's daylight white balance and colour matrix, no star-colour calibration. Colour only where the light is over 8 DN, the bright disc and the stars; the fainter edge is grey. Arcsinh stretch, black at the 78th percentile, gamma 0.9, S-curve 0.2, saturation x 1.15. The dark sky is set near black and smoothed (bilateral, 5 px), by choice: 8.6 percent of the picture is exactly black"),
              optics(stack("m77")["equipment"]["focal_length_mm_by_plate_solve"]), CAMERA, MOUNT])

    # -- NGC 1535, Cleopatra's Eye (final/ngc1535.json, ngc1535/recipe.json) ------------------------------------------
    # picture 720 x 480 at 0.777028306429 arcsec/px = 9.32 x 6.22 arcmin, one pixel per 2 x 2 colour cell, never enlarged;
    # north 35.777 deg clockwise of up (so -35.777 here), east 54.2 deg anticlockwise, not mirrored. Nebula's centre at
    # (358.9, 240.2). Distance roughly 6,000 ly, a round figure, not well known (estimates run from 5,000 to 7,500).
    # Spans 6000 x 9.32 x 2.909e-4 = 16.3 ly.
    # The bright disc: fitted radius 11.3 arcsec in green, so 22.5 arcsec across: 6000 x 22.5 x 4.848e-6 = 0.65 ly, "about
    # two thirds of a light-year". The shell: the light ends 28 to 34 arcsec from the centre, 56 to 68 arcsec across:
    # 6000 x 62 x 4.848e-6 = 1.8 ly (1.6 to 2.0), "nearly 2".
    # Light left 2026 - 6000 = about 4000 BC (3000 BC to 5500 BC over the range of distances): the first pyramid is about
    # 2650 BC, so "before the pyramids" holds over the whole range; writing begins about 3300 BC, so "probably before writing".
    # Bar: 2 ly = 2 / (6000 x 2.909e-4) = 1.146 arcmin = 68.8 arcsec = 88.5 px: about the width of the shell.
    # Labels, each looked at in a full-size crop. The picture's brightness along twelve spokes from the centre runs about
    # 150 at the centre, 90 at 12 px, 43 at 20 px, 30 at 24 px, 20 at 28 px, 10 at 32 px, 5 at 36 px, the same all round:
    #   inner disc and central star  the centre itself, (359, 240): the star is the bright core of the disc, not a separate
    #            point at this star size (the recipe: 233 DN at the centre against about 100 of disc around it)
    #   outer shell  24 px (19 arcsec) from the centre, inside the ring of 14 to 25 arcsec where the recipe proves the shell,
    #            down and to the left at (358.9 - 24 x 0.866, 240.2 + 24 x 0.5) = (338, 252). Not to the right: the small
    #            brighter spot the recipe could not identify sits there, near (380, 233), and nothing points at it.
    #            The leader runs to within 3 px so that it ends in the shell and not on the sky outside it.
    T["ngc-1535"] = dict(src="final/ngc1535.png", scale=0.777028306429, north=-35.777, title="NGC 1535", sub="Cleopatra's Eye, a planetary nebula in Eridanus",
        what="This is what a star like the Sun does at the end: it puffs its outer layers off into space, and the bare, hot core left behind makes them glow. The bright middle of the disc is that core, on its way to becoming a white dwarf; the faint shell round the disc is gas the star threw off earlier. William Herschel found it in 1785.",
        facts=[("DISTANCE", "roughly 6,000 light-years (not well known: estimates run from 5,000 to 7,500)"),
               ("THIS PICTURE SPANS", "16 light-years; the nebula with its faint shell is nearly 2 across, the bright disc about two thirds of one"),
               ("THE LIGHT LEFT", "roughly 6,000 years ago, before the pyramids and probably before writing"),
               ("HONEST NOTE", "the nebula glows in a blue-green from oxygen that is purer than any screen can show, so the screen's nearest colour stands in for it")],
        bar=(bar(2, 6000, 0.777028306429), "2 light-years"), frames="30 of 33 frames of 4 s",
        labels=lambda im: [((359, 240), "Inner disc and its central star", 5, -6), ((338, 252), "Faint outer shell", -6, 3.5, 0.3)],
        how_sub="two minutes of light, low in the sky: the softest picture of the night",
        tech=[("EXPOSURES", "30 x 4 s at ISO 1600: 120 seconds. Nothing clipped: the nebula peaks at 3 percent of the range in a 4 s frame"),
              ("FRAMES", "33 taken, 30 kept. One was taken while the mount was still re-centring after the telescope's computer was restarted mid-run; one had soft stars (6.55 arcsec against a limit of 6.5); one was trailed. The frames came in two runs either side of the restart, 17 and 13 kept, with the nebula in two different places on the sensor"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 5.8 arcsec wide (half-flux): the softest picture of the night, because it was the lowest"),
              ("FIELD", "9.3 x 6.2 arcmin: a 720 x 480 crop round the nebula, turned by quarter turns only (no resampling after the stack). North 36 degrees clockwise of up"),
              ("WHEN", "13 October 2026, after midnight, over 17 minutes. About 40 degrees up"),
              ("REGISTRATION", "Rotation and shift on 35 to 70 stars; the field turned 0.38 degrees. The air is a prism this low: red and blue star images sat 0.79 arcsec apart, measured on 22 stars and taken out in the one resampling (0.02 left). For the nebula's own light, which is not starlight, blue is still about 0.15 arcsec off"),
              ("CALIBRATION", "No darks and no flat frames were taken. Divided by the night's flat, built from the open sky of the NGC 891 run. This run's own sky is too faint in 4 s to check dust near the nebula; the odd and the even frames, each with frames of both runs, agree to 1 percent on the nebula. Hot pixels from the run itself (690 to 760 per colour plane)"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour, under 1.5 DN across it"),
              ("WHAT IS REAL", "The blue-green inner disc. The central star, as a star-wide bright core in the middle of it. The faint outer shell: in the ring 14 to 25 arcsec out the green light is 10.0 DN where the disc's own blur would leave 2.2, 73 times the noise, and the odd and the even frames each show it (55 and 65 times). The light ends 28 to 34 arcsec from the centre"),
              ("NOT SEEN", "Any structure inside the disc, or a sharp edge between disc and shell: with stars 5.8 arcsec wide the two run into each other. A small brighter spot in the shell about 17 arcsec out repeats in both halves and is not identified"),
              ("COLOUR", "The camera's daylight white balance and colour matrix, no saturation added. The nebula shines mostly in doubly ionised oxygen at 501 nm, a green-blue outside what a screen can show: the matrix gives it a negative red, which is shown as zero across the disc. That is the colour space, not the sensor"),
              ("FINISH", "Brightness smoothed 1 px, colour 3.5 px, arcsinh stretch. Black at the 60th percentile, S-curve 0.15. Dark sky smoothed (median 3 px, bilateral 4 px) but kept below the shell on purpose: the shell's outer edge is grainy at full size, which is the stack's own noise"),
              optics(stack("ngc1535")["plate_solution"]["focal_length_mm"]), CAMERA, MOUNT])

    # -- the Crab Nebula, M1 (final/m1.json, m1/recipe.json) ---------------------------------------------------------
    # picture 800 x 600 at 0.776489214015 arcsec/px = 10.35 x 7.77 arcmin, cut from the stack and not turned; the camera's
    # orientation: north 53.1 deg anticlockwise of up, east to the lower left, not mirrored. Distance about 6,500 ly.
    # The words follow the 8 October entry for the same object (that night's annotate.py; it was not on that night's page).
    # Spans 6500 x 10.35 x 2.909e-4 = 19.6 ly, "20". The glow runs into the sky at 7.0 x 4.4 arcmin:
    # 6500 x 7.0 x 2.909e-4 = 13.2 ly long and 6500 x 4.4 x 2.909e-4 = 8.3 ly wide (the catalogue's 6 x 4 arcmin: 11 x 8).
    # Light left 2026 - 6500 = 4474 BC, "around 4500 BC" (writing: about 3300 BC). The explosion was seen in 1054, so the
    # light of the explosion itself had left about 1054 - 6500 = 5450 BC.
    # Still spreading at about 1,500 km a second. The pulsar turns once in 33 thousandths of a second: 1 / 0.033 = 30 a second.
    # Bar: 5 ly = 5 / (6500 x 2.909e-4) = 2.64 arcmin = 204 px, as on 8 October.
    # Labels, each looked at in a full-size crop:
    #   the pulsar's place  catalogue px (399.6, 299.7). The recipe finds a compact source of 25 sigma 3.5 arcsec from it, at
    #            (395, 300): the pair of 16th magnitude stars at the nebula's centre, the pulsar and its neighbour, one
    #            blob at this star size. In the picture a small bright spot is there: peak() finds it at (393, 300), 239
    #            against 199 to 220 twelve px to either side. Named as blended, because which part is the pulsar cannot be shown
    #   a notch  in the outline at lower left (the east side): on a star-free, smoothed copy of the picture the contours at
    #            80 and 120 of 255 turn sharply inward round (338, 402), a dark bay about 40 px (30 arcsec) wide. The
    #            recipe: "lopsided, with notches in its outline", proven real at 11 to 44 arcsec (9.3 sigma)
    #   a star   at (456, 234), 75 px from the centre of the nebula's light, on the bright part: as sharp and as bright as
    #            the stars of the field (249 of 255). The nebula is in our own galaxy and so is the star: whether it is in
    #            front or behind is not known, so it is named only as not part of the nebula.
    # Not named: any filament (not seen as filaments).
    T["crab-nebula"] = dict(src="final/m1.png", scale=0.776489214015, north=53.1, title="The Crab Nebula", sub="Messier 1, the wreck of an exploded star in Taurus",
        what="What is left of a star that blew itself apart. Astronomers in China saw the explosion in 1054: a new star bright enough to see in daylight for three weeks. The cloud is still flying outward at about 1,500 km a second. At its centre is the collapsed core of the star, no bigger than a city, spinning about 30 times a second.",
        facts=[("DISTANCE", "about 6,500 light-years"), ("THIS PICTURE SPANS", "20 light-years; the nebula is about 13 long and 8 wide"), ("THE LIGHT LEFT", "around 4500 BC, before writing was invented"),
               ("HONEST NOTE", "the lumpy, lopsided shape is real: two separate halves of the frames show the same shape. The nebula's famous red threads are not seen, so it has one warm colour here")],
        bar=(bar(5, 6500, 0.776489214015), "5 light-years"), frames="37 of 41 frames of 15 s",
        labels=lambda im: [(peak(im, (395, 300), 6, 1.5), "The pulsar, blended with a star", 9, 1, 0.7), ((338, 402), "A notch in the outline", -8, 2.5, 0.5),
                           (peak(im, (456, 234), 6, 1.5), "A star, not part of the nebula", 6, -6.5, 1.2)],
        how_sub="9.25 minutes of light on one field, against one minute on 8 October",
        tech=[("EXPOSURES", "37 x 15 s at ISO 3200: 9.25 minutes"),
              ("FRAMES", "41 taken, 37 kept. The first after the slew was dropped by rule; two were smeared and one had wide stars. A few frames were slightly trailed by the unguided drive, every star stretched the same way: not out of focus. The stars dimmed 4 percent over the run; the frames are scaled and weighted for it"),
              ("SAMPLING", "0.776 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 4.8 arcsec wide (half-flux), round"),
              ("FIELD", "10.4 x 7.8 arcmin: an 800 x 600 crop round the catalogue place from a stack of 38.3 x 25.3 arcmin, nothing resampled, not turned (north 53 degrees anticlockwise of up)"),
              ("WHEN", "13 October 2026, after midnight, over 27 minutes. About 60 degrees up"),
              ("FIELD ROTATION", "0.65 degrees over the run, because the polar axis is about 5 degrees off; corrected in registration (rotation and shift on about 200 stars, 0.32 to 0.48 sensor px rms)"),
              ("CALIBRATION", "No darks and no flat frames were taken. The night's flat, built from the open sky of the NGC 891 run, and 133 dust shadows it left, measured on this run's own sky and divided out. The sky just round the nebula sits about 1 percent low, which trims the nebula's faintest edge a little. Hot pixels from the run itself"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 5.5 to 5.7 times lower than one frame (6.1 expected from the weights)"),
              ("WHAT IS REAL", "The oval glow, 44 times the scatter of blank sky: half its central brightness at 3.1 x 2.0 arcmin, into the sky by 7.0 x 4.4. And the structure inside it: the odd and the even halves of the frames, band-passed, agree inside the nebula at 9 to 16 sigma over blank sky, at scales from 3 to 44 arcsec. On 8 October the same tests gave 1.4 and 3.5"),
              ("NOT SEEN", "The red filaments as such: the red-excess test does not repeat between the halves (0.6, -0.1 and 0.9 sigma), and a stock camera passes little of their deep red. So the nebula is given one colour and no red web is drawn. The pulsar is not shown as a separate star: it and its 16th magnitude neighbour, about 5 arcsec apart, are one blob at this star size"),
              ("FINISH", "Warm white, red : green : blue 1.10 : 1 : 0.83 in the camera's daylight white balance, core and rim alike. The colour comes from a 32 px average, so the stars are shown white: a side effect, not their colour. Arcsinh stretch, black at the 60th percentile, S-curve 0.15, no saturation added. The dark sky is set near black and smoothed (median 5 px, bilateral 5 px), by choice: 2.8 percent of the picture is exactly black"),
              ("COMPARED", "With 8 October's picture of it: 37 frames against 4, 9.25 minutes against 1, noise per pixel 5.9 DN against 38 in green for about the same nebula, stars 4.8 arcsec and round against 5.6 and stretched, and a flat this time. That picture had star colours; this one does not"),
              optics(stack("m1")["equipment"]["focal_length_mm_by_plate_solve"]), CAMERA, MOUNT])

    # -- Messier 78, NGC 2068 (final/m78.json, m78/recipe.json) ------------------------------------------------------
    # picture 1320 x 990 at 0.777180691402 arcsec/px = 17.10 x 12.82 arcmin, cut at (700, 420) from the stack, not turned;
    # the camera's orientation: north 53.5 deg anticlockwise of up, east to the lower left, not mirrored.
    # Distance about 1,350 ly (the Orion cloud; the 3 October page gives the Orion Nebula 1,344).
    # Spans 1350 x 17.10 x 2.909e-4 = 6.7 ly, "nearly 7". The glow above the sky is 5.4 x 4.5 arcmin:
    # 1350 x 5.4 x 2.909e-4 = 2.1 ly by 1350 x 4.5 x 2.909e-4 = 1.8 ly, "about 2 across" (the catalogue's 8 x 6: 3.1 x 2.4).
    # The two stars are 50.6 arcsec apart: 1350 x 50.6 x 4.848e-6 = 0.33 ly.
    # Light left 2026 - 1350 = 676, "around the year 680" as on the 3 October page for Orion; the Maya's Classic age of
    # city building runs from about 250 to 900, so it holds for any distance near this one.
    # Bar: 1 ly = 1 / (1350 x 2.909e-4) = 2.55 arcmin = 197 px.
    # Labels, each looked at in a full-size crop:
    #   the two stars  the recipe's places (661.7, 489.3) and (598.5, 473.5); peak() finds them at (661, 489) and (598, 473).
    #            One set of words with a leader to each: both leaders end at (440, 560), in the sky to the left of
    #            the cloud, so in drawing units of 13.2 px they are (-11.97, 6.59) from the second star and (-16.74, 5.38)
    #            from the first. From below and the left, because a small orange star sits just above the second, at
    #            (605, 452), and a leader coming down from above would seem to name it; the first star's leader passes
    #            36 px under the second star
    #   the dark lane  on the recipe's strip from the stars' midpoint (630.1, 481.4) towards the north-west, which on the
    #            picture is the direction (-0.132, -0.991): north (-0.804, -0.594) x cos 314 + east (-0.594, 0.804) x sin 314.
    #            The picture's brightness along it: 204 at the midpoint, 41 at 80 px, 0 to 2 from 120 to 200 px, 27 at
    #            280 px. The lane is named at 162 px (2.1 arcmin, the recipe's minimum): (609, 321)
    #   the arc beyond the lane  the far bank at its brightest on the same strip, 280 px out: (593, 204), where the
    #            picture reads 22 to 27 against 0 in the lane: the edge of NGC 2067 (the recipe: 8 sigma, in both halves)
    #   NGC 2064  catalogue px (1212.6, 296.4): a faint patch there, 66 of 255 in the picture against 15 round it
    # Not named: NGC 2071 (outside this crop); the dust streak near (690, 780) (said in the rows, not pointed at).
    T["messier-78"] = dict(src="final/m78.png", scale=0.777180691402, north=53.5, title="Messier 78", sub="A cloud of dust in Orion, lit by the stars inside it",
        what="This cloud does not shine by itself. It is dust, lit by the young stars inside it the way fog glows round a street lamp, and it is bluer than its stars for the same reason the daytime sky is blue. The black band above it is more of the same dust, unlit. It is one of the brightest clouds of its kind in the sky, and part of the great cloud where Orion's stars are being born.",
        facts=[("DISTANCE", "about 1,350 light-years"), ("THIS PICTURE SPANS", "nearly 7 light-years; the glow shown is about 2 across"),
               ("THE LIGHT LEFT", "around the year 680, when the Maya were building their great cities"),
               ("HONEST NOTE", "the cloud measures bluer than the stars that light it, but that is only a cool white beside them, and no colour was added to make it blue. Its faint outer parts are not shown")],
        bar=(bar(1, 1350, 0.777180691402), "1 light-year"), frames="34 of 36 frames of 15 s",
        labels=lambda im: [(peak(im, (598.5, 473.5), 8, 1.5), "The two stars lighting the cloud", -11.97, 6.59, 1.4), (peak(im, (661.7, 489.3), 8, 1.5), "", -16.74, 5.38, 1.4),
                           ((609, 321), "A dark lane of dust", 9, -1, 0.4), ((593, 204), "The far bank of the lane, edge of NGC 2067", 5, -9, 0.5),
                           ((1212.6, 296.4), "NGC 2064", -5, 6, 2.2)],
        how_sub="8.5 minutes of light on one field; no frame trailed",
        tech=[("EXPOSURES", "34 x 15 s at ISO 3200: 8.5 minutes"),
              ("FRAMES", "36 taken, 34 kept. The first after the slew was dropped by rule, and the last, whose stars had widened to 6.6 arcsec. None trailed. In the last four frames the stars widened and dimmed together, which is what dew starting on the telescope's front plate does; thin cloud is the other reading. Until then the stars' brightness was steady within 5 percent"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 5.5 arcsec wide (half-flux) in the stack; 5.2 to 5.7 over most of the run"),
              ("FIELD", "17.1 x 12.8 arcmin: a 1320 x 990 crop from a stack of 38.6 x 25.4 arcmin, nothing resampled, not turned (north 54 degrees anticlockwise of up). NGC 2071, 14 arcmin away, is real in the full field and outside this crop"),
              ("WHEN", "13 October 2026, after midnight, over 23 minutes. About 45 degrees up"),
              ("REGISTRATION", "Rotation and shift on 22 or 23 stars (a field in a dark cloud has few), 0.33 to 0.59 sensor px rms; the field turned 0.54 degrees. The air spread red from blue by 0.57 arcsec: measured on the stars and taken out in the one resampling"),
              ("CALIBRATION", "No darks and no flat frames were taken. The night's flat, built from the open sky of the NGC 891 run, and 75 dust shadows it left, measured on this run's own sky and divided out. Hot pixels from the run itself"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 5.1 to 5.5 times lower than one frame (5.8 expected from the weights)"),
              ("WHAT IS REAL", "Each of these repeats in the odd and the even halves of the frames. The glow round the two stars, 20 times the scatter of blank sky. The dark lane to the north-west: its far bank stands above it at 8 sigma. The arc beyond the lane, the edge of NGC 2067. NGC 2064, small and faint, at 16 sigma. Above the sky the glow is 5.4 arcmin east to west by 4.5 north to south; the catalogue gives 8 x 6"),
              ("KNOWN FLAWS", "The sky under the nebula is probably a little too high (the dark lane reads slightly below zero), so the nebula's faint edge is trimmed. A short dark streak at the nebula's southern edge is a dust shadow that could not be measured there: it was left, not painted out. Some of the light within 20 to 40 arcsec of the two stars is the telescope's own spread of starlight"),
              ("COLOUR", "No saturation added. In the camera's daylight white balance the bright body is red : green : blue 0.98 : 1 : 1.01, a cool white; the two stars that light it are 0.83 and 0.63 in blue over green. So the nebula is bluer than the bluer of its stars, by 4.2 sigma, which is what scattering by dust does; against white it is neutral. No colour is shown in the faintest parts"),
              ("FINISH", "The camera's daylight white balance and colour matrix. Arcsinh stretch, black at the 70th percentile, S-curve 0.15. The dark sky is set near black and smoothed (median 5 px, bilateral 5 px), by choice: 14 percent of the picture is exactly black, and the faintest edge, the arc and NGC 2064 are smoothed with the sky"),
              optics(stack("m78")["equipment"]["focal_length_mm_by_plate_solve"]), CAMERA, MOUNT])

    # -- Hubble's Variable Nebula, NGC 2261 (final/ngc2261.json, ngc2261/recipe.json) --------------------------------
    # picture 800 x 600 at 0.776633617294 arcsec/px = 10.36 x 7.77 arcmin, cut at (1106, 666) from the stack, not turned;
    # the camera's orientation: north 52.9 deg anticlockwise of up, east to the lower left, not mirrored.
    # Distance about 2,500 ly. Spans 2500 x 10.36 x 2.909e-4 = 7.5 ly.
    # The fan is 91 arcsec long from the star and 83 across: 2500 x 91 x 4.848e-6 = 1.10 ly long, 2500 x 83 x 4.848e-6 =
    # 1.01 ly wide, "about a light-year" (the catalogue's 2 arcmin would be 1.45 ly).
    # Light left 2026 - 2500 = 474 BC, "around 470 BC", as the 8 October page says of the Little Dumbbell at the same distance
    # (Socrates born c. 470 BC).
    # Bar: 1 ly = 1 / (2500 x 2.909e-4) = 1.375 arcmin = 82.5 arcsec = 106 px: about the length of the fan shown.
    # Labels, each looked at in a full-size crop:
    #   R Monocerotis  the recipe's place in the picture (446, 336), 1.3 arcsec from the catalogue place; peak() finds the
    #            brightest point there, at the fan's southern tip
    #   the fan  a point on its axis 55 arcsec from the star. The axis is at position angle 356 deg: on the picture
    #            north (-0.798, -0.603) x cos 356 + east (-0.603, 0.798) x sin 356 = (-0.754, -0.657), so 55 arcsec is
    #            70.8 px: (446 - 53.4, 336 - 46.5) = (393, 290), inside the fan (the picture reads about 100 to 150 there)
    # Not named: the darker channel along the axis. Across the fan 36 to 41 arcsec out the picture reads 172, 162, 165,
    # 181, 189: a dip of 10 to 25 in 255, real in the stack but not something the eye picks out at this size.
    # Nor the second bright knot 15 arcsec north-east of the star: in the picture it runs into the star's own glow.
    T["hubbles-variable-nebula"] = dict(src="final/ngc2261.png", scale=0.776633617294, north=52.9, title="Hubble's Variable Nebula", sub="NGC 2261, a fan of dust lit by the star R Monocerotis",
        what="A fan of dust lit from its tip by a young star, like a torch beam in fog. It changes: clouds of dust close to the star cast shadows that sweep up the fan over weeks and months, so no two pictures of it taken a season apart are the same. Edwin Hubble studied it for years, and in January 1949 he made it the first thing photographed with the 200 inch telescope on Palomar.",
        facts=[("DISTANCE", "about 2,500 light-years"), ("THIS PICTURE SPANS", "7.5 light-years; the fan shown is about one light-year long"),
               ("THE LIGHT LEFT", "around 470 BC, about when Socrates was born"),
               ("HONEST NOTE", "a soft picture: the stars came out wider than earlier in the night and thin cloud took the last frames, so the moving shadows are too fine to see here. The pale green tint is the camera's, not the nebula's")],
        bar=(bar(1, 2500, 0.776633617294), "1 light-year"), frames="25 of 32 frames of 15 s; thin cloud took the last six",
        labels=lambda im: [(peak(im, (446, 336), 6, 1.5), "R Monocerotis, the star that lights it", -4, 7, 1.2), ((393, 290), "The fan, dust lit by the star", 7, -7, 0.5)],
        how_sub="6.25 minutes of light on a soft night; thin cloud took the last six frames",
        tech=[("EXPOSURES", "25 x 15 s at ISO 3200: 6.25 minutes"),
              ("FRAMES", "32 taken, 25 kept. The first after the slew was dropped by rule. The last six were lost to thin cloud: the stars fell to about half their brightness while staying sharp, under a brighter sky, and were coming back within minutes, which is cloud and not dew. None trailed"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 6.3 arcsec wide (half-flux) in the stack, against about 5 earlier in the night: the whole run is soft. Nothing was sharpened"),
              ("FIELD", "10.4 x 7.8 arcmin: an 800 x 600 crop from a stack of 38.7 x 25.5 arcmin, nothing resampled, not turned (north 53 degrees anticlockwise of up)"),
              ("WHEN", "13 October 2026, after midnight, over 17 minutes. About 50 degrees up"),
              ("REGISTRATION", "Rotation and shift on about 150 stars, 0.40 to 0.64 px rms; the field turned 0.39 degrees. The air spread red from blue by about half an arcsecond: measured on the stars and taken out in the one resampling"),
              ("CALIBRATION", "No darks and no flat frames were taken. The night's flat, built from the open sky of the NGC 891 run, and 126 dust shadows it left, measured on this run's own sky and divided out. Nothing could be judged under the fan itself, and nothing there was touched. Hot pixels from the run itself"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 4.5 to 4.8 times lower than one frame (5.0 expected from the weights)"),
              ("WHAT IS REAL", "Each of these repeats in the odd and the even halves of the frames. The comet-shaped fan, 64 times the scatter of blank sky: 91 arcsec long from the star and 83 across at its widest. The star at its southern tip: a bright point in the brightest part of its own nebula, not a clean star image. A second bright knot 15 arcsec north-east of the star. Brighter edges, with a darker channel along the axis 23 to 41 arcsec out"),
              ("NOT SEEN", "The faint northern end of the fan, out to the catalogue's 2 arcmin, and the fine filaments and shadows that make it variable: the stars are 6.3 arcsec wide. The fan's outer edge is grainy and smoothed by the finish, so texture there is not detail"),
              ("COLOUR", "No saturation added. The fan measures near white: red : green 1.00 and blue : green 0.92 in the camera's daylight white balance. The camera's own colour matrix turns that into a pale cream-green: the tint is the rendering of a near-white measure, not a claim about the nebula"),
              ("FINISH", "Arcsinh stretch; colour from an 8 px average, and only where there is signal. Black at the 65th percentile, S-curve 0.15. The dark sky is set near black and smoothed (median 5 px, bilateral 5 px): 5.2 percent of the picture is exactly black"),
              optics(stack("ngc2261")["equipment"]["focal_length_mm_by_plate_solve"]), CAMERA, MOUNT])

    # -- NGC 2392 (final/ngc2392.json, ngc2392/recipe.json) -----------------------------------------------------------
    # A companion to NGC 1535 above: the same kind of object, taken the same way, and worded to be read beside it.
    # picture 720 x 480 at 0.776811834468 arcsec/px = 9.32 x 6.21 arcmin, one pixel per 2 x 2 colour cell, never enlarged;
    # north 38.025 deg clockwise of up (so -38.025 here), east 52 deg anticlockwise, not mirrored. Nebula's centre at
    # (358.6, 240.0). Distance roughly 6,500 ly, not well known (estimates run from about 3,000 to 7,000).
    # Spans 6500 x 9.32 x 2.909e-4 = 17.6 ly, "about 18".
    # The inner shell: a shoulder of light from 4 to 10 arcsec out (fitted radius 9.7), so about 19 arcsec across:
    # 6500 x 19 x 4.848e-6 = 0.60 ly. The outer disc: the light ends 28 to 34 arcsec from the centre, 56 to 68 across:
    # 6500 x 62 x 4.848e-6 = 1.95 ly (1.8 to 2.1), "about 2".
    # Light left 2026 - 6500 = 4474 BC, "roughly 6,500 years ago"; writing begins about 3300 BC, so before writing if the
    # distance is right (at 3,000 ly it would be 1000 BC, which is why the words say "if").
    # Bar: 2 ly = 2 / (6500 x 2.909e-4) = 1.058 arcmin = 63.5 arcsec = 81.7 px: about the width of the outer disc.
    # Labels, each looked at in a full-size crop. The picture's brightness along eight spokes from the centre runs about
    # 159 at the centre, 133 at 4 px, 97 at 8 px, 77 at 12 px, 57 at 16 px, 45 at 20 px, 37 at 24 px, 28 at 28 px,
    # 18 at 32 px, 9 at 36 px:
    #   central star  the centre, (359, 240): a sharp point, brighter than everything round it
    #   inner shell   9 px (7 arcsec) from the centre, inside the recipe's shoulder of 4 to 10 arcsec, down and to the
    #                 right: (358.6 + 9 x 0.707, 240 + 9 x 0.707) = (365, 246)
    #   outer disc    25 px (19 arcsec) from the centre, inside the ring of 14 to 25 arcsec where the recipe proves it,
    #                 to the left and a little down: (358.6 - 25 x 0.940, 240 + 25 x 0.342) = (335, 249)
    #   the bright star 1.7 arcmin north: 102 arcsec = 131 px along north (0.616, -0.788) = (439, 137); peak() finds it at
    #                 (433, 135). An 8th magnitude field star by the recipe, its core at full scale in green. The nebula
    #                 is in our own galaxy and so is the star, so it is named only as not part of the nebula.
    # Nothing is said of which side of the outer disc is brighter: the stars of this stack are a little lopsided.
    T["ngc-2392"] = dict(src="final/ngc2392.png", scale=0.776811834468, north=-38.025, title="NGC 2392", sub="A planetary nebula in Gemini",
        what="The same kind of object as tonight's NGC 1535, taken the same way. The star at the centre was once much like the Sun. It has thrown off its outer layers twice: the faint outer disc first, and the bright inner shell after it. What is left of the star is the hot point in the middle, which makes both of them glow. William Herschel found it in 1787.",
        facts=[("DISTANCE", "roughly 6,500 light-years (not well known: estimates run from 3,000 to 7,000)"),
               ("THIS PICTURE SPANS", "about 18 light-years; the outer disc is about 2 across, the inner shell a little over half of one"),
               ("THE LIGHT LEFT", "roughly 6,500 years ago: if that distance is right, before writing was invented"),
               ("HONEST NOTE", "cloud was thickening as this was taken, so it holds little more than a minute of light. And as with NGC 1535, the nebula's blue-green is purer than any screen can show")],
        bar=(bar(2, 6500, 0.776811834468), "2 light-years"), frames="21 of 32 frames of 4 s; cloud took the last ten",
        labels=lambda im: [((359, 240), "Central star", -6, -6.5, 0.4), ((365, 246), "Inner shell", 6, 5, 0.3), ((335, 249), "Fainter outer disc", -6, 4, 0.3),
                           (peak(im, (439, 137), 15, 1.2), "A star, not part of the nebula", 4, -4, 1.3)],
        how_sub="84 seconds of light, taken the same way as NGC 1535; cloud took the last ten frames",
        tech=[("EXPOSURES", "21 x 4 s at ISO 1600: 84 seconds. Nothing clipped: the nebula peaks at 8 percent of the range in a 4 s frame"),
              ("FRAMES", "32 taken, 21 kept. The first after the slew was dropped by rule; the last ten were lost to cloud, when the stars fell below half their brightness. None trailed. Cloud thickened through the run, so the later frames kept are scaled up and weighted down: the stack is worth about 15 clear frames, a minute of light"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged, as for NGC 1535. Stars 5.0 arcsec wide (half-flux)"),
              ("FIELD", "9.3 x 6.2 arcmin: a 720 x 480 crop round the nebula, turned by quarter turns only (no resampling after the stack). North 38 degrees clockwise of up"),
              ("WHEN", "13 October 2026, after midnight, over 10 minutes. About 50 degrees up"),
              ("REGISTRATION", "Rotation and shift on 81 to 156 stars, 0.8 to 1.1 px rms; the field turned 0.23 degrees over the frames used. The air spread red from blue by 0.48 arcsec: measured on 62 stars and taken out in the one resampling"),
              ("CALIBRATION", "No darks and no flat frames were taken. Divided by the night's flat, built from the open sky of the NGC 891 run. This run's own sky is too faint in 4 s to check the flat's dust, and the nebula sat on the same pixels throughout, so a shadow there would not average out. Hot pixels from the run itself (580 to 620 per colour plane)"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well"),
              ("WHAT IS REAL", "The central star, a clear star-like point, far stronger than in NGC 1535: 716 DN at the centre against 136 at 4.7 arcsec out. The inner shell, a blue-green shoulder of light from about 4 to 10 arcsec out. The fainter outer disc: in the ring 14 to 25 arcsec out the green light is 17.3 DN where spilled inner light would leave 0.9, 136 times the noise, and the odd and the even frames each show it (95 and 112 times). The light ends 28 to 34 arcsec from the centre"),
              ("NOT SEEN", "A dark gap between the star and the inner shell, the shell's rim as a ring, knots or filaments: with stars 5.0 arcsec wide the star's own image reaches the shell. The star images in this stack are slightly lopsided, so no claim is made about the nebula's shape"),
              ("COLOUR", "The camera's daylight white balance and colour matrix, no saturation added. As with NGC 1535, the green-blue of doubly ionised oxygen at 501 nm lies outside what a screen can show: the matrix gives it a negative red, shown as zero across the outer disc. The stars read slightly green-yellow, as in tonight's other pictures: that is the camera, not the stars"),
              ("FINISH", "Brightness smoothed 1.5 px (NGC 1535: 1.0), colour 3.5 px, arcsinh stretch. Black at the 60th percentile, S-curve 0.15. Dark sky smoothed (median 3 px, bilateral 4 px). The 8th magnitude star north of the nebula is five times brighter than the nebula's centre: its core is at full scale in green for a few pixels"),
              optics(stack("ngc2392")["plate_solution"]["focal_length_mm"]), CAMERA, MOUNT])

    # -- NGC 2419 (final/ngc2419.json, ngc2419/recipe.json) -----------------------------------------------------------
    # picture 1200 x 800 at 0.776554075574 arcsec/px = 15.53 x 10.35 arcmin, cut at (1158, 433) from the stack, not turned;
    # the camera's orientation: north 52 deg anticlockwise of up, east to the lower left, not mirrored.
    # Distance about 300,000 ly from us (270,000 to 300,000 published).
    # Spans 3.0e5 x 15.53 x 2.909e-4 = 1,355 ly, "about 1,400". The haze is 2.1 arcmin across above the stack's zero and
    # 2.5 against the sky just round it: 3.0e5 x 2.1 x 2.909e-4 = 183 ly and 3.0e5 x 2.5 x 2.909e-4 = 218 ly, "about 200"
    # (the catalogue's 4 to 6 arcmin: 350 to 520 ly, so less than half its full width is shown).
    # One pixel = 3.0e5 x 0.776554 x 4.848e-6 = 1.13 ly.
    # Light left about 300,000 years ago: the oldest fossils of our own species are about 300,000 years old.
    # The Large Magellanic Cloud is about 163,000 ly away: 300,000 / 163,000 = 1.84, "nearly twice as far".
    # The two bright stars are of magnitude 7 and 8 (the recipe); their distances are not in the recipe. Stars that bright
    # are typically a hundred to several hundred ly away: 300,000 / 300 = 1,000, so "hundreds or thousands of times nearer".
    # Bar: 200 ly = 200 / (3.0e5 x 2.909e-4) = 2.29 arcmin = 177 px: about the width of the haze shown.
    # Labels, each looked at in a full-size crop:
    #   the cluster  catalogue px (377.9, 583.4); a smoothed, star-free copy of the picture peaks at (381, 586) and reads
    #            135 at the centre, 93 at 30 px, 52 at 50 px, 32 at 70 px, 3 at 90 px. The leader ends at the haze's
    #            lower left edge, 59 px from the centre: (378 - 42, 583 + 42) = (336, 625)
    #   the two bright stars  the recipe's places (578.4, 353.1) and (822.1, 117.0): both are flat white discs (they clip
    #            in every frame), so the recipe's centres are used and not peak(), which would land on a disc's rim.
    #            One set of words with a leader to each: both leaders end at (735, 335), so in drawing units of 12 px
    #            they are (13.05, -1.51) from the nearer star and (-7.26, 18.17) from the farther. No catalogue name is
    #            printed: the recipe's names are inferred from position.
    T["ngc-2419"] = dict(src="final/ngc2419.png", scale=0.776554075574, north=52.0, title="NGC 2419", sub="A globular cluster in Lynx, at the far edge of our galaxy",
        what="A ball of hundreds of thousands of ancient stars, nearly twice as far away as the Large Magellanic Cloud, the Milky Way's big companion galaxy. It is so far out that it was once thought to be adrift between galaxies, and was called the Intergalactic Wanderer; in fact it orbits the Milky Way. The two bright stars beside it are in our own neighbourhood, hundreds or thousands of times nearer.",
        facts=[("DISTANCE", "about 300,000 light-years"), ("THIS PICTURE SPANS", "about 1,400 light-years; the haze shown is about 200 across, and one pixel is more than a light-year"),
               ("THE LIGHT LEFT", "about 300,000 years ago, around when our own species first appears in the fossil record"),
               ("HONEST NOTE", "a short picture, partly through cloud: only the bright middle of the cluster shows, less than half its full width. Its speckle is real, but no single star can be picked out")],
        bar=(bar(200, 3.0e5, 0.776554075574), "200 light-years"), frames="17 of 29 frames of 15 s; cloud took the other twelve",
        labels=lambda im: [((336, 625), "NGC 2419, the cluster", -5, 5, 0.4),
                           ((578.4, 353.1), "Two stars in our own neighbourhood, far in front", 13.05, -1.51, 2.6), ((822.1, 117.0), "", -7.26, 18.17, 2.6)],
        how_sub="4.25 minutes of light, between patches of cloud",
        tech=[("EXPOSURES", "17 x 15 s at ISO 3200: 4.25 minutes"),
              ("FRAMES", "29 taken, 17 kept. All 12 dropped were lost to cloud: the run began and ended under thin cloud in patches, the stars dimmer under a brighter sky, with 13 clear frames in a row in the middle. Four thin frames, at 80 to 90 percent, are used, scaled up and weighted down"),
              ("SAMPLING", "0.777 arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars 5.0 arcsec wide (half-flux)"),
              ("FIELD", "15.5 x 10.4 arcmin: a 1200 x 800 crop from a stack of 38.7 x 25.6 arcmin, nothing resampled, not turned (north 52 degrees anticlockwise of up)"),
              ("WHEN", "13 October 2026, after midnight, over 15 minutes. About 60 degrees up"),
              ("REGISTRATION", "Rotation and shift on 84 to 86 stars, 0.31 to 0.42 sensor px rms; the field turned 0.40 degrees. The air spread red from blue by 0.32 arcsec: measured on the stars and taken out in the one resampling"),
              ("CALIBRATION", "No darks and no flat frames were taken. The night's flat, built from the open sky of the NGC 891 run, and 53 dust shadows it left, measured on this run's own sky and divided out; nothing within 3 arcmin of the cluster was judged or changed. Hot pixels from the run itself"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour is subtracted as well. Noise 3.7 to 3.8 times lower than one frame (4.1 expected from the weights)"),
              ("WHAT IS REAL", "A round haze, brightest at the centre (38 percent above the sky there) and falling to half at 22 arcsec. It stands above the sky over 2.1 arcmin, in the stack and in the odd and the even halves of the frames each alone; 2.5 against the sky just round it. The haze is grainy and the grain is real: of 36 points in it, 21 repeat in both halves, where chance would give about 2"),
              ("NOT CLAIMED", "Any single star of the cluster: each point is a bright giant, a blend of a few, or a star in front. Nor the catalogue's 4 to 6 arcmin: the outer part is too faint for 4.25 minutes. The sky round the cluster reads slightly low, so the width given is a lower limit"),
              ("COLOUR", "No saturation added. The haze is a faintly warm white, red : green : blue 1.10 : 1 : 0.81 in the camera's daylight white balance: the same, within the errors, as the field's stars. The two bright stars clip in every frame: they are shown white and were not repaired, and the glow round each is the telescope's own spread of their light"),
              ("FINISH", "The camera's daylight white balance and colour matrix. Arcsinh stretch, black at the 75th percentile, S-curve 0.15. The dark sky is set near black and smoothed (median 3 px, bilateral 4 px), by choice: 8.3 percent of the picture is exactly black, and the haze's outermost ring fades into it"),
              optics(stack("ngc2419")["equipment"]["focal_length_mm_by_plate_solve"]), CAMERA, MOUNT])
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
CARD_TEXT = {"ngc-2419": "top"}   # the cluster sits at the lower left, under where the words would go; the top is empty sky       # where a link preview's words go when the foot of the picture is the busy part

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
