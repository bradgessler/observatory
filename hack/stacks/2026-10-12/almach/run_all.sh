#!/bin/sh
# The Almach picture of 12/13 October 2026, every step in order. Restart from a step with: ./run_all.sh 4
# Each step logs to $ALMACH_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-12-a6000/almach/work).
# Hooks are environment variables (see common.py and each step's docstring); with none set this reproduces the delivered run.
# RAWs are read in place and never written. Needs ~200 MB of work space until step 10 clears it (CLEAN=0 keeps it).
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${ALMACH_WORK:-$HOME/.observatory/nights/2026-10-12-a6000/almach/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
for s in step1_frames step2_prepare step3_register step4_stack step5_solve step6_pair step7_render step8_deliver step8b_finish step9_recipe; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  echo "== $s"
  if [ "$s" = "step8b_finish" ]; then sh step8b_finish.sh 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
if [ "${CLEAN:-1}" = "1" ]; then $PY step10_clean.py 2>&1 | tee "$WORK/logs/step10_clean.log"; fi
