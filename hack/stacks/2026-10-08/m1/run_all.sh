#!/bin/sh
# M1 (Crab Nebula) from the night of 8/9 October 2026, every step in order. Restart from a step with
# ./run_all.sh 7. Each step logs to $M1_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-08-a6000/m1/work).
# Hooks are environment variables (see common.py and the step docstrings); with none set this reproduces the delivered
# run. RAWs are read in place and never written. CLEAN=0 keeps the big intermediates.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M1_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/m1/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
for s in step1_hot step2_stars step3_register step4_solve_ref step5_quality step6_select step7_stack step8_solve step9_measure step10_render step11_finish step12_deliver; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  echo "== $s"
  if [ -f "$s.sh" ]; then sh "$s.sh" 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
if [ "${CLEAN:-1}" = "1" ]; then $PY step13_clean.py 2>&1 | tee "$WORK/logs/step13_clean.log"; fi
