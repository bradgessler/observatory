"""Put the sharp run's outputs in their folder with one recipe: what was used, what was left out and why, every parameter, and the
measurements the choices rest on, set against the earlier run. Refuses to overwrite anything.
recipe3.py is recipe.py rewritten for the sharp run of 2026-10-04 (08:46 to 09:05 UTC).
Usage: recipe3.py <out folder>"""
import sys, os, json, hashlib, shutil, time, glob
import numpy as np, cv2
from PIL import Image
from metrics import measure
from rounds import kernel, rim_of
OUT = os.path.expanduser(sys.argv[1]); STILLS = os.path.expanduser("~/.observatory/nights/2026-10-03-a6000/stills"); RESTACK = os.path.expanduser("~/.observatory/nights/2026-10-03-a6000/saturn/restack")
if os.path.exists(OUT) and os.listdir(OUT): sys.exit("will not write into " + OUT + ": it is not empty")
os.makedirs(os.path.join(OUT, "scripts"), exist_ok=True); os.makedirs(os.path.join(OUT, "checks"), exist_ok=True)
J = lambda p: json.load(open(p)); r4 = lambda x: round(float(x), 4)
def put(src, name):
    dst = os.path.join(OUT, name)
    if os.path.exists(dst): sys.exit("will not overwrite " + dst)
    shutil.copyfile(src, dst); return dst
def jpg(png, name):
    dst = os.path.join(OUT, name)
    if os.path.exists(dst): sys.exit("will not overwrite " + dst)
    Image.fromarray(np.asarray(Image.open(png).convert("RGB"))).save(dst, quality=92, optimize=True); return dst      # from the pixels alone: no metadata carried
old = J(os.path.join(RESTACK, "saturn-and-moons-restack.json")); base = J("final/saturn-and-moons-sharp.json"); clean = J("final/saturn-and-moons-sharp-clean.json"); rec = base["planet"]["recipe"]; fin = rec["finish"]; mrec = base["moons"]["recipe"]
names = J("moonfield/names.json"); who = J("moonfield/whois.json"); who_after = J("moonfield-after-dir/whois.json"); UNIT = 0.3955; TRUE = who["arcsec_per_sensor_px"]; K = TRUE / UNIT
# -- the frame list ---------------------------------------------------------------------------------------------------------------
fl = J("frames-fixed.json"); now = J("frames.json"); run = [f for f in fl["frames"] if "20261004-0846" <= f["name"] < "20261004-0910"]
planet = [f for f in run if f["iso"] == 800 and abs(f["exp"] - 0.025) < 1e-6]; longs = [f for f in run if f["iso"] == 6400 and f["exp"] == 2.0]
late = [f["name"] for f in now["frames"] if "20261004-0846" <= f["name"] < "20261004-0910" and f["name"] not in {g["name"] for g in fl["frames"]}]
frame_list = dict(taken_at_utc=fl["taken_at"], rule="a frame counts when its .ARW, .JPG and .json are all present and the .ARW is the size its sidecar says (pickframes.py)", window="stamps 20261004-0846 to 20261004-0909",
                  planet_frames_complete=len(planet), planet_first=planet[0]["name"], planet_last=planet[-1]["name"], long_frames_complete=len(longs), long_frames=[f["name"] for f in longs],
                  arrived_after_the_list=late, arrived_after_note="20261004-090956-DSC01547 (2 s ISO 6400) finished copying after the list was taken; graded afterwards: Titan is a 28 arcsec trail (the mount was already moving to the next target), so it would not have been used. Everything stamped 0914 and later is another target (30 s frames).",
                  note="When the work began DSC01545 was still arriving (.ARW.part) and eight 2 s frames after the planet run were complete; by the time the list was fixed there were ten.")
# -- how many frames to keep: the measurements --------------------------------------------------------------------------------------
def plain(path):
    s = np.load(path).astype(np.float32); m, _ = measure(s[:, :, 1]); _, grain, _ = rim_of(s.sum(2) / 3, s[:, :, 1])
    return dict(gap_contrast=m["gap_contrast"], gap_contrast_east_west=[m["east"]["contrast"], m["west"]["contrast"]], ansa_width_fwhm_arcsec=m["ansa_width_fwhm_arcsec"], grain_on_globe=r4(grain), sky_noise_of_globe=round(m["noise_of_globe"], 5), ring_line_deg=m["ring_line_deg"])
keep = {str(k): plain("stacks/s%d.npy" % k) for k in (8, 12, 16, 20, 30, 47)}
keep_clear = {str(k): plain("stacks/c%d.npy" % k) for k in (12, 16, 20)}
earlier_plain = plain("stacks/earlier16.npy")
def rounds_table(path, psf, rounds=(0, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 20)):
    s = np.load(path).astype(np.float32); Kk = kernel(psf[0], psf[1], np.radians(psf[2])); b = lambda a: cv2.filter2D(a, -1, Kk, borderType=cv2.BORDER_REFLECT_101); L = np.maximum(s.sum(2) / 3, 1e-7).astype(np.float32); est = L.copy(); done = 0; tab = {}
    for r in rounds:
        while done < r: est *= b(L / np.maximum(b(est), 1e-7)); done += 1
        m, _ = measure(s[:, :, 1] * (est / L)); rim, grain, _ = rim_of(est, s[:, :, 1])
        tab[str(r)] = dict(false_rim_on_globe=round(rim, 3), gap_contrast=m["gap_contrast"], ansa_width_fwhm_arcsec=m["ansa_width_fwhm_arcsec"], ring_ansa_level_of_globe=[m["east"].get("ansa_level"), m["west"].get("ansa_level")], grain_on_globe=r4(grain))
    return tab
psf_of = lambda stem: (lambda f: (f["psf_fwhm_arcsec"][0], f["psf_fwhm_arcsec"][1], f["psf_long_axis_deg_in_picture"]))(J(stem + ".json")["finish"])
rounds = {}
for k in (12, 16, 20, 30):
    p = psf_of("stacks/s%d" % k); rounds["%d frames" % k] = dict(blur_fwhm_arcsec=[p[0], p[1]], blur_long_axis_deg=p[2], **rounds_table("stacks/s%d.npy" % k, p))
ofin = old["planet"]["recipe"]["finish"]; po = (ofin["psf_fwhm_arcsec"][0], ofin["psf_fwhm_arcsec"][1], ofin["psf_long_axis_deg_in_picture"])
rounds["earlier run, 16 frames"] = dict(blur_fwhm_arcsec=[po[0], po[1]], blur_long_axis_deg=po[2], **rounds_table("stacks/earlier16.npy", po, (0, 5, 8)))
halves = J("stacks/s16-halves.json"); rlmodel = J("stacks/s16-rlmodel.json"); psfm = J("stacks/psfmodel.json"); tf = J("stacks/s16-titan-fine.json"); R16 = rounds["16 frames"]; RND = str(fin["rounds"])
choice = dict(
    measures=dict(gap_contrast="green, along the ring line: (ring ansa peak - the dip between globe and ring) / (peak + dip), both sides averaged; larger is sharper",
                  ansa_width_fwhm_arcsec="width across the ring 18.5 arcsec from the centre; smaller is sharper (the ring itself is about 3 arcsec thick there)",
                  false_rim_on_globe="how much the globe brightens outward before the limb, away from the ring line, as a fraction of its brightness; the plain stack never does, so this is what the deconvolution drew",
                  grain_on_globe="pixel-to-pixel structure on the globe as a fraction of its brightness (noise and real fine detail together; halves.py separates them)",
                  unit="arcsec at the earlier scripts' 0.3955 per px, as in the restack recipe; multiply by %.4f for the measured scale" % K),
    plain_stack_by_frames_kept=keep, plain_stack_clear_sky_frames_only=dict(note="only the 35 frames at 0.9 of the median light or more (no cloud at all): slightly softer at every count, so the pipeline's own rule (0.6 to 1.6 of the median) was kept", **keep_clear),
    after_deconvolution_by_rounds=rounds,
    noise_by_split_halves_16_frames=dict(how="halves.py: the 16 kept frames in two halves of 8, each stacked and put through the same rounds; half the difference is the noise", **halves),
    rim_on_a_model_planet=dict(how="rlmodel.py: a Saturn of known shape blurred by exactly the blur divided out, with the stack's grain, through the same rounds", **rlmodel),
    blur_checks=dict(titan_on_the_planets_own_fine_grid=tf, note_titan="finish2.py measures Titan in a half-size green stack (the two green photosites averaged): %.2f x %.2f arcsec. Laid on the planet's own fine grid by the planet's own resampling it is %.2f x %.2f (green): the kernel divided out is about 4 percent wide on its long axis, which errs on the gentle side." % (fin["psf_fwhm_arcsec"][0], fin["psf_fwhm_arcsec"][1], tf["green"]["fwhm_arcsec"][0], tf["green"]["fwhm_arcsec"][1]),
                     from_the_planets_own_shape=psfm["s16"], note_planet="psfmodel.py fits the planet with a blur of %.1f x %.1f arcsec, wider than Titan's %.2f x %.2f (in the earlier run the two agreed). The points have a narrow core and wide skirts now (the given star half-flux diameter, 4.4 arcsec, is well above the 2.5 to 3.7 arcsec widths at half maximum; they are teardrop shaped): a Gaussian fitted to Titan follows the core, the planet's gap contrast feels the skirts. Dividing out the core alone under-corrects, which is the safe side: no rim appears at any number of rounds up to 20." % (psfm["s16"]["fwhm_along_ring_arcsec"], psfm["s16"]["fwhm_across_ring_arcsec"], fin["psf_fwhm_arcsec"][0], fin["psf_fwhm_arcsec"][1])),
    kept=rec["kept"], rounds=fin["rounds"],
    why="Kept: 8, 12, 16, 20, 30 and all 47 were stacked. Gap contrast in the plain stack %.3f, %.3f, %.3f, %.3f, %.3f, %.3f; ansa width %.2f, %.2f, %.2f, %.2f, %.2f, %.2f arcsec; sky noise %.5f, %.5f, %.5f, %.5f, %.5f, %.5f of the globe. "
        "12 and 16 are equally sharp (within 1 percent on both measures) and 16 is 13 percent quieter; 20 is 3 percent softer and 30 is 6 percent softer. 16 was kept: the sharpest count that is not noisier than it needs to be, and the earlier run's count, so the before and after compare like with like. "
        "Rounds: finish2.py's standing 8. The rule was to back off if a rim or ring appeared that the plain stack does not have: none did (false rim %.3f at 8 rounds, %.3f at 20; on the model planet %.3f at 8, %.3f at 12, %.3f at 20; the earlier run showed 5 percent at 8 and was backed off to 5). "
        "More than 8 was not taken although no rim appears: by 8 rounds the ring's width at the ansa (%.2f arcsec) has reached the ring's own thickness, the model planet starts to show a rim at 12, and the noise measured by split halves goes from %.4f of the globe (plain) to %.4f at 8 and %.4f at 20."
        % (*[keep[k]["gap_contrast"] for k in ("8", "12", "16", "20", "30", "47")], *[keep[k]["ansa_width_fwhm_arcsec"] for k in ("8", "12", "16", "20", "30", "47")], *[keep[k]["sky_noise_of_globe"] for k in ("8", "12", "16", "20", "30", "47")],
           R16["8"]["false_rim_on_globe"], R16["20"]["false_rim_on_globe"], rlmodel["8"]["with_grain_mean"], rlmodel["12"]["with_grain_mean"], rlmodel["20"]["with_grain_mean"], R16["8"]["ansa_width_fwhm_arcsec"], halves["rounds"]["0"]["noise_on_globe"], halves["rounds"]["8"]["noise_on_globe"], halves["rounds"]["20"]["noise_on_globe"]))
# -- the field's turning -------------------------------------------------------------------------------------------------------------
rot = J("rotation.json"); tb = rec["turned_back"]
turning = dict(deg_per_minute=tb["deg_per_minute"], reference_minute_of_day_utc=tb["reference_minute_of_day_utc"], reference="08:47:20 UTC, the middle of the two moon frames",
               measured_from="Titan's direction from Saturn in 5 groups of 12 short frames, 08:50 to 09:04 UTC (rottitan.py)", fit=rot, fit_note="rottitan.py is unchanged and still counts its minutes from 05:00 UTC: 230.23 is 08:50:14; its 'deg_at_0530' is the line carried back to 05:30 and means nothing here",
               also_seen_in=["the stars in the 2 s frames: the picture's up was %.2f deg east of north at 08:47:20 and %.2f at 09:06:34 (whois3.py, %d and %d stars): %+.4f deg per minute" % (who["up_east_of_north_deg"], who_after["up_east_of_north_deg"], who["stars_matched"], who_after["stars_matched"], (who_after["up_east_of_north_deg"] - who["up_east_of_north_deg"]) / 19.24),
                             "the ring line's angle in single frames (rotcheck.py): +0.036 deg per minute, scatter 0.46 deg per frame", "the plate solves of the two moon frames: 156.73 deg (up %.2f deg east of north)" % who["plate_solves_up_east_of_north_deg"]],
               against_the_earlier_run="the earlier run turned the other way and faster: %.4f deg per minute at 05:20 to 05:53. Between the runs the picture's up went from -18.65 to %.2f deg east of north. The brief expected 0.06 to 0.08 deg per minute; it is half that, and of the opposite sign." % (old["field_turning"]["deg_per_minute"], who["up_east_of_north_deg"]),
               why="the mount's axis is some degrees off the pole and both axes are driven, so the sky turns in the frame while the planet is held; how fast, and which way, depends on where the planet is in the sky")
# -- the 2 s frames ------------------------------------------------------------------------------------------------------------------
lg = {r["frame"]: r for r in J("longgrades.json")}; lp = {r["frame"]: r for r in J("longphot.json")}; best_rhea = max(r["Rhea"]["flux"] for r in lp.values() if "Rhea" in r); every = []
for f in longs:
    n = f["name"] + ".ARW"; g = lg[n]; p = lp[n]; t = p["Rhea"]["flux"] / best_rhea; used = n in mrec["used"]
    fate = "kept: clear sky" if used else "left out: behind cloud (Rhea shows %.2f of its light in the clear frames; the sky is %.1f times as bright)" % (t, p["sky"] / lp[mrec["used"][0]]["sky"])
    if n in ("20261004-090612-DSC01537.ARW", "20261004-090634-DSC01538.ARW", "20261004-090656-DSC01539.ARW"): fate += "; used for the second field (09:06:34) that shows which way each moon moved"
    every.append(dict(frame=n, fate=fate, saturn_at_px=[g["x"], g["y"]], rhea_light_of_the_clearest=round(t, 2), sky_level=round(p["sky"], 5), rhea_fwhm_arcsec=p["Rhea"]["fwhm_arcsec"], titan=dict(fwhm_arcsec=[g["titan"]["long_arcsec"], g["titan"]["short_arcsec"]], peak=g["titan"]["peak"], blown_out=p["Titan"]["clipped"] > 0), in_the_hot_pixel_map=True))
lateg = J("longgrade-late.json"); every.append(dict(frame=lateg["frame"], fate="arrived after the list; would have been left out: trailed (Titan %.0f x %.1f arcsec: the mount was moving)" % (lateg["titan"]["long_arcsec"], lateg["titan"]["short_arcsec"]), saturn_at_px=[float(lateg["x"]), float(lateg["y"])]))
widths_new = J("moonfield/moonfield-widths.json"); widths_old = J("moonfield/earlier-widths.json")
moons = dict(frames=mrec["frames"], used=mrec["used"], exposure="2 s ISO 6400", combine=base["moons"]["combine"], glare=base["moons"]["glare"], hot_pixels=mrec["hot_pixel_map"], colours=dict(slid_onto_green_half_px=mrec["colours_slid_onto_green_half_px"], left_to_move_in_the_composite_native_px=base["moons"]["colour_planes_moved_native_px"]),
             glare_by_symmetry=mrec["glare_by_symmetry"], glare_along_the_blown_out_edge=mrec["glare_along_the_blown_out_edge"], tone=base["moons"]["tone"], noise_near_the_planet=base["moons"]["noise_near_the_planet"], grey_beside_the_blown_out_patch=base["moons"]["grey_beside_the_blown_out_patch"],
             choice=dict(rule="2 s ISO 6400 frames of this run with a clear sky: Rhea at 0.9 or more of its light in the clearest frame", with_saturn=len(longs), kept=mrec["frames"],
                         why="The brief expected the eight frames after the planet run to make the moon field. They are behind thickening cloud: Rhea shows 0.70, 0.69, 0.46, 0.00, 0.11, 0.25, 0.27, 0.40, 0.08, 0.01 of its light in them, with a bright uneven glow round the planet. The two finder frames taken just before the planet run (08:46:49, 08:47:51) are clear, so the field is made from those two. "
                             "Two frames cannot be combined by a median that drops hot pixels (it needs three), so hot pixels are taken out by a map of the sensor's faults made from all twelve 2 s frames, and the two are averaged. The two epochs cannot be mixed: Saturn moves 4 arcsec among the stars in the 19 minutes between them, so the stars would double."),
             every_long_frame=every, named=names["named"], how_named=dict(ephemeris=names["ephemeris"], near_the_planet=names["near_the_planet"], direction_of_motion=names["direction_of_motion"], saturn_moved_among_the_stars_since_the_earlier_run_arcsec=names["saturn_moved_among_the_stars_since_the_earlier_run_arcsec"], saturn_au_from_the_globes_radius=names["saturn_au"],
                                                                         words="whichmoon.py. Not a star: not in the solver's catalogues, and keeps its place beside Saturn while the stars slide past (43 arcsec since the earlier run, 4 arcsec in the 19 minutes to the second field). Which moon: the size of the orbit its place implies (the regular moons lie on ellipses the shape of the rings), its brightness, and the way it moved. "
                                                                               "Dione, Tethys and Enceladus are new in this run (the earlier points were too wide to show anything within 50 arcsec of the planet); Titan, Rhea and Iapetus are where the earlier run left them, allowing for their orbits; Hyperion is the faint point that was in the earlier field too, unnamed, 9.7 arcsec further east: it has moved west at Hyperion's speed, on Hyperion's ellipse."),
             not_named=names["not_named"], not_named_note="the unnamed points within 55 arcsec are what is left of the glare at the edge of the blown-out patch (none is seen again 19 minutes later as a point); the two far ones are stars (in the same place among the stars as in the earlier run): the 8th-magnitude star, and a faint one that is not in the catalogue",
             widths=dict(this_run=widths_new, earlier_run=widths_old, note="moonwidths3.py, true arcsec; Titan and the 8th-magnitude star are blown out in the 2 s frames of both runs, which makes them read wide"),
             dione="Dione is 3 half-size px from the edge of the planet's blown-out patch and its side toward the planet is lost in it: the picture shows the outer three quarters of it. Its place for the naming was measured with the lost pixels left out of the fit.",
             scripts=["moons2.py", "plan.py", "whois3.py", "whichmoon.py", "moonwidths3.py", "longgrade.py", "longphot.py", "composite3.py"])
# -- the Cassini division ---------------------------------------------------------------------------------------------------------
cas = J("look/cassini.json")
cassini = dict(seen=False, how="cassini.py: brightness along the ring line through each end of the rings, 12 to 25 arcsec from the centre. Seen only if, going outward past ring B's peak, it falls to a low and rises again, in the plain stack too.",
               plain_stack=cas["plain 16"], finished=cas["finished 8 rounds"], at_12_rounds=cas["12 rounds"], at_20_rounds=cas["20 rounds"],
               words="No dip, in the plain stack or the finished one, on either side, at 8, 12 or 20 rounds. On the east side the outer flank eases to a shoulder at about 20.5 to 21 arcsec (ring A, outside where the division is); that is all. The division is 0.75 arcsec wide; the blur is 2.3 to 2.7.")
# -- against the earlier run ------------------------------------------------------------------------------------------------------
of = old["planet"]["recipe"]["finish"]; orec = old["planet"]["recipe"]; oR = rounds["earlier run, 16 frames"]
against = dict(
    titan_fwhm_arcsec_in_the_short_exposure_stack=dict(how="finish2.py, the 16 kept frames, half-size green, turned back for the field's turning; elliptical Gaussian; true arcsec",
                                                       this_run=[round(fin["titan"]["elliptical_fit_fwhm_arcsec"][0] * K, 2), round(fin["titan"]["elliptical_fit_fwhm_arcsec"][1] * K, 2)], earlier_run=[round(of["titan"]["elliptical_fit_fwhm_arcsec"][0] * K, 2), round(of["titan"]["elliptical_fit_fwhm_arcsec"][1] * K, 2)],
                                                       round_fit_this_run=round(fin["titan"]["round_fit_fwhm_arcsec"] * K, 2), round_fit_earlier_run=round(of["titan"]["round_fit_fwhm_arcsec"] * K, 2),
                                                       ratio=[round(of["titan"]["elliptical_fit_fwhm_arcsec"][0] / fin["titan"]["elliptical_fit_fwhm_arcsec"][0], 2), round(of["titan"]["elliptical_fit_fwhm_arcsec"][1] / fin["titan"]["elliptical_fit_fwhm_arcsec"][1], 2)]),
    rhea_fwhm_arcsec_in_the_2_s_moon_field=dict(how="moonwidths3.py on the moon field of each run (earlier: median of 8 frames; this run: mean of 2); true arcsec", this_run=widths_new["Rhea"]["fwhm_arcsec"], earlier_run=widths_old["Rhea"]["fwhm_arcsec"],
                                                ratio=[round(widths_old["Rhea"]["fwhm_arcsec"][0] / widths_new["Rhea"]["fwhm_arcsec"][0], 2), round(widths_old["Rhea"]["fwhm_arcsec"][1] / widths_new["Rhea"]["fwhm_arcsec"][1], 2)]),
    titan_fwhm_arcsec_in_the_2_s_moon_field=dict(this_run=widths_new["Titan"]["fwhm_arcsec"], earlier_run=widths_old["Titan"]["fwhm_arcsec"], note="blown out in both: reads wide"),
    faint_stars_fwhm_arcsec_in_the_2_s_moon_field=dict(this_run=[widths_new[k]["fwhm_arcsec"] for k in ("star", "star2", "star3", "star4") if k in widths_new], earlier_run=[widths_old[k]["fwhm_arcsec"] for k in ("star", "star2", "star3", "star4") if k in widths_old]),
    plain_stack_16_frames=dict(gap_contrast=dict(this_run=keep["16"]["gap_contrast"], earlier_run=earlier_plain["gap_contrast"], ratio=round(keep["16"]["gap_contrast"] / earlier_plain["gap_contrast"], 2)),
                               ansa_width_fwhm_arcsec=dict(this_run=keep["16"]["ansa_width_fwhm_arcsec"], earlier_run=earlier_plain["ansa_width_fwhm_arcsec"], unit="0.3955 per px, as the restack recipe; true: %.2f and %.2f" % (keep["16"]["ansa_width_fwhm_arcsec"] * K, earlier_plain["ansa_width_fwhm_arcsec"] * K),
                                                           blur_left_after_taking_out_the_rings_own_3_arcsec=dict(this_run=round(float(np.sqrt(max(keep["16"]["ansa_width_fwhm_arcsec"] ** 2 - 9, 0))), 2), earlier_run=round(float(np.sqrt(max(earlier_plain["ansa_width_fwhm_arcsec"] ** 2 - 9, 0))), 2))),
                               grain_on_globe=dict(this_run=keep["16"]["grain_on_globe"], earlier_run=earlier_plain["grain_on_globe"]), sky_noise_of_globe=dict(this_run=keep["16"]["sky_noise_of_globe"], earlier_run=earlier_plain["sky_noise_of_globe"])),
    finished=dict(this_run=dict(rounds=fin["rounds"], **R16[RND]), earlier_run=dict(rounds=of["rounds"], **oR[str(of["rounds"])]), note="the earlier picture stopped at 5 rounds with a 1.2 percent rim; this one has none at 8"),
    frames=dict(this_run=dict(found=rec["frames"], usable=rec["usable"], kept=rec["kept"], left_out="%d dimmed by cloud to under 0.6 of the median light" % (rec["frames"] - rec["usable"])), earlier_run=dict(found=orec["frames"], usable=orec["usable"], kept=orec["kept"])),
    frame_sharpness_grade=dict(this_run=dict(best=r4(rec["sharpness"]["best"]), worst_kept=r4(rec["sharpness"]["worst_kept"]), worst=r4(rec["sharpness"]["worst"])), earlier_run=dict(best=r4(orec["sharpness"]["best"]), worst_kept=r4(orec["sharpness"]["worst_kept"]), worst=r4(orec["sharpness"]["worst"])),
                               note="the same measure in both runs (saturn.py's find): this run's worst kept frame (%.3f) grades above the earlier run's best (%.3f); this run's worst usable frame (%.3f) about equals the earlier run's worst kept (%.3f)" % (rec["sharpness"]["worst_kept"], orec["sharpness"]["best"], rec["sharpness"]["worst"], orec["sharpness"]["worst_kept"])),
    moons_named=dict(this_run=sorted(names["named"]), earlier_run=sorted(old["moons"]["named"])),
    in_words="The refocus roughly halved the blur: Titan in the 1/40 s stack went from %.1f x %.1f to %.1f x %.1f arcsec, Rhea in the 2 s frames from %.1f x %.1f to %.1f x %.1f. In the plain stack the dark gap between globe and rings is about twice as deep (gap contrast %.3f against %.3f) and the ring at the ansa is %.2f arcsec wide against %.2f. The Cassini division is still not resolved."
             % (of["titan"]["elliptical_fit_fwhm_arcsec"][0] * K, of["titan"]["elliptical_fit_fwhm_arcsec"][1] * K, fin["titan"]["elliptical_fit_fwhm_arcsec"][0] * K, fin["titan"]["elliptical_fit_fwhm_arcsec"][1] * K, *widths_old["Rhea"]["fwhm_arcsec"], *widths_new["Rhea"]["fwhm_arcsec"],
                keep["16"]["gap_contrast"], earlier_plain["gap_contrast"], keep["16"]["ansa_width_fwhm_arcsec"] * K, earlier_plain["ansa_width_fwhm_arcsec"] * K))
looked_wrong = [
    "Cloud. 13 of the 61 planet frames are dimmed to under 0.6 of the median light (down to 0.15) and were left out by the pipeline's own rule; 13 more are dimmed by 13 to 40 percent and are usable by that rule (three of them are among the 16 kept; stacks of clear-sky frames only were tried and are slightly softer, so they stayed).",
    "The 2 s frames after the planet run, which the brief expected to use, are all behind cloud (0.70 of Rhea's light at best, most under 0.4). The moon field is from the two clear finder frames taken before the planet run.",
    "The field turns +0.038 deg per minute by Titan (+0.030 by the stars), not 0.06 to 0.08, and the opposite way to the earlier run.",
    "The planet's own shape says the blur is 4.3 x 3.0 arcsec; Titan says 2.8 x 2.3. The points have skirts a Gaussian does not follow (and are teardrop shaped). The deconvolution uses Titan's core, so it is gentler than the true blur would allow.",
    "A first hot-pixel filter (single frames, 6 sigma over the neighbours' median) flagged 13000 pixels a frame and clipped the cores of stars; it was replaced by a map of sensor faults seen in at least 6 of the 12 two-second frames (630 photosites).",
    "The glare near the planet is not the same turned half round (teardrop points) and not the same in each colour (the air's prism): left as it was it gave a bright crescent at the west ring tip that looked like a moon, a blue haze above the planet and a red one below. Colours are registered first, the arcs along the blown-out edge are taken off by a running median, and within 12 px of the edge the field is shown grey.",
    "Dione sits 3 px from the planet's blown-out patch; its side toward the planet is clipped away.",
    "No ephemeris on this machine: the moons are named from their orbits' shapes, brightness and motion (whichmoon.py). The naming of the three near the planet beats the next best by a wide margin, but it is a deduction, not a lookup.",
    "titan.py's radial-profile step fails on some of these stacks (Titan is now so narrow that the innermost ring of the profile holds no pixel); its fits print before that and agree with finish2.py. It is not in the picture's path.",
    "The sidecars give the telescope as 2032 mm; the stars give 0.3880 arcsec per px, which is 2084 mm with this sensor. The caption keeps the earlier picture's 2080 mm.",
    "Hyperion is measured but barely visible on the picture's tone curve; it is labelled 'faint'."]
pictures = {
    "saturn-sharp.png": "the plain stack of the 16 sharpest frames on the 3x grid (576 px = 74.5 arcsec), the sensor's way up at 08:47:20 UTC (turn it %.2f deg for north up); finish2.py's stretch (white at the 99.95th percentile, gamma 2.2)" % who["up_east_of_north_deg"],
    "saturn-sharp-finished.png": "the same after %d rounds of Richardson-Lucy with Titan's blur (%.2f x %.2f arcsec at the scripts' scale)" % (fin["rounds"], fin["psf_fwhm_arcsec"][0], fin["psf_fwhm_arcsec"][1]),
    "saturn-and-moons-sharp.png / .jpg": "the labelled composite, north up, 1 px = 1 sensor px",
    "saturn-and-moons-sharp-clean.png / .jpg": "the same pixels with no words, lines, inset or scale bar",
    "saturn-and-moons-sharp-clean-close.png / .jpg": "a crop of the clean picture, not resampled: Saturn with %s" % ", ".join(clean["close"]["holds"]),
    "saturn-before-after.png": "left the earlier run's plain 16-frame stack, right this run's; north up, 3x grid, one stretch for both; no words"}
# -- scripts -------------------------------------------------------------------------------------------------------------------------
scripts = {"pickframes.py": "takes the fixed frame list", "grade.py": "grades every planet frame", "saturn.py": "finish2.py and the checks use its find() and planes()", "saturn2.py": "the planet stack", "finish2.py": "Titan's blur, Richardson-Lucy",
           "rottitan.py": "the field's turning from Titan", "rotcheck.py": "the same from the ring line", "metrics.py": "sharpness numbers for a stack", "rounds.py": "false rim and sharpness against rounds", "psfmodel.py": "the blur from the planet's own shape, as a check",
           "rlcheck.py": "the deconvolution on a planet of known shape, as a check", "titan.py": "Titan's shape in the short frames (its last step fails on these stacks: see looked_wrong)", "panel.py": "comparison panels", "panel2.py": "comparison panels", "moons.py": "the earlier run's moon field, made again for the width table",
           "longgrade.py": "grades every 2 s frame by Titan's shape; Titan's direction changed from 158.2 to 154.4 deg for this run", "longphot.py": "new: how much light each 2 s frame let through (cloud), and the points' widths; the points' places come from a first-pass field of six of the later frames (moons.py)", "looklong.py": "new: a contact sheet of the 2 s frames",
           "moons2.py": "moons.py + hot-pixel map, two-frame mean, colours registered first, glare by two-fold symmetry and along the blown-out edge, blown-out mask", "plan.py": "new: plan.json for whois from the moon frames' own plate solves",
           "whois3.py": "whois2.py + starts from these frames' own solves, leaves out blown-out points instead of bright ones", "whichmoon.py": "new: names the moons from their orbits, brightness and motion", "moonwidths3.py": "moonwidths.py with the points given on the command line",
           "composite3.py": "composite2.py + names from whichmoon.py, planet set in where the long exposure is blown out, local noise threshold, label layout, --clean", "titanfine.py": "new: Titan on the planet's own fine grid, as a check on the blur",
           "halves.py": "new: noise against rounds by split halves", "rlmodel.py": "new: when the deconvolution draws a rim on a model planet", "cassini.py": "new: is there a dip where the Cassini division is", "beforeafter.py": "new: the before and after panel", "recipe3.py": "this recipe"}
steps = ["pickframes.py: the frame list, fixed at %s; this run's frames linked into planet/ (61) and long/ (12); originals never copied or changed" % fl["taken_at"],
         "grade.py: every planet frame graded (sharpness, light, place)",
         "rottitan.py: the field's turning from Titan in the short frames (+0.0378 deg per minute)",
         "longgrade.py (Titan's direction set to 154.4 deg), moons.py on six of the later 2 s frames for a first look, longphot.py: the later 2 s frames are behind cloud, the two finder frames are clear",
         "saturn2.py planet stacks/sN N 0.0378 527.34 for N = 8, 12, 16, 20, 30, 47, and the same on the clear-sky frames only for N = 12, 16, 20; metrics.py on each",
         "finish2.py planet stacks/sN 8 for N = 12, 16, 20, 30 (Titan's blur, 8 rounds); rounds.py; psfmodel.py; rlcheck.py; titanfine.py; halves.py; rlmodel.py; cassini.py: 16 frames and 8 rounds chosen",
         "moons2.py moonframes moonfield/moonfield long: the moon field from the two finder frames (hot-pixel map from all twelve 2 s frames); moons2.py on DSC01537 to DSC01539 for a second field 19 minutes later",
         "plan.py, whois3.py on both fields: stars matched, the picture's up and scale; whichmoon.py: the moons named",
         "composite3.py, and again with --clean",
         "saturn2.py <the earlier run's 170 frames> stacks/earlier16 16 -0.0559 314.67 (the restack's script unchanged: identical to the restack's stack); moons.py on the earlier run's 8 moon frames (identical too); moonwidths3.py on both fields; beforeafter.py",
         "recipe3.py: the pictures, JPEGs, recipes and scripts into the folder"]
sc = []
for name, what in scripts.items():
    put(name, "scripts/" + name); h = hashlib.sha256(open(name, "rb").read()).hexdigest(); o = os.path.join(RESTACK, "scripts", name)
    sc.append(dict(script=name, what=what, sha256=h, against_the_restack="unchanged" if os.path.exists(o) and hashlib.sha256(open(o, "rb").read()).hexdigest() == h else ("changed" if os.path.exists(o) else "new")))
# -- the pictures ------------------------------------------------------------------------------------------------------------------
put("final/saturn-sharp-plain.png", "saturn-sharp.png"); put("final/saturn-sharp-deconvolved.png", "saturn-sharp-finished.png"); put("final/saturn-before-after.png", "saturn-before-after.png")
for stem in ("saturn-and-moons-sharp", "saturn-and-moons-sharp-clean", "saturn-and-moons-sharp-clean-close"):
    p = put("final/%s.png" % stem, stem + ".png"); jpg(p, stem + ".jpg")
ba = J("final/saturn-before-after.json"); orec_ = J("stacks/earlier16.json")
ba["left"].update(what="the earlier run (before the refocus): plain stack of its 16 sharpest frames of %d usable, made again from the originals with the restack's own saturn2.py and found identical to the restack's stack, number for number" % orec_["usable"], frames=orec_["used"], turned_back=orec_["turned_back"], stack="saturn2.py <the earlier run's 170 frames> 16 -0.0559 314.67")
ba["right"].update(what="this run (after the refocus): plain stack of its 16 sharpest frames of %d usable" % rec["usable"], frames=rec["used"], turned_back={k: rec["turned_back"][k] for k in ("deg_per_minute", "reference_minute_of_day_utc")}, stack="saturn2.py <this run's 61 frames> 16 0.0378 527.34")
ba["neither_is_deconvolved"] = True; ba["full_recipe"] = "saturn-and-moons-sharp.json"
json.dump(ba, open(os.path.join(OUT, "saturn-before-after.json"), "x"), indent=1)
ps = dict(what="Saturn alone, 2026-10-04 08:48 to 09:05 UTC: saturn-sharp.png is the plain stack, saturn-sharp-finished.png the same after %d rounds of Richardson-Lucy" % fin["rounds"], pictures={k: v for k, v in pictures.items() if k.startswith("saturn-sharp")}, why_16_frames_and_8_rounds="saturn-and-moons-sharp.json, planet.choice", **rec)
json.dump(ps, open(os.path.join(OUT, "saturn-sharp.json"), "x"), indent=1)
json.dump(clean, open(os.path.join(OUT, "saturn-and-moons-sharp-clean.json"), "x"), indent=1)
for src, name in (("look/cassini.png", "checks/ring-line-profiles-cassini.png"), ("look/panel-plain.png", "checks/frames-kept-plain.png"), ("look/panel-rounds-s16.png", "checks/rounds-0-3-5.png"), ("look/panel-rounds-s16b.png", "checks/rounds-8-12-20.png"), ("look/long-all.png", "checks/2s-frames-cloud.png"), ("stacks/profiles-plain.png", "checks/ring-line-profiles-plain.png")):
    if os.path.exists(src): put(src, name)
out = dict(what=base["what"], made_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           files=dict(planet_plain="saturn-sharp.png", planet_finished="saturn-sharp-finished.png", composite="saturn-and-moons-sharp.png, .jpg", clean="saturn-and-moons-sharp-clean.png, .jpg", clean_close="saturn-and-moons-sharp-clean-close.png, .jpg", before_after="saturn-before-after.png",
                      jpg="quality 92, written from the pixels alone, no metadata", recipes_beside_the_pictures="saturn-sharp.json, saturn-and-moons-sharp-clean.json, saturn-before-after.json; this file holds everything", checks="checks/: comparison panels and profiles the choices rest on (these have words on them)", scripts="scripts/"),
           pictures=pictures, size=base["size"], arcsec_per_px=base["arcsec_per_px"], north_up_rotation_deg=base["north_up_rotation_deg"], orientation_and_scale=base["orientation_and_scale"], times_utc=base["times_utc"], captions=base["captions"], labels=base["labels"],
           frame_list=frame_list, planet=dict(frames_listed=rec["frames"], frames_usable=rec["usable"], frames_used=rec["kept"], exposure=base["planet"]["exposure"], placed=dict(centre_on_canvas_px=base["planet"]["centre_on_canvas_px"], centred_on=base["planet"]["centred_on"], set_in=base["planet"]["set_in"], share_not_shown=base["planet"]["share_of_planet_picture_outside_the_hole_not_shown"]), choice=choice, recipe=rec),
           field_turning=turning, moons=moons, moon_places_on_canvas_px=base["moons"]["places_on_canvas_px"], clean=dict(close=clean["close"], same_pixels_as=clean["same_pixels_as"]), cassini_division=cassini, before_after=ba, against_the_earlier_run=against, looked_wrong=looked_wrong,
           steps=steps, tools="numpy, scipy, OpenCV, rawpy, Pillow; every output pixel is an average or a plain filter (median, Gaussian, Lanczos resampling, Richardson-Lucy with a measured Gaussian) of measured pixels; nothing generated or learned; originals read in place through symlinks, none modified", scripts=sc)
json.dump(out, open(os.path.join(OUT, "saturn-and-moons-sharp.json"), "x"), indent=1, default=float)
print("wrote", OUT); [print("  ", f, os.path.getsize(os.path.join(OUT, f))) for f in sorted(os.listdir(OUT)) if os.path.isfile(os.path.join(OUT, f))]
