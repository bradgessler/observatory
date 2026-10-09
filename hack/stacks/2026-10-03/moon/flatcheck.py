"""Does the flat make clear frames of the same ground agree? (a check, not a step)

The same piece of Moon was photographed at one place on the sensor in frame A and at another in
frame B, both under clear sky. Without a flat, the one nearer the frame's edge is dimmer by the
vignetting and each frame carries its own dust shadows; with a true flat their ratio B/A is one
number everywhere. Two things are measured, without the flat and with it:
  large scale: the ratio's median and its spread across the shared ground (5th to 95th percentile
  after a 10-cell blur), and its slope across the frame;
  dust: the flat itself says where dust shadows should show in the ratio and how deep (flat at B's
  place / flat at A's place, its fine structure only). The ratio's own fine structure is compared
  with that prediction at the pixels where the prediction departs from 1 by more than 1%. A slope
  of 1 means the shadows are in the frames just as the flat says; 0 means they are gone.
Usage: flatcheck.py <raw dir> out.json flat.npz frameA frameB [frameA frameB ...]"""
import json, os, sys, numpy as np, cv2
import moonlib
SRC = os.path.expanduser(sys.argv[1]); out = sys.argv[2]; z = np.load(sys.argv[3]); FLAT = {k: z[k] for k in ("00", "01", "10", "11")}
T = json.load(open("transforms-sensor.json" if os.path.exists("transforms-sensor.json") else "transforms.json"))["placed"]
FG = None


def green(flat, name):
    """The frame's green (mean of the two green planes), its own sky level taken off, and the flat's green."""
    global FG
    pl, wb = moonlib.cells(moonlib.raw_path(SRC, name))
    if flat is not None:
        pl = [(c, x, y, p / flat["%d%d" % (y, x)]) for c, x, y, p in pl]
    if FG is None:
        FG = np.mean([FLAT["%d%d" % (y, x)] for c, x, y, p in pl if c == "G"], 0)
    s = moonlib.measure_sky(pl)["sky"]
    return np.mean([p - si for (c, x, y, p), si in zip(pl, s) if c == "G"], 0)


hp = lambda r, m, med: cv2.GaussianBlur(r, (0, 0), 4) / cv2.GaussianBlur(np.where(m, cv2.GaussianBlur(r, (0, 0), 4), med), (0, 0), 40)
pairs = list(zip(sys.argv[4::2], sys.argv[5::2])); res = []
for A, B in pairs:
    MA = np.vstack([T[A]["M"], [0, 0, 1]]); MB = np.vstack([T[B]["M"], [0, 0, 1]]); B2A = (np.linalg.inv(MA) @ MB)[:2]   # B's pixels laid on A's frame
    rec = dict(A=A, B=B); fine = {}
    for label, flat in (("without_flat", None), ("with_flat", FLAT)):
        ga = green(flat, A); gb = green(flat, B); h, w = ga.shape
        gbw = cv2.warpAffine(gb, B2A, (w, h), flags=cv2.INTER_LINEAR); okw = cv2.warpAffine(np.ones_like(gb), B2A, (w, h), flags=cv2.INTER_LINEAR)
        sa, sb = cv2.GaussianBlur(ga, (0, 0), 10), cv2.GaussianBlur(gbw, (0, 0), 10)
        m = (okw > 0.999) & (sa > 0.012) & (sb > 0.006)
        m = cv2.erode(m.astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
        v = (sb / np.maximum(sa, 1e-6))[m]; med = float(np.median(v))
        yy, xx = np.nonzero(m); c = np.linalg.lstsq(np.c_[np.ones(len(v)), xx / w, yy / h], v / med, rcond=None)[0]
        m2 = cv2.erode(m.astype(np.uint8), np.ones((81, 81), np.uint8)) > 0
        fine[label] = hp(gbw / np.maximum(ga, 1e-6) * (ga > 0.004), m, med)
        rec[label] = dict(B_over_A_median=round(med, 3), spread_p5_p95_pct=round(100 * float(np.diff(np.percentile(v, [5, 95]))[0] / med), 1),
                          slope_pct_across_frame=[round(100 * float(c[1]), 1), round(100 * float(c[2]), 1)])
    # what the flat predicts for the ratio's fine structure, and how much of it is there
    pred = cv2.warpAffine(FG, B2A, (w, h), flags=cv2.INTER_LINEAR, borderValue=1.0) / FG
    pred = hp(pred, np.ones_like(m), 1.0); dusty = m2 & (np.abs(pred - 1) > 0.01)
    rec["shared_ground_pct_of_frame"] = round(100 * float(m.mean()), 1)
    if dusty.sum() > 200:
        x = pred[dusty] - 1
        rec["dust"] = dict(pixels=int(dusty.sum()), deepest_predicted_pct=round(100 * float(np.abs(x).max()), 1),
                           slope_without_flat=round(float((x * (fine["without_flat"][dusty] - 1)).sum() / (x * x).sum()), 2),
                           slope_with_flat=round(float((x * (fine["with_flat"][dusty] - 1)).sum() / (x * x).sum()), 2))
    print(A[9:15], B[9:15], json.dumps({k: v for k, v in rec.items() if k not in ("A", "B")}))
    res.append(rec)
json.dump(dict(note="A and B: two clear frames showing the same ground at different places on the sensor", pairs=res), open(out, "w"), indent=1)
