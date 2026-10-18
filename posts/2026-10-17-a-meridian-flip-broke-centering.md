---
title: "After a meridian flip, my telescope thought a one degree nudge was a half turn"
date: 2026-10-17
kind: note
summary: "My mount can point at any star two ways. After it flipped to the other side, the software that centers targets worked out its correction for the wrong side and gave up. The fix was one line."
---

My telescope centers each target on its own. It does a Go To, takes a picture, plate solves it to find out exactly where it landed, and nudges the mount by the difference. It usually takes one or two pictures. Tonight, right after the mount flipped over, it took one picture and quit.

## A German equatorial mount can point at any star two ways

My mount is a Sky-Watcher EQ6-R. The tube sits on one end of a bar and a counterweight on the other, and the whole thing turns around an axis pointed at the pole. To point at a star, the tube can be on the east side of the mount with the counterweight on the west, or the other way around. Both see exactly the same sky.

Which one you use depends on where the star is. As a star crosses the meridian, the north-south line overhead, the tube on one side would end up below the counterweight and run into the tripod. So the mount swings around to the other side. That's a meridian flip.

## The picture said one degree, the math said half a turn

The Moon was behind my garage, so Claude flipped the telescope over to Vega instead, high in the west. Vega wasn't in the picture. The plate solve found the picture was 68 arcminutes away from Vega, a little over a degree.

That's a big miss but an easy one to fix. The centering software worked out the nudge and came back with 179 degrees on one axis and 99 on the other. It has a rule that a nudge bigger than 3 degrees isn't a nudge, so it refused, which is the only reason it didn't send the telescope on a half turn around the sky.

## Why it picked the wrong side

To move the mount, the software has to turn a position in the sky into two motor positions. Because of the two-ways-to-point thing, there are always two answers, one for each side. Here's the function that picks between them:

```elixir
# from Controller.Sky.Model: two motor positions reach any star, one for each side of the mount
def encoders(params, signs, alt, az, near) do
  [a, b] = solutions(params, signs, alt, az)

  cond do
    # one answer on the normal side, one past it: take the normal side
    abs(elem(a, 0)) <= 90 and abs(elem(b, 0)) > 90 -> a
    abs(elem(b, 0)) <= 90 and abs(elem(a, 0)) > 90 -> b
    # only when both are normal does it look at where the motors are now
    near != nil -> Enum.min_by([a, b], fn {r, d} -> abs(r - elem(near, 0)) + abs(d - elem(near, 1)) end)
    true -> Enum.min_by([a, b], fn {r, _} -> abs(r) end)
  end
end
```

For a fresh Go To that's what you want: prefer the normal side. But a nudge isn't a fresh Go To. After a flip the telescope is on the other side on purpose, and the nudge should stay there. The function preferred the normal side first and only looked at where the motors actually were as a tiebreaker, so it planned the nudge from the wrong side.

The tracking code had already run into this and has its own rule, `{:stay, near}`, that always takes the answer closest to where the motors are. The centering code just wasn't using it:

```elixir
# from Controller.Sky.Centre: stay on the side the tube is on
{ra_a, dec_a} <- Pointing.axes_for(aim, ctx, near: {:stay, cur})
```

## It worked on the next target

Claude made the change and rebuilt and reflashed the Raspberry Pi while the telescope sat still. That takes about a minute and a half. The next target on the flipped side was the Dumbbell Nebula. The Go To landed about a degree off again, and two nudges took it to within about 2 arcminutes.

## Why the Go To missed by a degree on that side

That part isn't a bug, but it's worth knowing. The software builds its model of how the mount is sitting from four plate-solved pictures, and tonight all four were taken with the tube on the same side. Small errors, like the camera not sitting quite square to the mount's axes, add up one way on one side and the other way on the other side. So a model built on one side can be a degree off on the other. A plate solve after the flip measures that, which is why the centering step matters so much on a mount that isn't carefully set up.
