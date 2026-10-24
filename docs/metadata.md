# Metadata: capture to publish

What is known about every picture, where it is written at each stage, and
which standard name it goes by. This is the spec; the gap list and the order
of work are at the end.

Audited 23 October 2026 against: `Controller.StillCamera.Sidecar`
(`observatory.still/1`), `StillCamera.write_solve/1`
(`observatory.still.solve/1`), `Controller.ScopeCamera.Header` (FITS cards of
the scope camera's frames), `Controller.StillCamera.{Record, SensorMap, Optics,
Cloud, Focus}`, `Controller.Sky.FieldRotation`, `Camera.Sony.describe/1`,
the 1,135 real sidecars and 1,130 solve answers under `~/.observatory/stills/`,
the 17 October stacks (`hack/stacks/2026-10-17/*`), the stacking tools
(`.claude/skills/stack-pictures/tools/`), `observations/2026-10-17/` and
`mix site.build`.

## Principles

1. **One immutable record per file, written once, beside it.** The camera's
   files are never opened for writing (RAWs are read, never written). Later
   knowledge (a plate solve, a stack's verdict) is a new file that points
   back by name and SHA-256, never an edit of the old one.
2. **JSON is the source of truth; standard names ride with it.** Each JSON
   record keeps our own readable shape and gains a `fits` block: the same
   facts as FITS cards (`[keyword, value, comment]`), standard keywords
   first, ours under `HIERARCH OBS ...`. Any file we write in a standard
   format (FITS frames, stacks, masters) carries exactly those cards. One
   Elixir module and one Python helper make the cards, so the stills, the
   scope camera and the stacks can never disagree on a name.
3. **Standard first, then convention, then ours.** Order of preference:
   FITS 4.0 reserved keywords and the registered conventions (WCS Papers
   I-III, SIP, CHECKSUM); then the de facto capture-program keywords
   (N.I.N.A., MaxIm DL, SBIG, ASCOM) that Siril, PixInsight, ASTAP and
   astrometry.net read; then `HIERARCH OBS ...` for what has no standard.
   Published pictures use XMP: AVM 1.2 (`avm:`), Dublin Core (`dc:`), IPTC
   (`Iptc4xmpCore:`, `Iptc4xmpExt:`), `photoshop:` and `xmpMM:`.
4. **Capture more than the standards when we know more.** Dither, settle,
   field rotation, transparency, star size, lock-on, the sensor map, the
   mount's 4 Hz track: all kept, namespaced, in the units stated here.
5. **Unknown is absent, not zero.** No `0.0` for "no lens", no `false` for
   "not computed", no prose where a number belongs. A field that was asked
   for and has no answer says `null` with a reason beside it.
6. **Location is full precision inside, Bay Area outside.** See Privacy.

## Conventions

| Thing | Rule |
|---|---|
| Time | UTC, ISO 8601 with milliseconds (`2026-10-18T09:39:37.715Z`). FITS: `TIMESYS = 'UTC'`. MJD as `MJD-OBS` etc. (JD - 2400000.5). |
| Celestial frame | ICRS (`RADESYS = 'ICRS'`), also `EQUINOX = 2000.0` for readers that want it. J2000 FK5 and ICRS differ by about 0.02 arcsec: one frame for everything. |
| Angles | Degrees (decimal) everywhere in JSON and numeric FITS cards; sexagesimal only in the string cards that require it (`OBJCTRA = 'HH MM SS.s'`, `OBJCTDEC = '+DD MM SS'`). |
| Lengths | mm for optics (`FOCALLEN`, `APTDIA`), um for pixels (`XPIXSZ`), m for elevation (`SITEELEV`, `OBSGEO-H`). XISF wants metres for aperture and focal length: convert on export. |
| Pixels | Our arrays are top row first. FITS we write say `ROWORDER = 'TOP-DOWN'` (N.I.N.A. convention) and any WCS is written for the array order as stored, so `CRPIX` is valid in the file whichever way a viewer draws it. AVM counts from the bottom-left (FITS convention on the displayed image): convert, see Stage 6. |
| Hashes | SHA-256, lower-case hex, of the file's bytes, in every JSON record that names a file. FITS also get `CHECKSUM`/`DATASUM` (the FITS checksum convention). |
| Schema | Every JSON record has `"schema": "observatory.<kind>/<n>"`; adding a field is not a new version, changing a meaning is. |
| Target names | SIMBAD-resolvable (`M 27`, `NGC 6853`), so `OBJECT` can be looked up by any tool; the friendly name goes in a separate field. |

## The pipeline and its files

| Stage | File(s) | Record | Written by | Standard form |
|---|---|---|---|---|
| 1 Capture (stills) | `<stamp>-DSCnnnnn.ARW`, `.JPG` (camera's, untouched) | `<stem>.json` `observatory.still/1`, one line in the night's `index.jsonl` | `Controller.StillCamera.take/5` via `Sidecar` | `fits` block in the sidecar (to add); optional CFA FITS made on the Mac |
| 1 Capture (scope camera) | `<ms>-<n>.fits` | FITS header, `frames` table (SQLite) | `ScopeCamera.Header.cards/2` | FITS (exists) |
| 2 Plate solve | `<stem>.solve.json` | `observatory.still.solve/1` | `StillCamera.write_solve/1` | WCS cards (to add) |
| 3 Calibration | darks/flats as stage 1 frames; masters `master_<exp>s_iso<iso>.npz` + `.json`, flat folders (`flat_planes.npz`, `flat.json`) | per tool JSON | `darks.py`, `twilight_flat.py`, `skyflat.py` | master FITS with `IMAGETYP = 'MASTER ...'` (to add) |
| 3 Sensor map | `sensor_map.json` on the card | `SensorMap.status/0` | `Controller.StillCamera.SensorMap` | ours; optional FITS image |
| 4 Stack | `<target>-stack.tif` (linear, no tags), `recipe.json`, `work/solve/stack.wcs` | recipe (no schema) | `hack/stacks/<night>/<target>/step*.py` | `<target>-stack.fits` with WCS + HISTORY (to add) |
| 5 Finished picture | `final/<target>.png`, `.jpg`, `final/<target>.json` (finish recipe) | finish recipe | `crop.py`, `finish16.py` | XMP with AVM (to add) |
| 6 Published | `share/*.jpg`, `observations/<night>/images/*.jpg`, `objects.json` | `objects.json`, `plan.json`, `session.md` | `annotate.py`, `mix site.build` (strips all metadata) | none: scrubbed (decided 23 October 2026) |

---

## Stage 1: capture, per frame

The sidecar today is `observatory.still/1`. Its next version adds the blocks
marked **new** and a `fits` block. Columns: our field and where it lives
now; the standard keyword(s) it maps to; units; whether the keyword is
standard (S: FITS 4.0 or a registered convention), convention (C: the
capture-program keyword readers expect, source in brackets), or ours (X:
`HIERARCH OBS ...`); XISF property for PixInsight.

### Identity and files

| Ours (sidecar path) | Now | FITS | Units | Kind | XISF / note |
|---|---|---|---|---|---|
| `schema` | yes | `HIERARCH OBS SCHEMA` | | X | |
| `seq` | yes | `HIERARCH OBS FRAME SEQ` (scope camera already) | count | X | `Image:FrameNumber` |
| `files[].name`, `camera_name`, `format`, `bytes`, `sha256` | yes | `HIERARCH OBS FILE RAW SHA256` etc.; `FILENAME` is not standard, skip | bytes, hex | X | FITS files carry `CHECKSUM`/`DATASUM` (S) |
| `run.id`, `run.k`, `run.of` **new** | no | `HIERARCH OBS RUN ID`, `... RUN K` | | X | `Image:GroupId`. Today runs are found by hand-typed UTC windows in each `common.py`. |
| `purpose` **new**: `run`, `single`, `finder`, `focus`, `centre`, `test` | no (scope camera has `OBS FRAME WHY`) | `IMAGETYP = 'SNAPSHOT'` (N.I.N.A.) for anything not meant for a stack; `HIERARCH OBS FRAME WHY` | | C + X | lets stackers skip focus and centring frames without time windows |

### Frame type

| Ours | Now | FITS | Kind | Note |
|---|---|---|---|---|
| `frame.type` (`dark`, `flat`; absent means light) | written, but 0 of 1,135 real sidecars have it | `IMAGETYP = 'LIGHT' / 'DARK' / 'FLAT' / 'BIAS' / 'DARKFLAT'` | C (N.I.N.A. upper case; MaxIm writes `'Light Frame'`; Siril and PixInsight WBPP match either, case-insensitive) | write `light` explicitly instead of absent |
| `frame.flat_kind` **new**: `twilight`, `sky`, `panel`, `cloud` | no | `HIERARCH OBS FLAT KIND` | X | |
| `frame.cap` **new** (dark: cap on, tube covered) | no | `HIERARCH OBS DARK HOW` | X | |

### Time

| Ours | Now | FITS | Units | Kind | XISF |
|---|---|---|---|---|---|
| `time.shutter_pressed` | yes | `DATE-OBS`, `DATE-BEG`, `MJD-OBS`, `MJD-BEG` | UTC ISO / MJD | S | `Observation:Time:Start` |
| `time.exposure_end` | yes (computed: press + shutter) | `DATE-END`, `MJD-END` | | S | `Observation:Time:End` |
| mid-exposure **new** | no | `DATE-AVG`, `MJD-AVG` | | S | needed for ephemerides (Saturn's moons) and photometry |
| `time.exposure_s` / `camera.exposure_s` | yes (twice) | `EXPTIME` (C, every reader), `EXPOSURE` (C, older), `XPOSURE` (S, FITS 4.0 effective exposure) | s | | `Instrument:ExposureTime` |
| `time.picture_ready`, `time.saved` | yes | `HIERARCH OBS TIME READY`, `... SAVED`; `DATE` = file written (S) | UTC | X / S | |
| `time.clock` (prose) | prose | `HIERARCH OBS CLOCK SOURCE` = `ntp` / `peer` / `own`, `HIERARCH OBS CLOCK ERR S` | s | X | replace the sentence with an enum and an error bound |
| `time.note` (prose) | prose | `COMMENT` | | S | keep as a comment, not data |
| camera's own clock **new** (`camera.clock_exif`, `camera.clock_offset_s`) | no | `HIERARCH OBS CAMERA CLOCK OFFSET S` | s | X | the a6000's EXIF `DateTimeOriginal` reads `2014:01:01 08:02:02`: its clock was never set. Siril or PixInsight reading the ARW directly date every frame 2014. Record the offset; set the camera's clock over PTP at connect if the property is writable (to check). |

### Camera and sensor

| Ours | Now | FITS | Units | Kind | XISF / note |
|---|---|---|---|---|---|
| `camera.manufacturer`, `camera.model` | yes | `INSTRUME = 'Sony ILCE-6000'` | | S | `Instrument:Camera:Name` |
| `camera.id` | yes | `HIERARCH OBS CAMERA ID` | | X | |
| `camera.serial` **new** | no (PTP device info has `serial_number`; scope camera writes `OBS CAMERA SERIAL`) | `HIERARCH OBS CAMERA SERIAL` | | X | internal only (Privacy) |
| `camera.firmware` **new** | no (PTP `device_version`; EXIF says `ILCE-6000 v2.00`) | `HIERARCH OBS CAMERA FIRMWARE` | | X | |
| `camera.iso` | yes (from the shutter's settings) | `ISOSPEED` | ISO | C (MaxIm/BackyardEOS, Siril) | `Instrument:Camera:ISOSpeed`. Stacking tools trust the RAW's EXIF ISO over this; the sidecar now reads at shutter time (`settings_from: "shutter"`), keep both and flag a disagreement. |
| CMOS gain setting (astro cameras later; scope camera now) | scope camera `GAIN` | `GAIN`, `OFFSET` | camera units | C (N.I.N.A.) | |
| conversion gain **new** | no | `EGAIN` | e-/ADU | C (N.I.N.A., SBIG) | `Instrument:Camera:Gain` (XISF's Gain is e-/ADU, not the setting). Measure per ISO from flats, or leave out. |
| `camera.shutter` (words) | yes | `HIERARCH OBS CAMERA SHUTTER` | string | X | `EXPTIME` carries the number |
| `camera.quality` | yes | `HIERARCH OBS CAMERA QUALITY` | | X | |
| `camera.f_number` | **writes `0.0`** (no lens) | `FOCRATIO` comes from optics, not the camera | | | drop 0.0: absent |
| `camera.focus` | yes | `HIERARCH OBS CAMERA FOCUS MODE` | | X | |
| exposure program **new** (`describe/1` has `program`) | no | `HIERARCH OBS CAMERA PROGRAM` | | X | |
| as-shot white balance **new** | no (in the RAW; recipe reads it) | `HIERARCH OBS CAMERA WB` | multipliers | X | |
| `camera.battery_pct` | yes | `HIERARCH OBS CAMERA BATTERY PCT` | % | X | |
| sensor temperature | no sensor on the a6000 | `CCD-TEMP`, `SET-TEMP` | degC | C | astro cameras later; Sony maker notes may hold a temperature (check with exiftool before relying on it). `Instrument:Sensor:Temperature`, `...:TargetTemperature` |
| `sensor` **new** (from a per-model camera profile): `w_px`, `h_px`, `pixel_um`, `w_mm`, `h_mm`, `cfa`, `bayer_offset`, `black_dn`, `white_dn`, `bits` | no: hard-coded (`@sensor_mm 23.5` in `still_camera.ex`, plane order in `rawplanes.py`) | `XPIXSZ`/`YPIXSZ` (um), `XBINNING`/`YBINNING` = 1, `BAYERPAT = 'RGGB'`, `XBAYROFF`/`YBAYROFF` = 0, `SATURATE` (white level), `HIERARCH OBS RAW BLACK` | um, DN | C (`BAYERPAT`, `XBAYROFF` N.I.N.A./Siril; `SATURATE` common) | `Instrument:Sensor:XPixelSize`. Also the JPEG's 6000 x 4000 sits inside the RAW's 6024 x 4024: record that offset once (`sensor.jpeg_in_raw_px`), since the solve is on the JPEG and stacks are on RAW planes. |

### Optics

| Ours | Now | FITS | Units | Kind | XISF |
|---|---|---|---|---|---|
| `optics.focal_length_mm` | yes | `FOCALLEN` | mm | C | `Instrument:Telescope:FocalLength` (m) |
| `optics.aperture_mm` | yes | `APTDIA` | mm | C | `Instrument:Telescope:Aperture` (m) |
| focal ratio **new** (derived) | no | `FOCRATIO` | | C (N.I.N.A.) | |
| `optics.focal_length_from` (`solve`/`label`), `focal_length_label_mm` | yes | `HIERARCH OBS OPTICS FOCAL FROM`, `... FOCAL LABEL MM` | | X | |
| telescope name **new** | no in stills; scope camera **misuses `TELESCOP` for the mount** | `TELESCOP = 'Celestron 8SE'` (the optical tube) | | S | `Instrument:Telescope:Name`. Mount goes to `HIERARCH OBS MOUNT NAME`. |
| reducer / accessories **new** | no | `HIERARCH OBS OPTICS TRAIN` | | X | |
| focuser | none (manual) | `FOCUSPOS`/`FOCPOS`, `FOCTEMP` | steps, degC | C | `Instrument:Focuser:Position`, for later |
| filter | none (stock Bayer) | `FILTER` absent (one-shot colour) | | C | `Instrument:Filter:Name` |

### Site and observer

| Ours | Now | FITS | Units | Kind | XISF |
|---|---|---|---|---|---|
| `site.lat` | yes, full precision | `SITELAT` (C, decimal degrees as N.I.N.A. writes), `OBSGEO-B` (S) | deg N | | `Observation:Location:Latitude` |
| `site.lon` | yes, full precision | `SITELONG` (C), `OBSGEO-L` (S) | deg E | | `Observation:Location:Longitude` |
| `site.elevation_m` **new** | no (Ephemeris takes it, nothing stores it) | `SITEELEV` (C), `OBSGEO-H` (S) | m | | `Observation:Location:Elevation` |
| `site.from` **new** (typed, phone, config) | no | `HIERARCH OBS SITE FROM` | | X | |
| observer **new** | no | `OBSERVER = 'Brad Gessler'` | | S | `Observation:Observer:Name` |

### Target and pointing

| Ours | Now | FITS | Units | Kind | Note |
|---|---|---|---|---|---|
| `object` **new**: `name` (SIMBAD), `title`, `ra_deg`, `dec_deg` (catalogue, ICRS), `from` (the hold) | no: the Tracker's hold name is read for Cloud and SensorMap, then dropped | `OBJECT = 'M 27'`, `OBJCTRA`, `OBJCTDEC` (target's catalogue place, sexagesimal) | deg | S (`OBJECT`) + C | `Observation:Object:Name`, `:RA`, `:Dec`. Scope camera header **puts the pointing in `OBJCTRA`/`OBJCTDEC`**: those are the target's. |
| `pointing.ra_deg`, `dec_deg` | yes (model's guess, about 1 degree off on a poor alignment) | `RA`, `DEC` | deg | C (N.I.N.A.: where the mount says it points) | `Observation:Center:RA`/`:Dec` only after a solve |
| `pointing.equinox` | `2000.0` | `EQUINOX = 2000.0`, `RADESYS = 'ICRS'` | | S | `Observation:Equinox`, `Observation:CelestialReferenceSystem` |
| `pointing.source` | yes | `HIERARCH OBS POINTING SOURCE` | | X | exists in scope camera |
| `pointing.alt_deg`, `az_deg` | yes | `CENTALT`, `CENTAZ` | deg | C (MaxIm, N.I.N.A.) | internal only (Privacy) |
| airmass **new** for stills (scope camera has it) | no | `AIRMASS` | | C | use a refraction-aware formula (Kasten and Young) not `1/sin(alt)` near the horizon; internal only |
| hour angle **new** | no | `OBJCTHA` | h | C (MaxIm) | internal only |
| pier side **new** | no (derivable from the Dec axis and home) | `PIERSIDE = 'EAST' / 'WEST'` | | C (N.I.N.A., ASCOM SideOfPier pointing state) | decides meridian-flip rotation in stacks |
| camera angle **new** (from the solve) | no | `OBJCTROT` / `ROTATANG` | deg | C | no rotator; after a solve this is the field's position angle |

### Mount, model, tracking (ours)

| Ours | Now | FITS | Units | Kind |
|---|---|---|---|---|
| `mount.id` | yes | `HIERARCH OBS MOUNT ID` | | X (exists in scope camera) |
| `mount.start` / `mount.end`: `connected`, `tracking`, `homed`, `ra/dec.{deg, steps, deg_per_s, running}`, `at` | yes | `HIERARCH OBS MOUNT START RA DEG` ... (as the scope camera writes) | deg, steps, deg/s | X |
| `mount.track[]` (4 Hz samples) | yes | JSON only (too long for a header) | | X |
| `model.n`, `model.rms_arcmin`, `model.stale?` | yes | `HIERARCH OBS MODEL POINTS`, `... RMS ARCMIN`, `... STALE` | arcmin | X |
| `model.axis_words` | **prose** | `HIERARCH OBS MODEL AXIS ALT DEG`, `... AXIS AZ DEG`, `... AXIS OFF DEG` (numbers; keep the words as a comment) | deg | X, internal only (the axis altitude gives the latitude away) |
| `tracking` (being added): `axis_off_deg`, `rate_deg_per_h`, `corner_arcsec`, `smear_arcsec`, `max_exposure_s`, `tolerance_arcsec` | in progress | `HIERARCH OBS TRACKING AXIS OFF DEG`, `... ROT DEG PER H`, `... CORNER ARCSEC`, `... SMEAR ARCSEC`, `... MAX EXP S`, `... TOL ARCSEC` | deg, deg/h, arcsec, s | X. `smear_arcsec` can be written as `false` when the exposure is unknown (`is_number(exposure_s) && ...`): should be absent. |
| `settling`, `settle.since_slew_s`, `settle.settle_s` | yes | `HIERARCH OBS SETTLING`, `... SINCE SLEW S`, `... SETTLE S` | s | X |
| `dither.{k, east_arcmin, north_arcmin, radius_arcmin}` | yes (400 frames) | `HIERARCH OBS DITHER K`, `... EAST ARCMIN`, `... NORTH ARCMIN`, `... RADIUS ARCMIN` | arcmin | X |
| `lock_on.{state, holding, why, target, rates, error_px, offset, calibration, saved_calibration}` | yes | `HIERARCH OBS LOCKON STATE`, `... HOLDING`, `... ERR PX`; the calibration matrix in JSON only | px, px/s | X (no guiding standard; PHD2 keeps its own log) |

### Sky and measures (ours, with the nearest standard noted)

| Ours | Now | FITS | Units | Kind | Note |
|---|---|---|---|---|---|
| `cloud` (bool), `transparency`, `transparency_from.{stars, sky_ratio, first}` | 315 frames | `HIERARCH OBS SKY CLOUD`, `... TRANSPARENCY`, `... TRANSP STARS` | ratio | X | not `CLOUDCVR` (N.I.N.A.'s is percent of sky from a cloud sensor: a different quantity) |
| `measured.{w, h, background, max, stars, bright}` | yes | `HIERARCH OBS FRAME BACKGROUND`, `... MAX`, `... STARS` (scope camera names) | DN of the 8-bit copy | X | `measured.copy` is prose: replace with `copy_w`, `copy_kind` |
| `measured.star_size.{arcsec, px, n, w, arcsec_per_px, measure}` | 1,018 frames | `HIERARCH OBS STARS HFD ARCSEC`, `... HFD PX`, `... HFD N` | arcsec | X | for a Gaussian star HFD equals FWHM, so this is also ObsCore `s_resolution`. N.I.N.A.'s `STARFWHM` is a weather sensor's seeing: don't reuse it. |
| Moon **new**: `alt_deg`, `illum`, `sep_deg` | no | `HIERARCH OBS MOON ALT DEG`, `... ILLUM`, `... SEP DEG` | deg, fraction | X | explains a bright sky; Ephemeris already computes it |
| Sun altitude **new** | no | `HIERARCH OBS SUN ALT DEG` | deg | X | twilight flats are chosen by it |
| sky brightness **new** (later, once frames are photometric) | no | `MPSAS` / `SKYQUAL` | mag/arcsec^2 | C (N.I.N.A.) | |
| `plate_solve.{queued, mount, plate, answer_in, why}` | yes | `HIERARCH OBS PLATE N`, `... PLATE ANSWER` | | X | |
| `sensor_map` **new**: id and SHA-256 of the map in force | no | `HIERARCH OBS SENSOR MAP SHA256`, `... UPTIME` | | X | which dust map a frame was dithered against |

### Box and software

| Ours | Now | FITS | Kind |
|---|---|---|---|
| `box.node` | yes | `HIERARCH OBS BOX NODE` | X |
| `box.firmware` (nerves_fw_uuid; absent when run from `mix phx.server`) | yes, 7 frames without | `HIERARCH OBS BOX FIRMWARE` | X |
| software version **new** | no | `SWCREATE = 'Observatory <version> (<git sha>)'` | C (exists as `'Observatory'` in the scope camera) |

### The scope camera's FITS header (`ScopeCamera.Header`): changes

| Card | Now | Should be |
|---|---|---|
| `TELESCOP` | `'EQ6-R (ttyUSB0)'` (the mount) | the optical tube; mount in `HIERARCH OBS MOUNT NAME` |
| `IMAGETYP` | always `'LIGHT'` | from the frame's type; `'SNAPSHOT'` for live view |
| `OBJCTRA`, `OBJCTDEC` | the pointing | the target's catalogue place; pointing stays in `RA`/`DEC` |
| `RA`, `DEC` | yes | keep |
| missing | | `OBJECT`, `RADESYS`, `MJD-OBS`, `DATE-AVG`, `SITEELEV`, `OBSERVER`, `FOCRATIO`, `PIERSIDE`, `EGAIN` (when measured), `CHECKSUM`/`DATASUM` |
| `XPIXSZ` | `2.9 * binned` hard-coded for the IMX307 | from the camera profile |

---

## Stage 2: plate solve

`<stem>.solve.json` (`observatory.still.solve/1`) today keeps the centre,
field size, rotation, parity, scale, star count and time. The solver
(`Controller.Sky.Solve.Local`) writes the full WCS (`solve.wcs`) into a
temporary folder and deletes it; `Plates` drops the index name
(`Map.take` without `:index`). The solve is made on a 1,500 x 1,000 grey copy
(`@solve_w 1400`, decoded at half size then halved), 4 x smaller than the
6,000 px JPEG.

| Ours (solve.json) | Now | FITS / WCS | Units | Kind | XISF / AVM |
|---|---|---|---|---|---|
| `solution.ra_deg`, `dec_deg` (centre) | yes | `CRVAL1`, `CRVAL2` (at `CRPIX` = image centre), `CTYPE1 = 'RA---TAN-SIP'`, `CTYPE2 = 'DEC--TAN-SIP'`, `CUNIT1/2 = 'deg'` | deg | S (WCS I, II) | `PCL:AstrometricSolution:ReferenceCelestialCoordinates`; `avm:Spatial.ReferenceValue` |
| `wcs` **new**: the whole `solve.wcs` header: `WCSAXES`, `CRPIX1/2`, `CD1_1`, `CD1_2`, `CD2_1`, `CD2_2`, `LONPOLE`, `LATPOLE`, `A_ORDER`, `A_p_q`, `B_*`, `AP_*`, `BP_*`, `IMAGEW`, `IMAGEH` | **thrown away** | as written by astrometry.net | deg/px | S (WCS, SIP convention) | `PCL:AstrometricSolution:LinearTransformationMatrix`, `...:ReferenceImageCoordinates` |
| `wcs_full` **new**: the same for the full-size JPEG | no | `CRPIX_full = (CRPIX_copy - 0.5) * s + 0.5`, `CD_full = CD_copy / s`, SIP `A_p_q` scaled by `s^(1-p-q)`, `s = 4` | | S | so the solve applies to the camera's picture, not our copy |
| `solution.width_deg`, `height_deg` | yes | derived from WCS | deg | | ObsCore `s_fov` |
| `solution.pixscale_arcsec` | yes | derived (`sqrt(abs(det CD)) * 3600`); `PIXSCALE` (C, ASTAP) | arcsec/px | C | `avm:Spatial.Scale` (deg/px, with sign) |
| `solution.rotation_deg` ("up is N degrees E of N", astrometry.net) | yes | derived; `CROTA2` only for readers that need it (deprecated in WCS II) | deg | | `avm:Spatial.Rotation`; derive from `CD`, not from this number, because of parity and the AVM y flip |
| `solution.parity` | yes | sign of `det CD` | | | |
| `solution.stars` | yes | `HIERARCH OBS SOLVE STARS` | | X | |
| `solution.seconds` | yes | `HIERARCH OBS SOLVE SECONDS` | s | X | |
| `solution.solver` (`"this machine"`) | words | `HIERARCH OBS SOLVE SOFTWARE = 'astrometry.net 0.9x'`, `... INDEX = '4100 series (Tycho-2)'` | | X | `PCL:AstrometricSolution:CatalogName`, `...:CreatorApplication` |
| `state`, `reason` | yes | `PLTSOLVD = T/F` | | C (PinPoint, MaxIm) | |
| `focal_length_mm` | yes | `FOCALLEN` (measured) | mm | C | |
| `residual_arcmin` (in `plate_state`, not written) **new** | no | `HIERARCH OBS SOLVE RMS ARCSEC` | arcsec | X | |
| `corners` **new** (four RA/Dec) | no | | deg | | ObsCore `s_region` (POLYGON ICRS) |
| `written` | yes | `DATE` | UTC | S | `PCL:AstrometricSolution:CreationTime` |

---

## Stage 3: calibration frames, masters, the sensor map

Calibration frames are stage 1 frames with `frame.type` set: same record,
same `fits` block. Today none has been recorded that way; the 13 October
twilight flats were found by time and ISO (`twilight_flat.py`), darks by the
same rule or a `darks/` folder (`darks.py`).

### Frames

| Field | FITS | Kind | Note |
|---|---|---|---|
| type | `IMAGETYP = 'DARK' / 'FLAT' / 'BIAS' / 'DARKFLAT'` | C | |
| matched exposure and ISO | `EXPTIME`, `ISOSPEED` | C | darks are matched on these |
| temperature | `CCD-TEMP` when the camera has one; the a6000 has none | C | darks are only "same night, before or after"; record the time gap |
| Sun altitude (flats) | `HIERARCH OBS SUN ALT DEG` | X | |
| tracking off (flats) | `HIERARCH OBS MOUNT START TRACKING` | X | |
| flat kind | `HIERARCH OBS FLAT KIND` | X | |

### Masters (`darks.py`, `twilight_flat.py`, `skyflat.py`)

Write each master as FITS beside the `.npz` (one HDU per colour plane, or
`NAXIS3 = 4` in R, G1, G2, B order). Same JSON as today beside it, with
`schema: "observatory.master/1"` and the inputs' SHA-256.

| Field (tool JSON now) | FITS | Kind | XISF |
|---|---|---|---|
| kind | `IMAGETYP = 'MASTER DARK' / 'MASTER FLAT'` | C (PixInsight WBPP writes this form) | |
| frame count | `NCOMBINE` | C (IRAF) | |
| exposure, ISO | `EXPTIME`, `ISOSPEED` | C | |
| combine (sigma-clipped mean, 3 sigma, MAD) | `HISTORY` lines; `HIERARCH OBS COMBINE` | S + X | |
| normalisation (flat = 1 at the sensor centre) | `HIERARCH OBS FLAT NORM` | X | |
| inputs | `HISTORY` one line per input name + SHA-256, also in the JSON | S | |
| time span | `DATE-OBS` (first), `DATE-END` (last) | S | |
| plane order, CFA | `BAYERPAT = 'RGGB'`, `HIERARCH OBS PLANES = 'R G1 G2 B'` | C + X | |
| hot pixels counted | `HIERARCH OBS HOT N` | X | |

### Sensor map (`SensorMap`, `sensor_map.json`)

| Field | Now | Standard | Kind |
|---|---|---|---|
| `spots[]` (sensor px, size arcsec, depth) | JSON | none. Closest standard object is a defect map or a flat; optionally export as a 240 px FITS image `IMAGETYP = 'DUSTMAP'` | X |
| `uptime` (fraction of sensor dimmed less than 3%) | JSON | none | X |
| `dither_arcmin` | JSON | none | X |
| `frames`, `pointings`, `at` | JSON | `NCOMBINE`, `DATE` | X |
| id **new**: SHA-256 of the map, referenced from each frame's sidecar | no | | X |

---

## Stage 4: stack (linear)

Today: `<target>-stack.tif`, 16-bit RGB, written with `metadata=None` (no
tags at all), camera RGB times daylight white balance, plus a pedestal of
1,000; the WCS sits in `work/solve/stack.wcs` and, for M33 and M42 only, in
the recipe as `wcs_header`. Proposed: also write `<target>-stack.fits`,
float32, `NAXIS3 = 3` (R, G, B), no pedestal, and keep the TIF only if some
tool wants it.

### Stack FITS header

| Field (recipe now) | FITS | Units | Kind | XISF |
|---|---|---|---|---|
| target | `OBJECT`, `OBJCTRA`, `OBJCTDEC` | | S + C | `Observation:Object:*` |
| frames used (`summary.frames`, `steps[4-5].numbers.used`) | `NCOMBINE` (C, IRAF), `STACKCNT` (C, Siril) | count | | |
| single exposure | `EXPTIME`, `XPOSURE` = one frame (the data are in per-frame DN) | s | | |
| total exposure (`integration_s`) | `LIVETIME` (C, Siril), `HIERARCH OBS INTEGRATION S` | s | | |
| first frame start, last frame end | `DATE-OBS`, `DATE-END`, `MJD-OBS`, `MJD-END`; `DATE-AVG` (weighted mid) | UTC | S | `Observation:Time:Start/End` |
| plate solve of the stack (`steps[9].numbers`, `stack.wcs`) | full WCS + SIP as in Stage 2, `CRPIX` shifted by the crop (`crop_on_reference_grid.x0/y0`) | | S | `PCL:AstrometricSolution:*` |
| pixel scale (0.777 arcsec/px) | from WCS; `XPIXSZ = 7.84` (2 x 2 cell), `XBINNING = 2` | um | C | |
| units (`tif.units`) | `BUNIT = 'adu'`; comment: per 15 s frame, 14-bit raw scale | | S | |
| pedestal (16-bit form only) | `PEDESTAL = -1000` (SBIG: add this to get zero-based) | DN | C | |
| calibration applied | `CALSTAT = 'F'` (flat only; `'DF'` with a dark) | | C (MaxIm) | |
| colour (`white_balance_applied`, `star_colour_factors`) | `HIERARCH OBS COLOUR SPACE = 'camera RGB'`, `... WB R`, `... WB B` | | X | |
| combine (`coadd.method`, paper) | `HISTORY` | | S | `PixInsight:ProcessingHistory` is PixInsight's own; we write `HISTORY` |
| every step | `HISTORY step 3 register: rotation + shift on stars, ref 20261018-040355, wrms <= 0.49 px` (one or more lines per recipe step) | | S | |
| star size in the stack | `HIERARCH OBS STARS HFD ARCSEC` | arcsec | X | |
| noise (`noise_faint_region`) | `HIERARCH OBS NOISE R/G/B` | DN | X | |
| recipe | `HIERARCH OBS RECIPE SHA256`, `HISTORY recipe: <path>` | | X | |
| instrument, telescope, site, observer | as Stage 1 | | | |
| integrity | `CHECKSUM`, `DATASUM` | | S | |

### Recipe (`recipe.json`): provenance

The recipes already hold every number. What they lack is a fixed shape.
Proposed `schema: "observatory.stack.recipe/1"`, shaped after W3C PROV / the
IVOA Provenance model (entities used, an activity, entities generated):

| Field | Now | Proposed |
|---|---|---|
| `schema` | absent | `observatory.stack.recipe/1` |
| `target` | prose (`"Messier 27 (NGC 6853), the Dumbbell Nebula, ..."`) | `{name: "M 27", ids: ["NGC 6853"], title, ra_deg, dec_deg}` plus the prose |
| inputs | M33, M42: `frames[].arw_sha256`; **M27: none**; Saturn: `every_frame` | `used[]: {file, sha256, sidecar_sha256, solve_sha256, weight, kept, why}` for every recipe |
| calibration inputs | paths to flat folders | `{flat: {path, sha256}, dark: {...}, sensor_map: {...}}` |
| tools | `tools.note` (prose); `coadd.py 1.1` inside a step | `software[]: {name, version or sha256}`, git commit of the repo, Python, numpy, OpenCV, rawpy, astrometry.net and its index series |
| outputs | paths; Saturn alone has `delivered_sha256` | `generated[]: {file, sha256, kind: stack_fits / stack_tif / picture_png / picture_jpg}` |
| paths | absolute (`/Users/...`) | relative to the night folder or the repo, plus the root once |
| steps | yes | keep; each step also becomes `HISTORY` in the FITS |
| `made` | yes | keep (`DATE` in the FITS) |

---

## Stage 5: finished picture (non-linear)

`final/<target>.png` (16-bit), `.jpg`, and `final/<target>.json` (the finish
recipe: sky to neutral, levels, midtones, grain, saturation, clipped
percentages). Not science data: no FITS. Carry XMP inside the PNG (`iTXt`
`XML:com.adobe.xmp`) and the JPEG (APP1), internal copy:

| Field | XMP | Note |
|---|---|---|
| derived from the stack | `xmpMM:DerivedFrom` (`stRef:documentID` = SHA-256 of the stack FITS), `xmpMM:DocumentID` (this picture's) | standard provenance chain |
| finish recipe | `xmpMM:History` (one `stEvt` per finish step: `action`, `parameters`, `softwareAgent`) | |
| full AVM | everything in Stage 6, plus `avm:Spatial.*` for this crop | |
| how it was made | `Iptc4xmpExt:DigitalSourceType = http://cv.iptc.org/newscodes/digitalsourcetype/computationalCapture` | says "captured and computed, not generated", the project's rule |

---

## Stage 6: published picture

Today `annotate.py` saves with no metadata and `mix site.build` strips APP1
to APP15 and COM from JPEGs (EXIF, GPS, XMP, ICC) and `tEXt`/`zTXt`/`iTXt`/
`eXIf`/`tIME` from PNGs, and refuses posts naming the town or the site's
coordinates to 1 to 3 decimals. Keep both.

**Decided (Brad, 23 October 2026): published pictures carry no metadata at all.** The build keeps stripping
everything, and nothing is injected afterwards. AVM and the rest live only in the internal copies (Stage 5);
the table below is what those internal copies carry, not what is published.

### AVM 1.2 (+ Dublin Core, IPTC, Photoshop)

| AVM field (XMP name) | From | Example |
|---|---|---|
| Creator: `dc:creator` | constant | `Brad Gessler` |
| `photoshop:Credit` | `objects.json` `credit` | `Brad Gessler` |
| `dc:rights`, `xmpRights:Marked = True`, `xmpRights:WebStatement` | COPYRIGHT.md | `(c) 2026 Brad Gessler. All rights reserved.` |
| `Iptc4xmpCore:CreatorContactInfo/Iptc4xmpCore:CiUrlWork` | constant | `https://bradgessler.com` |
| `avm:ReferenceURL` | the picture's page | |
| `avm:Publisher`, `avm:ID` | constant, slug | `bradgessler.com`, `2026-10-17/dumbbell-nebula` |
| `avm:Type` | | `Observation` (plain, annotated); `Collage` ("how it was made") |
| `avm:Image.ProductQuality` | | `Good` / `Moderate` / `Poor` |
| `dc:title`, `photoshop:Headline`, `dc:description` | `objects.json` `title`, `subtitle`, `what` | |
| `avm:Subject.Name` (bag) | recipe target | `M 27`, `NGC 6853`, `Dumbbell Nebula` |
| `avm:Subject.Category` | AVM taxonomy | e.g. a planetary nebula `B.4.1.3`, a spiral galaxy `C.5.1.1` (check against the AVM 1.2 taxonomy table) |
| `avm:Distance` (seq: light-years, redshift), `avm:Distance.Notes` | `objects.json` facts | `1300`, `1,200 to 1,400` |
| `avm:Facility`, `avm:Instrument` (seq, one per channel) | gear | `Celestron 8SE`, `Sony a6000` |
| `avm:Spectral.ColorAssignment` | | `Red`, `Green`, `Blue` |
| `avm:Spectral.Band` | | `Optical` x 3 |
| `avm:Spectral.Bandpass` | | `R (Bayer)`, `G (Bayer)`, `B (Bayer)` |
| `avm:Spectral.CentralWavelength` | camera curves, approximate | nm |
| `avm:Spectral.Notes` | recipe colour step | `Gaia DR3 star colours; camera daylight white balance` |
| `avm:Temporal.StartTime` (seq), `avm:Temporal.IntegrationTime` (seq) | stack `DATE-OBS`, `LIVETIME` | to the minute |
| `avm:DatasetID` | stack FITS SHA-256 | |
| `avm:Spatial.CoordinateFrame`, `avm:Spatial.Equinox` | | `ICRS`, `J2000` |
| `avm:Spatial.ReferenceValue`, `ReferencePixel`, `ReferenceDimension`, `Scale`, `Rotation`, `CoordsystemProjection` (`TAN`), `Quality` (`Full`) | stack WCS through the crop | **plain picture and its resizes only.** `ReferenceDimension` lets a resized copy (the 1600 px) share one block. Leave `Spatial` off thumbnails, cards and the annotated/how versions (their caption band changes the frame). Make it with PyAVM from the FITS WCS (`AVM.from_wcs`) and verify by drawing a catalogue star on the JPEG: AVM counts pixels from the bottom-left, our arrays from the top. |
| `avm:Spatial.Notes` | | `TAN-SIP solution reduced to TAN` |
| `avm:MetadataVersion`, `avm:MetadataDate` | | `1.2`, build time |
| `Iptc4xmpExt:DigitalSourceType` | | `computationalCapture` |
| location | | **none**: no `exif:GPS*`, no `Iptc4xmpCore:Location`, no `photoshop:City`. The words "San Francisco Bay Area" may appear in `dc:description` or the credit line only. |

---

## Privacy

Internal files (the box's card, the Mac's `~/.observatory`, the night
folders) keep the full location and everything that can be turned back into
it. Nothing published places the telescope finer than "San Francisco Bay
Area".

| Field | Internal | Published |
|---|---|---|
| `site.lat`, `site.lon`, `SITELAT`, `SITELONG`, `OBSGEO-*` | full precision | never |
| `site.elevation_m`, `SITEELEV` | full | never |
| town name | config | never (build refuses it) |
| `pointing.alt_deg`/`az_deg`, `CENTALT`, `CENTAZ`, `AIRMASS`, `OBJCTHA`, LST | full | never as numbers. Altitude with an exact time and a known RA/Dec gives the latitude back. Words like "about 60 degrees up" only where no clock time goes with them (the recipes already say so). |
| polar axis alt/az (`model`, `tracking`) | full | never (the axis altitude is close to the latitude); `axis_off_deg` alone is fine |
| field rotation rate | full | fine as words; depends on latitude only through the axis error |
| times | full | to the minute in AVM `Temporal.StartTime`; no `DATE-LOC`, no time zone |
| camera serial, box node, firmware UUID, file paths with the home folder | full | never (stripped with EXIF; keep paths in public recipes relative) |
| local weather from a station | if added later | never (a station ID is a place) |
| AVM `Spatial.*` (where in the sky) | | fine: says nothing about the ground |

Found in the audit, outside metadata: `config/config.exs` (`:site`) in this
public repository carries the town's name and the site's coordinates, and
three test files carry the same coordinates. The build's check protects the
blog from them; the repository itself does not. Moving the configured site to
an untracked file or the box's settings is a separate change.

---

## A queryable index: IVOA ObsCore

One row per frame, master, stack and finished picture, in SQLite
(`Controller.Repo` already has `settings` and `frames`), so "every M27 frame
under 5 arcsec with no cloud" is a query. ObsCore column names, so a VO tool
could read it later. `index.jsonl` stays the box's per-night log.

| ObsCore column | From | Units |
|---|---|---|
| `obs_id`, `obs_collection` (`observatory`), `obs_publisher_did` | file stem | |
| `dataproduct_type` | `image` | |
| `calib_level` | 0 ARW, 1 FITS made from it, 2 calibrated frame, 3 stack | |
| `target_name`, `target_class` | `OBJECT`, AVM category | |
| `s_ra`, `s_dec`, `s_fov`, `s_region` | solve (else pointing, flagged) | deg, POLYGON ICRS |
| `s_resolution` | star HFD (equals FWHM for a Gaussian) | arcsec |
| `s_pixel_scale`, `s_xel1`, `s_xel2` | WCS, size | arcsec, px |
| `t_min`, `t_max`, `t_exptime` | `MJD-OBS`, `MJD-END`, `EXPTIME` (stack: `LIVETIME`) | MJD, s |
| `em_min`, `em_max` | stock Bayer with IR cut, approximate | m (about 4.0e-7 to 7.0e-7) |
| `o_ucd` | `phot.count` | |
| `facility_name`, `instrument_name` | `TELESCOP`, `INSTRUME` | |
| `access_url`, `access_format`, `access_estsize` | path, `image/x-sony-arw` / `image/fits`, size | kB (ObsCore's unit) |
| extensions | `obs_transparency`, `obs_cloud`, `obs_settling`, `obs_dither_k`, `obs_smear_arcsec`, `obs_run_id`, `obs_purpose`, `obs_sha256` | |

---

## Gaps, ranked

Most valuable first: what makes data findable and usable in any tool, then
what makes stacks reproducible, then naming.

1. **The plate solve's WCS is thrown away.** The box solves 631 of 1,130
   pictures and keeps only the centre, size, rotation and parity; `solve.wcs`
   is deleted with its temporary folder and the index name is dropped. No
   frame, stack, TIF or JPEG carries a WCS; stacks keep `stack.wcs` in a
   work folder (and in the recipe for M33 and M42, not M27). Keep the header
   in `solve.json` (`wcs`, `wcs_full` scaled to the camera's picture),
   write it into every FITS and the AVM block.
2. **Stills have no standard-named time, and the camera's clock is 2014.**
   EXIF `DateTimeOriginal` reads `2014:01:01`; any standard tool opening the
   ARW dates it wrong, and only our JSON knows the real time. Add the `fits`
   block (`DATE-OBS`, `DATE-END`, `DATE-AVG`, `MJD-*`, `EXPTIME`), record the
   camera clock offset, set the camera's clock at connect if PTP allows.
3. **No target, no run, no purpose on a still.** `OBJECT` is absent
   though the Tracker knows the hold's name; runs are rebuilt from UTC
   windows typed into each `common.py`; focus, centring and finder frames are
   told apart by time. Add `object`, `run`, `purpose`.
4. **Calibration frames are not recorded as such.** `frame.type` exists in
   code and in `darks.py`'s reader, but 0 of 1,135 sidecars carry it; masters
   are `.npz` + JSON with no `IMAGETYP`, `NCOMBINE` or input hashes in a
   standard file. Add the capture flow that sets it, Sun altitude for flats,
   master FITS.
5. **The linear stack has no metadata.** The TIF is written with
   `metadata=None`. Write `<target>-stack.fits`: WCS, `NCOMBINE`/`STACKCNT`,
   `EXPTIME`/`LIVETIME`, dates, `CALSTAT`, `BUNIT`, `HISTORY` per step,
   recipe hash, `CHECKSUM`.
6. **Recipes are not uniform.** No `schema`; M27 has no input hashes; only
   Saturn hashes its outputs; tools have no versions or git commit; paths are
   absolute. Adopt `observatory.stack.recipe/1`.
7. **Published pictures carry nothing.** No credit, rights, AVM or source
   type; the build strips everything (rightly). Decide: inject a whitelisted
   XMP (AVM + IPTC) after the strip, or not.
8. **Scope camera FITS misnames three things.** `TELESCOP` holds the mount,
   `IMAGETYP` is always `LIGHT`, `OBJCTRA`/`OBJCTDEC` hold the pointing.
   Missing `OBJECT`, `RADESYS`, `MJD-OBS`, `SITEELEV`, `OBSERVER`,
   `FOCRATIO`, `PIERSIDE`, `CHECKSUM`. Pixel size is hard-coded.
9. **Sensor geometry is in code, not in records.** Pixel size, sensor mm,
   CFA pattern, black and white level, bit depth, and the JPEG's offset in the
   RAW: needed for `XPIXSZ`, `BAYERPAT`, `SATURATE` and for carrying a JPEG
   solve onto RAW planes. A per-model camera profile, copied into each record.
10. **Prose and sentinels where numbers belong.** `model.axis_words`,
    `time.clock`, `measured.copy`; `camera.f_number: 0.0` for "no lens";
    `tracking.smear_arcsec` can be `false`.
11. **Known but not written.** Camera serial and firmware (PTP device info),
    exposure program, as-shot white balance, site elevation, Moon (altitude,
    phase, separation), Sun altitude, pier side, solve residual, solver
    version and index series, which sensor map was in force.
12. **No archive index.** `index.jsonl` per night for stills, the `frames`
    table for the scope camera only, nothing for masters, stacks or pictures.
    An ObsCore-shaped table makes everything searchable from one place.
13. **Ours, already good, keep and namespace:** dither, settle, field
    rotation and smear, transparency and cloud, star HFD, lock-on and its
    calibration, the 4 Hz mount track, sensor map uptime, SHA-256 of every
    file. None has a standard; all go under `HIERARCH OBS`.

## Order of work

1. **One keyword map** (`Controller.Metadata.Fits`, and a matching
   `sidecar_fits.py` for the stacking tools): record in, ordered cards out.
   `ScopeCamera.Header` uses it (fixing `TELESCOP`, `IMAGETYP`, `OBJCTRA`);
   the sidecar gains its `fits` block from it. Tests: the cards for a known
   sidecar, and a Siril/astropy read of a written header.
2. **Keep the WCS.** Copy `solve.wcs` into `solve.json` (`wcs`,
   `wcs_full`), keep the index and the residual. Test: a catalogue star's
   pixel through `wcs_full` lands on the star in the 6,000 px JPEG.
3. **Capture context.** `object`, `run`, `purpose`, the camera profile
   (`sensor`), elevation, Moon and Sun, camera serial and firmware, clock
   offset, pier side; drop the sentinels and the prose. Schema
   `observatory.still/2`.
4. **Calibration capture.** A dark and a flat flow that set `frame.type`
   (and `flat_kind`, Sun altitude); masters written as FITS.
5. **Stacks.** `<target>-stack.fits` with WCS and `HISTORY`; recipe schema
   with hashes, versions and git commit; optional `arw2fits.py` so a night
   opens in Siril or PixInsight with the right dates and pointing.
6. **Finished pictures.** XMP with AVM, IPTC and `xmpMM` provenance in the
   internal PNG and JPEG; check with PyAVM round trip.
7. **Publishing** (after Brad's decision): strip, then inject the
   whitelisted packet; run `private_terms` over it; `Spatial` only on the
   plain picture and its resizes.
8. **Archive index.** ObsCore-shaped table in SQLite fed from sidecars,
   solves, masters and recipes.
