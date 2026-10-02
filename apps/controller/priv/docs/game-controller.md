# Game controller

A USB game controller plugged into the machine running the server (the box at
the telescope, or the Mac). The server reads it, never the browser, so it
works the same whatever phone or laptop has the page open. The Game
Controller page shows every one it can see, its sticks and buttons live.

The one it knows by name is the Microsoft SideWinder Dual Strike, whose right
half tilts on a ball joint: that is **the ball**. Any other controller shows
up too, with its raw axes and buttons, so it can be mapped by watching what
changes when you press things.

## Watch Only and Moves the Mount

Two states, and the page always says which one it is in:

- **Watch Only**: the controller is read and shown, and moves nothing.
- **Moves the Mount**: it drives the mount named under it.

On a box it starts in Moves the Mount, because in the field it is how the
telescope is driven. It drops back to Watch Only by itself if the mount stops
answering or the controller is unplugged, and the page says why.

## The trigger is a dead man's switch

Nothing moves unless the trigger is held. Hold the trigger and tilt the ball:
the further the tilt, the faster, from a creep to 800×, RA left and right,
Dec forward and back. Let go of the trigger and both axes stop.

The software also stops the mount by itself when the controller goes quiet:
every report is stamped with the time, anything more than a fraction of a
second old is thrown away, and if no fresh report arrives for 0.6 s the move is
released. A controller that falls behind can never replay a backlog of old
"trigger held" reports and keep the mount moving after the hand let go.

## The D-pad

The D-pad makes small moves without the trigger. It moves the view the way
the [Center](/docs/center) page's touchpad does: press up and the object
moves up in the eyepiece, using the same map of which axis moves the view
which way. A tap creeps; hold it and it speeds up.

## Centered and STOP

- **STOP** (the left trigger on the Dual Strike) stops both axes and ends
  tracking, like STOP on every page.
- **Centered** (the face button marked 1) says "it's in the middle of the
  eyepiece": an alignment point for whatever is being tracked, the same as
  the **Centered** key on a page.

Every press shows in [Events](/docs/events), filtered under Game Controller.
