"""The record kept beside the mosaic: frames.csv (every frame: used or discarded, and why) and
recipe.json (every step and number). Usage: record.py <output folder> <keep tag, e.g. keep10>"""
import sys, csv, json, os
from collections import Counter

out, tag = sys.argv[1], sys.argv[2]
grades = {r["name"]: r for r in csv.DictReader(open("grades.csv"))}
exif = {l.split()[0]: l.split()[1:3] for l in open("exif.txt")} if os.path.exists("exif.txt") else {}
T = json.load(open("transforms.json")); R = json.load(open("recipe-%s-2x.json" % tag))
plain_json = os.path.join(out, "finish-moon-full-resolution.json"); restored_json = os.path.join(out, "moon-full-resolution-restored.json")
F = json.load(open(plain_json)); W = json.load(open(restored_json))
raw = lambda n: n[0] + "%0*d.ARW" % (len(n) - 5, int(n[1:-4]) + 1)
rows = []
for n, g in sorted(grades.items()):
    shutter, iso = exif.get(n, ["?", "?"])
    if n in T["placed"]:
        p = T["placed"][n]
        rows.append(dict(frame=n, raw=raw(n), shutter=shutter, iso=iso, verdict="used", why="", matches=p["inliers"], fit_px=round(p["rms_px"], 2),
                         rotation_deg=round(p["rot_deg"], 2), scale=round(p["scale"], 4), share_of_patches_pct=round(100 * R["patch_share"].get(n, 0), 2)))
    else:
        if float(g["lit"]) < 0.03:
            why = "no Moon in the frame" + (" (a 1 s exposure for stars)" if shutter == "1/1" else " (cloud, the door, or lost)")
        elif shutter == "1/1":
            why = "a 1 s exposure: the Moon is blown out"
        else:
            why = "too dim under cloud to match craters"
        rows.append(dict(frame=n, raw=raw(n), shutter=shutter, iso=iso, verdict="discarded", why=why, matches="", fit_px="", rotation_deg="", scale="", share_of_patches_pct=""))
with open(os.path.join(out, "frames.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
why = Counter(r["why"] for r in rows if r["verdict"] == "discarded")
json.dump(dict(
    files={"moon-full-resolution.tif": "the stack as it is, linear 16-bit, at the sensor's pixel scale",
           "moon-full-resolution-restored.tif": "the same with the blur's contrast loss undone as far as the two half-stacks agree (Wiener filter)",
           "frames.csv": "every frame: used or discarded, and why"},
    source=dict(frames=len(rows), used=sum(r["verdict"] == "used" for r in rows), discarded=dict(why)),
    steps=["grade.py: every frame graded from its JPEG (is the Moon there, how much, clouds)",
           "moonlib.load: each RAW read as colour planes, no demosaicing",
           "register.py: craters matched between frames (SIFT), each frame's rotation, shift and scale solved (RANSAC)",
           "stack.py ref / local: frames averaged into a yardstick; per frame a grid of patches matched to it; per patch, detail measured with noise subtracted",
           "stack2x.py: per patch the sharpest frames; each frame's four colour planes read at their own place in the 2x2 colour cell onto the sensor's pixel grid (Lanczos-4, once); feathered at frame edges; cloud and clipped pixels left out",
           "measure.py: colour-plane offsets and the Moon's limb (centre, radius) measured on the stack",
           "psf.py: the blur's spectrum measured from the sunlit limb",
           "frc.py: two stacks from separate halves of the frames compared scale by scale: what both show is real",
           "wiener.py: contrast restored at each scale by (share that is signal) / (contrast the blur left); held at the limb so it cannot ring"],
    resolution=dict(pixel_scale_arcsec=W["arcsec_per_px"], halves_agree=W["halves_agree"]["resolution_arcsec"]),
    stack=R, plain=F, restored=W,
    nothing_generative="No step predicts or invents pixels. Every output pixel is a weighted average of measured pixels from the frames listed in frames.csv, then one linear filter built from two measured curves."),
    open(os.path.join(out, "recipe.json"), "w"), indent=1)
os.remove(plain_json); os.remove(restored_json)
print("used", sum(r["verdict"] == "used" for r in rows), "discarded", dict(why))
