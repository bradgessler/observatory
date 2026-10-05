"""The record kept beside the mosaic: frames.csv (every frame of the session: used or not, and why)
and recipe.json (every step and number).
Usage: record.py <stills folder> <output folder> <keep tag, e.g. keep30>"""
import sys, csv, json, os, glob
from collections import Counter
import moonlib

src, out, tag = os.path.expanduser(sys.argv[1]), sys.argv[2], sys.argv[3]
J = lambda f: json.load(open(f))
frames = J("frames.json"); grades = {r["name"]: r for r in csv.DictReader(open("grades.csv"))}
sky = J("sky.json"); glow = J("glow.json"); photo = J("photo.json"); T = J("transforms.json"); TS = J("transforms-sensor.json")
R = J("recipe-%s-2x.json" % tag); flat = J("flat.json"); orient = J("orient.json"); cov = J("coverage.json"); whole_psf = J("psf-2x.json"); whole_frc = J("frc-2x.json")
F = J(os.path.join(out, "finish-moon-last-quarter.json")); W = J(os.path.join(out, "moon-last-quarter-restored.json")); crops = J(os.path.join(out, "crops.json"))
C = 16383 - 512

# which pointing each Moon frame belongs to: a new group whenever more than a minute passed
order = ["centre check, pass 1", "panel 1, pass 1", "panel 2, pass 1", "panel 3, pass 1", "panel 4, pass 1",
         "centre check, pass 2", "panel 1, pass 2", "panel 2, pass 2", "panel 3, pass 2", "panel 4, pass 2"]
secs = lambda n: int(n[9:11]) * 3600 + int(n[11:13]) * 60 + int(n[13:15])
group = {}; g = -1; last = None
for f in frames:
    if f["role"] != "moon":
        continue
    if last is None or secs(f["name"]) - last > 60:
        g += 1
    last = secs(f["name"]); group[f["name"]] = order[g] if g < len(order) else "?"
clear_face = max(v["face"] for v in sky.values())
rows = []
for f in frames:
    n = f["name"]; raw = f["raw"]
    row = dict(frame=n, raw=raw, time_utc=f["time_utc"], shutter=f["shutter"], iso=f["iso"], taken_for=group.get(n, {"test": "first test exposure", "earthshine": "earthshine attempt"}.get(f["role"], f["role"])),
               verdict="", why="", transparency="", sky_counts_green="", cloud_glow_counts="", matches="", fit_px="", rotation_deg="", scale="", share_of_patches_pct="")
    if f["role"] != "moon":
        row.update(verdict="not used", why=f["why"]); rows.append(row); continue
    s = sky.get(raw)
    if s:
        row["sky_counts_green"] = round((s["sky"][1] + s["sky"][2]) / 2 * C, 1)
    if n in T["placed"]:
        p = TS["placed"][n]; share = 100 * R["patch_share"].get(n, 0); t = photo[n]["transparency"]
        row.update(transparency=round(t, 2), cloud_glow_counts=round(glow["frames"][n]["glow_on_lit_ground_median"] * C, 1), matches=p["inliers"], fit_px=round(p["rms_px"], 2),
                   rotation_deg=round(p["rot_deg"], 2), scale=round(p["scale"], 4), share_of_patches_pct=round(share, 2))
        if share > 0:
            row.update(verdict="used")
        else:
            row.update(verdict="not used", why="under cloud: %d%% of the light got through; %s" % (round(100 * t), "under a quarter is never used" if t < 1 / R["cloud"]["not_used_if_gain_over"] else "clearer frames covered all it shows"))
    elif s and s["face"] == 0:
        row.update(verdict="not used", why="nothing lit in the frame: this panel looked at the Moon's night side")
    else:
        row.update(verdict="not used", why="too dim under cloud to find the Moon in it (lit face %d counts; a clear frame has %d)" % (round(s["face"] * C), round(clear_face * C)))
    rows.append(row)
# the flats: every twilight frame taken after the Moon
flat_by = {r["file"]: r for r in flat["frames"]}
for jf in sorted(glob.glob(os.path.join(src, "20261004-*-DSC*.json"))):
    stem = os.path.basename(jf)[:-5]
    if jf.endswith(".solve.json") or not ("134800" <= stem.split("-")[1] <= "140900"):
        continue
    j = J(jf); c = j.get("camera", {}); r = flat_by.get(stem + ".ARW")
    if r is None:
        verdict, why = "not used", "twilight frame that is not in the flats log"
    elif r["used"]:
        verdict, why = "used", "in the master flat"
    else:
        verdict, why = "not used", r["why"]
    rows.append(dict(frame=stem + ".JPG", raw=stem + ".ARW", time_utc=j.get("time", {}).get("shutter_pressed"), shutter=c.get("shutter"), iso=c.get("iso"), taken_for="flat (twilight sky)", verdict=verdict, why=why,
                     transparency="", sky_counts_green="", cloud_glow_counts="", matches="", fit_px="", rotation_deg="", scale="", share_of_patches_pct=""))
with open(os.path.join(out, "frames.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

moon = [r for r in rows if r["taken_for"] in order]; used = [r for r in moon if r["verdict"] == "used"]
short = lambda t: "under cloud: " + t.split("; ")[1] if t.startswith("under cloud") else t.split(" (lit face")[0]
why = Counter(short(r["why"]) for r in rows if r["verdict"] != "used" and r["taken_for"] != "flat (twilight sky)")
by_group = {g_: dict(frames=sum(r["taken_for"] == g_ for r in moon), used=sum(r["taken_for"] == g_ and r["verdict"] == "used" for r in moon),
                     transparency=[r["transparency"] for r in moon if r["taken_for"] == g_ and r["transparency"] != ""]) for g_ in order}
gl = [r["cloud_glow_counts"] for r in moon if r["cloud_glow_counts"] != ""]
recipe = dict(
    what="The Moon at last quarter, 2026-10-04 13:14-13:47 UTC: Celestron 8SE (0.388 arcsec per pixel, plate-solved) + Sony a6000, 1/60 s at ISO 100, from RAW. Four panels in two passes, in morning twilight, the southern panels through thin cloud.",
    files={"moon-last-quarter.png / .jpg": "the stack as it is, lunar north up, at the sensor's pixel scale (%d x %d)" % tuple(F["size"]),
           "moon-last-quarter-restored.png / .jpg": "the same with the blur's contrast loss undone as far as two half-stacks agree (Wiener filter), held to the plain stack at the limb and in the night side",
           "moon-last-quarter-linear.tif": "the plain stack, linear 16-bit: 65535 = half the sensor's ceiling, sky at 0",
           "crop-*.png": crops, "frames.csv": "every frame of the session: used or not, and why", "scripts/": "the code that made all this: run.sh, start to finish"},
    source=dict(session_frames=len([r for r in rows if r["taken_for"] != "flat (twilight sky)"]), moon_exposures=len(moon), used=len(used), not_used=dict(why), by_pointing=by_group,
                flats=dict(taken=sum(r["taken_for"] == "flat (twilight sky)" for r in rows), in_the_log=flat["frames_in_log"], kept_by_the_log=flat["kept_by_log"], used=flat["used"])),
    steps=["frames.py: the session's frames sorted by what they were taken for (the box's sidecars)",
           "flat.py: master flat from the twilight frames the log kept and that show no lit cloud; per colour plane, median of frames each divided by its own median",
           "grade.py: every Moon frame graded from its JPEG (is the Moon there, how much)",
           "sky.py: each frame's own sky level per colour plane, from the RAW after the flat",
           "register.py: craters matched between frames (SIFT), each frame's rotation, shift and scale solved (RANSAC), then every frame solved again against all its neighbours",
           "stack.py photo: one transparency number per frame, from where frames overlap",
           "glow.py: the glow thin cloud puts round the Moon, fitted per frame where the truth is black and subtracted; stack.py photo again",
           "stack.py ref / local / combine, measure.py, orient.py, turn.py: a first stack sensor-way-up; lunar north from 17 craters; every placement turned so the stack is made north-up",
           "stack.py ref / local: frames averaged into a yardstick; per frame a grid of patches matched to it; per patch, detail measured with noise subtracted",
           "stack2x.py: per patch the sharpest frames among the clear ones; each frame's four colour planes read at their own place in the 2x2 colour cell onto the sensor's pixel grid (Lanczos-4, once); feathered at frame edges",
           "measure.py, psf.py: colour-plane offsets, the limb (centre, radius) and the blur's spectrum from the sunlit limb",
           "frc.py: two stacks from separate halves of the frames compared scale by scale; zones.py: the same two measurements for north, middle and south separately",
           "finish.py: the plain picture; wiener.py: the restored one (per zone: contrast restored by (share that is signal) / (contrast the blur left), never more than 3x, held to the plain stack at the limb and in the night side); coverage.py, crops.py, record.py"],
    changed_from_hack_moon_mosaic=[
        "moonlib: the RAW has the JPEG's own name; numbers x4 (ISO 100, not 800) so the old thresholds hold; scale 0.3881 arcsec per pixel (plate-solved this night)",
        "new, flat.py + moonlib: every colour plane divided by a master flat from this morning's twilight frames; the hair's shadow (it crept during the flats) counted as no data",
        "new, sky.py + moonlib: each frame's own sky level per colour plane taken off (twilight)",
        "new, glow.py + moonlib: the glow of thin cloud fitted per frame (the lit Moon blurred by 75 arcsec to 20 arcmin, five amplitudes and a constant, fitted only on black sky and the night side) and taken off",
        "register.py: anchors spread over every pointing instead of the twelve frames with the most Moon; then two rounds solving each frame against all its neighbours at once",
        "new, stack.py photo: one transparency per frame from the overlaps; the yardstick is built from frames scaled alike, weighted by transparency squared and faded at their edges (four panels, no step where one ends)",
        "stack.py local: a frame's brightness map against the yardstick leans on its one number where there is no light to compare",
        "stack.py weights: cloud judged patch by patch against the clearest frame there (gain within 1.5x, or the 10 clearest), frames below a quarter of the light never used; sharpest 30% of those, at least 8",
        "new, orient.py + turn.py: lunar north measured from craters and every placement turned before stacking, so north is up without resampling a finished picture",
        "stack2x.py: reads the calibrated planes",
        "frc.py, psf.py: can be limited to rows of the picture / a stretch of limb; new, zones.py: blur and noise measured for north, middle and south separately",
        "wiener.py: one filter per zone, blended down the picture; a zone's blur curve is the sharper of its own limb's and the whole limb's; gain capped at 3; holds against ringing made stronger (at the limb and in the night side the plain stack shows through; no moat round lit peaks); writes PNG and JPEG",
        "finish.py: writes PNG, JPEG (quality 92) and the linear TIFF; record.py, coverage.py, crops.py, frames.py, judge.py, flatcheck.py, glowcheck.py new or rewritten"],
    flat=dict(method=flat["method"], used=flat["used"], planes=flat["planes"], hair_counted_as_no_data_cells=moonlib.HAIR,
              frames=[dict(file=r["file"], shutter=r["shutter"], iso=r["iso"], used=r["used"], why=r["why"], large_scale_departure_pct=r.get("large_scale_departure_pct")) for r in flat["frames"]],
              check=J("flatcheck.json") if os.path.exists("flatcheck.json") else None),
    sky_and_glow=dict(sky_counts_green=dict(first_frame=moon[0]["sky_counts_green"], last_frame=moon[-1]["sky_counts_green"], note="of 15871; the black level reads 2.5 counts low, so a dark sky is -2.5"),
                      glow=dict(model="c + sum of a_i * blur(lit Moon, sigma_i), a_i >= 0", blur_sigmas_arcsec=glow["blur_sigmas_arcsec"], fitted_on="black sky and night side at least %.0f arcsec from lit ground" % glow["margin_arcsec"],
                                rounds=glow["rounds"], counts_on_lit_ground_median_per_frame=dict(least=min(gl), most=max(gl)),
                                check=J("glowcheck.json") if os.path.exists("glowcheck.json") else None)),
    north_up=dict(how="orient.py: %d craters of known selenographic place read off the first, sensor-way-up stack; the turn and the libration fitted to all at once" % orient["verdict"]["craters"],
                  sensor_way_up_picture_was_turned_anticlockwise_by_deg=round(orient["verdict"]["turned_anticlockwise_deg"], 2), plus_minus_deg=round(orient["verdict"]["plus_minus_deg"], 2),
                  so_every_placement_was_turned_clockwise_by_deg=round(T["north_up"]["turned_clockwise_deg"], 2), fit_rms_px_half_size=round(orient["verdict"]["rms_px"], 1),
                  libration_fitted_deg=dict(longitude=round(orient["verdict"]["libration_deg"][0], 1), latitude=round(orient["verdict"]["libration_deg"][1], 1)),
                  mirrored=orient["verdict"]["picture_is"] != "as it is", cusp_line_says_deg=round(orient["verdict"]["cusp_line_says_deg"], 1),
                  result="lunar north up, lunar east (Mare Crisium's side, the night side here) right; the lit limb is the Moon's west limb",
                  craters={k: v for k, v in orient["as it is"]["residuals_px"].items()}),
    coverage=cov,
    resolution=dict(pixel_scale_arcsec=W["arcsec_per_px"],
                    whole_limb=dict(blur_fwhm_arcsec=whole_psf["psf_fwhm_arcsec"], edge_10_90_arcsec=whole_psf["edge_10_90_arcsec"], by_measure_py=dict(fwhm_arcsec=F["measured"]["blur_fwhm_arcsec"], edge_10_90_px=F["measured"]["edge_10_90_px"])),
                    whole_picture_halves_agree_512px_tiles=whole_frc["resolution_arcsec"],
                    by_zone={z["zone"]: dict(rows=z["rows"], limb_blur_fwhm_arcsec=z["blur"]["psf_fwhm_arcsec"], limb_edge_10_90_arcsec=z["blur"]["edge_10_90_arcsec"],
                                             halves_agree_arcsec=z["halves_agree"]["resolution_arcsec"], restoration_peak_gain=z["peak_gain"]) for z in W["zones"]},
                    note="more pixels than detail. The north (clear frames) is sharper and far less noisy than the middle and south (frames through cloud; the far south also blurrier, near the frame's edge in every picture that shows it)"),
    stack=R, plain=F, restored=W,
    nothing_generative="No step predicts or invents pixels. Every output pixel is a weighted average of measured pixels from the frames listed in frames.csv (each divided by the flat and with its own sky level and fitted cloud glow subtracted), then, in the restored picture only, one linear filter built from two measured curves. Where no frame covers the picture it is black.")
json.dump(recipe, open(os.path.join(out, "recipe.json"), "w"), indent=1)
os.remove(os.path.join(out, "finish-moon-last-quarter.json")); os.remove(os.path.join(out, "moon-last-quarter-restored.json")); os.remove(os.path.join(out, "crops.json"))
print("session frames", recipe["source"]["session_frames"], "moon exposures", len(moon), "used", len(used), "not used", dict(why))
for g_, v in by_group.items():
    print("  %-22s %2d frames, %2d used, transparency %s" % (g_, v["frames"], v["used"], " ".join("%.2f" % t for t in v["transparency"])))
