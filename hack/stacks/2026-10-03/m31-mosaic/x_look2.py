"""Quick look with the mosaic renderer (not a deliverable): python x_look2.py set soft pedestal cp_min cp_k chroma [scale]"""
import sys, numpy as np, cv2
from mcommon import *
from mrender import *
name = sys.argv[1]; soft, ped, cpcore, cppan, chroma = [float(v) for v in sys.argv[2:7]]; f = 2; target = float(sys.argv[7]) if len(sys.argv) > 7 else 0; smax = float(sys.argv[8]) if len(sys.argv) > 8 else 2.0
m = np.load(W(name + '_rgb.npy')); nz = np.load(W(name + '_noise.npy'))
m[nz <= 0] = np.nan
b = bin2(m, f=f); n2 = bin2(np.where(nz > 0, nz, np.nan), f=f) * 0.6
n2 = np.nan_to_num(n2, nan=0)
if target > 0: b, sg, _ = adaptive_smooth(b, n2, target, smax); print('sigma px: median %.2f max %.2f' % (np.median(sg[n2 > 0]), sg.max()))
cs = bin2(np.load(W(name + '_coreshare.npy')).astype(np.float32) / 255, f=f)
img = stretch(b, cpcore * cs + cppan * (1 - cs), 14000.0, soft, ped, chroma)
tag = '%s_s%g_p%g_c%g_k%g_t%g' % (name, soft, ped, cpcore, cppan, target)
cv2.imwrite(W('look2_%s.png' % tag), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
small = cv2.resize(img, None, fx=f / 8, fy=f / 8, interpolation=cv2.INTER_AREA); cv2.imwrite(W('look2_%s_small.jpg' % tag), cv2.cvtColor(small, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
print(img.shape, tag)
