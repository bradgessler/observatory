"""Is the glow that was taken off the right amount, on the lit ground itself? (a check, not a step)

The same ground was photographed clear and through cloud. If cloud only dimmed and added a glow,
cloudy = T * clear + pedestal, and after the glow is taken off the pedestal must be zero. Bright
and dark ground side by side (mare against highland, the terminator's slope) fix both numbers:
in every block of 160x160 cells of shared lit ground a line is fitted, and the pedestals' median
is printed, with the glow left in and with it taken off.
The first cloudy frame given should be another clear one: it shows what the test itself reads when
there is nothing to find (a couple of counts: the two frames are not equally sharp).
Usage: glowcheck.py <raw dir> out.json clear.JPG cloudy.JPG [cloudy.JPG ...]"""
import json, os, sys, numpy as np, cv2
import moonlib
SRC = os.path.expanduser(sys.argv[1]); OUT = sys.argv[2]; A = sys.argv[3]
T = json.load(open("transforms-sensor.json" if os.path.exists("transforms-sensor.json") else "transforms.json"))["placed"]; C = 16383 - 512; rec = {}
def green(name, glow):
    moonlib.GLOW_DIR = os.path.join(moonlib.HERE, "glow") if glow else "none"
    pl, wb, clip = moonlib.planes(moonlib.raw_path(SRC, name))
    g = [p for c, x, y, p in pl if c == "G"]
    return cv2.GaussianBlur((g[0] + g[1]) / 2 / moonlib.GAIN, (0, 0), 4), clip
ga, ca = green(A, True); h, w = ga.shape; MA = np.vstack([T[A]["M"], [0, 0, 1]])
for B in sys.argv[4:]:
    out = []
    for glow in (False, True):
        gb, cb = green(B, glow); MB = np.vstack([T[B]["M"], [0, 0, 1]]); B2A = (np.linalg.inv(MA) @ MB)[:2]
        gbw = cv2.warpAffine(gb, B2A, (w, h), flags=cv2.INTER_LINEAR); ok = cv2.warpAffine((~cb).astype(np.float32), B2A, (w, h), flags=cv2.INTER_LINEAR) > 0.999
        m = ok & ~ca & (ga > 0.0015)
        m[:40] = False; m[-40:] = False; m[:, :40] = False; m[:, -40:] = False
        ped, slope, n = [], [], 0
        for y in range(0, h - 160, 160):
            for x in range(0, w - 160, 160):
                mm = m[y:y + 160, x:x + 160]
                if mm.mean() < 0.6:
                    continue
                a = ga[y:y + 160, x:x + 160][mm]; b = gbw[y:y + 160, x:x + 160][mm]
                if np.percentile(a, 95) < 1.5 * np.percentile(a, 5):      # too even a block fixes nothing
                    continue
                s, p = np.polyfit(a, b, 1); ped.append(p * C); slope.append(s); n += 1
        out.append((np.median(ped) if ped else np.nan, np.percentile(ped, 25) if ped else np.nan, np.percentile(ped, 75) if ped else np.nan, np.median(slope) if slope else np.nan, n))
    rec[B] = dict(pedestal_counts_glow_left_in=round(float(out[0][0]), 1), pedestal_counts_glow_taken_off=round(float(out[1][0]), 1), quartiles_taken_off=[round(float(out[1][1]), 1), round(float(out[1][2]), 1)],
                  transmitted=round(float(out[1][3]), 2), blocks=out[1][4])
    print("%s against clear %s:  glow left in: pedestal %6.1f counts (quartiles %6.1f..%6.1f), T %.2f   taken off: pedestal %5.1f counts (%5.1f..%5.1f), T %.2f   [%d blocks]" % (
        B[9:15], A[9:15], out[0][0], out[0][1], out[0][2], out[0][3], out[1][0], out[1][1], out[1][2], out[1][3], out[1][4]))
json.dump(dict(clear_frame=A, note="cloudy = T * clear + pedestal, fitted in blocks of 160x160 cells of shared lit ground; counts of 15871", frames=rec), open(OUT, "w"), indent=1)
