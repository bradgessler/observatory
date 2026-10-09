#!/usr/bin/env python3
"""Move the stills camera's pictures from the box to this Mac, so the box's card never fills.

A picture is moved, never just deleted: its files are copied here, each copy's SHA-256 is checked
against the hash the box wrote in the picture's sidecar when the camera delivered it, and only then
are the RAW and the JPEG removed from the box. Anything that does not verify stays on the box and is
reported. The sidecars (.json) and the night's index stay on the box as well as coming here: they
are small, and they are the record.

    offload.py <night on the box, e.g. 2026-10-04> <folder here> [minutes to keep going, default 600]

BOX names the box (default 10.0.1.44). Copies already here under the folder's parent (by name) are
linked in rather than fetched again.
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request

night, dest = sys.argv[1], os.path.expanduser(sys.argv[2])
minutes = float(sys.argv[3]) if len(sys.argv) > 3 else 600
BOX = os.environ.get("BOX", "10.0.1.44"); BASE = "http://%s/cameras/stills/files/%s" % (BOX, night)
HERE = os.path.dirname(os.path.abspath(__file__))
PICTURE = re.compile(r"^\d{8}-\d{6}[a-z]?-[A-Za-z0-9_]+\.(ARW|JPG)$")
os.makedirs(dest, exist_ok=True)


def log(msg): print(time.strftime("%H:%M:%S", time.gmtime()), msg, flush=True)


def listing():
    with urllib.request.urlopen(BASE, timeout=20) as r: return {x["name"]: x["bytes"] for x in json.load(r)}


def fetch(name):
    tmp = os.path.join(dest, name + ".part")
    with urllib.request.urlopen(BASE + "/" + name, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk: break
            f.write(chunk)
    os.replace(tmp, os.path.join(dest, name))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()


def elsewhere(name):
    """A copy made earlier tonight, somewhere under the night's folder."""
    root = os.path.dirname(dest)
    for d, _, files in os.walk(root):
        if name in files and os.path.abspath(d) != os.path.abspath(dest): return os.path.join(d, name)


def remove_on_box(names):
    """Only plain picture names in the night's folder, and only ones just verified here."""
    names = [n for n in names if PICTURE.match(n)]
    if not names: return 0
    code = 'dir = Path.join(Controller.StillCamera.dir(), "%s"); n = Enum.count(%s, fn f -> f == Path.basename(f) and File.rm(Path.join(dir, f)) == :ok end); IO.puts("REMOVED #{n}")' % (night, json.dumps(names))
    out = subprocess.run([os.path.join(HERE, "box"), code], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"REMOVED (\d+)", out); return int(m.group(1)) if m else 0


end = time.time() + minutes * 60; moved_total = 0; quiet = 0
while time.time() < end:
    try:
        files = listing()
    except Exception as e:
        log("the box did not answer (%s): trying again" % e); time.sleep(15); continue
    # the index and every sidecar first: they say what each picture's files must hash to
    for name in sorted(n for n in files if n.endswith(".json") or n == "index.jsonl"):
        path = os.path.join(dest, name)
        if not os.path.exists(path) or os.path.getsize(path) != files[name]:
            try: fetch(name)
            except Exception as e: log("could not fetch %s: %s" % (name, e))
    verified, bad, copied = [], [], 0
    newest = max((n for n in files if n.endswith(".json") and not n.endswith(".solve.json")), default="")
    sides = [n for n in files if n.endswith(".json") and not n.endswith(".solve.json") and n != "index.jsonl"]
    # pictures already copied here go first: they free the card without waiting on a download
    here = lambda side: any(os.path.exists(os.path.join(dest, side[:-5] + ext)) or elsewhere(side[:-5] + ext) for ext in (".ARW", ".JPG"))
    for side in sorted(sides, key=lambda n: (not here(n), n)):
        if side == newest: continue                      # the picture being written right now is left alone
        try: rec = json.load(open(os.path.join(dest, side)))
        except Exception: continue
        for f in rec.get("files", []):
            name = f["name"]
            if name not in files: continue                # already moved
            path = os.path.join(dest, name)
            try:
                if not os.path.exists(path):
                    other = elsewhere(name)
                    if other and os.path.getsize(other) == f["bytes"]: os.link(other, path)
                    else: fetch(name); copied += 1
                if os.path.getsize(path) == f["bytes"] and sha(path) == f["sha256"]: verified.append(name)
                else:
                    bad.append(name); os.remove(path)     # a bad copy is thrown away here and fetched again next round; the box keeps its file
            except Exception as e:
                log("could not move %s: %s" % (name, e)); break
        if len(verified) >= 12: break                     # remove in small batches, so room comes back steadily
    removed = remove_on_box(verified) if verified else 0
    moved_total += removed
    if verified or bad or copied:
        left = sum(1 for n in files if PICTURE.match(n)) - removed
        log("fetched %d, verified %d, removed from the box %d%s; %d picture files still on the box; %d moved in all" % (copied, len(verified), removed, (", %d did NOT verify and stay there: %s" % (len(bad), bad)) if bad else "", left, moved_total))
        quiet = 0
    else:
        quiet += 1
        time.sleep(20)
log("done: %d files moved" % moved_total)
