# Optical axes

Find the mount's axes in the camera picture by moving them.

## Why it exists

A camera that knows where the axes are in its picture can draw them over
the live view, notice when the mount moves without being told to, and — with
more cameras in a lab — measure how a mount really behaves so its driver can
be written from data. This page is the first, deliberately simple step.

## What it does

1. Takes a still.
2. Turns the RA axis 3°, takes another still, turns back.
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
  Dec), drawn 4× long.
* **Cross**: the best-fit pivot, shown only when the motion looks like a spin.
* **spin / slide**: how much the arrows fan out around a point (spin, 1 = all
  of them) versus all point the same way (slide, 1 = parallel). An axis that
  points roughly at the camera spins; one that lies across the view slides,
  and its pivot is off-frame or not a point at all.

## What one camera can and cannot say

When the motion is a slide, every arrow points the same way, and the axis
must run at right angles to them, through the moving body — that is the
dashed line. Where along the line of sight the axis sits is invisible to a
single camera; a second camera at roughly a right angle turns two such
lines into an axis in space. Arrows that disagree with the crowd by more
than 60° (a shelf matching itself one block over) are ignored and counted.

## The sweep

*Sweep* takes five stills per axis across ±6° (or ±20° for the wide sweep),
follows spots frame to frame and fits the axis in space: every spot rides a
circle around the axis, and with the turn angle known at each frame the
arcs' curvature says where the axis is in depth as well as in the picture.
A small sweep's arcs are nearly straight, so "toward" and "away" fit
equally well — the page says so rather than picking one. The two axes are
then fitted **together, perpendicular by construction**, which removes the
weakness a lone axis has when it points near the camera.

**Camera's reading of each step**: with the axis and the spots' circles
known, each frame gives the one turn angle that best explains every spot.
Commanded 10°, camera saw 9.75° — that is the hardware doing what it was
told, measured from outside the encoders. The *stray* (how far those
readings scatter from the commands) is the practical margin; it includes
tracking noise and lens distortion, which the fit's own ± does not know
about.

## Honest limits

* This is a 2-D reading of a 3-D motion. It says where the axis *appears*
  to pivot in this camera's picture; the axis in space needs the camera's
  pose, which is the next step.
* It needs texture: a plain white tube against a plain wall gives few
  arrows. Tape, labels and the counterweight bar all help.
* Anything else moving during the scan — a person walking past — adds
  arrows that don't belong. Run it when the scene is still.
* The camera is assumed to be an ideal pinhole with the field of view on
  the Camera page. Real lenses distort toward the edges; that shows up as
  step readings straying by a degree or two. A checkerboard calibration is
  the cure, later.
* Depth is in units of the distance to the axis: one camera never knows
  how big the mount is, only its shape.
