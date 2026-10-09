"""Side-by-side panel of fine-grid arrays at one stretch: each is scaled so the globe's middle is the same grey, same gamma.
Usage: panel.py out.png [--gain 1.0] label=file.npy ... ('|' starts a new row)"""
import sys, numpy as np, cv2
out = sys.argv[1]; args = sys.argv[2:]; gain = 1.0
if "--gain" in args: i = args.index("--gain"); gain = float(args[i + 1]); del args[i:i + 2]
rows = [[]]
for a in args:
    if a == "|": rows.append([]); continue
    name, path = a.split("=", 1); s = np.load(path).astype(np.float32); n = s.shape[0]; c = n // 2
    g = s[:, :, 1]; bg = np.median(np.concatenate([g[:70, :70].ravel(), g[-70:, -70:].ravel()]))
    ref = float(np.median(g[c - 15:c + 15, c - 15:c + 15]) - bg)                      # the globe's middle
    v = np.clip((s - bg) / ref * 0.72 * gain, 0, 1) ** (1 / 2.2)
    crop = v[c - 140:c + 140, c - 215:c + 215, ::-1]; img = (crop * 255 + 0.5).astype(np.uint8).copy()
    cv2.putText(img, name, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA); rows[-1].append(img)
w = max(len(r) for r in rows)
for r in rows:
    while len(r) < w: r.append(np.zeros_like(rows[0][0]))
cv2.imwrite(out, np.vstack([np.hstack(r) for r in rows])); print(out)
