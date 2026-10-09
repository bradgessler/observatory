# Horizon and setup

The Sky Map's **Horizon** tab. Everything here is a parameter of the ranking
on the Tonight page and the shading on the map. Set it once per site; it's
remembered.

## Tree line

For each compass direction, how many degrees above level the trees, houses or
hills start. 0 means you can see down to the horizon; 90 means completely
blocked. Anything below the line is drawn dim on the map and left out of
Tonight.

Rough numbers are fine. Hold your fist at arm's length: it's about 10°.

## From a photo

Stand where the telescope is, take a **Night-mode** photo with the phone's camera
app so the tree line and some stars are in the frame, then pick it here. Two
things happen:

1. Your phone traces the boundary between sky and obstruction in each column of
   the picture.
2. The photo is [plate solved](/docs/glossary#plate-solve) at
   nova.astrometry.net to learn exactly which way it faced and how wide it was. That maps the boundary to altitude per compass
   direction, and those directions' tree line is updated.

You need a free API key from nova.astrometry.net (profile → API key), set as
`NOVA_API_KEY` when starting the server. Solving takes 30–90 s. Lit windows and
street lights confuse the tracing; check the result and fix the numbers by hand.

## Equipment

Aperture in millimetres of what you're looking through: 0 for eyes only, 50 for
binoculars, 100 for a 4-inch refractor, 203 for an 8-inch SCT. This sets the
faintest thing worth suggesting — see [Magnitude](/docs/magnitude).

## Location

Where the telescope is, in decimal degrees, north and east positive. The
default comes from the config file; change it on the
[Location](/docs/location) page when you travel.

## Field calibration

The pointing model needs to know which way each axis turns and which way the
sky moves. Both are guesses until the first Go To. They live under Modes on
[Setup](/docs/setup#modes):

- **RA axis sign / Dec axis sign**: if a Go To lands on the mirror image of
  the target (right distance, wrong side), flip that axis. Then center a star
  and tap **Centered**.
- **Tracking direction**: if a star drifts out *faster* with tracking on,
  tracking is running backwards. Slow drift is normal polar-alignment error.
- **Auto-track after slew**: start tracking after every Go To. On by
  default.

## Moon

The Moon's phase and whether it's up. A bright Moon washes out faint galaxies
and nebulae, so Tonight moves them down and says so.
