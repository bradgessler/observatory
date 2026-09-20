# Stamp a Box

Put a card in this machine, say what the box is for, and write a bootable
Observatory onto it. Then put the card in a Raspberry Pi, power it up, and the
telescope has its own computer instead of borrowing your laptop.

## The card

Only removable disks are listed. The machine's own drive cannot appear here,
so a mistaken tap cannot take your laptop out. Everything on the card you
choose is erased, and the page says which card that is before it starts.

The card is checked again in the moment before writing. If you pull it while
an image is building, nothing is written and the page says so.

## What the box is for

Three shapes, because not every box needs everything:

- **Observatory** is the whole thing: the mount driver, the web controller, the
  camera and the game pad. A telescope you plug a phone into.
- **Mount Only** is the driver and the cluster plumbing. Small and quiet, and
  enough to move the telescope. It runs on anything down to a Pi Zero 2 W.
- **Eyes** is the camera and video with no mount: a second box watching a
  telescope that something else is driving.

## Development or production

A **development** box leaves the door open. You get a shell over SSH, and new
firmware can be pushed over the network, so a box bolted to the mount never
needs its card pulled again. Anyone on your network holding your SSH key can
open a shell on it.

A **production** box is closed up. No shell, no firmware over the network,
quiet logs. To change it, stamp the card again.

Either way the keys look after themselves. The public keys of the machine
doing the stamping are baked into the box, so there is nothing to copy or type
in. If that machine has never had an SSH key, one is made for it.

## How it gets on a network

Give it your Wi-Fi and it joins that network. Leave the fields blank and it
brings up a network of its own, which is the only way to reach a box in a
field with no signal: connect your phone to it and configure it from there.

Either way it falls back to its own network when yours is not there, so a box
is never unreachable. Once it is up it answers at the name you gave it, with
`.local` on the end.

## While it works

Writing a card takes a couple of minutes. The first build for a given machine
takes about ten, because the whole system is compiled. So the page tells you
what it is doing the entire time: which of the four steps it is on, what that
step is doing right now, a bar when there is a real percentage to show, and
the tools' own output underneath if you want to watch it turn over.

If a step fails it says which step and why in plain words, and stops. A
half-written card has to be written again; it will not boot.

## Administrator rights

Writing directly to a disk needs them. If you press the key and nothing
happens, run `sudo -v` in a terminal once, then try again.
