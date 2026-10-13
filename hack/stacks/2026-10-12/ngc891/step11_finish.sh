#!/bin/sh
# Step 11: crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/ngc891.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 the galaxy is 13.5 x 2.5 arcmin in a 38 x 25 arcmin field of plain sky: a cut around its
#                           catalogue place (step 9 chose the rectangle), pixels untouched, nothing resampled. Crop
#                           first, then finish: levels are percentiles of what is in the frame.
#   --neutral, band 0-40%   the darkest 40% (sky) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white-pct 99.9 --gamma --curve   the brightest 0.1% (star cores) to white, midtones, a small S-curve
#   --quiet 4 12 45 --chroma-blur 5   where the picture is dark: a bilateral filter (4 px) on brightness, and colour
#                           blurred. Stars and the galaxy's bright middle are left alone.
#   --sat 1.15 --grey-below 8 18   a little colour; below L 8 no colour at all (there it is only noise)
# Tried and not kept: --black-pct 50 --median 5 --sat 1.3 (the sky mottled, the outer disc in daubs, the bulge a hard
# orange patch); --black-pct 65 --black 0.015 --gamma 0.85 --median 3 --quiet 3 10 40 (11% of the picture exactly
# black and the disc grainier).
# The same options make the full field (ngc891/ngc891-field.*), kept beside the crop.
# Hooks: N891_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${N891_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
OUT=${N891_OUT:-$NIGHT/ngc891}
WORK=${N891_WORK:-$OUT/work}
FINAL=${N891_FINAL:-$NIGHT/final}
OPTS=${N891_FINISH:-"--neutral --neutral-band 0 40 --black-pct 60 --black 0.02 --white-pct 99.9 --gamma 0.9 --curve 0.2 --quiet 4 12 45 --chroma-blur 5 --sat 1.15 --grey-below 8 18"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['galaxy_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/ngc891-stretched.png" "$WORK/ngc891-crop" "$1" "$2" "$3" "$4" "the galaxy is 13.5 x 2.5 arcmin in a 38 x 25 arcmin field of plain sky: a cut around its catalogue place at the stack's own pixels, nothing resampled"
$PY finish16.py "$WORK/ngc891-crop.png" "$FINAL/ngc891" $OPTS
$PY finish16.py "$WORK/ngc891-stretched.png" "$OUT/ngc891-field" $OPTS
$PY skycheck.py "$FINAL/ngc891.png" "$OUT/ngc891-field.png"
