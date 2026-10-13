# Now: what the telescope is doing

Two things say what the telescope is doing. A **bar at the top of every
page** says it in one line, and **Now**, first under Telescope in the
sidebar, is the page the bar opens: the same line, and everything behind it.

Both come from the mount's own driver, the same for every phone and laptop
looking at it. There is nothing to drive on Now. It is the page you leave
open.

## The bar on every page

One line, the same wherever you are: what the telescope is doing, which
telescope, and where it points.

- **Still**: nothing is moving it.
- **Tracking**, with the object's name when it is holding one ("Tracking
  M33 Triangulum").
- **Moving**: an axis is being driven by hand, from a keypad, a strip or the
  game controller.
- **Slewing**, with where it is going when a Go To sent it ("Slewing to
  Saturn") and how far it has got, as a percentage.
- **Aligning with the camera**: an alignment run is taking its pictures.
- **Not answering**: the mount's cable or power.

While it is slewing or moving the bar is loud: taller, in the caution tone,
and it carries **STOP**. That STOP stops everything that could be moving this
telescope: the motors, a Go To, an alignment run, tracking, Lock On. The
page's own STOP steps aside while the bar has one, so there is one at the
top of the screen, never two. When the telescope is still or tracking, STOP
is back in the page's toolbar, on every page.

After the words comes where it points:

- **RA and Dec**, once an alignment or a home says where the axes point on
  the sky. On a wide screen it adds how high and which way ("45° up in the
  SE").
- **Not on the sky yet**, before that. Set home or align and it changes by
  itself. On a wide screen the two axis angles follow, called *RA axis* and
  *Dec axis*: they are how far each axis has turned, not a place on the sky.

A phone has room for the words and one of these. During a slew it shows the
words, the percentage and STOP.

The bar is the one place this is said. Pages that move the telescope
(Nudge, Plain Keypad, Axis Strips, Center, Position) do not repeat it under
their titles.

With more than one telescope, the bar is about the one picked in the
switcher at the top of the sidebar. These help pages have no bar.

Tap the bar to open Now.

## Doing

The bar's line, larger, with what it has no room for:

- Where it points, and under that how high and which way, or **Not on the
  sky yet: set home or align**.
- During a Go To, a progress bar and how many degrees each axis still has to
  turn.
- A line for the mount itself: each axis's angle with a lamp while it turns,
  whether it is tracking, whether home is set, and *Simulator* when there is
  no telescope on the cable. It opens [Setup](/docs/setup).

Under it, **Alignment** says how well the telescope is aligned and opens
[Status](/docs/start), and **Setup** opens how it is steered.

## Seeing

The latest picture from the camera on the telescope, with how long ago it
was taken. While a picture is being taken it says which stage it is at and,
for a long exposure, how many seconds have gone. **Telescope Camera** opens
the camera's own page. With no camera on the telescope this part is not
drawn.

## Where it points

The sky right now as the mount turns through it: hour angle across, the
meridian down the middle, declination up. Grey is below the horizon. The
crosshair is the telescope. Until home is set or the telescope is aligned
there is no crosshair, and the caption says so. **Sky Map** opens the map
for picking something to go to.

## The mount

The telescope drawn the way it is standing, from its encoders: the tripod,
the head turning on the RA axis (the polar axis), the tube on the Dec axis
with the counterweight opposite. Turn an axis from anywhere and the drawing
follows.

- An **arc** beside an axis means that axis is turning right now.
- A **lamp** at the base, lit, means the mount is tracking, either sidereal
  tracking (the RA motor alone) or tracking through the alignment.

Before an alignment the drawing assumes the mount stands as you said it does
under *Mount As It Stands* on [Setup](/docs/setup#mount-as-it-stands): the
latitude knob at your latitude, the tripod pointed north. Once stars or
pictures have measured the mount, the drawing uses the axis they measured,
so a crooked set-up looks crooked.

Two forms are drawn. A German equatorial has the polar axis and the
counterweight. An alt-az mount, a fork on a base, turns about the vertical
and the tube swings up and down. The page picks the form from what the
driver says the mount is. For the geometry as a diagram, see the
[Orb](/docs/orb).

## Log

What has happened to this telescope, newest first: every Go To, stop, home
and alignment point, with the time. **All Events** opens the full log for
every device.

## What it is for

Seeing at a glance that the telescope is where you think it is, without
walking outside. Watching a slew happen when the telescope is in another
building. And having something to look at when nothing is plugged in at
all: the [simulator](/docs/glossary#simulator) drives the same page.
