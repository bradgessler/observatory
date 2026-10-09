#!/bin/sh
# Step 11: levels and colour with finish.py (the finish-pictures tool, reading the 16-bit stretch from step 10).
# One line per picture; every number that shaped the finished picture is on that line. skycheck.py prints the dark
# sky's colour: R-G and B-G should be within about 1 of 255.
#   --neutral, band 0-40%   the darkest 40% of the crop (sky) made grey
#   --black-pct 40          black point at the sky's 40th percentile of brightness (then lifted by 0.02)
#   --gamma 0.9             a small midtone lift
#   --median 5 --quiet 4 15 55   where the picture is dark (L below 15, fading out by 55): a 5 px median, then a
#                           bilateral filter (4 px, 7 L units) on brightness. The shell (L 11 to 26) is in that range:
#                           its grain is traded for a quiet sky, by choice. Stars and the central star are left alone.
#   --sat 1.4 --grey-below 8 18  CIELAB chroma x 1.4; below L 8 no colour at all (there it is only noise), full from 18
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${N1514_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/ngc1514/work}
$PY finish.py "$WORK/ngc1514-stretched.png" "$WORK/ngc1514-finished" --neutral --neutral-band 0 40 --black-pct 40 --black 0.02 --gamma 0.9 --median 5 --quiet 4 15 55 --sat 1.4 --grey-below 8 18
$PY skycheck.py "$WORK/ngc1514-finished.png"
