#!/bin/sh
# The last-quarter Moon of 2026-10-04 as one picture, start to finish. The RAWs are only ever read.
#   PY=<python with numpy scipy opencv rawpy tifffile> ./run.sh <stills folder> <flats-log.json> <output folder>
#
# This is hack/moon-mosaic (written two nights earlier for a nearly full Moon that almost fitted one
# frame) changed for a real mosaic: four panels in two passes, ISO 100, morning twilight, the
# southern panels through thin cloud, dust and a hair on the sensor. What changed is listed in
# recipe.json ("changed_from_hack_moon_mosaic") and at the top of each script.
set -e
D=$1; LOG=$2; OUT=$3; KEEP=0.3; TAG=keep30; ARC=0.3881
cd "$(dirname "$0")"
PY=${PY:-python3}
# a patch is the average of the sharpest KEEP of the clear frames over it, at least 8; "clear" is within
# 1.5x of the clearest frame's gain there, or the 10 clearest. The half-stacks get half of each.
FULL="MOON_MINK=8 MOON_ATLEAST=10"; HALF="MOON_MINK=4 MOON_ATLEAST=5"
rm -rf features local glow crop.json crop-sensor.json ref.npz photo.json sky.json transforms.json transforms-sensor.json stack-*.npz
mkdir -p "$OUT"

$PY frames.py "$D" 130500 134730             # the session's frames, by what they were taken for
$PY flat.py "$D" "$LOG" flat.npz             # the master flat (and flat.json: which frames, what it looks like)
$PY grade.py "$D" grades.csv
$PY sky.py "$D" > sky.log                    # each frame's own sky level
$PY register.py "$D"
$PY stack.py "$D" photo > photo-with-glow.log
$PY glow.py "$D" > glow.log                  # the cloud's glow, per frame
$PY stack.py "$D" photo > photo.log          # transparency again, the glow gone
# two checks on the calibration, against clear frames of the same ground
$PY flatcheck.py "$D" flatcheck.json flat.npz 20261004-131807-DSC01918.JPG 20261004-131514-DSC01912.JPG 20261004-131514-DSC01912.JPG 20261004-133242-DSC01949.JPG 20261004-131714-DSC01915.JPG 20261004-131548-DSC01914.JPG
$PY glowcheck.py "$D" glowcheck.json 20261004-131807-DSC01918.JPG 20261004-133242-DSC01949.JPG 20261004-133351-DSC01953.JPG 20261004-133426-DSC01955.JPG 20261004-133443-DSC01956.JPG \
    20261004-132952-DSC01943.JPG 20261004-133059-DSC01947.JPG 20261004-132825-DSC01942.JPG 20261004-134420-DSC01978.JPG 20261004-134436-DSC01979.JPG 20261004-134453-DSC01980.JPG 20261004-134716-DSC01988.JPG

# a first stack the sensor's way up, to find lunar north on
$PY stack.py "$D" ref
$PY stack.py "$D" local
env $FULL $PY stack.py "$D" combine "$KEEP"
$PY measure.py "stack-$TAG.npz" measured-half-sensor.json 1 > /dev/null
$PY orient.py "stack-$TAG.npz" measured-half-sensor.json crop.json orient.json
mv crop.json crop-sensor.json
$PY turn.py orient.json
rm -rf local ref.npz "stack-$TAG.npz"

# the stack, north up
$PY stack.py "$D" ref
$PY stack.py "$D" local
env $FULL $PY stack.py "$D" combine "$KEEP"            # the half-size stack: quick to look at, and its recipe
env $FULL $PY stack2x.py "$D" "$KEEP"                  # the same choice of frames on the sensor's pixel grid
env $HALF MOON_HALF=a $PY stack2x.py "$D" "$KEEP"      # two stacks from separate halves of the frames
env $HALF MOON_HALF=b $PY stack2x.py "$D" "$KEEP"
$PY measure.py "stack-$TAG-2x.npz" measured-2x.json 2 > /dev/null
$PY psf.py "stack-$TAG-2x.npz" 2 psf-2x.npz
$PY frc.py "stack-$TAG-2x-half-a.npz" "stack-$TAG-2x-half-b.npz" $ARC frc-2x.npz
$PY zones.py "stack-$TAG-2x.npz" "stack-$TAG-2x-half-a.npz" "stack-$TAG-2x-half-b.npz" measured-2x.json $ARC psf-2x.npz   # blur and noise, zone by zone
$PY coverage.py "stack-$TAG-2x.npz" measured-2x.json "stack-$TAG.npz" coverage.json > /dev/null
$PY finish.py "stack-$TAG-2x.npz" measured-2x.json "$OUT" --stem moon-last-quarter
$PY wiener.py "stack-$TAG-2x.npz" measured-2x.json zones.json "$OUT" moon-last-quarter-restored
$PY crops.py "$OUT"
$PY record.py "$D" "$OUT" "$TAG"
