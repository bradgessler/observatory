"""Grade every planet frame once with saturn.py's own find(), save the grades (so the recipe can say why each frame was kept or not)."""
import sys, os, json, glob, importlib.util
from concurrent.futures import ProcessPoolExecutor
import numpy as np
sys.argv = [sys.argv[0], "planet", "x"]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import saturn as sat
if __name__ == "__main__":
    files = sorted(glob.glob("planet/*.ARW"))
    with ProcessPoolExecutor(8) as ex: found = list(ex.map(sat.find, files))
    for f in found: f["name"] = os.path.basename(f.pop("path"))
    json.dump(found, open("grades.json", "w"), indent=1)
    ok = [f for f in found if f["ok"]]; ok.sort(key=lambda f: -f["sharp"])
    med = np.median([f["flux"] for f in ok])
    for i, f in enumerate(ok): print("%3d %s sharp %.4f flux %.3f (%.2f of median) peak %.3f clipped %d at (%.1f, %.1f)" % (i + 1, f["name"][9:15] + " " + f["name"][16:24], f["sharp"], f["flux"], f["flux"] / med, f["peak"], f["clipped"], f["x"] * 2, f["y"] * 2))
    for f in found:
        if not f["ok"]: print("not ok:", f["name"], f["why"])
