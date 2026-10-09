"""Numbers for a planet stack (fine grid, 3 per native px = 0.1318 arcsec per fine px), on the green plane only
so that colour registration cannot colour the answer:
  ring line     the long axis of the rings (from the faint outskirts' second moments)
  gap contrast  along the ring line: (ring ansa peak - the dip between globe and ring) / (peak + dip), both sides averaged
  ansa width    FWHM across the ring at 18.5 arcsec from the centre: the ring is thin there, so this is close to the blur itself
  limb width    10 to 90 percent of the edge of the globe along the polar axis
  noise         standard deviation of the sky in the tile's corners, as a fraction of the globe's brightness
Usage: metrics.py name=stack.npy [name=stack.npy ...] [--plot out.png]
"""
import sys, json
import numpy as np, cv2
FINE = 0.3955 / 3

def sample(img, cx, cy, ang, r, off=0.0, half=3):
    """Profile along direction ang through (cx, cy) displaced by off along the normal; averaged over +-half fine px across."""
    ca, sa = np.cos(ang), np.sin(ang); out = np.zeros(len(r), np.float32)
    for k in range(-half, half + 1):
        x = cx + r * ca - (off + k) * sa; y = cy + r * sa + (off + k) * ca
        out += cv2.remap(img, x.astype(np.float32)[None], y.astype(np.float32)[None], cv2.INTER_LINEAR)[0]
    return out / (2 * half + 1)

def fwhm(r, p):
    p = p - min(p[0], p[-1]); i = int(np.argmax(p)); h = p[i] / 2
    a = i
    while a > 0 and p[a] > h: a -= 1
    b = i
    while b < len(p) - 1 and p[b] > h: b += 1
    xa = r[a] + (h - p[a]) / (p[a + 1] - p[a]) * (r[a + 1] - r[a]); xb = r[b - 1] + (h - p[b - 1]) / (p[b] - p[b - 1]) * (r[b] - r[b - 1])
    return xb - xa

def edge(r, p):
    """10-90 width of a falling edge: p starts on the plateau and ends in the sky."""
    top = p[:len(p) // 4].max(); bot = np.median(p[-len(p) // 8:]); q = (p - bot) / (top - bot); i0 = int(np.argmax(p[:len(p) // 4]))
    def cross(level):
        for i in range(i0, len(q) - 1):
            if q[i] >= level > q[i + 1]: return r[i] + (q[i] - level) / (q[i] - q[i + 1]) * (r[i + 1] - r[i])
    return cross(0.1) - cross(0.9)

def measure(g):
    g = g.astype(np.float32); n = g.shape[0]; yy, xx = np.mgrid[0:n, 0:n]
    corners = np.concatenate([g[:70, :70].ravel(), g[:70, -70:].ravel(), g[-70:, :70].ravel(), g[-70:, -70:].ravel()]); bg = float(np.median(corners)); noise = float(corners.std())
    v = np.clip(g - bg, 0, None); m = v > 0.25 * v.max(); cx = (xx * v * m).sum() / (v * m).sum(); cy = (yy * v * m).sum() / (v * m).sum()
    sm = cv2.GaussianBlur(v, (0, 0), 4); w = ((sm > 0.08 * sm.max()) & (sm < 0.5 * sm.max())).astype(np.float64)       # the outskirts: mostly ring
    dx, dy = xx - cx, yy - cy; cxx = (w * dx * dx).sum(); cyy = (w * dy * dy).sum(); cxy = (w * dx * dy).sum(); ang = 0.5 * np.arctan2(2 * cxy, cxx - cyy)
    r = np.arange(-230, 231, 1.0); along = sample(g - bg, cx, cy, ang, r); globe = float(along[np.abs(r) < 30].mean())
    res = dict(centre=[round(float(cx), 2), round(float(cy), 2)], ring_line_deg=round(float(np.degrees(ang)), 2), globe=globe, noise_of_globe=noise / globe)
    cons = []
    for side in (-1, 1):
        sel = (r * side > 75) & (r * side < 190); rs, ps = r[sel] * side, along[sel]; o = np.argsort(rs); rs, ps = rs[o], ps[o]
        # the dip: lowest point before the last local maximum (the ansa)
        d1 = np.gradient(cv2.GaussianBlur(ps[None], (0, 0), 2)[0]); peaks = [i for i in range(1, len(ps) - 1) if d1[i - 1] > 0 >= d1[i] and rs[i] > 95]
        if peaks:
            ip = peaks[0]; idip = int(np.argmin(ps[:ip])); con = float((ps[ip] - ps[idip]) / (ps[ip] + ps[idip])); cons.append(con)
            res["east" if side < 0 else "west"] = dict(ansa_peak_arcsec=round(float(rs[ip] * FINE), 2), ansa_level=round(float(ps[ip] / globe), 4), dip_arcsec=round(float(rs[idip] * FINE), 2), dip_level=round(float(ps[idip] / globe), 4), contrast=round(con, 4))
        else:
            cons.append(0.0); res["east" if side < 0 else "west"] = dict(contrast=0.0, note="no dip between globe and ring")
    res["gap_contrast"] = round(float(np.mean(cons)), 4)
    q = np.arange(-70, 71, 1.0); ws = []
    for side in (-1, 1):
        px, py = cx + side * 140 * np.cos(ang), cy + side * 140 * np.sin(ang); ws.append(fwhm(q, sample(g - bg, px, py, ang + np.pi / 2, q, half=6)) * FINE)
    res["ansa_width_fwhm_arcsec"] = round(float(np.mean(ws)), 3); res["ansa_width_each"] = [round(float(x), 3) for x in ws]
    rr = np.arange(0, 150, 1.0); es = []
    for side in (-1, 1): es.append(edge(rr, sample(g - bg, cx, cy, ang + side * np.pi / 2, rr, half=6)) * FINE)
    res["polar_limb_10_90_arcsec"] = round(float(np.mean(es)), 3); res["polar_limb_each"] = [round(float(x), 3) for x in es]
    # how much fine detail is in it: gradient energy over the planet per unit light (the same measure the frames were graded by, on the stack)
    t0 = v; gx, gy = np.gradient(cv2.GaussianBlur(t0, (0, 0), 2.4)); res["gradient_energy"] = round(float(((gx ** 2 + gy ** 2) * m).sum() / (t0 * m).sum() ** 2 * 1e7), 4)
    return res, (r * FINE, along / globe)

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if "=" in a]; plot = sys.argv[sys.argv.index("--plot") + 1] if "--plot" in sys.argv else None
    out = {}; profs = {}
    for a in args:
        name, path = a.split("=", 1); s = np.load(path); g = s[:, :, 1] if s.ndim == 3 else s
        out[name], profs[name] = measure(g)
        o = out[name]; print("%-10s ring line %6.2f deg  gap contrast %.4f (E %.4f, W %.4f)  ansa width %.3f\"  polar limb 10-90 %.3f\"  noise %.5f of globe  grad %.4f" % (name, o["ring_line_deg"], o["gap_contrast"], o["east"]["contrast"], o["west"]["contrast"], o["ansa_width_fwhm_arcsec"], o["polar_limb_10_90_arcsec"], o["noise_of_globe"], o["gradient_energy"]))
    json.dump(out, open("metrics.json" if not plot else plot.replace(".png", ".json"), "w"), indent=1)
    if plot:
        W, H = 1400, 700; img = np.full((H, W, 3), 255, np.uint8); cols = [(200, 60, 40), (40, 140, 40), (40, 60, 200), (150, 40, 150), (0, 0, 0), (0, 150, 170), (120, 120, 120), (220, 140, 0)]
        X = lambda a: int((a + 31) / 62 * (W - 80)) + 60; Y = lambda v: int(H - 50 - v / 1.15 * (H - 90))
        for a in range(-30, 31, 5): cv2.line(img, (X(a), Y(0)), (X(a), Y(1.15)), (225, 225, 225), 1); cv2.putText(img, str(a), (X(a) - 10, H - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        for v in (0, 0.25, 0.5, 0.75, 1.0): cv2.line(img, (X(-31), Y(v)), (X(31), Y(v)), (225, 225, 225), 1); cv2.putText(img, "%.2f" % v, (8, Y(v) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        for i, (name, (r, p)) in enumerate(profs.items()):
            pts = np.array([[X(a), Y(v)] for a, v in zip(r, p) if abs(a) <= 31], np.int32); cv2.polylines(img, [pts], False, cols[i % len(cols)][::-1], 2, cv2.LINE_AA)
            cv2.putText(img, name, (W - 200, 40 + 24 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.6, cols[i % len(cols)][::-1], 2)
        cv2.putText(img, "green, along the ring line; arcsec from the centre; globe = 1", (60, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
        cv2.imwrite(plot, img)
