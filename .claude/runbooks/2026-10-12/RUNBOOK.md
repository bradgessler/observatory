# Operator runbook: the night of 12 to 13 October 2026

You are the operator for one night of pictures with Brad's telescope. Another
session is changing the software at the same time; you do not. Your job is to
start one observing plan, watch it, restart it when it stops, write down what
happens, and park the telescope before the Sun. Brad watches the pages
himself; talk to him in short plain sentences.

Everything below is run from this folder:

    W=/Users/bradgessler/Projects/bradgessler/observatory/.claude/worktrees/beautiful-payne-df0a74
    R=$W/.claude/runbooks/2026-10-12
    box() { BOX=10.0.1.15 "$W/.claude/skills/mttr/box" "$@"; }

`box 'elixir code'` runs code on the telescope's computer (a Raspberry Pi,
"the box") over ssh. `box - < file.exs` runs a file.

## Rules

1. **Only three things may move the telescope:** `plan.exs` (the plan),
   `park.exs` (the end), and Brad. Never call `Mount.*`, `Pointing.slew`,
   `Centre.start` or `Tracker.*` yourself.
2. **Never open the box in a browser tool.** `box` and `curl` only.
3. **Never flash, reboot, or edit code.** If something needs a code fix, write
   it in the ledger and tell Brad in one line.
4. **Never print or read** `~/.observatory/stamps/` (Wi-Fi passwords).
5. One instruction to Brad at a time, and only when a machine cannot do it.
6. Times are UTC ("Z") on the box. Pacific time is UTC minus 7:
   12:25Z is 05:25 in the morning.

## Brad is asleep

Brad answered Step 0's question at 08:30Z (the tube is on the **west** side;
it is set on the box) and said go for this plan. Then he went to bed. So:

- **Do not ask Brad anything and do not wait for him.** Skip the question in
  Step 0 and start at its check.
- Wherever this runbook says "tell Brad", write the same words in the ledger
  instead and put them in your final report.
- Anything that needs a hand at the telescope (the camera hung, the mount
  not connected, a stall, the plan stopping twice on the same target) means
  the night is over: **park (Step 3) and go to Step 4.** A parked telescope
  with a short night is a good outcome. A telescope left pointing east is not.
- Your final report is read by the session that started you, then by Brad in
  the morning.

## Step 0: one question for Brad, then the check

The telescope is aligned (4 pictures, 1 arcminute) and is following M33 now.
One fact was never told truthfully: which side of the mount the tube is on.
Ask Brad exactly this and wait for the answer:

> Right now, is the telescope tube on the east side or the west side of the
> mount? (Stand behind the mount facing north: east is on your right.) And say
> "go" when I may start moving it.

Then tell the box (use `:east` or `:west`):

    box 'id = "ttyUSB0"; IO.inspect(Controller.Sky.Lineup.set_counterweight(id, Mount.snapshot(id), :east))'

If it prints `{:error, :upright}`, ask instead "is the counterweight below or
above the tube?" and use `:below` or `:above`.

Now the check (read only):

    box - < $R/check.exs | grep '^W'

Go on only if **every line says `pose=:same`** and every `cw_after` is below
20. If any line says `:flip`, stop and tell Brad which target: a flip is his
decision.

## Step 1: start the plan

Ten targets, about 3 h 30 min. It runs on the box by itself, so your ssh
session ending does not stop it.

    PLAN='Almach@30.975/42.330:12:400:1/60,NGC891@35.639/42.349:30,m77:30,NGC1535@63.566/-12.739:30:1600:4,m1:40,m78:35,NGC2261@99.791/8.738:28,NGC2392@112.295/20.912:30:1600:4,NGC2419@114.535/38.882:28,m82:40'
    box "System.put_env(\"PLAN\", \"$PLAN\"); System.put_env(\"ISO\", \"3200\"); System.put_env(\"SHUTTER\", \"15\"); $(cat $W/.claude/skills/drive-the-box/plan.exs)" | grep '^S'

A step is `target:pictures` or `target:pictures:ISO:shutter`. For each target
the box does Go To, centres it with plate solves, waits for the tracking to
settle, takes the pictures, and goes on.

What they are, for when Brad asks: Almach (gold and blue double star),
NGC 891 (edge-on galaxy), M77 (galaxy with a bright core), NGC 1535 (small
blue planetary nebula), M1 (Crab Nebula), M78 (reflection nebula), NGC 2261
(Hubble's Variable Nebula), NGC 2392 (planetary nebula), NGC 2419 (a very
distant globular cluster), M82 (the Cigar Galaxy).

## Step 2: watch, every 3 minutes

    box - < $R/status.exs | grep '^N'

Healthy looks like: `runner_alive true`, `camera state :ready shooting true`,
`good` going up, `hold ... paused: false` with `error_arcmin` under 0.2,
`trouble ... none`. A `phase` of `centred` or a hold that is `paused: :goto`
for a minute or two between targets is normal.

Append one line per check to the ledger, and one line whenever a target
starts or ends:

    echo "$(date -u +%H:%MZ) <what you saw>" >> ~/.observatory/nights/2026-10-12.txt

Tell Brad when a target finishes ("NGC 891 done, 30 pictures, on to M77").
Otherwise stay quiet unless something below happens.

## When something goes wrong

| What you see | What it means | What you do |
|---|---|---|
| `runner_alive false`, plan `phase` is not `finished` | The plan stopped: the hold ended, the camera stopped, or the box was reflashed (`fw` changed) | Restart from where it was. Same target still held (`hold` names it): start the plan with the **remaining count** for that target first and add `System.put_env(\"FIRST_SKIP_CENTRE\", \"1\");`. Otherwise start from the **next** target. Never restart a target whose `cw` was near +20. |
| Plan `result` mentions `no_hold` and `ended` says `why: :meridian` | The target went too far past the meridian | Start from the next target. |
| `ended` says `why: :lost` or `:counterweight_unknown` | The hold refused or lost the target | Do not restart. Tell Brad the line you saw. |
| A target is "not centred ... skipping" | Clouds, a tree, or too few stars | Nothing: the plan goes on. Write it down. |
| `camera state` is not `:ready`, or `good` has not risen for 4 minutes while `shooting true` | The Sony has hung | Tell Brad: "The camera is not answering. Please switch it off and on." Do not restart anything else. When `state :ready` returns, restart the plan from the current target. |
| `star_size` suddenly near double the last few, or `trouble` lists `late` or `hold_expired` | Tracking let go for a moment (the bug fixed tonight) | Write the picture's name and the trouble lines in the ledger and tell Brad in one line. Keep going. |
| `trouble` lists `stall`, `link_lost` or `goto_failed` | The mount or its cable | Run status again in 30 s. If `mount connected false` or the plan has stopped, tell Brad the line. Do not restart until he says. |
| `box` prints nothing twice in a row | The box is rebooting (the other session flashing: about 40 s) or off the network | Wait 2 minutes and try again. Still nothing: tell Brad. After a reboot the plan runner is gone: see the first row. |
| `free_mb` under 1500 | The SD card is filling | Tell Brad. The pictures are copied to the Mac by the other session; do not delete anything. |
| Brad says stop | | `box 'send(:plan_runner, :stop)'`, then run status and tell him what is still running. |

## Step 3: park before the Sun, at 12:25Z (05:25 Pacific), no later

Whatever is running. This stops the plan, lets the picture in flight finish,
stops the camera run, ends the hold, and sends the mount home: counterweight
down, tube at the pole, in the north. The Sun never comes near there.
Tracking is off afterwards.

    box - < $W/.claude/skills/drive-the-box/park.exs | grep '^S'

It must end with a line like:

    S parked: ra_running=false dec_running=false tracking=:off hold=nil tube_dec=89.x (90 is the pole)

- `tube_dec` above 85 and both `running=false`: tell Brad "Parked at the pole,
  tracking off. Safe for sunrise."
- `S NOT PARKED` or anything else: tell Brad at once, in these words: "The
  telescope is NOT parked. Motors are stopped. Please put the cap on or turn
  it away from the east before sunrise (07:15)." Run status and give him the
  mount line.

If the plan finishes early, park as soon as it does.

## Step 4: hand back

Last ledger line: targets done, pictures per target, every surprise. Then
tell Brad the totals in three lines or fewer.
