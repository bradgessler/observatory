# Observatory

Software for running a telescope — starting with a Sky-Watcher EQ6-R on a
Raspberry Pi and growing into star maps, voice control, and astrophotography.
Everything is Elixir: small OTP apps that can run on the Pi next to the mount
or on a bigger machine across the network, moved around as compute and
latency dictate.

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
2. `WIFI_SSID=… WIFI_PSK=… MIX_TARGET=rpi4 mix firmware && mix burn`
3. Move the card to the Pi, plug the Pi into the mount's HAND CONTROL port
   with the EQDIR cable, power up.
4. From any machine on the network: `Node.connect(:"telescope@telescope.local")`
   and drive it with `Mount.slew/3`, `Mount.goto_relative/3`, `Mount.track/2`.

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

## Hardware notes

* EQ6-R power: 11–16 V DC, 4 A, **center-positive** on the GX12 locking plug.
  Reversed polarity looks like a dead short to the supply (voltage collapses to
  ~0.3 V, no LED). Found the hard way.
* HAND CONTROL port is 3.3 V TTL at 9600 baud; any FTDI "EQDIR" cable works.
* No absolute encoders: the mount reports `0x800000` on both axes at power-on
  wherever it happens to be. Power on in the home position (counterweight
  down, scope at the pole) and `Mount.set_home/1`.
* The mount's `:f` status, `:j` position, and `:e/:a/:b/:g` constants are
  documented in `Mount.Protocol`.
