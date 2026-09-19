# Optical axes

Find the mount's axes in the camera picture by moving them.

## Why it exists

A camera that knows where the axes are in its picture can draw them over
the live view, notice when the mount moves without being told to, and — with
more cameras in a lab — measure how a mount really behaves so its driver can
be written from data. This page is the first, deliberately simple step.

## What it does

1. Takes a still.
2. Turns the RA axis 1.5°, takes another still, turns back.
3. Does the same for Dec.
4. For each axis, cuts the two stills into small blocks and finds where each
   block went (block matching, plain arithmetic, no learned model). Blocks
   that didn't move — the shelves, the wall — drop out. What remains is the
   moving part: the tube, the counterweight.
5. Fits a rotation centre to those arrows: for a spin in the picture every
   arrow is at right angles to the line from the centre, which is a small
   least-squares problem.

## Reading the result

* **Arrows**: where the picture moved when that axis turned (blue RA, green
  Dec), drawn 3× long.
* **Cross**: the best-fit pivot, shown only when the motion looks like a spin.
* **spin / slide**: how much the arrows fan out around a point (spin, 1 = all
  of them) versus all point the same way (slide, 1 = parallel). An axis that
  points roughly at the camera spins; one that lies across the view slides,
  and its pivot is off-frame or not a point at all.

## Honest limits

* This is a 2-D reading of a 3-D motion. It says where the axis *appears*
  to pivot in this camera's picture; the axis in space needs the camera's
  pose, which is the next step.
* It needs texture: a plain white tube against a plain wall gives few
  arrows. Tape, labels and the counterweight bar all help.
* Anything else moving during the scan — a person walking past — adds
  arrows that don't belong. Run it when the scene is still.
