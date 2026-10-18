---
title: "After a meridian flip, my telescope thought a small nudge was a half turn"
date: 2026-10-17
kind: note
summary: "My mount can point at any star two ways. After it swung over to its other side, the software that centers targets did its math for the wrong side and gave up. The fix was one line."
---

My telescope centers each target by itself. It points at the target, takes a picture, works out from the stars exactly where it landed, and nudges itself by the difference. It usually takes one or two pictures. Tonight, right after the mount swung over to its other side, it took one picture and quit.

## First, how my mount points

My mount is a Sky-Watcher EQ6-R. The telescope sits on one end of a bar and a heavy counterweight on the other, like a seesaw. The whole thing turns around an axis that points at the North Star, so it can follow the sky as the Earth turns.

Here's the part that matters. To point at any star, the telescope can be on the east side of the mount with the counterweight on the west, or the other way around. Both see exactly the same sky. As a star crosses the line straight overhead, the mount has to swing the telescope over to the other side, or the telescope would bump into the tripod. Astronomers call that a meridian flip.

## The problem: one degree turned into half a turn

The Moon was hidden behind my garage, so Claude swung the telescope over to Vega instead. Vega wasn't in the picture. The stars said the telescope was pointing a bit more than one degree away from it. That's a big miss, but an easy one to fix.

The centering software worked out the nudge and came back with 179 degrees one way and 99 degrees the other. That's half a turn of the mount to fix a one degree miss. It has a safety rule that any nudge bigger than 3 degrees isn't really a nudge, so it refused and stopped. That rule is the only reason the telescope didn't go swinging around the sky.

## Why the math picked the wrong side

To move the mount, the software turns a spot in the sky into a position for each of the two motors. Because the mount can reach any star two ways, there are always two answers. The function that chooses between them prefers the mount's normal side first, and only looks at where the motors actually are when both answers are on the normal side. Here it is, with comments added:

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

When you're choosing where to go for a brand new target, that's right: use the normal side. But a nudge isn't a new target. After a flip, the telescope is on the other side on purpose, and a small nudge should keep it there. So the software planned a nudge from the wrong side, and a small fix looked like a giant move.

## The fix: one line

The code that keeps the telescope following the sky had hit this same problem before, and it already had its own rule, called `{:stay, near}`: always pick the answer closest to where the motors are right now. The centering code just wasn't using it. Now it does:

```elixir
# from Controller.Sky.Centre: stay on the side the telescope is on
{ra_a, dec_a} <- Pointing.axes_for(aim, ctx, near: {:stay, cur})
```

Claude made the change and loaded the new software onto the little computer on the tripod, a Raspberry Pi, while the telescope sat still. That takes about a minute and a half. The next target on that side was the Dumbbell Nebula. The telescope landed about a degree off again, and two nudges brought it to within 2 arcminutes of the middle. An arcminute is 60 arcseconds, so that's a sliver of the camera's view.

## Why it missed by a degree on that side at all

That part isn't a bug, but it's good to know. When I set up, the software takes four pictures to learn how my mount is tilted. Tonight all four were taken with the telescope on the same side. Tiny imperfections, like the camera not sitting perfectly square on the telescope, add up one way on one side and the opposite way on the other. So the setup can be a degree off on the side it never practiced on. Taking a picture and checking the stars after every flip catches that, and that's why the centering step matters so much.
