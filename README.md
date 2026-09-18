# Observatory

Astronomy software that is modular underneath and polished on top — good
enough for someone doing real science with a mount, a camera and an
autoguider, and easy enough that you can hand a phone to a kid at a star
party and say "pick something."

It starts with a Sky-Watcher EQ6-R on a Raspberry Pi and grows into star
maps, voice control, astrophotography, and running more than one telescope.
Everything is Elixir: small OTP apps that run on the Pi next to the mount or
on a bigger machine across the network, moved around as compute and latency
dictate.

## What we're building

**For the serious observer.** Accurate pointing and tracking you can trust,
an alignment model that gets better the more you use it, plate solving,
autoguiding, PEC, session planning, observation logs, and raw data (FITS)
out the other end. No black boxes: every number the mount reports is
inspectable, every command is a plain function call.

**For the star party.** Power it on, it finds itself. A phone in anyone's
hand shows what the scope is looking at and what else is up tonight; tap a
thing, the scope goes there, and the screen tells you what you're seeing.
Voice works when hands are cold. Nothing to install, nothing to configure,
nothing that can drive the scope into the tripod.

**For both.** One system. The star-party UI and the science tools sit on the
same `Mount`, catalog, and alignment model, so a casual night can turn into a
serious one without switching software.

## Principles

* **Modular, not fragmented.** Small apps with sharp boundaries (mount, catalog,
  camera, solver, UI), but shipped as a few named configurations that just run.
  Nobody assembles modules by hand.
* **Polished.** The UI is a product, not a debug panel. Latency, failure, and
  "what is it doing right now?" are designed for, not patched.
* **Boring wire.** Erlang terms end to end, JSON only at the browser edge. No
  serialization layer to maintain.
* **Safe by default.** Held slews self-stop, soft limits from home, emergency
  stop is one call and one button. Losing the network stops the scope, it
  never runs it away.
* **Runs where it makes sense.** The Pi does the minimum; heavy work moves to a
  laptop or the cloud based on the link (USB, LAN, Starlink, 5G).
* **Hardware-agnostic eventually.** The EQ6-R is first. The mount API is written
  so NexStar, LX200, and INDI/ASCOM bridges slot in behind it.

## Layout

```
apps/telescope   shared plumbing: PubSub + cluster membership
apps/mount       the EQ6-R driver (Sky-Watcher motor-controller protocol over an EQDIR cable)
firmware/        Nerves image for the Raspberry Pi: networking + ssh + the mount driver, nothing else
```

`apps/` is a Mix umbrella for host-side work; `firmware/` is a separate Nerves
project that pulls the apps in as path dependencies (the "poncho" layout
Nerves recommends).

## v1: the headless controller

The loop we're building first:

1. Plug a Raspberry Pi's SD card into the laptop.
2. `cd firmware && mix observatory.flash` — asks which Pi and which Wi-Fi,
   builds, burns. (Or by hand: `WIFI_SSID=… WIFI_PSK=… MIX_TARGET=rpi4 mix firmware && mix burn`.)
3. Move the card to the Pi, plug the Pi into the mount's HAND CONTROL port
   with the EQDIR cable, power up.
4. From any machine on the network: `Node.connect(:"telescope@telescope.local")`
   and drive it with `Mount.slew/3`, `Mount.goto_relative/3`, `Mount.track/2`.

Later updates go over the network: `mix observatory.flash --upload telescope.local`.

The Pi does three things and nothing more: manage network connections
(Wi-Fi, ethernet, and the USB cable to a laptop), watch USB for mounts, and
move the mount. Heavier work lives elsewhere and talks to it over the cluster.

### Network

* Initial Wi-Fi is baked into the build from `WIFI_SSID` / `WIFI_PSK`.
* More networks later: `ssh telescope.local`, then `Firmware.add_wifi("Site", "pw")`.
* No known network for 60 s → the Pi opens a `telescope-setup` hotspot; join it
  and pick a network at http://telescope.setup. Saved across reboots.
* Plugging the Pi's USB port into a laptop gives a network link too:
  `telescope.local` works over the cable with no Wi-Fi at all.

### Driving the mount from the laptop

```sh
cd apps && iex --name me@$(hostname).local --cookie observatory -S mix
```

```elixir
Node.connect(:"telescope@telescope.local")
[m] = Mount.list()
Mount.snapshot(m)                 # position, status, firmware
Mount.slew(m, :ra, 64)            # 64× sidereal until stopped
Mount.stop(m)
Mount.goto_relative(m, :dec, 5.0) # full-speed, mount-managed ramps
Mount.track(m, :sidereal)
Mount.emergency_stop(m)
```

Without hardware, `iex -S mix` in `apps/` starts a simulated EQ6-R that speaks
the real wire protocol, so everything above works on a laptop.

## Roadmap

Tracked as GitHub issues on the project board; the phases, roughly in order:

1. **Headless controller** (v1) — Pi image, build/burn loop, networking, mount driver, cluster access.
2. **Hand control web UI** — Phoenix LiveView arrow pad, rates, tracking, stop; runs on the Pi or anywhere.
3. **Star map** — catalog import, a 2‑D sky you can scroll, click-to-slew, alignment model, site/time.
4. **Voice & AI** — "slew to Vega", "what's good tonight", an agent over the same `Mount` API.
5. **Astrophotography** — Canon EOS capture over USB, image queue to a bigger machine, plate solving, autoguiding, one-button alignment.
6. **Observatory** — several telescopes, workload placement by latency (USB / LAN / Starlink / 5G).

## Topology

Many small apps, a few named ways to run them (#25):

| Configuration | What runs | Where |
|---|---|---|
| **Pi** (firmware) | networking, ssh, mount driver | next to the scope |
| **Desktop** | web UI + cluster client, one binary (Burrito) | a laptop on the LAN or over USB |
| **Server** | many Pis dialing in, multi-telescope UI, heavy services | the cloud |

On a LAN the nodes find each other by multicast and talk plain Erlang
distribution. Across Starlink/5G the Pi is behind NAT, so it has to dial out:
an overlay network (Tailscale) first, a small dedicated uplink later (#24).
Wire format stays Erlang terms end to end; JSON only at the browser.

## Hardware notes

* EQ6-R power: 11–16 V DC, 4 A, **center-positive** on the GX12 locking plug.
  Reversed polarity looks like a dead short to the supply (voltage collapses to
  ~0.3 V, no LED). Found the hard way.
* HAND CONTROL port is 3.3 V TTL at 9600 baud; any FTDI "EQDIR" cable works.
* No absolute encoders: the mount reports `0x800000` on both axes at power-on
  wherever it happens to be. Power on in the home position (counterweight
  down, scope at the pole) and `Mount.set_home/1`. That also arms the soft
  limits (`config :mount, :limits`, default RA ±100°, Dec ±95° from home): a
  goto past one is refused, a slew heading for one is stopped a second early.
* The mount's `:f` status, `:j` position, and `:e/:a/:b/:g` constants are
  documented in `Mount.Protocol`.
