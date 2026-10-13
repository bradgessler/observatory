#!/bin/sh
# Step 12: crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/m78.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 M78 is 8 x 6 arcmin in a 39 x 25 arcmin field: a cut of 1320 x 990 px (17.1 x 12.8 arcmin)
#                           chosen in step 9 (M78 with sky all round, the dark lane and the arc beyond it, NGC 2064
#                           whole at the right; NGC 2071 is not in it), pixels untouched, nothing resampled, nothing
#                           enlarged. Crop first, then finish: levels are percentiles of what is in the frame.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky; the nebulae cover about a sixth of it) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white-pct --gamma --curve   the brightest pixels (star cores) to white, midtones, a small S-curve
#   --median --quiet --chroma-blur   where the picture is dark (the sky and the nebula's faint edge, not its body): a
#                           5 px median, then a bilateral filter on brightness, and colour blurred. Stars and the
#                           nebula's body are left alone.
#   --sat 1.0 --grey-below  colour as the camera matrix gives it, NO boost: step 11 measures the nebula at blue : green
#                           1.01 in the camera's daylight balance (white), bluer than the two stars that light it
#                           (0.83 and 0.63) but not blue in itself; the picture shows that and no more. Below the first
#                           L no colour at all (noise).
# The same options make the full field (m78/m78-field.*, with NGC 2071 at its left edge), kept beside the crop.
# Hooks: M78_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M78_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
OUT=${M78_OUT:-$NIGHT/m78}
WORK=${M78_WORK:-$OUT/work}
FINAL=${M78_FINAL:-$NIGHT/final}
OPTS=${M78_FINISH:-"--neutral --neutral-band 0 40 --black-pct 70 --black 0.03 --white-pct 99.9 --gamma 1.0 --curve 0.15 --median 5 --quiet 5 12 50 --chroma-blur 8 --sat 1.0 --grey-below 12 26"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['nebula_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/m78-stretched.png" "$WORK/m78-crop" "$1" "$2" "$3" "$4" "M78 is 8 x 6 arcmin in a 39 x 25 arcmin field: a cut that holds its glow with sky all round, the dark lane, the arc beyond it and NGC 2064, at the stack's own pixels, nothing resampled; NGC 2071, 14 arcmin away at the field's edge, is left to the full field"
$PY finish16.py "$WORK/m78-crop.png" "$FINAL/m78" $OPTS
$PY finish16.py "$WORK/m78-stretched.png" "$OUT/m78-field" $OPTS
$PY skycheck.py "$FINAL/m78.png" "$OUT/m78-field.png"
