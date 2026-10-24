#!/bin/sh
# Saturn and its moons, night of 17/18 October 2026 (frames of 18 October UTC, 05:22 to 07:23), every step in order.
# Restart from a step with ./run_all.sh 5 ; run only steps 5 to 9 with ./run_all.sh 5 9.
# Template: hack/stacks/2026-10-03/saturn (saturn2.py, finish2.py, rlmodel.py, moons2.py, composite3.py), made one pipeline.
# Logs go to ./logs/<step>.log; small intermediates to $SAT_WORK (default ~/.observatory/nights/2026-10-17-a6000/saturn/work,
# under 200 MB), deleted at the end (CLEAN=0 keeps them). The pictures go to ./final/ and ./share/, the recipe to final/recipe.json.
# Hooks are environment variables (SAT_*, see each step's docstring); with none set this reproduces the delivered run bit for bit.
# RAWs (~/.observatory/stills/2026-10-18/) are read in place and never written; nothing is cached per frame.
# The JPL Horizons answers are kept in ./horizons/ (SAT_HORIZONS_REFRESH=1 asks again); Gaia in ~/.observatory/catalogs/.
# step14_metadata.py (after the recipe): the planet stack as FITS (~/.observatory/nights/.../saturn/), the recipe in the
# schema observatory.recipe/1 (.claude/skills/stack-pictures/tools/obsmeta.py, stack_fits.py, upgrade_recipe.py).
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
mkdir -p logs final share checks
FROM=${1:-1}
TO=${2:-99}
n=0
for s in step1_frames step2_grade step3_ephemeris step4_select step5_stack step6_moons step7_titan step8_restore step9_compose step10_finish step11_annotate step12_recipe step14_metadata; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  [ "$n" -gt "$TO" ] && continue
  echo "== $n $s"
  if [ -f "$s.sh" ]; then sh "$s.sh" 2>&1 | tee "logs/$s.log"; else $PY "$s.py" 2>&1 | tee "logs/$s.log"; fi
done
if [ "$TO" -ge 13 ] && [ "${CLEAN:-1}" = "1" ]; then $PY step13_clean.py 2>&1 | tee logs/step13_clean.log; fi
