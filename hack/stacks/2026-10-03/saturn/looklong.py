"""A look at every 2 s frame: the field round Saturn (green, half-size px), one stretch, and each frame's sky level and the light of Rhea-sized points."""
import json, glob, os, numpy as np, cv2
from longgrade import green
lg = {r["frame"]: r for r in json.load(open("longgrades.json"))}
tiles = []
for path in sorted(glob.glob("long/*.ARW")):
    g = green(path); r = lg[os.path.basename(path)]; fx, fy = r["x"] / 2, r["y"] / 2; R = 520
    M = np.float32([[1, 0, R - fx], [0, 1, R - fy]]); w = cv2.warpAffine(g, M, (2 * R, 2 * R), flags=cv2.INTER_LINEAR)
    sky = float(np.median(g[::8, ::8])); sd = 1.4826 * float(np.median(np.abs(g[::8, ::8] - sky)))
    v = np.clip((cv2.GaussianBlur(w, (0, 0), 1.0) - sky) / (40 * sd), 0, 1) ** 0.5
    img = cv2.resize((v * 255).astype(np.uint8), (520, 520), interpolation=cv2.INTER_AREA); cv2.putText(img, os.path.basename(path)[9:15] + " sky %.4f sd %.4f" % (sky, sd), (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 255, 1)
    tiles.append(img); print(os.path.basename(path), "sky %.5f noise %.5f" % (sky, sd))
rows = [np.hstack(tiles[i:i + 4]) for i in range(0, 12, 4)]; cv2.imwrite("look/long-all.png", np.vstack(rows))
