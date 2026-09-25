import Config

config :logger, backends: [RingLogger]

# Bring up networking + ssh (nerves_pack) before the app so a broken driver
# never locks us out of the box.
config :shoehorn, init: [:nerves_runtime, :nerves_pack], handler: Firmware.AppRestarter

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

# This Mac's own key, with no passphrase, so the VM smoke test and a box being
# worked on can be reached without depending on whether an agent happens to be
# holding yours (it often is not). Development boxes only: a production box
# (below) authorizes nothing. Anyone who can read this Mac's ~/.observatory can
# get into a development box, as they can into its VM.
vm_key = Path.join(System.user_home!(), ".observatory/vm_ed25519.pub")
keys = if File.exists?(vm_key), do: keys ++ [vm_key], else: keys

# A production box is closed up: no shell, no firmware over the network.
# A development box leaves the door open so it can be worked on in place.
case System.get_env("OBS_FLAVOUR", "dev") do
  "prod" ->
    config :nerves_ssh, authorized_keys: []

  _ ->
    config :nerves_ssh, authorized_keys: Enum.map(keys, &File.read!/1)
end

# ---- networking -----------------------------------------------------------------
# Two ways to reach the box, and it picks between them by itself:
#
#   Its own network (the field). The box is a Wi-Fi network named after
#   itself. Join it from a phone and open http://<name>.local, or
#   http://192.168.24.1 where .local names do not work. Nothing else is needed:
#   no router, no internet, no setup page. With no home Wi-Fi given, this is
#   what it does from the moment it boots.
#
#   Your home Wi-Fi. Given WIFI_SSID, the box tries that first, joins it at
#   home, and answers at http://<name>.local like anything else on the
#   network. If it has not joined within 45 seconds you are somewhere else,
#   and it puts up its own network instead (Firmware.Wireless).
#
# A Pi has one Wi-Fi radio, so it is on one or the other, never both at once.
# Everything comes from the stamp's environment; blank means unset throughout.

blank_is = fn var, default ->
  case System.get_env(var, "") do
    "" -> default
    value -> value
  end
end

name = blank_is.("NERVES_HOSTNAME", "telescope")
own_ssid = blank_is.("OBS_AP_SSID", name)
own_psk = System.get_env("OBS_AP_PSK", "")

# A WPA2 password is 8 to 63 characters. Anything else and the network never
# comes up, and a box in a field with no network cannot be reached to fix it,
# so this stops the build instead of writing that card.
unless own_psk == "" or String.length(own_psk) in 8..63 do
  raise "OBS_AP_PSK must be 8 to 63 characters (or empty for an open network); got #{String.length(own_psk)}"
end

own_network = %{
  type: VintageNetWiFi,
  vintage_net_wifi: %{
    networks: [
      if own_psk == "" do
        %{mode: :ap, ssid: own_ssid, key_mgmt: :none}
      else
        # AES only (CCMP), never TKIP, which phones refuse outright. WPA2-only
        # would also want proto=RSN, but vintage_net_wifi drops that key without
        # saying so (checked in the VM smoke test), so the network is WPA/WPA2
        # with AES: an iPhone joins it and may label it "Weak Security".
        %{mode: :ap, ssid: own_ssid, key_mgmt: :wpa_psk, psk: own_psk, pairwise: "CCMP"}
      end
    ]
  },
  ipv4: %{method: :static, address: {192, 168, 24, 1}, netmask: {255, 255, 255, 0}},
  # A captive portal, the way vintage_net_wizard did it on these same boards:
  # phones get the box as their router and DNS server, and the box answers
  # every name with itself. A phone's "is this a captive network?" check lands
  # on the box, which says "yes, the Observatory" (Firmware.Web.Captive),
  # and the phone opens its sheet straight onto the page. Any address typed
  # into a browser lands there too.
  dhcpd: %{
    start: {192, 168, 24, 10},
    end: {192, 168, 24, 250},
    options: %{dns: [{192, 168, 24, 1}], router: [{192, 168, 24, 1}], subnet: {255, 255, 255, 0}}
  },
  dnsd: %{records: [{name, {192, 168, 24, 1}}, {"*", {192, 168, 24, 1}}]}
}

# The Wi-Fi client network stamped in, if any. A network with no password is
# an open network, which wpa_psk cannot describe; a blank name is no network
# at all, not one called "". Matched by SSID, never BSSID: any access point
# broadcasting it will do (Firmware.Wireless roams between them).
client_networks =
  case {System.get_env("WIFI_SSID", ""), System.get_env("WIFI_PSK", "")} do
    {"", _} -> []
    {ssid, ""} -> [%{key_mgmt: :none, ssid: ssid}]
    {ssid, psk} -> [%{key_mgmt: :wpa_psk, ssid: ssid, psk: psk}]
  end

config :vintage_net,
  regulatory_domain: System.get_env("WIFI_COUNTRY", "US"),
  # Nothing VintageNet saves may replace the boot settings below: the access
  # point at every power-on is the box's promise of a way in, and a saved
  # client config would quietly break it. Client networks added on the Network
  # page are kept by Firmware.Wireless instead.
  persistence: VintageNet.Persistence.Null,
  config: [
    # Pi plugged into a computer's USB port shows up as a network link: <name>.local over the cable.
    {"usb0", %{type: VintageNetDirect}},
    # a cable into any switch: an address by DHCP, whatever the radio is doing
    {"eth0", %{type: VintageNetEthernet, ipv4: %{method: :dhcp}}},
    # Always the access point at power-on: the one Wi-Fi setting proven on the
    # boards. Firmware.Wireless moves to a client network after the window.
    {"wlan0", own_network}
  ]

# events and the flight recorder go to the SD card, so a reset leaves a record
config :telescope, events_file: "/data/observatory/events.log"

config :firmware,
  name: name,
  blackbox_dir: "/data/observatory/blackbox",
  own_network: own_network,
  client_networks: client_networks,
  # 0 (the default): join the client network at power-on, the access point
  # only if it does not join. Above 0: the access point first for that long
  # after every power-on, and a phone that joins in that time keeps it.
  ap_window_ms: String.to_integer(System.get_env("OBS_AP_WINDOW_S", "0")) * 1000,
  # a client network not joined in this long after power-on gives way to the
  # access point; once joined, a drop is only ever rejoined
  home_wifi_ms: 45_000,
  # from that fallback access point, with no phone on it, try the client again
  client_retry_ms: String.to_integer(System.get_env("OBS_CLIENT_RETRY_S", "180")) * 1000,
  wifi_file: "/data/observatory/wifi.etf"

# What this box plugs into the controller (Controller.Extensions): its own
# Network page, and the captive portal that opens the Observatory when a phone
# joins the access point. Both live in this app, next to the radio they drive.
# Nothing from the stamping Mac's Stamp a Box is in the image at all: the provision
# app is not a dependency here.
config :controller,
  extensions: [
    %{
      bare:
        for({path, action} <- [
              {"/hotspot-detect.html", :apple},
              {"/library/test/success.html", :apple},
              {"/generate_204", :redirect},
              {"/gen_204", :redirect},
              {"/connecttest.txt", :redirect},
              {"/ncsi.txt", :redirect},
              {"/redirect", :redirect},
              {"/portal", :portal},
              {"/portal/continue", :continue}
            ],
            do: {:get, path, Firmware.Web.Captive, action}),
      routes: [
        {:live, "/network", Firmware.Web.NetworkLive, :index},
        {:live, "/network/wifi", Firmware.Web.NetworkLive, :wifi},
        {:live, "/network/join", Firmware.Web.NetworkLive, :join}
      ],
      home: [
        {"Plumbing", {"Network", "/network", "The Wi-Fi radio: access point or client, the networks it knows, power", "/docs/network"}}
      ]
    }
  ]

config :mdns_lite,
  hosts: [:hostname, name],
  ttl: 120,
  services: [
    # the page, so it shows up in Safari's Bonjour list and anything else that looks
    %{protocol: "http", transport: "tcp", port: 80},
    %{protocol: "ssh", transport: "tcp", port: 22},
    %{protocol: "sftp-ssh", transport: "tcp", port: 22},
    %{protocol: "epmd", transport: "tcp", port: 4369}
  ]

# ---- observatory ------------------------------------------------------------------
# Watch USB for EQDIR cables; one driver per mount, none when unplugged.
config :mount,
  mounts: :auto,
  simulate_when_empty: false,
  # The same soft limits the Mac uses, degrees from home, armed by
  # Mount.set_home/1. Without them a box that can be driven from a phone could
  # swing the tube into its own tripod.
  limits: %{ra: {-100.0, 100.0}, dec: {-175.0, 175.0}}

# ---- the telescope's own page ------------------------------------------------------
# The box serves the same page the Mac does, on port 80, so typing its
# address into a phone is all it takes, on either network.
config :controller, Controller.Endpoint,
  url: [host: name <> ".local"],
  adapter: Bandit.PhoenixAdapter,
  http: [ip: {0, 0, 0, 0}, port: 80],
  server: true,
  check_origin: false,
  render_errors: [formats: [html: Controller.ErrorHTML, json: Controller.ErrorJSON], layout: false],
  pubsub_server: Telescope.PubSub,
  live_view: [signing_salt: "4T+tSHI9"],
  # new each build: a reflash signs everyone out, which is fine for a box
  secret_key_base: :crypto.strong_rand_bytes(48) |> Base.encode64()

# The root filesystem is read-only. Anything the page saves lives on /data,
# which survives reboots and firmware updates.
config :controller, settings_path: "/data/observatory/settings.json"
config :provision, scripts_dir: "/data/observatory/stamps"

# Nodes find each other over Erlang distribution; the Mac connects with
# `Node.connect(:"telescope@telescope.local")` (see Firmware.Distribution).
config :libcluster, topologies: []

config :firmware, node_name: System.get_env("OBSERVATORY_NODE", "telescope")
