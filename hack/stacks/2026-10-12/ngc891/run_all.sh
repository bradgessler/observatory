#!/bin/sh
# The NGC 891 stack of 12/13 October 2026, every step in order. Restart from a step with: ./run_all.sh 4
# Each step logs to $N891_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-12-a6000/ngc891/work).
# Hooks are environment variables (see common.py and each step's docstring); with none set this reproduces the
# delivered run. RAWs are read in place and never written; nothing is cached per frame (the disk was tight).
# Step 7 also writes the night's flat to <night>/flat/ for the other targets.
set -e
set -o pipefail 2>/dev/null || true
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${N891_WORK:-$HOME/.observatory/nights/2026-10-12-a6000/ngc891/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_solve_ref step7_flat step8_stack step9_solve step10_deliver step11_finish step12_recipe; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  echo "== $s"
  if [ "$s" = "step11_finish" ]; then sh step11_finish.sh 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
# big intermediates go once the deliverables exist (CLEAN=0 keeps them)
if [ "${CLEAN:-1}" = "1" ]; then $PY step13_clean.py 2>&1 | tee "$WORK/logs/step13_clean.log"; fi
