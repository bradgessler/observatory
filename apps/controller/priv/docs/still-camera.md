# Stills camera

A mirrorless camera on the telescope, in place of an eyepiece, plugged into
the box with its USB cable. Today that's the Sony a6000 (and its family). The
box drives it the way Sony's own remote software does: it reads and sets ISO
and shutter speed, presses the shutter, and takes each picture straight off
the camera, RAW and JPEG, as the camera made it.

With a stills camera on the telescope, **Telescope Camera** is this camera.
Its page always shows the latest picture and how long ago it was taken (past
a minute, the clock time too), because its frames come seconds or minutes
apart rather than thirty a second. One job a screen: the picture and **Take
Picture** on the camera's own screen; **Exposure**, **Lock On** and **Plate
Solving** each a tap away, each with the latest picture on it.

## Plug it in so the box can drive it

The camera has to be in **PC Remote** mode: **Menu → toolbox → USB
Connection → PC Remote**.

**Switch the camera on first, then plug in the cable.** An a6000 switched on
with the cable already in comes up as a USB disk instead (a storage-mode
camera can't be driven), whatever the menu says. When that happens the page
says so in one line; unplug the cable and plug it back in.

Set **Power Save Start Time** to 30 minutes, so it doesn't go to sleep
between pictures.

## Pictures

**Take Picture** takes one; **Shoot Continuously** takes one after another
(about one every fifteen seconds on a Pi: most of that is copying the 25 MB
RAW). Every picture is kept whole, never written over, in the box's
`stills/<date>/` folder, named by the time it was taken.

The picture on the page is a small grey copy of the JPEG, measured the way the
telescope camera's frames are: its background, its stars, and the middle of
anything bright and large (the Moon, a planet). Set the camera to **RAW+JPEG**
for the page to have something to show.

**ISO** and **shutter speed** are set by turning the camera's own dials a
notch at a time, the only way an a6000 takes them over USB, so a change takes
a few seconds. The line above the keys says where they landed.

While a picture is being taken the page says what the camera is doing,
stage by stage: preparing, exposing (with a bar against the shutter time for
an exposure of two seconds or more), the camera finishing the picture, each
file coming down with its size, saving, and measuring the stars. The last
picture stays on the screen until the new one is in.

## Exposure

**Exposure** is the screen for ISO and shutter speed, with the latest picture
and **Take Picture** beside them: change one, take a picture, look. Shutter
speed is in seconds. A longer shutter or a higher ISO shows more stars.

### Suggested exposure

While the mount is tracking a target, the screen has one more line: **For
Saturn: ISO 800 · 1/60 s**, the reason under it, and **Use It**, which turns
both dials there. The same suggestion is on the object's own page and, on a
wide screen, beside Tonight's List. It is advice, a place to start: take a
picture, look, and turn the dials from there. Nothing is set until you tap
**Use It**.

What it is based on depends on what the target is:

- **The Moon and the planets** are sunlit discs, so the exposure follows
  from how bright the disc is per square arcsecond, the telescope's f-ratio
  and the ISO. The Moon uses the photographer's Looney 11 rule (a full Moon
  at f/11 takes 1/ISO seconds), with half a stop more for a gibbous Moon,
  one for a quarter and two for a crescent. Each planet is scaled from that
  by its surface brightness: Venus shorter than a full Moon's, Mars about
  twice as long, Jupiter about six times, Saturn about twenty.
- **A star** gets a short shutter that keeps it round and unclipped, so its
  colour shows. It is not a deep exposure, and it is rough: how wide a star
  is depends on the air and the focus.
- **Galaxies, nebulae and clusters**: the object's magnitude does not set
  the exposure. Sky glow and how long the mount keeps a star round do. The
  suggestion is the longest shutter under the tracking limit at a high ISO,
  and a number of frames to stack, more for a big faint thing than a small
  bright one.

The f-ratio comes from the aperture and the focal length the box has (the
focal length is measured by the first plate solve). Until both are set it
assumes f/10 and says so. The tracking limit is 15 s until the box measures
how much the mount drifts under a hold, which it does not do yet.

The shutter speed and ISO are always ones this screen's dials offer, so the
suggestion can sit a stop or so from what the arithmetic asks for. When it
has to miss, it leans dark: a clipped planet is lost, a dark one can be
brightened afterwards.

## Pictures that are kept but not counted

The box keeps a count of good pictures. Some pictures are marked and left
out of that count. They are kept all the same: nothing is ever deleted.

**The first picture after a slew.** The mount is still settling and there
is stray light about, so that picture is often poor. A picture whose
shutter opened within 2 seconds of the mount's last slew, or while it was
slewing, is marked `settling` in its `.json`, and the page says so in one
line: `Mount settling: taken 1.0 s after a slew. Kept, not counted`.
Tracking, and Lock On steering the motors, are not slews.

**A picture taken through cloud.** Thin cloud does two things at once: the
same stars get dimmer and the sky gets brighter. (A lamp only brightens the
sky. A focus that has slipped only dims the stars.) The box holds each
picture's stars against the same stars in the clearest picture of this
field so far, and when they are more than 20 percent dimmer while the sky
is brighter, the picture is marked `cloud` in its `.json` and the page says
`Thin cloud: stars 25 percent dimmer. Kept, not counted` for as long as it
lasts. When the stars are gone altogether under a much brighter sky it says
`Cloud: no stars left to measure`.

The first picture of a field has nothing to be held against, so it is the
yardstick until a clearer one comes. A field starts again when the mount
slews further than a picture is wide, and when the target, the ISO or the
shutter speed changes. How much of their light the stars have, from 0 to 1,
is kept with every picture as `transparency`.

## Focusing

Under the picture the page says **Star size**: how wide the stars in that
picture are, in arcseconds. Smaller is sharper. Turn the focus knob a
little, take a picture, compare.

`Star size 8.2 arcsec, was 9.5 (12 stars)` reads: the stars in this picture
are 8.2 arcseconds wide, in the picture before they were 9.5, and the number
comes from 12 stars. The turn you just made helped. When the number goes up
instead, turn back the other way.

**What the number is.** A star's half-flux diameter: the width of the circle
round its middle that holds half its light. The box measures up to twelve of
the brightest stars and gives the middle value. A star out of focus in this
kind of telescope is a ring with a small bright core. Measuring only the
core would call it sharp. This number counts the light out in the ring too,
so it stays big until the ring has closed.

**What good looks like.** With the 8 inch Schmidt-Cassegrain (2032 mm), 3 to
4 arcsec on an average night and under 3 on a good one. 8 is well out of
focus, though the picture on a phone can still look fine.

**It needs a new picture after each turn.** The number comes from the picture
just taken, not from a live view. **Shoot Continuously** at a short exposure
(a second or two at a high ISO) keeps them coming: turn, wait for the next
picture, read the number.

**Finish with a counter-clockwise turn.** A Schmidt-Cassegrain focuses by
moving its main mirror. A counter-clockwise turn pushes the mirror up
against its own weight, so it stays where you left it; after a clockwise
turn it can sag back. If you go past focus, back off and come up to it
again counter-clockwise.

**Check it again through the night.** The focus shifts as the tube cools,
and after a big slew, when the mirror settles a little differently.

**No stars to measure** means the picture has none it can use. The box
leaves out stars that are saturated, at the edge of the picture, too close
together or in the glare of something bright, and hot pixels. A longer
shutter or a higher ISO shows more stars; a shorter one stops the bright
ones saturating. A star that trailed during the exposure reads wide too, so
keep the exposure short while focusing. A planet counts as one wide star.

Arcseconds come from the telescope's focal length (`focal_length_mm` in
Settings). Until that is set the number is in pixels of the picture at half
size, and still gets smaller as the focus gets sharper. The number is also
kept with the picture, under `measured` in its `.json`.

## What is kept with each picture

Beside every picture the box writes a small file with the same name ending
in `.json`: everything it knew when the shutter opened. The camera's own
files are never changed.

- **Time**: when the shutter was pressed, when the exposure ended, when the
  camera had the picture. UTC.
- **Camera**: ISO, shutter speed, quality, focus mode, battery, as they
  were when the shutter was pressed. A dial turned while the picture is
  still coming off the camera belongs to the next picture.
- **Optics**: focal length and aperture, and where the focal length came
  from: `label` (the number typed into Settings) or `solve` (measured from
  a solved picture, see Plate solving).
- **Mount**: both axes at the start and the end of the exposure (degrees,
  encoder steps, speed), whether it was tracking, and its track in between,
  four times a second.
- **Settling**: whether the shutter opened while the mount was still
  settling after a slew, and how long after it.
- **Cloud**: how much of their light the stars have against the clearest
  picture of the field (`transparency`), whether that is cloud, and how many
  stars say so.
- **Pointing**: RA/Dec and altitude/azimuth, when the mount is homed or
  aligned. Without that it says `null`; the encoder positions are still there
  to work it out later.
- **Lock On**: whether it was holding, the motor speeds, how far off the
  target was, and the calibration it steered by (which is also the picture's
  scale and which way up it is against the mount's axes).
- **Measured**: background, stars, the bright target, and the star size.
- **Files**: each file's size and SHA-256, so it can be shown later that a
  RAW is exactly what the camera made.

The night's `index.jsonl` has the same record for every picture, one per
line.

## Getting pictures off the box

Pictures leave over plain HTTP, so anything can copy a night:

- `/cameras/stills/files` lists the nights.
- `/cameras/stills/files/2026-10-03` lists that night's files.
- `/cameras/stills/files/2026-10-03/<name>` is one file, whole.

The page says how much room the SD card has left. Pictures stop 300 MB
short of full, with a line that says so: the box keeps its settings and its
logs on the same card.

## Plate solving

**Solve Pictures** has the box work out, from the stars in each picture,
exactly where the telescope pointed: the centre's RA and Dec, how much sky
the picture covers, and which way up it is. It takes a few seconds on the
box.

It needs stars: open sky, the mount tracking, and an exposure long enough
to show a dozen of them (a second or more at a high ISO). With too few it
says so, and a longer shutter or a higher ISO is the fix.

Every solved picture is also an alignment photo: it joins the mount's
plates, the same ones Align by Phone Photo collects, so a few of them spread over
the sky align the mount. **Alignment Photos** shows them and the fit. For a
picture to count, the mount must have a home set.

The answer is written beside the picture, in `<name>.solve.json`.

**A finder picture** is one quick picture solved to check the aim before a
series starts (`Controller.StillCamera.finder()`, from a plan or IEx; set a
short exposure at a high ISO first). It goes ahead of every picture waiting
to be solved, and it has 30 seconds. When it isn't solved by then the box
stops that solve, says `the finder solve missed its deadline`, and gets on
with the next one. A series need not wait on it: with `shoot_anyway: true`
the answer is the model's aim as it stands.

**The first solved picture measures the focal length.** The number on the
tube is a label: an 8 inch Schmidt-Cassegrain says 2032 mm, and its
pictures say 2084. From how much sky a pixel covers and how big a pixel is,
the box works out the real one, keeps it in Settings as `focal_length_mm`,
and uses it from then on (star size in arcseconds, the scale the solver is
told to expect). Put another focal length in Settings (another telescope,
a reducer) and that one is used, until the next solved picture measures it.

## Lock On

Lock On holds the target still in the picture by driving both motors, however
the mount is set up: no polar alignment, no level tripod.

1. **Calibrating** (about a minute). Two pictures with the motors still
   measure how the target drifts. Then each axis is nudged once (5 seconds at
   4×) to see how it moves the picture.
2. **Holding.** Every picture sets both motor speeds: the ones that cancel
   the drift, plus a gentle pull back toward the middle.

It says what it's doing in one line, here and on every page:

- **Target hidden**: a cloud, the edge of a door. The motors keep cancelling
  the drift, so the target is still there when it comes back. After five
  minutes they stop, and it keeps watching.
- **Waiting for pictures**: no new picture for 45 seconds. The motors stop
  until pictures come back; the lock carries on then.
- **Pad in use**: a hand on the game pad. It steps aside until you let go.
- **Off**: released, or STOP was pressed anywhere.

After the mount is moved (the clutches, the tripod), release and lock on again
so it calibrates afresh.

**Lock On the Bright Target** holds the middle of the Moon or a planet. **Lock
On a Star** holds the brightest star in the picture (best at a high ISO and a
second or so).
