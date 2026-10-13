#!/bin/sh
# The NGC 2392 stack of 12/13 October 2026, every step in order. Restart from a step with: ./run_all.sh 6
# Each step logs to $N2392_WORK/logs/<step>.log (default ~/.observatory/nights/2026-10-12-a6000/ngc2392/work).
# Hooks are environment variables (see common.py and each step's docstring); with none set this reproduces the
# delivered picture. RAWs are read in place and never written; nothing is cached per frame (the disk was tight: the
# work folder peaks at about 0.5 GB and ends at a few MB). Step 6 reads the night's flat from <night>/flat/ (made by the
# NGC 891 stack) and writes nothing there. About two minutes.
#   PY            python with numpy, opencv, rawpy, tifffile (default ~/.observatory/pyenv/bin/python)
#   N2392_NIGHT   the night's folder; N2392_OUT (default $N2392_NIGHT/ngc2392); N2392_WORK; N2392_FINAL (default $N2392_NIGHT/final)
#   CLEAN=0       keeps the big intermediates (the stack arrays, the hot-pixel map). After a clean, restart from step 1:
#                 steps 2 and 5 to 8 need the hot-pixel map or the stack arrays, which the clean deletes.
# astrometry.net (image2xy, solve-field, wcs-rd2xy, wcs-xy2rd, wcsinfo) must be on the PATH, its config in ~/.observatory/astrometry.
set -e
cd "$(dirname "$0")"
PY=${PY:-$HOME/.observatory/pyenv/bin/python}
WORK=${N2392_WORK:-${N2392_OUT:-${N2392_NIGHT:-$HOME/.observatory/nights/2026-10-12-a6000}/ngc2392}/work}
mkdir -p "$WORK/logs"
FROM=${1:-1}
n=0
for s in step1_frames step2_stars step3_register step4_select step5_solve_ref step6_stack step7_measure step8_render step9_finish step10_recipe; do
  n=$((n + 1))
  [ "$n" -lt "$FROM" ] && continue
  echo "== $s"
  if [ "$s" = "step9_finish" ]; then sh step9_finish.sh > "$WORK/logs/$s.log" 2>&1 || { tail -5 "$WORK/logs/$s.log"; exit 1; }
  else $PY "$s.py" > "$WORK/logs/$s.log" 2>&1 || { echo "$s failed"; tail -8 "$WORK/logs/$s.log"; exit 1; }; fi
  tail -3 "$WORK/logs/$s.log" | cut -c1-300
done
if [ "${CLEAN:-1}" = "1" ]; then $PY step11_clean.py 2>&1 | tee "$WORK/logs/step11_clean.log"; fi
