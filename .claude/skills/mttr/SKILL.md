---
name: mttr
description: Fix the box while it is in use and bring it back to what it was doing — find the bug, fix it on the side, flash, restore, measure how long the telescope was out, and make that number smaller next time. Use when something breaks during a session, before any firmware push to a box that is tracking or shooting, and when reviewing why a recovery was slow.
---

# MTTR: every flash is an outage

A telescope that is holding a target is in production. Anything that stops it
(a bug, a crash, a power cut, **and every firmware push**) is an outage, and
the number that matters is how long until it is doing again what it was doing:
the same target, held, pictures flowing. Measure it every time. Shrink it.

The loop: **notice → keep it alive → fix on the side → flash → restore →
record → find the slowest step → fix that too.**

## 1. Notice, and say what is out

State it in one line before touching anything: what the scope was doing, what
it is doing now, since when. "Lock On lost Saturn at 05:03, tracking alone
drifts 5.5 arcsec/s." Read it off the box, not from memory:

    .claude/skills/mttr/box - < .claude/skills/mttr/poll.exs

## 2. Keep it alive first

If the target can be kept or got back by hand-driving the software, do that
before fixing the cause. A workaround that holds the target is worth more
than a fix that needs a reboot. Tonight's example: Lock On would have lost
Saturn while calibrating, so it was handed a calibration computed from plate
solves instead, and the code change waited.

## 3. Fix on the side

All changes are made and tested on the Mac, against the simulator, while the
box keeps running the old code. Nothing is edited on the box. Before a flash:

- the test that would have caught it exists and fails without the fix;
- `mix test` for the apps touched is green;
- `.claude/skills/mttr/build.sh` built the image (it checks the Pi binaries
  are ARM, and never prints the stamp file's secrets).

## 4. Flash, timed

    .claude/skills/mttr/flash.sh "why this flash"

It refuses when a goto or an auto-align is in flight, or when a lock is
holding without a fresh heartbeat (it would not be picked up). Then it
uploads, watches the box come back, and prints one line per change with the
seconds since it went down. The lock keeps holding during the upload; the
outage starts at the reboot.

## 5. Restore: the box does it, you verify

The box brings itself back (`Controller.LockOn`, `Controller.StillCamera`):

- the stills camera resumes continuous shooting and solving from what it
  saved in Settings (`"still_camera"`);
- Lock On finds its heartbeat (`"lock_on_resume"`, saved every 10 s while
  holding), waits for the mount and a network-set clock, moves each axis to
  where it would be by now, and holds on the saved calibration.

Verify, don't assume: lock `holding`, error under ~10 px and shrinking, a new
picture every cycle, the same exposure. If it gave up, `why` says so.

**If the target did not come back** (not in the frame after the catch-up):
set a finder exposure (ISO 6400, 2 s), turn Solve Pictures on, solve one
frame, and move by the difference to the target's RA/Dec with the mount's
measured axis effect (`hack/` has the night's scripts). Then lock again with
`saved: true`. Do not re-calibrate with the motors stopped on a small target:
it leaves the field before the calibration ends.

## 6. Record it

`flash.sh` appends to `~/.observatory/outages.jsonl`: why, firmware before and
after, and seconds from going down to: the box answering, the clock set,
pictures flowing, the lock holding, the target seen. Add a line to the
night's log too. An outage nobody timed did not get better.

## 7. Find the slowest step and fix it

Read the last few lines of `outages.jsonl`. The biggest gap is the next thing
to fix, in the product, not in the script.

Baseline, 2026-10-04 05:41 UTC (EQ6-R, a6000, Pi 3, Saturn held by Lock On):

| step | at |
|---|---|
| box answers | +20 s |
| mount connected, camera ready, shooting again | +26 s |
| clock set by the network | +101 s |
| lock holding again | +104 s |
| Saturn seen, 32 px from centre | +111 s |

75 of those 104 seconds were the wait for network time. That is the first
thing to remove.

## Rules

- Never flash in the middle of a goto, an auto-align or a held slew.
- Never flash a holding lock that has no heartbeat.
- A restore that needs a person is a bug: write down what you had to do by
  hand, then make the box do it.
- STOP still ends everything, during a restore too. A restore never moves the
  mount further than `revive_max_deg`, and gives up in words rather than guess.
- Measure from the outside (`flash.sh`) and from the inside (the box's own
  record of each recovery): a crash at 3 am has no one watching.
