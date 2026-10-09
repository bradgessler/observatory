"""Which points near Saturn are stars? Catalogue stars (the plate solver's 2MASS index) are placed where they would fall around
Saturn and matched to the points found. A point with no catalogue star under it is not a star.

whois2.py is whois.py with two changes, made for the restack of 2026-10-04:
  1. The plate solver's own scale is used for the catalogue (its 960 px copy is 6.25 sensor px per px: 0.3886 arcsec per sensor
     px). whois.py converted with 0.3955, 1.8 percent large: 10 arcsec at the edge of this field, more than the match allowed.
  2. The picture's turn on the sky is searched along with the slide, then turn, scale and slide are fitted to the matched stars
     (least squares) and the match repeated. The field turns about 0.056 deg a minute tonight (the mount's axis is off the pole),
     so the angle from the 05:00-05:10 plate solves is not the angle of later frames.
The fitted turn and scale are written out: they are the picture's orientation and scale at the time of these frames.

Usage: whois3.py   (in a folder with plan.json and moonfield.json; writes whois.json)

whois3.py is whois2.py for the sharp run of 2026-10-04 (moon frames 08:46:49 and 08:47:51 UTC), with these changes:
  1. plan.json is made by plan.py from the plate solves of the moon frames themselves, so the search for the turn starts at their
     own angle (searched -1.5 to +1.5 deg) and the words printed say so.
  2. The brightest points are no longer left out by flux (the points are sharper now, so the same light is a larger number here):
     a point is left out of the fit when it has a blown-out pixel (peak at 0.9 of full scale or more) or is nearer than 100 arcsec.
  3. A point within 100 arcsec that lines up with a star is still reported as a star; one that does not is left for inner.py, which
     says which moon it is from the shape of its orbit."""
import json, subprocess, glob, os, numpy as np
p = json.load(open("plan.json")); A0 = np.array(p["A"]); s = 1 / np.hypot(*A0[0]); alpha0 = float(np.arctan2(A0[0, 1], -A0[0, 0]))     # copy px per arcsec (E, N) -> (x, y)
sat_ra, sat_dec = p["sat"]; SOLVER = s / 6.25                       # arcsec per sensor px, from the plate solves
pts = json.load(open("moonfield.json"))["points"]; R = 760; HALF = 0.791                               # moons.py's arcsec per half-size px (0.3955 x 2)
idx = os.path.expanduser("~/.observatory/astrometry"); stars = {}
for series in ("4204", "4205"):
    for f in sorted(glob.glob(idx + "/index-%s-*.fits" % series)):
        for line in subprocess.run(["query-starkd", "-r", str(sat_ra), "-d", str(sat_dec), "-R", "0.3", "-T", f], capture_output=True, text=True).stdout.splitlines():
            q = line.split(",")
            if len(q) == 3 and not line.startswith("#"):
                try: stars[(round(float(q[0]), 4), round(float(q[1]), 4))] = float(q[2])
                except ValueError: pass
EN = np.array([[(ra - sat_ra) * np.cos(np.radians(sat_dec)) * 3600, (dec - sat_dec) * 3600, j] for (ra, dec), j in stars.items()])
P = np.array([[q["x"] - R, q["y"] - R] for q in pts], float)        # half-size px from the planet
FIELD = np.load("moonfield-glare.npy")[..., 1]
far = np.array([q["arcsec"] > 100 and FIELD[int(q["y"]) - 3:int(q["y"]) + 4, int(q["x"]) - 3:int(q["x"]) + 4].max() < 0.9 for q in pts])  # nearer in is ring glare and moons; the blown-out ones have no good middle
def place(alpha, per_px):                                            # catalogue -> half-size px about the planet
    A = np.array([[-np.cos(alpha), np.sin(alpha)], [-np.sin(alpha), -np.cos(alpha)]]); return (EN[:, :2] @ A.T) / (2 * per_px)
best = None
for delta in np.arange(-1.5, 1.51, 0.1):
    cat = place(alpha0 + np.radians(delta), SOLVER)
    for sx in np.arange(-120, 121, 2.0):
        dx = P[far][:, None, 0] - (cat[None, :, 0] + sx)
        for sy in np.arange(-120, 121, 2.0):
            d = np.hypot(dx, P[far][:, None, 1] - (cat[None, :, 1] + sy)).min(1); m = d < 4; n = int(m.sum()); md = float(d[m].mean()) if n else 1e9
            if best is None or (n, -md) > (best[0], -best[1]): best = (n, md, delta, sx, sy)
n, md, delta, sx, sy = best; alpha, per_px, sh = alpha0 + np.radians(delta), SOLVER, np.array([sx, sy], float)
print("%d catalogue stars within 18 arcmin (J %.1f to %.1f). Search: turned %+.1f deg from the plate solves of these frames, slid (%.0f, %.0f) arcsec, %d of %d points line up" % (len(EN), EN[:, 2].min(), EN[:, 2].max(), delta, sx * HALF, sy * HALF, n, int(far.sum())))
for tol in (5.0, 4.0, 4.0, 4.0):                                     # refine: turn, scale and slide by least squares on the matched pairs
    cat = place(alpha, per_px) + sh; d = np.hypot(P[:, None, 0] - cat[None, :, 0], P[:, None, 1] - cat[None, :, 1]); j = d.argmin(1); m = (d.min(1) < tol) & far
    E = EN[j[m], :2]; X = P[m]; M = np.zeros((2 * int(m.sum()), 4)); M[0::2] = np.c_[-E[:, 0], E[:, 1], np.ones(len(E)), np.zeros(len(E))]; M[1::2] = np.c_[-E[:, 1], -E[:, 0], np.zeros(len(E)), np.ones(len(E))]
    (a, b, tx, ty), *_ = np.linalg.lstsq(M, X.ravel(), rcond=None); alpha = float(np.arctan2(b, a)); per_px = float(1 / (2 * np.hypot(a, b))); sh = np.array([tx, ty])
cat = place(alpha, per_px) + sh; d = np.hypot(P[:, None, 0] - cat[None, :, 0], P[:, None, 1] - cat[None, :, 1]); k = d.argmin(1); dm = d.min(1) * 2 * per_px; star = dm < 3.0
rms = float(np.sqrt((dm[star & far] ** 2).mean()))
print("Fitted to %d stars (rms %.2f arcsec): up is %.2f deg east of north (the plate solves of these frames said %.2f); %.4f arcsec per sensor px (plate solves %.4f; the scripts assume 0.3955)" % (int((star & far).sum()), rms, np.degrees(alpha), np.degrees(alpha0), per_px, SOLVER))
out = []
for q, kk, dd, st in zip(pts, k, dm, star):
    q["star"] = bool(st); q["j_mag"] = float(EN[kk, 2]) if st else None; q["true_arcsec"] = round(q["arcsec"] / 0.3955 * per_px, 1); out.append(q)
    print("  %6.1f arcsec (%6.1f at the fitted scale) at %7.1f deg  flux %8.3f  %s" % (q["arcsec"], q["true_arcsec"], q["angle"], q["flux"], ("star, J %.1f (%.1f arcsec off)" % (EN[kk, 2], dd)) if st else "NOT in the catalogue (nearest star %.0f arcsec off, J %.1f)" % (dd, EN[kk, 2])))
json.dump(dict(points=out, shift_px=[float(sh[0]), float(sh[1])], up_east_of_north_deg=round(float(np.degrees(alpha)), 2), plate_solves_up_east_of_north_deg=round(float(np.degrees(alpha0)), 2), arcsec_per_sensor_px=round(per_px, 4),
               plate_solves_arcsec_per_sensor_px=round(float(SOLVER), 4), stars_matched=int((star & far).sum()), match_rms_arcsec=round(rms, 2), ring_line_deg=None), open("whois.json", "w"), indent=1)
