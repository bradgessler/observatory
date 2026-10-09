# Telescope camera

A USB camera in the telescope's focuser, in place of an eyepiece (the SVBONY
SV105 or any "UVC" camera that works without a driver), plugged into the box.
It sees what the telescope sees, so it is the telescope's viewfinder. The box
finds it by itself; the page says its name once it does.

## Focus it

Tap **Live View**: the camera takes frame after frame and measures each one.
The picture is brightened so faint stars show. Turn the focuser slowly and
watch the number under **Focus**: it's the half-flux radius (HFR) of the
stars, in pixels, the radius inside which half a star's light falls. Smaller is sharper. The line under it is the last minute of readings,
so you can see whether the last turn helped. The close-up is the brightest
star in the frame; at best focus it's a tight dot.

If there are no stars: take the cap off, point away from the Moon, and try
a longer exposure or more exposures stacked (**Exposures Per Frame** on the
camera's Settings). A planetary camera like the SV105 is made for bright
things, so the faint stars a plate solver needs take a second or so of
exposure, or several exposures stacked.

The line under the camera's name says the size and format frames are taken
in: the most pixels the camera has, raw rather than JPEG when it offers both
(JPEG smooths faint stars away). If a frame fails in that format, the next
one uses the camera's own default.

## Video

**Video**, on the camera's Settings page, hands the camera to the same video
the Observatory Camera uses. It plays on a phone (Safari on an iPhone
included), a few seconds behind. It's for aiming and rough focus by eye: the
focus number and Live View pause while it's on, because only one thing can
read the camera at a time. The
exposure sets the frame rate, so at 500 ms it's two frames a second; drop
it to 100 ms on a bright star for smooth video.

## Auto Align

Tap **Auto Align**. It takes a frame, works out where in the sky it points
(a [plate solve](/docs/glossary#plate-solve), on the box, with no internet),
moves the mount a little, and repeats, spreading the frames over a patch of
sky about 30° across. When four agree, they become the
[alignment](/docs/align) and Go To uses them.

The moves are small: 15° on RA and 10° on Dec at most, from wherever you
started. Start with the telescope pointed somewhere sensible, well above
the trees. STOP ends it anytime.

The first frame takes the longest to plate solve (up to a few minutes on the
Pi), because nothing says where to look yet. After that each one takes
seconds.

## When it can't see stars

Every frame is checked before the plate solver sees it: too bright (the
Moon, a light, a lit wall), no stars (clouds, a wall, trees, the cap),
blurry blobs (out of focus, or something close up), or only a few stars. A
frame with only a few stars is taken again with more exposures stacked.
After three frames in a row it can't place, it stops moving the mount and
says what it saw. Point the telescope at open sky with the game controller or
the touchpad, then tap **Continue**.
