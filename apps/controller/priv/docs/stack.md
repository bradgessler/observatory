# The control stack

Between a hand and the motors there are layers, and every layer corrects for something a casual set-up got wrong. The Control Stack page shows all of them at once, live, and lights the ones the current input runs through.

| Law | Layer | Corrects for |
|---|---|---|
| 5 | Tracking the target | whatever the pointing model still misses, measured while it runs |
| 4 | Small sky corrections | the target's own corrections (the Moon's parallax, refraction) and the mechanics (cone error, flexure, backlash) |
| 3 | Your mount's alignment | where the polar axis really points (an unlevel tripod and mis-set bolts land here together), where the encoders started counting, the axis directions |
| 2 | If the mount were perfect | nothing: it assumes a level, polar-aligned mount with home set upright |
| 1 | Eyepiece directions | which axis and sign move the view which way (the optics and the side of the pier) |
| 0 | Motors | nothing: steps and rates |

Each control drives at one law. The Center touchpad and the game controller's D-pad drive at law 1, through the eyepiece map. The game controller's ball, with the trigger held, drives at law 0, straight to the motors. A Go To drives at law 3. Tracking a target runs at law 5.

Nothing degrades behind your back: a lower law is a choice, and every layer reads the same encoders, so moving the mount at law 0 never blinds the layers above. Tracking sees the move and tracks the new spot.

A term the software does not model yet is still listed, as "not modelled". A correction that is zero tonight is still a correction.
