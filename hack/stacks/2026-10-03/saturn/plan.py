"""plan.json for whois2.py, from the plate solves of the moon frames themselves (sidecar .solve.json): the picture's turn and scale, and
Saturn's place on the sky (the solve's centre, moved by Saturn's offset from the middle of the sensor). The earlier run's plan.json came
from the live session; this one needs only the two solves.
Usage: plan.py <moonfield stem> <out plan.json>"""
import sys, json, os, numpy as np
stem, out = sys.argv[1], sys.argv[2]; ST = os.path.expanduser("~/.observatory/nights/2026-10-03-a6000/stills"); rec = json.load(open(stem + ".json")); lg = {r["frame"]: r for r in json.load(open("longgrades.json"))}
rows = []
for name in rec["used"]:
    s = json.load(open(os.path.join(ST, name[:-4] + ".solve.json")))
    if s["state"] != "solved": continue
    so = s["solution"]; per_px = so["pixscale_arcsec"] * (so["width_deg"] * 3600 / so["pixscale_arcsec"]) / 6000      # the solver's copy is 1500 px wide: arcsec per sensor px
    alpha = np.radians(so["rotation_deg"] - 180)                                                                       # the picture's up, east of north (162.1 at 05:03 was -17.9)
    dx, dy = lg[name]["x"] - 3000, lg[name]["y"] - 2000; E = per_px * (-np.cos(alpha) * dx - np.sin(alpha) * dy); N = per_px * (np.sin(alpha) * dx - np.cos(alpha) * dy)
    rows.append(dict(frame=name, up_east_of_north_deg=float(np.degrees(alpha)), arcsec_per_sensor_px=float(per_px), sat=[so["ra_deg"] + E / 3600 / np.cos(np.radians(so["dec_deg"])), so["dec_deg"] + N / 3600], solve=so))
    print(name, "up %.3f deg east of north, %.5f arcsec per sensor px, Saturn at RA %.5f Dec %.5f" % (rows[-1]["up_east_of_north_deg"], per_px, *rows[-1]["sat"]))
alpha = np.radians(np.mean([r["up_east_of_north_deg"] for r in rows])); s = np.mean([r["arcsec_per_sensor_px"] for r in rows]) * 6.25      # whois2.py's unit: a 960 px copy, 6.25 sensor px per px
A = (np.array([[-np.cos(alpha), np.sin(alpha)], [-np.sin(alpha), -np.cos(alpha)]]) / s).tolist()
json.dump(dict(A=A, sat=[float(np.mean([r["sat"][0] for r in rows])), float(np.mean([r["sat"][1] for r in rows]))], from_solves=rows), open(out, "w"), indent=1)
