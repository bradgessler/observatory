---
title: "Up is up: steering by the eyepiece"
date: 2026-09-26
summary: "At the eyepiece I don't want to think about RA and Dec. I want to pull up and have the stars go up. A red touchpad that pulls from wherever the thumb lands, a D-pad that crawls and then hurries, and one small map from the view to the axes, learned at the eyepiece."
hero: "images/center-pull-up.png"
hero_alt: "The Center page on the simulator, mid-pull: the eyepiece drawn as a red touchpad, an arrow pointing up, RA running at 2.8×"
---

The first field night ended with Saturn, and later the Pleiades, sitting in the middle of the eyepiece. Go To got them close. This post is about the last few arcminutes, which is where I spent most of the night.

An EQ6-R has two axes, RA and Dec, and at the eyepiece neither of them means anything. On a mount set down anyhow, never zeroed, with a star diagonal in the focuser, "Dec forward" might move the stars left, or up, or down and a bit left. It depends on which side of the pier the tube is on, the mirror in the diagonal, and how the diagonal is turned in its holder. A hand controller leaves you to work that out with your eye on the glass, one wrong button at a time.

I wanted what a map on a phone does. Pull up, the picture goes up.

## The Center page

![The Center page on the simulator, mid-pull: a thumb pulling up, the view moving up at 2.8×, RA doing the work](images/center-pull-up.png)

The Center page draws the eyepiece as a round touchpad. Put a thumb on it and pull the way you want the view to go. Further is faster. Let go and it stops. The line under it says what the mount is actually doing, from the mount's own report, so there's proof the thumb is working.

Speed runs from 0.5× to 8× sidereal, which is nothing like a slew. The curve is eased so the first half of the pull stays slow and only the end is brisk:

```elixir
# apps/controller/lib/controller/live/center_live.ex
# the drag: just past the dead zone crawls, the rim is brisk; nothing like a slew
@slow 0.5
@fast 8.0

def speed(mag) when mag <= 0, do: 0.0
def speed(mag), do: @slow * :math.pow(@fast / @slow, :math.pow(min(mag, 1.0), 1.5))
```

Half a pull is 1.3×. At the rim it's 8×.

Which axis moves the view which way is a setting, `"view_map"`, not a guess. It says what moves the view down and what moves it right, each as an axis and a sign:

```elixir
# the first night, EQ6-R, star diagonal: what moved the view down and right
@view_map %{"down" => ["ra", 1], "right" => ["dec", -1]}
```

That default is what the night taught me at the eyepiece: down is RA forward, right is Dec back. A different set-up is a tap or two away. **Up/down backwards** and **Left/right backwards** each flip a pair. **Up/down and left/right swapped** turns the whole map 90°, which is what happens when the diagonal gets turned in its holder. Mine did, somewhere between the Moon and Saturn.

```elixir
def turn(map), do: %{"right" => map["down"], "down" => (fn [a, s] -> [a, -s] end).(map["right"])}
def flip(map, pair), do: Map.update!(map, pair, fn [axis, s] -> [axis, -s] end)
```

Four turns are back where they started, and with the two flips every way the view can sit is covered. It's a setting, so it goes through `Controller.Settings`, and every phone and page picks up the change.

One more thing a pull does. With tracking on, RA is already running at 1× to hold the sky still. A pull that ignored that would move the view relative to a stopped motor, and the stars would lurch the moment you touched the glass. So RA carries on from the tracking rate, and the pull is added on top:

```elixir
for axis <- [:ra, :dec], r = Map.get(rel, axis, 0.0), abs(r) > 1.0e-9 do
  {axis, if(axis == :ra, do: Map.get(@track_units, tracking, 0.0) + r, else: r)}
end
```

Let go and RA goes back to tracking and Dec stops. Every command carries the driver's hold and is re-sent every 250 ms while a thumb is down, so a phone that locks or a hand that slips off stops the mount within a second on its own.

## What the eyepiece taught me

**Red, always.** The first version drew the eyepiece as a white disc. Walking back to the scope with the phone was, in my words at the time, a big white light blasting in my eyeballs. The Center page is red now whatever the theme says, because it only gets used in the dark.

**Pull from where the thumb lands.** The first version measured the pull from the pad's centre. With your eye at the eyepiece you can't see where the centre is, so wherever the thumb came down was already a pull in some direction. My complaint that night was "my thumb is just not following the screen." Now zero is wherever the thumb lands:

```js
// apps/controller/priv/static/assets/js/app.js
// data-origin="touch": zero is where the thumb lands, not the pad's centre
// (an eye at the eyepiece can't see where the centre is); data-reach is
// the pull in px for full speed, data-dead the still zone as a share of it
const fromTouch = pad.dataset.origin === "touch";
...
origin = fromTouch ? { x: e.clientX, y: e.clientY } : centre;
```

The still zone went up too, from 12% of the reach to 18%, so a thumb settling onto glass doesn't move anything. That hook is the only JavaScript involved. It exists because LiveView has no pointer bindings and a held move needs a heartbeat; everything else on the page is HEEx.

**One direction per touch.** A thumb that means "up" drifts sideways without its owner knowing. I'd pull up and Saturn would slide out the side. So the first real pull decides the direction, and it's the only way that touch drives until it lifts:

```elixir
def lock_for(x, y), do: if(abs(y) >= abs(x), do: :vertical, else: :horizontal)

def locked({x, _y}, :horizontal), do: {if(x >= 0, do: 1.0, else: -1.0), 0.0}
def locked({_x, y}, :vertical), do: {0.0, if(y >= 0, do: 1.0, else: -1.0)}
```

The status line says so while you pull: "up/down only until you lift."

## The D-pad

The game pad is a SideWinder Dual Strike, read by the server over USB HID. Its hat, the little D-pad, used to drive the axes as they are: left/right was RA, up/down was Dec. In eyepiece mode it moves the view the same way the touchpad does. `Controller.PadView` pushes the same `"view_map"` to the pad's mapper when it starts, whenever a phone changes it, and every 30 seconds in case the mapper restarted and forgot. One Backwards tap fixes both.

A tap crawls at 2×. That's right for the last arcminute and hopeless for anything bigger. At 2× the view moves about 30″ a second, so crossing the Pleiades, about two degrees, takes four minutes. It felt like it. So holding the hat ramps up:

```elixir
# apps/input/lib/input/gamepad.ex
defp hat_rates(:eyepiece, hx, hy, m) do
  rate =
    cond do
      m.hat_held_ms >= m.fine_top_ms -> m.fine_top
      m.hat_held_ms >= m.fine_ramp_ms -> m.fine_rate
      true -> m.fine_slow
    end
  ...
```

2× on a tap, 8× after a second and a half, 32× after four seconds. At 32× the Pleiades go by in about fifteen seconds. The mapper also notes the tracking rate at the moment the hat goes down and adds it to RA, same as the touchpad. Every number is a parameter on the pad's map, so a different pad or a different taste is config, not code.

## What went wrong

**The D-pad's "wires were crossed."** From the eyepiece I reported that left/right on the pad moved the view up and down. That report arrived while a firmware upgrade to the box was still installing. I was still on the old firmware, where the hat drove the axes directly, and driving RA directly *looks* like up/down in the eyepiece. The new map was right. I "fixed" it anyway, and then put it back once the upgrade finished and the pad did the right thing. Lesson: before changing config because of what somebody sees, know which firmware they're looking at.

**A white disc** and **a pull from the centre**, both above. Neither shows up on a laptop at a desk. Both were obvious in about ten seconds in the yard.

## Where it landed

Saturn centred by feel, first on the touchpad and later on the pad, then the Pleiades. No thinking about axes, no wrong buttons. **Centered** records the time and where both axes were, and says so on the page.

## What's next

- **Centered is an alignment point now** ([#94](https://github.com/bradgessler/observatory/issues/94)). As of the firmware on the box for the second night, Centered on the pad or the page adds a point for whatever the hold is keeping, refits, and says so on the object's page with an Undo. Next is seeing the margin shrink at the eyepiece.
- **The ball as a throttle.** On the Dual Strike you squeeze the trigger and tilt the ball to drive the axes. It might be better as the D-pad's throttle: the hat says which way, the ball says how fast.
- **The map belongs to one side of the pier.** A meridian flip turns the view 180°, which is both Backwards buttons at once. The software knows when it flips the mount, so it should turn the map itself.
