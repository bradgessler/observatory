#!/bin/sh
# Step 12: crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/m1.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 the nebula is 6 x 4 arcmin in a 38 x 25 arcmin field of plain sky: a cut around the
#                           catalogue place (step 9 chose the rectangle: 800 x 600 px, 10.4 x 7.8 arcmin, the size of
#                           last week's Crab picture), pixels untouched, nothing resampled, nothing enlarged.
#                           Crop first, then finish: levels are percentiles of what is in the frame.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky; the nebula covers about a quarter of it) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white-pct --gamma --curve   the brightest pixels (star cores) to white, midtones, a small S-curve
#   --median --quiet --chroma-blur   where the picture is dark (the sky and the nebula's faint edge, not its body): a
#                           5 px median, then a bilateral filter on brightness, and colour blurred. Stars and the
#                           nebula's body are left alone. (Tried first: --black-pct 55 --black 0.03 --quiet 4 8 26, which
#                           left the sky peppered and the nebula's edge stippled; and --black-pct 50 --black 0.05, a
#                           brighter, mottled sky. Not kept: less noise over faint detail.)
#   --sat 1.0 --grey-below  colour as the camera matrix gives it, no boost; below the first L no colour at all (noise)
# The same options make the full field (m1/m1-field.*), kept beside the crop.
# Hooks: M1_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M1_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
OUT=${M1_OUT:-$NIGHT/m1}
WORK=${M1_WORK:-$OUT/work}
FINAL=${M1_FINAL:-$NIGHT/final}
OPTS=${M1_FINISH:-"--neutral --neutral-band 0 40 --black-pct 60 --black 0.04 --white-pct 99.9 --gamma 1.0 --curve 0.15 --median 5 --quiet 5 12 50 --chroma-blur 8 --sat 1.0 --grey-below 12 26"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['nebula_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/m1-stretched.png" "$WORK/m1-crop" "$1" "$2" "$3" "$4" "the nebula is 6 x 4 arcmin in a 38 x 25 arcmin field of plain sky: a cut around its catalogue place at the stack's own pixels, nothing resampled"
$PY finish16.py "$WORK/m1-crop.png" "$FINAL/m1" $OPTS
$PY finish16.py "$WORK/m1-stretched.png" "$OUT/m1-field" $OPTS
$PY skycheck.py "$FINAL/m1.png" "$OUT/m1-field.png"
