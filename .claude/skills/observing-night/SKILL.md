---
name: observing-night
description: Run a field-test night with the Observatory software and the EQ6-R — setup order, what to check, what to record, how findings become issues. Use when the user is about to go outside with the scope, is at the scope, or is debriefing a session.
---

# Observing night

We break in hardware and software by using them. Every night is a field test.
Keep the loop cheap: same setup order, same checks, same debrief.

## Physical safety first

* The laptop sits on a stool next to the mount and the USB cable is short: a
  big slew can drag it off. Until a longer cable arrives, **no remote slews
  bigger than a few degrees without a camera check**, and the person at the
  scope watches the cable during gotos. Soft limits stay armed (zero the axes).

## Camera night, fastest to looking (8 October 2026)

The box at the scope, the Sony a6000 on the 8SE, the phone on the box's page
(`http://observatory.local`; the address DHCP hands out moves). A session can
drive all of it: `.claude/skills/drive-the-box`.

1. Tripod anywhere with open sky overhead; level and polar alignment don't
   matter (13° off aligned to 14″ that night). Camera on, lens cap off.
2. Alignment › **Align with the Camera**: four plate-solved pictures, about
   3½ minutes, the box's own code. A frame of garage glow or tree is skipped.
3. **Tell it the counterweight side** (below or above level) before any Go
   To on a mount never homed. The guess was upside down twice.
4. Go To from Tonight's list lands 1 to 3′ off; Go To and Centre (one
   picture, one nudge) brings it under 0.5′. Two solves a minute apart prove
   the tracking (0.19″/s that night).
5. Eyepiece: prove tracking first, then camera off (switch, then USB),
   diagonal and widest eyepiece in. D-pad steers in eyepiece terms; square it
   on Center (Backwards / Swapped). A meridian flip turns the view 180°.
6. For kids, build up and end on the best (Saturn, coloured doubles); a list
   of nebulae is a list of smudges.

## Star-align night (no Polaris needed)

1. Set the mount down: latitude knob near the site latitude, axis roughly north. Level is nice, not needed.
2. Power on, plug in, open `/start` on the phone (Home › Start). It is a flow: **Plug in → Zero → Stars → Look**; it moves on by itself.
   **Zero the axes here** (mount upright: counterweight down, tube along the axis) — this arms the limits.
3. Stars: *Slew near it* (first one is a guess — watch the cable), centre it with any control, *That's it*. Buttons grey out while a slew is in flight; wait. Three stars that agree to under half a degree **lock** the page.
4. Locked: **Look At** › Go on Saturn / the Pleiades. Both motors hold it through the model; nudge to centre and the hold keeps where you left it. STOP on any page ends it. Setup › *How It's Steered* has the numbers (law, offsets, axis error, rates).
5. If a goto misses by more than an eyepiece field, add the object as a star (Sync) and go on.
6. Tube somewhere odd? `/events` says who moved it and when; nothing there means it was moved by hand — zero the axes and align again.

## Before dark (laptop, indoors)

1. `cd ~/Projects/bradgessler/telescope && git pull && mix deps.get && mix phx.server`
   - No cable yet → a simulated mount appears; that's fine for checking the UI.
   - Since October 2026 a dev server keeps to itself: no cluster, no looking for boxes, so a server
     started for something else can never join a telescope in use (one did, and its simulated camera
     showed on the box as live stars). When this Mac should be a node of the box's cluster (to drive
     the box's mount from here, copy its frames, solve its plates): `OBSERVATORY_CLUSTER=1 mix phx.server`.
2. Open `http://<laptop-ip>:4000` on the phone (same Wi-Fi). Toggle night mode (◐).
3. Sky tab → **Horizon**: set the tree line per direction for tonight's spot;
   set aperture for the scope in use.
4. **Tonight** tab: sanity-check the top five against the actual sky (is the
   Moon there if it's up? planets? anything obviously below the trees?).

## At the scope

1. Power: 12 V, 4 A, **center-positive**; LED steady. Plug the EQDIR cable into
   the laptop; the real mount replaces the simulator within ~3 s.
2. Polar align with the polar scope.
3. Home position: counterweight **down**, scope pointing at the pole.
   Setup → **Zero the axes here** (this arms soft limits and the pointing model).
4. **Direction check before anything else** (10 seconds, saves the night):
   on the keypad hold **RA +** at 64× and watch which way the tube moves, then
   **Dec +**. Then Sky → Horizon → tap **Flip RA** / **Flip Dec** until a slew
   to a bright star goes the right way (a wrong sign sends the scope to the
   mirror image of the target). Do this on the Moon or Vega: big, obvious.
5. First light: Tonight → pick a bright star near the zenith → **Slew**.
   - Lowest-power eyepiece, defocus so the star is a big disk.
   - Not in the field? **Search** (spiral); **Stop** when it appears.
   - Center with the keypad at 8× then 1×. **Sync**.
   - Watch it for 30 s. Drifting out *fast*? **Flip tracking** (Horizon tab).
     Drifting slowly = normal (polar alignment); re-center and move on.
6. Now the Top 5. Tour order: brightest/easiest first. Auto-track is on by
   default after every slew from the sky page.
7. **If the scope heads somewhere alarming: the STOP button is in the sky
   page header and the middle of the keypad; EMERGENCY STOP is the red bar.**
   Soft limits stop RA at ±100° from zero only once the axes are zeroed.

## Game controller (bench › Game controller, or /input)

- The pad starts in **watch only** every time the server starts, and turns
  itself off when the mount driver restarts (cable hiccup). A held trigger
  while it is off does nothing except a line on the page and in `/events`
  ("pad is off"). Turn **Pad moves scope** on from the locked front page or the
  Game Controller page; move the ball first and check what it reads.
- SideWinder Dual Strike: hold **button 7** (right trigger) and tilt; more tilt
  is faster, up to 800× at full tilt. **Button 6** (left trigger) is STOP.
- If the mount ever moves with nothing held: STOP on any page, then turn the
  pad off. Then tell the log what happened (`git log` has the post-mortem of
  the first time).
- After playing on the bench, **re-home** before slewing from the sky page.

## With the camera on the scope (learned on the night of 3 October 2026)

The box sits at the scope with the Sony a6000 at prime focus; the phone is
the page; no laptop outside. A session on the Mac drives the box over ssh
(`.claude/skills/mttr/box`) and curl. Never open the box's pages in the
app's browser pane: it stops the session on a permission prompt.

1. **Focus first.** The Stills page shows star size (half-flux diameter) and
   the last value beside it. Turn the knob a little, shoot, read. Stars were
   8.5 arcsec all evening unnoticed, and 5.0 after two minutes at the knob.
2. **Tell the box which side the counterweight is on**
   (`Lineup.set_counterweight/3`). Left to guess from plates all taken near
   shaft-level, it guessed wrong, and Go To would have gone to the unsafe
   side.
3. **Is it the thing?** Solve a frame and find the target's place in it. The
   brightest blob was a 7th magnitude star, not the nebula.
4. **One driver of the mount at a time.** Killing a script on the Mac does
   not stop what it started on the box. Two ran the mount together for ten
   minutes at Orion. Before starting anything that moves the scope, check
   nothing else is.
5. **Order the list by the sky.** Dim objects before the Moon rises, the
   west before it goes behind the tree (the Ring and the Dumbbell were lost
   to it), bright things last.
6. **Cloud.** Sky three times brighter with the same stars 20 percent dimmer
   is thin cloud, not a lamp. It passed every 10 to 15 minutes. Shoot three
   times the frames you want.
7. **Short frames for bright cores**, and exposures no longer than the drift
   allows (20 s at 0.1 arcsec per second).
8. **Dawn: flats, then darks.** Twilight sky, tracking off, exposure walked
   to mid-scale, 20 frames or more. Then the cap on for darks. The darks
   were missed that night.
9. **Offload as you go**, and delete a frame from the box only after its
   copy on the Mac matches by SHA-256.
10. **Keep the ledger**: `~/.observatory/nights/<date>.txt`, a numbered line
    for everything done by hand that the box should have done itself. That
    list is the debrief.

What to do with the frames afterwards: `stack-pictures`, `finish-pictures`,
`annotate-pictures`, `publish-observations`, `share-cards`.

## Record as you go (a note on the phone is fine)

- Where each slew landed vs. where the target was (eyepiece fields off, and which way).
- The Sync offsets the UI prints (RA/Dec degrees). Trend over the night = model error.
- Which direction "RA +" / "Dec +" actually moved the scope (fixes `pointing` signs and `tracking_direction`).
- Anything the ranking got wrong: recommended and invisible, or great and missing.
- Hardware quirks: power sag, cable, clutch slip, noises, USB drops.
- Time and conditions: Moon, haze, light domes.

## Debrief (next day or right after)

1. Findings → issues on `bradgessler/observatory`, on the milestone of the kind of night it was
   (**Camera night** with the camera on the scope, **Eyepiece night** by eye, **v0: star party night** before that).
   Look for an open issue first and add to it rather than open a second one.
   Pointing/direction facts go on #21 (tracking direction) and #5; ranking misses on #37/#38.
2. Corrections that are just config (axis signs, site, default horizon) → commit them.
3. Update this skill if the order or checks were wrong.

## Known gaps tonight

- Pointing model is first-order (home + one-star sync). Expect a few degrees off until Sync.
- No camera, no finder: Search + Sync is the workflow.
- Planets/Moon come from a low-precision ephemeris (~0.5°): fine for a low-power eyepiece.
