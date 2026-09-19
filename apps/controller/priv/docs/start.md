# Start: from the box to looking at things

The front page is a flow with four steps. It shows the step you are on and
moves on by itself as the telescope's state changes. Two phones see the same
step because nothing here lives in a browser.

## 1. Plug in

Power the mount and plug the EQDIR cable into the machine running this. The
mount appears within a few seconds. If it doesn't, **Devices** shows what the
machine can see on its ports.

## 2. Zero

The mount has no absolute encoders: it does not know which way it is turned
until you tell it. Put it upright by eye — counterweight straight down, tube
along the polar axis — and tap **Zero the axes here**. That gives the
software its reference for the axis angles and arms the cable-safety limits.
It has nothing to do with the sky; the stars do that next. Zeroing again later
starts the star alignment over, on purpose: the old stars counted from the
old zero.

## 3. Stars

You do not need Polaris or a level tripod. The page names a bright star and
says where to look. Tap **Slew near it** (the first slew is a guess from the
ideal set-up — watch the cable), centre the star in the eyepiece with any
control, then tap **That's it**.

- One star fixes the offsets. Gotos are roughly right.
- Two stars, far apart, pin the polar axis wherever it really is.
- Three stars let the software say how well they agree. When they agree to
  better than half a degree the page **locks** and turns into the control
  surface.

If the three disagree by degrees, one of them is not the star you think it
is: forget the one with the biggest "off by" and do it again.

## 4. Look

Locked. **Look At** is tonight's list ranked for this spot and this scope: tap
**Go** and the mount slews there and holds it — both axes, at whatever rates
the fitted geometry needs, so a crooked polar axis does not matter for
looking. **On Target** says what it is holding and how far off it thinks it
is. **Centre it** opens the nudge pad; when you let go, the hold picks up
from where you left it rather than dragging the object back to where the
model thought it was.

STOP is in the header on every page and on the game pad. It stops both axes
and ends the hold. **Add a star** tightens the alignment any time; **How
it's steered** (Setup) shows the offsets, the axis error and which control
law is in charge.

## Where the numbers are

- **Setup › How It's Steered** — law 1/2/3, the fitted axis error, the
  offsets in force, the tracker's rates and error.
- **Star Align › Stars So Far** — each star's residual.
- **Events** — every move, who asked for it, every star, every stop.
