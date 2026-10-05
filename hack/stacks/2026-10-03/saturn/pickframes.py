"""Fixed list of frames at this moment: only those with .ARW, .JPG and .json all present (and the ARW size matching the sidecar)."""
import glob, json, os, collections, sys, time
S = os.path.expanduser("~/.observatory/nights/2026-10-03-a6000/stills")
rows = []; incomplete = []
for j in sorted(glob.glob(S + "/*.json")):
    if j.endswith(".solve.json"): continue
    stem = j[:-5]
    if not (os.path.exists(stem + ".ARW") and os.path.exists(stem + ".JPG")): incomplete.append(os.path.basename(stem)); continue
    try: d = json.load(open(j))
    except Exception as e: incomplete.append(os.path.basename(stem) + " (sidecar unreadable)"); continue
    want = {f["format"]: f["bytes"] for f in d.get("files", [])}
    if want.get("arw") and os.path.getsize(stem + ".ARW") != want["arw"]: incomplete.append(os.path.basename(stem) + " (ARW still arriving)"); continue
    c = d["camera"]; rows.append(dict(name=os.path.basename(stem), iso=c["iso"], exp=c["exposure_s"], shutter=c["shutter"], t=d["time"]["shutter_pressed"],
                                      ra=d["mount"]["start"]["ra"]["deg"], dec=d["mount"]["start"]["dec"]["deg"], tracking=d["mount"]["start"].get("tracking"), lock=d.get("lock_on", {}).get("state")))
json.dump(dict(taken_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), frames=rows, incomplete=incomplete), open("frames.json", "w"), indent=1)
print(len(rows), "complete frames;", len(incomplete), "incomplete")
cnt = collections.Counter((r["iso"], r["exp"], r["shutter"]) for r in rows)
for k, v in sorted(cnt.items(), key=lambda kv: -kv[1]): print(v, k, min(r["t"] for r in rows if (r["iso"], r["exp"], r["shutter"]) == k), max(r["t"] for r in rows if (r["iso"], r["exp"], r["shutter"]) == k))
