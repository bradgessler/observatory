# Words

One word for each thing, the one you would look up elsewhere, used the same
way on every page. Each entry says what it means, the words this software
doesn't use for it, and where it is explained properly.

## The telescope

### Telescope

The whole instrument: the mount, the tube on it, and its cameras.
Not: *scope* (the Scope page keeps its name: it draws the whole telescope).

### Mount

The motorized base that turns the tube: here a Sky-Watcher EQ6-R, a German
equatorial mount. It is what moves, and what the software talks to.
Not: *scope*. More in [Scope](/docs/scope).

### Tube

The optical tube that collects the light, with the eyepiece or the Telescope
Camera at its back end.
Not: *OTA*, *scope*.

### RA axis

The axis the mount turns to follow the sky (right ascension). It is meant to
point at the celestial pole, so when the talk is about where it points
(polar alignment, the altitude bolt) it is called the **polar axis**.
Not: *RA (polar) axis*, *polar* on its own. More in [Orb](/docs/orb).

### Dec axis

The second axis (declination), square to the RA axis, with the tube on one
end and the counterweight on the other. It swings the tube toward or away
from the pole.
Not: *dec axis*, *DEC*. More in [Orb](/docs/orb).

### Encoders

The step counters in each motor. They say how far each axis has turned since
the mount was switched on, not where it points: that is what the home
position and the alignment are for.

### Home position

Counterweight straight down, tube along the polar axis: where both axes read
0°. **Set Home Here** tells the mount it is standing there now.
Not: *zero*, *zeroed*, *homed*, *park*. More in [Setup](/docs/setup#home-position).

### Soft limits

How far each axis may turn from the home position before the mount stops
itself, so it never winds up its cables. Armed once home is set.
More in [Setup](/docs/setup#home-position).

### Location

Where the telescope stands: latitude and longitude, plus the clock. The sky
map, Go To and tracking all work from it.
Not: *site*. More in [Location](/docs/location).

### Meridian flip

Swinging the tube to the other side of the mount, so a target past the
meridian can be followed without the counterweight rising.
More in [Sky Map](/docs/sky#the-meridian-and-the-flip).

## Pointing

### Go To

The mount slews to a named object by itself.
Not: *GoTo*, *goto*, *move to*. More in [Sky Map](/docs/sky#go-to).

### Slew

A fast move under motor power: a Go To, or a key held down.

### Tracking

Turning the mount so a target stays still in the eyepiece while the sky
turns. **Sidereal tracking** is the mount's own: the RA motor alone at the
sky's rate. **Tracking a target** runs both motors through the alignment, so
a crooked polar axis doesn't matter; it starts after a Go To, or with
**Track What I'm On**.
Not: *hold*, *holding*. More in [Align by Stars](/docs/align#tracking-with-a-crooked-axis).

### Sidereal rate

The speed the sky turns: once in 23 h 56 min. On the rate keys it is 1×; 800×
crosses the sky.

### Alignment

What the software has measured about how the mount really sits, fitted from
alignment points. Three or more that agree make the telescope **aligned**,
and Go To lands.
Not: *lock*, *locked*, *line-up*, *lined up*. More in [Align by Stars](/docs/align).

### Alignment point

One moment the software knew exactly where the tube pointed: a star you
centered and tapped **Centered** on, or a photo or frame that was plate
solved.
Not: *sample*, *star* (when it is a photo).

### Centered

The key for "it's in the middle of the eyepiece right now". It adds an
alignment point. Other software calls this a *sync*.
Not: *On It*, *That's it*, *Sync*. More in [Sky Map](/docs/sky#go-to).

### Pointing model

The arithmetic behind the alignment: where the polar axis really points, where
the encoders started counting, which way each motor turns.
Not: *the fit*, *the geometry*. More in [Control Stack](/docs/stack).

### Polar alignment

Turning the mount's altitude and azimuth bolts until the polar axis points at
the celestial pole. Not needed for looking here; it matters for long
exposures.
More in [Align by Photo](/docs/align-photo).

### Plate solve

Working out exactly where a photo or frame points by matching its stars
against a star catalog. It needs no alignment and no idea where it points.
Not: *solve* on its own. More in [Align by Photo](/docs/align-photo#where-it-solves).

### Auto Align

The Telescope Camera does the alignment by itself: it plate solves a frame,
moves the mount a few degrees, and repeats until four agree.
Not: *Find Where It's Pointing*. More in [Telescope camera](/docs/scope-camera#auto-align).

### Margin

How far a Go To may land from the target: twice the alignment's rms, so about
95% of Go Tos land inside it. Shown as the ring around the crosshair on the
sky map.
More in [Sky Map](/docs/sky#go-to).

### Arcminute

A sixtieth of a degree, written ′. The full Moon is about 30′ across; a
low-power eyepiece shows about 60′.

### Field of view

How much sky the eyepiece or a camera shows, in arcminutes or degrees. Short:
*field*.

### Modes

Anything kept between nights that changes where the telescope points: a
flipped axis sign, reversed tracking, a sync offset, a site typed by hand.
While one is on, every page says so.
More in [Setup](/docs/setup#modes).

### Sync offset

A one-star correction from before alignments existed, kept until cleared. It
shows in Modes.
More in [Setup](/docs/setup#modes).

## Moving the mount

### Rate

Speed, as a multiple of the sidereal rate: 1× creeps with the sky, 8× and 64×
center things, 400× and 800× cross the sky.
Not: *speed* on a key.

### STOP

Stops both axes at once and ends tracking. It is on every page and on the
game controller.

### Game controller

A USB game controller plugged into the machine running the server, read by the
server, never the browser.
Not: *pad*, *game pad*, *gamepad*. More in [Game controller](/docs/game-controller).

### Dead man's switch

A control that has to be held for anything to move: the game controller's
trigger, and every held key. Let go, or lose the connection, and the mount
stops within a second.
Not: *dead-man*. More in [Game controller](/docs/game-controller#the-trigger-is-a-dead-mans-switch).

### D-pad

The four-way pad on a game controller, and the four arrows on the Plain
Keypad and Eyepiece pages.

## Cameras

### Telescope Camera

The camera in the focuser, in place of an eyepiece: it sees what the telescope
sees, and is used for focusing and plate solving.
Not: *scope camera*, *finder*. More in [Telescope camera](/docs/scope-camera).

### Observatory Camera

The camera watching the mount, so you can see it move from anywhere.
Not: *Watch*, *webcam*. More in [Observatory camera](/docs/watch).

### Frame

One numbered image from a camera, the thing that is measured, plate solved
and kept. A Telescope Camera frame can be several exposures stacked.
Not: *picture*.

### Exposure

How long the camera's sensor collects light for one reading, and that
reading itself.

### Stack

Several exposures averaged into one frame: fainter stars, less noise, and
that many times as long. **Exposures Per Frame** sets how many.
Not: *frames per picture*.

### Still

An Observatory Camera frame taken on its own every few seconds, when video is
off.

### Photo

A picture taken with your phone: through the eyepiece for Align by Photo, or
of the tree line.

### Live View

The Telescope Camera taking frame after frame and measuring each one, for
focusing.
More in [Telescope camera](/docs/scope-camera#focus-it).

### Video

A smooth stream to the phone, a few seconds behind. Nothing in it is
measured.
Not: *live video*, *stream*. More in [Observatory camera](/docs/watch#stills-and-video).

### Half-flux radius

The focus number: the radius, in pixels, inside which half a star's light
falls. Smaller is sharper. Short: *HFR*.
More in [Telescope camera](/docs/scope-camera#focus-it).

## The box and the network

### Box

A Raspberry Pi running Observatory from an SD card, at the telescope.
Not: *device*, *Pi* when the box is meant. More in [Stamp a Box](/docs/provision).

### Mac

The computer that stamps SD cards, copies kept frames off the boxes, and can
drive a mount itself.

### This machine

The computer serving the page you are looking at: a box or the Mac.
Not: *computer*, *host*.

### EQDIR cable

The USB-to-serial lead into the mount's HAND CONTROL jack: how the software
talks to the mount.
Not: *telescope cable*. More in [Devices](/docs/devices).

### Simulator

A stand-in mount that speaks the real protocol, so every page works with
nothing plugged in.
Not: *sim*. More in [Eyepiece](/docs/eyepiece#the-simulators-hidden-truth).

### SD card

The card a box boots from and keeps frames on.
Not: *card* on its own. More in [Queues](/docs/queues).

### Hostname, SSID, access point

The standard network terms, used as your router uses them.
More in [Network](/docs/network).

### Node

A machine's name in the cluster, like `telescope@observatory.local`. Boxes and
the Mac join each other by it.
More in [Devices](/docs/devices).
