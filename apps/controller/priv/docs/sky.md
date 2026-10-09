# Sky Map

A map of the sky right now from where you are: stars to magnitude 5, the Messier
objects and other named deep-sky objects, constellation lines, the Moon and
the bright planets. North is up, east is left — the way it looks when you lie
on your back and look up. The rim is the horizon, the center is straight
overhead. The shaded ring is your tree line (see [Horizon](/docs/horizon)).

## Go To

Tap an object for its page. Three lines answer what matters before you
touch anything:

- **Look**: is it up and clear of your trees, and until when.
- **Go To**: will it land in the eyepiece. Once the telescope is aligned
  (three or more alignment points) it says the margin against your field:
  "lands within ±14′, inside your 72′ field". Before that it says how to get
  there: center any bright star or planet and tap **Centered**.
- **Track**: how long tracking keeps it once it's there. It lasts until it
  sets, goes behind the trees, or the counterweight reaches its limit.

The red crosshair on the map is where the software thinks the telescope is
pointing. The shaded ring around it is the [margin](/docs/glossary#margin),
how far off that may be, drawn true to size on the sky, so pinch in to see
it. It is the alignment's rms doubled (about 95% of pointings land inside)
with tracking's live error on top, and the line under the map gives the
number. With fewer than three alignment
points there is nothing to judge the fit by, so there is no ring and the line
says so.

Then:

- **Spiral Search** walks an expanding spiral around the target, one
  low-power eyepiece field per step, pausing at each. Tap **Stop** when it
  appears.
- Center it with the touchpad on the [Center](/docs/center) page or the
  [game controller's](/docs/game-controller) D-pad; both move the view the
  way you push.
- **Centered** says "it's in the middle right now". It asks first, adds an
  alignment point, and can be undone. Each one shrinks the margin. Other
  software calls this a sync.

## The meridian and the flip

A German equatorial mount reaches every star two ways, one on each side of
the pier. The counterweight shaft is the Dec axis. With the tube on the
meridian (the line through due south and overhead) the shaft is level.
Tracking west past that raises the counterweight and lowers the tube toward
the tripod legs.

On a mount whose home was never set there are no soft limits, so the
counterweight is the limit:

- Go To stays on this side of the pier while the counterweight stays level or
  below.
- For a target further west it offers a **flip**: the tube swings to the other
  side of the pier, where the counterweight hangs low and tracking can keep
  it until it sets. A flip goes in two legs. First to the home position
  (counterweight straight down, tube at the pole), where it stops and asks
  whether the way is clear.
  Then, when you tap **Continue**, on to the target. STOP works all the way.
- **Stay This Side** goes without flipping when the target is only a little
  past, with you watching. Tracking stops when the counterweight is 20° above
  level, where the tube can reach the legs, and the page says so.

Which way the counterweight hangs is a guess from where the alignment points
were taken (you probably had it below level), until you say. The sky cannot
tell the two sides of the mount apart, and twice the guess was upside down,
so until it is told Go To and tracking wait. An object's page says
*Counterweight side: guessed* above Go To, and a Go To asks the question
right under its key: is the counterweight below or above level right now?
[Why it asks](/docs/setup#counterweight).

## Tonight

What's worth looking at from your spot over the next two hours, on its own
page (Tonight in the menu). It only lists things above your tree line, judges
them against your telescope (see [Magnitude](/docs/magnitude)), pushes faint
galaxies down when the Moon is bright, and favours things people actually
enjoy: the Moon, planets, bright clusters, the showpiece nebulae and
galaxies. The first five are a tour; the rest are there if the crowd wants
more.

Each row shows how high it is (the line in the quarter circle, with your
trees shaded) and until when it's clear. What Go To and tracking will do
for one of them is on its page (Look, Go To, Track), not on every row.

The plot beside the list (above it on a phone) is the night for the first
five: altitude against time, dusk to dawn, each line numbered as the list
is. Where a line peaks is when that one is highest; dimmed stretches are
behind your trees.

On a wide screen, clicking a row shows it beside the list instead of the
five: its night, its own altitude curve with its highest point and when,
and Go To. On a phone a row opens the object's page, which has the same two
pictures under its keys. Picking something on the Sky Map shows the same
panel, and draws the path on the map itself.

## An object's night

Where one object goes across your sky from now until dawn, on the same
chart you picked for the Sky Map (the dome, the horizon, the mount's axes).
The line says how dark the sky is along the way: **solid** where it's
fully dark (the sun 18° or more below the horizon), **dashed** in twilight,
**dotted** in daylight. A dot marks each hour, with the time beside it, and
a ring marks where it is now. During the day, that's the whole night ahead,
so you can see when it's worth waiting for.

There are no stars on it. They wheel across the sky with the object, so
stars drawn for one moment would be in the wrong place for every hour
after it. The horizon, the compass and your tree line stay put, and those
are what "where will it be" is measured against. The equator and the
ecliptic are left off for the same reason.

## Data

Star, DSO and constellation data are from
[d3-celestial](https://github.com/ofrohn/d3-celestial) (BSD). Solar-system
positions come from a low-precision ephemeris good to about half a degree —
fine for a low-power eyepiece.
