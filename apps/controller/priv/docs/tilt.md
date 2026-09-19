# Tilt

Hold the big button and tilt the phone. The mount follows; more tilt is
faster; let go and it stops.

## Why it exists

When your eye is on the eyepiece you have one thumb and no view of the
screen. A dead-man button plus tilt needs neither.

## How it works

* The way you hold the phone when you press is "still". Tilting away from
  that moves; a 5° null zone means a shaky hand does nothing.
* The phone's orientation sensor is read in the browser — it is the one
  thing the server cannot read — and only a plain direction and strength go
  to the server, four times a second. Nothing arriving for 900 ms stops the
  mount.
* iPhone: the browser asks for the sensor once, from your tap, and only over
  **HTTPS** (use the tunnel address). If you said no, close the tab and open
  the page again; if it still says no, Settings › Safari › Advanced › Website
  Data → remove this site.
