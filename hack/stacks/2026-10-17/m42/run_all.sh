#!/bin/sh
# Messier 42, the Orion Nebula (with M43): the night of 17/18 October 2026 (frames of 18 October UTC), every step in
# order. 30 s ISO 1600 frames for the nebula, 2 s ISO 400 frames for the bright core, joined where any long frame came
# within 7 percent of the sensor's ceiling. Restart from a step with ./run_all.sh 8 ; run only steps 8 to 10 with
# ./run_all.sh 8 10. Templates: hack/stacks/2026-10-17/m33 (calibration, dithered frames on a canvas),
# hack/stacks/2026-10-17/m27 (proper coaddition with the old mean as a control), hack/stacks/2026-10-03/m42 (the join).
# Logs go to ./logs/<step>.log; big intermediates to $M42_WORK (default ~/.observatory/nights/2026-10-17-a6000/m42/work),
# deleted at the end (CLEAN=0 keeps them). The finished picture and recipe.json go to ./final/, the share set to
# ./share/. Hooks are environment variables (common.py and each step's docstring); with none set this reproduces the
# delivered run. RAWs are read in place and never written; nothing is cached per frame. Order: the reference frame is
# plate-solved (step6) before registration, which uses it.
# step16_metadata.py (after the recipe): the linear stack as FITS beside the TIF (~/.observatory/nights/...), the recipe in the
# schema observatory.recipe/1 (.claude/skills/stack-pictures/tools/obsmeta.py, stack_fits.py, upgrade_recipe.py).
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M42_WORK:-$HOME/.observatory/nights/2026-10-17-a6000/m42/work}
mkdir -p "$WORK" logs final
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step6_solve_ref step3_register step4_quality step5_select step7a_flatcheck step7_dust step8_coadd step8b_join step9_deliver step10_finish step11_halves step13_recipe step16_metadata step12_annotate; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $n $s"
  if [ -f "$s.sh" ]; then sh "$s.sh" 2>&1 | tee "logs/$s.log"; else $PY "$s.py" 2>&1 | tee "logs/$s.log"; fi
done
if [ "$TO" -ge 16 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step15_clean.py 2>&1 | tee logs/step15_clean.log; fi
