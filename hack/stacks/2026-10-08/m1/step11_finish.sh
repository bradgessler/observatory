#!/bin/sh
# Step 11: levels and colour with finish.py (the finish-pictures tool, reading the 16-bit stretch from step 10).
# One line per picture; every number that shaped the finished picture is on that line. skycheck.py prints the dark
# sky's colour: R-G and B-G should be within about 1 of 255.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky; the nebula covers about a quarter of it) made grey
#   --black-pct 20          black point at the 20th percentile of brightness, then lifted by 0.02: about 7% of the
#                           dark sky's noise goes to black, by choice (less noise over faint detail; 15 and 24 were tried)
#   --gamma 1.0             no midtone change beyond the arcsinh of step 10
#   no --quiet              the faint parts were already smoothed in step 10 (Gaussian, 6 px, stars left out); the
#                           bilateral filter here drew worm-like grain from noise this faint (tried, not kept)
#   --sat 1.0 --grey-below 12 28  colour as the camera matrix gives it, no boost: the nebula's colour is measured only at
#                           large scale (step 10 takes it from a 32 px blur); below L 12 no colour at all, full from 28
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M1_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/m1/work}
$PY finish.py "$WORK/m1-stretched.png" "$WORK/m1-finished" --neutral --neutral-band 0 40 --black-pct 20 --black 0.02 --gamma 1.0 --sat 1.0 --grey-below 12 28
$PY skycheck.py "$WORK/m1-finished.png"
