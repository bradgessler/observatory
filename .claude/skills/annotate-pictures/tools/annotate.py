"""The share set: three JPEGs for every finished picture.

  <name>.jpg            the picture as it is, nothing on it
  <name>-annotated.jpg  names and a scale bar on the picture; underneath, what it is, how far, how big
  <name>-how.jpg        for photographers: the fields that were joined (outlined on the picture), exposures,
                        frames kept and lost, sampling, calibration, stacking and finishing

The caption band is added underneath; it never covers the picture. All drawing is plain text and lines.
JPEGs are full resolution, quality 93, no chroma subsampling, no metadata.

Usage: annotate.py [name ...]           (no names: all) -> share/
       annotate.py --site <folder>      the same pictures and words for the website: <folder>/images and <folder>/objects.json

Nothing here gives a clock time with an altitude: together with the object they would place the telescope.
"""
import json, math, os, re, sys
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); os.makedirs("share", exist_ok=True)
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"
def font(size, weight="regular"): return ImageFont.truetype(AVENIR, max(8, int(round(size))), index={"bold": 0, "demi": 2, "medium": 5, "regular": 7}[weight])
INK, SOFT, DIM, BAND, RULE = (244, 244, 240), (198, 198, 194), (140, 140, 138), (10, 10, 12), (62, 62, 64)
GEAR = "© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, 2,080 mm) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  4 October 2026"
TRUE = "Stacked from the camera's RAW frames. Nothing generated."
OPTICS = ("TELESCOPE", "Celestron 8SE Schmidt-Cassegrain with dew shield: 203 mm aperture, 2,084 mm focal length (measured by plate solve), f/10.3")
CAMERA = ("CAMERA", "Sony a6000, stock, at prime focus: APS-C 23.5 x 15.6 mm, 6000 x 4000, 3.9 micron pixels, RAW")
MOUNT = ("MOUNT", "Sky-Watcher EQ6-R, unguided. Set down 27 degrees off the pole; both axes driven from a pointing model fitted to plate solves. Residual drift about 0.1 arcsec per second")
MADE = "Capture and mount: Observatory (Elixir on a Raspberry Pi 3).  Stacking: numpy, OpenCV, rawpy.  Plate solving: astrometry.net.  " + TRUE
STACK = "RAW colour planes (no demosaic), hot pixels by 3 x 3 median, registered on stars with rotation, sigma-clipped mean"

def affine(path): return np.array(json.load(open(path))["source_px_to_this_px"])
def through(M, pt): return (M[0, 0] * pt[0] + M[0, 1] * pt[1] + M[0, 2], M[1, 0] * pt[0] + M[1, 1] * pt[1] + M[1, 2])
def peak(img, near, radius, blur):
    """The brightest spot near a place, so a name sits on the thing itself and not on a guess."""
    g = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32), (0, 0), blur)
    x0, y0 = max(int(near[0] - radius), 0), max(int(near[1] - radius), 0); t = g[y0:y0 + 2 * radius, x0:x0 + 2 * radius]
    y, x = np.unravel_index(np.argmax(t), t.shape); return (x0 + x, y0 + y)

def moon_place(lon, lat, c=(2729.6, 2714.9), R=2528.2, l0=2.8, b0=-3.7):
    L, B, l0, b0 = map(math.radians, (lon, lat, l0, b0))
    e = math.cos(B) * math.sin(L - l0); n = math.sin(B) * math.cos(b0) - math.cos(B) * math.sin(b0) * math.cos(L - l0)
    return (c[0] + R * e, c[1] - R * n)

def footprints(centre_px, scale, axes, panels, M=None):
    """Outlines of the sensor frame at each aim, in picture pixels. centre_px: where the mosaic's reference point sits in
    the north-up picture; scale: arcsec per px there; axes: arcmin east, north per sensor px along the frame's x and y;
    panels: [(label, arcmin east, arcmin north)]; M: north-up picture -> levelled picture."""
    xe, xn, ye, yn = axes; out = []
    for label, e, n in panels:
        poly = []
        for sx, sy in ((-3000, -2000), (3000, -2000), (3000, 2000), (-3000, 2000)):
            E, N = e + sx * xe + sy * ye, n + sx * xn + sy * yn
            p = (centre_px[0] - E * 60 / scale, centre_px[1] - N * 60 / scale); poly.append(through(M, p) if M is not None else p)
        out.append((poly, label))
    return out

def targets():
    T = {}
    T["orion-nebula"] = dict(src="final/orion-nebula.png", scale=0.776, north=24.0, title="The Orion Nebula", sub="Messier 42",
        what="A cloud of glowing gas where stars are being born right now. The four young stars at its heart, the Trapezium, light up the whole nebula.",
        facts=[("DISTANCE", "1,344 light-years"), ("THIS PICTURE SPANS", "15 light-years"), ("THE LIGHT LEFT", "around the year 680"), ("FOR SCALE", "Neptune's whole orbit would cover a fifth of one pixel")],
        bar=(3 / (1344 * 2.909e-4) * 60 / 0.776, "3 light-years"), frames="39 frames of 20 s, with 16 of 2 s for the bright core",
        labels=lambda im: [(peak(im, (1388, 908), 60, 6), "Trapezium", 7, -7), (peak(im, (896, 518), 80, 3), "M43", -6, -5), ((1366, 1062), "Orion Bar", 9, 6), ((1178, 905), "Fish's Mouth", -11, 3)],
        how_sub="13 minutes of light on one field, plus short frames so the core does not burn out",
        tech=[("EXPOSURES", "39 x 20 s at ISO 3200 for the nebula; 16 x 2 s at ISO 800 for the core"), ("FRAMES", "69 long frames taken, 39 kept. 30 lost to passing cloud (stars dimmed to between 3 and 77 percent)"),
              ("HIGH DYNAMIC RANGE", "The 2 s stack replaces the 20 s stack wherever any frame came within 7 percent of clipping: 31 star cores, the Trapezium among them. Measured ratio 41.0, expected 40"),
              ("SAMPLING", "0.776 arcsec per pixel: one pixel per 2 x 2 colour cell. Stars 4.2 arcsec wide"), ("FIELD", "38.8 x 25.8 arcmin: one sensor frame"),
              ("WHEN", "4 October 2026, before dawn. 41 to 46 degrees up, 41 percent Moon in the sky, thin cloud passing"),
              ("CALIBRATION", "Flat from 26 twilight-sky frames, its large-scale shape from cloud-lit frames. No darks"), ("STACKING", STACK + ". One sky constant per colour"),
              ("FINISH", "Black 19 and white 217 of 255, gamma 0.95, S-curve 0.3. Saturation x 1.6 in CIELAB. Dark sky made neutral and smoothed (bilateral, 2.5 px)"), OPTICS, CAMERA, MOUNT])
    M42 = affine("m42/m42-mosaic-level.json"); ax42 = (-0.005904, -0.002649, 0.002660, -0.005897)
    T["orion-nebula-wide"] = dict(src="final/orion-nebula-wide.png", scale=1.552, north=24.2, title="The Orion Nebula, wide", sub="Messier 42 and Messier 43",
        what="Five overlapping fields joined into one, to take in the faint outer loops of gas round the bright heart of the nebula.",
        facts=[("DISTANCE", "1,344 light-years"), ("THIS PICTURE SPANS", "27 light-years"), ("THE LIGHT LEFT", "around the year 680"), ("WHAT IT IS", "the nearest great nursery of new stars")],
        bar=(5 / (1344 * 2.909e-4) * 60 / 1.552, "5 light-years"), frames="mosaic of 5 fields, 20 s frames, joined to the deep centre",
        labels=lambda im, M=M42: [(peak(im, through(M, (1630, 1378)), 40, 3), "Trapezium", 7, -7), (peak(im, (through(M, (1630, 1378))[0] - 246, through(M, (1630, 1378))[1] - 195), 50, 2), "M43", -6, -5)],
        outlines=lambda M=M42: footprints((1630, 1378), 1.552, ax42, [("Centre: 39 of 69", 0.7, 0.0), ("1: 13 of 13", 9.93, 15.78), ("2: 12 of 13", -18.40, 3.10), ("3: 5 of 13", -9.93, -15.78), ("4: 2 of 13", 18.40, -3.10)], M),
        how_sub="a 2 x 2 mosaic round the deep centre field; each outline is one sensor frame, with frames kept of frames taken",
        tech=[("EXPOSURES", "20 s at ISO 3200 throughout; 2 s at ISO 800 for the core"), ("FRAMES", "Centre 39 of 69. Panels 13, 12, 5 and 2 of 13 each: the last two were shot under cloud and are shown in grey"),
              ("MOSAIC", "Each panel centred by plate solve, then placed by its own plate solution; scaled on shared stars; matched to the centre with a constant and a plane; feathered"),
              ("SAMPLING", "1.552 arcsec per pixel (2 x 2 mean of the working grid). Stars 4.4 to 5 arcsec wide"), ("FIELD", "67.9 x 43.4 arcmin, cropped level from the mosaic; one frame is 38.8 x 25.9"),
              ("WHEN", "4 October 2026, before dawn. 41 to 46 degrees up, Moon up, thin cloud passing"), ("CALIBRATION", "Flat from 26 twilight-sky frames, large-scale shape from cloud-lit frames. No darks"),
              ("STACKING", STACK), ("FINISH", "Black 34 and white 199 of 255, S-curve 0.3. Saturation x 1.5. Dark sky made neutral and smoothed (bilateral, 3 px)"), OPTICS, CAMERA, MOUNT])
    T["andromeda-core"] = dict(src="final/andromeda-core.png", scale=0.776, north=31.7, title="The heart of the Andromeda Galaxy", sub="Messier 31",
        what="The centre of the nearest big galaxy to our own. The glow is billions of stars, too far away to see one by one. The dark lanes are dust in its spiral arms, where new stars form.",
        facts=[("DISTANCE", "2.5 million light-years"), ("THIS PICTURE SPANS", "28,000 light-years"), ("THE LIGHT LEFT", "2.5 million years ago, when our ancestors were first making stone tools"), ("FOR SCALE", "each pixel is about 10 light-years across")],
        bar=(5000 / (2.54e6 * 2.909e-4) * 60 / 0.776, "5,000 light-years"), frames="38 clear frames of 20 s",
        labels=lambda im: [(peak(im, (1426, 1235), 200, 25), "Nucleus", 8, 7), ((1950, 985), "Dust lanes", 7, -10)],
        how_sub="an hour on one field; cloud took two frames in three",
        tech=[("EXPOSURES", "38 x 20 s at ISO 3200: 12.7 minutes"), ("FRAMES", "109 taken, 38 kept (27 clear, 11 through thin cloud and down-weighted). 71 lost to cloud, judged by how much each frame dimmed the stars"),
              ("SAMPLING", "0.776 arcsec per pixel: one pixel per 2 x 2 colour cell. Stars 4.1 arcsec wide"), ("FIELD", "37.4 x 22.5 arcmin: the part of one sensor frame that at least 31 of the 38 frames cover, less 2.3 arcmin off the top, cropped to lose the shadow of a piece of chaff in the light path"),
              ("WHEN", "4 October 2026, after midnight, over 70 minutes. 83 degrees up, Moon just rising"), ("FIELD ROTATION", "The mount was far off the pole, so the field turned 2.9 degrees during the run. Corrected in registration"),
              ("CALIBRATION", "Flat built from the clouded frames themselves: cloud glow seen through the optics, less the scaled clear frame. Dust shadows left out of the average. No darks"),
              ("STACKING", STACK + ", weighted by transparency. One constant per frame; no sky surface fitted, the galaxy fills the frame"),
              ("FINISH", "Black 13 and white 229 of 255, gamma 1.2, S-curve 0.45. Saturation x 1.2. Dark parts made neutral and smoothed (bilateral, 2.5 px)"), OPTICS, CAMERA, MOUNT])
    M31 = affine("m31/mosaic/m31-mosaic-level.json"); ax31 = (-0.005326, -0.003670, 0.003656, -0.005333)
    T["andromeda-mosaic"] = dict(src="final/andromeda-mosaic.png", scale=1.552, north=35.1, title="The Andromeda Galaxy: core, dust lanes and a companion", sub="Messier 31 and Messier 32",
        what="Six fields joined round the galaxy's core. M32, the fuzzy ball below it, is a small galaxy in orbit round Andromeda.",
        facts=[("DISTANCE", "2.5 million light-years"), ("THIS PICTURE SPANS", "55,000 light-years; the galaxy's disc is about 2.5 times wider"), ("THE LIGHT LEFT", "2.5 million years ago"), ("FOR SCALE", "each pixel is about 19 light-years across")],
        bar=(10000 / (2.54e6 * 2.909e-4) * 60 / 1.552, "10,000 light-years"), frames="six fields of 30 s frames joined to the deep core; thin cloud that hour",
        labels=lambda im: [(peak(im, (984, 690), 120, 10), "M31 nucleus", -9, -7), (peak(im, (1520, 1420), 160, 6), "M32", 7, -5), ((1340, 592), "Dust lanes", 8, -9)],
        outlines=lambda M=M31: footprints((2232, 1868), 1.552, ax31, [("Core: 38 of 109", -3.1, 4.8), ("1: 5 of 11", 19.72, 26.15), ("2: 3 of 11", -5.85, 8.53), ("3: 2 of 11", -31.41, -9.08), ("4: 3 of 11", -19.72, -26.15), ("5: 2 of 11", 5.85, -8.53), ("6: 8 of 11", 31.41, 9.08)], M),
        how_sub="a 3 x 2 mosaic joined to the deep core field; each outline is one sensor frame, with frames kept of frames taken",
        tech=[("EXPOSURES", "Panels: 30 s at ISO 3200. Core: 20 s at ISO 3200"), ("FRAMES", "66 panel frames taken, 23 kept: 11.5 minutes. 43 lost to cloud. The core adds 38 frames, 12.7 minutes"),
              ("MOSAIC", "Each panel plate-solved, then all solved jointly on shared stars (0.4 to 0.6 arcsec). One brightness scale per panel from shared stars; backgrounds matched with a plane per panel; feathered"),
              ("SAMPLING", "1.552 arcsec per pixel. Stars 4.1 arcsec wide"), ("FIELD", "74.8 x 42.5 arcmin, cropped level from the mosaic; one frame is 38.8 x 25.9"),
              ("WHEN", "4 October 2026, in the small hours, over 67 minutes. 72 to 61 degrees up, Moon up, cloud passing"),
              ("HONEST LIMITS", "Outside the core field the panels hold 1 to 14 percent of the core's depth, and are shown in grey because their colour zero is not trusted. A map, not a measurement"),
              ("CALIBRATION", "Flat from 26 twilight-sky frames, its large-scale shape from cloud-lit frames; the dust in it checked against this hour's frames. No darks"),
              ("FINISH", "Black 53 and white 226 of 255, gamma 1.2, S-curve 0.3. Dark sky made neutral and smoothed (bilateral, 3.5 px)"), OPTICS, CAMERA, MOUNT])
    M45 = affine("m45/m45-mosaic-level.json"); stars = json.load(open("m45/before-flats/m45-mosaic-recipe.json"))["named_stars"]; ax45 = (-0.005814, -0.002818, 0.002813, -0.005816)
    side = dict(Alcyone=(5, -6), Atlas=(8, 6), Pleione=(-8, -5), Electra=(5, 5), Maia=(6, -5), Merope=(6, 6), Taygeta=(6, -2), Celaeno=(6, 3), Asterope=(-8, 5))
    T["pleiades"] = dict(src="final/pleiades.png", scale=1.553, north=26.1, title="The Pleiades", sub="Messier 45, the Seven Sisters",
        what="A family of about a thousand young stars, born together some 100 million years ago. The blue haze round Merope and Maia is a dust cloud they are drifting through, lit by their light.",
        facts=[("DISTANCE", "444 light-years"), ("THIS PICTURE SPANS", "13 light-years"), ("THE LIGHT LEFT", "in 1582, the year the modern calendar began"), ("HONEST NOTE", "the glow round Atlas and Pleione is thin cloud that night, not nebula")],
        bar=(2 / (444 * 2.909e-4) * 60 / 1.553, "2 light-years"), frames="nine fields, 60 frames of 10 s",
        labels=lambda im, M=M45: [(through(M, v["in_m45_mosaic_png_at_px"]), k) + side[k] for k, v in stars.items()],
        outlines=lambda M=M45: footprints((2327.75, 2231.75), 1.553, ax45, [("1: 7 of 7", 18.91, 32.14), ("2: 7 of 7", -9.0, 18.61), ("3: 3 of 7", -36.91, 5.08), ("4: 6 of 7", -27.91, -13.53), ("5: 7 of 7", 0.0, 0.0),
                                                                           ("6: 5 of 7", 27.91, 13.53), ("7: 3 of 7", 36.91, -5.08), ("8: 7 of 7", 9.0, -18.61), ("9: 7 of 7", -18.91, -32.14)], M),
        how_sub="a 3 x 3 mosaic; each outline is one sensor frame, with frames kept of frames taken",
        tech=[("EXPOSURES", "10 s at ISO 1600, about 7 frames per panel: one minute each"), ("FRAMES", "72 taken, 60 kept: 10 minutes in all. Panels 3 and 7 were shot through cloud and only fill where clear panels have no data"),
              ("MOSAIC", "Each panel centred to 0.6 arcmin by plate solve and a local nudge. Placed by its own plate solution (shared stars agree to 0.5 arcsec); one brightness scale and one constant per panel; feathered"),
              ("SAMPLING", "1.553 arcsec per pixel. Stars about 5 arcsec wide; the bright ones are saturated and left white"), ("FIELD", "99 x 63 arcmin, cropped level from the mosaic; one frame is 38.8 x 25.8"),
              ("WHEN", "4 October 2026, before dawn, over 49 minutes. 74 degrees up, 41 percent Moon in the sky"),
              ("WHAT IS REAL", "The haze at Merope and Maia repeats between independent stacks at 4 to 11 sigma. The glow at Atlas and Pleione is cloud"),
              ("CALIBRATION", "Flat and dust map from tonight's clouded frames; a faint sensor pattern common to all panels removed. No darks"),
              ("FINISH", "Black 24 of 255, gamma 0.95. Saturation x 1.45. Dark sky made neutral and smoothed (median 5 px, then bilateral 5 px): faint haze traded for a quiet sky"), OPTICS, CAMERA, MOUNT])
    T["m15"] = dict(src="final/m15.png", scale=0.388, north=20.9, title="Messier 15", sub="A globular cluster in Pegasus",
        what="A ball of well over a hundred thousand ancient stars, held together by their own gravity, in orbit round the Milky Way. At about 12 billion years old it is nearly as old as the universe.",
        facts=[("DISTANCE", "about 33,600 light-years"), ("THIS PICTURE SPANS", "156 light-years"), ("THE LIGHT LEFT", "in the last Ice Age, about when the oldest cave paintings in Europe were made"), ("FOR SCALE", "near its centre the stars are packed thousands of times closer than round the Sun")],
        bar=(25 / (33600 * 2.909e-4) * 60 / 0.388, "25 light-years"), frames="23 frames of 15 s", labels=lambda im: [],
        how_sub="under six minutes of light, straight after the telescope was refocused",
        tech=[("EXPOSURES", "23 x 15 s at ISO 1600: 5.75 minutes"), ("FRAMES", "26 taken, 23 kept. Two dimmed by cloud, one soft"),
              ("SAMPLING", "0.388 arcsec per pixel, the sensor's own. Stars 4.4 arcsec across (half-flux), down from 7.0 before the refocus"), ("FIELD", "16 x 16 arcmin, cropped from one sensor frame"),
              ("WHEN", "4 October 2026, just after midnight. 45 degrees up, no Moon yet"), ("FIELD ROTATION", "1.1 degrees in 14 minutes, corrected in registration"),
              ("CALIBRATION", "Dust and vignetting divided out with a flat built from the run's own sky. No darks"), ("STACKING", STACK + ". Core unclipped: 26 percent of full scale"),
              ("FINISH", "Black 28 and white 214 of 255, S-curve 0.2. Saturation x 1.5; dark sky shown without colour and smoothed (bilateral, 2.5 px)"), OPTICS, CAMERA, MOUNT])
    T["blue-snowball"] = dict(src="final/blue-snowball.png", scale=0.194, north=31.5, title="The Blue Snowball", sub="NGC 7662, a planetary nebula in Andromeda",
        what="A star like our Sun at the end of its life, puffing its outer layers into space. Its exposed core makes the gas glow; the blue-green is oxygen. The Sun will do this in about 5 billion years.",
        facts=[("DISTANCE", "roughly 5,700 light-years (not well known)"), ("THE SHELL IS", "about 0.8 light-years across: 50,000 times the Earth to Sun distance"), ("THE LIGHT LEFT", "before the pyramids were built"), ("HONEST NOTE", "taken before the telescope was refocused, so it is soft")],
        bar=(1 / (5700 * 2.909e-4) * 60 / 0.194, "1 light-year"), frames="25 frames of 6 s", labels=lambda im: [],
        how_sub="the first deep-sky target of the night, shot before the focus was fixed",
        tech=[("EXPOSURES", "25 x 6 s at ISO 1600: 2.5 minutes"), ("FRAMES", "25 taken, all kept"), ("SAMPLING", "0.194 arcsec per pixel: the sensor's 0.388 enlarged 2 x by Lanczos. Stars are rings 7 arcsec across: out of focus"),
              ("FIELD", "5.0 x 3.3 arcmin, cropped from one sensor frame"), ("WHEN", "3 October 2026, late evening. 84 degrees up, no Moon"), ("FIELD ROTATION", "0.5 degrees in 10 minutes, corrected in registration"),
              ("CALIBRATION", "None beyond a fitted sky. No flat, no darks"), ("STACKING", STACK + ": noise 4.8 times lower than one frame"),
              ("FINISH", "Black 26 and white 194 of 255, S-curve 0.2. Saturation x 1.4; dark sky shown without colour and smoothed"), OPTICS, CAMERA, MOUNT])
    km = 365300.0
    craters = [("Copernicus", -20.08, 9.62, 6, -5), ("Kepler", -38.0, 8.1, -7, -5), ("Aristarchus", -47.4, 23.7, -8, 5), ("Tycho", -11.36, -43.31, -9, 4), ("Clavius", -14.4, -58.4, -9, 3), ("Gassendi", -39.9, -17.5, -8, 4),
               ("Bullialdus", -22.2, -20.7, -9, 3), ("Eratosthenes", -11.3, 14.5, -11, -6), ("Grimaldi", -68.6, -5.2, 6, 6), ("Montes Recti", -20.0, 48.3, 6, -6), ("Sinus Iridum", -31.5, 44.1, -9, -6), ("Mare Imbrium", -17.0, 34.0, -11, 2),
               ("Mare Humorum", -38.6, -24.4, -10, 7), ("Oceanus Procellarum", -56.0, 3.0, 0, 0)]
    T["moon"] = dict(src="final/moon.png", scale=0.3881, north=0.0, title="The Moon at last quarter", sub="4 October 2026  ·  41 percent lit",
        what="Along the line between day and night the Sun is setting, so every crater rim and mountain throws a long shadow. That is why the detail is richest there.",
        facts=[("DISTANCE", "365,000 km, measured from its size in this picture"), ("ACROSS", "3,475 km"), ("LIGHT TOOK", "1.2 seconds"), ("FOR SCALE", "Copernicus is 93 km wide; Clavius, 231 km")],
        bar=(500 / km * 206265 / 0.3881, "500 km"), frames="39 frames of 1/60 s over four fields, flat-fielded",
        labels=lambda im: [(moon_place(lon, lat), name, dx, dy) for name, lon, lat, dx, dy in craters], compass=False, plain=("Oceanus Procellarum",),
        how_sub="lucky imaging over a 2 x 2 mosaic in morning twilight, with cloud about",
        tech=[("EXPOSURES", "1/60 s at ISO 100"), ("FRAMES", "78 taken over five aims in two passes, 39 kept. 17 saw only the night side; the rest were lost to cloud"),
              ("LUCKY IMAGING", "Frames registered on the lunar surface itself (12,000 matched features, 0.8 px). In each patch only the sharpest 30 percent of the clear frames are averaged"),
              ("RESTORATION", "Blur measured at the limb: 1.8 arcsec. Wiener and Richardson-Lucy with the gain capped at 3 x and held at the limb. No ringing found at limb, cusps or terminator"),
              ("SAMPLING", "0.388 arcsec per pixel, the sensor's own: 0.7 km per pixel on the Moon"), ("FIELD", "Disc 32.7 arcmin across, taller than one 38.8 x 25.9 frame: a 2 x 2 mosaic and a centre frame. One panel saw only the night side"),
              ("WHEN", "4 October 2026, in morning twilight, over half an hour. 62 to 70 degrees up"), ("CALIBRATION", "Flat from 7 twilight-sky frames: corners at 74 percent of the centre, 340 dust shadows divided out. Cloud glow fitted and subtracted per frame"),
              ("ORIENTATION", "Lunar north up, from 17 craters of known position (32.2 degrees from the sensor's way up)"), OPTICS, CAMERA, MOUNT])
    sj = json.load(open("saturn/sharp/saturn-and-moons-sharp.json")); mp = sj["moon_places_on_canvas_px"]; au = 8.5 * 149597870.7
    off = dict(Titan=(0, -5), Rhea=(3, -6), Iapetus=(0, -5), Tethys=(3, 6), Dione=(0, -8), Enceladus=(-5, 6), Hyperion=(0, -5))
    T["saturn"] = dict(src="saturn/sharp/saturn-and-moons-sharp-clean.png", scale=0.388, north=0.0, title="Saturn and seven of its moons", sub="At opposition, 4 October 2026",
        what="Saturn at its closest and brightest for the year, its rings tilted only a few degrees toward us. Every labelled point is a moon. Titan, the big one, is larger than the planet Mercury.",
        facts=[("DISTANCE", "1.27 billion km"), ("LIGHT TOOK", "about 70 minutes to get here"), ("THE RINGS", "270,000 km tip to tip: 70 percent of the way from Earth to the Moon"), ("HONEST NOTE", "the three inner moons are named from how they moved between frames")],
        bar=(500000 / au * 206265 / 0.388, "500,000 km"), frames="planet: the 16 sharpest of 48 frames at 1/40 s; moons: 2 s frames",
        labels=lambda im: [(tuple(mp[k]), k) + off[k] for k in mp] + [(tuple(sj["planet"]["placed"]["centre_on_canvas_px"]), "Saturn", 0, 7), ((306, 1269), "A star, not a moon", 5, -4)], compass=False,
        how_sub="two exposures in one picture: 1/40 s for the planet, 2 s for the moons",
        how_labels=lambda im: [(tuple(sj["planet"]["placed"]["centre_on_canvas_px"]), "The planet: 16 frames of 1/40 s at ISO 800", 0, 8), (tuple(mp["Iapetus"]), "Everything else: 2 frames of 2 s at ISO 6400", -3, -7)],
        tech=[("EXPOSURES", "Planet: 1/40 s at ISO 800. Moons: 2 s at ISO 6400, 640 times the planet's exposure"), ("FRAMES", "Planet: 61 taken, 48 usable, the 16 sharpest kept. Moons: 2 clear frames; the other ten were behind cloud"),
              ("PLANET STACK", "Each RAW colour plane placed at its own sub-pixel offset on a grid 3 x finer than the sensor (0.129 arcsec). No demosaic. Colours re-registered for the air's prism effect. Shown here at the sensor's scale, not enlarged"),
              ("RESTORATION", "Blur measured from Titan in the same frames: 2.7 x 2.2 arcsec (5.0 x 4.0 before the refocus). Richardson-Lucy, 8 rounds; stopped where a model planet starts to grow a false rim"),
              ("COMPOSITE", "The planet is set into the moon field where the 2 s frames are blown out. The planet's glare is subtracted ring by ring. Moons are lifted about 640 x relative to the planet"),
              ("SAMPLING", "Field: 0.388 arcsec per pixel, north up (9 catalogue stars, 0.6 arcsec)"), ("WHEN", "4 October 2026, after midnight, over 19 minutes. 52 degrees up, at opposition"),
              ("MOON NAMES", "No ephemeris used: each point keeps its place beside Saturn while the stars slide past, and sits at its orbit's reach. Worth a check"),
              ("NOT SEEN", "The Cassini division: no dip along the ring line in the plain stack or the restored one"), OPTICS, CAMERA, MOUNT])
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
    for i, l in enumerate(credit): ops.append((pad, y, l, fC, SOFT if i == 0 else DIM)); y += 1.6 * u
    return int(math.ceil(y + pad * 0.7)), ops, rules

def render(name, t, kind, caption=True):
    rgb = cv2.cvtColor(cv2.imread(t["src"], cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB); H, W = rgb.shape[:2]; u = W / 100.0; pad = 3.2 * u
    if kind == "story":
        band, ops, rules = band_layout(W, u, t["title"], t["sub"], t["what"], t["facts"], len(t["facts"]), [GEAR, t["frames"][0].upper() + t["frames"][1:] + ".  " + TRUE], False)
    else:
        band, ops, rules = band_layout(W, u, "How it was made: " + re.sub("^The ", "the ", t["title"].split(":")[0]), t["how_sub"][0].upper() + t["how_sub"][1:], None, t["tech"], 3, [GEAR, MADE], True)
    if not caption: band, ops, rules = 0, [], []
    canvas = Image.new("RGB", (W, H + band), BAND); canvas.paste(Image.fromarray(rgb), (0, 0)); d = ImageDraw.Draw(canvas, "RGBA")
    fN, fC = font(1.5 * u, "medium"), font(0.98 * u); lw = max(2, int(round(u / 9)))
    def words(tx, ty, text, f=fN, fill=INK):
        tw = d.textlength(text, font=f); th = f.size * 1.25
        d.rounded_rectangle([tx - 0.45 * u, ty - 0.1 * u, tx + tw + 0.45 * u, ty + th + 0.1 * u], radius=0.35 * u, fill=(0, 0, 0, 150 if kind == "story" else 235)); d.text((tx, ty), text, font=f, fill=fill)
    def label(pt, text, dx, dy, leader=True):
        tw = d.textlength(text, font=fN); th = fN.size * 1.25
        if dx == 0 and dy == 0: return words(pt[0] - tw / 2, pt[1] - th / 2, text)
        ax, ay = pt[0] + dx * u, pt[1] + dy * u
        tx = ax + 0.4 * u if dx > 0 else (ax - tw - 0.4 * u if dx < 0 else ax - tw / 2); ty = ay - th / 2 if dx != 0 else (ay - th - 0.3 * u if dy < 0 else ay + 0.3 * u)
        if leader:
            L = math.hypot(dx, dy) * u; g0 = min(0.9 * u, L * 0.25)
            p0 = (pt[0] + dx * u * g0 / L, pt[1] + dy * u * g0 / L); p1 = (ax, ay)
            d.line([p0, p1], fill=(0, 0, 0, 120), width=lw + 2); d.line([p0, p1], fill=(238, 238, 234, 240), width=lw)
        words(tx, ty, text)
    if kind == "story":
        for pt, text, dx, dy in t["labels"](rgb):
            if 0 <= pt[0] < W and 0 <= pt[1] < H: label(pt, text, dx, dy, leader=text not in t.get("plain", ()))
    elif t.get("how_labels"):
        for pt, text, dx, dy in t["how_labels"](rgb): label(pt, text, dx, dy)
    elif t.get("outlines"):
        tints = [(120, 200, 255), (255, 200, 120), (160, 255, 170), (255, 160, 200), (220, 200, 255), (255, 240, 140), (140, 240, 230), (255, 180, 150), (200, 230, 150)]
        frames = t["outlines"]()
        for i, (poly, text) in enumerate(frames):
            col = tints[i % len(tints)]; pts = [tuple(p) for p in poly] + [tuple(poly[0])]
            d.line(pts, fill=(0, 0, 0, 110), width=lw + 3); d.line(pts, fill=col + (235,), width=lw + 1)
        for i, (poly, text) in enumerate(frames):
            col = tints[i % len(tints)]
            cx = sum(p[0] for p in poly) / 4; cy = sum(p[1] for p in poly) / 4; cx = min(max(cx, 8 * u), W - 8 * u); cy = min(max(cy, 3 * u), H - 3 * u)
            tw = d.textlength(text, font=fN); words(cx - tw / 2, cy - fN.size * 0.6, text, fill=col)
    bl, btxt = t["bar"]; ang = bl * t["scale"]; angtxt = "%.1f arcminutes" % (ang / 60) if ang >= 90 else "%.0f arcseconds" % ang
    if kind == "how": bl = round(ang / 60 if ang >= 90 else ang) * (60 if ang >= 90 else 1) / t["scale"]; ang = bl * t["scale"]; btxt = "%.0f arcminutes" % (ang / 60) if ang >= 90 else "%.0f arcseconds" % ang; angtxt = "%.3g arcsec per pixel" % t["scale"]
    bx, by = pad, H - pad
    d.line([(bx, by), (bx + bl, by)], fill=(0, 0, 0, 120), width=lw + 3); d.line([(bx, by), (bx + bl, by)], fill=INK, width=lw + 1)
    for xx in (bx, bx + bl): d.line([(xx, by - 0.5 * u), (xx, by + 0.5 * u)], fill=INK, width=lw + 1)
    tw = d.textlength(btxt, font=fN); words(max(bx, bx + bl / 2 - tw / 2), by - 3.3 * u, btxt)
    tw = d.textlength(angtxt, font=fC); words(max(bx, bx + bl / 2 - tw / 2), by + 0.7 * u, angtxt, f=fC, fill=SOFT)
    if t.get("compass", True):
        a = math.radians(t["north"]); cx, cy, r = W - pad - 4 * u, H - pad - 1.5 * u, 4.2 * u
        nx, ny = -math.sin(a), -math.cos(a); ex, ey = -math.cos(a), math.sin(a)            # north is `north` deg counter-clockwise of up; east is to its left
        for (vx, vy, txt, k) in ((nx, ny, "N", 1.0), (ex, ey, "E", 0.62)):
            tip = (cx + vx * r * k, cy + vy * r * k); d.line([(cx, cy), tip], fill=(0, 0, 0, 120), width=lw + 2); d.line([(cx, cy), tip], fill=INK, width=lw)
            lx, ly = cx + vx * (r * k + 1.4 * u), cy + vy * (r * k + 1.4 * u); d.text((lx - d.textlength(txt, font=fC) / 2, ly - 0.7 * u), txt, font=fC, fill=INK)
    if not caption: return canvas
    d.rectangle([0, H, W, H + band], fill=BAND + (255,))
    for x0, y0, x1 in rules: d.line([(x0, H + y0), (x1, H + y0)], fill=RULE, width=max(1, int(u / 14)))
    for x, y, text, f, fill in ops: d.text((x, H + y), text, font=f, fill=fill)
    out = "share/%s-%s.jpg" % (name, "annotated" if kind == "story" else "how"); canvas.save(out, quality=93, subsampling=0, optimize=True); return out

ORDER = ["orion-nebula", "moon", "pleiades", "andromeda-core", "saturn", "orion-nebula-wide", "andromeda-mosaic", "m15", "blue-snowball"]
THUMB = {"saturn": (1168, 435, 1200, 800)}       # the part of a picture its small version shows: x, y, width, height
CARD = {"saturn": (1168, 520, 1200, 630)}        # the part a link preview shows, at the picture's own pixels (never enlarged)
CARD_TEXT = {"pleiades": "top", "andromeda-core": "top"}   # where a link preview's words go when the foot of the picture is the busy part

def site(out):
    """The same set for the website: pictures at full size and 1600 wide, small ones for the grid, and the words as data
    (objects.json) so the page sets them as text. Pictures carry no caption band here."""
    os.makedirs(out + "/images", exist_ok=True); objects = []
    def put(img, stem, q):
        img.save("%s/images/%s.jpg" % (out, stem), quality=q, subsampling=0, optimize=True)
        if img.width > 1600: img.resize((1600, round(img.height * 1600 / img.width)), Image.LANCZOS).save("%s/images/%s-1600.jpg" % (out, stem), quality=88, optimize=True)
    for name in ORDER:
        t = T[name]; clean = Image.fromarray(cv2.cvtColor(cv2.imread(t["src"], cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)); put(clean, name, 93)
        x, y, w, h = THUMB.get(name, (0, 0, clean.width, clean.height)); small = clean.crop((x, y, x + w, y + h)); small.thumbnail((900, 900), Image.LANCZOS)
        small.save("%s/images/%s-thumb.jpg" % (out, name), quality=86, optimize=True)
        put(render(name, t, "story", caption=False), name + "-labels", 90)
        frames = bool(t.get("outlines") or t.get("how_labels")); card = None
        if name in CARD:
            x, y, w, h = CARD[name]; card = name + "-card.jpg"; clean.crop((x, y, x + w, y + h)).save("%s/images/%s" % (out, card), quality=92, subsampling=0, optimize=True)
        if frames: put(render(name, t, "how", caption=False), name + "-frames", 90)
        objects.append(dict(slug=name, title=t["title"], subtitle=t["sub"], what=t["what"], facts=[[k.capitalize(), sent(v)] for k, v in t["facts"]],
                            made=sent(t["frames"]), how=sent(t["how_sub"]), specs=[[k.capitalize(), sent(v)] for k, v in t["tech"]],
                            width=clean.width, height=clean.height, thumb=[small.width, small.height], arcsec_per_px=t["scale"], frames=frames, card=card, card_text=CARD_TEXT.get(name, "bottom")))
        print("site: %-18s %d x %d%s" % (name, clean.width, clean.height, ", with frames" if frames else ""))
    json.dump(dict(credit=GEAR, made_with=MADE, objects=objects), open(out + "/objects.json", "w"), indent=1, ensure_ascii=False)

T = targets()
if len(sys.argv) > 2 and sys.argv[1] == "--site": site(sys.argv[2]); sys.exit(0)
for name in (sys.argv[1:] or list(T)):
    t = T[name]; rgb = cv2.cvtColor(cv2.imread(t["src"], cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    Image.fromarray(rgb).save("share/%s.jpg" % name, quality=93, subsampling=0, optimize=True)
    a, b = render(name, t, "story"), render(name, t, "how")
    print("%-20s %5d x %-5d  clean %4.1f MB  annotated %4.1f MB  how %4.1f MB" % (name, rgb.shape[1], rgb.shape[0], os.path.getsize("share/%s.jpg" % name) / 1e6, os.path.getsize(a) / 1e6, os.path.getsize(b) / 1e6))
