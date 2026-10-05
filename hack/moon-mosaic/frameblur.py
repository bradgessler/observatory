"""The blur of single frames, from the sunlit limb in each (same fit as judge.py). Read only."""
import sys, os, json, numpy as np, cv2
from concurrent.futures import ProcessPoolExecutor
from scipy.optimize import curve_fit
from scipy.special import erfc
import moonlib
SRC = os.path.expanduser(sys.argv[1]); T = json.load(open("transforms.json"))["placed"]

def one(name):
    try:
        g = moonlib.load(moonlib.raw_path(SRC, name))["g"]
        lit = (cv2.GaussianBlur(g, (0, 0), 2) > 0.5 * np.percentile(g[g > 0.05], 50)).astype(np.uint8)
        cnt = max(cv2.findContours(lit, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0], key=cv2.contourArea)[:, 0, :].astype(np.float64)
        h, w = g.shape; cnt = cnt[(cnt[:, 0] > 20) & (cnt[:, 0] < w - 20) & (cnt[:, 1] > 20) & (cnt[:, 1] < h - 20)]
        def c3(p):
            A = np.c_[2 * p, np.ones(len(p))]; b = (p ** 2).sum(1); cx, cy, c = np.linalg.lstsq(A, b, rcond=None)[0]
            return cx, cy, np.sqrt(max(c + cx * cx + cy * cy, 0))
        rng = np.random.default_rng(7); best = (0, None)
        for _ in range(3000):
            cx, cy, r = c3(cnt[rng.choice(len(cnt), 3, replace=False)])
            if 880 <= r * moonlib.ARCSEC_PER_PX <= 1010:
                on = np.abs(np.hypot(cnt[:, 0] - cx, cnt[:, 1] - cy) - r) < 1.5
                if on.sum() > best[0]: best = (int(on.sum()), on)
        if best[0] < 300: return name, None, 0
        p = cnt[best[1]]; cx, cy, r = c3(p)
        ang = np.arctan2(p[:, 1] - cy, p[:, 0] - cx); a0, a1 = np.percentile(ang, [3, 97]); rs = np.arange(-14, 14.01, 0.25); profs = []
        for a in np.linspace(a0, a1, 800):
            xs = (cx + (r + rs) * np.cos(a)).astype(np.float32)[None]; ys = (cy + (r + rs) * np.sin(a)).astype(np.float32)[None]
            if xs.min() < 2 or ys.min() < 2 or xs.max() > w - 3 or ys.max() > h - 3: continue
            pr = cv2.remap(g, xs, ys, cv2.INTER_CUBIC)[0]; lo, hi = pr[-8:].mean(), pr[:8].mean()
            if 0.1 < hi < 0.9 and lo < 0.2 * hi:
                n = (pr - lo) / (hi - lo); k = np.argmin(np.abs(n - 0.5)); profs.append(np.interp(rs, rs - rs[k], n))
        if len(profs) < 60: return name, None, len(profs)
        (r0, sig), _ = curve_fit(lambda x, r0, s: 0.5 * erfc((x - r0) / (np.sqrt(2) * s)), rs, np.mean(profs, 0), p0=(0, 1.5))
        return name, 2.355 * abs(sig) * moonlib.ARCSEC_PER_PX, len(profs)
    except Exception as e:
        return name, None, -1

if __name__ == "__main__":
    names = sorted(T)
    with ProcessPoolExecutor(8) as ex:
        res = list(ex.map(one, names))
    ok = [(n, f) for n, f, k in res if f]
    v = np.array([f for _, f in ok])
    print("%d of %d frames have a clean stretch of limb" % (len(ok), len(res)))
    print("single-frame limb blur: best %.2f\"  10th pct %.2f\"  median %.2f\"  90th pct %.2f\"  worst %.2f\"" % (v.min(), np.percentile(v, 10), np.median(v), np.percentile(v, 90), v.max()))
    print("sharpest:", [(n, round(f, 2)) for n, f in sorted(ok, key=lambda t: t[1])[:8]])
    json.dump(dict(ok), open("frameblur.json", "w"), indent=1)
