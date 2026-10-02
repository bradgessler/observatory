# Start: from the box to looking at things

Start (`/start`, first under Alignment in the sidebar, and on Home on a
phone) is a flow with four steps. It shows the step you are on and moves on
by itself as the telescope's state changes. Two phones see the same step
because nothing here lives in a browser.

## 1. Plug in

Power the mount and plug the EQDIR cable into the machine running this. The
mount appears within a few seconds. If it doesn't, **Devices** shows what the
machine can see on its ports.

## 2. Set home

The mount has no absolute encoders: it does not know which way it is turned
until you tell it. Stand it in its [home position](/docs/setup#home-position)
by eye (counterweight straight down, tube along the polar axis) and tap
**Set Home Here**. That gives the software its reference for the axis angles
and arms the soft limits that keep the cables safe. It has nothing to do with
the sky; the stars do that next. Setting home again later starts the star
alignment over, on purpose: the old stars counted from the old home.

## 3. Stars

You do not need Polaris or a level tripod. The page names a bright star and
says where to look. Tap **Go To** (the first one is a guess from the ideal
set-up, so watch the cable), center the star in the eyepiece with any
control, then tap **Centered**.

- One star fixes the offsets. Go To is roughly right.
- Two stars, far apart, pin down where the polar axis really points.
- Three stars let the software say how well they agree. When they agree to
  better than half a degree the telescope is **aligned** and the page turns
  into the control surface.

If the three disagree by degrees, one of them is not the star you think it
is: forget the one with the biggest "off by" and do it again.

## 4. Look

Aligned. **Look At** is tonight's list ranked for this spot and this
telescope: tap **Go To** and the mount slews there and tracks it, both axes,
at whatever rates the alignment needs, so a crooked polar axis does not
matter for looking. **On Target** says what it is tracking and how far off it
thinks it is. **Center It** opens the [Eyepiece](/docs/eyepiece) page's
arrows; tracking carries on from where you leave it rather than dragging the
object back to where the pointing model thought it was. **Centered**, once
it is in the middle, adds one more alignment point.

STOP is in the header on every page and on the game controller. It stops
both axes and ends tracking. **Add a Star** tightens the alignment any time;
**How It's Steered** ([Setup](/docs/setup)) shows the offsets, the axis error
and which control law is in charge.

## Where the numbers are

- **Setup › How It's Steered**: law 1/2/3, the fitted axis error, the
  offsets in force, tracking's rates and error.
- **Star Align › Stars So Far**: how far off each star is.
- **Events**: every move, who asked for it, every star, every stop.

The words used on every page are in [Words](/docs/glossary).
