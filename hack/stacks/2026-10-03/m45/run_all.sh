#!/bin/sh
# The whole M45 mosaic pipeline, in order. Usage: sh run_all.sh [from_step]   (steps: 1 2 2b 2c 3 4 5 6 7 8 9 10 10b 11 12 12b 12c 12d 13 14)
# Reads the RAWs in place; writes only to the work folder until step 12, which writes the deliverables. About 5 minutes.
#   PY                python with numpy, scipy, opencv, rawpy, tifffile, pillow
#   M45_WORK          work folder, about 5 GB (default: ../work beside this scripts folder)
#   M45_OUT           where the deliverables go (default: ~/.observatory/nights/2026-10-03-a6000/m45)
# WITH REAL FLAT FRAMES (the rerun of 2026-10-04):
#   M45_MASTER_FLAT   a master flat, .npy float32 (4, 2012, 3012), planes R, G1, G2, B, each 1 at the sensor centre.
#                     Step 2c checks it against this hour and writes what step 6 divides by; steps 12d and 14 compare
#                     with ../before-flats and add the rerun's notes to the recipe.
#   M45_BEFORE_WORK   optional: a work folder of steps 1 to 6 run WITHOUT the master flat (for step 12d's dust numbers)
# Without M45_MASTER_FLAT everything runs as in the first run; steps 2c, 12d and 14 are skipped.
cd "$(dirname "$0")"
PY=${PY:-../../mosaic2/venv/bin/python}
L=${M45_WORK:-../work}; mkdir -p "$L"
FROM=${1:-1}
run() { step=$1; shift; case " $ORDER " in *" $step "*) echo "== step $step: $*"; "$PY" "$@" > "$L/log_p$step.txt" 2>&1 || { echo "step $step failed"; tail -5 "$L/log_p$step.txt"; exit 1; };; esac; }
ALL="1 2 2b 2c 3 4 5 6 7 8 9 10 10b 11 12 12b 12c 12d 13 14"
ORDER=""; on=0
for s in $ALL; do [ "$s" = "$FROM" ] && on=1; [ $on = 1 ] && ORDER="$ORDER $s"; done
run 1 p1_frames.py
run 2 p2_hot.py
run 2b p2b_hair.py
[ -n "$M45_MASTER_FLAT" ] && run 2c p2c_masterflat_check.py
run 3 p3_stars.py
run 4 p4_register.py
run 5 p5_select.py
run 6 p6_stack.py
run 7 p7_solve.py
run 8 p8_place.py
run 9 p9_resample.py
run 10 p10_background.py
run 10b p10b_dark_check.py
run 11 p11_combine.py
run 12 p12_deliver.py
run 12b p12b_glare.py
run 12c p12c_seen_twice.py
[ -n "$M45_MASTER_FLAT" ] && run 12d p12d_before_after.py
run 13 p13_recipe.py
[ -n "$M45_MASTER_FLAT" ] && run 14 p14_rerun_notes.py
exit 0
