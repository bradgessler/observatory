# Align by Stars

You don't need to see Polaris. Set the mount down roughly (the latitude knob
near your latitude, the polar axis pointed vaguely north) and let a few stars
do the aligning.

## What to do

1. **Set home.** Stand the mount in its home position (counterweight
   straight down, tube along the polar axis, by eye is fine) and tap
   *Set Home Here*. The mount has no absolute encoders, so this is how the
   software learns which way the axes are turned; it also arms the soft
   limits that keep the mount from winding up cables. It does not need to be
   accurate. See [Setup](/docs/setup#home-position).
2. The page names a **star** and says where to look ("high in the east").
   Tap *Go To* if you like, then center the star in the eyepiece with any
   control: the keypad, Nudge, the Center touchpad, the game controller.
3. Tap **Centered**. That is one alignment point: where the encoders were
   when the tube was on a known star.
4. Do a **second star, far from the first**. Two stars are enough to work out
   which way the polar axis really points; from here on Go To lands.
5. A **third** says how well the stars agree. "Agree to 4′" means the
   pointing model puts each star within four arcminutes of where you
   centered it.

Any later *Centered* on an object's page adds another point to the same
alignment.

## What it means

* **agree to N′**: the rms disagreement between your centerings and the
  pointing model. Under 30′ is fine for looking; under 10′ for the Moon and
  planets; under 2′ for real exposures.
* **polar axis 31° from the pole (12° east of north, 4° too steep)**: how the
  mount is actually sitting. If you want to polar-align, that is what to fix
  ([Align by Photo](/docs/align-photo) says which bolt and how far).
* **off by N′** next to a star: how far that one star sits from the fit. One
  big number among small ones means that centering was sloppy; forget it with
  ✕ and do it again.

## Tracking with a crooked axis

On a polar-aligned mount, tracking is the RA motor alone at the sidereal
rate: sidereal tracking. With the axis somewhere else the target drifts in
both axes, so after a Go To the software tracks through the alignment:
every couple of seconds it runs both motors at whatever rates keep the
target still, and corrects any drift. **Track What I'm On** does the same
for whatever is in the eyepiece now. It pauses while you drive by hand and
ends when you press STOP or **Stop Tracking**.

With the axis far from the pole the field slowly rotates in the eyepiece.
Harmless for looking; it limits long exposures.

## Honest limits

* The stars you center are the truth the pointing model is built on. Center
  carefully.
* Nothing here corrects a tube that isn't square to the Dec axis (cone error)
  or axes that aren't perpendicular. Those come with more stars later.
* Home still matters for the soft limits. If you move the mount by hand with
  the power off, set home again and start the alignment over.
