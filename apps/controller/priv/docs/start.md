# Alignment status: from the box to looking at things

**Status**, first under Alignment in the sidebar, says how well the
telescope is aligned and walks the four steps to get there. It shows the
step you are on and moves on by itself as the telescope's state changes.
Two phones see the same step because nothing here lives in a browser.

## How well it's aligned

The same picture everywhere: in the sidebar under the telescope you're
driving, beside each telescope in the switcher, and at the top of every
Alignment page. A bullseye and a line of words:

- **Not aligned**: no home, no points. Every ring is dark.
- **Home set · no points**: Go To assumes the mount is perfectly polar
  aligned. The centre dot shows.
- **1 or 2 points · margin unknown**: they fit exactly, whatever they are, so
  the rings are dashed. A third point measures the margin.
- **±3′ · 4 points**: how closely the points agree, which is about how close
  a Go To lands. The rings light from the outside in as the margin meets
  each goal: the outer ring at 30′ (good enough to just look), the middle at
  10′ (the Moon and planets), the centre at 2′ (deep sky).

**Counterweight side guessed** under any of these is about a mount with no
home set: the margin says how close a Go To lands, not which side of the
pier it picks, and that side is a guess until you say where the
counterweight is. Status links to the question, and
[Setup](/docs/setup#counterweight) explains why it asks.

There are three ways to add points. The quickest is **Align with the
Camera**: with a camera on the telescope (the Sony in PC Remote, or the
telescope camera), one tap and the box does it alone. The others are
**Align by Stars** (center a few stars in the eyepiece, one at a time) and
**Align by Phone Photo** (your phone held to the eyepiece, the photos plate
solved, which also says which bolt to turn for the polar axis). All three
feed the same alignment.

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

With a camera on the telescope this step is optional: the strip says
*Set Home (optional)* and the page goes straight to the stars, because the
pictures say where the telescope points without a home. Align by Stars
still needs one.

## 3. Stars

### With a camera: Align with the Camera

Tap **Align with the Camera**. Straight after Set Home the tube looks along
the polar axis, where turning RA only spins the view, so it first swings the
tube up toward overhead on the Dec axis alone, the counterweight still down.
Watch the cables on that first move, and press STOP if it heads for the
ground (an axis sign is flipped). Then it takes four pictures a few degrees
apart, plate solves each on the box, and fits how the mount really sits: a
polar axis 25° off the pole is fine. About three minutes. The pictures are
finder pictures, set to ISO 6400 and 2 seconds, which is what solved on real
sky; the camera is left at that afterwards.

A frame that doesn't solve (a tree, a roof, cloud, soft focus) is skipped
and the mount moves on. Three in a row and it hands the mount to you: move
to clear sky and tap **Continue**. If every frame says too few stars, the
sky is not dark yet or the focus is off: the Stills Camera page's star size
is the number to focus by.

With no home set, one question is left when the frames agree: *Is the
counterweight bar below or above level right now?* No picture can say which
side of the pier the counterweight is on, and Go To waits for it, so the
two keys are right under the camera's card. Look at the mount, tap one, and
the page moves on to Look. [Why it asks](/docs/setup#counterweight).

Once aligned, the camera can come off and an eyepiece go in. The alignment
belongs to the mount, not the camera, as long as the tripod and the clutches
are not touched.

### By eye: Align by Stars

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
- **Align by Stars › Stars So Far**: how far off each star is.
- **Events**: every move, who asked for it, every star, every stop.

The words used on every page are in [Words](/docs/glossary).
