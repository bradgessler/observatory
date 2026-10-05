"""Did the panels cover the whole lit Moon? Measured on the finished stack, read only.

The limb circle (measure.py) is walked all the way round. At each angle: is there a frame over the
limb there (40 px inside and 40 px outside it), and is the limb bright? The sunlit limb is always
half the circle; its last degrees toward each cusp are too thin and dim to pass for bright, so the
cusps are taken as the middle of the bright arc +-90 degrees. Both cusps must lie inside the
covered arc, with room to spare. Then, over the lit ground itself: the fewest frames any lit pixel
is the average of (from the half-size stack, which counts them).
Usage: coverage.py stack-2x.npz measured-2x.json stack-half.npz out.json"""
import sys, json, numpy as np, cv2
z = np.load(sys.argv[1]); img = z["img"]; depth = z["depth"]; m = json.load(open(sys.argv[2]))
cx, cy = m["moon_centre_px"]; R = m["moon_radius_px"]; h, w = depth.shape; g = img[:, :, 1]
ang = np.radians(np.arange(0, 360, 0.1))
def at(a, r, arr):
    x = np.round(cx + r * np.cos(a)).astype(int); y = np.round(cy + r * np.sin(a)).astype(int)
    ok = (x >= 0) & (x < w) & (y >= 0) & (y < h); out = np.zeros(len(a), arr.dtype); out[ok] = arr[y[ok], x[ok]]
    return out, ok
d_in, in1 = at(ang, R - 40, depth); d_out, in2 = at(ang, R + 40, depth)
covered = (d_in > 0) & (d_out > 0)
inner = np.mean([at(ang, R - k, g)[0] for k in range(6, 30, 4)], 0)
lit = inner > 0.25 * np.percentile(inner, 95)
def arcs(mask):
    d = np.diff(np.r_[mask[-1], mask].astype(int)); s = np.where(d == 1)[0]; e = np.where(d == -1)[0]
    if len(s) == 0:
        return []
    out = []
    for a in s:
        b = e[e > a]; b = b[0] if len(b) else e[0] + len(mask)
        out.append((float(np.degrees(ang[a])), float(np.degrees(ang[b % len(mask)])), float((b - a) * 0.1)))
    return sorted(out, key=lambda t: -t[2])
lit_arc = arcs(lit)[0]; cov_arc = arcs(covered)[0]
mid = (lit_arc[0] + lit_arc[2] / 2) % 360; cusps = [(mid - 90) % 360, (mid + 90) % 360]
cusp_ok = [bool(covered[int(round(c / 0.1)) % len(ang)]) for c in cusps]
litmask = cv2.GaussianBlur(g, (0, 0), 3) > 0.02
count = cv2.resize(np.load(sys.argv[3])["depth"], (w, h), interpolation=cv2.INTER_NEAREST)
out = dict(
    bright_limb=dict(from_deg=lit_arc[0], to_deg=lit_arc[1], length_deg=lit_arc[2], middle_deg=mid, note="screen angles, 0 = right (lunar east), 90 = down (south), 180 = left, 270 = up"),
    cusps_deg=dict(south=cusps[0], north=cusps[1]),
    limb_with_frames_over_it=dict(from_deg=cov_arc[0], to_deg=cov_arc[1], length_deg=cov_arc[2]),
    both_cusps_covered=all(cusp_ok), bright_limb_wholly_covered=bool((covered | ~lit).all()),
    room_beyond_the_cusps=dict(south_deg=round(float((cusps[0] - cov_arc[0]) % 360), 1), north_deg=round(float((cov_arc[1] - cusps[1]) % 360), 1),
                               south_px=round(float(np.radians((cusps[0] - cov_arc[0]) % 360) * R)), north_px=round(float(np.radians((cov_arc[1] - cusps[1]) % 360) * R))),
    lit_ground=dict(pixels=int(litmask.sum()), with_no_frame=int((litmask & (depth <= 0)).sum()), fewest_frames=float(count[litmask].min()), median_frames=float(np.median(count[litmask])),
                    by_thirds_median_frames=dict(north=float(np.median(count[:h // 3][litmask[:h // 3]])), middle=float(np.median(count[h // 3:2 * h // 3][litmask[h // 3:2 * h // 3]])), south=float(np.median(count[2 * h // 3:][litmask[2 * h // 3:]])))),
    picture=dict(size=[w, h], with_no_frame_pct=round(100 * float((depth <= 0).mean()), 2),
                 note="the picture is the lit Moon plus a margin; pixels no frame covers are black (0)"),
    moon=dict(centre_px=[cx, cy], radius_px=R, diameter_arcmin=round(2 * R * m["arcsec_per_px"] / 60, 2)))
# where the uncovered pixels are
nod = depth <= 0
if nod.any():
    ys, xs = np.nonzero(nod); out["picture"]["no_frame_bbox_px"] = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    out["picture"]["no_frame_nearest_to_limb_px"] = float(np.abs(np.hypot(xs - cx, ys - cy) - R).min())
json.dump(out, open(sys.argv[4], "w"), indent=1); print(json.dumps(out, indent=1))
