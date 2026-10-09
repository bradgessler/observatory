"""Is the Cassini division there? The brightness along the ring line through each end of the rings (averaged +-0.4 arcsec across), from
12 to 25 arcsec from the centre, in the plain stack and in the finished one. The division lies 2.0 Saturn radii out (19.5 arcsec),
0.75 arcsec wide, between ring B (inside) and ring A (outside). It is "seen" only if the brightness, going outward past the peak of
ring B, falls to a low and rises again (a dip with a second peak outside it) and does so in the plain stack too.
Usage: cassini.py name=stack.npy ... [--plot out.png]"""
import sys, json
import numpy as np, cv2
from metrics import measure, sample
SCALE = 0.3882 / 3                       # true arcsec per fine px (stars in the moon frames)
args = [a for a in sys.argv[1:] if "=" in a]; plot = sys.argv[sys.argv.index("--plot") + 1] if "--plot" in sys.argv else None
ref = np.load(args[0].split("=", 1)[1]).astype(np.float32); m, _ = measure(ref[:, :, 1] if ref.ndim == 3 else ref); cx, cy = m["centre"]; ang = np.radians(m["ring_line_deg"]); out = {}; profs = {}
for a in args:
    name, path = a.split("=", 1); s = np.load(path).astype(np.float32); g = s[:, :, 1] if s.ndim == 3 else s
    corners = np.concatenate([g[:70, :70].ravel(), g[:70, -70:].ravel(), g[-70:, :70].ravel(), g[-70:, -70:].ravel()]); bg = float(np.median(corners))
    r = np.arange(-200, 201, 1.0); p = sample(g - bg, cx, cy, ang, r, half=3); globe = float(p[np.abs(r) < 30].mean()); p = p / globe; out[name] = {}
    for side, label in ((-1, "east"), (1, "west")):
        sel = (r * side * SCALE >= 12) & (r * side * SCALE <= 25); rs = r[sel] * side * SCALE; ps = p[sel]; o = np.argsort(rs); rs, ps = rs[o], ps[o]; sm = cv2.GaussianBlur(ps[None].astype(np.float32), (0, 0), 1.0)[0]
        ipk = int(np.argmax(sm)); d = np.gradient(sm); mins = [i for i in range(ipk + 1, len(sm) - 1) if d[i - 1] < 0 <= d[i]]; dip = None
        for i in mins:
            after = sm[i:].max(); depth = float(min(sm[ipk], after) - sm[i])
            if depth > 0: dip = dict(at_arcsec=round(float(rs[i]), 2), level=round(float(sm[i]), 4), second_peak_at_arcsec=round(float(rs[i + int(np.argmax(sm[i:]))]), 2), second_peak_level=round(float(after), 4), depth_of_globe=round(depth, 4)); break
        # where it would be: the slope of the outer flank between 18.5 and 21 arcsec (a shoulder shows as the slope easing, without a dip)
        fl = (rs >= 18.0) & (rs <= 21.5); slope = np.gradient(sm, rs); out[name][label] = dict(ring_peak_at_arcsec=round(float(rs[ipk]), 2), ring_peak_level=round(float(sm[ipk]), 4), dip=dip, gentlest_slope_18_to_21p5_per_arcsec=round(float(slope[fl].max()), 4), steepest=round(float(slope[fl].min()), 4))
        profs[(name, label)] = (rs, sm)
        print("%-16s %s: ring peak %.3f of globe at %.2f arcsec; %s; slope on the outer flank between 18 and 21.5 arcsec: from %.3f to %.3f per arcsec" % (name, label, sm[ipk], rs[ipk], ("DIP at %.2f arcsec, %.4f of the globe deep, second peak at %.2f" % (dip["at_arcsec"], dip["depth_of_globe"], dip["second_peak_at_arcsec"])) if dip else "no dip outside the peak", slope[fl].min(), slope[fl].max()))
json.dump(out, open((plot or "cassini.png").replace(".png", ".json"), "w"), indent=1)
if plot:
    W, H = 1400, 700; img = np.full((H, W, 3), 255, np.uint8); cols = [(200, 60, 40), (40, 140, 40), (40, 60, 200), (150, 40, 150), (0, 0, 0), (0, 150, 170)]
    X = lambda a: int((a - 12) / 13 * (W - 100)) + 70; Y = lambda v: int(H - 50 - v / 1.4 * (H - 90))
    for a in range(12, 26): cv2.line(img, (X(a), Y(0)), (X(a), Y(1.4)), (225, 225, 225), 1); cv2.putText(img, str(a), (X(a) - 8, H - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    for v in (0, 0.25, 0.5, 0.75, 1.0, 1.25): cv2.line(img, (X(12), Y(v)), (X(25), Y(v)), (225, 225, 225), 1); cv2.putText(img, "%.2f" % v, (8, Y(v) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    for a in (19.08, 19.82): cv2.line(img, (X(a), Y(0)), (X(a), Y(1.4)), (160, 160, 160), 1)
    names = []
    for (name, label), (rs, sm) in profs.items():
        if name not in names: names.append(name)
        i = names.index(name); pts = np.array([[X(a), Y(v)] for a, v in zip(rs, sm)], np.int32); cv2.polylines(img, [pts], False, cols[i % len(cols)][::-1], 2 if label == "east" else 1, cv2.LINE_AA)
    for i, name in enumerate(names): cv2.putText(img, name, (W - 330, 40 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cols[i % len(cols)][::-1], 2)
    cv2.putText(img, "green along the ring line, arcsec from the centre; globe = 1; thick east, thin west; grey lines: where the Cassini division is", (70, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1); cv2.imwrite(plot, img)
