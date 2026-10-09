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
    # `parts` is what the image actually runs, taken from `apps`: a role that
    # says "Web UI" has to install the controller, or the box's address serves
    # nothing.
    %{
      id: :observatory,
      name: "Observatory",
      blurb: "Mount driver and web UI, with camera and game pad support.",
      parts: ["Mount", "Web UI", "Camera", "Game pad"],
      apps: [:telescope, :mount, :controller, :watch, :video, :input],
      wants: :rpi4
    },
    %{
      id: :mount_only,
      name: "Mount only",
      blurb: "Mount driver only, no web UI. Driven from another node over Erlang distribution.",
      parts: ["Mount"],
      apps: [:telescope, :mount],
      wants: :rpi0_2
    },
    %{
      id: :eyes,
      name: "Camera only",
      blurb: "Camera and video only, no web UI. For a scope another node drives.",
      parts: ["Camera"],
      apps: [:telescope, :watch, :video],
      wants: :rpi4
    }
  ]

  @targets [
    %{id: :rpi5, name: "Raspberry Pi 5", note: "Cortex-A76, 4 to 8 GB. Handles video."},
    %{id: :rpi4, name: "Raspberry Pi 4", note: "Cortex-A72, 2 to 8 GB. Handles video."},
    %{id: :rpi3, name: "Raspberry Pi 3", note: "Cortex-A53, 1 GB. Stills, no video."},
    %{id: :rpi3a, name: "Raspberry Pi 3 A+", note: "Cortex-A53, 512 MB, one USB port."},
    %{id: :rpi0_2, name: "Raspberry Pi Zero 2 W", note: "Cortex-A53, 512 MB. Mount only."}
  ]

  @flavours [
    %{
      id: :dev,
      name: "SSH on",
      blurb: "Authorizes your keys from ~/.ssh. Firmware updates over the network with mix upload.",
      warn: "Anyone holding one of those private keys gets a shell on the box."
    },
    %{
      id: :prod,
      name: "SSH off",
      blurb: "No SSH, no network firmware updates. Update by re-stamping the SD card.",
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
      # Every box is its own Wi-Fi network wherever there is no home network to
      # join, named after the box, so the name on the phone's Wi-Fi list is the
      # name in its address. The firmware reads both of these.
      "OBS_AP_SSID" => opts[:ap_ssid] || hostname,
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

    own = opts[:ap_ssid] || opts[:hostname] || "observatory"

    network =
      case wifi do
        %{ssid: ssid} when is_binary(ssid) and ssid != "" ->
          "Wi-Fi client on #{ssid}; access point #{own} when #{ssid} is out of range"

        _ ->
          "Access point #{own}"
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
