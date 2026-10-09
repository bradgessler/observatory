# Devices

How the software finds the telescope, and what to do when it doesn't.

## Adding hardware

Everything is plugged in and found by itself: there's nothing to add by hand.
**Devices** (under System) lists each piece of hardware by what it's for, says
what was found and what it's doing, or, when there's none, how to add one.

| For | What to plug in | Where | Its page |
|---|---|---|---|
| The mount | The EQDIR cable (an FTDI USB serial cable) into the mount's HAND CONTROL port | This machine or a box | Devices, then any of the Controls |
| The telescope camera | A USB camera that speaks UVC (the SVBONY SV105C, most "planetary" cameras), in the focuser in place of an eyepiece | This machine or a box | [Telescope Camera](/docs/scope-camera) |
| The observatory camera | A webcam pointed at the mount | A Mac for now: its own camera or a USB webcam (stills need `imagesnap`) | [Observatory Camera](/docs/watch) |
| A game controller | A USB game pad | This machine or a box | Game Controller |
| Power | Nothing: a box watches its own supply | A box | Devices, Power |

A camera plugged into a box is found within a few seconds and becomes the
telescope camera; the Mac shows it too, through the box. While you drive
the scope on the keypad, what the telescope camera sees is beside the
strips (the viewfinder), and on the telescope camera's page **Move the
Scope** nudges it, so centering and looking happen in one place.

## How connecting works

The mount talks over an EQDIR cable: a USB-to-serial lead (FTDI chip) that
plugs into the mount's **HAND CONTROL** jack. No hand controller is involved.

Every 3 seconds the software lists the serial ports the computer sees. Any
FTDI port gets a driver, which asks the mount for its firmware version. If the
mount answers, it shows up on the keypad and the sky page within a few
seconds; the simulator (if one was running) goes away. Pull the cable and the
driver goes away too.

**Scan Now** does that check immediately. **Connect** starts a driver on a
port the auto-detector didn't recognize — a different USB-serial chip, for
example. Drivers started that way have a **Disconnect** button.

## "Port appears, but not answering"

The computer sees the cable but the mount isn't replying. In order:

1. **Power.** The mount's LED must be steady. 11–16 V, 4 A, centre-positive on
   the locking plug. Reversed polarity looks like a dead short: no LED, and
   the supply's voltage collapses.
2. **Which jack.** HAND CONTROL is the 8-pin RJ45; AUTO GUIDE is the 6-pin
   RJ12 next to it and looks similar.
3. **Power-cycle the mount**, then Scan. The motor board can sulk after a bad
   command.
4. **Another program on the port.** A serial terminal or a test script holding
   the port blocks us. Quit it and Scan.

## "No serial ports at all"

The computer doesn't see the cable.

- Try another USB port; skip the hub; try the cable in a different machine.
- On a Mac the port is named `cu.usbserial-…`; on Linux `ttyUSB0`.
- On Linux your user needs to be in the `dialout` group.

## More than one

Every cable gets its own driver, named after its port. The keypad and sky
pages show a picker when there's more than one. Mounts attached to other
machines on the same network appear too, tagged with that machine's name,
once this machine has joined them (below).

## A Mac next to a box

A box can always be joined. A Mac running the software from source does not
join one by itself: started with `mix phx.server` it keeps to itself, is not a
node of the cluster, and does not look for boxes (Devices has no Boxes list).

Started as a node, with `OBSERVATORY_CLUSTER=1 mix phx.server`, Devices lists
the boxes on the network and **Connect** joins one. The box's mount and
cameras then show on the Mac's pages, its frames are copied to the Mac and
its photos can be solved there. A box connected once is joined again each
time the Mac is started this way; **Disconnect** on Boxes forgets it.

A simulator is listed only on the machine that runs it. A Mac with nothing
plugged in runs a simulated mount and simulated cameras so that its pages
work. They never show on a box it has joined: a box with no camera says it
has none.

## Phones

Phones connect to this computer's web address, shown on the Devices page.
Same Wi-Fi: `http://<address>:4000`. From anywhere: the tunnel URL, if one is
running. Location and camera features need the HTTPS (tunnel) address on
iPhones.
