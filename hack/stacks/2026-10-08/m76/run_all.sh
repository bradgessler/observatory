#!/bin/sh
# M76, night of 8 to 9 October 2026: the whole pipeline, in order. Usage: sh run_all.sh [from_step]
#   steps: 1 2 3 4 5 6 6n 6a 6b 7 8 9 10 11 12   (6 = ref grid, 7 = plate solve of it, 6n/6a/6b = north-up grid, whole and halves)
# About 3 minutes on the Mac Studio. Reads the RAWs in place (never writes them); writes only to the work folder until
# step 10 (m76.jpg) and step 12 (m76-stack.tif, recipe.json) in ~/.observatory/nights/2026-10-08-a6000/m76/.
#   PY        python with numpy, scipy, opencv, rawpy, tifffile, pillow (default ~/.observatory/pyenv/bin/python)
#   M76_WORK  work folder, needs about 5 GB while it runs (default ~/.observatory/nights/2026-10-08-a6000/m76/work)
#   M76_REF   reference frame time stamp (default 20261009-055305)
# astrometry.net (solve-field, image2xy, wcs-rd2xy, wcs-xy2rd, wcsinfo) must be on the PATH, with
# ~/.observatory/astrometry/astrometry.cfg. With no hooks set this reproduces the delivered run.
# After a good run: sh run_all.sh clean   deletes the big intermediates (planes, stacks) and keeps logs and step JSONs.
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
L=${M76_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/m76/work}; mkdir -p "$L"
if [ "$1" = clean ]; then
  rm -rf "$L/planes" "$L"/*.npy "$L"/*-stretched.png "$L"/solve_*.fits "$L"/solve_*.axy
  du -sh "$L"; exit 0
fi
FROM=${1:-1}
run() { step=$1; shift; case " $ORDER " in *" $step "*) echo "== step $step: $*"; env $ENVS "$PY" "$@" > "$L/log_$step.txt" 2>&1 || { echo "step $step failed"; tail -5 "$L/log_$step.txt"; exit 1; };; esac; ENVS=""; }
ALL="1 2 3 4 5 6 7 6n 6a 6b 8 9 10 11 12"
ORDER=""; on=0
for s in $ALL; do [ "$s" = "$FROM" ] && on=1; [ $on = 1 ] && ORDER="$ORDER $s"; done
ENVS=""
run 1 step1_solve.py
run 2 step2_hot.py
run 3 step3_stars.py
run 4 step4_register.py
run 5 step5_quality.py
run 6 step6_stack.py ref
run 7 step7_solve_stack.py
run 6n step6_stack.py north
ENVS="M76_HALF=a"; run 6a step6_stack.py north
ENVS="M76_HALF=b"; run 6b step6_stack.py north
run 8 step8_sky.py
run 9 step9_measure.py
run 10 step10_finish.py
run 11 step11_decon_trial.py
run 12 step12_deliver.py
echo "done: $(ls ~/.observatory/nights/2026-10-08-a6000/m76/ | tr '\n' ' ')"
