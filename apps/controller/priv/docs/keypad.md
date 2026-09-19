# Keypad

The hand controller, on a phone or a laptop.

## Moving the scope

Press and hold an arrow. The mount moves while you hold and stops when you let
go — or within a second if the connection drops.

The picture at the top is your mount as it stands: the **polar axis** tilted
up toward the pole by your latitude, and the **Dec axis** square to it. Below
it, **one strip per axis**. Touch a strip and pull: a small pull creeps, a long
pull crosses the sky (1× to 800×, shown while you hold), let go and it stops.
The axis you're turning lights up in the picture.

- **Polar axis (RA)** — turns the whole tube around the tilted axis, following
  the sky's rotation. Pull toward **E** or **W**.
- **Dec axis** — swings the tube **toward** or **away from** the pole.

If E and W feel backwards for your mount, flip the RA sign in Setup; if
toward/away does, flip Dec. Those two signs are the whole calibration.

There is also a **blended** mode (tap the label under the strips): a round pad
where up means toward the top of the sky and left/right run along the horizon,
with both motors driven at once to make that happen. It needs home set, and it
is off by default because it hides which axis is moving.

The rate row sets how fast: **1×** is sidereal (a star creeps), **8×** and
**64×** are for centering, **400×** and **800×** cross the sky. Start slow when
something is already in the eyepiece.

On a keyboard the arrow keys do the same thing and the space bar stops.

## STOP

The circle in the middle stops both axes instantly, no ramp-down. It is always
safe to press. If you want tracking back afterwards, tap **Track** again.

## Track

Sidereal tracking turns the RA axis at the speed of the sky so a target stays
put. If a star drifts *out of the field faster* with tracking on than off, the
direction is backwards for this mount: flip it on the sky page's Horizon tab.
Slow drift is normal and is your polar alignment talking.

## More

**Degrees** moves an axis by an exact amount at full speed (the mount manages
the ramps). **Set home** tells the software the mount is in its home position:
counterweight straight down, tube pointing at the pole. That zeroes both axes
and arms the soft limits — do it once at the start of a night, before any
slewing from the sky page.

## Reading the numbers

RA and Dec are degrees the axes have turned from home. The dot lights while an
axis is moving. Badges show tracking, whether home is set, and which machine the
mount is attached to.
