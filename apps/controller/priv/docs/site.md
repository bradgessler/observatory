# Site

Where the telescope stands and what time it is. The phone in your hand knows
both better than the box does, so the Site page takes them from it.

## Latitude and longitude

**Use This Phone's Location** asks the phone for its position, once, when
you tap it. Stand by the telescope. The accuracy is shown beside it: a few
metres outdoors is typical, and a few kilometres would still point a
telescope well. Typed coordinates work too (decimal degrees, north and east
positive).

What the phone reports is saved as the site, which the sky map, Go To and
the pointing model all use. Without a site they assume 0°, 0°, and the Modes
strip says *No site* on every page.

On a page served over plain http (a box, usually) the browser won't share
the phone's location at all; type the numbers instead. The iPhone Compass app
shows them.

## Equatorial mount

- **Polar axis altitude** is your latitude: the number to set on the mount's
  latitude scale, so the polar axis (the RA axis) tilts up at the pole.
- **Aim at** says which pole. In the north, Polaris sits about 0.7° from the
  true pole.
- **Sidereal time** is the right ascension on your meridian right now: the
  sky's own clock, which runs four minutes a day fast.

## Hand controller (NexStar)

What a Celestron hand controller asks for when it starts, in its own terms:
the time (24-hour), **Standard Time or Daylight Saving**, the time zone as
hours from UTC in *standard* time, the date, and latitude and longitude in
degrees and minutes. Enter them as shown. The phone knows whether daylight
saving is on, so you don't have to.

## Time

The box's clock in UTC, and whether the network set it. A box in a field has
no internet time, so the first phone to open this page sets its clock when
the two disagree by more than 2 seconds; the event log records it. A Mac's
clock is never changed.
