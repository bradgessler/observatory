# Keypad

The hand controller, on a phone or a computer: the **Axis Strips** page (one
strip per axis) and the **Plain Keypad** (four arrows), both under Controls.

## Moving the mount

Press and hold an arrow. The mount moves while you hold and stops when you let
go, or within a second if the connection drops: every held key is a
[dead man's switch](/docs/glossary#dead-mans-switch).

The picture at the top is your mount as it stands: the **RA axis** (the polar
axis) tilted up toward the pole by your latitude, and the **Dec axis** square
to it. Below
it, **one strip per axis**. Touch a strip and pull: a small pull creeps, a long
pull crosses the sky (1× to 800×, shown while you hold), let go and it stops.
The axis you're turning lights up in the picture.

- **RA axis**: turns the whole tube around the tilted axis, following the
  sky's rotation. Pull toward **E** or **W**.
- **Dec axis**: swings the tube **toward** or **away from** the pole.

If E and W feel backwards for your mount, flip the RA axis sign under Modes on
[Setup](/docs/setup#modes); if toward/away does, flip Dec. Those two signs are
the whole calibration.

There is also a **blended** mode (tap the label under the strips): a round pad
where up means toward the top of the sky and left/right run along the horizon,
with both motors driven at once to make that happen. It needs home set, and it
is off by default because it hides which axis is moving.

The rate row sets how fast, as a multiple of the sidereal rate: **1×** is the
sky's own speed (a star creeps), **8×** and **64×** are for centering,
**400×** and **800×** cross the sky. Start slow when
something is already in the eyepiece.

On a keyboard the arrow keys do the same thing and the space bar stops.

## STOP

STOP stops both axes instantly, no ramp-down, and ends tracking. It is always
safe to press. If you want tracking back afterwards, tap **Track** again.

## Track

**Track** is sidereal tracking: the RA motor alone at the speed of the sky,
so a target stays put on a polar-aligned mount. If a star drifts *out of the
field faster* with tracking on than off, the direction is backwards for this
mount: flip **Tracking direction** under Modes on [Setup](/docs/setup#modes).
Slow drift is normal and is your polar alignment talking; after a Go To on an
aligned mount, tracking runs both motors and takes it out (see
[Star Align](/docs/align#tracking-with-a-crooked-axis)).

## Exact moves and home

The [Position](/docs/position) page moves an axis to an exact angle at full
speed (the mount manages the ramps), and **Nudge** by an exact step.
**Set Home Here** on [Setup](/docs/setup#home-position) tells the software
the mount is standing in its home position: counterweight straight down,
tube pointing at the pole. That sets both axes to 0° and arms the soft
limits. Do it once at the start of a night, before any Go To.

## Reading the numbers

RA and Dec are degrees the axes have turned from the home position. The dot
lights while an axis is moving. Badges show tracking, whether home is set,
and which machine the mount is attached to.
