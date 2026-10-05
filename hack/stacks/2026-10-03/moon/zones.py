"""The blur and the noise, zone by zone down the Moon.

This night neither was the same everywhere. The north was taken under clear sky, the middle and
south through cloud (less light, so more noise once scaled back up). And the blur measured on the
limb runs from about 1.5 arcsec in the north and middle to 2.8 in the south, where the Moon sat
near the edge of the frame in every picture that shows it (an SCT's field is curved, and this
one's collimation is a little off). One blur curve and one noise curve for the whole picture
would sharpen the north more than its own limb supports and the south less.

So the picture is cut into three zones by two points on the sunlit limb (BOUNDS, screen degrees):
north of 205 (the rows clear frames cover), 205 to 152, and south of 152 (where the limb's blur
steps up). For each zone: the blur's spectrum from its own stretch of limb (psf.py), and how well
two half-stacks agree on its own rows (frc.py, 256-px tiles so the narrow horns have tiles).
wiener.py restores each zone with its own curves and blends the three down the picture (and says
why a zone's blur curve is never taken blurrier than the whole limb's).

Writes psf-2x-<zone>.npz/.json, frc-2x-<zone>.npz/.json and zones.json.
Usage: zones.py stack-2x.npz half-a.npz half-b.npz measured-2x.json arcsec_per_px whole-limb-psf.npz"""
import json, os, subprocess, sys, numpy as np
stack, a, b, measured, arc, whole = sys.argv[1:7]
m = json.load(open(measured)); (cx, cy), R = m["moon_centre_px"], m["moon_radius_px"]; h = np.load(a)["depth"].shape[0]
BOUNDS = (205.0, 152.0); LIT = (262.0, 98.0)          # the bright limb runs from 262 (north) round by 180 (west) to 98 (south)
row = lambda deg: int(round(cy + R * np.sin(np.radians(deg))))
zones = [("north", (BOUNDS[0], LIT[0]), (0, row(BOUNDS[0]))), ("middle", (BOUNDS[1], BOUNDS[0]), (row(BOUNDS[0]), row(BOUNDS[1]))), ("south", (LIT[1], BOUNDS[1]), (row(BOUNDS[1]), h))]
out = []
for name, (a0, a1), rows in zones:
    subprocess.run([sys.executable, "psf.py", stack, "2", "psf-2x-%s.npz" % name], env=dict(os.environ, MOON_ARC="%g:%g" % (a0, a1), MOON_LIMB=measured), check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, "frc.py", a, b, arc, "frc-2x-%s.npz" % name], env=dict(os.environ, MOON_TILE="256", MOON_ROWS="%d:%d" % rows), check=True, stdout=subprocess.DEVNULL)
    P = json.load(open("psf-2x-%s.json" % name)); F = json.load(open("frc-2x-%s.json" % name))
    out.append(dict(name=name, rows=list(rows), limb_arc_deg=[a0, a1], psf="psf-2x-%s.npz" % name, psf_whole_limb=whole, frc="frc-2x-%s.npz" % name, blur=P, halves_agree=F))
    print("%-6s rows %4d-%4d  limb %3.0f-%3.0f deg: blur FWHM %.2f arcsec (edge 10-90 %.2f), contrast kept at 4 arcsec %.2f, at 3 arcsec %.2f;  halves agree to %.2f / %.2f arcsec (%d tiles)" % (
        name, rows[0], rows[1], a0, a1, P["psf_fwhm_arcsec"], P["edge_10_90_arcsec"], P["mtf_at"]["4.0 arcsec"], P["mtf_at"]["3.0 arcsec"], F["resolution_arcsec"]["half"], F["resolution_arcsec"]["one_seventh"], F["tiles"]))
json.dump(out, open("zones.json", "w"), indent=1)
