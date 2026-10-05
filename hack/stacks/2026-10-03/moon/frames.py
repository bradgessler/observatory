"""Which pictures are the Moon session, and what each one is. Reads the box's sidecar beside each
still (shutter, ISO, time); writes frames.json. Nothing is graded here: this only sorts the
session's frames by what they were taken for.

Usage: frames.py <stills folder> <first stamp HHMMSS> <last stamp HHMMSS>
"""
import glob, json, os, sys
SRC = os.path.expanduser(sys.argv[1]); T0, T1 = sys.argv[2], sys.argv[3]
HERE = os.path.dirname(os.path.abspath(__file__))
rows = []
for f in sorted(glob.glob(os.path.join(SRC, "20261004-*-DSC*.json"))):
    if f.endswith(".solve.json"):
        continue
    stem = os.path.basename(f)[:-5]; hms = stem.split("-")[1]
    if not (T0 <= hms <= T1):
        continue
    j = json.load(open(f)); c = j.get("camera", {}); p = j.get("pointing", {})
    sh, iso = c.get("shutter"), c.get("iso")
    if sh == "1/60" and iso == 100:
        role, why = "moon", ""
    elif sh == "1/160":
        role, why = "test", "first test at 1/160 s: underexposed, Moon in the corner of the frame"
    elif sh == "4":
        role, why = "earthshine", "4 s at ISO 1600 for earthshine: blown white"
    else:
        role, why = "other", "not a Moon exposure"
    rows.append(dict(name=stem + ".JPG", raw=stem + ".ARW", time_utc=j.get("time", {}).get("shutter_pressed"), shutter=sh, iso=iso, role=role, why=why,
                     has_raw=os.path.exists(os.path.join(SRC, stem + ".ARW")), has_jpg=os.path.exists(os.path.join(SRC, stem + ".JPG")),
                     ra_deg=p.get("ra_deg"), dec_deg=p.get("dec_deg"), alt_deg=p.get("alt_deg")))
json.dump(rows, open(os.path.join(HERE, "frames.json"), "w"), indent=1)
from collections import Counter
print(len(rows), "frames in the session:", dict(Counter(r["role"] for r in rows)))
