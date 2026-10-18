"""The share set for the night of 17 October 2026: three JPEGs for every finished picture.

  <name>.jpg            the picture as it is, nothing on it
  <name>-annotated.jpg  names, a scale bar and north on the picture; underneath, what it is, how far, how big
  <name>-how.jpg        for photographers: exposures, frames kept and lost, sampling, calibration, stacking and finishing

The caption band is added underneath; it never covers the picture. All drawing is plain text and lines.
JPEGs are full resolution, quality 93, no chroma subsampling, no metadata.

Usage: annotate.py [name ...]           (no names: all) -> share/
       annotate.py --site <folder>      the same pictures and words for the website: <folder>/images and <folder>/objects.json

ADDING A PICTURE: add one entry to targets(), keyed by its website slug (the slug in observations/2026-10-17/plan.json),
and run both lines again. The page shows the pictures in the order of the entries. Nothing else in this file changes.

Copied from hack/stacks/2026-10-12/annotate.py (itself from the 8 October 2026 script, itself from
.claude/skills/annotate-pictures/tools/annotate.py) with tonight's targets() table. The drawing code is unchanged but for the last two changes below.
Five changes for tonight:
  - each stacking agent leaves its finished work in its own folder: <folder>/final/<file>.png the picture,
    <folder>/final/<file>.json its finish recipe, <folder>/final/recipe.json the stack's recipe, so an entry reads all
    three from there (finish(), stack());
  - each entry is the stacking agent's own (its step14_annotate.py, whose labels, facts and words were looked at in a
    full-size crop and are on the card Brad has seen), keyed by the website slug; only its photographers' rows are
    rewritten here, from the recipe;
  - calibration is three rows: Darks, Flats, and Calibration for the rest (tonight's dust). The site builder files all
    three under acquisition and the Copy for Reddit text lists them; a label the builder does not know is processing.
  - an entry may carry its own credit line for its share cards (gear): the Triangulum Galaxy is from two nights;
  - an entry may draw its own labels, scale bar and north (draw): Saturn's card is the stacking agent's own layout, and
    its labels are drawn as that card draws them, on the picture's own pixels.
Small pictures (a 640 px crop at the sensor's own scale, never enlarged) are handled as on 8 October: the drawing unit
has a floor (UMIN) and the share versions sit at their own size in the middle of a band wide enough for the words.
Every number in targets() is copied from that picture's recipe files; the arithmetic for the facts is beside them.

Nothing here gives a clock time, and never the measured altitude: together with the object they would place the
telescope. The words carry the part of the night ("the evening") and "nearly overhead" or an altitude rounded to
the nearest ten degrees, nothing finer.
"""
import json, math, os, re, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); os.makedirs("share", exist_ok=True)   # hack/stacks/2026-10-17/: reads <folder>/final/; writes share/
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
def font(size, weight="regular"): return ImageFont.truetype(AVENIR, max(8, int(round(size))), index={"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight])
INK, SOFT, DIM, BAND, RULE = (244, 244, 240), (198, 198, 194), (140, 140, 138), (10, 10, 12), (62, 62, 64)
# f/10.3: the plate solves tonight give 2,082 to 2,083 mm on 203 mm of aperture (M27: 2,083.4 the reference frame, 2,082.4 the stack); each picture's own focal length is in its rows
GEAR = "© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  night of 17 October 2026"
TRUE = "Stacked from the camera's RAW frames. Nothing generated."
CAMERA = ("CAMERA", "Sony a6000, stock, at prime focus: APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW")
# the frames' sidecars: "polar axis 10.6 deg from the pole", model of 4 plate-solved photos, rms 0.77 arcmin
MOUNT = ("MOUNT", "Sky-Watcher EQ6-R, unguided, not dithered on this target. Set down about 10 degrees off the pole; aligned from four plate-solved photos (under 1 arcminute), both axes driven from that model")
MADE = "Capture and mount: Observatory (Elixir on a Raspberry Pi 3).  Stacking: numpy, OpenCV, rawpy.  Plate solving: astrometry.net.  " + TRUE
STACK = "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered on stars with rotation, proper coaddition (Zackay and Ofek: each frame weighted by its own measured blur and noise)"
UMIN = 10.0     # px. The drawing unit is a hundredth of the picture's width, but never under this: names on a 600 px picture would be set at 9 px

def finish(folder, name): return json.load(open("%s/final/%s.json" % (folder, name)))   # the finish recipe of <folder>/final/<name>.png
def stack(folder): return json.load(open("%s/final/recipe.json" % folder))               # the stack's own recipe
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

    # -- the Dumbbell Nebula, Messier 27 (m27/final/m27.png, m27/final/m27.json, m27/final/recipe.json) ----------------
    # The entry is m27/step14_annotate.py's: title, sub, what, facts, bar, labels and how_sub word for word, as on
    # m27/share/m27-annotated.jpg. Its notes:
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
    # The photographers' rows, from m27/final/recipe.json (summary and steps):
    #   frames: 70 in the run, 66 used; dropped: the first after the slew (by rule), three smeared (common ellipticity
    #           0.20 to 0.21, limit 0.20); transparency 0.980 to 1.009: no cloud
    #   brightest nebula pixel in a frame: 0.124 of the ceiling (step 10, core): nothing clipped
    #   stars 4.47 arcsec half-flux in the stack, 117 stars (step 10, star_size)
    #   registration: rotation -0.004 to +0.047 deg; the shift at centre went from (+257, +160) to (-235, -119) sensor px:
    #           566 x 0.388 arcsec = 220 arcsec = 3.7 arcmin; red and blue -0.28/+0.05 and +0.32/-0.19 sensor px off green
    #   hot pixels 19,996 to 21,490 per plane (step 1); darks none taken (summary, darks)
    #   flat: the 13 October hybrid flat, chosen over the 13 October twilight flat and an M33 flat on this run's own sky:
    #           green 0.57 percent left after a plane, against 0.80 (M33) and 1.98 (twilight) (step 7a, said)
    #   dust: 11 shadows measured on this run's sky in the odd and the even frames alone, 0.73 percent of the sensor; the
    #           crescent 12.7 / 12.6 / 1.7 percent (before any flat / after the 13 October flat / after tonight's own),
    #           new since 13 October; spot a 5.5 / 0.5 / 0.1, spot b 9.0 / 0.2 / 0.2 (summary, dust)
    #   noise 7.45 to 7.75 times lower than one frame, 8.12 expected from the weights (summary, noise)
    #   ears: 3 to 4 arcmin out, 12 / 12 and 11 / 11 sigma along the long axis (odd / even), none beyond 4 arcmin (step 12)
    #   star colours: Gaia DR3, 93 stars, red x 1.013, blue x 1.153 (step 9b)
    #   finish: black at the 50th percentile, S-curve 0.15, bilateral 4 px, saturation x 1.2, 3.99 percent exactly black
    #   altitude: 60 to 66 degrees by the sidecars, "about 60 degrees up"; the run lasted 36 minutes, in the evening
    rec = stack("m27"); fin = finish("m27", "m27"); s9 = step(rec, "9 plate solve of the stack and the crop")["numbers"]
    S = s9["pixscale_arcsec"]; FL = s9["focal_length_mm"]; NORTH = s9["north_angle_from_up_deg_clockwise"]
    s10 = step(rec, "10 deliver: TIF, stretch, sky plane in the picture only, measures")["numbers"]; gaia = step(rec, "9b star colours (Gaia DR3)")["numbers"]
    D = 1300.0
    T["dumbbell-nebula"] = dict(src="m27/final/m27.png", scale=S, north=-NORTH, title="The Dumbbell Nebula", sub="Messier 27, a planetary nebula in Vulpecula",
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
        tech=[("EXPOSURES", "66 x 15 s at ISO 3200: 16.5 minutes. Nothing clipped on the nebula: its brightest pixel reached %.0f percent of the sensor's range in a frame" % (100 * s10["core"]["highest_fraction_of_the_ceiling"])),
              ("FRAMES", "70 taken, 66 kept. The first after the slew was dropped by rule; three were smeared (every star stretched the same way, ellipticity 0.20 to 0.21). No cloud: every frame's stars within 2 percent of the run's typical brightness"),
              ("SAMPLING", "%.3f arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars %.2f arcsec wide (half-flux, %d stars) in the stack, %.2f in one frame" % (S, s10["star_size"]["hfd_stack_arcsec"], s10["star_size"]["stars"], s10["star_size"]["hfd_single_arcsec"])),
              ("FIELD", "15.5 x 12.9 arcmin: a 1200 x 1000 crop from a stack of 36.9 x 24.3 arcmin, nothing resampled after the stack, not turned (north 116 degrees clockwise of up)"),
              ("WHEN", "The evening of 17 October 2026, over 36 minutes. About 60 degrees up"),
              ("REGISTRATION", "Rotation and shift on the stars; the field drifted 3.7 arcmin across the sensor and turned 0.05 degrees. Red and blue star images sat 0.3 sensor px off green (the air's prism): measured and taken out in the one resampling"),
              ("DARKS", "None taken tonight. Hot pixels found from the run itself, about 20,000 to 21,500 per colour plane, and repaired by the 3 x 3 median of their colour plane"),
              ("FLATS", "No flat frames tonight. The hybrid flat of 13 October: its large scale from that night's open sky, its dust from the 13 October twilight frames. Picked over two others on this run's own sky: it leaves 0.57 percent in green after a plane, against 0.80 and 1.98 for the others"),
              ("CALIBRATION", "Dust that moved since 13 October, measured on this run's own sky, seen in the odd and the even frames alone, and divided out: 11 shadows, 0.73 percent of the sensor. Among them a new crescent 12.7 percent deep, which the 13 October flat does not have, left at 1.7 percent"),
              ("STACKING", STACK + ". One sky constant per colour per frame; in the picture only, a sky plane per colour, about 3 DN across it. Noise 7.5 to 7.8 times lower than one frame (8.1 expected from the weights). The old sigma-clipped mean was made beside it as a control"),
              ("WHAT IS REAL", "The bright body and the faint outer lobes that fill it out to its apple shape: 3 to 4 arcmin from the star they stand 11 to 12 times above blank sky in the odd and the even frames each alone. The nebula is followed 8.1 arcmin across"),
              ("NOT SEEN", "The faint outer halo of deep pictures: beyond 4 arcmin from the star nothing passes the half-stack test. Nor the fine knots inside the nebula: the stars are 4.5 arcsec wide"),
              ("COLOUR", "The camera's colour matrix with its white balance set by the colours of %d Gaia stars in the field (red x %.2f, blue x %.2f). The oxygen glow is outside what a screen shows; the faint lobes are grey, because their colour there is set by sky and flat, not the nebula" % (gaia["used"], gaia["factors"]["R"], gaia["factors"]["B"])),
              ("FINISH", "Star colours from Gaia, the camera's colour matrix. Arcsinh stretch; black at the 50th percentile, S-curve 0.15, saturation x 1.2; the dark sky smoothed (bilateral 4 px) and set near black, by choice: %.1f percent of the picture is exactly black" % fin["clipped_to_black_pct"]),
              optics(FL), CAMERA, MOUNT])

    # -- the Triangulum Galaxy, Messier 33 (m33/final/m33.png, m33/final/m33.json, m33/final/recipe.json) --------------
    # The entry is m33/step12_annotate.py's: title, sub, what, facts, bar, label words and how_sub word for word, as on
    # m33/share/m33-annotated.jpg, whose credit line names both nights (gear). Its notes:
    # picture 2804 x 1652 at 0.7764 arcsec/px = 36.3 x 21.4 arcmin, not turned: north 64.4 deg anticlockwise of up.
    # Distance 2.73 million ly (840 kpc; published values 2.6 to 3.0 million), a soft number.
    # Spans 2.73e6 x 36.3 x 2.909e-4 = 28,800 ly ("about 29,000"). One pixel: 2.73e6 x 0.7764 x 4.848e-6 = 10.3 ly.
    # NGC 604: about 1,500 ly across (published), 40 times the Orion Nebula's span.
    # Light left 2.7 million years ago: about when the first stone tools were made in East Africa (2.6 million years).
    # Bar: 5,000 ly = 5000 / (2.73e6 x 2.909e-4) = 6.30 arcmin = 487 px.
    # Labels: catalogue places (J2000, as in hack/stacks/2026-10-12/m33/step8_solve.py) through the stack's own plate
    # solution (~/.observatory/nights/2026-10-17-a6000/m33/work/solve/stack.wcs, wcs-rd2xy, minus 1 for 0-based px), then
    # peak(); each looked at here in a full-size crop of m33/final/m33.png:
    #   core     catalogue (1450.4, 678.9), peak (1451, 679), 0.5 arcsec: the star-like point in the glow
    #   NGC 604  catalogue (631.6, 1060.1), peak (636, 1053), 6.5 arcsec: inside the blue cloud, which has several knots
    #   NGC 595  catalogue (1439.8, 362.8), peak (1441, 355), 6.1 arcsec: the knot in the middle of the pale cloud; no
    #            Gaia star within 8 arcsec of either point
    #   NGC 592  catalogue (1783.5, 125.2): a small clump of knots. step12's peak() (15 px round (1784, 128)) went to
    #            (1790, 137), 10.5 arcsec off, the brightest point at the clump's lower edge, which is Gaia DR3
    #            303381856840348160 (0.7 arcsec away): G 14.4, BP-RP 0.93, proper motion 10.5 mas/yr, so a star of our own
    #            galaxy in front (at M33's distance that motion would be over 40,000 km/s). The cloud's blue knot at
    #            (1781, 116) is Gaia 303381856836403968 (G 16.8, BP-RP 0.11, 1.4 mas/yr, within its errors of none). So the
    #            label's point is moved off the star: peak() kept to 6 px round (1782, 120), which finds (1781, 119), 5.2
    #            arcsec from the catalogue place, inside the clump, 20 px from the star. The words are unchanged.
    #   NGC 588 (catalogue (1970.8, -282.7)) and IC 133 fall outside the picture; not labelled.
    # The photographers' rows, from m33/final/recipe.json (summary, dropped, frames, steps):
    #   frames 342, kept 267: turn 1a (held still) 53 of 63, 1b (dithered) 26 of 30, 2 (after Saturn) 129 of 143,
    #           13 October 59 of 106. Dropped tonight (28): 21 smeared (common ellipticity over 0.20), 7 of them the first
    #           frame after a dither move (taken under 30 s after it), one (turn 1b) when someone was at the telescope
    #           (turn note); 2 with stars over 20 percent wider than the night's median (4.23); 3 the first frame after a
    #           slew, by rule; 2 taken under 10 s after a move. Dropped on 13 October (47): 43 smeared or soft (that
    #           night's median 3.63; until the fault was fixed the tracking let go now and then), 3 the first after a
    #           slew, 1 too soon after a move
    #   dither: turn 1b a spiral of radius 1.5 arcmin (frames moved up to 0.8); turn 2 every 3 frames, 47 places, probe
    #           radii 1 to 2.5 then 3 to 4 arcmin, the last place 4.8 arcmin out (radius 5); "a sensor-map bug chose 4;
    #           it widens the combined field" (turn notes)
    #   coverage: at least half the frames over 36.3 x 21.4 arcmin; every frame over 63 percent of the picture, three
    #           quarters over 94; edges 50 to 53 percent (summary, coverage; step 9 picture_edges)
    #   rotation: per turn 1a 6.7 to 8.2, 1b 5.7 to 6.6, 2 -0.5 to 1.2, 13 October 8.0 to 9.7 degrees: 10.2 in all
    #   hot pixels tonight 20,122 to 22,590 per plane, 13 October 4,959 to 6,931 (step 1)
    #   noise: green 3.49 DN in the faint region against 47.97 for one frame; tonight alone 3.88, 13 October alone 7.11
    #   stars 4.51 arcsec half-flux in the stack (100 stars), 4.91 the reference frame (step 9, deliver)
    #   colour shown on 0.46 percent of the picture (step 9, render_info); 0.248 percent exactly black (finish)
    #   altitude: turn 1 46 to 57, turn 2 76 to 83, 13 October 77 to 86 by the sidecars: "about 50 degrees up in the
    #           evening, about 80 after midnight"; the turns were in the evening and after midnight
    rec = stack("m33"); fin = finish("m33", "m33"); sm = rec["summary"]
    s9 = step(rec, "9 coverage, plate solve of the stack, star colours, render")["numbers"]
    S = s9["solve"]["pixscale_arcsec"]; FL = s9["solve"]["focal_length_mm"]; NORTH = s9["solve"]["north_angle_from_up_deg_clockwise"]
    turns = sm["turns"]; nU = sum(v["used"] for v in turns.values()); nT = sum(v["taken"] for v in turns.values())
    D = 2.73e6
    T["triangulum-galaxy"] = dict(src="m33/final/m33.png", scale=S, north=-NORTH, title="The Triangulum Galaxy", sub="Messier 33, a spiral galaxy in Triangulum",
        gear="© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  nights of 12 and 17 October 2026",
        what="A whole galaxy of about 40 billion stars, the third largest in our Local Group after Andromeda and our own Milky Way. It is bigger on the sky than the camera sees: this is its middle and inner arms. The bright knots along the arms are clouds where new stars are being born; the biggest, NGC 604, is one of the largest star-forming clouds known.",
        facts=[("DISTANCE", "about 2.7 million light-years (estimates run 2.6 to 3.0 million)"),
               ("THIS PICTURE SPANS", "about 29,000 light-years; one pixel is about 10 light-years, and NGC 604 alone is about 1,500 light-years across"),
               ("THE LIGHT LEFT", "about 2.7 million years ago, around when the first stone tools were made in East Africa"),
               ("HONEST NOTE", "the galaxy fills every frame, so there is no empty sky to set black by: the darkest part of the picture is still galaxy. The outer arms that deep pictures show reach past the edges")],
        bar=(bar(5000, D, S), "5,000 light-years"), frames="%d of %d frames of 15 s, from two nights" % (nU, nT),
        labels=lambda im: [(peak(im, (1451, 680), 15, 2.0), "The core", 10, -9),
                           (peak(im, (630, 1060), 15, 3.0), "NGC 604, a giant star-forming cloud", 6, 10),
                           (peak(im, (1440, 360), 15, 3.0), "NGC 595, a star-forming cloud", -10, -7),
                           (peak(im, (1782, 120), 6, 3.0), "NGC 592, a star-forming cloud", 9, 4)],
        how_sub="%.1f hours of light from two nights, the camera moved a little between frames" % (nU * 15 / 3600.0),
        tech=[("EXPOSURES", "%d x 15 s at ISO 3200: %.1f minutes. Tonight %d frames, %.1f minutes in three turns; 13 October %d frames, %.1f minutes" % (nU, nU / 4.0, nU - turns["13oct"]["used"], (nU - turns["13oct"]["used"]) / 4.0, turns["13oct"]["used"], turns["13oct"]["used"] / 4.0)),
              ("FRAMES", "%d taken, %d kept. Tonight, held still: %d of %d; dithered: %d of %d; after Saturn, dithered: %d of %d. 13 October: %d of %d. Dropped tonight: 21 smeared (every star stretched the same way; 7 of them the first frame after a dither move, one when someone was at the telescope), 2 with soft stars, 3 the first frame after a slew, 2 taken too soon after a move. Dropped on 13 October: 43 trailed or soft (the tracking let go now and then until it was fixed during that run), 3 the first frame after a slew, 1 too soon after a move" % (nT, nU, turns["1a"]["used"], turns["1a"]["taken"], turns["1b"]["used"], turns["1b"]["taken"], turns["2"]["used"], turns["2"]["taken"], turns["13oct"]["used"], turns["13oct"]["taken"])),
              ("DITHERING", "Tonight's first turn held still (the field drifted about 2.5 arcmin). The second moved between frames in a spiral up to 1.5 arcmin. The turn after Saturn moved every 3 frames, small probe steps and then up to 4 arcmin from the start (the last place nearly 5): a bug in the sensor map chose the 4, and it was kept because it widened the field the frames cover. 13 October was not dithered"),
              ("SAMPLING", "%.3f arcsec per pixel: one pixel per 2 x 2 colour cell, never enlarged. Stars %.1f arcsec wide (half-flux) in the stack, %.1f in the reference frame; the frames' median 4.2 tonight, 3.6 on 13 October" % (S, s9["deliver"]["star_size"]["stack_arcsec"], s9["deliver"]["star_size"]["reference_frame_arcsec"])),
              ("FIELD", "%.1f x %.1f arcmin: the area that at least half the frames cover. Inside it %.0f percent of the pixels have every frame and %.0f percent at least three quarters of them; at the edges it falls to 50 to 53 percent. Not turned (north 64 degrees anticlockwise of up)" % (s9["solve"]["field_arcmin"][0], s9["solve"]["field_arcmin"][1], 100 * s9["solve"]["fraction_inside_with_every_frame"], 100 * s9["solve"]["fraction_inside_with_three_quarters"])),
              ("WHEN", "The night of 17 October 2026, in the evening and after midnight, either side of Saturn; and 13 October 2026, after midnight. About 50 degrees up in the evening, about 80 after midnight"),
              ("REGISTRATION", "Each frame placed first by its own plate solve (all within 9 sensor px of the star solution), then rotation and shift on the stars, weighted rms at most 0.84 px. The field turned 10.2 degrees across all the frames, 8.7 of it over tonight's turns, because the mount stood about 10 degrees off the pole"),
              ("DARKS", "None taken. Hot pixels found from the frames, one map per night (about 20,000 to 22,600 per colour plane tonight, 5,000 to 6,900 on 13 October), repaired by the 3 x 3 median of their colour plane"),
              ("FLATS", "No flat frames. The hybrid flat of 13 October (large scale from that night's open sky, dust from its twilight frames), the flat tonight's Dumbbell Nebula run chose. On this run's dithered sky, the galaxy's middle masked, it leaves less than the twilight flat alone: 1.3 against 2.8 percent in green after a plane, galaxy light included. The galaxy fills the frame, so no large scale could be built or judged from these frames"),
              ("CALIBRATION", "Dust that moved since 13 October, measured on each night's own frames (each frame against the first stack put back on its sensor grid, so the galaxy cancels) and divided out. Tonight %d shadows, each seen in the first turn and the turn after Saturn alone, %.2f percent of the sensor; among them the new crescent, %.1f percent deep after the 13 October flat, left at %.2f percent. 13 October: %d shallow ones (1.5 to 3 percent), from its odd and even frames, a weaker test because those frames were not dithered" % (len(step(rec, "7 canvas and dust")["numbers"]["nights"]["18oct"]["divided_out"]), 100 * step(rec, "7 canvas and dust")["numbers"]["nights"]["18oct"]["sensor_fraction_changed"], 100 * step(rec, "7 canvas and dust")["numbers"]["nights"]["18oct"]["named_shadows"][0]["left_by_the_13oct_flat"], 100 * step(rec, "7 canvas and dust")["numbers"]["nights"]["18oct"]["named_shadows"][0]["left_after_own_correction"], len(step(rec, "7 canvas and dust")["numbers"]["nights"]["13oct"]["divided_out"]))),
              ("STACKING", "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered with rotation, then a 3-sigma clipped mean weighted by each frame's clarity and noise. Not done, for the time limit: proper coaddition (1 to 4 percent more signal to noise on stars from 15 s frames), and lining red and blue up with green against the air's prism. One constant per colour per frame, set on the darkest 30 percent of the area every frame covers: the galaxy's faintest level, not the true sky; no surface fitted. Noise 13.7 times lower than one frame (green); with 13 October's frames 10 percent lower than tonight's alone"),
              ("WHAT IS REAL", "The arms and clusters at every distance from the core: the odd and the even frames, each stacked alone, agree in 84 of 84 tiles of 3 arcmin, out to the corners 18 to 30 arcmin from the core; and tonight's frames against 13 October's, two nights with two dust corrections, agree in 84 of 84"),
              ("NOT SEEN", "The galaxy's far outer arms: they lie beyond the frame. The true sky level: there is none in the frame"),
              ("HONEST LIMITS", "The tests compare structure at the scale of arms and clusters, not the smooth glow of the disc; with no blank sky in the frame they cannot say how far the faintest light stands above the true sky"),
              ("COLOUR", "The camera's colour matrix with its white balance set by %d Gaia stars in the field (red x %.2f, blue x %.2f). Colour only where the light is bright enough to carry it, %.1f percent of the picture; the faint disc is grey" % (s9["colour"]["used"], s9["colour"]["factors"]["R"], s9["colour"]["factors"]["B"], 100 * s9["deliver"]["render_info"]["colour_shown_fraction"])),
              ("FINISH", "Star colours from Gaia, the camera's colour matrix. Arcsinh stretch; black at the faintest part's own level, gamma 0.9, S-curve 0.3, saturation x 1.25; the dark parts smoothed (bilateral 3 px). %.1f percent of the picture is exactly black" % fin["clipped_to_black_pct"]),
              optics(FL), CAMERA,
              ("MOUNT", "Sky-Watcher EQ6-R, unguided. Set down about 10 degrees off the pole tonight; aligned from plate-solved photos, both axes driven from that model. Dithered between frames for most of tonight")])

    # -- Saturn and five of its moons (saturn/final/saturn-finished.png, saturn/final/recipe.json) ----------------------
    # The stacking agent's card (saturn/share/saturn-annotated.jpg, drawn by saturn/step11_annotate.py) is its own layout,
    # not this file's: fixed type sizes, labels placed in pixels, the picture on a 1,100 px frame with 90 px of black above
    # it for labels. The entry draws those labels itself (draw=), with step 11's words, sizes, colours and offsets, on the
    # picture's own 964 x 514 pixels; the facts are step 11's word for word. One label moves: "A star, not a moon" sat
    # in the black above the picture (offset -30, -75 from the star at (516.7, 63.1)), which the website's labelled
    # picture does not have; here it is at -6, -36, straight above the star, clear of "Globe" and "Dione".
    # Step 11 read work/*.json, which step 13 deleted; every number here is read from final/recipe.json, which keeps them
    # (composite: moons_px, planet_px, stars_px, arcsec_per_px; ephemeris: distance_au, equatorial_diameter_arcsec).
    # Facts: 8.46288 AU x 1.495979e8 = 1,266 million km; 8.46288 x 499.005 s = 70 minutes; globe 19.6 arcsec = 50 px.
    # The photographers' rows, from final/recipe.json:
    #   frames: 488 planet frames, every one "usable" (none dropped for light: flux band 0.8 to 1.25, all within 0.93 to
    #           1.07 of the median), 25 kept; selection.why_kept and counts_compared for why 25 and not the rule's 5
    #   stack: residual shift 0.115 fine px rms = 0.04 sensor px; dispersion red (0.313, 0.363), blue (-0.519, -0.543)
    #           sensor px, the same in each half to 0.04
    #   titan_blur 3.198 x 2.970 arcsec; restoration 24 rounds, rim limit 0.02 (model rim with grain 0.0196 at 24, 0.0222
    #           at 26); cassini_seen false: at 1.985 equatorial radii the light lies between ring B's (1.8) and ring A's
    #           (2.15) at both ends, plain, restored and in each half: no dip
    #   moons: off 0.01 to 0.12 arcsec from Horizons, similarity fit 0.067 arcsec rms; Mimas (30 arcsec out) not found,
    #           Tethys (9.6) inside the blown-out patch, Hyperion not found; the star Gaia DR3 2549423661270534784, G 11.9,
    #           0.93 arcsec from its catalogue place; seven points of 6 to 8 sigma match neither a moon nor a Gaia star
    #           brighter than 16: one is Gaia G 14.2, the others are not named
    #   4 October (hack/stacks/2026-10-03/saturn; observations/2026-10-03/objects.json; ~/.observatory/nights/
    #           2026-10-03-a6000/saturn/sharp/saturn-and-moons-sharp.json): Titan's blur 2.7 x 2.2 arcsec, the plain stack
    #           of 16 with gap contrast 0.325 and ring width 3.82 arcsec, by the same metrics.py; tonight's plain stack of 25:
    #           0.127 and 4.16
    #   when: frames 22:20 to 00:25 local by the window, kept ones mostly in the first hour; "about 50 degrees up"
    sr = json.load(open("saturn/final/recipe.json")); co = sr["composite"]; eph = sr["ephemeris"]; SS = co["arcsec_per_px"]
    au = eph["distance_au"]; km = au * 1.495979e8; light_min = au * 499.005 / 60; diam = eph["equatorial_diameter_arcsec"]
    def saturn_labels(d, ox):
        """saturn/step11_annotate.py's labels, bar and north, on the picture's own pixels (its TOP margin is 0 here)."""
        INK11, DIM11, PILL11 = (235, 235, 235), (165, 165, 165), (0, 0, 0, 170); f, fs = font(17, "medium"), font(14); s = 1 / SS
        def label(px, text, dx, dy, gap=9, small=None):
            x, y = px[0] + ox, px[1]; tx, ty = x + dx, y + dy; L = np.hypot(dx, dy); ux, uy = dx / L, dy / L
            d.line([(x + ux * gap, y + uy * gap), (tx - ux * 4, ty - uy * 4)], fill=(200, 200, 200, 255), width=1)
            w = max(d.textlength(text, font=f), d.textlength(small, font=fs) if small else 0); bx = tx if dx >= 0 else tx - w - 12; by = ty - 12 if abs(dy) < 1e-6 else (ty - 24 if dy < 0 else ty)
            d.rounded_rectangle([bx - 2, by, bx + w + 10, by + 24 + (18 if small else 0)], 6, fill=PILL11); d.text((bx + 4, by + 2), text, font=f, fill=INK11)
            if small: d.text((bx + 4, by + 24), small, font=fs, fill=DIM11)
        m = co["moons_px"]; P = co["planet_px"]
        label(m["Titan"], "Titan", 40, 50, small="bigger than Mercury"); label(m["Rhea"], "Rhea", 50, 40); label(m["Dione"], "Dione", 60, -40)
        label(m["Iapetus"], "Iapetus", -60, -40); label(m["Enceladus"], "Enceladus", -70, -55, small="faint")
        for st_ in co["stars_px"]: label(st_["where"], "A star, not a moon", -6, -36, gap=6)      # step 11: -30, -75, in the black above the picture
        re_px = diam / 2 * s
        label([P[0] - 1.9 * re_px, P[1] + 1], "Rings", -20, 80, gap=4); label([P[0], P[1] - 0.7 * re_px], "Globe", -90, -40, gap=4)
        label([P[0] + 1.35 * re_px, P[1] + 1], "Dark gap between rings and globe", 60, 95, gap=3)
        Hp, Wp = co["size"][1], co["size"][0]
        bx, by = 40 + ox, Hp - 40; L1 = 60 * s; d.line([(bx, by), (bx + L1, by)], fill=INK11, width=2); d.text((bx, by - 26), "1 arcminute", font=fs, fill=INK11)
        nx, ny = Wp - 260 + ox, Hp - 40; d.line([(nx, ny), (nx, ny - 50)], fill=INK11, width=2); d.text((nx - 5, ny - 72), "N", font=fs, fill=INK11); d.line([(nx, ny), (nx - 50, ny)], fill=INK11, width=2); d.text((nx - 68, ny - 9), "E", font=fs, fill=INK11)
    sel = sr["selection"]; stk = sr["stack"]; ti = sr["titan_blur"]; rs = sr["restoration"]; mo = sr["moons"]; nP = sr["frames"]["planet"]; K = stk["keep"]
    T["saturn"] = dict(src="saturn/final/saturn-finished.png", scale=SS, north=0.0, title="Saturn and five of its moons", sub="The ringed planet, in Pisces",
        draw=saturn_labels,
        what="A planet ten times as far from the Sun as the Earth, with rings of ice wider than the planet itself. Two hours of short pictures around its highest point in the sky, and only the sharpest moments kept.",
        facts=[("HOW FAR", "Saturn was %s million km away; its light took %d minutes to get here." % (format(int(round(km / 1e6)), ","), round(light_min))),
               ("HOW BIG", "The globe is about 120,000 km across, nine Earths side by side; the rings span about 270,000 km and are mostly less than a kilometre thick. Here the globe is %.0f arcseconds wide, about 50 pixels." % diam),
               ("THE MOONS", "Five of its moons, named from where JPL's orbits put them at that moment; each name sits on a point found in the picture. Titan, the largest, has a thick atmosphere. Tethys and Mimas were lost in the planet's glare, Hyperion was too faint."),
               ("HONEST NOTE", "The air was soft that night. The rings, the dark gap inside them and the globe show; the Cassini division in the rings does not. The planet and the moons are shown at different brightness: the moons are hundreds to thousands of times fainter than the planet.")],
        bar=(60 / SS, "1 arcminute"), frames="%d of %d frames of 1/60 s for the planet, 2 frames of 2 s for the moons" % (K, nP),
        how_sub="the sharpest %d of %d short frames for the planet, two longer ones for the moons, set together at the sensor's own scale" % (K, nP),
        tech=[("EXPOSURES", "%d x 1/60 s at ISO 800 for the planet; 2 x 2 s at ISO 6400 for the moons, the two framing shots taken just before, in which the planet is blown out (960 times the exposure)" % nP),
              ("FRAMES", "%d taken for the planet, all usable, the sharpest %d kept. No cloud: every frame's light within 7 percent of the median. Each frame graded by sharpness, its ring line measured to follow the field's turn. Moons: both frames" % (nP, K)),
              ("WHEN", "The night of 17 October 2026, from late in the evening to just after midnight, over two hours; 24 of the 25 kept frames from its first hour. About 50 degrees up"),
              ("SAMPLING", "%.3f arcsec per pixel, the sensor's own scale, never enlarged: the planet is stacked on a grid 3 times finer for the arithmetic, then binned back" % SS),
              ("FIELD", "%.1f x %.1f arcmin, north up and east left: both parts turned %.0f degrees in one resampling each, at their own scale" % (co["size"][0] * SS / 60, co["size"][1] * SS / 60, mo["similarity_fit"]["turn_deg"])),
              ("CALIBRATION", "No darks or flats. Each frame's sky, one constant per colour plane, taken off. The two moon frames averaged, and where they disagree by more than 6 sigma the lower kept, so a hot pixel or a cosmic ray in one drops out (the field moved 4.6 arcmin across the sensor between them)"),
              ("LUCKY IMAGING", "Plain stacks of the sharpest 5 up to all %d compared on the polar limb, the ring's width and the gap between rings and globe: 8 to 25 frames sit on one plateau, more are softer, and 5 is sharper by the gap (%.3f against %.3f), so the rule chose 5. %d were kept, because restored, %d beat 5 (gap %.3f against %.3f) with less than half the grain and Titan measured at 18 sigma instead of 8: the blur is known better" % (nP, sel["counts_compared"][0]["gap_contrast"], [c for c in sel["counts_compared"] if c["keep"] == K][0]["gap_contrast"], K, K, rs["metrics_restored"]["gap_contrast"], 0.313)),
              ("REGISTRATION", "Each colour plane laid at its own place on a grid 3 times finer than the sensor (0.129 arcsec), no demosaic; the field's turn (%.3f degrees a minute) taken out; registered to %.2f sensor px rms. The air's prism: red sat %.2f, %.2f and blue %.2f, %.2f sensor px from green, the same in each half of the frames, and were slid back onto it" % (abs(sel["turn_deg_per_minute"]), stk["residual_shift_after_fine_px_rms"] / 3, *stk["dispersion_native_px"]["red"], *stk["dispersion_native_px"]["blue"])),
              ("PLANET STACK", "The %d frames each turned back to the moons' moment and laid down in one Lanczos resampling with their colour places and shift, then averaged; two half stacks (odd and even ranks) made the same way for the tests" % K),
              ("RESTORATION", "Blur measured on Titan in the same %d frames: %.2f x %.2f arcsec (Titan's own disc, 0.8 arcsec, adds about 1 percent). Divided out with %d rounds of Richardson-Lucy on brightness, each colour scaled alike. The rounds were set on a model Saturn blurred the same way with the stack's own grain: stopped before its false bright rim passes %.0f percent of the globe" % (ti["frames"], *ti["fwhm_arcsec"], rs["rounds"], 100 * rs["rim_limit"])),
              ("COMPOSITE", "The planet set into the moon field where the 2 s frames are blown out, grown %d px and feathered over %d. The planet's glare taken off the moon field ring by ring. Each part has its own white: the moons are lifted hundreds to thousands of times against the planet" % (co["grow_px"], co["feather_px"])),
              ("FINISH", "Planet: white at its brightest 0.05 percent, gamma 1.25. Moons: an arcsinh stretch so Titan and Iapetus both show. Then the dark sky set neutral and to black at its own level (60th percentile), smoothed (bilateral 4 px), saturation x 1.15"),
              ("MOON NAMES", "Every point 6 sigma above the glare listed and matched to JPL Horizons for the frames' moment: Titan, Rhea, Dione, Iapetus and Enceladus each within %.2f arcsec of its predicted place, %.2f arcsec rms. The point beside Dione is the star Gaia DR3 %d (G %.1f), not a moon" % (max(v["found"]["off_arcsec"] for v in mo["moons"].values() if v["found"]), mo["similarity_fit"]["rms_arcsec"], mo["stars"][0]["gaia"]["source"], mo["stars"][0]["gaia"]["g"])),
              ("NOT SEEN", "The Cassini division: at its place the light lies between ring B's and ring A's at both ends, in the plain stack, the restored one and each half alone, with no dip. Mimas (30 arcsec out) not found; Tethys (10 arcsec out) inside the blown-out patch; Hyperion too faint. Seven faint points (6 to 8 sigma) match no moon; one is a Gaia star, the others are not named"),
              ("COMPARED", "Not as sharp as 4 October: Titan's blur %.1f x %.1f arcsec against 2.7 x 2.2 then, and by the same measures the plain stack's gap contrast %.2f against 0.32 and the ring's width %.1f against 3.8 arcsec" % (ti["fwhm_arcsec"][0], ti["fwhm_arcsec"][1], sel["counts_compared"][[c["keep"] for c in sel["counts_compared"]].index(K)]["gap_contrast"], sel["counts_compared"][[c["keep"] for c in sel["counts_compared"]].index(K)]["ansa_width_fwhm_arcsec"])),
              ("TELESCOPE", "Celestron 8SE Schmidt-Cassegrain: 203 mm aperture, 2,084 mm focal length by plate solve, f/10.3"), CAMERA,
              ("MOUNT", "Sky-Watcher EQ6-R, unguided, not dithered")])
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
        band, ops, rules = band_layout(Wc, u, t["title"], t["sub"], t["what"], t["facts"], len(t["facts"]), [t.get("gear", GEAR), t["frames"][0].upper() + t["frames"][1:] + ".  " + TRUE], False)
    else:
        band, ops, rules = band_layout(Wc, u, "How it was made: " + re.sub("^The ", "the ", t["title"].split(":")[0]), t["how_sub"][0].upper() + t["how_sub"][1:], None, t["tech"], 3, [t.get("gear", GEAR), MADE], True)
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
    own = kind == "story" and "draw" in t                         # an entry that draws its own labels, bar and north (Saturn, as its own card)
    if own: t["draw"](d, ox)
    elif kind == "story":
        for pt, text, dx, dy, *gap in t["labels"](rgb):           # a label may carry its own gap as a fifth value
            if 0 <= pt[0] < W and 0 <= pt[1] < H: label(pt, text, dx, dy, leader=text not in t.get("plain", ()), gap=gap[0] if gap else None)
    if not own:
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
