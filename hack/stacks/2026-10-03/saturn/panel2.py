"""Enlarged side-by-side at one stretch, twice: the ordinary stretch, and a hard one that shows only the top third of the brightness range
(where a ring drawn by the filter would show on the globe). Usage: panel2.py out.png label=file.npy ..."""
import sys, numpy as np, cv2
out = sys.argv[1]; top, bot = [], []
for a in sys.argv[2:]:
    name, path = a.split("=", 1); s = np.load(path).astype(np.float32); n = s.shape[0]; c = n // 2
    g = s[:, :, 1]; bg = np.median(np.concatenate([g[:70, :70].ravel(), g[-70:, -70:].ravel()])); ref = float(np.median(g[c - 15:c + 15, c - 15:c + 15]) - bg)
    v = (s - bg) / ref; crop = v[c - 110:c + 110, c - 190:c + 190, ::-1]
    a1 = np.clip(crop * 0.72, 0, 1) ** (1 / 2.2); a2 = np.clip((crop.mean(2, keepdims=True) - 0.55) / 0.6, 0, 1).repeat(3, 2)
    for arr, dst in ((a1, top), (a2, bot)):
        img = cv2.resize((arr * 255 + 0.5).astype(np.uint8), None, fx=1.3, fy=1.3, interpolation=cv2.INTER_CUBIC); cv2.putText(img, name, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA); dst.append(img)
cv2.imwrite(out, np.vstack([np.hstack(top), np.hstack(bot)])); print(out)
