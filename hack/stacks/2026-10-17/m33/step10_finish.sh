#!/bin/sh
# Step 10: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch
# of step 9 at full depth). The options are the 13 October M33 picture's (hack/stacks/2026-10-12/m33/step10_finish.sh),
# so the two nights compare like for like:
#   --neutral, band 0-12%   the darkest 12% made grey (the galaxy fills the frame: a narrow band)
#   --black-pct / --black   black point at the faintest part's own level, then lifted a little
#   --white-pct --gamma --curve   the brightest pixels to white, midtones, an S-curve
#   --quiet --chroma-blur   where the picture is dark: a bilateral filter on brightness, colour blurred
#   --sat --grey-below      a little colour; below the first L none at all (there it is only noise)
# finish16.py writes final/m33.png, .jpg and final/m33.json (its recipe). Hooks: M33_FINISH="<options>".
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M33_NIGHT:-$HOME/.observatory/nights/2026-10-17-a6000}
OUT=${M33_OUT:-$NIGHT/m33}
WORK=${M33_WORK:-$OUT/work}
FINAL=${M33_FINAL:-$(pwd)/final}
OPTS=${M33_FINISH:-"--neutral --neutral-band 0 12 --black-pct 14 --black 0.025 --white-pct 99.9 --gamma 0.9 --curve 0.3 --quiet 3 10 40 --chroma-blur 4 --sat 1.25 --grey-below 8 20"}
mkdir -p "$FINAL"
$PY finish16.py "$WORK/m33-stretched.png" "$FINAL/m33" $OPTS
for h in odd even tonight oct13; do [ -f "$WORK/$h-stretched.png" ] && $PY finish16.py "$WORK/$h-stretched.png" "$WORK/$h-finished" $OPTS; done
$PY skycheck.py "$FINAL/m33.png"
