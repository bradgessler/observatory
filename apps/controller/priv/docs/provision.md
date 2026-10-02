# Stamp a Box

Put an SD card in this machine, answer five short screens, and write a
bootable Observatory onto it. Then put the card in a Raspberry Pi, power it
up, and the telescope has its own computer, a **box**, instead of borrowing
yours.

Each screen asks one thing, and tapping the answer is also the way forward.
Going back changes nothing you have already said.

## 1. SD card

Only removable disks are listed. The machine's own drive cannot appear here,
so a mistaken tap cannot take this machine out. Everything on the card you
choose is erased, and the card is named again before anything is written.

The card is checked once more in the moment before writing. If you pull it
while an image is building, nothing is written and the page says so.

## 2. Role

Three roles, because not every box needs everything. The chips on each row
are the parts that land on the card.

- **Observatory** is the whole thing: the mount driver, the web pages, the
  cameras and the game controller. A telescope you open on a phone.
- **Mount only** is the mount driver, with no web pages, driven from another
  node. Small and quiet, and enough to move the telescope. It runs on
  anything down to a Pi Zero 2 W.
- **Camera only** is camera and video with no mount: a second box watching a
  telescope that something else is driving.

## 3. Board

Picking a role suggests the board that suits it, marked on the row. Override
it and the override sticks, even if you go back and change the role.

Video is the thing that decides this. A Pi 4 or 5 encodes it without
complaint; a Pi 3 does stills; a Zero 2 W is for a box that only moves the
mount.

## 4. Network

Every field starts filled in with the value the box will really use.

- **Hostname**: the box's name, and its address with `.local` on the end.
- **Access Point**: the box's own Wi-Fi network, always there. Its **SSID**
  follows the hostname until you change it; an empty **Password** makes it an
  open network, which anyone in range can join. No router or internet needed,
  which is the only way to reach a box in a field.
- **Wi-Fi Client (Optional)**: your own Wi-Fi. With it, the box joins that
  network at boot and falls back to its access point when the network isn't
  there, so a box is never unreachable.

How a stamped box chooses between the two is in [Network](/docs/network).

## 5. Build

The last screen is the whole plan in a few lines, and one choice:

- **SSH on** authorizes the SSH keys of the machine doing the stamping, so
  you get a shell over SSH and new firmware can be pushed over the network: a
  box bolted to the mount never needs its card pulled again. Anyone holding
  one of those keys can open a shell on it.
- **SSH off** is closed: no shell, no firmware over the network. To change
  it, stamp the card again.

Then one key, **Stamp**. It opens a terminal, because writing to a disk needs
administrator rights: `sudo` asks for your password there, and `fwup` asks
before it writes.

Writing a card takes a couple of minutes. The first build for a given board
takes about ten, because the whole system is compiled. The terminal shows
the tools' own output the entire time. If a step fails it says which step
and why, and stops. A half-written card has to be written again; it will not
boot.
