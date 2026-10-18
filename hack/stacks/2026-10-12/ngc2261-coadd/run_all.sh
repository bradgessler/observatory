#!/bin/sh
# The proper-coadd trial on NGC 2261 (Hubble's Variable Nebula), 12/13 October 2026: the delivered NGC 2261 pipeline
# (hack/stacks/2026-10-12/ngc2261) with ONLY the combine step replaced. step8_coadd.py combines with Zackay & Ofek's
# proper coaddition (.claude/skills/stack-pictures/tools/coadd.py) and, on the same cube in the same pass, with the
# delivered sigma-clipped weighted mean (the control). Steps 9 to 13 finish and measure the coadd exactly as the delivered
# picture was; step15_compare.py measures the two against each other and against the published stack.
# Restart from a step with: ./run_all.sh 8   (and stop after one with ./run_all.sh 8 8)
# Logs go to $N2261_WORK/logs (default ~/.observatory/nights/2026-10-12-a6000/ngc2261-coadd/work). Nothing is written
# in <night>/ngc2261/, <night>/flat/ or <night>/final/: the finished picture goes to <night>/final-trial/ngc2261-coadd.*
# Hooks: N2261_COADD_DELIVER=proper|mean-psf|control (step 8); N2261_T_MIN=0.4 N2261_DROP_FIRST=0 N2261_NAME=ngc2261-coadd-all
#        (every frame of the run, the thin-cloud ones too; a second trial beside the first).
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
NAME=${N2261_NAME:-ngc2261-coadd}
WORK=${N2261_WORK:-$HOME/.observatory/nights/2026-10-12-a6000/$NAME/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_solve_ref step7_flat step8_coadd step9_solve step10_deliver step11_measure step12_finish step13_recipe step15_compare; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $s"
  if [ "$s" = "step12_finish" ]; then sh step12_finish.sh 2>&1 | tee "$WORK/logs/$s.log"; else $PY "$s.py" 2>&1 | tee "$WORK/logs/$s.log"; fi
done
# big intermediates go once the deliverables exist (CLEAN=0 keeps them)
if [ "$TO" -ge 14 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step14_clean.py 2>&1 | tee "$WORK/logs/step14_clean.log"; fi
