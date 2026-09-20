# Firmware

**TODO: Add description**

## Targets

Nerves applications produce images for hardware targets based on the
`MIX_TARGET` environment variable. If `MIX_TARGET` is unset, `mix` builds an
image that runs on the host (e.g., your laptop). This is useful for executing
logic tests, running utilities, and debugging. Other targets are represented by
a short name like `rpi5` that maps to a Nerves system image for that platform.
All of this logic is in the generated `mix.exs` and may be customized. For more
information about targets see:

https://nerves.hexdocs.pm/supported-targets.html

## Getting Started

To start your Nerves app:
  * `export MIX_TARGET=my_target` or prefix every command with
    `MIX_TARGET=my_target`. For example, `MIX_TARGET=rpi5`
  * Install dependencies with `mix deps.get`
  * Create firmware with `mix firmware`
  * Burn to an SD card with `mix burn`

## Learn more

  * Official docs: https://nerves.hexdocs.pm/getting-started.html
  * Official website: https://nerves-project.org/
  * Forum: https://elixirforum.com/c/nerves-forum
  * Elixir Discord #nerves channel: https://discord.gg/elixir
  * Source: https://github.com/nerves-project/nerves

## The VM loop

A card swap is a two minute round trip and you cannot put a test around it.
The `x86_64` target builds the same image, made by the same `fwup`, and boots
it in QEMU on the laptop:

    cd firmware && MIX_TARGET=x86_64 MIX_ENV=prod mix firmware
    cd apps/provision && mix test --only vm

That boots the image, waits for the release and for ssh, and asks the running
system questions: which applications started, whether networking came up,
whether the filesystem is writable. About forty seconds to boot, then the
whole suite in twelve.

It proves the image boots, the release starts and the supervision tree comes
up. It cannot prove anything about the Pi: no EQDIR cable, no camera, no GPIO,
no ARM. That is the point. Run this a hundred times a day so the real box only
has to be right about hardware.
