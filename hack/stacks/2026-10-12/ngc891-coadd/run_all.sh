#!/bin/sh
# The proper-coadd trial on NGC 891, 12/13 October 2026: the delivered NGC 891 pipeline (hack/stacks/2026-10-12/ngc891)
# with ONLY the combine step replaced. step8_coadd.py combines with Zackay & Ofek's proper coaddition
# (.claude/skills/stack-pictures/tools/coadd.py) and, on the same cube in the same pass, with the delivered sigma-clipped
# weighted mean (the control). Steps 9 to 12 finish the coadd exactly as the delivered picture was finished;
# step14_compare.py measures the two against each other and against the published stack.
# Restart from a step with: ./run_all.sh 8   (and stop after one with ./run_all.sh 8 8)
# Logs go to $N891_WORK/logs (default ~/.observatory/nights/2026-10-12-a6000/ngc891-coadd/work). Nothing is written in
# <night>/ngc891/, <night>/flat/ or <night>/final/: the finished picture goes to <night>/final-trial/ngc891-coadd.*
# Hooks: N891_COADD_DELIVER=proper|mean-psf|control (step 8: which result steps 9-12 finish; default proper).
set -e
set -o pipefail 2>/dev/null || true
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${N891_WORK:-$HOME/.observatory/nights/2026-10-12-a6000/ngc891-coadd/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_solve_ref step7_flat step8_coadd step9_solve step10_deliver step11_finish step12_recipe step14_compare; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $s"
  if [ "$s" = "step11_finish" ]; then sh step11_finish.sh 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
# big intermediates go once the deliverables exist (CLEAN=0 keeps them)
if [ "$TO" -ge 13 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step13_clean.py 2>&1 | tee "$WORK/logs/step13_clean.log"; fi
