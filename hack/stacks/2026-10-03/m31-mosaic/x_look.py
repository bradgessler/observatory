"""Quick looks at a combined mosaic (not a deliverable)."""
import sys, numpy as np, cv2
from mcommon import *
from render import asinh_stretch
name = sys.argv[1]; soft = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0; ped = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0; sig = float(sys.argv[4]) if len(sys.argv) > 4 else 0.0
m = np.load(W(name + '_rgb.npy'))
def binn(a, f):
    h, w = a.shape[0] // f * f, a.shape[1] // f * f
    b = a[:h, :w].reshape(h // f, f, w // f, f, -1)
    ok = np.isfinite(b).all(4, keepdims=True)
    n = ok.sum((1, 3)); s = np.where(ok, b, 0).sum((1, 3))
    return np.where(n > 0, s / np.maximum(n, 1), np.nan).astype(np.float32)
for f in (8,):
    b = binn(m, f); nodata = ~np.isfinite(b).all(2)
    bb = np.nan_to_num(b, nan=0.0)
    if sig > 0:
        okf = (~nodata).astype(np.float32); bb = cv2.GaussianBlur(bb * okf[:, :, None], (0, 0), sig) / np.maximum(cv2.GaussianBlur(okf, (0, 0), sig), 1e-3)[:, :, None]
    img = asinh_stretch(bb, white=14000.0, soft=soft, pedestal=ped, chroma_sigma=2.0)
    img[nodata] = 0
    cv2.imwrite(W('look_%s_f%d_s%d.jpg' % (name, f, int(soft))), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(img.shape)
