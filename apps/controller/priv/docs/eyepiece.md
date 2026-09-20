# Eyepiece: what the tube sees

A circular field of view with the stars that are in it, a crosshair at the
centre, and whatever the mount is holding ringed in green. North is up, east is
to the left, the way it looks through a star diagonal.

The field comes from the encoders, four times a second. Let go of tracking and
it drifts west, because the sky keeps moving and the mount does not. Nudge and
it steps. Hold something and it stays put.

## The simulator's hidden truth

A simulated mount that is perfectly aligned teaches nothing: every goto would
land dead centre and Star Align would have no work to do. So the simulator is
given a **truth**: a polar axis a couple of degrees off the pole and encoder
offsets that are not quite zero. That truth decides what the eyepiece shows.

So on the simulator this page is honest. Slew to a star and it lands off
centre, exactly as it would outside with a mount set down in a hurry. Nudge it
to the crosshair, tap **On It**, do it twice more, and the software works out
the geometry from your three answers. After that its gotos land where they
should, because it has discovered the truth rather than been told it.

The truth is only ever read by this page. It never reaches the pointing model,
the star alignment or the tracker. If it did, the alignment would be cheating
and would prove nothing about the real mount.

## On a real mount

There is no camera in the eyepiece, so nothing here is a photograph. The page
draws where the software **believes** the tube is pointing, and the line under
the field says so. It is still useful: it shows what the model thinks, which is
what every goto is about to act on.

## The arrows

The arrows move the picture the way they point. That sounds obvious and it is
not: on a crooked mount, turning the Dec axis does not move the field north,
because the axis itself is tilted. So rather than trust the compass, the page
turns each axis a little on paper, sees which way the stars would slide, and
picks the one that comes closest to the arrow you pressed.

## What it does not show

The catalogue stops at magnitude 6, about five thousand stars. A real eyepiece
at high power shows far more, and often none of them are in the catalogue. That
is why the narrowest field here is two degrees rather than the half a degree a
real eyepiece gives: any tighter and the view is usually empty, which would be
a true picture but a useless one.
