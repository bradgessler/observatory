#!/bin/sh
# The M33 stack of 8/9 October 2026, every step in order. Restart from a step with: ./run_all.sh 4
# Each step logs to $M33_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-08-a6000/m33/work).
# Hooks are environment variables (see common.py and each step's docstring); with none set this reproduces the
# delivered run. RAWs are read in place and never written.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M33_WORK:-$HOME/.observatory/nights/2026-10-08-a6000/m33/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_vignette step7_stack step8_solve step9_deliver step9b_checks step10_decon step11_recipe; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  echo "== $s"
  $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"
done
# big intermediates go once the deliverables exist (CLEAN=0 keeps them)
if [ "${CLEAN:-1}" = "1" ]; then $PY step12_clean.py 2>&1 | tee "$WORK/logs/step12_clean.log"; fi
