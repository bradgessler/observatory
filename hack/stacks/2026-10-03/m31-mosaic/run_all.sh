#!/bin/sh
# The whole mosaic pipeline, in order. Usage: sh run_all.sh [from_step]   (steps: 1 2 3 4 5 5b 5c 6 6c 7 8 9 10 10b 11 12 12b 13 14)
# About 3 minutes. Reads the RAWs in place; writes only to the work folder until steps 12 and 13,
# which write the deliverables and the recipe into ~/.observatory/nights/2026-10-03-a6000/m31/mosaic/.
#   PY                python with numpy, scipy, opencv, rawpy, tifffile, pillow (default: the venv it was made with)
#   M31M_WORK         work folder, needs about 13 GB (default: ../work beside this scripts folder)
#   M31_CORE_WORK     the core run's work files (default: see mcommon.py; copies are in ../calibration-from-core-run)
#   UNTIL             optional: last step to run
# WITH REAL FLAT FRAMES (the rerun of 2026-10-04):
#   M31M_MASTER_FLAT  a master flat, .npy float32 (4, 2012, 3012), planes R, G1, G2, B, each 1 at the sensor centre.
#                     Step 5c then checks it against this hour and writes, into the work folder, the flat that step 6
#                     divides by (flat_master_hour.npy: the master flat, and this hour's own response inside the few
#                     patches where the two differ), those patches (leaveout_master.npy) and the dawn hair's zone
#                     (nodata_master.npy); steps 6 on are given them. Steps 12b and 14 compare with ../before-flats.
#   M31_CORE_TIF      a re-made core stack on the same grid as m31-core-cloudflat-linear.tif (made with that same flat)
#   M31M_BEFORE_WORK  optional: a work folder in which step 6 was run WITHOUT the master flat, for step 6c's comparison
# Without M31M_MASTER_FLAT everything runs as in the first run (cloud-glow flat and dust maps), steps 5c, 6c, 12b, 14 are skipped.
# astrometry.net (solve-field, image2xy) must be on the PATH, with ~/.observatory/astrometry/astrometry.cfg.
cd "$(dirname "$0")"
PY=${PY:-../../mosaic2/venv/bin/python}
L=${M31M_WORK:-../work}; mkdir -p "$L"; L=$(cd "$L" && pwd)
FROM=${1:-1}
run() { step=$1; shift; case " $ORDER " in *" $step "*) echo "== step $step: $*"; "$PY" "$@" > "$L/log_$step.txt" 2>&1 || { echo "step $step failed"; tail -5 "$L/log_$step.txt"; exit 1; };; esac; }
ALL="1 2 3 4 5 5b 5c 6 6c 7 8 9 10 10b 11 12 12b 13 14"; [ -n "$UNTIL" ] && ALL=$(echo "$ALL" | sed "s/ $UNTIL .*/ $UNTIL/")
ORDER=""; on=0
for s in $ALL; do [ "$s" = "$FROM" ] && on=1; [ $on = 1 ] && ORDER="$ORDER $s"; done
run 1 m1_frames.py
run 2 m2_hot.py
run 3 m3_stars.py
run 4 m4_register.py
run 5 m5_quality_select.py
run 5b m5b_dustcheck.py
if [ -n "$M31M_MASTER_FLAT" ]; then
  export M31M_MASTER_FLAT_PLAIN="$M31M_MASTER_FLAT"
  run 5c m5c_masterflat_check.py
  export M31M_MASTER_FLAT="$L/flat_master_hour.npy" M31M_DUST_MASK="$L/leaveout_master.npy" M31M_NODATA_MASK="$L/nodata_master.npy"
  [ -n "$M31_CORE_TIF" ] && export M31_CORE_FLAT="${M31_CORE_FLAT:-$M31M_MASTER_FLAT_PLAIN}"
fi
run 6 m6_stack.py
[ -n "$M31M_MASTER_FLAT" ] && [ -n "$M31M_BEFORE_WORK" ] && run 6c m6c_before_after.py
run 7 m7_solve.py
run 8 m8_place.py
run 9 m9_resample.py
run 10 m10_background.py
run 10b m10b_centre_check.py
run 11 m11_combine.py six centre
run 12 m12_deliver.py
[ -n "$M31M_MASTER_FLAT" ] && run 12b m12b_before_after.py
run 13 m13_recipe.py
[ -n "$M31M_MASTER_FLAT" ] && run 14 m14_rerun_notes.py
exit 0
