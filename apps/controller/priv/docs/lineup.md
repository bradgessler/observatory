# Line up

You don't need to see Polaris. Set the mount down roughly — the latitude knob
near your latitude, the polar axis pointed vaguely north — and let a few stars
do the aligning.

## What to do

1. **Set home.** Counterweight straight down, tube pointing roughly along the
   polar axis. By eye is fine. This arms the soft limits that keep the mount
   from winding up cables; it does not need to be accurate.
2. The page names a **star** and says where to look ("high in the east").
   Tap *Slew near it* if you like, then centre the star in the eyepiece with
   any control — keypad, nudge, game pad, tilt.
3. Tap **That's it**. That is one sample: where the encoders were when the
   tube was on a known star.
4. Do a **second star, far from the first**. Two stars are enough to work out
   which way the polar axis really points; from here on gotos land.
5. A **third** says how well the stars agree. "Agree to 4′" means the model
   puts each star within four arcminutes of where you centred it.

Any later *Sync* on the Sky page adds another star to the same set.

## What it means

* **agree to N′** — the rms disagreement between your centrings and the fitted
  geometry. Under 30′ is fine for looking; under 10′ for the Moon and planets;
  under 2′ for real exposures.
* **polar axis 31° from the pole (12° east of north, 4° too steep)** — how the
  mount is actually sitting. If you want to polar-align, that is what to fix.
* **off by N′** next to a star — how far that one star sits from the fit. One
  big number among small ones means that centring was sloppy; forget it with
  ✕ and do it again.

## Tracking with a crooked axis

On a polar-aligned mount tracking is the RA motor at sidereal rate. With the
axis somewhere else the target drifts in both axes, so after a goto the
software tracks through the model: every couple of seconds it runs both
motors at whatever rates hold the target, and corrects any drift. It pauses
while you drive by hand and ends when you press STOP.

With the axis far from the pole the field slowly rotates in the eyepiece.
Harmless for looking; it limits long exposures.

## Honest limits

* The stars you centre are the truth the model is built on. Centre carefully.
* Nothing here corrects a tube that isn't square to the Dec axis (cone error)
  or axes that aren't perpendicular. Those come with more stars later.
* Home still matters for the limits. If you move the mount by hand with the
  power off, set home again and start the line-up over.
