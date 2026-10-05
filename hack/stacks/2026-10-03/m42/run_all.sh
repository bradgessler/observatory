#!/bin/sh
# The whole M42 pipeline, in order. Usage: sh run_all.sh [from_step]   (steps: 1 2 3 4 5 6 7 8 9 9b 9c 10 11 12 12b 13 14 14b 14c 15)
# All of it takes about 5 minutes.
# Reads the RAWs in place; writes only to the work folder until step 14, which writes the pictures, and step 15, the recipe,
# into ~/.observatory/nights/2026-10-03-a6000/m42/.
#   PY        python with numpy, scipy, opencv, rawpy, tifffile, pillow
#   M42_WORK  work folder, needs about 6 GB (default: ../work beside this scripts folder)
#   FLAT      twilight (default if the morning's sky flats are in the stills folder) or cloud
# astrometry.net (solve-field, image2xy) must be on the PATH, with ~/.observatory/astrometry/astrometry.cfg.
cd "$(dirname "$0")"
PY=${PY:-../../mosaic2/venv/bin/python}
L=${M42_WORK:-../work}; mkdir -p "$L"
FROM=${1:-1}
run() { step=$1; shift; case " $ORDER " in *" $step "*) echo "== step $step: $*"; "$PY" "$@" > "$L/log_$step.txt" 2>&1 || { echo "step $step failed"; tail -5 "$L/log_$step.txt"; exit 1; };; esac; }
ALL="1 2 3 4 5 6 7 8 9 9b 9c 10 11 12 12b 13 14 14b 14c 15"; [ -n "$UNTIL" ] && ALL=$(echo "$ALL" | sed "s/ $UNTIL .*/ $UNTIL/")
ORDER=""; on=0
for s in $ALL; do [ "$s" = "$FROM" ] && on=1; [ $on = 1 ] && ORDER="$ORDER $s"; done
run 1 s1_frames.py
run 2 s2_hot.py
run 3 s3_stars.py
run 4 s4_register.py
run 5 s5_quality.py
run 6 s6_flat.py ${FLAT:-twilight}
run 7 s7_stack.py
run 8 s8_solve.py
run 9 s9_hdr.py
run 9b s9b_core.py
run 9c s9c_starwidth.py
run 10 s10_place.py
run 11 s11_resample.py
run 12 s12_background.py
run 12b s12b_flatcheck.py
run 13 s13_combine.py
run 14 s14_deliver.py
run 14b s14b_sharpen.py
run 14c s14c_notes.py
run 15 s15_recipe.py
