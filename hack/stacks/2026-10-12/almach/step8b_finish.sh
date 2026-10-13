#!/bin/sh
# Step 8b: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py reading the 16-bit stretch of step 7 at full depth,
# plus --white-max, see its header). One line; every number that shaped the picture is on it, and finish16.py writes them to final/almach.json.
# skycheck.py prints the dark sky's colour: R-G and B-G should be within about 1 of 255.
#   --neutral, band 0-60%  the darkest 60% of the picture (all of it is empty sky bar the pair) made grey: a check more than a change
#   --black-pct 60 --black 0.02   black point at the 60th percentile of brightness, lifted by 0.02: a small object on empty sky, so the
#                          black sits in the sky's own noise (less noise over faint detail, by choice; there is no faint detail to lose)
#   --white-pct 100 --white-max   white at the brightest colour channel of the brightest pixel, so the gold star's red and green are not cut
#   --gamma 1.0 --curve 0.15      no midtone lift, a slight S-curve
#   --quiet 2 10 40 --chroma-blur 2   brightness smoothed (bilateral, 2 px) and colour blurred only where dark
#   --sat 1.0 --grey-below 6 16   NO extra saturation: the colours are what the camera's planes give; below L 6 no colour at all
# Hooks: ALMACH_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${ALMACH_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
WORK=${ALMACH_WORK:-$NIGHT/almach/work}
FINAL=${ALMACH_FINAL:-$NIGHT/final}
OPTS=${ALMACH_FINISH:-"--neutral --neutral-band 0 60 --black-pct 60 --black 0.02 --white-pct 100 --white-max --gamma 1.0 --curve 0.15 --quiet 2 10 40 --chroma-blur 2 --sat 1.0 --grey-below 6 16"}
mkdir -p "$FINAL"
$PY finish16.py "$WORK/almach-stretched.png" "$FINAL/almach" $OPTS
$PY skycheck.py "$FINAL/almach.png"
