"""Quick look, labelled as such: a stack of the camera's own JPEGs, registered on the stars.
Not the RAW pipeline (stack-pictures); every number it used goes into the recipe beside the picture.

usage: quickstack.py OUT_PREFIX CX CY HALF_W HALF_H FRAME.jpg [FRAME.jpg ...]
CX, CY: the target's place in the first frame (sensor pixels, the sensor's own way up)."""
import sys, json, os
import numpy as np, cv2

out, cx, cy, hw, hh = sys.argv[1], *map(int, sys.argv[2:6])
frames = sys.argv[6:]


def load(f):
    return cv2.imread(f, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION).astype(np.float32)


def stars(img, n=80):
    """Centroids of the brightest compact stars, from a 2x-shrunk grey copy."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (g.shape[1] // 2, g.shape[0] // 2), interpolation=cv2.INTER_AREA)
    bg = cv2.medianBlur(g.astype(np.uint8), 31).astype(np.float32)
    d = g - bg
    s = 1.4826 * np.median(np.abs(d - np.median(d)))
    mask = (d > 6 * s).astype(np.uint8)
    k, lab, st, cen = cv2.connectedComponentsWithStats(mask)
    good = [(st[i, cv2.CC_STAT_AREA], cen[i]) for i in range(1, k) if 3 <= st[i, cv2.CC_STAT_AREA] <= 400]
    good.sort(key=lambda t: -t[0] * d[int(t[1][1]), int(t[1][0])])
    return np.array([c for _, c in good[:n]], np.float32) * 2.0


def pairs(ref, pts, tol):
    a, b = [], []
    for p in pts:
        dd = np.linalg.norm(ref - p, axis=1)
        j = dd.argmin()
        if dd[j] < tol:
            a.append(ref[j]); b.append(p)
    return np.array(a, np.float32), np.array(b, np.float32)


def match(ref, pts):
    """The field shifts a little and turns about its middle (a degree in 20 minutes): a shift from the densest
    vote of pair offsets, then a rough rotation+shift from loose pairs, then a tight fit from close pairs."""
    off = (pts[None, :, :] - ref[:, None, :]).reshape(-1, 2)
    q = np.round(off / 8.0).astype(int)
    keys, counts = np.unique(q, axis=0, return_counts=True)
    shift = keys[counts.argmax()] * 8.0
    a, b = pairs(ref, pts - shift, 45.0)
    if len(a) < 6:
        return None, len(a)
    M1, _ = cv2.estimateAffinePartial2D(b + shift, a, method=cv2.RANSAC, ransacReprojThreshold=6.0)
    if M1 is None:
        return None, 0
    moved = pts @ M1[:, :2].T + M1[:, 2]
    a, _ = pairs(ref, moved, 4.0)
    keep = [i for i, p in enumerate(moved) if np.linalg.norm(ref - p, axis=1).min() < 4.0]
    if len(keep) < 6:
        return None, len(keep)
    M, inl = cv2.estimateAffinePartial2D(pts[keep], np.array([ref[np.linalg.norm(ref - moved[i], axis=1).argmin()] for i in keep]),
                                         method=cv2.RANSAC, ransacReprojThreshold=2.0)
    return M, int(inl.sum()) if inl is not None else 0


ref_img = load(frames[0])
ref_st = stars(ref_img)
x0, y0, x1, y1 = cx - hw, cy - hh, cx + hw, cy + hh
cube, used, dropped = [], [], []
for f in frames:
    img = ref_img if f == frames[0] else load(f)
    if f == frames[0]:
        M, n = np.float32([[1, 0, 0], [0, 1, 0]]), len(ref_st)
    else:
        M, n = match(ref_st, stars(img))
    if M is None or n < 10:
        dropped.append({"frame": os.path.basename(f), "matched": n}); continue
    w = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=np.nan)
    cube.append(w[y0:y1, x0:x1]); used.append({"frame": os.path.basename(f), "matched": n, "dx": float(M[0, 2]), "dy": float(M[1, 2]),
                                               "rot_deg": float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))})
cube = np.array(cube)
# sigma-clipped mean: satellites, planes, hot pixels out
m = np.nanmean(cube, 0)
for _ in range(2):
    s = np.nanstd(cube, 0)
    cube = np.where(np.abs(cube - m) > 2.5 * s, np.nan, cube)
    m = np.nanmean(cube, 0)
stack = m
# the sky: one constant per colour, measured off the target (sigma-clipped median); neutral black
sky = []
for c in range(3):
    v = stack[..., c][np.isfinite(stack[..., c])]
    for _ in range(5):
        med, sd = np.median(v), np.std(v)
        v = v[np.abs(v - med) < 2.5 * sd]
    sky.append(float(np.median(v)))
lin = np.stack([stack[..., c] - sky[c] for c in range(3)], -1)
noise = float(np.std(np.clip(lin, -50, 50)))
white = float(np.nanpercentile(lin, 99.97))
k = 12.0
pic = np.arcsinh(np.clip(lin, 0, None) / white * k) / np.arcsinh(k)
pic = np.clip(np.nan_to_num(pic), 0, 1)
cv2.imwrite(out + '-full.jpg', (pic * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 93])
# a quieter, half-size copy: 2x2 averaged (smaller, never enlarged)
small = cv2.resize(pic, (pic.shape[1] // 2, pic.shape[0] // 2), interpolation=cv2.INTER_AREA)
cv2.imwrite(out + '-half.jpg', (small * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 93])
single = ref_img[y0:y1, x0:x1]
sl = np.stack([single[..., c] - sky[c] for c in range(3)], -1)
sp = np.clip(np.arcsinh(np.clip(sl, 0, None) / white * k) / np.arcsinh(k), 0, 1)
side = np.concatenate([sp, np.zeros((sp.shape[0], 12, 3)), pic], 1)
cv2.imwrite(out + '-single-vs-stack.jpg', (side * 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 90])
json.dump({"what": "quick look: the camera's JPEGs, not the RAWs", "frames_used": len(used), "frames_dropped": dropped,
           "registration": "brightest compact stars (6 sigma, 2x shrunk), pair-offset vote, loose pairs (45 px) to a rough rotation+shift, close pairs (4 px) to the final RANSAC fit (2 px)",
           "warp": "Lanczos4", "combine": "mean, 2 passes of 2.5 sigma clipping", "sky": sky, "stretch": {"asinh_k": k, "white": white},
           "region": [x0, y0, x1, y1], "frames": used}, open(out + '-recipe.json', 'w'), indent=1)
print(f"stacked {len(used)} of {len(frames)} (dropped {len(dropped)}); sky {[round(v,1) for v in sky]}, noise {noise:.2f}")
