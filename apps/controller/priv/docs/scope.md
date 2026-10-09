# Scope: the mount as a picture

The Scope page draws the telescope the way it is standing right now. It is not
a diagram of the geometry, that is the Orb. It is the thing itself: tripod,
pier, the head turning on the RA axis (the polar axis), the tube swinging on
the Dec axis, the counterweight opposite it.

Everything comes from the mount's own encoders, read four times a second. Turn
an axis anywhere, on the keypad, with the game controller, from a Go To, and
the picture follows.

## What the shapes mean

Each part is told apart by its shape first, so the drawing reads the same in
night mode, where every line is red.

- The **housing that leans up from the pier** is the RA axis (blue), the
  one the whole head turns on; pointed at the pole, it is the polar axis. On a German equatorial it points at the
  celestial pole when the mount is aligned.
- The **thin bar across its top** is the Dec axis (green), the one the tube
  swings on: the counterweight is the disc on one end, the tube on the other.
- The **thickest line** is the tube (bright). The small circle at one end is
  the aperture, the end you look through the other way.
- **Dim** lines are structure: the tripod, the pier, the ground.
- A **dashed arc** around an axis means that axis is turning right now.
- A **lamp** at the base, lit, means the mount is tracking, either sidereal
  tracking (the RA motor alone) or tracking through the alignment.

## Where the polar axis comes from

Before an alignment the drawing assumes the mount stands as you said it does
under *Mount As It Stands* on [Setup](/docs/setup#mount-as-it-stands): the
latitude knob at your latitude, the tripod pointed north. After three stars
agree, the drawing uses the axis the stars actually measured, so a crooked
set-up looks crooked.

## Equatorial and alt-az

Two forms are drawn. A German equatorial has the polar axis and the
counterweight. An alt-az mount, a fork or a single arm, turns about the
vertical and the tube swings up and down. The page picks the form from what
the driver says the mount is.

## What it is for

Three things. Seeing at a glance that the mount is where you think it is,
without walking outside. Watching a slew happen when the telescope is in another
building. And having something to look at when nothing is plugged in at all:
the [simulator](/docs/glossary#simulator) drives the same drawing.
