"""Restore the contrast the blur took, as far as the data allows, in one step (a Wiener filter).

Two measured curves decide everything, and neither is a guess about the Moon:
  the blur's spectrum MTF(f), from the Moon's sunlit limb in this stack (psf.py): how much contrast
  survives at each fineness. The larger of the measurement and its fitted curve is used, so the
  filter never boosts by more than the limb itself shows was lost;
  the signal fraction S(f) = 2c / (1 + c), from how well two stacks of separate halves of the
  frames agree at each fineness (frc.py): the share of what the stack shows there that is real.
At each fineness the filter multiplies by S(f) / MTF(f): undo the blur, times the share that is
signal. Where the halves agree, contrast is restored in full; where they stop agreeing the filter
lets go, and past that it passes nothing new. Brightness (R + 2G + B) is filtered and each colour
scaled by the same ratio.

Changed for the last-quarter mosaic:
  - zones (zones.py): the blur and the noise were not the same down the Moon, so each zone is
    filtered with its own curves and the three results are blended down the picture (each zone's
    result counts fully at the zone's middle row and fades linearly to the next middle).
    A zone's blur curve is the sharper, at each fineness, of two: its own stretch of limb, and
    the whole limb. So no zone is boosted by more than its own limb supports (the north's limb is
    sharper than the whole limb's average, and gets less boost at 4-6 arcsec than the average
    would give it), and no zone is boosted on the word of a limb blurrier than the average: the
    far southern limb measured 2.8 arcsec, but with that curve the craters inland of it came out
    with black moats, the mark of a blur assumed wider than it was there;
  - gentle: no fineness is multiplied by more than CAP (3). Uncapped, the clear north asked for
    10x and more at 1.5 arcsec, where the limb's spectrum is no longer measured but extrapolated,
    and the blurred south for 5-7x: the first came out as grain, the second as hard black
    outlines round every crater. Both were looked at and thrown away;
  - the holds against ringing are stronger (see the comment at the holds): at the limb and in the
    night side the plain stack shows through;
  - PNG and JPEG with the plain picture's own tone curve (white at the 99.9th percentile of the
    plain picture's lit ground), so the two can be compared. No text or marks.

Usage: wiener.py stack.npz measured.json zones.json outdir stem [--strength s] [--cap c]
       (zones.json: [{"name", "rows": [y0, y1], "psf": its limb's psf.npz, "psf_whole_limb": the whole limb's, "frc": frc.npz}, ...])
"""
import sys, os, json, numpy as np, cv2
args = sys.argv[1:]; strength = 1.0; CAP = 3.0
DARK = 0.02; DIM = 0.10
if "--cap" in args:
    i = args.index("--cap"); CAP = float(args[i + 1]); args = args[:i] + args[i + 2:]
if "--strength" in args:
    i = args.index("--strength"); strength = float(args[i + 1]); args = args[:i] + args[i + 2:]
stack, measured, zones_path, outdir, stem = args[:5]
zs = np.load(stack); img = zs["img"].astype(np.float32); depth = zs["depth"]; m = json.load(open(measured)); zones = json.load(open(zones_path))
h, w = img.shape[:2]; arc = m["arcsec_per_px"]
for c, key in ((0, "red_shift_px"), (2, "blue_shift_px")):
    dx, dy = m[key]
    img[:, :, c] = cv2.warpAffine(img[:, :, c], np.float32([[1, 0, -dx], [0, 1, -dy]]), (w, h), flags=cv2.INTER_LANCZOS4)
img = np.clip(img, 0, None) * (depth[:, :, None] > 0); white = float(np.percentile(img[cv2.GaussianBlur(img[:, :, 1], (0, 0), 3) > 0.05], 99.9))
L = (img[:, :, 0] + 2 * img[:, :, 1] + img[:, :, 2]) / 4


def blur_curve(psf_path, f):
    """Contrast kept at each fineness: the larger of the limb's measured spectrum and its fitted curve."""
    pz = np.load(psf_path); f0, pw = float(pz["f0"]), float(pz["power"])
    mf, mm = pz["mtf_f"], pz["mtf"]; mm = np.convolve(np.pad(mm, 2, mode="edge"), np.ones(5) / 5, "valid")
    return np.maximum(np.exp(-(np.maximum(f, 1e-6) / f0) ** pw), np.interp(f, mf, mm))


def curves(psf_path, whole_path, frc_path):
    """A zone's gain at each fineness, from its blur's spectrum and its signal fraction."""
    fz = np.load(frc_path); f = fz["f"]; frac = fz["signal_fraction"]
    mtf = blur_curve(psf_path, f)
    if whole_path:
        mtf = np.maximum(mtf, blur_curve(whole_path, f))
    gain = 1 + strength * (frac / np.maximum(mtf, 1e-4) - 1); gain[0] = 1
    gain[frac <= 0] = np.minimum(gain[frac <= 0], 0) if strength >= 1 else gain[frac <= 0]
    asked = float(gain.max()); gain = np.clip(gain, 0, CAP)
    report = {"%.1f arcsec" % per: dict(blur_keeps=round(float(np.interp(arc / per, f, mtf)), 4), signal_fraction=round(float(np.interp(arc / per, f, frac)), 3), gain=round(float(np.interp(arc / per, f, gain)), 2))
              for per in (10, 6, 4, 3.5, 3, 2.7, 2.5, 2.3, 2.1, 1.9, 1.7, 1.5)}
    return f, gain, report, asked


# -- apply: each zone's filter, blended down the picture ---------------------------------------------
pad = 128; Lp = cv2.copyMakeBorder(L, pad, pad, pad, pad, cv2.BORDER_REFLECT)
fy, fx = np.meshgrid(np.fft.fftfreq(Lp.shape[0]), np.fft.rfftfreq(Lp.shape[1]), indexing="ij"); fr = np.hypot(fx, fy); del fx, fy
FL = np.fft.rfft2(Lp)
mid = np.array([np.mean(z["rows"]) for z in zones]); yy = np.arange(h, dtype=np.float32)
Ls = np.zeros_like(L); zrep = []
for i, z in enumerate(zones):
    f, gain, report, asked = curves(z["psf"], z.get("psf_whole_limb"), z["frc"])
    wy = np.ones(h, np.float32)                                    # this zone's share, row by row
    if i > 0:
        wy = np.minimum(wy, np.clip((yy - mid[i - 1]) / (mid[i] - mid[i - 1]), 0, 1))
    if i < len(zones) - 1:
        wy = np.minimum(wy, np.clip((mid[i + 1] - yy) / (mid[i + 1] - mid[i]), 0, 1))
    Ls += wy[:, None] * np.fft.irfft2(FL * np.interp(fr, f, gain, right=0), s=Lp.shape)[pad:-pad, pad:-pad].astype(np.float32)
    zrep.append(dict(zone=z["name"], rows=z["rows"], middle_row=float(mid[i]), limb_arc_deg=z.get("limb_arc_deg"), peak_gain=round(float(gain.max()), 2), peak_gain_asked_before_the_cap=round(asked, 1), gain_at=report,
                     blur=json.load(open(z["psf"].replace(".npz", ".json"))), blur_curve_used="the sharper of this zone's limb and the whole limb, at each fineness", halves_agree=json.load(open(z["frc"].replace(".npz", ".json")))))
    print("%-6s peak gain %.1f  " % (z["name"], gain.max()) + "  ".join("%s x%.1f" % (k.split()[0] + '"', v["gain"]) for k, v in report.items()))
del FL, fr

# At the Moon's edge any such filter rings: a dark moat just outside, a faint bright line beyond it,
# a bright rim just inside. None is real. Two holds, both simply the plain picture showing through:
#   the limb: from RIM px inside the fitted limb outward (and all the sky beyond it) the picture
#   fades to the plain stack, so the Moon's edge is the edge as it was measured;
#   the night side: where the plain picture (smoothed 3 px) is below DARK of the white point, the
#   plain stack again, so the filter cannot draw rings into the dark round a lit peak or amplify
#   the noise there. Lit peaks themselves are above DARK and are restored.
# And inside the limb, within LIMB px, the old hold still applies: the restored brightness stays
# between the darkest and brightest plain pixels REACH px around it.
LIMB, REACH = 30 * arc ** -1 * 0.3955, 16 * arc ** -1 * 0.3955   # 11.9 and 6.3 arcsec
RIM = 16 * arc ** -1 * 0.3955                                    # 6.3 arcsec
cxm, cym = m["moon_centre_px"]
Y, X = np.indices(L.shape, dtype=np.float32); rad = np.hypot(X - cxm, Y - cym); del X, Y
dist = np.abs(rad - m["moon_radius_px"])
hold = np.clip((LIMB - dist) / (LIMB / 3), 0, 1)
ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * int(REACH) + 1, 2 * int(REACH) + 1))
lo, hi = cv2.erode(L, ker), cv2.dilate(L, ker)
Ls = hold * np.clip(Ls, lo, hi) + (1 - hold) * Ls
# the dim ground along the terminator: round a lit peak the filter digs a moat darker than the night
# beside it. Where the plain picture (smoothed REACH px) is below DIM of white, the restored
# brightness cannot go below the darkest plain pixel within reach.
dim = np.clip((DIM * white - cv2.GaussianBlur(L, (0, 0), REACH)) / (DIM * white / 2), 0, 1)
Ls = dim * np.maximum(Ls, lo) + (1 - dim) * Ls
w_limb = np.clip((rad - (m["moon_radius_px"] - RIM)) / (0.75 * RIM), 0, 1)
w_night = np.clip((DARK * white - cv2.GaussianBlur(L, (0, 0), 3)) / (DARK * white / 2), 0, 1)
plain = np.maximum(w_limb, w_night)
Ls = plain * L + (1 - plain) * Ls
ratio = np.clip(Ls / np.maximum(L, 1e-6), 0, 8); out = img * ratio[:, :, None] * (L[:, :, None] > 0)
os.makedirs(outdir, exist_ok=True)
over = float((out.max(2) > white).mean())
v8 = ((np.clip(out / white, 0, 1) ** (1 / 2.2))[:, :, ::-1] * 255 + 0.5).astype(np.uint8)
cv2.imwrite(os.path.join(outdir, stem + ".png"), v8, [cv2.IMWRITE_PNG_COMPRESSION, 9])
cv2.imwrite(os.path.join(outdir, stem + ".jpg"), v8, [cv2.IMWRITE_JPEG_QUALITY, 92])
lit = L > DARK * white
json.dump(dict(method="Wiener filter on brightness (R+2G+B)/4, colours scaled by the same ratio; one filter per zone, blended down the picture", strength=strength, gain_cap=CAP,
               zones=zrep,
               limb_hold=dict(zone_px=round(float(LIMB), 1), reach_px=round(float(REACH), 1), note="within the zone the restored brightness stays between the darkest and brightest plain pixels within reach"),
               limb_rim_hold=dict(from_px_inside_the_limb=round(float(RIM), 1), note="from there outward, and in all the sky beyond the limb, the plain stack shows through"),
               terminator_hold=dict(where="plain picture (smoothed %.0f px) below %.0f%% of white" % (REACH, 100 * DIM), note="the restored brightness cannot go below the darkest plain pixel within %.0f px" % REACH),
               night_side_hold=dict(where="plain picture (smoothed 3 px) below %.0f%% of white" % (100 * DARK), note="the plain stack shows through: nothing is restored in the dark"),
               share_of_lit_ground_restored_in_full_pct=round(100 * float(((plain < 0.01) & lit).sum() / max(lit.sum(), 1)), 1),
               pixels_above_white_pct=round(100 * over, 4),
               colour_planes=dict(red_moved_px=[-q for q in m["red_shift_px"]], blue_moved_px=[-q for q in m["blue_shift_px"]]),
               tone_curve_for_png_and_jpeg=dict(white=white, gamma=2.2, black=0.0, note="the plain picture's white"), size=[w, h], arcsec_per_px=arc), open(os.path.join(outdir, stem + ".json"), "w"), indent=1)
print("saved", stem)
