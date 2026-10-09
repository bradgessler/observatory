#!/bin/sh
# M57, the Ring Nebula, night of 8/9 October 2026: the whole pipeline, in order.
# Usage: sh run_all.sh [from_step]      (steps: 1 2 3 4 5 6 6b 7 8 f 10 9 clean)
# About two minutes. Reads the RAWs in place (never writes them); writes only to the work folder until step 8, which
# writes m57-stack.tif, step 10, which writes the labelled m57-deconvolved.jpg, and step 9, which writes m57.jpg,
# m57-single-vs-stack.jpg and recipe.json into M57_OUT.
#   PY          python with numpy, scipy, opencv, rawpy, tifffile, pillow (default: ~/.observatory/pyenv)
#   M57_NIGHT   the night's folder (default ~/.observatory/nights/2026-10-08-a6000; RAWs in stills/)
#   M57_OUT     where the deliverables go (default $M57_NIGHT/m57)
#   M57_WORK    work folder, about 5 GB while it runs (default $M57_OUT/work)
#   M57_WORKERS parallel processes (default 4)
#   UNTIL       optional: last step to run
# astrometry.net (image2xy, solve-field) must be on the PATH, index files in ~/.observatory/astrometry.
# The step "clean" deletes the cached planes and the big intermediate arrays (about 4.5 GB); everything can be made
# again from step 1. With no variables set this reproduces the delivered picture.
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
export M57_NIGHT=${M57_NIGHT:-$HOME/.observatory/nights/2026-10-08-a6000}
export M57_OUT=${M57_OUT:-$M57_NIGHT/m57}
export M57_WORK=${M57_WORK:-$M57_OUT/work}
L=$M57_WORK; mkdir -p "$L"
FROM=${1:-1}
# levels and quiet sky (finish.py, the finish-pictures tool): the same numbers for the stack and for the single frame
export M57_FINISH_ARGS="--neutral --neutral-band 0 40 --black-pct 60 --black 0.02 --white-pct 99.99 --curve 0.15 --sat 1.0 --shadow-l 14 30 --grey-below 6 16 --median 5 --quiet 4 12 45 --chroma-blur 4"
ALL="1 2 3 4 5 6 6b 7 8 f 10 9 clean"; [ -n "$UNTIL" ] && ALL=$(echo "$ALL" | sed "s/ $UNTIL .*/ $UNTIL/")
ORDER=""; on=0
for s in $ALL; do [ "$s" = "$FROM" ] && on=1; [ $on = 1 ] && ORDER="$ORDER $s"; done
want() { case " $ORDER " in *" $1 "*) return 0;; esac; return 1; }
run() { step=$1; shift; if want "$step"; then echo "== step $step: $*"; "$PY" "$@" > "$L/log_$step.txt" 2>&1 || { echo "step $step failed"; tail -5 "$L/log_$step.txt"; exit 1; }; fi; }
run 1 step1_hot.py
run 2 step2_stars.py
run 3 step3_register.py
run 4 step4_quality.py
run 5 step5_select.py
run 6 step6_stack.py
run 6b step6b_dispersion.py
run 7 step7_solve.py
run 8 step8_render.py
if want f; then
  echo "== step f: finish.py and skycheck.py"
  "$PY" finish.py "$L/m57-stretched.png" "$L/m57-finished" $M57_FINISH_ARGS > "$L/log_f.txt" 2>&1 || { echo "finish failed"; exit 1; }
  "$PY" finish.py "$L/single-stretched.png" "$L/single-finished" $M57_FINISH_ARGS >> "$L/log_f.txt" 2>&1 || { echo "finish failed"; exit 1; }
  "$PY" skycheck.py "$L/m57-finished.png" "$L/single-finished.png" > "$L/skycheck.txt" 2>&1
  cat "$L/log_f.txt" "$L/skycheck.txt"
fi
run 10 step10_decon.py
run 9 step9_deliver.py
if want clean; then
  echo "== clean: cached planes and big intermediate arrays"
  rm -rf "$L/planes"
  rm -f "$L"/stack_*.npy "$L"/single_planes.npy "$L"/cover.npy "$L"/unreg_median_G1.npy "$L"/hotmap.npy "$L"/crop_*.npy "$L"/solve/stack.fits
fi
exit 0
