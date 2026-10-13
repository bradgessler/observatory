#!/bin/sh
# Step 9: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch
# of step 8 at full depth). Every number that shaped the finished picture is on this line, and finish16.py writes them
# to final/ngc1535.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
# The crop was made in step 8 (pixels of the stack, quarter turns only), so levels are percentiles of what is shown.
#   --neutral, band 0-40%   the darkest 40% (sky) made grey
#   --black-pct / --black   black point at that percentile of brightness (the sky's own level), then lifted a little:
#                           the sky's noise below it goes to black, by choice (less noise over faint detail)
#   --white 1.0             the white point is the stretch's own full scale (step 8 put the nebula's brightest colour
#                           channel at 0.97 of it): a percentile of brightness would clip the disc's green and blue
#   --curve                 a small S-curve on brightness, colour ratios kept
#   --median --quiet --chroma-blur   where the picture is dark (L below 6, fading out by 14): a 3 px median, then a
#                           bilateral filter on brightness, and colour blurred. The shell's faint edge is about L 17
#                           and the disc far above: the nebula is left alone (a wider range, 12 to 45, was tried first
#                           and turned the shell's grain into facets), so the grain at the shell's edge is the stack's own.
#   --sat --grey-below      the colour as the camera's matrix gives it (x 1.0); below the first L no colour at all
# Hook: N1535_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${N1535_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}
OUT=${N1535_OUT:-$NIGHT/ngc1535}
WORK=${N1535_WORK:-$OUT/work}
FINAL=${N1535_FINAL:-$NIGHT/final}
OPTS=${N1535_FINISH:-"--neutral --neutral-band 0 40 --black-pct 60 --black 0.02 --white 1.0 --curve 0.15 --sat 1.0 --shadow-l 14 30 --grey-below 6 16 --median 3 --quiet 4 6 14 --chroma-blur 4"}
mkdir -p "$FINAL"
$PY finish16.py "$WORK/ngc1535-stretched.png" "$FINAL/ngc1535" $OPTS
$PY skycheck.py "$FINAL/ngc1535.png"
