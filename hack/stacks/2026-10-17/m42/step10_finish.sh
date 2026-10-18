#!/bin/sh
# Step 10: levels, quiet sky and colour with finish16.py (the finish-pictures tool finish.py, reading the 16-bit stretch
# of step 9 at full depth). Started from tonight's M33 options (hack/stacks/2026-10-17/m33/step10_finish.sh) and changed one
# number at a time while looking at the result (the values and why are in the OPTS line's comment below):
#   --neutral, band 0-12%   the darkest 12% made grey (the nebula fills the frame: a narrow band)
#   --black-pct / --black   black point at the faintest part's own level, then lifted a little
#   --white-pct --gamma --curve   the brightest pixels to white, midtones, an S-curve
#   --quiet --chroma-blur   where the picture is dark: a bilateral filter on brightness, colour blurred
#   --sat --grey-below      saturation; below the first L none at all (there it is only noise)
# finish16.py writes final/m42.png, .jpg and final/m42.json (its recipe). Hooks: M42_FINISH="<options>".
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NIGHT=${M42_NIGHT:-$HOME/.observatory/nights/2026-10-17-a6000}
OUT=${M42_OUT:-$NIGHT/m42}
WORK=${M42_WORK:-$OUT/work}
FINAL=${M42_FINAL:-$(pwd)/final}
# From M33's: --white-pct 99.9 put the white point inside the joined core and washed out the Trapezium region, so
# --white 1.0 (the stretch's own full scale); gamma 0.9 -> 1.0 and black 14 -> 10 percent, 0.025 -> 0.02 (the first try
# was too bright); curve 0.25, saturation 1.2.
OPTS=${M42_FINISH:-"--neutral --neutral-band 0 12 --black-pct 10 --black 0.02 --white 1.0 --gamma 1.0 --curve 0.25 --quiet 3 10 40 --chroma-blur 4 --sat 1.2 --grey-below 8 20"}
mkdir -p "$FINAL"
$PY finish16.py "$WORK/m42-stretched.png" "$FINAL/m42" $OPTS
for h in odd even; do [ -f "$WORK/$h-stretched.png" ] && $PY finish16.py "$WORK/$h-stretched.png" "$WORK/$h-finished" $OPTS; done
$PY skycheck.py "$FINAL/m42.png"
