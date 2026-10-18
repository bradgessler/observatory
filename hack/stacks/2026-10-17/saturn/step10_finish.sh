#!/bin/sh
# Step 10: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading step 9's 16-bit
# picture at full depth). Every number that shaped the finished picture is on the OPTS line, and finish16.py writes them
# to final/saturn.json. skycheck.py prints the dark sky's colour: R-G and B-G within about 1.
#   --neutral, band 0-60%   the darkest 60% (open sky round the moons) made grey
#   --black-pct / --black   black point at the sky's own level (60th percentile), set just above zero (2 of 255): the moon field's
#                           grain goes to black, by choice (less noise; nothing faint is lost that a moon needs)
#   --white 1.0             step 9 already put the planet's brightest 0.05 percent at full scale
#   --quiet --chroma-blur   only where the picture is dark: the sky's grain smoothed, its colour blurred
#   --sat --grey-below      a little colour; the darkest sky has none (there it is only noise)
# Hooks: SAT_FINISH="<options>" replaces the options below.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
OPTS=${SAT_FINISH:-"--neutral --neutral-band 0 60 --black-pct 60 --black 0.008 --white 1.0 --gamma 1.0 --curve 0.1 --quiet 4 10 35 --chroma-blur 4 --sat 1.15 --shadow-l 14 30 --grey-below 10 22"}
$PY finish16.py final/saturn.png final/saturn-finished $OPTS
$PY skycheck.py final/saturn-finished.png
