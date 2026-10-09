# Setup

One mount's page (`/setup/<mount>`, from the status line on any page or a
mount's badge on Home): how it is being steered, its home position, and every
mode that changes where it points.

## How it's steered

Which layer of the [Control Stack](/docs/stack) is in charge, what it is
correcting for, and what tracking is doing right now. Law 3, *Sky ·
star-aligned*, means Go To and tracking go through this mount's pointing
model; law 2, *Sky · ideal geometry*, means the software assumes a
polar-aligned mount because there is no alignment yet.

## Home position

The mount has no absolute encoders: switched on, it counts from wherever it
stands. The **home position** gives the counts a meaning:

- counterweight straight down,
- tube along the polar axis, pointing at the pole,
- both axes at 0°.

Stand it like that by eye and tap **Set Home Here**. That also arms the
**soft limits**, the angles from home past which the mount stops itself so
it never winds up its cables (*Soft limits from home* under Modes shows
them).

Home does not need to be accurate: it is for the limits and the readouts,
and the stars do the pointing. Setting home again starts a star alignment
over, on purpose, because the old stars counted from the old home. Align by
Photo works without home at all.

The [Position](/docs/position) page sends both axes back to 0°, 0°.

## Counterweight

A German equatorial mount reaches every point in the sky two ways, one from
each side of the pier, and only one of them has the counterweight below
level. Which one depends on which side of the mount the counterweight is
on, and the sky cannot say: both sides see the same stars, so no star you
center and no photo it solves tells them apart.

With home set there is nothing to ask: home is where the counterweight
hangs straight down. With no home set (Align with the Camera and Align by
Phone Photo work without one) the software guesses that most alignment
points were taken with the counterweight low. When they were all taken
near the meridian, with the counterweight shaft close to level, that guess
is a coin toss. Got wrong,
Go To offers a flip to what it thinks is the safe side and goes to the
unsafe one, tube toward the tripod legs.

So once there is an alignment, the **Counterweight** card asks, here, on
Align by Phone Photo, under Align with the Camera, and right under any Go
To that waited for it: *Is the counterweight below or above level right
now?* Look at the mount and follow the counterweight shaft from the mount
out to the weight. Sloping down is **Below Level**; sloping up is
**Above Level**. With the shaft within 10° of level nobody can say by eye, so the keys are
greyed out: turn the RA axis a little and answer then.

The answer is kept with the alignment, through more alignment points and a
restart of the box, until the mount itself is switched on again. The card
then shows what the software has for the mount as it stands, with that key
lit. If it ever disagrees with what you see, tap the other key.

Until it is told, Go To and tracking wait. The guess was upside down on two
nights running, and on the second a Go To drove the tube to the pose with
the counterweight bar 64° above level and the camera near a tripod leg; a
meridian flip would have swung it further the wrong way. So a Go To, a flip
and a hold all refuse on a guess, say *Which side is the counterweight on?*,
and ask right there. Every page says *Counterweight side guessed* meanwhile.
Once told, Go To picks its side of the pier by the answer, and tracking
never holds with the counterweight more than 20° above level.

## Modes

Anything kept between nights that changes where the telescope points. While
one is on it shows on every page, linking here, so a setting nobody remembers
making can't quietly send Go To the wrong way.

- **Sync offset**: a one-star correction from before alignments existed.
  **Clear** removes it.
- **RA axis flipped**, **Dec axis flipped**: which way a positive step turns
  that axis. Flip one if a Go To lands on the mirror image of the target
  (right distance, wrong side). The alignment usually finds this by itself
  and says so.
- **Tracking reversed**: sidereal tracking runs the RA motor the other way.
  Flip it if a star drifts out of the field faster with tracking on than
  off.
- **Auto-track off**: a Go To no longer starts tracking when it lands.
- **No location**, **Location override**: the sky and Go To assume 0°, 0°
  until there is a [location](/docs/location); an override is one typed in
  or taken from a phone in place of the configured one.
- **Mount tilt**, **Polar axis … of true north**: how the mount stands, under
  *Mount As It Stands*, when that differs from the site latitude and true
  north.
- **Star-aligned**: Go To and tracking go through the alignment.
- **Counterweight side guessed**: on a mount with no home set, which side
  the counterweight is on is only a guess, and Go To and tracking wait until
  it is told. Tell it under [Counterweight](/docs/setup#counterweight).
- **Axis scan running**: the Optical Axes page is moving the mount.

**Reset Pointing to Defaults** puts the axis signs and the sync offset back.

## Mount as it stands

Before there is an alignment, the [Orb](/docs/orb) and the
[Scope](/docs/scope) drawing need to know how the mount was set down: **Tilt**
is the latitude knob, **Heading** where the tripod's north leg points, in
degrees east of true north. Once stars or photos have measured the mount,
the measurement wins.
