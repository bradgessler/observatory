"""Turn a linear stack into pictures to look at. A fixed tone curve (gamma 2.2, white at the 99.9th
percentile); no sharpening unless asked. Usage: show.py stack-keep30.npz out.png [x y w h]"""
import sys, numpy as np, cv2
z = np.load(sys.argv[1]); img = z["img"]
white = np.percentile(img[img.sum(2) > 0], 99.9)
out = np.clip(img / white, 0, 1) ** (1 / 2.2)
if len(sys.argv) > 3:
    x, y, w, h = map(int, sys.argv[3:7]); out = out[y:y + h, x:x + w]
cv2.imwrite(sys.argv[2], (out[:, :, ::-1] * 255 + 0.5).astype(np.uint8))
print(sys.argv[2], out.shape, "white", round(float(white), 4))
