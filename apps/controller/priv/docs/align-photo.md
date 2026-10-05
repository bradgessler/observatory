# Align by Photo

Hold your phone to the eyepiece and take a photo. The machine finds the
stars in it and matches them to a star catalog (a [plate solve](/docs/glossary#plate-solve)),
so it knows exactly where the tube was pointing, and pairs that with where the
motors were the moment you chose the photo.
Two photos with the RA axis swung between them say how the polar axis
really sits: which bolt to turn, which way, and how far. No Polaris, no
alignment stars to name.

## What to do

1. **Set home, if you like.** Counterweight down, tube along the polar
   axis, by eye, then *Set Home Here* on [Setup](/docs/setup#home-position).
   This arms the soft limits; it does not need to be accurate, and the photos
   work without it as long as you move the mount only with its motors.
2. **Point anywhere with stars** in a low-power eyepiece (a field of a
   fifth of a degree to three degrees across).
3. **Take Photo.** Hold the phone's camera square to the eyepiece until the
   circle of sky fills the middle of the frame. Night mode or a 1 to 3 s
   exposure helps; a phone adapter helps more. Keep the telescope still until
   you tap *Use Photo*: that is the moment the motors are read.
4. **Move on straight away.** Swing the RA axis at least 20° (30° to 60° is
   better) with any control and take the next photo. Photos are plate solved
   in the background, oldest first; the list says which are waiting, which is
   solving and where each one landed. The page says how far RA has turned
   since the last photo.
5. **Read the Polar Axis card** as the photos land, turn the bolts it
   names, then **Start Over**: the photos so far describe the mount as it
   was. Repeat until the error is small enough for what you want to do.
6. **Use This Alignment.** The photos become the mount's alignment points
   (replacing any stars), and Go To goes through them.
7. **Say where the counterweight is**, if home is not set. A
   **Counterweight** card appears: tap **Below Level** or **Above Level**
   for the mount as it stands. Both sides of the mount see the same sky, so
   no photo can say which side the counterweight is on, and Go To picks its
   side of the pier by it. [Why it asks](/docs/setup#counterweight).

## What the numbers mean

* **0.9° from the pole**: the angle between where the polar axis (the RA
  axis) points and the celestial pole the sky turns about.
* **Altitude: Raise 0.5°**: tilt the polar axis up by that much, with the
  altitude (latitude) bolts. *Lower* tilts it down.
* **Azimuth: Turn 0.8° west**: turn the whole mount on its base so the end
  of the polar axis that points at the pole moves west, with the azimuth
  knobs. The number is degrees of azimuth, which is what the knobs turn.
* **±0.2°**: the margin, about 95%. It comes from how well the photos pin
  the axis down (how far apart they are) and how far off one photo's center
  can be: 3′ is assumed, and when three or more photos disagree by more,
  their own disagreement is used. Two photos always fit exactly, so a third
  is what checks them.
* **Drift, up to 0.24′ a minute**: how fast a star can wander out of the
  eyepiece with plain sidereal tracking at this polar error, at worst.
  Tracking through the alignment (after Use This Alignment) runs both motors
  and takes it out; the field still rotates slowly.
* **off by 1.2′** next to a photo: how far that photo sits from the fit.
  One big number among small ones is a photo taken with the phone askew or
  the telescope moving; remove it with ✕.
* The picture shows the same thing facing the pole: the cross is the pole,
  the dot is where the axis points, the dashed ring is the margin.

## When a photo does not solve

* **Too few stars (needs about 15)**: the solver found fewer than about
  fifteen points of light, and with fewer it never finds a match. Hold the
  phone steadier, use a longer exposure, or point at a richer patch of sky.
* **Stars, but no match**: usually a field much smaller or larger than a
  fifth of a degree to three degrees, or trees and glow mistaken for stars.
* **Telescope was moving**: the photo was chosen while the mount slewed, so
  its motors and its sky do not belong together. It is kept, but not used.

*Retry* queues a photo again; *✕* removes it.

## Where it solves

The first of these that can:

1. **This machine**, when it has astrometry.net and its index files.
2. **Another machine in the cluster** that has them: the photo travels over
   the network, the answer comes back. A box with no solver uses the Mac.
3. **nova.astrometry.net**, when `NOVA_API_KEY` is set: online, 30 to 90 s.

The page says which. Photos are plate solved several at a time on a Mac (one
fewer than its cores), one at a time on a box; they are kept in
`~/.observatory/plates`, one folder per set, so a restart loses nothing and
a photo that failed can be looked at the next day.

To set up a Mac:

    brew install astrometry-net jpeg-turbo
    mkdir -p ~/.observatory/astrometry && cd ~/.observatory/astrometry
    for n in 4107 4108 4109 4110 4111 4112 4113 4114; do
      curl -O http://data.astrometry.net/4100/index-$n.fits
    done
    printf 'inparallel\ncpulimit 60\nadd_path %s\nautoindex\n' "$PWD" > astrometry.cfg

Those Tycho-2 index files (337 MB) cover fields from about 0.3° to 5.6°
across. Solving uses four small programs and no Python, the same on a Mac
and on a box: `djpeg` turns the JPEG grey, `an-pnmtofits` makes it FITS,
`image2xy` finds the stars, `solve-field` matches them. With the mount's
rough pointing as a hint a solve takes well under a second of work; without
one, up to a minute.

A box keeps its index files on `/data/astrometry` (they are too big for the
image) and solves there, with no Mac and no internet. On a Pi 3 a phone
photo takes about 10 to 20 seconds with a hint.

**The eyepiece, cut out first.** A phone at an eyepiece sees a bright disc
(moonlight, a lit sky) with a hard rim, in a black border, and a star finder
counts the rim and the grain as thousands of stars. So the photo is cut to
the eyepiece first:

* the disc found from a small copy;
* its rim shaved off;
* the moonlight across it taken away;
* everything outside it made black.

The center of what is left is the center of the eyepiece, so the solved
center is where the tube points. This runs in Elixir everywhere; on the first
night's 15 photos it solves the same 10 the old ImageMagick way did, in a
fraction of the time.

**A match below the horizon is refused.** At the moment and place a photo
was taken, a solve that lands below the horizon is a false one, however
confident the solver is. The page says "take it again".

## Honest limits

* The center of the photo is taken as where the tube points. A phone held
  off-center on the eyepiece moves that by a few arcminutes, which is what
  the margin allows for.
* Which moment a photo belongs to: when the mount is tracking, the moment
  you chose it; when it is still, the moment the shutter opened (from the
  photo itself, or the moment you chose it if the photo does not say). A
  photo more than 5 minutes older than that is refused.
* JPEG only for now (an iPhone set to Camera, Formats, Most Compatible, or
  any photo a browser hands over from the camera).
* The catalogs are J2000; the sky turns about the pole of today, about
  0.15° away in 2026. The readout compares with today's pole. Refraction
  (about 1′ at the pole's altitude here) is not corrected.
* Cone error (a tube not square to the Dec axis) and axes that are not
  perpendicular are not modelled. They show as photos that disagree.
