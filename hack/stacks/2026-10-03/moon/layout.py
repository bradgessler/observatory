"""A look at where the frames sit (not a deliverable): every placed frame, scaled by its one
number, feather-averaged at 1/4 of the working scale, plus the outline of each pointing."""
import json, os, sys, numpy as np, cv2
import moonlib, stack
SRC = os.path.expanduser(sys.argv[1]); out = sys.argv[2]
names = sorted(stack.T["placed"])
size = (stack.CW // 4 + 1, stack.CH // 4 + 1)
num = np.zeros(size[::-1], np.float64); den = np.zeros_like(num)
outl = np.zeros(size[::-1] + (3,), np.uint8)
H, W = stack.T["shape"]
for i, n in enumerate(names):
    f = moonlib.load(moonlib.raw_path(SRC, n)); M = stack.placed(n) / 4.0
    g = cv2.warpAffine(cv2.GaussianBlur(f["g"], (0, 0), 2.0), M, size, flags=cv2.INTER_LINEAR)
    w = cv2.warpAffine(stack.usable(f) * stack.edge_fade(f["g"].shape, 64), M, size, flags=cv2.INTER_LINEAR)
    k = stack.scalar(n); num += g * k * w / k ** 2; den += w / k ** 2
    c = (np.array([[0, 0, 1], [W, 0, 1], [W, H, 1], [0, H, 1]], float) @ M.T).astype(np.int32)
    hms = int(n[9:15]); col = (255, 255, 255)
    cv2.polylines(outl, [c.reshape(-1, 1, 2)], True, (80 + (hms * 37) % 175, 80 + (hms * 91) % 175, 80 + (hms * 53) % 175), 1)
img = num / np.maximum(den, 1e-6); img[den <= 0] = 0
v = np.clip(img / np.percentile(img[img > 0.02], 99.5), 0, 1) ** (1 / 2.2)
g8 = (v * 255).astype(np.uint8)
cv2.imwrite(out, np.maximum(cv2.cvtColor(g8, cv2.COLOR_GRAY2BGR), outl // 2))
print(size, "canvas origin", stack.X0, stack.Y0)
