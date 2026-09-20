# Stamp a Box

Put a card in this machine, answer five short screens, and write a bootable
Observatory onto it. Then put the card in a Raspberry Pi, power it up, and the
telescope has its own computer instead of borrowing your laptop.

Each screen asks one thing, and tapping the answer is also the way forward.
Going back changes nothing you have already said.

## 1. The card

Only removable disks are listed. The machine's own drive cannot appear here,
so a mistaken tap cannot take your laptop out. Everything on the card you
choose is erased, and the card is named again in the confirmation.

The card is checked once more in the moment before writing. If you pull it
while an image is building, nothing is written and the page says so.

## 2. What it does

Three shapes, because not every box needs everything. The chips on each row
are the parts that land on the card.

- **Observatory** is the whole thing: mount, web, camera, pad. A telescope you
  plug a phone into.
- **Mount Only** is the driver and the cluster plumbing. Small and quiet, and
  enough to move the telescope. It runs on anything down to a Pi Zero 2 W.
- **Eyes** is camera and video with no mount: a second box watching a telescope
  that something else is driving.

## 3. The machine

Picking a job suggests the machine that suits it, marked on the row. Override
it and the override sticks, even if you go back and change the job.

Video is the thing that decides this. A Pi 4 or 5 encodes it without complaint;
a Pi 3 does stills; a Zero 2 W is for a box that only moves the mount.

## 4. The network

Give it your Wi-Fi and it joins that network. Leave the fields blank and it
brings up a network of its own, which is the only way to reach a box in a field
with no signal: connect your phone to it and configure it from there.

Either way it falls back to its own network when yours is not there, so a box
is never unreachable. Once it is up it answers at the name you gave it, with
`.local` on the end.

### The door

A **development** box leaves it open. You get a shell over SSH, and new firmware
can be pushed over the network, so a box bolted to the mount never needs its
card pulled again. Anyone on your network holding your SSH key can open a shell
on it.

A **production** box is closed. No shell, no firmware over the network, quiet
logs. To change it, stamp the card again.

Either way the keys look after themselves. The public keys of the machine doing
the stamping are baked into the box, so there is nothing to copy or type in. If
that machine has never had an SSH key, one is made for it.

## 5. Writing

The last screen is the whole plan in four lines, then one key.

Writing a card takes a couple of minutes. The first build for a given machine
takes about ten, because the whole system is compiled. So the page tells you
what it is doing the entire time: which of the four steps it is on, what that
step is doing right now, a bar when there is a real percentage to show, and the
tools' own output underneath if you want to watch it turn over.

If a step fails it says which step and why in plain words, and stops. A
half-written card has to be written again; it will not boot.

## Administrator rights

Writing directly to a disk needs them. If you press the key and nothing
happens, run `sudo -v` in a terminal once, then try again.
