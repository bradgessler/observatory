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
- **No site**, **Site override**: the sky and Go To assume 0°, 0° until
  there is a [site](/docs/site); an override is a site typed in or taken from
  a phone in place of the configured one.
- **Mount tilt**, **Polar axis … of true north**: how the mount stands, under
  *Mount As It Stands*, when that differs from the site latitude and true
  north.
- **Star-aligned**: Go To and tracking go through the alignment.
- **Axis scan running**: the Optical Axes page is moving the mount.

**Reset Pointing to Defaults** puts the axis signs and the sync offset back.

## Mount as it stands

Before there is an alignment, the [Orb](/docs/orb) and the
[Scope](/docs/scope) drawing need to know how the mount was set down: **Tilt**
is the latitude knob, **Heading** where the tripod's north leg points, in
degrees east of true north. Once stars or photos have measured the mount,
the measurement wins.
