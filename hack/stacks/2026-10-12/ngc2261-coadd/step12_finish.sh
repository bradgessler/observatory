#!/bin/sh
# (Trial: the same crop and the same finish options as the delivered picture, on the proper coadd; to final-trial/.)
# Step 12: crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/ngc2261.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 NGC 2261 is 1.5 arcmin long in a 39 x 25 arcmin field: a cut of 800 x 600 px (10.4 x 7.8
#                           arcmin) chosen in step 9 (its middle 60 px north of R Monocerotis, so the fan sits in the
#                           middle with sky and field stars all round), pixels untouched, nothing resampled, nothing
#                           enlarged: 0.777 arcsec per pixel, the stack's own scale. Crop first, then finish: levels
#                           are percentiles of what is in the frame.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky; the fan covers 2% of it) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white --gamma --curve the stretch's own white kept (R Monocerotis is the brightest thing in the fan and is not
#                           clipped), midtones, a small S-curve
#   --median --quiet --chroma-blur   where the picture is dark (the sky and the fan's faint outer edge, not its body): a
#                           5 px median, then a bilateral filter on brightness, and colour blurred. Stars and the
#                           fan's body are left alone.
#   --sat 1.0 --grey-below  colour as the camera matrix gives it, NO boost: step 11 measures the fan at red : green
#                           1.00, blue : green 0.92 in the camera's daylight balance (near white, a little warm).
#                           Below the first L no colour at all (noise).
# The same options make the full field (ngc2261/ngc2261-field.*), kept beside the crop.
# Hooks: N2261_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${N2261_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
NAME=${N2261_NAME:-ngc2261-coadd}
OUT=${N2261_OUT:-$NIGHT/$NAME}
WORK=${N2261_WORK:-$OUT/work}
FINAL=${N2261_FINAL:-$NIGHT/final-trial}     # the trial: never final/
OPTS=${N2261_FINISH:-"--neutral --neutral-band 0 40 --black-pct 65 --black 0.03 --white 1.0 --gamma 1.0 --curve 0.15 --median 5 --quiet 5 12 50 --chroma-blur 8 --sat 1.0 --grey-below 12 26"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['nebula_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/$NAME-stretched.png" "$WORK/$NAME-crop" "$1" "$2" "$3" "$4" "NGC 2261 is 1.5 arcmin long in a 39 x 25 arcmin field: a cut with the fan in the middle and sky all round, at the stack's own pixels (0.777 arcsec each), nothing resampled, nothing enlarged"
$PY finish16.py "$WORK/$NAME-crop.png" "$FINAL/$NAME" $OPTS
$PY finish16.py "$WORK/$NAME-stretched.png" "$OUT/$NAME-field" $OPTS
$PY skycheck.py "$FINAL/$NAME.png" "$OUT/$NAME-field.png"
