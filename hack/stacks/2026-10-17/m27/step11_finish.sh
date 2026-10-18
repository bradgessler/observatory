#!/bin/sh
# Step 11 (CALIBRATED: the same options as the published picture; it goes to final-trial/m27.*): crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/m77.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 the galaxy is 7 x 6 arcmin in a 38 x 25 arcmin field of plain sky: a cut around the
#                           nucleus's catalogue place (step 9 chose the rectangle), pixels untouched, nothing resampled.
#                           Crop first, then finish: levels are percentiles of what is in the frame.
#   --neutral, band 0-40%   the darkest 40% (sky) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white-pct --gamma --curve   the brightest pixels (star cores, the nucleus) to white, midtones, a small S-curve
#   --quiet --chroma-blur   where the picture is dark: a bilateral filter on brightness, and colour blurred. Stars and
#                           the galaxy's bright middle are left alone.
#   --sat --grey-below      a little colour; below the first L no colour at all (there it is only noise)
# The same options make the full field (m27/m27-field.*), kept beside the crop.
# Hooks: M27_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M27_NIGHT:-$HOME/.observatory/nights/2026-10-17-a6000}
OUT=${M27_OUT:-$NIGHT/m27}
WORK=${M27_WORK:-$OUT/work}
FINAL=${M27_FINAL:-$(pwd)/final}
NAME=${M27_NAME:-m27}
OPTS=${M27_FINISH:-"--neutral --neutral-band 0 40 --black-pct 50 --black 0.02 --white 1.0 --gamma 1.0 --curve 0.15 --quiet 4 8 30 --chroma-blur 4 --sat 1.2 --shadow-l 14 30 --grey-below 8 18"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['galaxy_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/m27-stretched.png" "$WORK/m27-crop" "$1" "$2" "$3" "$4" "the nebula and its halo are about 8 x 10 arcmin in a 37 x 24 arcmin field of plain sky: a cut around the central star's catalogue place at the stack's own pixels, nothing resampled"
$PY finish16.py "$WORK/m27-crop.png" "$FINAL/$NAME" $OPTS
$PY finish16.py "$WORK/m27-stretched.png" "$OUT/m27-field" $OPTS
$PY skycheck.py "$FINAL/$NAME.png" "$OUT/m27-field.png"
