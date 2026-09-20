defmodule Firmware.MixProject do
  use Mix.Project

  @app :firmware
  @version "0.1.0"
  # x86_64 is not a box you buy: it is the same image booted in a VM, so the
  # whole stack (fwup, the rootfs, the release, the supervision tree) can be
  # exercised on a laptop in a minute instead of a card swap and a reboot.
  @all_targets [:rpi0_2, :rpi3, :rpi3a, :rpi4, :rpi5, :x86_64]

  def project do
    [
      app: @app,
      version: @version,
      elixir: "~> 1.20",
      archives: [nerves_bootstrap: "~> 1.17"],
      start_permanent: Mix.env() == :prod,
      deps: deps(),
      releases: [{@app, release()}]
    ]
  end

  def application do
    [
      extra_applications: [:logger, :runtime_tools],
      mod: {Firmware.Application, []}
    ]
  end

  def cli do
    [preferred_targets: [run: :host, test: :host]]
  end

  defp deps do
    [
      # What this box is for: the mount driver and the cluster plumbing.
      {:mount, path: "../apps/mount"},
      {:telescope, path: "../apps/telescope"},

      {:nerves, "~> 1.13", runtime: false},
      {:shoehorn, "~> 0.9.1"},
      {:ring_logger, "~> 0.11.0"},
      {:toolshed, "~> 0.5.0"},
      {:nerves_runtime, "~> 0.13.12"},

      # Networking (wifi/ethernet/usb-gadget), ssh, mdns, time — and a captive
      # portal to pick a new Wi-Fi network in the field.
      {:nerves_pack, "~> 0.7.1", targets: @all_targets},
      {:vintage_net_wizard, "~> 0.4", targets: @all_targets},

      {:nerves_system_rpi0_2, "~> 2.0", runtime: false, targets: :rpi0_2},
      {:nerves_system_rpi3, "~> 2.0", runtime: false, targets: :rpi3},
      {:nerves_system_rpi3a, "~> 2.0", runtime: false, targets: :rpi3a},
      {:nerves_system_rpi4, "~> 2.0", runtime: false, targets: :rpi4},
      {:nerves_system_rpi5, "~> 2.0", runtime: false, targets: :rpi5},
      {:nerves_system_x86_64, "~> 1.34", runtime: false, targets: :x86_64}
    ]
  end

  def release do
    [
      overwrite: true,
      cookie: System.get_env("OBSERVATORY_COOKIE", "observatory"),
      include_erts: &Nerves.Release.erts/0,
      steps: [&Nerves.Release.init/1, :assemble],
      strip_beams: Mix.env() == :prod or [keep: ["Docs"]]
    ]
  end
end
