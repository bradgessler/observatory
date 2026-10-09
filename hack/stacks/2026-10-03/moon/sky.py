"""Each frame's own sky level, per colour plane, measured on the RAW after the flat: the session
ran into morning twilight, so the sky under the Moon is brighter in every frame than in the last.
Also the glow round the Moon (cloud). Reads grades.csv and the RAWs; writes sky.json.

Usage: sky.py <raw dir>
"""
import csv, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import moonlib

SRC = os.path.expanduser(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))


def one(name):
    pl, wb = moonlib.cells(moonlib.raw_path(SRC, name))
    F = moonlib.flat()
    if F:
        pl = [(c, x, y, p / F["%d%d" % (y, x)]) for c, x, y, p in pl]
    return os.path.splitext(name)[0] + ".ARW", moonlib.measure_sky(pl)


if __name__ == "__main__":
    names = [r["name"] for r in csv.DictReader(open(os.path.join(HERE, "grades.csv"))) if os.path.exists(moonlib.raw_path(SRC, r["name"]))]
    with ProcessPoolExecutor(6) as ex:
        out = dict(ex.map(one, names))
    json.dump(out, open(moonlib.SKY_PATH, "w"), indent=1)
    c = 16383 - 512
    for k in sorted(out):
        v = out[k]; print(k[9:15], "sky counts R %5.1f G %5.1f G %5.1f B %5.1f   face %6.0f   glow %.3f   far %.2f" % (*[s * c for s in v["sky"]], v["face"] * c, v["glow"], v["far_share"]))
