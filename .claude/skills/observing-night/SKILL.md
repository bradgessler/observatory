---
name: observing-night
description: Run a field-test night with the Observatory software and the EQ6-R — setup order, what to check, what to record, how findings become issues. Use when the user is about to go outside with the scope, is at the scope, or is debriefing a session.
---

# Observing night

We break in hardware and software by using them. Every night is a field test.
Keep the loop cheap: same setup order, same checks, same debrief.

## Before dark (laptop, indoors)

1. `cd ~/Projects/bradgessler/telescope && git pull && mix deps.get && mix phx.server`
   - No cable yet → a simulated mount appears; that's fine for checking the UI.
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
   Keypad → **Set home** (this arms soft limits and the pointing model).
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
   Soft limits stop RA at ±100° from home only after Set home.

## Game controller (bench › Game controller, or /input)

- The pad starts in **watch only** every time the server starts. Move the ball
  and press buttons first; the page shows exactly what it reads. Turn **Pad
  moves scope** on only when that looks right.
- SideWinder Dual Strike: hold **button 7** (right trigger) and tilt; more tilt
  is faster, up to 800× at full tilt. **Button 6** (left trigger) is STOP.
- If the mount ever moves with nothing held: STOP on any page, then turn the
  pad off. Then tell the log what happened (`git log` has the post-mortem of
  the first time).
- After playing on the bench, **re-home** before slewing from the sky page.

## Record as you go (a note on the phone is fine)

- Where each slew landed vs. where the target was (eyepiece fields off, and which way).
- The Sync offsets the UI prints (RA/Dec degrees). Trend over the night = model error.
- Which direction "RA +" / "Dec +" actually moved the scope (fixes `pointing` signs and `tracking_direction`).
- Anything the ranking got wrong: recommended and invisible, or great and missing.
- Hardware quirks: power sag, cable, clutch slip, noises, USB drops.
- Time and conditions: Moon, haze, light domes.

## Debrief (next day or right after)

1. Findings → issues on `bradgessler/observatory`, milestone **v0: star party night**.
   Pointing/direction facts go on #21 (tracking direction) and #5; ranking misses on #37/#38.
2. Corrections that are just config (axis signs, site, default horizon) → commit them.
3. Update this skill if the order or checks were wrong.

## Known gaps tonight

- Pointing model is first-order (home + one-star sync). Expect a few degrees off until Sync.
- No camera, no finder: Search + Sync is the workflow.
- Planets/Moon come from a low-precision ephemeris (~0.5°): fine for a low-power eyepiece.
