import Config

config :logger, backends: [RingLogger]

# Bring up networking + ssh (nerves_pack) before the app so a broken driver
# never locks us out of the box.
config :shoehorn, init: [:nerves_runtime, :nerves_pack]

# Bad firmware that can't finish booting rolls back to the previous one.
config :nerves_runtime, startup_guard_enabled: true

config :nerves, :erlinit, update_clock: true

# ---- ssh ---------------------------------------------------------------------
# The person stamping the box gets into the box: their own public keys are
# baked in, so there are no keys to hand around and nothing to type in. If
# they have never made one, make one for them rather than stopping with an
# error nobody asked for.
keys =
  case Path.wildcard(Path.join(System.user_home!(), ".ssh/id_{rsa,ecdsa,ed25519}.pub")) do
    [] ->
      path = Path.join(System.user_home!(), ".ssh/id_ed25519")
      File.mkdir_p!(Path.dirname(path))
      {_, 0} = System.cmd("ssh-keygen", ["-t", "ed25519", "-N", "", "-C", "observatory", "-f", path], stderr_to_stdout: true)
      IO.puts("No SSH key found, so one was made for you: #{path}")
      [path <> ".pub"]

    found ->
      found
  end

# A production box is closed up: no shell, no firmware over the network.
# A development box leaves the door open so it can be worked on in place.
case System.get_env("OBS_FLAVOUR", "dev") do
  "prod" ->
    config :nerves_ssh, authorized_keys: []

  _ ->
    config :nerves_ssh, authorized_keys: Enum.map(keys, &File.read!/1)
end

# ---- networking -----------------------------------------------------------------
# Initial Wi-Fi is baked in at build time from the environment:
#
#     WIFI_SSID="Home" WIFI_PSK="secret" mix firmware
#
# Extra networks can be added later without a rebuild: `Firmware.add_wifi/2`
# over ssh, or the captive portal (see wizard below).
wifi =
  case System.get_env("WIFI_SSID") do
    nil ->
      %{type: VintageNetWiFi}

    ssid ->
      %{
        type: VintageNetWiFi,
        vintage_net_wifi: %{
          networks: [%{key_mgmt: :wpa_psk, ssid: ssid, psk: System.fetch_env!("WIFI_PSK")}]
        },
        ipv4: %{method: :dhcp}
      }
  end

config :vintage_net,
  regulatory_domain: System.get_env("WIFI_COUNTRY", "US"),
  config: [
    # Pi plugged into a laptop's USB port shows up as a network link: telescope.local over the cable.
    {"usb0", %{type: VintageNetDirect}},
    {"eth0", %{type: VintageNetEthernet, ipv4: %{method: :dhcp}}},
    {"wlan0", wifi}
  ]

# No usable Wi-Fi for a minute → the Pi opens its own "telescope-setup"
# hotspot with a web page to pick a network. Config persists across reboots.
config :vintage_net_wizard,
  ssid: "telescope-setup",
  dns_name: "telescope.setup",
  captive_portal: true

config :mdns_lite,
  hosts: [:hostname, "telescope"],
  ttl: 120,
  services: [
    %{protocol: "ssh", transport: "tcp", port: 22},
    %{protocol: "sftp-ssh", transport: "tcp", port: 22},
    %{protocol: "epmd", transport: "tcp", port: 4369}
  ]

# ---- observatory ------------------------------------------------------------------
# Watch USB for EQDIR cables; one driver per mount, none when unplugged.
config :mount, mounts: :auto, simulate_when_empty: false

# Nodes find each other over Erlang distribution; the laptop connects with
# `Node.connect(:"telescope@telescope.local")` (see Firmware.Distribution).
config :libcluster, topologies: []

config :firmware,
  node_name: System.get_env("OBSERVATORY_NODE", "telescope"),
  wizard_after_ms: 60_000
