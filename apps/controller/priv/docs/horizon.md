# Horizon and setup

Everything here is a parameter of the ranking on the Tonight tab and the
shading on the map. Set it once per site; it's remembered.

## Tree line

For each compass direction, how many degrees above level the trees, houses or
hills start. 0 means you can see down to the horizon; 90 means completely
blocked. Anything below the line is drawn dim on the map and left out of
Tonight.

Rough numbers are fine. Hold your fist at arm's length: it's about 10°.

## From a photo

Stand where the scope is, take a **Night-mode** photo with the phone's camera
app so the tree line and some stars are in the frame, then pick it here. Two
things happen:

1. Your phone traces the boundary between sky and obstruction in each column of
   the picture.
2. The photo is plate-solved at nova.astrometry.net to learn exactly which way
   it faced and how wide it was. That maps the boundary to altitude per compass
   direction, and those directions' tree line is updated.

You need a free API key from nova.astrometry.net (profile → API key), set as
`NOVA_API_KEY` when starting the server. Solving takes 30–90 s. Lit windows and
street lights confuse the tracing; check the result and fix the numbers by hand.

## Equipment

Aperture in millimetres of what you're looking through: 0 for eyes only, 50 for
binoculars, 100 for a 4-inch refractor, 203 for an 8-inch SCT. This sets the
faintest thing worth suggesting — see [Magnitude](/docs/magnitude).

## Field calibration

The pointing model needs to know which way each axis turns and which way the
sky moves. Both are guesses until the first slew.

- **Flip RA / Flip Dec** — if a slew lands on the mirror image of the target
  (right distance, wrong side), flip that axis. Then Sync on a star.
- **Flip tracking** — if a star drifts out *faster* with tracking on, tracking
  is running backwards. Slow drift is normal polar-alignment error.
- **Auto-track after slew** — start sidereal tracking after every slew from the
  sky page. On by default.
- **Latitude / longitude** — where the scope is. Defaults come from the config
  file; override here when you travel.

## Moon

The Moon's phase and whether it's up. A bright Moon washes out faint galaxies
and nebulae, so Tonight moves them down and says so.
