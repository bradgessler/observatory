"""The master flat: what an evenly lit sky looks like to this telescope and sensor (vignetting, the
dust rings, the hair), so it can be divided out of the Moon frames.

Twilight sky frames were taken right after the Moon with the mount standing still. The frames the
flats log kept are read as colour planes (no demosaicing); each plane of each frame is divided by
its own median; the median across frames is the flat (a star drifts, so it is in one frame at a
place and drops out). Each plane is 1.0 at its own median. Reads only.

The sun was coming up under thin cloud while these were taken, and the later frames show the cloud
itself, lit: structure of several percent across the frame that is sky, not telescope. So after a
first flat from every kept frame, a frame whose green planes depart from it by more than CLEAN
(3%) from one 64x64-cell block to another is left out and the flat is made again, until none does.
Last, each plane is smoothed by a Gaussian of 1 cell (the dust rings' edges are 3 cells and wider;
the flat's own pixel noise is not something to divide a Moon by).

Usage: flat.py <stills folder> <flats-log.json> <out.npz>
"""
import json, os, sys
import numpy as np, cv2
import moonlib

SRC = os.path.expanduser(sys.argv[1]); LOG = json.load(open(sys.argv[2])); OUT = sys.argv[3]
kept = [e for e in LOG if e["kept"]]
rows = []; stacks = {k: [] for k in ("00", "01", "10", "11")}; colours = {}
for e in LOG:
    raw = os.path.join(SRC, os.path.splitext(e["file"])[0] + ".ARW")
    row = dict(file=os.path.basename(raw), shutter=e["shutter"], iso=e["iso"], jpeg_level=e["level"], kept_by_log=e["kept"])
    if not os.path.exists(raw):
        row.update(used=False, why="its RAW is not on this Mac"); rows.append(row); continue
    pl, wb = moonlib.cells(raw)
    med = {"%d%d" % (y, x): float(np.median(p)) for c, x, y, p in pl}
    top = max(float(np.percentile(p, 99.9)) for c, x, y, p in pl)
    row.update(median_of_range={k: round(v, 4) for k, v in med.items()}, p999_of_range=round(top, 4))
    if not e["kept"]:
        row.update(used=False, why="the log did not keep it (JPEG level %s)" % e["level"])
    elif top >= 0.9:
        row.update(used=False, why="too near the sensor's ceiling")
    elif min(med.values()) < 0.01:
        row.update(used=False, why="too dark")
    else:
        row.update(used=True, why="")
        for c, x, y, p in pl:
            k = "%d%d" % (y, x); colours[k] = c
            stacks[k].append((p / med[k]).astype(np.float32))
    rows.append(row); print(row)
CLEAN = 3.0; SMOOTH = 1.0
cand = [r for r in rows if r["used"]]; keep = list(range(len(cand))); rounds = 0
while True:
    rounds += 1
    flat = {k: np.median(np.stack([stacks[k][i] for i in keep]), 0).astype(np.float32) for k in stacks}
    # how far each frame is from the master on the large scale (sky gradients, lit cloud)
    worst = {}
    for i, r in enumerate(cand):
        d = {}
        for k in stacks:
            q = cv2.resize(stacks[k][i] / flat[k], None, fx=1 / 64, fy=1 / 64, interpolation=cv2.INTER_AREA)
            d[k] = round(100 * float(q.max() - q.min()), 2)
        r["large_scale_departure_pct"] = d
        worst[i] = max(d[k] for k in stacks if colours[k] == "G")
    out = [i for i in keep if worst[i] > CLEAN]
    print("round", rounds, "frames", len(keep), "over %.0f%%:" % CLEAN, [cand[i]["file"][9:15] for i in out])
    if not out or len(keep) - len(out) < 5:
        break
    keep = [i for i in keep if i not in out]
for i, r in enumerate(cand):
    if i not in keep:
        r.update(used=False, why="lit cloud in the frame: %.1f%% across it against the flat from the others" % worst[i])
n = len(keep)
halves = {k: (np.median(np.stack([stacks[k][i] for i in keep[0::2]]), 0) - np.median(np.stack([stacks[k][i] for i in keep[1::2]]), 0)).astype(np.float32) for k in stacks}
raw_noise = {k: round(100 * float(np.std(halves[k][200:-200, 200:-200])) / 2, 3) for k in stacks}
flat = {k: cv2.GaussianBlur(v, (0, 0), SMOOTH) for k, v in flat.items()}
flat = {k: (v / np.median(v)).astype(np.float32) for k, v in flat.items()}
halves = {k: cv2.GaussianBlur(v, (0, 0), SMOOTH) for k, v in halves.items()}
np.savez(OUT, **flat)
h, w = flat["00"].shape
def stats(f):
    c = float(np.median(f[h // 2 - 100:h // 2 + 100, w // 2 - 100:w // 2 + 100]))
    cor = [float(np.median(q)) for q in (f[:100, :100], f[:100, -100:], f[-100:, :100], f[-100:, -100:])]
    hp = f / cv2.GaussianBlur(f, (0, 0), 40)
    return dict(centre=round(c, 4), corners=[round(v, 4) for v in cor], corner_over_centre=round(min(cor) / c, 3),
                fine_structure_p0_1=round(float(np.percentile(hp, 0.1)), 4), fine_structure_p1=round(float(np.percentile(hp, 1)), 4))
summary = dict(frames_in_log=len(LOG), kept_by_log=len(kept), used=n, rounds=rounds, clean_limit_pct=CLEAN, smooth_sigma_cells=SMOOTH,
               planes={k: dict(colour=colours[k], **stats(flat[k]), noise_per_pixel_pct_before_smoothing=raw_noise[k], noise_per_pixel_pct=round(100 * float(np.std(halves[k][200:-200, 200:-200])) / 2, 3)) for k in flat},
               method="per colour plane: each frame divided by its own median, then the median across frames; frames showing lit cloud left out; Gaussian of 1 cell; each plane 1.0 at its own median", frames=rows)
json.dump(summary, open(OUT.replace(".npz", ".json"), "w"), indent=1)
print(json.dumps({k: v for k, v in summary.items() if k != "frames"}, indent=1))
