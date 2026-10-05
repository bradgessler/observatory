"""Which way is lunar north? Measured on the stack from craters whose places on the Moon are known.

Each crater's centre was read off the first, sensor-way-up half-size stack by eye (to about 3
pixels) and is kept here in the reference frame's own pixels (stack pixel + the crop's corner), so
the reading holds whatever the crop. A crater at
selenographic longitude L, latitude B is seen, on a Moon whose centre faces us at (l0, b0) (the
libration), at
    east  = cos B sin(L - l0)                       (lunar east: toward Mare Crisium, right when north is up)
    north = sin B cos b0 - cos B sin b0 cos(L - l0)
times the Moon's radius from its centre; the limb gives centre and radius (measure.py). Three
numbers are fitted to all the craters at once: the angle the picture is turned by, l0 and b0.
The same fit with the picture mirrored is run too. A mirrored Moon fits the craters just as well
only if we were looking at its far side (l0 near 180 degrees): the fit that comes out with a
libration of a few degrees is the true one, and says whether the picture is mirrored.
As a second opinion, the line through the two cusps (the horns of the lit part): it is
square to the direction of the Sun, and the Sun stands within 1.6 degrees of the Moon's equator,
so the cusp line lies within a few degrees of the Moon's axis.

Usage: orient.py stack.npz measured.json crop.json out.json
"""
import sys, json, numpy as np, cv2
from scipy.optimize import least_squares
# name, longitude east (deg), latitude north (deg), x, y: read on the stack whose crop corner was READ_AT
READ_AT = (1389, -880)
CRATERS = [("Copernicus", -20.08, 9.62, 803, 1129), ("Kepler", -38.01, 8.12, 544, 1350), ("Aristarchus", -47.49, 23.73, 313, 1122),
           ("Euler", -29.18, 23.26, 542, 969), ("Lambert", -20.99, 25.77, 645, 840), ("Pytheas", -20.59, 20.55, 692, 933),
           ("Timocharis", -13.10, 26.72, 761, 742), ("Reinhold", -22.86, 3.28, 823, 1285), ("Lansberg", -26.63, -0.31, 804, 1394),
           ("Bullialdus", -22.26, -20.75, 1143, 1704), ("Gassendi", -39.96, -17.55, 843, 1831), ("Tycho", -11.22, -43.30, 1609, 1920),
           ("Helicon", -23.12, 40.42, 542, 602), ("Le Verrier", -20.61, 40.33, 574, 581), ("Eratosthenes", -11.32, 14.47, 900, 944),
           ("Pitatus", -13.54, -29.88, 1402, 1758), ("Schickard", -55.31, -44.38, 1168, 2238)]
m = json.load(open(sys.argv[2])); cx, cy = m["moon_centre_px"]; R = m["moon_radius_px"]
crop = json.load(open(sys.argv[3])); off = (READ_AT[0] - crop["x0"], READ_AT[1] - crop["y0"])
lon = np.radians([c[1] for c in CRATERS]); lat = np.radians([c[2] for c in CRATERS]); P = np.array([[c[3] + off[0], c[4] + off[1]] for c in CRATERS], float)


def model(p, mirror):
    th, l0, b0 = p
    e = np.cos(lat) * np.sin(lon - l0); n = np.sin(lat) * np.cos(b0) - np.cos(lat) * np.sin(b0) * np.cos(lon - l0)
    if mirror:
        e = -e
    # the north-up picture (x = east, y = -north) turned anticlockwise on the screen by th
    x = e * np.cos(th) - n * np.sin(th); y = -e * np.sin(th) - n * np.cos(th)
    return np.c_[cx + R * x, cy + R * y]


out = {}
for mirror in (False, True):
    best = None
    for th0 in np.radians(np.arange(0, 360, 30)):
        r = least_squares(lambda p: (model(p, mirror) - P).ravel(), [th0, 0, 0])
        if best is None or r.cost < best.cost:
            best = r
    res = model(best.x, mirror) - P; rms = float(np.sqrt((res ** 2).sum(1).mean()))
    J = best.jac; cov = np.linalg.inv(J.T @ J) * (res ** 2).sum() / (res.size - 3)
    out["mirrored" if mirror else "as it is"] = dict(turned_anticlockwise_deg=float(np.degrees(best.x[0]) % 360), plus_minus_deg=float(np.degrees(np.sqrt(cov[0, 0]))),
                                                    libration_longitude_deg=float(np.degrees(best.x[1])), libration_latitude_deg=float(np.degrees(best.x[2])), rms_px=rms,
                                                    residuals_px={c[0]: [round(float(v), 1) for v in r_] for c, r_ in zip(CRATERS, res)})
# -- the cusps -------------------------------------------------------------------------------------
img = np.load(sys.argv[1])["img"]; g = img[:, :, 1]
ang = np.radians(np.arange(0, 360, 0.05)); lit = []
for a in ang:
    xs = (cx + (R - np.arange(3, 14)) * np.cos(a)).astype(np.float32)[None]; ys = (cy + (R - np.arange(3, 14)) * np.sin(a)).astype(np.float32)[None]
    lit.append(float(cv2.remap(g, xs, ys, cv2.INTER_LINEAR, borderValue=0).mean()))
lit = np.array(lit) > 0.25 * np.percentile(lit, 95)
# the longest run of lit limb, wrapping round
d = np.diff(np.r_[lit[-1], lit].astype(int)); starts = np.where(d == 1)[0]; ends = np.where(d == -1)[0]
runs = [(s, e if e > s else e + len(lit)) for s in starts for e in [min([x for x in ends if x > s], default=ends[0] + len(lit))]]
s, e = max(runs, key=lambda r: r[1] - r[0]); a0, a1 = np.degrees(ang[s % len(lit)]), np.degrees(ang[e % len(lit)])
mid = np.radians(a0 + ((a1 - a0) % 360) / 2)       # toward the Sun, on the screen (x right, y down)
# north-up picture turned anticlockwise by th: the Sun (lunar west, for a waning Moon) points to screen angle 180 - th
out["cusps"] = dict(lit_limb_from_deg=float(a0), to_deg=float(a1), lit_arc_deg=float((a1 - a0) % 360),
                    turned_anticlockwise_deg_if_sun_due_west=float((180 - np.degrees(mid)) % 360))
out["moon"] = dict(centre_px=[cx, cy], radius_px=R)
true = min(("as it is", "mirrored"), key=lambda k: abs((out[k]["libration_longitude_deg"] + 180) % 360 - 180))
out["verdict"] = dict(picture_is=true, turned_anticlockwise_deg=out[true]["turned_anticlockwise_deg"], plus_minus_deg=out[true]["plus_minus_deg"],
                      craters=len(CRATERS), rms_px=out[true]["rms_px"], libration_deg=[out[true]["libration_longitude_deg"], out[true]["libration_latitude_deg"]],
                      cusp_line_says_deg=out["cusps"]["turned_anticlockwise_deg_if_sun_due_west"],
                      note="turn the picture clockwise by this much and lunar north is up, lunar east (Mare Crisium's side) right")
json.dump(out, open(sys.argv[4], "w"), indent=1); print(json.dumps(out["verdict"], indent=1))
