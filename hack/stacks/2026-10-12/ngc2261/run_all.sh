#!/bin/sh
# The NGC 2261 (Hubble's Variable Nebula) stack of 12/13 October 2026, every step in order. Restart from a step with: ./run_all.sh 4
# Each step logs to $N2261_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-12-a6000/ngc2261/work).
# Hooks are environment variables (see common.py and each step's docstring); with none set this reproduces the
# delivered run. RAWs are read in place and never written; nothing is cached per frame (the disk was tight).
# Step 7 reads the night's flat from <night>/flat/ (made by the NGC 891 stack) and writes nothing there.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${N2261_WORK:-$HOME/.observatory/nights/2026-10-12-a6000/ngc2261/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_solve_ref step7_flat step8_stack step9_solve step10_deliver step11_measure step12_finish step13_recipe; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $s"
  if [ "$s" = "step12_finish" ]; then sh step12_finish.sh 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
# big intermediates go once the deliverables exist (CLEAN=0 keeps them)
if [ "$TO" -ge 13 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step14_clean.py 2>&1 | tee "$WORK/logs/step14_clean.log"; fi
