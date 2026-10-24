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
- **Every pipeline ends with the stack as FITS and a recipe in the schema**
  (below). Nothing a processed file carries may give the site away.

## Metadata: the stack FITS and the recipe (docs/metadata.md)

The tools: `tools/obsmeta.py` (one reader for a frame's sidecar and solve,
`observatory.still/1` and `/2`; the FITS cards by the spec's names; FITS with
CHECKSUM/DATASUM; the recipe helpers), `tools/stack_fits.py` (the stack FITS),
`tools/master_fits.py` (calibration masters), `tools/upgrade_recipe.py` (an old
recipe to the schema), `tools/privacy_check.py` (before every commit),
`tools/test_obsmeta.py` (run it after changing any of them). Worked example:
`hack/stacks/2026-10-17/<target>/step16_metadata.py` (Saturn: `step14`) and
`hack/stacks/2026-10-17/nightmeta.py`.

- **The last steps of a pipeline:** the recipe step, then a metadata step that
  (1) brings the recipe to `observatory.recipe/1` (`upgrade_recipe.upgrade(old,
  ctx)`, or build it in that shape and call `obsmeta.finish_recipe`), (2) writes
  `<OUT>/<target>-stack.fits` with `stack_fits.write(...)`, (3) adds the FITS to
  the recipe's outputs, (4) dumps the recipe. Then the annotate step, then the
  clean (the metadata step reads `work/`).
- **The deliver step keeps the linear stack itself:** `np.save(W('stack_linear_rgb.npy'),
  cam.astype(np.float32))` beside the TIF, before rounding. The FITS is that array
  (float32, planes first: R, G, B; G the mean of G1 and G2; camera RGB times the
  white balance; no pedestal; not clipped: the TIF clipped M42's core at 65535).
  `stack_fits.write(..., tif=, pedestal=1000)` proves round(data + 1000) is the TIF.
- **Header:** `IMAGETYP = 'MASTER LIGHT'`, `NCOMBINE`/`STACKCNT`, `EXPTIME` =
  one frame (the data are per frame), `LIVETIME` = total, `DATE-OBS`/`DATE-END`
  of the frames, `DATE-AVG` weighted, MJDs, `OBJECT` (SIMBAD name) and
  `OBJCTRA`/`OBJCTDEC`, `TELESCOP`/`INSTRUME`/`FOCALLEN` (from the stack's own
  solve)/`APTDIA`, `XPIXSZ` effective (7.84 um and `XBINNING = 2` for one pixel
  per colour cell), `BUNIT`, `CALSTAT`, `ROWORDER = 'TOP-DOWN'`, one `HISTORY`
  per recipe step (each step's `history` line), `HIERARCH OBS RECIPE ID`. A
  SHA-256 is too long for one HIERARCH card: it is split over `KEY`, `KEY 2`
  (`obsmeta.joined` reads it back).
- **WCS: plate-solve the stack itself** (`solve=dict(ra_deg, dec_deg,
  scale_low, scale_high)`: astrometry.net, SIP order 2, for the array as
  stored), never frame WCS pushed through the registration. It is checked
  against Gaia DR3: every isolated Gaia star looked for at its place through
  the WCS (17 October: 140 to 639 stars, median 0.39 px for M27, 0.49 for M33,
  1.14 for M42, all within 1.7 px at the 90th percentile; a mean offset of
  0.1 to 0.7 px remains, with the Tycho-2 and the 2MASS indexes alike, cause
  not found). The write fails past a median of 1.5 px, a 90th percentile of
  2.5 or a mean offset of 1 px. The solve is deterministic: the same stack
  gives the pipeline's own `work/solve/stack.wcs` to 0.000 px. astropy reads
  it with `WCS(header, naxis=2)` (NAXIS3 is the colour).
- **A planet (lucky imaging):** no stars, and the planet moves against them
  (Saturn 18 arcsec over 1.7 hours). Pass `wcs=` yourself: Saturn-centred at
  `DATE-AVG` (`WCSNAME` says so), scale and turn from the moons against JPL
  Horizons, CRVAL geocentric. Check it on the ring axis. Fine grid: `XPIXSZ` =
  3.92 / 3 um.
- **Masters:** `darks.py`, `twilight_flat.py`, `skyflat.py` write `.fits` beside
  the `.npz` (`IMAGETYP = 'MASTER DARK' / 'MASTER FLAT'`, NAXIS3 = 4 planes R G1
  G2 B, `NCOMBINE`, `EXPTIME`, `ISOSPEED`, dates, every input's name and SHA-256
  in HISTORY) and their JSON gains `schema: observatory.master/1`, `inputs`,
  `fits`. For a master built before: `master_fits.py <folder>`.
- **The recipe** (`observatory.recipe/1`): `schema`, `id` (SHA-256 of
  everything but id, made, git, outputs: the FITS carries it), `target` {name,
  ids, title, ra_deg, dec_deg, text}, `night`, `made`, `reproduce`, `roots`
  (where relative paths start), `software` (versions, astrometry.net and its
  indexes), `git` (commit, the scripts' last commit, changes not committed),
  `inputs` (every frame considered: name, night, folder, the RAW's SHA-256 from
  its sidecar, the sidecar's and solve's own, used, why, weight), `calibration`,
  `steps` (each with `history`), `outputs` (file, root, kind, SHA-256, bytes;
  the stack FITS with its WCS and checks). Paths relative to the repository or
  under `~/.observatory`, never `/Users/...`. `obsmeta.check_recipe` lists what
  does not conform.
- **Privacy (Brad's rule): nothing a processed file carries may give the site
  away.** No `SITELAT`, `SITELONG`, `SITEELEV`, `OBSGEO-*`, `CENTALT`/`CENTAZ`,
  hour angle or local time zone in any FITS, HISTORY or HIERARCH card;
  `AIRMASS` only to 0.1. `obsmeta.write_fits` strips them whatever it is given
  and refuses text naming the site. No site in a recipe either: it names the
  frames. FITS, TIF, NPZ and anything with metadata live under
  `~/.observatory/nights/` only, never in git (write_fits refuses the
  repository); the committed pictures carry no metadata at all (OpenCV writes
  none). Before committing: `tools/privacy_check.py` on the staged files.

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

## What the night of 8 October 2026 added

Six targets, one agent each, all reproducible bit for bit from `hack/stacks/2026-10-08/<target>/run_all.sh`
(the M57 and NGC 1514 pipelines are the best templates now).

- **Select by star shape, not only size.** Frames taken while the hold took up a Go To's last error, and a
  periodic wobble later, smear every star the same way: drop frames with common-direction ellipticity above
  0.2, star size above ~6.5", or within 10 s of a move. Two consecutive sharp frames between smeared ones are fine.
- **Transparency where the object is,** not over the whole frame, when something (a tree, a roof) is partly in
  the way: fit a plane through the star-flux ratios. A rising object behind an obstruction looks like a
  brightening sky in green and blue with red flat; cloud makes the sky darker.
- **A flat from the night's own open-sky frames** (another target's run, same optics and settings) when there
  were no twilight flats: multiplicative, per colour, dust shadows found against two skies and divided out.
  It matched the 3 October flat to 1%.
- **Atmospheric dispersion:** measure red and blue against green on the stack's stars (0.2 to 0.6 px at
  30-40 degrees) and take it out in the one resampling.
- **Register on the RAW green planes with a lower threshold (4.5 sigma)** when the sky is bright; a 2nd-order
  fit beside rotation+shift halves residuals on a long run.
- **Sky:** one constant per colour per frame in the stack, always. A sky plane or vignetting model fitted far
  from the object is allowed in the picture only, and said in the recipe.
- **Finishing:** read the 16-bit stretched image at full depth (`finish16.py` beside each night's scripts);
  keep the stretch floor below zero (a hard zero leaves exact-black specks the finish tool treats as no data);
  luminance from a light blur, colour from a heavier one faded to grey in the sky, when red and blue are 2-3x
  noisier than green. Colour only where the signal carries it; say so (M33's disk was left grey).
- **Deconvolution** was tried on five targets and delivered on none as the main picture: rings around stars
  and drowned faint parts every time at this depth. Keep it as a labelled extra only when it doesn't ring.
- **Prove the faint thing** with half stacks (odd and even frames) and blank-sky placements of the same
  aperture; the Crystal Ball's shell passed, the Crab's filaments did not.

## What the night of 12 October 2026 added

Ten targets, one agent each as the telescope left it, each done in 15 to 45 minutes and reproducible from
`hack/stacks/2026-10-12/<target>/run_all.sh`. Templates now: `m78` (a faint object on open sky), `ngc1535` (a
small bright one delivered as a tight crop), `almach` (a double star from 1/60 s frames), `m33` (an object bigger
than the frame).

- **Read RAWs in place at every step; keep no per-frame cache.** A target then needs about 0.6 GB of work space,
  not 5 to 12, and two can run at once on a nearly full disk.
- **Hand each agent the night's newest finished pipeline as its template and a time limit.** The first targets
  took 45 to 65 minutes designing; the later ones 15 to 25 adapting.
- **The flat is elliptical, not radial:** light falls off faster along the sensor's short side. A flat fitted from
  one target's open sky (NGC 891) left about 1 percent, read about 1.5 percent high in the middle of the sensor
  where that target hid the sky, and left dozens of dust shadows. So every run measured its own dust on its own
  sky (each shadow seen in odd and even frames alone) and divided it out, and said what could not be judged under
  the object. Real twilight flats were taken at the end of the night (13 frames, ISO 100, the Sun 3 to 0.5 degrees
  down): use them.
- **Cloud is found on the stars, frame by frame, against the clear plateau of the run,** not against the run's
  median (which may itself be thin) and not from the box's transparency figure (it read 1.0 through thin cloud).
  Dimmer stars under a brighter sky that recover in minutes are cloud; stars widening and dimming together for
  good are dew.
- **An unguided 15 s frame is smeared 1 to 2 arcsec along RA about one time in ten.** Common-direction
  ellipticity above 0.2 finds them. A frame taken while the hold re-centred after a restart is found in its
  sidecar (`settle.since_slew_s` near 0, mount start and end hundreds of arcseconds apart).
- **Short frames of a bright star: more frames made it softer.** The sharpest 5 of 13 beat all 13 (Almach).
- **A planetary nebula's blue-green is outside sRGB:** the camera matrix gives negative red, clipped at zero. Set
  white on the brightest colour channel, not on luminance (`--white` in that target's `finish16.py`), or the disc
  and its central star flatten.
- **Prove structure by correlating band-passed odd and even stacks against blank-sky places** (the Crab: 9 to 16
  sigma where 8 October's four frames gave 1.4). A colour that does not repeat is not drawn (its red filaments).

## Calibration tools (`tools/`, from the frames of 12 and 13 October)

Proven on NGC 891 and M77 against the published stacks, which the same pipelines rebuild bit for bit with
the old flat: the sky pattern left after a plane fell from 0.5 to 0.8 percent to 0.2 to 0.3; M77 is followed
5.9 arcmin across instead of 2.5, part of its outer disc now passes the half-stack test; NGC 891's disc
reaches 12.1 arcmin instead of 11.1; star colours match Gaia instead of leaning green. The pipelines are
`hack/stacks/2026-10-12/{ngc891,m77}-calibrated/`.

- **The flat is the night's sky for the large scale, times the twilight flats' dust.** `twilight_flat.py`
  builds the dust from twilight frames (1,000 to 8,000 DN; ISO does not matter for dust). `skyflat.py` builds
  the large scale from the open sky of the night's other runs (leave the target's own run out) and multiplies
  in the dust. Check any flat on the run's own sky before stacking with `flatcheck.py`. A twilight flat taken
  parked at the pole carries the wrong large scale (13 October: the light centred 880 px off the middle).
  A flat fitted from one target's sky reads 1 to 1.5 percent high in the middle and hides faint outer light.
  What looked like a sky slope in every run is the optics: keep it in the flat.
- **Star colours from the catalogue.** `star_colour.py` on the linear stack, before finishing: Gaia DR3 for
  the field through `catalogue.py` (cached under `~/.observatory/catalogs/`, the query written beside it).
  Expect red x1.0 and blue x1.14 to 1.16 over the camera's daylight balance. A colour term of about -0.18 mag
  per mag remains and is not applied.
- **Darks.** `darks.subtract` in a pipeline's plane loading: with no master dark it changes nothing and says
  so; with darks (`drive-the-box/darks.exs`, cap on, the lights' exposures and ISOs) it also fixes the black
  level, which reads about 5 DN under 512 at ISO 400 and is not yet measured at 3200.
- **Prove faint outer structure against the flat's own uncertainty** (rebuild it leaving one run out), not
  only against odd and even halves.

## Combining frames (`tools/coadd.py`, 17 October 2026)

Zackay and Ofek's proper coaddition: each frame filtered by its own measured PSF, weighted by
(transparency / sky noise) squared, summed and whitened. Linear once the outlier mask is fixed; nothing is
deconvolved. Pipelines: `hack/stacks/2026-10-12/{ngc891,ngc2261}-coadd/`, which also rebuild the published
stacks byte for byte as a control.

- **What it bought on 15 s frames in 3.6 to 7 arcsec seeing: little.** Point-source S/N +1.4 percent (NGC
  891) and +4.1 percent (NGC 2261); nothing visible, star size the same, nothing new in the half stacks.
  Most of that is not the PSF weighting (+0.3 and +1.5 percent): it is dropping the 3 sigma clip about the
  median, which costs 1 to 3 percent and clips sharp frames' stars when the seeing varies.
- **Default combine:** `coadd.outlier_mask` (with the PSFs and a 1/flat noise map) and
  `proper_coadd(keep_phase='mean')`, with the old combine kept as a control in the same pass for a few
  nights. One PSF per frame and plane, from 150 to 200 isolated unsaturated stars: the PSF changes 40
  percent across this field, but every frame changes the same way. Keep the mean phase: the paper's
  zero-phase image drew dark crescents beside bright stars.
- **Do not deliver** the version convolved to the mean's PSF for its lower per-pixel noise: that is
  smoothing, and smoothing belongs in the finish.
- **Thin-cloud frames** help point sources but add noise on large scales; keep the 0.9 transparency cut for
  faint extended objects.
- The real gains this week came from calibration (above) and from more light per night, not from combining.

## What the night of 17 October 2026 added

Four targets, one agent each, reproducible from `hack/stacks/2026-10-17/<target>/run_all.sh`. Templates now: `m42` (a
bright core joined from short frames, proper coaddition, dithered), `m33` (two nights and three turns, framed for
the area most frames cover), `saturn` (lucky imaging with moons matched to JPL Horizons), `m27` (a small object,
undithered, dust measured on its own sky).

- **Dust moves between nights.** The 13 October hybrid flat still had the right large scale, but a new crescent
  12 percent deep had appeared. Every run measured its own dust on its own sky (each shadow seen in both halves
  of the run alone) and divided it out after the flat. A dithered run measures dust far better: frame against
  the first stack, put back on the sensor grid, so the object cancels.
- **Is a dark spot dust?** Compare the same sensor pixels in two different targets. Dust is in both; a dust lane
  is in one. `tools/dustcheck.py "<target A JPEGs>" "<target B JPEGs>" out.png` does it and draws the proof
  (each spot from both targets side by side; `--at x,y` for a spot someone saw on the screen); the box's sensor
  map runs the same rule live (`Controller.StillCamera.SensorMap`).
- **Dithered runs:** frame for the area at least half the frames cover and say what the edges get. The picture
  can still come out smaller than one frame (M33: 36 x 21 against 39 x 26 arcmin); don't call it wider without
  measuring.
- **Proper coaddition again bought 1.5 to 2.3 percent** point-source S/N on 30 s frames: the default, nothing a
  viewer sees. When the nebula fills the frame, read each frame's noise at its own median level, not the noise
  model's zero term (which fell to 0 and weighted M42 as 75 frames of 165).
- **Joining short and long exposures:** the measured ratio was 62.65 on M42's nebula (65.2 on stars) against the
  60 the exposures and ISOs give. The join uses the measured value; the cause (ISO or shutter not nominal) is
  unverified. Measure it every time and say it.
- **Labels:** check every one at full size against the plate solve. NGC 592's search radius landed on a Gaia
  foreground star; a 6 px radius found the cloud. Fail the annotate step when a label box leaves the picture.
- **Planet moons need their own frames.** Tonight's moons came from the two 2 s ISO 6400 centring shots; their
  cores clipped, so each moon showed a flat white dot in a halo (not focus: one peak, no ring; a star in the same
  frame was 4.5"). Shoot about 30 frames at 1 s, ISO 800, on the planet's turn (`drive-the-box`).
