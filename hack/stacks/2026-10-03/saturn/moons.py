"""The moons' field from the long exposures (Saturn blown out, the moons and stars showing).

Each frame: half-size colour planes, no demosaicing. Saturn's blown-out blob is found (its middle
is the middle of the planet), every frame is slid so the blobs coincide, and the frames are combined
by their median: the sky moved across the sensor between frames, so a hot pixel is in a different
place in each and the median drops it. Then the planet's glare, which is the same in every
direction, is taken off as its ring-by-ring median, leaving the points.

Usage: moons.py <folder of .ARW> <out stem>
"""
import glob, os, sys, json
import numpy as np, cv2, rawpy
SRC, STEM = sys.argv[1], sys.argv[2]
R = 760            # half-size pixels kept each side of Saturn: 10 arcmin


def planes(path):
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32); pat, desc = r.raw_pattern, r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32); white = float(r.white_level); wb = np.array(r.camera_whitebalance[:3], np.float32)
    out = {"R": None, "G": [], "B": None}
    for y in (0, 1):
        for x in (0, 1):
            c = desc[pat[y, x]]; p = (raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]])
            if c == "G": out["G"].append(p)
            else: out[c] = p
    return np.dstack([out["R"], sum(out["G"]) / 2, out["B"]]), wb / wb[1]


frames = []
for path in sorted(glob.glob(os.path.join(SRC, "*.ARW"))):
    rgb, wb = planes(path); g = rgb[:, :, 1]
    sm = cv2.GaussianBlur(g, (0, 0), 6); cy, cx = np.unravel_index(np.argmax(sm), sm.shape)
    if sm[cy, cx] < 0.3: print(os.path.basename(path), "no Saturn"); continue
    # the blob's own middle: everything within reach at more than half the blob's level
    y0, x0 = max(cy - 60, 0), max(cx - 60, 0); t = sm[y0:cy + 60, x0:cx + 60]; m = t > 0.5 * t.max()
    yy, xx = np.mgrid[0:t.shape[0], 0:t.shape[1]]; fx = float((xx * m).sum() / m.sum()) + x0; fy = float((yy * m).sum() / m.sum()) + y0
    M = np.float32([[1, 0, R - fx], [0, 1, R - fy]])
    w = cv2.warpAffine(rgb * wb, M, (2 * R, 2 * R), flags=cv2.INTER_LANCZOS4, borderValue=np.nan)
    frames.append(w); print(os.path.basename(path), "Saturn at (%.1f, %.1f)" % (fx * 2, fy * 2))
cube = np.stack(frames); n_cover = np.isfinite(cube[..., 1]).sum(0)
med = np.nanmedian(cube, 0).astype(np.float32); med[n_cover < 3] = 0
# the glare: ring by ring around the planet, the median of each ring
yy, xx = np.mgrid[0:2 * R, 0:2 * R]; rr = np.hypot(xx - R, yy - R)
flat = np.zeros_like(med)
edges = np.unique(np.round(np.concatenate([np.arange(0, 60, 1.0), np.geomspace(60, R * 1.5, 160)]))).astype(int)
for c in range(3):
    prof_r, prof_v = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        ring = (rr >= a) & (rr < b) & (n_cover >= 3)
        if ring.sum() > 8: prof_r.append((a + b) / 2); prof_v.append(np.median(med[..., c][ring]))
    flat[..., c] = np.interp(rr, prof_r, prof_v)
pts = med - flat; pts[n_cover < 3] = 0
np.save(STEM + ".npy", pts); np.save(STEM + "-glare.npy", med)
noise = 1.4826 * np.median(np.abs(pts[..., 1][n_cover >= 3]))
# every point of light: where, how bright, how wide
sm = cv2.GaussianBlur(pts[..., 1], (0, 0), 2.0); n, lab, st, cen = cv2.connectedComponentsWithStats((sm > 5 * noise / 4).astype(np.uint8), 8)
found = []
for k in range(1, n):
    x, y, w, h, area = st[k]
    if area < 12: continue
    px, py = cen[k]; d = np.hypot(px - R, py - R) * 0.791
    if d < 22: continue                                    # the planet and its rings
    peak = float(sm[int(py), int(px)]); flux = float(pts[..., 1][max(int(py) - 8, 0):int(py) + 9, max(int(px) - 8, 0):int(px) + 9].sum())
    found.append(dict(x=float(px), y=float(py), arcsec=round(d, 1), angle=round(float(np.degrees(np.arctan2(py - R, px - R))), 1), flux=round(flux, 4), snr=round(float(peak / (noise / 4)), 1), area=int(area)))
found.sort(key=lambda f: f["arcsec"])
json.dump(dict(frames=len(frames), half_size_px_per_side=2 * R, arcsec_per_px=0.791, points=found), open(STEM + ".json", "w"), indent=1)
print("%d frames; %d points away from the planet; noise %.5f" % (len(frames), len(found), noise))
for f in found[:24]: print("  %6.1f arcsec  at %6.1f deg  flux %.3f  snr %5.1f" % (f["arcsec"], f["angle"], f["flux"], f["snr"]))
v = np.clip(pts / (40 * noise), 0, 1) ** 0.5
cv2.imwrite(STEM + ".png", (v[:, :, ::-1] * 255).astype(np.uint8))
