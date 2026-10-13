#!/bin/sh
# Step 12: crop, then levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the
# 16-bit stretch of step 10 at full depth). Every number that shaped the finished picture is on these lines, and
# finish16.py writes them to final/ngc2419.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   crop.py                 NGC 2419 is a haze 2 to 3 arcmin across in a 39 x 26 arcmin field: a cut of 1200 x 800 px
#                           (15.5 x 10.4 arcmin) chosen in step 9: the cluster at the lower left, the two bright stars
#                           that lead to it running to the upper right, sky all round; pixels untouched, nothing
#                           resampled, nothing enlarged. Crop first, then finish: levels are percentiles of what is in
#                           the frame.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky; the cluster and the stars' glare cover a few percent) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white-pct --gamma --curve   the brightest pixels to white (the two bright stars' cores touched the sensor's
#                           ceiling in every frame and are white already: clipped, not repaired), midtones, a small S-curve
#   --median --quiet --chroma-blur   where the picture is dark (the sky, not the haze's body): a 3 px median, then a
#                           bilateral filter on brightness (sigma 4 px, full below L 10, none above L 34), and colour
#                           blurred. Stars and the cluster's body are left alone. Tonight's M78 values (--black-pct 70
#                           --median 5 --quiet 5 12 50) were tried first and NOT kept: on this small haze they reached
#                           into its body and its edge and turned the grain (which step 11 finds real: it repeats in the
#                           odd and the even half stacks) into flat daubs. Four gentler settings were compared at full size.
#   --sat 1.0 --grey-below  colour as the camera matrix gives it, NO boost: step 11 measures the haze at red : green
#                           1.10 +- 0.14 and blue : green 0.81 +- 0.07 in the camera's daylight balance, the same as the
#                           field's stars (1.01, 0.86): a faintly warm white. Below the first L no colour at all (noise).
# The same options make the full field (ngc2419/ngc2419-field.*), kept beside the crop.
# Hooks: N2419_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${N2419_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
OUT=${N2419_OUT:-$NIGHT/ngc2419}
WORK=${N2419_WORK:-$OUT/work}
FINAL=${N2419_FINAL:-$NIGHT/final}
OPTS=${N2419_FINISH:-"--neutral --neutral-band 0 40 --black-pct 75 --black 0.03 --white-pct 99.9 --gamma 1.0 --curve 0.15 --median 3 --quiet 4 10 34 --chroma-blur 8 --sat 1.0 --grey-below 12 26"}
mkdir -p "$FINAL"
set -- $($PY -c "import json,sys; g=json.load(open(sys.argv[1]))['nebula_crop']; print(g['x'],g['y'],g['w'],g['h'])" "$WORK/step9_solve.json")
$PY crop.py "$WORK/ngc2419-stretched.png" "$WORK/ngc2419-crop" "$1" "$2" "$3" "$4" "NGC 2419 is a haze 2 to 3 arcmin across in a 39 x 26 arcmin field: a cut that holds it and the two bright stars west of it that people find it by, at the stack's own pixels (0.777 arcsec each), nothing resampled, nothing enlarged"
$PY finish16.py "$WORK/ngc2419-crop.png" "$FINAL/ngc2419" $OPTS
$PY finish16.py "$WORK/ngc2419-stretched.png" "$OUT/ngc2419-field" $OPTS
$PY skycheck.py "$FINAL/ngc2419.png" "$OUT/ngc2419-field.png"
