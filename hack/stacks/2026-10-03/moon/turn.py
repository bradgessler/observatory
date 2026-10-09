"""Lunar north up: every frame's placement turned by the angle orient.py measured, so the stack is
made north-up directly and each RAW is still resampled only once (no second turn of a finished picture).
Rewrites transforms.json (the sensor-way-up one is kept as transforms-sensor.json).
Usage: turn.py orient.json"""
import json, os, sys, shutil, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
O = json.load(open(sys.argv[1]))["verdict"]
if O["picture_is"] != "as it is":
    sys.exit("the picture is mirrored: a turn cannot put it right")
src = os.path.join(HERE, "transforms-sensor.json")
if not os.path.exists(src):
    shutil.copy(os.path.join(HERE, "transforms.json"), src)
T = json.load(open(src)); th = np.radians(O["turned_anticlockwise_deg"])
Rn = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])       # screen coordinates (y down): clockwise by th
for n, p in T["placed"].items():
    p["M"] = (Rn @ np.array(p["M"])).tolist()
    p["rot_deg"] = float(np.degrees(np.arctan2(p["M"][1][0], p["M"][0][0])))
T["north_up"] = dict(turned_clockwise_deg=float(np.degrees(th)), how="orient.py: %d craters, rms %.1f px; cusp line says %.1f" % (O["craters"], O["rms_px"], O["cusp_line_says_deg"]))
json.dump(T, open(os.path.join(HERE, "transforms.json"), "w"), indent=1)
print("placements turned clockwise by %.2f degrees: lunar north is up" % np.degrees(th))
