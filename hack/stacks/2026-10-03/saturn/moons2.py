"""The moons' field from the long exposures (Saturn blown out, the moons and stars showing).

Each frame: half-size colour planes, no demosaicing. Saturn's blown-out blob is found (its middle
is the middle of the planet), every frame is slid so the blobs coincide, and the frames are combined
by their median: the sky moved across the sensor between frames, so a hot pixel is in a different
place in each and the median drops it. Then the planet's glare, which is the same in every
direction, is taken off as its ring-by-ring median, leaving the points.

Usage: moons2.py <folder of .ARW> <out stem> [folder of .ARW for the hot-pixel map, default the same]

moons2.py is moons.py with two changes, made for the sharp run of 2026-10-04 (08:47 UTC), where only two 2 s frames were taken
under a clear sky (the ten taken after the planet run are behind thickening cloud):
  1. Hot pixels are taken out of each frame before it is slid, because a median of two frames cannot drop them. A hot pixel is a
     fault of the sensor, so it sits at the same photosite in every frame while the sky moves: a photosite that stands more than
     6 sigma of the sky above the median of its 3x3 neighbours (same colour) in at least half of the frames given for the map
     (all twelve 2 s ISO 6400 frames of this run, clear or cloudy) is hot, and is replaced by that median. A star or a moon is
     never at the same photosite in half the frames (Saturn moved 4 to 47 px between them), so none is touched.
     (A first try flagged single frames alone: it clipped the bright pixels of stars, whose own shot noise exceeds 6 sigma of sky.)
  2. A pixel counts when at least min(3, frames) frames cover it (it was 3). With two frames the median is their mean.
  3. After the ring-by-ring median, what is left of the glare near the planet is taken off by its two-fold symmetry. The ring-by-ring
     median removes what is the same in every direction; the rings' ends are not, and left two bright lobes out to 36 arcsec, with two
     dark ones between them. With the points now 3 to 4 arcsec wide, moons show 26 to 45 arcsec from the planet, inside those lobes.
     Saturn with its rings looks the same turned half round about its centre; a moon does not. So within 79 arcsec (fading out by 103)
     each pixel loses the smaller of two values: the lightly smoothed picture there, and the same at the point straight across the
     centre. Glare, bright or dark, is on both sides and goes; a moon or star is on one side only and stays, and leaves no ghost
     across the centre. The centre of symmetry is searched for (to 0.05 px) as the point that makes the two sides most alike (green).
     The air spreads the colours like a weak prism, so the red and blue pictures of the planet sit half a pixel either side of the
     green one, and one centre for all three left a blue haze above the planet and a red one below: so red and blue are first slid
     onto green (by what Rhea shows, least squares, as composite2.py did afterwards), and the ring-by-ring median is taken again.
     (Searching a centre for each colour on its own was tried: the red and blue searches wandered 2 px and left coloured patches.)
     Where the long exposure is blown out on the planet there is nothing to measure: the patch that holds the centre, of pixels where a
     photosite of any colour is at 0.98 of full scale or more in any frame, and 1 px around it, is set to zero and written out as a
     mask, so the composite can set the short-exposure planet in there. (A first try called everything at 0.9 or more in the median
     blown out, and 2 px around: that cut Dione in half, which sits 3 px from the patch on glare of 0.5 and peaks at 0.95, unclipped.)
  4. The points are not quite the same turned half round (stars and moons are slightly teardrop shaped tonight: collimation), so the
     glare is not either: thin arcs of it are left hugging the blown-out patch, the brightest a crescent at the west end of the rings
     that could be taken for a moon. An arc runs along the edge of the patch for 15 px or more; a moon is 4 px wide. So within 16 px
     of the patch (fading out from 12), each pixel loses the median of the pixels at the same distance from the patch (within 0.6 px)
     and within 12 px of it: a running median along the edge, 24 px long. A moon fills a third of that at most and is passed over.
The count of photosites replaced, the centre found and the size of the blown-out region are recorded.
"""
import glob, os, sys, json
import numpy as np, cv2, rawpy
from scipy.optimize import minimize
SRC, STEM = sys.argv[1], sys.argv[2]; HOTSRC = sys.argv[3] if len(sys.argv) > 3 else SRC
R = 760            # half-size pixels kept each side of Saturn: 10 arcmin


def stands_out(path):
    """For each of the four colour planes: which photosites stand more than 6 sigma of the sky above their 3x3 neighbours' median."""
    with rawpy.imread(path) as r: raw = r.raw_image_visible.astype(np.float32)
    out = []
    for y in (0, 1):
        for x in (0, 1):
            p = np.ascontiguousarray(raw[y::2, x::2]); sky = float(np.median(p[::8, ::8])); sd = 1.4826 * float(np.median(np.abs(p[::8, ::8] - sky))); out.append(p - cv2.medianBlur(p, 3) > 6 * sd)
    return out


hot_from = sorted(glob.glob(os.path.join(HOTSRC, "*.ARW"))); count = None
for path in hot_from:
    so = stands_out(path); count = [c + s.astype(np.uint8) for c, s in zip(count, so)] if count else [s.astype(np.uint8) for s in so]
HOT = [c >= (len(hot_from) + 1) // 2 for c in count]; N_HOT = int(sum(h.sum() for h in HOT))
print("hot-pixel map from %d frames: %d photosites stand out in at least %d of them" % (len(hot_from), N_HOT, (len(hot_from) + 1) // 2))


def planes(path):
    with rawpy.imread(path) as r:
        raw = r.raw_image_visible.astype(np.float32); pat, desc = r.raw_pattern, r.color_desc.decode()
        black = np.array(r.black_level_per_channel, np.float32); white = float(r.white_level); wb = np.array(r.camera_whitebalance[:3], np.float32)
    out = {"R": None, "G": [], "B": None}; k = 0; clipped = None
    for y in (0, 1):
        for x in (0, 1):
            c = desc[pat[y, x]]; p = np.ascontiguousarray((raw[y::2, x::2] - black[pat[y, x]]) / (white - black[pat[y, x]])); p = np.where(HOT[k], cv2.medianBlur(p, 3), p); k += 1
            clipped = (p >= 0.98) if clipped is None else clipped | (p >= 0.98)      # a clipped photosite of any colour
            if c == "G": out["G"].append(p)
            else: out[c] = p
    return np.dstack([out["R"], sum(out["G"]) / 2, out["B"]]), wb / wb[1], clipped


frames = []; used = []; clips = []
for path in sorted(glob.glob(os.path.join(SRC, "*.ARW"))):
    rgb, wb, clipped = planes(path); g = rgb[:, :, 1]
    sm = cv2.GaussianBlur(g, (0, 0), 6); cy, cx = np.unravel_index(np.argmax(sm), sm.shape)
    if sm[cy, cx] < 0.3: print(os.path.basename(path), "no Saturn"); continue
    # the blob's own middle: everything within reach at more than half the blob's level
    y0, x0 = max(cy - 60, 0), max(cx - 60, 0); t = sm[y0:cy + 60, x0:cx + 60]; m = t > 0.5 * t.max()
    yy, xx = np.mgrid[0:t.shape[0], 0:t.shape[1]]; fx = float((xx * m).sum() / m.sum()) + x0; fy = float((yy * m).sum() / m.sum()) + y0
    M = np.float32([[1, 0, R - fx], [0, 1, R - fy]])
    w = cv2.warpAffine(rgb * wb, M, (2 * R, 2 * R), flags=cv2.INTER_LANCZOS4, borderValue=np.nan)
    clips.append(cv2.warpAffine(clipped.astype(np.float32), M, (2 * R, 2 * R), flags=cv2.INTER_LINEAR) > 0.01)
    frames.append(w); used.append(os.path.basename(path)); print(os.path.basename(path), "Saturn at (%.1f, %.1f)" % (fx * 2, fy * 2))
cube = np.stack(frames); n_cover = np.isfinite(cube[..., 1]).sum(0); NEED = min(3, len(frames))
med = np.nanmedian(cube, 0).astype(np.float32); med[n_cover < NEED] = 0
# the glare: ring by ring around the planet, the median of each ring
yy, xx = np.mgrid[0:2 * R, 0:2 * R]; rr = np.hypot(xx - R, yy - R)
edges = np.unique(np.round(np.concatenate([np.arange(0, 60, 1.0), np.geomspace(60, R * 1.5, 160)]))).astype(int)
def ring_by_ring(med):
    flat = np.zeros_like(med)
    for c in range(3):
        prof_r, prof_v = [], []
        for a, b in zip(edges[:-1], edges[1:]):
            ring = (rr >= a) & (rr < b) & (n_cover >= NEED)
            if ring.sum() > 8: prof_r.append((a + b) / 2); prof_v.append(np.median(med[..., c][ring]))
        flat[..., c] = np.interp(rr, prof_r, prof_v)
    pts = med - flat; pts[n_cover < NEED] = 0; return pts
pts = ring_by_ring(med)
# the air spreads the colours (blue above, red below): red and blue are slid onto green before the glare is taken off by symmetry, by what the
# brightest point with no clipped pixel shows (least squares on a 64 px tile, as composite2.py did on Rhea after the fact)
anyclip = cv2.dilate(np.any(clips, 0).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0; smg = cv2.GaussianBlur(pts[..., 1], (0, 0), 2.0); smg[anyclip | (rr < 60) | (rr > R - 40)] = 0
ry_, rx_ = np.unravel_index(np.argmax(smg), smg.shape)
def ls_shift(ref, img, margin=10, blur=1.0):
    a = cv2.GaussianBlur(ref, (0, 0), blur); b0 = cv2.GaussianBlur(img, (0, 0), blur); h, w = a.shape; sl = (slice(margin, h - margin), slice(margin, w - margin))
    def cost(p):
        b = cv2.warpAffine(b0, np.float32([[1, 0, -p[0]], [0, 1, -p[1]]]), (w, h), flags=cv2.INTER_LINEAR); k = (a[sl] * b[sl]).sum() / (b[sl] ** 2).sum(); return float(((a[sl] - k * b[sl]) ** 2).sum())
    r = minimize(cost, (0.0, 0.0), method="Nelder-Mead", options=dict(xatol=0.005, fatol=1e-16, initial_simplex=np.array([(0.0, 0.0), (0.7, 0.0), (0.0, 0.7)]))); return float(r.x[0]), float(r.x[1])
tile_ = lambda c: np.ascontiguousarray(pts[ry_ - 32:ry_ + 32, rx_ - 32:rx_ + 32, c]); COLOURS = {}
for c, name in ((0, "red"), (2, "blue")):
    dx, dy = ls_shift(tile_(1), tile_(c)); COLOURS[name] = [round(dx, 3), round(dy, 3)]
    med[..., c] = cv2.warpAffine(med[..., c], np.float32([[1, 0, -dx], [0, 1, -dy]]), med.shape[1::-1], flags=cv2.INTER_LANCZOS4)
print("colours slid onto green by what the point %.0f arcsec from Saturn shows: red (%.2f, %.2f), blue (%.2f, %.2f) half px" % (np.hypot(rx_ - R, ry_ - R) * 0.791, *COLOURS["red"], *COLOURS["blue"]))
pts = ring_by_ring(med)
np.save(STEM + "-rings-only.npy", pts)                       # as moons.py left it
# the glare near the planet by its two-fold symmetry
n2 = 2 * R; _, lab_b = cv2.connectedComponents(np.any(clips, 0).astype(np.uint8), connectivity=8); blown = lab_b == lab_b[R, R]      # the planet's own blown-out patch (Titan and a bright star are blown out too: those stay)
def half_round(img, cx, cy):
    return cv2.warpAffine(img, np.float32([[-1, 0, 2 * cx], [0, -1, 2 * cy]]), (n2, n2), flags=cv2.INTER_LINEAR)
S1 = cv2.GaussianBlur(pts[..., 1], (0, 0), 1.0); ann = (rr > 30) & (rr < 90) & ~blown
def unlike(dx, dy):
    opp = half_round(blown.astype(np.float32), R + dx, R + dy) > 0; ok = ann & ~opp; d = np.abs(S1 - half_round(S1, R + dx, R + dy))[ok]
    return float(np.mean(np.sort(d)[:int(0.9 * d.size)]))    # the most unlike tenth left out: that is where the moons and stars are
best = min((unlike(dx, dy), dx, dy) for dx in np.arange(-2, 2.01, 0.25) for dy in np.arange(-2, 2.01, 0.25))
best = min((unlike(dx, dy), dx, dy) for dx in np.arange(best[1] - 0.25, best[1] + 0.251, 0.05) for dy in np.arange(best[2] - 0.25, best[2] + 0.251, 0.05))
SYM = (float(best[1]), float(best[2])); scx, scy = R + SYM[0], R + SYM[1]; wsym = np.clip((130 - np.hypot(xx - scx, yy - scy)) / 30, 0, 1)
for c in range(3):
    Sc = cv2.GaussianBlur(pts[..., c], (0, 0), 1.0); pts[..., c] -= wsym * np.minimum(Sc, half_round(Sc, scx, scy))
out_of_reach = cv2.dilate(blown.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))) > 0; pts[out_of_reach] = 0; pts[n_cover < NEED] = 0
np.save(STEM + "-before-arcs.npy", pts)
# what runs along the edge of the blown-out patch
dist_b = cv2.distanceTransform((~blown).astype(np.uint8), cv2.DIST_L2, 5); by_, bx_ = np.nonzero((dist_b > 1) & (dist_b <= 16) & (n_cover >= NEED)); bd_ = dist_b[by_, bx_]; arcs = np.zeros((len(by_), 3), np.float32)
for i in range(len(by_)):
    near = (np.abs(bd_ - bd_[i]) <= 0.6) & ((bx_ - bx_[i]) ** 2 + (by_ - by_[i]) ** 2 <= 144)
    arcs[i] = np.median(pts[by_[near], bx_[near]], 0)
pts[by_, bx_] -= arcs * np.clip((16 - bd_) / 4, 0, 1)[:, None]
print("glare along the edge of the blown-out patch: %d px within 16 px of it; the median taken off there is %.4f of full scale at most (green)" % (len(by_), float(arcs[:, 1].max())))
print("glare by symmetry: centre (%.2f, %.2f) half px from the blob's middle (unlikeness %.5f, at the blob's middle %.5f); %d px blown out" % (SYM[0], SYM[1], best[0], unlike(0, 0), int(blown.sum())))
np.save(STEM + ".npy", pts); np.save(STEM + "-glare.npy", med); np.save(STEM + "-blown.npy", blown)
noise = 1.4826 * np.median(np.abs(pts[..., 1][n_cover >= NEED]))
# every point of light: where, how bright, how wide
sm = cv2.GaussianBlur(pts[..., 1], (0, 0), 2.0); n, lab, st, cen = cv2.connectedComponentsWithStats((sm > 5 * noise / 4).astype(np.uint8), 8)
found = []
for k in range(1, n):
    x, y, w, h, area = st[k]
    if area < 12: continue
    px, py = cen[k]; d = np.hypot(px - R, py - R) * 0.791
    if out_of_reach[int(py), int(px)]: continue            # the planet and its rings (moons.py: nearer than 22 arcsec)
    peak = float(sm[int(py), int(px)]); flux = float(pts[..., 1][max(int(py) - 8, 0):int(py) + 9, max(int(px) - 8, 0):int(px) + 9].sum())
    found.append(dict(x=float(px), y=float(py), arcsec=round(d, 1), angle=round(float(np.degrees(np.arctan2(py - R, px - R))), 1), flux=round(flux, 4), snr=round(float(peak / (noise / 4)), 1), area=int(area)))
found.sort(key=lambda f: f["arcsec"])
json.dump(dict(script="moons2.py", frames=len(frames), used=used, hot_pixel_map=dict(frames=[os.path.basename(p) for p in hot_from], rule="more than 6 sigma of sky above the 3x3 median of the same colour in at least %d of %d frames" % ((len(hot_from) + 1) // 2, len(hot_from)), photosites_replaced=N_HOT), frames_needed_per_pixel=NEED, colours_slid_onto_green_half_px=COLOURS, colours_measured_on_point_arcsec_from_saturn=round(float(np.hypot(rx_ - R, ry_ - R) * 0.791), 1), glare_along_the_blown_out_edge=dict(within_half_px=16, fading_from_half_px=12, same_distance_within_half_px=0.6, running_median_length_half_px=24, pixels=int(len(by_)), largest_taken_off_green=round(float(arcs[:, 1].max()), 4)), glare_by_symmetry=dict(centre_from_blob_middle_half_px=[round(SYM[0], 2), round(SYM[1], 2)], smoothing_sigma_half_px=1.0, full_within_half_px=100, none_beyond_half_px=130, blown_out_px=int(blown.sum()), blown_out_rule="the patch holding the centre where a photosite of any colour is at 0.98 of full scale or more in any frame; widened by 1 px"), half_size_px_per_side=2 * R, arcsec_per_px=0.791, points=found), open(STEM + ".json", "w"), indent=1)
print("%d frames; %d points away from the planet; noise %.5f" % (len(frames), len(found), noise))
for f in found[:24]: print("  %6.1f arcsec  at %6.1f deg  flux %.3f  snr %5.1f" % (f["arcsec"], f["angle"], f["flux"], f["snr"]))
v = np.clip(pts / (40 * noise), 0, 1) ** 0.5
cv2.imwrite(STEM + ".png", (v[:, :, ::-1] * 255).astype(np.uint8))
