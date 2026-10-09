# Orb

The mount's geometry as a small 3-D sphere: the polar axis, the Dec axis and
the tube, drawn where they really are and turning as the motors turn.

## Why it exists

A German equatorial mount is confusing the first ten times: "east" turns the
RA axis, "up" is toward the pole, and the same spot in the sky can be
reached two ways. The keypad hides all that behind arrows; the orb shows it.
Watch the strips move the axes on the sphere and the mount stops being a
mystery.

## What it draws

* The **celestial sphere** from your standing spot (pick *from S/E/N/W* to
  match where you are in the yard).
* The **RA axis** (blue), the polar axis, tilted by the latitude knob and
  turned by the heading you set on Setup, or placed by the alignment once you
  have one.
* The **Dec axis** (green) and the **tube** (red) at the current encoder angles. The red crosshair is where the tube points on the sky; at the home position it sits on the pole mark, because there the tube lies along the polar axis.
* Arrowheads chase around an axis while it is running.

## Notes

* The two strips under the sphere are honest: each drives one axis.
* Once there is an alignment, the orb draws the measured mount, not the ideal one.
* Before home is set it says *home not set · assuming upright*.
* Planned: uncertainty caps that shrink as stars are added, and drag to look
  around (#49).
