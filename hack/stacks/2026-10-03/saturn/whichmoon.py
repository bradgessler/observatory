"""Which moon is which? No ephemeris is used (there is none on this machine): the moons are named from what the pictures themselves show.

A point is a moon when it is not a catalogue star (whois3.py) and it keeps its place beside Saturn while the stars slide past (Saturn
moved 43 arcsec among the stars between the earlier run at 05:14 and this one, and 4 arcsec between this field and the one taken 19
minutes later).

Which moon: the regular moons move in the plane of the rings, so each lies on an ellipse the shape of the rings,
(x/a)^2 + (y/(a sin B))^2 = 1, with x along the ring line and y across it, and a the size of its orbit (known: Mimas 185539, Enceladus
237948, Tethys 294619, Dione 377396, Rhea 527108, Titan 1221870, Hyperion 1481010 km). Seen this nearly edge-on, y is small and has to be
measured to a fraction of an arcsec, and the middle of the blown-out planet is only known to an arcsec or so; so for the points near the
planet every way of giving them different names is tried, each time letting the centre (2 numbers) and the ring line's angle (1) settle,
and the misfit across the ring line is recorded, together with how far each point's brightness is from what that moon should have
(about magnitude 9.7 Rhea, 10.2 Tethys, 10.4 Dione, 11.7 Enceladus, 12.9 Mimas at opposition). The naming with the smallest misfit wins,
and how far ahead of the next it is, is recorded. The distance to Saturn (arcsec per km) comes from the globe's own radius in the planet
stack (psfmodel.py), not from a table.

Last check: moons on the near half of their orbits all move one way along the ring line and those on the far half the other, so the side
of the ring line a moon is on (the sign of y) must agree with the way it moved between the two fields, the same rule for all.

Iapetus does not move in the ring plane (its orbit is tilted 15 deg to it): it is named as the point that is not a star, lies beyond
Titan's reach and within Iapetus's, and has kept its place beside Saturn since the earlier run.

Usage: whichmoon.py <field stem> <whois.json> <plan.json> <later field stem> <its whois.json> <ring line deg in the field> <globe radius arcsec> <earlier whois.json> <earlier plan.json> <out names.json>"""
import sys, json, itertools
import numpy as np, cv2
from scipy.optimize import curve_fit, least_squares
A, WHO, PLAN, B, WHOB, PHI, RE, WHO0, PLAN0, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], float(sys.argv[6]), float(sys.argv[7]), sys.argv[8], sys.argv[9], sys.argv[10]
SINB = 0.1297; R = 760; KM = dict(Mimas=185539, Enceladus=237948, Tethys=294619, Dione=377396, Rhea=527108, Titan=1221870, Hyperion=1481010, Iapetus=3560820); ECC = dict(Titan=0.029, Hyperion=0.105, Iapetus=0.028)
PER = dict(Mimas=0.942, Enceladus=1.370, Tethys=1.888, Dione=2.737, Rhea=4.518, Titan=15.945, Hyperion=21.277, Iapetus=79.33); MAG = dict(Mimas=12.9, Enceladus=11.7, Tethys=10.2, Dione=10.4, Rhea=9.7, Titan=8.4, Hyperion=14.2, Iapetus=10.6)
PER_KM = RE / 60268.0                                                        # arcsec per km: the globe's equatorial radius is 60268 km
def f3(X, a, x0, y0, s1, s2, th, c):
    u = (X[0] - x0) * np.cos(th) + (X[1] - y0) * np.sin(th); v = -(X[0] - x0) * np.sin(th) + (X[1] - y0) * np.cos(th)
    return a * np.exp(-u * u / (2 * s1 * s1) - v * v / (2 * s2 * s2)) + c
def load(stem, who):
    W = json.load(open(who)); rec = json.load(open(stem + ".json")); g = np.load(stem + ".npy")[..., 1]; sx, sy = rec["glare_by_symmetry"]["centre_from_blob_middle_half_px"]
    pp = W["arcsec_per_sensor_px"]; al = np.radians(W["up_east_of_north_deg"]); pts = []
    for q in W["points"]:
        if q["star"]: continue
        x, y = q["x"], q["y"]; fit = None
        if q["snr"] >= 30:                                                    # bright enough for an elliptical Gaussian (green); the faint keep the middle of their patch
            ix, iy = int(round(x)), int(round(y)); w = cv2.GaussianBlur(g, (0, 0), 1.5)[iy - 6:iy + 7, ix - 6:ix + 7]; py, px = np.unravel_index(np.argmax(w), w.shape); ix, iy = ix - 6 + px, iy - 6 + py
            r = 7; p = g[iy - r:iy + r + 1, ix - r:ix + r + 1]; gy, gx = np.mgrid[-r:r + 1, -r:r + 1]; ok = p != 0
            try:
                (a, x0, y0, s1, s2, th, c), cov = curve_fit(f3, (gx[ok], gy[ok]), p[ok], p0=(p.max(), 0, 0, 2.0, 1.6, 1.5, 0), maxfev=20000); s1, s2 = sorted((abs(s1), abs(s2)), reverse=True)
                if np.hypot(x0, y0) < 4 and s1 < 5: x, y = ix + x0, iy + y0; fit = dict(flux=float(2 * np.pi * a * s1 * s2), fwhm=[round(2.355 * s1 * 2 * pp, 2), round(2.355 * s2 * 2 * pp, 2)])
            except Exception: pass
        dx, dy = x - (R + sx), y - (R + sy)                                    # from the centre of symmetry of the glare, half px
        pts.append(dict(px=float(x), py=float(y), dx=float(dx), dy=float(dy), arcsec=float(np.hypot(dx, dy) * 2 * pp), box_flux=q["flux"], snr=q["snr"], fit=fit,
                        E=float((-np.cos(al) * dx - np.sin(al) * dy) * 2 * pp), N=float((np.sin(al) * dx - np.cos(al) * dy) * 2 * pp)))
    return pts, W, pp
def ring(p, phi, pp, c=(0.0, 0.0), dphi=0.0):
    ph = np.radians(phi) + dphi; x = (p["dx"] * np.cos(ph) + p["dy"] * np.sin(ph)) * 2 * pp - c[0]; y = (-p["dx"] * np.sin(ph) + p["dy"] * np.cos(ph)) * 2 * pp - c[1]
    return (x * np.cos(dphi) + y * np.sin(dphi), -x * np.sin(dphi) + y * np.cos(dphi)) if False else (x, y)
pa, Wa, pp = load(A, WHO); pb, Wb, ppb = load(B, WHOB); TURN = Wb["up_east_of_north_deg"] - Wa["up_east_of_north_deg"]
# the later field, matched by place beside Saturn (sky offsets E, N: the stars' own turn is taken out by each field's own star fit)
for p in pa:
    m = min(pb, key=lambda q: np.hypot(q["E"] - p["E"], q["N"] - p["N"]), default=None); p["later"] = m if m is not None and np.hypot(m["E"] - p["E"], m["N"] - p["N"]) < 4.0 else None
# the earlier run: sky offsets of its points that were not stars
W0 = json.load(open(WHO0)); al0 = np.radians(W0["up_east_of_north_deg"]); pp0 = W0["arcsec_per_sensor_px"]
p0 = [dict(E=float((-np.cos(al0) * (q["x"] - R) - np.sin(al0) * (q["y"] - R)) * 2 * pp0), N=float((np.sin(al0) * (q["x"] - R) - np.cos(al0) * (q["y"] - R)) * 2 * pp0), flux=q["flux"]) for q in W0["points"] if not q["star"] and q.get("true_arcsec", 0) > 60]
sat = lambda plan, W: (lambda p, a, s, sh: (p["sat"][0] + (np.linalg.solve(np.array([[-np.cos(a), np.sin(a)], [-np.sin(a), -np.cos(a)]]), -sh * 2 * s)[0]) / 3600 / np.cos(np.radians(p["sat"][1])),
                                           p["sat"][1] + (np.linalg.solve(np.array([[-np.cos(a), np.sin(a)], [-np.sin(a), -np.cos(a)]]), -sh * 2 * s)[1]) / 3600))(json.load(open(plan)), np.radians(W["up_east_of_north_deg"]), W["arcsec_per_sensor_px"], np.array(W["shift_px"]))
s_now = sat(PLAN, Wa); s_then = sat(PLAN0, W0); cd = np.cos(np.radians(s_now[1])); moved_sat = [(s_now[0] - s_then[0]) * 3600 * cd, (s_now[1] - s_then[1]) * 3600]
print("Saturn among the stars: RA %.5f Dec %.5f now, %.5f %.5f in the earlier run: moved %.1f arcsec east, %.1f north" % (*s_now, *s_then, *moved_sat))
blown = np.load(A + "-blown.npy"); dist = cv2.distanceTransform((~blown).astype(np.uint8), cv2.DIST_L2, 5)
cand = [p for p in pa if p["later"] is not None or p["snr"] >= 8]              # seen again 19 minutes later in the same place beside Saturn, or clear enough on its own
near = [p for p in cand if p["arcsec"] < 70 and p["fit"] and p["later"] is not None and p["later"]["fit"]]     # the points near the planet: round, bright, and in the same place beside Saturn 19 minutes later
ref = [p for p in cand if p["fit"] and 70 <= p["arcsec"] < 100]               # Rhea, by its reach (85 arcsec) and brightness: the only bright point between 70 and 100 arcsec that is not a star
assert len(ref) == 1, "expected one bright point at Rhea's reach"
rhea = ref[0]; f_rhea = rhea["fit"]["flux"]
mag = lambda p: MAG["Rhea"] - 2.5 * np.log10((p["fit"]["flux"] if p["fit"] else p["box_flux"] / rhea["box_flux"] * f_rhea) / f_rhea)
print("%d points near the planet kept their place beside Saturn 19 minutes later: %s arcsec out, magnitudes about %s (Rhea 9.7)" % (len(near), ", ".join("%.1f" % p["arcsec"] for p in near), ", ".join("%.1f" % mag(p) for p in near)))
def misfit(names, pts):
    def res(q):
        out = []
        for p, n in zip(pts, names):
            x, y = ring(p, PHI + np.degrees(q[2]), pp, (q[0], q[1])); a = KM[n] * PER_KM
            out.append(abs(y) - SINB * np.sqrt(a * a - x * x) if abs(x) < a else (abs(x) - a) * 3 + abs(y))
        return out
    r = least_squares(res, [0.0, 0.0, 0.0]); return np.array(res(r.x)), r.x
trials = []
for names in itertools.permutations(["Mimas", "Enceladus", "Tethys", "Dione"], len(near)):
    r, q = misfit(list(names) + ["Rhea"], near + [rhea]); dm = np.array([mag(p) - MAG[n] for p, n in zip(near, names)])
    trials.append(dict(names=list(names), across_rms_arcsec=float(np.sqrt((r ** 2).mean())), brightness_rms_mag=float(np.sqrt((dm ** 2).mean())), centre_moved_arcsec=[round(float(q[0]), 2), round(float(q[1]), 2)], ring_line_moved_deg=round(float(np.degrees(q[2])), 2),
                       score=float(np.sqrt((r ** 2).mean()) / 0.5 + np.sqrt((dm ** 2).mean()) / 0.4 + np.hypot(q[0], q[1]) / 2.0)))
trials.sort(key=lambda t: t["score"]); best = trials[0]; q = (best["centre_moved_arcsec"][0], best["centre_moved_arcsec"][1], np.radians(best["ring_line_moved_deg"]))
print("namings tried for them (misfit across the ring line, misfit in brightness, how far the centre had to move):")
for t in trials[:6]: print("   %-30s %.2f arcsec  %.2f mag  centre %.1f arcsec  ring line %+.2f deg   score %.2f" % (", ".join(t["names"]), t["across_rms_arcsec"], t["brightness_rms_mag"], np.hypot(*t["centre_moved_arcsec"]), t["ring_line_moved_deg"], t["score"]))
named = {}
for p, n in zip(near, best["names"]): named[n] = p
named["Rhea"] = rhea
# the outer moons in the ring plane: Titan and Hyperion, each by the size of its orbit (their orbits are out of round by 3 and 10 percent)
for p in cand:
    if p in named.values() or p["arcsec"] < 100: continue
    x, y = ring(p, PHI + np.degrees(q[2]), pp, (q[0], q[1])); a = float(np.hypot(x, y / SINB)); p["orbit_arcsec"] = a
    for n in ("Titan", "Hyperion"):
        if abs(a / (KM[n] * PER_KM) - 1) < ECC[n] + 0.04 and abs(mag(p) - MAG[n]) < 1.5 and n not in named: named[n] = p
# Iapetus: not a star, beyond Titan's reach, within its own, and in the same place beside Saturn as a point of the earlier run
for p in cand:
    if p in named.values(): continue
    if KM["Titan"] * PER_KM * 1.1 < p["arcsec"] < KM["Iapetus"] * PER_KM * (1 + ECC["Iapetus"]) + 6 and any(np.hypot(o["E"] - p["E"], o["N"] - p["N"]) < 12 for o in p0) and "Iapetus" not in named: named["Iapetus"] = p
out = {}; signs = []
for n, p in sorted(named.items(), key=lambda kv: kv[1]["arcsec"]):
    x, y = ring(p, PHI + np.degrees(q[2]), pp, (q[0], q[1])); a = KM[n] * PER_KM; e = dict(arcsec_from_saturn=round(p["arcsec"], 1), east_arcsec=round(p["E"], 1), north_arcsec=round(p["N"], 1), field_half_px=[round(p["px"], 2), round(p["py"], 2)], along_ring_arcsec=round(float(x), 2), across_ring_arcsec=round(float(y), 2),
                                                                                             magnitude_about=round(float(mag(p)), 1), magnitude_expected_about=MAG[n], width_arcsec=p["fit"]["fwhm"] if p["fit"] else None, snr=p["snr"])
    if n != "Iapetus":
        e["orbit_arcsec"] = round(float(a), 1); e["orbit_from_its_place_arcsec"] = round(float(np.hypot(x, y / SINB)), 1); e["across_ring_expected_arcsec"] = round(float(np.sign(y) * SINB * np.sqrt(max(a * a - x * x, 0))), 2)
    old = min(p0, key=lambda o: np.hypot(o["E"] - p["E"], o["N"] - p["N"]), default=None)
    if old is not None and np.hypot(old["E"] - p["E"], old["N"] - p["N"]) < 15:
        e["since_the_earlier_run"] = dict(moved_beside_saturn_arcsec=[round(p["E"] - old["E"], 1), round(p["N"] - old["N"], 1)], a_star_would_have_moved_arcsec=[round(-moved_sat[0], 1), round(-moved_sat[1], 1)])
        if n in PER and n != "Iapetus":                                       # how far along the ring line it should have gone in that time, either way round
            xo = (old["E"] * 0 + 0); dxy = np.array([p["E"] - old["E"], p["N"] - old["N"]]); alr = np.radians(Wa["up_east_of_north_deg"]); ph = np.radians(PHI) + q[2]
            ring_e = np.array([-np.cos(alr) * np.cos(ph) - np.sin(alr) * np.sin(ph), np.sin(alr) * np.cos(ph) - np.cos(alr) * np.sin(ph)]); e["since_the_earlier_run"]["moved_along_ring_arcsec"] = round(float(dxy @ ring_e), 1)
    if p["later"] is not None:
        m = p["later"]; xb, yb = ring(m, PHI + TURN + np.degrees(q[2]), ppb, (q[0], q[1])); e["19_minutes_later"] = dict(moved_along_ring_arcsec=round(float(xb - x), 2), moved_across_arcsec=round(float(yb - y), 2), moved_beside_saturn_arcsec=round(float(np.hypot(m["E"] - p["E"], m["N"] - p["N"])), 2))
        if n != "Iapetus" and abs(x) < a:
            th = np.arccos(x / a); w = 2 * np.pi / PER[n] * (19.24 / 1440); e["19_minutes_later"]["expected_along_ring_arcsec_either_way"] = round(float(abs(a * np.cos(th + w) - x)), 2); signs.append((n, float(np.sign(y)), float(xb - x), float(abs(a * np.cos(th + w) - x))))
    out[n] = e
# the common shift between the two fields (their centres are each good to a few tenths of an arcsec): the mean of what is left after each moon's expected motion, with the sense that fits best
best_s = None
for sense in (1, -1):
    resid = [dx - (-sense * sy * ex) for _, sy, dx, ex in signs]; off = float(np.mean(resid)); rms = float(np.sqrt(np.mean([(r - off) ** 2 for r in resid])))
    if best_s is None or rms < best_s[1]: best_s = (sense, rms, off)
alt = [(dx - (best_s[0] * sy * ex)) for _, sy, dx, ex in signs]; alt_rms = float(np.sqrt(np.mean([(r - np.mean(alt)) ** 2 for r in alt])))
print("direction of motion: with one sense of going round for all, the moons' moves along the ring line fit to %.2f arcsec rms (after a common shift of %+.2f between the fields); with the opposite sense %.2f" % (best_s[1], best_s[2], alt_rms))
for n, e in out.items():
    print("%-9s %6.1f arcsec out (%+.1f E, %+.1f N), magnitude about %.1f (expected about %.1f); along ring %+.2f, across %+.2f" % (n, e["arcsec_from_saturn"], e["east_arcsec"], e["north_arcsec"], e["magnitude_about"], e["magnitude_expected_about"], e["along_ring_arcsec"], e["across_ring_arcsec"])
          + ("" if n == "Iapetus" else " (its orbit there: %+.2f); orbit %.1f arcsec, from its place %.1f" % (e["across_ring_expected_arcsec"], e["orbit_arcsec"], e["orbit_from_its_place_arcsec"]))
          + ("; since 05:14 it moved %s beside Saturn (a star: %s)" % (e["since_the_earlier_run"]["moved_beside_saturn_arcsec"], e["since_the_earlier_run"]["a_star_would_have_moved_arcsec"]) if "since_the_earlier_run" in e else "")
          + ("; 19 min later %+.2f along the ring (expected %.2f either way)" % (e["19_minutes_later"]["moved_along_ring_arcsec"], e["19_minutes_later"].get("expected_along_ring_arcsec_either_way", float("nan"))) if "19_minutes_later" in e else ""))
unnamed = [dict(arcsec_from_saturn=round(p["arcsec"], 1), east_arcsec=round(p["E"], 1), north_arcsec=round(p["N"], 1), box_flux=p["box_flux"], snr=p["snr"], seen_19_minutes_later=p["later"] is not None,
                at_the_same_place_among_the_stars_in_the_earlier_run=bool(any(np.hypot(o["E"] - (p["E"] + moved_sat[0]), o["N"] - (p["N"] + moved_sat[1])) < 5 for o in p0)), half_px_from_blown_out_edge=round(float(dist[int(p["py"]), int(p["px"])]), 1)) for p in pa if p not in named.values()]
json.dump(dict(script="whichmoon.py", ephemeris="none: named from the pictures", sin_B=SINB, ring_line_deg_in_field=PHI, arcsec_per_km=PER_KM, saturn_au=round(206265 / PER_KM / 1.495979e8, 3), globe_radius_arcsec=RE,
               saturn_moved_among_the_stars_since_the_earlier_run_arcsec=[round(moved_sat[0], 1), round(moved_sat[1], 1)], near_the_planet=dict(namings_tried=trials, chosen=best["names"], margin_over_next=round(trials[1]["score"] - best["score"], 2)),
               direction_of_motion=dict(one_sense_rms_arcsec=round(best_s[1], 2), opposite_sense_rms_arcsec=round(alt_rms, 2), common_shift_between_fields_arcsec=round(best_s[2], 2)), named=out, not_named=unnamed), open(OUT, "w"), indent=1)
print("not named:", [(u["arcsec_from_saturn"], u["snr"], "star-like: same place among the stars at 05:14" if u["at_the_same_place_among_the_stars_in_the_earlier_run"] else "") for u in unnamed])
