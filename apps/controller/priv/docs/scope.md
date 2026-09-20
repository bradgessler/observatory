# Scope: the mount as a picture

The Scope page draws the telescope the way it is standing right now. It is not
a diagram of the geometry, that is the Orb. It is the thing itself: tripod,
pier, the head turning on the polar axis, the tube swinging on the Dec axis,
the counterweight opposite it.

Everything comes from the mount's own encoders, read four times a second. Turn
an axis anywhere, on the keypad, with the game pad, from a goto, and the
picture follows.

## What the colours mean

- **Blue** is the polar axis, the one the whole head turns on. On a German
  equatorial it points at the celestial pole when the mount is aligned.
- **Green** is the Dec axis, the one the tube swings on.
- **Bright** is the tube. The small circle at one end is the aperture, the end
  you look through the other way.
- **Dim** is structure: the tripod, the pier, the ground.
- A **dashed arc** around an axis means that axis is turning right now.
- A **green lamp** at the base means the mount is tracking, either at its own
  sidereal rate or through the fitted model.

## Where the polar axis comes from

Before a star alignment the drawing assumes the mount stands as you said it
does under Setup: the latitude knob at your latitude, the tripod pointed north.
After three stars agree, the drawing uses the axis the stars actually measured,
so a crooked set-up looks crooked.

## Equatorial and alt-az

Two forms are drawn. A German equatorial has the polar axis and the
counterweight. An alt-az mount, a fork or a single arm, turns about the
vertical and the tube swings up and down. The page picks the form from what
the driver says the mount is.

## What it is for

Three things. Seeing at a glance that the mount is where you think it is,
without walking outside. Watching a slew happen when the scope is in another
building. And having something to look at when nothing is plugged in at all:
the simulator drives the same drawing.
