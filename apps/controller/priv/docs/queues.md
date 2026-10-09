# Queues

Frames the Telescope Camera keeps (**Keep Frames** on its Settings) go
through steps, and each step is a queue: frames wait their turn, a few are worked on at once, and nothing
upstream ever waits on it. When there's no room, the frame is dropped and
counted rather than holding up the camera.

## The steps

1. **Write to the SD card** (the box). Each kept frame is written to the
   box's card, into the spool.
2. **Waiting on the SD card for the Mac** (the box). The spool: frames on the
   SD card until the Mac has copied them. It has a budget (a quarter of the
   card's free space when it started, at most 4 GB) and keeps 1 GB of the
   card free for everything else. Frames the Mac has copied are deleted
   first when room is needed; if none are left to delete, new frames are
   dropped until the Mac catches up. Frames waiting here survive a restart.
3. **Copy to this Mac** (the Mac). The Mac asks the box for a few frames at
   a time over the cluster, copies each one over HTTP, checks its checksum,
   and tells the box it has it. The frames never travel on the cluster's
   own connection (the [node](/docs/glossary#node) link), which carries the
   mount's position and STOP.
4. **Find the stars** (the Mac). Each copied frame is measured: how many
   stars, how sharp, the background. The numbers go in a `.json` beside the
   frame in `~/.observatory/frames/<date>/`.

## Reading the page

Each step says how many frames wait and how long the oldest has, how long a
frame waits before its turn and how long the work takes (the middle of the
last minute, and the slowest), how many go through a second, and how busy
the step is: the bar is the share of the last minute its workers spent
working.

The line at the top names the **bottleneck**: the step that's busy 80% of
the time or more, or that has had something waiting 10 seconds or more.
Everything in front of a bottleneck piles up; everything after it sits idle.
