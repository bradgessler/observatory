#!/bin/sh
# Messier 33, the Triangulum Galaxy: the night of 17/18 October 2026 (frames of 18 October UTC, turns 1a, 1b and 2) with
# the frames of 13 October, every step in order. Restart from a step with ./run_all.sh 8 ; run only steps 8 to 10 with
# ./run_all.sh 8 10. Template: hack/stacks/2026-10-17/m27 (and hack/stacks/2026-10-12/m33 for the object bigger than the
# frame). Logs go to ./logs/<step>.log; big intermediates to $M33_WORK (default
# ~/.observatory/nights/2026-10-17-a6000/m33/work), deleted at the end (CLEAN=0 keeps them). The finished picture and
# recipe.json go to ./final/, the share set to ./share/. Hooks are environment variables (common.py and each step's
# docstring); with none set this reproduces the delivered run. RAWs are read in place and never written; nothing is
# cached per frame. Order: the reference frame is plate-solved (step6) before registration, which uses it.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M33_WORK:-$HOME/.observatory/nights/2026-10-17-a6000/m33/work}
mkdir -p "$WORK" logs final
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step6_solve_ref step3_register step4_quality step5_select step7a_flatcheck step7_dust step8_stack step9_deliver step10_finish step11_halves step13_recipe step12_annotate; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $n $s"
  if [ -f "$s.sh" ]; then sh "$s.sh" 2>&1 | tee "logs/$s.log"; else $PY "$s.py" 2>&1 | tee "logs/$s.log"; fi
done
if [ "$TO" -ge 14 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step15_clean.py 2>&1 | tee logs/step15_clean.log; fi
