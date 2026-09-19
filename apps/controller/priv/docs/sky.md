# Sky

The sky right now from where you are: stars to magnitude 5, the Messier
objects and other named deep-sky objects, constellation lines, the Moon and
the bright planets. North is up, east is left — the way it looks when you lie
on your back and look up. The rim is the horizon, the centre is straight
overhead. The shaded ring is your tree line (see [Horizon](/docs/horizon)).

## Slewing

Tap an object, then **Slew**. The mount goes there at full speed and starts
tracking. The red crosshair is where the software thinks the scope is pointing;
it appears once home is set on the keypad.

The pointing model is simple: it assumes the mount started in the home position
(counterweight down, tube at the pole) and knows the direction each axis turns.
Expect the first slew of the night to be a few degrees off. Then:

- **Search** walks an expanding spiral around the target, one low-power
  eyepiece field per step, pausing at each. Tap **Stop** when the target
  appears. This is how you find things without a finder scope.
- Center it with the keypad at 8× then 1×.
- **Sync** tells the model "the scope is on this right now". From then on
  slews should land in a low-power eyepiece. Re-Sync after a big move across
  the sky if things drift.

If a slew goes to the mirror image of the target (right amount, wrong
direction), one of the axis signs is backwards for your mount: flip it on the
Horizon tab, then Sync again.

## Tonight

What's worth looking at from your spot over the next two hours. It only lists
things above your tree line, judges them against your telescope (see
[Magnitude](/docs/magnitude)), pushes faint galaxies down when the Moon is
bright, and favours things people actually enjoy: the Moon, planets, bright
clusters, the showpiece nebulae and galaxies. The first five are a tour; the
rest are there if the crowd wants more.

Picking one rings it on the map. **Slew** is one more tap.

*up 2h+* means it stays above your tree line for at least two hours. *sets <1h*
means look now. *rises <2h* means it will clear the trees soon.

## Data

Star, DSO and constellation data are from
[d3-celestial](https://github.com/ofrohn/d3-celestial) (BSD). Solar-system
positions come from a low-precision ephemeris good to about half a degree —
fine for a low-power eyepiece.
