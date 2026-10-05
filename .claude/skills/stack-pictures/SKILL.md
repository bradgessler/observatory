---
name: stack-pictures
description: Turn a night's RAW frames from the camera on the telescope into stacks — deep-sky single fields and mosaics, the Moon, planets with their moons. Frame selection through cloud, flats without a flat panel, registration when the field turns, joining exposures and panels, and the checks that say whether a faint thing is real. Use when the user asks to stack, process, combine or "see what we got" from frames in ~/.observatory/nights/, or asks how a picture was made.
---

# Stack a night's frames

Frames in, one stack per target out, with a recipe beside it. Done for the
night of 3 October 2026 (Sony a6000 on the 8SE, 990 frames, thin cloud all
night); that night's scripts are the worked example in
`hack/stacks/2026-10-03/`. What comes after a stack is `finish-pictures`.

## Ground rules

- **RAWs are read, never written.** Work in a work folder, write the picture
  and a `recipe.json` beside it. Every number that shaped the picture is in
  the recipe: which frames, why the others were dropped, the flat, the
  weights.
- **Deterministic steps only.** Averages, medians, measured blurs divided
  out. Nothing predicts a pixel. This is the user's rule (see the memory
  "AI drives tools, not pixels").
- **One pipeline per target, numbered steps, one `run_all.sh`** that can
  restart from any step and logs each one. Hooks are environment variables,
  and with none set the script reproduces the last run bit for bit.
- **Say the honest verdict.** "Indistinguishable from before" is a result.
  A rerun that is not better is kept beside the first, not over it.
- **Clean up.** A target's work folder is 5 to 12 GB. The Mac ran down to
  23 GB free that night. Delete planes and intermediate stacks when the
  picture is delivered; keep scripts, logs and the deliverables.
- One agent per target works well: the targets share nothing. Tell each
  where the RAWs are, that they are read-only, and where to deliver.

## Before stacking: is it the thing?

Plate-solve a frame and find the target's catalogue position in it. The
brightest blob is not the target (a 7th magnitude star beat the Blue
Snowball), and a JPEG's EXIF orientation flips near the zenith: read images
ignoring it (`cv2.IMREAD_IGNORE_ORIENTATION`). The sidecar's ISO can be wrong
when settings changed between shutter and sidecar: trust the RAW's own
metadata. The focal length is 2,084 mm by plate solve, not the 2,032 on the
label.

## Deep sky, one field

1. **Planes, not a demosaic.** Split each RAW into its four colour planes
   (R, G1, G2, B), black subtracted. One picture pixel per 2 x 2 colour cell
   (0.776 arcsec at this focal length). Colour stays true and nothing is
   interpolated.
2. **Hot pixels** from the run itself: a pixel high in every frame while the
   stars move is the sensor. Repair with the 3 x 3 median of its plane.
   There were no darks; this stands in for them.
3. **Stars** in every frame: positions, flux, width (half-flux diameter).
4. **Register on the stars with rotation.** Far from the pole the field
   turns (0.03 to 0.08 degrees a minute that night; 2.9 degrees over the
   Andromeda run). A shift alone smears the corners.
5. **Select by transparency.** Each frame's star flux against the clearest
   frame says how much cloud was in the way. Sky brightness alone misleads:
   a bright sky with stars 20 percent dimmer is cloud, not a lamp. Keep the
   clear, down-weight the thin, drop the rest, and drop the first frame after
   a slew. Two frames in three were lost to cloud on M31; say so.
6. **Flat.** See below.
7. **Combine** with a sigma-clipped mean, weighted by transparency. Sky: one
   constant per colour per frame. Do not fit a surface when the object fills
   the frame (M31), or the fit eats the galaxy.

## Flats without a flat panel

- **Twilight flats** at dawn are the real thing: tracking off, exposure
  walked to mid-scale, 20 or more frames of blank sky. Master flat per plane,
  1 at the sensor centre.
- **A cloud flat** when there are none: the clouded frames, less the scaled
  clear frame, are the optics lit evenly. It carries the large-scale shape
  well and the dust badly.
- **The hybrid** that was delivered: twilight frames for dust and
  small-scale, cloud-lit frames for the large-scale shape.
- **Check the flat against the hour.** Dust moves. Compare dust depth in the
  flat with dust depth in that hour's own frames; where they disagree, leave
  those pixels out rather than divide blindly. A hair or chaff that moved is
  cut out per frame (it turned out to be coffee chaff, blown off next
  morning).
- An additive pattern (the same DN in colours whose sky differs fivefold) is
  not a flat error. Subtract it; do not divide.

## Mosaics

Stack each panel alone, then: plate-solve each stack (astrometry.net), solve
all jointly on shared stars (0.4 to 0.6 arcsec), resample onto one north-up
grid, set one brightness scale per panel from shared stars, match
backgrounds with a constant (a plane only when the Moon or cloud demands
it), feather the joins. A panel shot through cloud only fills where clear
panels have nothing. Where a panel's colour zero cannot be trusted, show it
grey and say so in the recipe.

## Joining long and short exposures (bright cores)

Stack the long and the short separately. The short stack replaces the long
one wherever any long frame came within 7 percent of clipping. Measure the
ratio between them on unclipped stars (41.0 against the 40 expected for
M42): if it is off, something else is wrong.

## The Moon

Lucky imaging. Register on the lunar surface itself (thousands of matched
features), then in each patch average only the sharpest 30 percent of the
clear frames. Flat-field first; subtract the cloud's glow per frame. Measure
the blur at the limb and restore (Wiener, then Richardson-Lucy) with the
gain capped (3 x) and held at the limb; look for ringing at the limb, cusps
and terminator before believing it. Turn to lunar north from craters of
known position. A panel that saw only the night side is not a failure of the
stack.

## A planet and its moons

- **The planet** from short frames: grade every frame by sharpness, keep the
  sharpest N of the usable ones (16 of 48; compare 8, 12, 16, 20, 30 and
  take the largest count that is not softer). Place each colour plane at its
  own sub-pixel offset on a grid 3 x finer than the sensor. Slide red and
  blue onto green: low in the sky the air is a prism.
- **Restore with a blur you measured**, from a moon in the same frames
  (Titan). Stop Richardson-Lucy where a model planet starts to grow a false
  rim. Say what is not seen (the Cassini division was not).
- **The moons** from long frames, with the planet's glare subtracted ring by
  ring. Name them from where they sit and how they move against the stars;
  say when a name is an inference.
- **Show it at the sensor's scale.** The fine grid is for the arithmetic.
  The user does not want the planet enlarged.

## Is it real?

Before a faint thing is called nebula: does it repeat between two
independent stacks (halves of the frames, or neighbouring panels)? The haze
at Merope and Maia repeats at 4 to 11 sigma. The glow at Atlas and Pleione
does not: it is cloud, and the picture says so. Run a control when a method
changes: the new script with the old inputs must reproduce the old result.

## What the stack needs from the night

Tell `observing-night` these before dark, because no stack can add them
afterwards: focus first (star size on the Stills page; 8.5 arcsec became
5.0), flats at dusk or dawn, darks with the cap on, short frames for bright
cores, exposures capped by the drift (20 s at 0.1 arcsec per second), and
three times the frames you want when cloud is about.
