"""Is the stack sharper than a single frame? Same crop, same tone curve, side by side; and the
detail limit of each measured the way spectrum.py does it (signal above twice the noise floor)."""
import sys, os, json, numpy as np, cv2
sys.argv = [sys.argv[0], os.path.expanduser(sys.argv[1])] + sys.argv[2:]
import stack, moonlib
SRC = sys.argv[1]; x, y, n = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]); out = sys.argv[5]
single_name = sys.argv[6] if len(sys.argv) > 6 else stack.T["reference"]
ys, xs = stack.grid(); zero = np.zeros((len(ys), len(xs)), np.float32)
f = moonlib.load(moonlib.raw_path(SRC, single_name)); mx, my = stack.maps_for(single_name, zero, zero)
single = cv2.remap(f["g"], mx, my, cv2.INTER_LANCZOS4)
tiles = [("one frame (%s)" % single_name, single)]
for tag in sys.argv[7:] or ["keep100", "keep30"]:
    tiles.append((tag, np.load(os.path.join(stack.HERE, "stack-%s.npz" % tag))["img"][:, :, 1]))

def limit(t):
    N = t.shape[0]; t = t / t.mean() - 1
    w = np.hanning(N)[:, None] * np.hanning(N)[None, :]
    P = np.abs(np.fft.fftshift(np.fft.fft2(t * w))) ** 2
    yy, xx = np.indices(P.shape); rr = np.hypot(yy - N // 2, xx - N // 2).astype(int)
    prof = np.bincount(rr.ravel(), P.ravel()) / np.maximum(np.bincount(rr.ravel()), 1)
    floor = np.median(prof[int(N * 0.42):N // 2])
    above = np.where(prof[2:N // 2] / floor > 2.0)[0]; k = above.max() + 2
    return N / k * moonlib.ARCSEC_PER_PX, prof, floor

ref_white = np.percentile(tiles[-1][1][y:y + n, x:x + n], 99.5)
row = []
for label, img in tiles:
    t = img[y:y + n, x:x + n]
    lim, prof, floor = limit(t.astype(np.float64))
    noise = float(np.sqrt(floor))
    print("%-22s detail to %.1f arcsec   noise floor (relative) %.3g" % (label, lim, noise))
    v = np.clip(t * (np.percentile(tiles[-1][1][y:y+n, x:x+n], 50) / np.percentile(t, 50)) / ref_white, 0, 1) ** (1 / 2.2)
    v = cv2.resize((v * 255).astype(np.uint8), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.putText(v, label, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 255, 2); row.append(v)
cv2.imwrite(out, np.hstack(row)); print(out)
