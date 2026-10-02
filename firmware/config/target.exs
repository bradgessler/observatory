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

ap_window_ms = String.to_integer(System.get_env("OBS_AP_WINDOW_S", "0")) * 1000

# What wlan0 is at power-on. With a client network stamped in: a client of it,
# so the access point never beacons at boot (a phone that knows it would grab
# it and hold the box there), and a box whose firmware app fails to start is
# still on the network. Firmware.Wireless takes over from there, and makes it
# the access point only if the client does not join. With no client network,
# or an access point window asked for: the access point.
boot_wlan0 =
  if client_networks != [] and ap_window_ms == 0 do
    %{
      type: VintageNetWiFi,
      vintage_net_wifi: %{networks: Enum.map(client_networks, &Map.put(&1, :scan_ssid, 1)), bgscan: {:simple, "30:-70:3600"}},
      ipv4: %{method: :dhcp}
    }
  else
    own_network
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
    {"wlan0", boot_wlan0}
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
  ap_window_ms: ap_window_ms,
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
# ---- Bluetooth ----------------------------------------------------------------------
# The Pi 3's Bluetooth and Wi-Fi share one chip and one antenna, and joining
# Wi-Fi is what a box must get right at power-on, so Bluetooth waits 20 s
# with its radio idle (Firmware.Bluetooth).
config :firmware, bluetooth: [start_after_ms: 20_000]

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
        {:live, "/network/join", Firmware.Web.NetworkLive, :join},
        {:live, "/bluetooth", Firmware.Web.BluetoothLive, :index}
      ],
      home: [
        {"System", {"Network", "/network", "The Wi-Fi radio: access point or client, the networks it knows, power", "/docs/network", "wifi"}},
        {"System", {"Bluetooth", "/bluetooth", "The Bluetooth radio and every device it hears", "/docs/bluetooth", "bluetooth"}}
      ]
    }
  ]

node_name = System.get_env("OBSERVATORY_NODE", "telescope")

config :mdns_lite,
  hosts: [:hostname, name],
  # the name a Bonjour browser shows, and the Mac's Devices page lists
  instance_name: name,
  ttl: 120,
  services: [
    # the page, so it shows up in Safari's Bonjour list and anything else that looks
    %{protocol: "http", transport: "tcp", port: 80},
    %{protocol: "ssh", transport: "tcp", port: 22},
    %{protocol: "sftp-ssh", transport: "tcp", port: 22},
    # the node, by its exact name: a Mac on the network finds the box and joins
    # it from its Devices page (Telescope.Boxes); a name that differs by a
    # letter is refused, so it is said here rather than guessed
    %{protocol: "epmd", transport: "tcp", port: 4369, txt_payload: ["node=#{node_name}@#{name}.local"]}
  ]

# ---- the clock ----------------------------------------------------------------------
# No internet time in a field, and no real-time clock: the first phone to open
# the Site page sets the clock when the network has not (Controller.Clock).
config :controller, clock_from_browser: true

# ---- the game pad ----------------------------------------------------------------
# A box's pad is how it is driven in the field: armed from boot. Holding the
# trigger is what moves the scope, and letting go stops it (Input.Mapper).
config :input, armed_at_start: true

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
# the database beside it: settings and the frames on the card (#107)
config :controller, Controller.Repo, database: "/data/observatory/observatory.db"

# The plate solver's Tycho-2 indexes (hundreds of MB) live on /data too, not
# in the image. Without this the solver looked in ~/.observatory, found
# nothing, and every photo went to the Mac over the network: fine at home,
# nothing at all in a field.
config :controller, :solver, index_config: "/data/astrometry/astrometry.cfg"
config :provision, scripts_dir: "/data/observatory/stamps"

# Nodes find each other over Erlang distribution; the Mac connects with
# `Node.connect(:"telescope@telescope.local")` (see Firmware.Distribution).
config :libcluster, topologies: []

config :firmware,
  node_name: node_name,
  # the cluster's shared secret, the same as a Mac's (config/dev.exs)
  cookie: String.to_atom(System.get_env("OBSERVATORY_COOKIE", "observatory"))
