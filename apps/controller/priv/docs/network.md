# Network

How a stamped box is reached, and how to change it. This page exists only on
a box; the Mac that stamps SD cards leaves its network to macOS.

## One radio, two modes

A Raspberry Pi has one Wi-Fi radio. At any moment it is either a **Wi-Fi
client** on a network you gave it, or its own **access point**. Never both.

- **Access point**. The box is a Wi-Fi network whose SSID is its hostname.
  Join it and open `http://<hostname>.local` or `http://192.168.24.1`. The box
  hands out addresses from `192.168.24.10` to `.250` and answers every DNS name
  with itself, so any address typed into a browser reaches it. No router or
  internet is involved.
- **Wi-Fi client**. With a client network saved (stamped in, or joined from
  this page), the box joins it and takes an address by DHCP. It is then at
  `http://<hostname>.local` on that network.

## At power-on

With a client network stamped in, the box boots straight onto it: its access
point never shows at startup, so a phone that knows the access point cannot
grab it and hold the box there.

- **Joined once, a client for the rest of the boot.** A drop (power sagging as
  the motors start, an access point rebooting, a walk out of range and back) is
  rejoined, never a reason to change networks.
- **Not joined within 45 seconds of power-on** (the network is not there: a
  field), the box becomes its access point. With no phone on it, it tries the
  client network again every 3 minutes, so a box that booted before the router
  did finds its way home.
- **No client network stamped in:** the access point, the whole time.

A phone that auto-joins the access point keeps the box on it, which is right
in a field and wrong at home. On an iPhone: Settings, Wi-Fi, the ⓘ beside the
box's network, and turn off Auto-Join.

A box built with `OBS_AP_WINDOW_S` set keeps its access point up for that many
seconds after every power-on first, and a phone that joins in that time keeps
it: a way in that does not depend on the client network working.

**Ethernet** works whatever the radio is doing: a cable into any switch or
router and the box takes an address by DHCP.

## Which networks it joins

Set for as many access points as it can join:

- By SSID, never by BSSID: any access point broadcasting the network will do,
  and the box moves to a stronger one of the same network when the signal
  falls below -70 dBm.
- Both bands the board's radio has. A Pi 3 Model B and a Zero 2 W have
  2.4 GHz only; a 3 B+, 4 and 5 have 2.4 and 5 GHz.
- WPA2 and WPA2/WPA3 (transition) networks first; a WPA3-only network, or WPA2
  with protected management frames required, is tried next. Open networks
  too. Hidden SSIDs are found.
- Wi-Fi power save is off: on a Pi 3 it can leave the box answering its name
  but nothing else, and it saves well under a watt.

## iPhones and the captive sheet

On joining the access point, an iPhone checks for internet and finds a sign-in
page: the Observatory's. Tap **Continue**. The box then answers the phone's
checks the way iOS wants, so it treats the network as good and stays on it.
Without that step, iOS marks a network with no internet as broken and leaves it
for any known network that has internet.

If the sheet is dismissed without Continue, iOS offers **Use Without Internet**,
which also keeps the phone on the network. The box forgets which phones pressed
Continue when it reboots.

## Joining a client network

Open **Wi-Fi Networks**, then a nearby network (or **Other Network**), and type
its password. The network is saved and tried after the access point window at
every boot.

Joining from a phone that is on the access point cuts that phone off: the
radio stops being the access point the moment it becomes a client. Rejoin the
phone on the client network and open `http://<hostname>.local`. A wrong
password is not a lockout: the client does not join, and after 45 seconds the
access point comes back.

The radio cannot scan for nearby networks while it is the access point. Type
the SSID.

**Forget** removes a saved network. With none left, the box is the access
point the whole time.

## Power

A Pi on a supply that sags browns out: the Wi-Fi drops or the board resets.
From a phone that looks exactly like the software failing, often the moment the
mount's motors start. The **Power** card shows whether the supply has fallen
below 4.63 V since boot, and how long the board has been up. A short uptime
after a drop means it reset. A Pi 3 wants its own 5 V, 2.5 A supply, not one
shared with the mount's motors.

## Updates over the network

A box stamped with **SSH on** takes new firmware over the network. The update
goes to the slot the box is not running, and the box boots it once on trial.
It is kept only when every app starts **and** the page answers on port 80
**and** a network interface has an address, within five minutes. Otherwise the
box reverts to the image it had before. A freshly stamped card has no previous
image, so it is not put on trial.
