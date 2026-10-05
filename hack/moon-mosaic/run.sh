#!/bin/sh
# The whole mosaic, start to finish. The RAWs are only ever read.
#   ./run.sh <folder of the camera's JPG+ARW pairs> <output folder> [keep, default 0.1]
set -e
D=$1; OUT=$2; KEEP=${3:-0.1}
cd "$(dirname "$0")"
[ -d venv ] || { python3 -m venv venv && ./venv/bin/pip install -q numpy scipy opencv-python-headless rawpy tifffile; }
PY=./venv/bin/python
TAG=$(printf "keep%02.0f" "$(echo "$KEEP * 100" | bc)")
rm -rf crop.json ref.npz local

$PY grade.py "$D" grades.csv
# each frame's shutter and ISO, for the record (ImageMagick)
(cd "$D" && ls *.JPG | xargs -n 16 magick identify -ping -format "%f %[EXIF:ExposureTime] %[EXIF:PhotographicSensitivity]\n") | sort > exif.txt
$PY register.py "$D"
$PY stack.py "$D" ref
$PY stack.py "$D" local
$PY stack.py "$D" combine "$KEEP"            # the half-size stack: quick to look at, and its recipe
$PY stack2x.py "$D" "$KEEP"                  # the same choice of frames on the sensor's pixel grid
MOON_HALF=a $PY stack2x.py "$D" "$KEEP"      # two stacks from separate halves of the frames
MOON_HALF=b $PY stack2x.py "$D" "$KEEP"
$PY measure.py "stack-$TAG-2x.npz" measured-2x.json 2
$PY psf.py "stack-$TAG-2x.npz" 2 psf-2x.npz
$PY frc.py "stack-$TAG-2x-half-a.npz" "stack-$TAG-2x-half-b.npz" 0.3955 frc-2x.npz
$PY finish.py "stack-$TAG-2x.npz" measured-2x.json "$OUT" --stem moon-full-resolution
$PY wiener.py "stack-$TAG-2x.npz" measured-2x.json psf-2x.npz frc-2x.npz "$OUT" moon-full-resolution-restored
$PY record.py "$OUT" "$TAG"
