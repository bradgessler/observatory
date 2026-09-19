# Devices

How the software finds the telescope, and what to do when it doesn't.

## How connecting works

The mount talks over an EQDIR cable: a USB-to-serial lead (FTDI chip) that
plugs into the mount's **HAND CONTROL** jack. No hand controller is involved.

Every 3 seconds the software lists the serial ports the computer sees. Any
FTDI port gets a driver, which asks the mount for its firmware version. If the
mount answers, it shows up on the keypad and the sky page within a few
seconds; the simulator (if one was running) goes away. Pull the cable and the
driver goes away too.

**Scan now** does that check immediately. **Connect** starts a driver on a
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
machines on the same network appear too, tagged with that machine's name.

## Phones

Phones connect to this computer's web address, shown on the Devices page.
Same Wi-Fi: `http://<address>:4000`. From anywhere: the tunnel URL, if one is
running. Location and camera features need the HTTPS (tunnel) address on
iPhones.
