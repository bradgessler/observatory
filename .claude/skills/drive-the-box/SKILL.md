---
name: drive-the-box
description: Drive the telescope box from a Claude session during a night — find it, check it, align it with the camera by plate solving, tell it the counterweight side, Go To and Centre, prove the tracking, show pictures, hand over to the eyepiece. Use when Brad is at the scope with the box and wants the session to run alignment, Go To, plate solving or checks, or asks "are you tracking?".
---

# Drive the box

The box (a Pi at the scope) runs the product. A session on the Mac drives it
over ssh with **the product's own functions** (`AutoAlign`, `Pointing.slew`,
`Sky.Centre`, `StillCamera.finder`, `Tracker`), never a parallel script that
moves the mount. If something only works by hand, that is a ledger line and a
product fix (`roll-learning-into-the-product`).

Written from the night of 8 October 2026: the 8SE with the Sony a6000 on a
tripod set down anyhow (polar axis 13° off), aligned by four plate solves in
3½ minutes, Go Tos landing 1 to 3′ off, Go To and Centre bringing them to
0.25′, then an eyepiece tour for kids.

## Rules that cost a night to learn

- **Never the browser pane for the box.** It prompts and stops the session.
  `curl` for pages and pictures, `ssh` (`.claude/skills/mttr/box`) for the rest.
- **Find it by name.** `observatory.local` (DHCP moved it from .44 to .15).
  `dns-sd -G v4 observatory.local` when ssh by name fails.
- **The counterweight side is told, never guessed.** On a mount never homed,
  plates cannot tell the two poses apart (both see the same sky). Twice the
  guess was upside down and a Go To drove the camera toward a tripod leg. Ask
  "is the counterweight bar below or above level right now?" or get a photo,
  then `Lineup.set_counterweight(id, snap, :below | :above)`. Dry-run every
  Go To first (`Pointing.landing/4`): `pose`, `d_ra`, `d_dec`, `cw` after.
- **A meridian flip is Brad's call**, with someone watching the cables.
  Prefer targets on the same side; say which need the swing.
- **One owner of the mount.** Before moving it, check nothing else is
  (`Tracker.status`, `AutoAlign.status`, `Centre.status`, the pad's
  `Input.status().armed`).
- **Flashing is an outage** (`mttr`): fine while setting up, never while
  people are at the eyepiece unless asked. Say "last flash" when he does.
  Order matters when he is waiting to touch the scope: flash, prove, then
  tell him to act. Never two instructions that cross.
- **Read before you blame hardware.** `Telescope.Events.recent(40)` says who
  moved what and why (a "stall" tonight was the driver's own window bug).
- **Hot fixes on the running box:** a misbehaving process can be stopped
  without a flash (`Supervisor.terminate_child(Controller.Supervisor, Mod)`).

## The night, in order

1. **Check** (`check.exs`): firmware, clock, site set, axis signs, the
   alignment (n, rms, home_at), mount connected/homed, the camera and its
   settings, the plate queue, the solver's index files. Prints no coordinates.
   **Stale alignment:** plates and a lineup from another night on a mount
   that was switched on since give the solver a hint in the wrong place
   (tonight: Dec −46° hinted, Dec −4° real, every solve hit its deadline).
   If the tripod moved, `Plates.clear(id)` and `Lineup.clear(id)`.
2. **One blind solve where it points** (`StillCamera.finder/1`, ISO 6400,
   2 s): 5 s on the Pi, ~100 stars. Report alt/az against what Brad says.
3. **Align** (`align.exs`, or the Alignment page's Align with the Camera):
   four frames, 15° RA / 10° Dec apart, a bad frame (garage glow, tree) is
   skipped. Report each plate. rms under 1′ is good; the polar error is in
   `Lineup.status(id).axis_words`.
4. **Counterweight side**: ask, set it, dry-run the targets.
5. **Go To + one solve** (`goto.exs TARGET=albireo`) to measure the landing,
   or **Go To and Centre** (`centre.exs TARGET=m57`): solve, nudge, until
   under 2′. Two pictures is usual.
6. **Prove the tracking** with two solves a minute apart: under 0.5″/s holds
   a target in an eyepiece for an hour. Say the number.
7. **Pictures as they come** (`show-pictures-as-they-come`): fetch the JPEG
   over HTTP (`/cameras/stills/files/<night>/<name>`), crop the middle at
   full size with `ffmpeg -noautorotate`, brighten modestly, caption exactly
   (frames, exposure, ISO, crop, brightened, not enlarged).
8. **Eyepiece hand-over**: prove tracking first, then "camera off (switch,
   then USB), eyepiece in, focus". The D-pad steers in eyepiece terms
   (Center page Backwards / Swapped to square it); the ball goes straight to
   the motors. A meridian flip turns the view 180°.
9. **Kid tour**: build up, end on the best. Saturn, coloured doubles
   (Albireo), the Double Double, bright globulars; nebulae are smudges.
   Facts kids can feel (light that left before ancient Greece, the Sun will
   do this, it's not a ring but a barrel seen end-on).
10. **Ledger** every manual step and every surprise in
    `~/.observatory/nights/<date>.txt`; it becomes issues.

## A night the box runs while Brad sleeps

First done on 12 October 2026: ten targets, 263 pictures, parked before dawn, operated by a Haiku subagent.

- **One question before he sleeps:** anything only his eyes can tell (which side of the mount the tube is on, when
  the bar is level). Then a read-only check that every target lands on the same side.
- **A runbook the operator follows** (`.claude/runbooks/<night>/RUNBOOK.md`, with `check.exs` and `status.exs`):
  what may move the telescope (the plan and the park, nothing else), a status line every three minutes into the
  ledger, a table of what to do for each failure, and "anything that needs a hand at the telescope means park".
  Copy that night's and change the list.
- **`plan.exs`** runs on the box, detached: Go To and Centre, wait for the hold to settle, N pictures, next. It
  stops a camera run left going and sets the camera for centring before every target (both learned the hard
  way). A reflash kills it: restart from the target it was on with the remaining count and `FIRST_SKIP_CENTRE=1`.
  **Always start it with `PARK_AT=hh:mm` (UTC).** The box then parks itself at that time, whatever is running,
  or as soon as the plan finishes if that is sooner. The plan prints "park NOT armed" without it. 18 October
  2026: the plan finished at 05:17, the park was left to a session that wasn't awake, and the telescope stood
  unparked into daylight. A flash kills the timer with the plan: restart both together. `DITHER=1.5` (arcmin)
  or `DITHER=auto` (sized from the sensor map) with `DITHER_EVERY=3` for exposures of 2 s and longer.
  **A planet's turn shoots its moons too:** follow the planet's short frames with a second step on the same
  target, which isn't centred again, e.g. `sol-saturn:2h:800:1/60,sol-saturn:30:800:1`. The moons need frames
  of their own that don't clip (17 October: two 2 s ISO 6400 centring shots clipped every moon's core).
- **`park.exs`** stops the plan and the camera, ends the hold, and sends the mount home: counterweight down, tube
  at the mount's own pole, tracking off. The tube then reads a few degrees under Dec 90 when the polar axis is
  off. **Park three times over:** the box's own `PARK_AT` timer, the operator at the deadline, and a scheduled
  wake-up for the session a few minutes later to check `plan.json` says `parked`.
- **`flats.exs`** takes twilight flats at dawn with the camera only, parked. At f/10 and ISO 100 the useful
  window is the Sun 3 to 0.5 degrees down.
- **The main session stacks, annotates and publishes each target as the telescope leaves it** (`stack-pictures`,
  `annotate-pictures`, `publish-observations`: "A night published as it goes").
- A script's first printed line can arrive glued to the shell's own output and its last can be lost when the ssh
  session closes: match with `grep -o 'S .*'`, not `^S`, and end a script with a short sleep.

## Scripts here

Run with `BOX=observatory.local .claude/skills/mttr/box - < script.exs`.
For a target, prepend: `box "System.put_env(\"TARGET\", \"m57\"); $(cat goto.exs)"`.
Each prints `S ...` lines; grep for them.

- `check.exs`: read-only state for the night.
- `align.exs`: AutoAlign from where it points, one line per plate.
- `goto.exs`: dry-run, refuse unless same side and the counterweight told,
  Go To, wait for landing, one finder solve, the miss in arcminutes.
- `centre.exs`: `Sky.Centre` with progress lines and the hold afterwards.
- `plan.exs`, `park.exs`, `flats.exs`: a night's list, the end of the night, and dawn flats (see above).
- `plan_check.exs`: read only, with the same `PLAN` and `PARK_AT`. Each step's altitude and hour angle at its
  start and end, the pose of its Go To, a warning when the hold would reach its meridian limit before the step
  ends (which stops the plan), and where the Sun is at the park. Run it before every plan and after any change.
- `status.exs`: read only. One screen of the night: the plan and whether its park timer is armed, the camera, the
  dither and the sensor map, the hold, the mount, and the last ten minutes' trouble.
