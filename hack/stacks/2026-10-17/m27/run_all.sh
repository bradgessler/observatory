#!/bin/sh
# Messier 27, the Dumbbell Nebula, night of 17/18 October 2026 (frames of 18 October UTC, 03:46 to 04:22), every step
# in order. Restart from a step with ./run_all.sh 8 ; run only steps 8 to 10 with ./run_all.sh 8 10.
# Template: hack/stacks/2026-10-12/m77-calibrated (calibrated flat, Gaia star colours, darks.subtract) with the combine of
# hack/stacks/2026-10-12/ngc891-coadd (proper coaddition, keep_phase='mean'; the old combine made beside it as a control).
# Logs go to ./logs/<step>.log; big intermediates to $M27_WORK (default ~/.observatory/nights/2026-10-17-a6000/m27/work),
# deleted at the end (CLEAN=0 keeps them). The finished pictures and recipe.json go to ./final/.
# Hooks are environment variables (common.py and each step's docstring); with none set this reproduces the delivered run.
# RAWs (~/.observatory/stills/2026-10-18/) are read in place and never written; nothing is cached per frame.
# step16_metadata.py (after the recipe): the linear stack as FITS beside the TIF (~/.observatory/nights/...), the recipe in the
# schema observatory.recipe/1 (.claude/skills/stack-pictures/tools/obsmeta.py, stack_fits.py, upgrade_recipe.py).
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${M27_WORK:-$HOME/.observatory/nights/2026-10-17-a6000/m27/work}
mkdir -p "$WORK" logs final
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_hot step2_stars step3_register step4_quality step5_select step6_solve_ref step7a_flats step7_flat step8_coadd step9_solve step9b_colour step10_deliver step11_finish step12_halves step13_recipe step16_metadata step14_annotate; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $n $s"
  if [ -f "$s.sh" ]; then sh "$s.sh" 2>&1 | tee "logs/$s.log"; else $PY "$s.py" 2>&1 | tee "logs/$s.log"; fi
done
if [ "$TO" -ge 17 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step15_clean.py 2>&1 | tee logs/step15_clean.log; fi
