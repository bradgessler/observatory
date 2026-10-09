#!/bin/sh
# The M31 core stack of 8/9 October 2026, every step in order. Restart from a step by its number in the list below,
# e.g. ./run_all.sh 13 starts at step9_deliver. Each step logs to $M31_WORK/logs/<step>.log
# (default work folder ~/.observatory/nights/2026-10-08-a6000/m31/work; pictures and recipe.json one folder up).
# Hooks are environment variables (M31_REF, M31_SOFT, M31_FINISH, M31_DECON_GAIN, ... see each step's docstring);
# with none set this reproduces the delivered run. The RAWs are read in place and never written.
# CLEAN=0 keeps the big intermediates (cached planes, stacks) after the run; by default they are deleted.
set -e
set -o pipefail 2>/dev/null || true
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M31_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/m31/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
run() {           # run <log name> <script> [args]
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && return 0
  echo "== $n $1"
  name=$1; shift
  $PY "$@" 2>&1 | tee "$WORK/logs/$name.log"
}
run step1_levels    step1_levels.py        # 1  exposure, ISO, corner levels, nucleus, per frame
run step2_hot       step2_hot.py           # 2  hot pixels and spikes; repaired planes cached
run step3_stars     step3_stars.py         # 3  stars in every frame
run step4_register  step4_register.py      # 4  rotation + shift per frame
run step5_quality   step5_quality.py       # 5  transparency, star size, trailing
run step6_vignette  step6_vignette.py      # 6  the flat from M76's sky (and M57's, for dust)
run step6b_dust     step6b_dustcheck.py    # 7  the dust against the M31 frames; the dust model
run step7_select    step7_select.py        # 8  which frames, what weights
run step8_stack_F   step8_stack.py F       # 9  the delivered stack
run step8_stack_L   step8_stack.py L       # 10 comparison: no dust model
run step8_stack_S   step8_stack.py S       # 11 comparison: the dropped green-shaped colour flats
run step8_stack_A   step8_stack.py A       # 12 comparison: no flat
run step9_deliver   step9_deliver.py       # 13 crop, zero, colour, TIFF, stretch, finish, JPEGs, numbers
run step9b_solve    step9b_solve.py        # 14 plate solution of the delivered stack
run step10_decon    step10_decon.py        # 15 the separate, labelled deconvolved version
run step11_recipe   step11_recipe.py       # 16 recipe.json
if [ "${CLEAN:-1}" = "1" ]; then run step12_clean step12_clean.py; fi   # 17 delete the big intermediates
