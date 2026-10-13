#!/bin/sh
# Step 10: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch
# of step 9 at full depth). One line; every number that shaped the finished picture is on it, and finish16.py writes
# them to final/m33.json. skycheck.py prints the dark sky's colour: R-G and B-G should be within about 1 of 255.
#   --neutral, band 0-12%   the darkest 12% made grey (narrow: the galaxy fills the frame). The stretch already shows
#                           the faint parts without colour, so this subtracts 0.0: a check more than a change.
#   --black-pct 14 --black 0.025  black point at the 14th percentile of brightness, then lifted by 0.025: the darkest
#                           sky's noise goes to black, by choice (less noise over faint detail). 6 was tried: the sky
#                           read grey (26 of 255) and flat. 20 was tried: 5% of the picture exactly black.
#   --white-pct 99.9 --gamma 0.9 --curve 0.3   the brightest 0.1% (star cores) to white, a small midtone lift and an
#                           S-curve so the arms stand off the sky
#   --quiet 3 10 40 --chroma-blur 4   brightness smoothed (bilateral, 3 px) and colour blurred only where dark
#   --sat 1.25 --grey-below 8 20     a galaxy's worth of colour; below L 8 no colour at all
# Hooks: M33_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M33_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
WORK=${M33_WORK:-$NIGHT/m33/work}
FINAL=${M33_FINAL:-$NIGHT/final}
OPTS=${M33_FINISH:-"--neutral --neutral-band 0 12 --black-pct 14 --black 0.025 --white-pct 99.9 --gamma 0.9 --curve 0.3 --quiet 3 10 40 --chroma-blur 4 --sat 1.25 --grey-below 8 20"}
mkdir -p "$FINAL"
$PY finish16.py "$WORK/m33-stretched.png" "$FINAL/m33" $OPTS
$PY skycheck.py "$FINAL/m33.png"
