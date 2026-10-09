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

## Scripts here

Run with `BOX=observatory.local .claude/skills/mttr/box - < script.exs`.
For a target, prepend: `box "System.put_env(\"TARGET\", \"m57\"); $(cat goto.exs)"`.
Each prints `S ...` lines; grep for them.

- `check.exs`: read-only state for the night.
- `align.exs`: AutoAlign from where it points, one line per plate.
- `goto.exs`: dry-run, refuse unless same side and the counterweight told,
  Go To, wait for landing, one finder solve, the miss in arcminutes.
- `centre.exs`: `Sky.Centre` with progress lines and the hold afterwards.

## The plan runner (`plan.exs`): let the box run the list

Driving step by step over ssh dies with every Wi-Fi blip (a series lost its counter mid-run on 8 Oct).
`plan.exs` spawns a process on the box, detached from the ssh session, that runs the list itself:

    box "System.put_env(\"PLAN\", \"m57:30,NGC1514@62.3208/30.7760:20,sol-saturn:40:800:1/40\"); $(cat plan.exs)"

Each step: wait for the camera to be idle, Go To and Centre (flip allowed), wait for the hold to be steady
(under 0.15' for 4 s: the first frames after centring were smeared without it), N good frames at the step's
own ISO/shutter (or `ISO`/`SHUTTER`), next. A step on the same target as the one before isn't centred
again. Planets by ephemeris id (`sol-saturn`); anything the catalogue lacks (159 objects, few NGCs) as
`NAME@RA/DEC` in J2000 degrees. `FIRST_SKIP_CENTRE=1` when the first target is already centred. It stops
(never moves on) if the hold ends. Progress in `/root/.observatory/plan.json`; stop with
`send(:plan_runner, :stop)` and `Sky.Centre.stop(id)`, then wait for the camera before the next plan:
killing a run mid-exposure and starting a Go To smears that frame. Watch it with a Monitor that prints
only target changes, every 10 frames and stops.

## Picking the night's targets

- **Same side of the mount first.** Dry-run every target from the current pose; a swing over the meridian
  winds the cables, and on 8 Oct the swing back pulled a plug and cut the box and the mount at once.
  Two swings a night at most, the second the unwinding way, someone watching.
- **Behind the trees is a target lost**: check altitude and direction before queuing (the Dumbbell at 39
  degrees due west, the Crab rising out of a tree in the east: 4 of 22 frames usable).
- **Small and bright suits 2 m of focal length** (planetaries, globulars, galaxy cores). Big, faint,
  deep-red nebulae (Heart, North America, California) want a wide rig and a modified camera: decline,
  say why, note it for a wide-field night.
- **What the site already has** (observations/): don't spend the night repeating it.

## Power loss, or the mount lost its counts

Signs: the box's uptime is seconds, `mount.power_on` in Events, both axes read 0.0, the alignment stale.
The Events written in the last minute before an unclean shutdown are lost; the box's black box line
(`system.boot` `last:`) says what the motors were doing. Then:

1. Stop everything that might move it: `Supervisor.terminate_child(Controller.Supervisor,
   Controller.Sky.Revive)`, `Input.arm(false)`, check no plan runner or Centre run.
2. Take one picture first, no motion: if it solves, re-align from there. If it's black (a tree, the
   ground), work out the possible stopping points from the interrupted move and the old model (the
   tripod hasn't moved, so its geometry holds), and make only the smallest move that heads toward open
   sky from all of them. Or ask Brad to point it up by hand: the alignment is redone anyway.
3. Align with the Camera, tell the counterweight side, then carry on.
4. Look at the cables: tonight's cause was cable wrap, not a supply sag.

## The offload queue

Start `.claude/skills/mttr/offload.py` with the first frame and leave it running all night (verified
copy, then removed from the box). Never "wait for Ethernet". See `night-to-website`.

## Never (8 October 2026)

- Move the mount on a guessed counterweight side.
- Tell Brad to touch the scope in the same message as a flash or a move; finish, prove, then one
  instruction. "Last flash" means none until he says.
- Trust a long-running watcher that acts on "nothing is holding" without a settle time (Revive pulled a
  Go To back to the old target); stop it on the running box rather than flash.
- Full-tilt pad hunting on a never-homed mount without saying so: 800x, no soft limits, and the stall
  watch trips on the ramp.
