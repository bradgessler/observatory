defmodule Provision.Templates do
  @moduledoc """
  What a box is for, and how much of it we build.

  A template is the compute that lands on the card: which apps run, and in
  which flavour. The flavour is the difference between a box you can get
  inside and change, and one that just works and keeps its mouth shut.

    * `:dev` leaves the door open. An IEx over SSH, firmware pushed over the
      network with `mix upload` (so a box bolted to the mount never needs its
      card pulled again), verbose logs, the setup wizard always reachable.
    * `:prod` closes it. No shell, no firmware-over-SSH, quiet logs. What you
      hand to someone else, or leave in a field for a season.
  """

  @templates [
    %{
      id: :observatory,
      name: "Observatory",
      blurb: "A telescope you plug a phone into.",
      parts: ["Mount", "Web", "Camera", "Pad"],
      apps: [:telescope, :mount, :controller, :watch, :video, :input],
      wants: :rpi4
    },
    %{
      id: :mount_only,
      name: "Mount Only",
      blurb: "Moves the telescope. Nothing else.",
      parts: ["Mount", "Web"],
      apps: [:telescope, :mount],
      wants: :rpi0_2
    },
    %{
      id: :eyes,
      name: "Eyes",
      blurb: "Watches a telescope something else is driving.",
      parts: ["Camera", "Web"],
      apps: [:telescope, :watch, :video],
      wants: :rpi4
    }
  ]

  @targets [
    %{id: :rpi5, name: "Pi 5", note: "Fastest. Video without thinking about it."},
    %{id: :rpi4, name: "Pi 4", note: "Enough for everything, including video."},
    %{id: :rpi3, name: "Pi 3", note: "Stills yes, video no."},
    %{id: :rpi3a, name: "Pi 3 Model A", note: "Smaller, one USB port."},
    %{id: :rpi0_2, name: "Pi Zero 2 W", note: "Tiny. Mount only."}
  ]

  @flavours [
    %{
      id: :dev,
      name: "Development",
      blurb: "A shell over SSH, and firmware pushed over the network.",
      warn: "Anyone with your SSH key can open a shell on it."
    },
    %{
      id: :prod,
      name: "Production",
      blurb: "No shell, no firmware over the network.",
      warn: nil
    }
  ]

  def all, do: @templates
  def targets, do: @targets
  def flavours, do: @flavours

  def get(id) when is_atom(id), do: Enum.find(@templates, &(&1.id == id))
  def get(id) when is_binary(id), do: Enum.find(@templates, &(to_string(&1.id) == id))

  def target(id) when is_binary(id), do: Enum.find(@targets, &(to_string(&1.id) == id))
  def target(id), do: Enum.find(@targets, &(&1.id == id))

  def flavour(id) when is_binary(id), do: Enum.find(@flavours, &(to_string(&1.id) == id))
  def flavour(id), do: Enum.find(@flavours, &(&1.id == id))

  @doc """
  The environment the firmware build runs with. Everything the image needs to
  know that is not code: which apps, which flavour, and how it should get on
  a network.

  Network credentials are passed as environment to the build, never written
  into the repository. A box with no Wi-Fi given still comes up talking: it
  brings up its own access point so you can reach it in a field with no
  signal, which is the only way to configure something you cannot otherwise
  see. With Wi-Fi given it joins that network, and still falls back to its own
  access point if the network is not there.
  """
  def build_env(opts) do
    template = get(opts[:template]) || hd(@templates)
    flavour = flavour(opts[:flavour] || :prod) || hd(@flavours)
    hostname = opts[:hostname] || "observatory"
    wifi = opts[:wifi] || %{}

    base = %{
      "MIX_TARGET" => to_string(opts[:target] || :rpi4),
      "MIX_ENV" => "prod",
      "OBS_TEMPLATE" => to_string(template.id),
      "OBS_APPS" => Enum.map_join(template.apps, ",", &to_string/1),
      "OBS_FLAVOUR" => to_string(flavour.id),
      "NERVES_HOSTNAME" => hostname,
      # every box brings up its own access point when it cannot reach a network
      "OBS_AP_SSID" => opts[:ap_ssid] || "#{hostname}-setup",
      "OBS_AP_PSK" => opts[:ap_psk] || ""
    }

    case wifi do
      %{ssid: ssid, psk: psk} when is_binary(ssid) and ssid != "" ->
        Map.merge(base, %{"WIFI_SSID" => ssid, "WIFI_PSK" => psk || ""})

      _ ->
        base
    end
  end

  @doc "A plain-words summary of what is about to be written, for the page to show back."
  def describe(opts) do
    template = get(opts[:template]) || hd(@templates)
    target = target(opts[:target] || :rpi4) || hd(@targets)
    flavour = flavour(opts[:flavour] || :prod) || hd(@flavours)
    wifi = opts[:wifi] || %{}

    network =
      case wifi do
        %{ssid: ssid} when is_binary(ssid) and ssid != "" ->
          "Joins #{ssid}, or its own network if that is not there"

        _ ->
          "Brings up #{opts[:ap_ssid] || "#{opts[:hostname] || "observatory"}-setup"} for you to join"
      end

    %{
      template: template.name,
      target: target.name,
      flavour: flavour.name,
      hostname: opts[:hostname] || "observatory",
      network: network
    }
  end
end
