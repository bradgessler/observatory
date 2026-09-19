# Keypad

The hand controller, on a phone or a laptop.

## Moving the scope

Press and hold an arrow. The mount moves while you hold and stops when you let
go — or within a second if the connection drops.

The arrows mean a direction on the **sky**, not a motor. The small label under
the D-pad says which convention is in use; tap it to switch.

- **as you see it** — up is toward the top of the sky (the zenith), left and
  right run along the horizon. An equatorial mount's axes are tilted toward
  the pole, so "up" is usually a blend of both motors; the software works out
  the blend from where the scope is pointing. Needs home to be set.
- **N · S · E · W** — the hand-controller convention: N/S swing the tube
  toward or away from the pole (the Dec axis), E/W follow the sky's rotation
  (the RA axis). Available before home is set. If E and W feel backwards,
  flip the RA axis sign in Setup; if N/S do, flip Dec.

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
