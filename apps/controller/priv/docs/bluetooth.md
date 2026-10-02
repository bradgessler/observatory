# Bluetooth

The box's own Bluetooth radio: what it hears, and later, what it pairs with
(game controllers) and reads from (batteries). This page exists only on a box built
with a Bluetooth system image; a Mac leaves Bluetooth to macOS.

## The stack

The standard Linux stack, BlueZ: `dbus-daemon` and `bluetoothd`, started and
watched from Elixir. The Pi's radio sits on its mini UART, and the kernel
attaches it by itself as `hci0` at boot.

Bluetooth is a convenience on a telescope, never a dependency. If the stack
stops (the daemon dies, the image has no BlueZ), the box notes why on this
page and starts it again after 5 s, 30 s, 2 min, then every 10 min. The
mount, the Wi-Fi and the game controller keep going the whole time.

## At power-on

A Pi 3's Bluetooth and Wi-Fi are one chip sharing one 2.4 GHz antenna. Joining
Wi-Fi comes first, so Bluetooth waits 20 s after power-on with its radio idle.

The kernel attaches the radio 1.5 s into boot, while other drivers are loading,
and on a Pi 3 that attach sometimes loses a reply from the chip. The kernel
then shows `hci0`, but it never finished setting up. The box watches for this:
`hci0` with no working adapter for 20 s gets its driver detached and attached
again, which is what unplugging and replugging would do. Up to three times a
boot; after that the page says the radio did not come up, and **Restart Radio**
tries again from the start.

A board with no Bluetooth radio at all says **No radio**, and a USB Bluetooth
adapter plugged in later is picked up within a minute.

## Nearby

Every Bluetooth Low Energy device heard in the last two minutes, strongest
first: its name if it gives one, its address, and the raw data it broadcasts.

- **Maker** is manufacturer data, by the company's Bluetooth ID. Batteries and
  sensors often put their readings here.
- **Service** is service data, by service UUID.
- **Random address** means the device changes its address from time to time,
  as most phones do.

A device that is asleep, or a game controller that is not in pairing mode,
does not advertise and does not show until it does. Pressing a button on it usually
wakes it.

## Scanning

The box scans **passively**: the radio only listens, about 10% of the time.
Measured on a Pi 3 on Wi-Fi, that costs nothing noticeable (16 to 23 ms ping,
against 14 to 19 ms with Bluetooth off), and every reading a device broadcasts
still arrives.

**Active Scan** asks each device for its scan response, where some put their
name, for 20 s. It more than doubles Wi-Fi latency while it runs (44 ms), so
it is a key you press, not a mode. Names learned are kept, so a device named
once stays named.

From IEx on the box: `Firmware.Bluetooth.status()`,
`Firmware.Bluetooth.active_scan(20_000)`, `Firmware.Bluetooth.restart()`.

## What is kept

Pairings, the names learned and the adapter's identity live in
`/data/bluetooth` on the SD card, so they survive a reboot and a firmware
update. The flight log records the Bluetooth state every sample (`bt=`).
