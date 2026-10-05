# Observatory

Astronomy software that is modular underneath and polished on top — for
someone doing real science with a mount, a camera and an autoguider, and for
handing a phone to a kid at a star party and saying "pick something."

Everything is Elixir: small OTP apps that run on a Raspberry Pi next to the
mount or on a bigger machine across the network. What's planned lives in the
[issues](https://github.com/bradgessler/observatory/issues) and the
[project board](https://github.com/users/bradgessler/projects/1); this README
covers what works today.

## v1: the headless controller

A Raspberry Pi plugged into a Sky-Watcher EQ6-R that does three things:
manages its network connections, watches USB for mounts, and moves the mount.
Anything else talks to it over the network.

```
apps/telescope   shared plumbing: PubSub + cluster membership
apps/mount       the EQ6-R driver (Sky-Watcher motor-controller protocol over an EQDIR cable)
firmware/        Nerves image for the Pi: networking + ssh + the mount driver, nothing else
hack/            day-one Python probes that proved the protocol; kept as a record
```

`apps/` is a Mix umbrella for host-side work; `firmware/` is a separate Nerves
project that pulls the apps in as path dependencies.

### Running it on a laptop

```sh
brew bundle        # fwup, hidapi, ffmpeg and the rest — see Brewfile
mix archive.install hex nerves_bootstrap   # only to build images
mix deps.get
mix phx.server     # http://localhost:4000
```

The mount appears when the EQDIR cable is plugged in; a simulator runs when it
isn't. Every host tool is optional: a missing one disables its feature and says
what to install, and nothing else notices.

### Hardware

* Sky-Watcher EQ6-R (also EQ6-R Pro).
* An EQDIR cable: any FTDI USB-to-RJ45 "for Sky-Watcher EQ6-R / AZ-EQ6" lead,
  plugged into the mount's **HAND CONTROL** port. No SynScan hand controller.
* Raspberry Pi Zero 2 W, 3, 3A+, 4 or 5, with an SD card.
* 12 V power for the mount (see hardware notes below — polarity matters).

### Flash the Pi

```sh
cd firmware
mix observatory.flash          # asks which Pi and which Wi-Fi; builds; burns the SD card
```

Equivalent by hand: `WIFI_SSID=… WIFI_PSK=… MIX_TARGET=rpi4 mix firmware && mix burn`.
Later updates go over the network: `mix observatory.flash --upload telescope.local`.

Card into the Pi, EQDIR cable from the Pi's USB to the mount, power both on.
The Pi comes up as `telescope.local`.

### Network

* The Wi-Fi you gave at build time is baked in.
* More networks later: `ssh telescope.local`, then `Firmware.add_wifi("Site", "pw")`.
* No known network for 60 s → the Pi opens a `telescope-setup` hotspot; join it
  and pick a network at http://telescope.setup. Saved across reboots.
* Plugging the Pi's USB port into a laptop gives a network link too:
  `telescope.local` works over the cable with no Wi-Fi at all.
* `ssh telescope.local` drops you in an IEx shell; `Firmware.status()` shows
  interfaces and mounts.

### The web UI (`apps/controller`)

`mix phx.server` at the repo root, then open `http://<this-machine>:4000` on a
phone, iPad, or the laptop itself. Phone-first, night-mode (◐), works on any size.

* **Keypad** `/` — press-and-hold D-pad, rates 1×–800×, STOP, Track, zero the axes,
  ±° gotos, emergency stop. Arrow keys + space on a keyboard.
* **Sky** `/sky` — the sky right now from your site: stars to mag 5, Messier and
  named DSOs, constellation lines, Moon and planets. Tap anything → **Slew**.
  No finder? **Search** spirals around the target until you see it; **Sync**
  teaches the pointing model where it really is.
  * **Tonight** — what's above *your* tree line over the next two hours, ranked
    for this scope and this sky (aperture → limiting magnitude, Moon up/phase,
    crowd-pleaser bias), each with plain words instead of a magnitude number.
    Top five, then the rest. Picking one rings it on the map.
  * **Horizon** — the tree line per compass direction, the scope's aperture,
    and **map obstructions from a photo**: take a Night-mode shot of the sky
    with the trees in frame, pick it, and the boundary is traced on your phone
    and plate-solved (needs a free `NOVA_API_KEY` from nova.astrometry.net)
    into that direction's horizon.

* **Home** `/` — the front door: a grouped list of everything, one line each
  (Star Lock, Controls, Watch, Plumbing), each with a `?` to the page that
  says why it exists.
* **Events** `/events` — every command to the mount with who sent it (which
  page, the game pad, the tracker), plus star alignment stars and video starts.
  In memory; the durable version is an issue.
* **Bench** `/bench` — every control surface side by side.
  One header with the scope's live state, the game pad, the camera and one
  always-visible STOP; a nav of surfaces, each rendered below:
  *Axis strips* (pull-to-speed per axis), *Plain keypad*, *Nudge* (tap = one
  exact 1′/5′/30′/2° step), *Orb* (the equatorial geometry as a 3-D gizmo),
  *Tilt* (hold the dead-man, tilt the phone; needs HTTPS), *Position* (type an
  axis angle, go home), *Game controller* (a USB pad read by the server —
  see `apps/input`), *Watch* and *Sky*.
* **Home** (`/`) is the list of everything. **Start** (`/start`) is an experiment: a flow, not a menu, *Plug in → Zero →
  Stars 0/3 → Look*. It shows the step you are on and moves on by itself; once
  three stars agree it becomes the control surface (tonight's targets with Go,
  what the tube is holding, the ways to centre, the pad switch, STOP) and
  draws the corrections in force: the law in charge, the mount's polar axis
  against the true pole, the offsets, and how much authority the tracker is
  using on each axis.
* **Star Align** (`/controls/align`) — no Polaris needed. Zero the axes (mount
  upright; it arms the limits), then centre the star the page names and tap
  *that's it*; a second star far from the first is enough to steer, a third
  says how well they agree. Behind it is a real geometric model of the mount
  (`Controller.Sky.Model`: polar axis anywhere + encoder offsets) fitted from
  the stars; gotos, readouts and the orb all go through it, and after a goto
  the software tracks through the model on both axes (`Controller.Sky.Tracker`).
  The alignment shows as a mode on every page; `/docs/align` explains the words.
* **Watch** — a camera on the mount, read by the server (`imagesnap` on a Mac,
  `fswebcam` on Linux). Every frame is kept under `~/.observatory/watch/frames`
  for the last 240 frames / 20 minutes / 256 MB, whichever comes first, so a
  person or an agent can look back at a slew (`Watch.history/1`,
  `/watch/frames/<name>`); the page shows the strip. **Video** is HLS from
  FFmpeg (`apps/video`: hardware H.264 where the machine has it, 1K/2K/4K as
  the camera allows), served as plain files; Safari plays it natively, other
  browsers get a lazily-loaded hls.js. While streaming, stills come from the
  encoder so the history keeps filling. It is a separate app on purpose: it is
  the heavy workload and is meant to run on a bigger machine than the camera's.

Settings persist in `~/.observatory/settings.json`. Site and the pointing
model's axis signs live in `config/config.exs` (`:controller`).

### Drive it from a laptop

```sh
cd apps && iex --name me@$(hostname).local --cookie observatory -S mix
```

```elixir
Node.connect(:"telescope@telescope.local")
[m] = Mount.list()
Mount.snapshot(m)                 # position, status, firmware, limits
Mount.set_home(m)                 # counterweight down, scope at the pole: zero + arm soft limits
Mount.slew(m, :ra, 64)            # 64× sidereal until stopped
Mount.stop(m)
Mount.goto_relative(m, :dec, 5.0) # full-speed, mount-managed ramps
Mount.track(m, :sidereal)         # also :lunar, :solar, :off
Mount.emergency_stop(m)
Mount.subscribe(m)                # then receive {:mount, snapshot} every 250 ms
```

Without hardware, `iex -S mix` in `apps/` starts a simulated EQ6-R that speaks
the real wire protocol, so all of the above works on a laptop. Plug a cable in
and the real mount appears alongside it; pull it and it goes away.

### Safety

* Slews started with `hold: true` stop by themselves unless refreshed within
  900 ms — a held button on a flaky link can't run away.
* Soft limits (`config :mount, :limits`, default RA ±100°, Dec ±95° from home)
  are armed by `set_home`. A goto past one is refused; a slew heading for one
  is stopped a second early based on measured speed.
* Losing the serial link restarts the driver; losing the network stops nothing
  the mount was already doing on its own except held slews.

## Hardware notes

* EQ6-R power: 11–16 V DC, 4 A, **center-positive** on the GX12 locking plug.
  Reversed polarity looks like a dead short to the supply (voltage collapses to
  ~0.3 V, no LED). Found the hard way.
* HAND CONTROL port is 3.3 V TTL at 9600 baud; any FTDI "EQDIR" cable works.
* No absolute encoders: the mount reports `0x800000` on both axes at power-on
  wherever it happens to be. Power on in the home position and `Mount.set_home/1`.
* The mount's `:f` status, `:j` position, and `:e/:a/:b/:g` constants are
  documented in `Mount.Protocol`. Measured on an EQ6-R: 9,216,000 steps/rev,
  timer 53,694 Hz, high-speed ratio 32, firmware `020B05`; full goto speed
  ≈3.4°/s; commanded sidereal rate within 0.001% of true.

## Copyright

The observations (everything under `observations/`) and the images in
`posts/images/` are Brad Gessler's own work, all rights reserved, whatever
licence the code carries. See [COPYRIGHT.md](COPYRIGHT.md).
