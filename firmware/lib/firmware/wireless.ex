defmodule Firmware.Wireless do
  @moduledoc """
  One radio, two jobs: the box's own access point, and a client on your Wi-Fi
  network. The promise: whatever Wi-Fi is doing, power it on and there is a
  way in.

    * With a client network stamped in, `wlan0` boots as a client of it (its
      setting in config/target.exs), so the access point never beacons at
      power-on for a phone to grab; this then applies the full client
      settings (`client_config/1`). With none, it boots as the access point.
    * **Joined once, a client for the rest of the boot.** A drop (a sag as the
      motors start, an access point rebooting, a walk out of range and back)
      is not a reason to change networks: wpa_supplicant keeps rejoining, and
      this keeps it a client. Falling back on a drop is what turned one bad
      moment into a box stranded on its own access point.
    * **Not joined within `:home_wifi_ms` (45 s) of power-on** (the client
      network is not there: a field), the access point. With no phone on it,
      the client network is tried again every `:client_retry_ms` (3 min), so
      a box that booted before the router did finds its way home.
    * No client network known: the access point, the whole boot.
    * `:ap_window_ms` above 0 (`OBS_AP_WINDOW_S` at build) keeps the access
      point up for that long after every power-on first, and a phone that
      joins in that time keeps it for the boot. A way in that does not depend
      on the client network working: a network can be joined and still
      unreachable, and from the box's side that looks the same as working.
      Off by default: at home the box should just be on the network.

  Client networks are the one stamped in (`:client_networks`) until one is
  added or forgotten on the Network page; from then on the list in
  `:wifi_file` on /data, readable by root alone. VintageNet persists nothing
  (config/target.exs): a saved client config there would replace the access
  point at boot and break the promise.

  VintageNet does the retrying underneath: wpa_supplicant keeps reassociating
  by itself. This only decides which job the radio has.

  `Firmware.Web.NetworkLive` is its page.
  """
  use GenServer
  require Logger

  # VintageNet only exists on the device; keep the host build warning-free.
  @compile {:no_warn_undefined, [VintageNet]}

  @connection ["interface", "wlan0", "connection"]
  @clients ["interface", "wlan0", "wifi", "clients"]

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Stop trying client networks and bring up the access point now, for the rest of the boot."
  def own_network, do: GenServer.call(__MODULE__, :own_network)

  @doc "What `wlan0` is doing: `:home` (Wi-Fi client), `:own` (access point), or `:none`."
  def mode do
    case VintageNet.get_configuration("wlan0") do
      %{vintage_net_wifi: %{networks: [%{mode: :ap} | _]}} -> :own
      %{vintage_net_wifi: %{networks: [_ | _]}} -> :home
      _ -> :none
    end
  end

  @doc """
  Where the radio has been this boot, oldest first: `{phase, ms since boot}`,
  phase one of `:window` (access point, waiting for a phone), `:kept` (a phone
  joined in the window), `:client` (trying a client network), `:own` (access
  point for the rest of the boot).
  """
  def history, do: GenServer.call(__MODULE__, :history)

  @doc """
  What a lost connection means: once joined this boot, keep rejoining
  (`:rejoin`); never joined, count down to the access point (`:countdown`).
  """
  def on_drop(joined?), do: if(joined?, do: :rejoin, else: :countdown)

  @doc """
  After the window: stay the access point (`:kept`) if a phone is on it or has
  asked the captive portal anything, else try the client networks (`:client`),
  if there are any.
  """
  def after_window(ap_clients, seen?, known) do
    cond do
      ap_clients != [] or seen? -> :kept
      known == [] -> :own
      true -> :client
    end
  end

  # -- the Network page (Firmware.Web.NetworkLive) ---------------------------------------

  def status do
    %{known: known, phase: phase, power_save: power_save, window_left_s: left} = GenServer.call(__MODULE__, :state)
    mode = mode()
    current = if mode == :home, do: VintageNet.get(["interface", "wlan0", "wifi", "current_ap"])

    %{
      mode: mode,
      phase: phase,
      window_left_s: left,
      connection: VintageNet.get(@connection),
      client_ssid: current && current.ssid,
      # the network it is joined to, as heard from here: signal, band, channel
      signal: current && describe(current),
      # phones on its access point, by MAC address
      clients: if(mode == :own, do: length(VintageNet.get(@clients) || []), else: 0),
      power_save: power_save,
      networks: Enum.map(known, & &1.ssid),
      ap_ssid: own_config() |> get_in([:vintage_net_wifi, :networks]) |> hd() |> Map.get(:ssid),
      name: Application.get_env(:firmware, :name, "telescope") <> ".local",
      addresses: addresses()
    }
  end

  defp addresses do
    for ifname <- VintageNet.all_interfaces(),
        ifname != "lo",
        %{address: {_, _, _, _} = ip} <- VintageNet.get(["interface", ifname, "addresses"]) || [],
        do: %{ifname: ifname, address: ip |> :inet.ntoa() |> to_string()}
  end

  def scan do
    case VintageNet.scan("wlan0") do
      :ok -> :ok
      other -> {:error, other}
    end
  end

  def access_points do
    (VintageNet.get(["interface", "wlan0", "wifi", "access_points"]) || [])
    |> Enum.reject(&(&1.ssid in [nil, ""]))
    |> Enum.sort_by(& &1.signal_percent, :desc)
    |> Enum.uniq_by(& &1.ssid)
    |> Enum.map(&describe/1)
  end

  defp describe(ap) do
    %{
      ssid: ap.ssid,
      signal: ap.signal_percent,
      dbm: ap.signal_dbm,
      band: band(ap.band),
      channel: ap.channel,
      security: security(ap.flags)
    }
  end

  defp band(:wifi_2_4_ghz), do: "2.4 GHz"
  defp band(:wifi_5_ghz), do: "5 GHz"
  defp band(_), do: nil

  @doc "Remember a client network and join it now, falling back to the access point if it does not join."
  def join(ssid, password), do: GenServer.call(__MODULE__, {:join, ssid, password})

  @doc "Forget a client network. With none left, the radio is the access point, now and at every boot."
  def forget(ssid), do: GenServer.call(__MODULE__, {:forget, ssid})

  @doc """
  The VintageNet config for being a client of these networks, set to join as
  many access points as it can. What was proven first, and more only where a
  network insists:

    * **Matched by SSID, never BSSID**: any access point of the network will
      do, on either band the board's radio has (Pi 3 Model B and Zero 2 W:
      2.4 GHz; 3 B+, 4, 5: 2.4 and 5 GHz). `regulatory_domain` (US) is what
      opens the 5 GHz channels.
    * **Two blocks per password-protected network.** First, WPA-PSK with no
      management frame protection: the setting that has always joined, and
      it joins WPA2 and WPA2/WPA3-transition networks (UniFi's "WPA2/WPA3").
      Second, lower priority, for a network that refuses the first: WPA3-SAE
      and WPA-PSK-SHA256 with protected management frames required (WPA3
      only, or WPA2 with PMF required). wpa_supplicant tries the first; a
      network that rejects it gets that block disabled for a while and the
      next one tried. So a stricter network costs a few seconds, and nothing
      that joins today can stop joining. (The system's wpa_supplicant is 2.12
      built with WPA3; `test/wifi_config_test.exs` in apps/provision runs the
      Pi's own binary over this file.)
    * `scan_ssid=1`: asks for the network by name, so a hidden SSID is found
      and a join does not wait for a beacon.
    * `sae_pwe=2`: WPA3 by either method, hunting-and-pecking or
      hash-to-element, whichever the access point offers.
    * `bgscan` (`roam/0`): moves to a stronger access point of the same
      network instead of hanging on to the first.
    * Power save off after each join (`power_save_off/1`).
  """
  def client_config(networks) do
    %{
      type: VintageNetWiFi,
      vintage_net_wifi: %{networks: Enum.flat_map(networks, &blocks/1), bgscan: roam(), sae_pwe: 2},
      ipv4: %{method: :dhcp}
    }
  end

  defp blocks(%{psk: psk} = network) when is_binary(psk) and psk != "" do
    base = network |> Map.take([:ssid, :psk]) |> Map.put(:scan_ssid, 1)

    [
      Map.merge(base, %{key_mgmt: :wpa_psk, priority: 1}),
      Map.merge(base, %{key_mgmt: [:sae, :wpa_psk_sha256], ieee80211w: 2, priority: 0})
    ]
  end

  defp blocks(network), do: [network |> Map.take([:ssid]) |> Map.merge(%{key_mgmt: :none, scan_ssid: 1})]

  @doc """
  Roaming between the access points of one network (a house with several).
  A client network is matched by SSID only, never by BSSID, so any access
  point broadcasting it will do; but without a background scan wpa_supplicant
  keeps the one it joined until that link dies, however weak it gets. This
  scans every 30 s while the signal is below -70 dBm (every hour above it) and
  moves to a stronger access point of the same network.
  """
  def roam, do: {:simple, "30:-70:3600"}

  # -- the process ------------------------------------------------------------------------

  @impl true
  def init(_) do
    known = load_known()
    left = window()

    # wlan0 is already a client (a network was stamped in) or the access point
    state = %{known: known, phase: nil, timer: nil, window_ends: nil, power_save: :unknown, history: [], joined: false}

    state =
      cond do
        known == [] -> enter(state, :own)
        # no window (the default): the client network straight away
        left <= 0 -> try_client(state)
        true -> enter(%{state | timer: Process.send_after(self(), :window_over, left), window_ends: now() + left}, :window)
      end

    {:ok, state}
  end

  @impl true
  def handle_info(:window_over, state) do
    ap_clients = VintageNet.get(@clients) || []
    seen? = Firmware.Web.Captive.seen?()

    case after_window(ap_clients, seen?, state.known) do
      :kept ->
        Logger.info("A phone joined the access point in the first #{div(window(), 1000)} s; keeping it this boot")
        {:noreply, enter(%{state | timer: nil}, :kept)}

      :own ->
        {:noreply, enter(%{state | timer: nil}, :own)}

      :client ->
        {:noreply, try_client(%{state | timer: nil})}
    end
  end

  def handle_info({VintageNet, @connection, _old, new, _meta}, %{phase: :client} = state), do: {:noreply, watch(state, new)}
  def handle_info({VintageNet, @connection, _, _, _}, state), do: {:noreply, state}

  def handle_info(:give_up, %{phase: :client, joined: false} = state) do
    Logger.warning("Wi-Fi client not joined for #{wait()} ms; wlan0 becomes the access point, trying the client again in #{div(retry(), 1000)} s")
    Process.send_after(self(), :retry_client, retry())
    {:noreply, go_own(%{state | timer: nil})}
  end

  def handle_info(:give_up, state), do: {:noreply, %{state | timer: nil}}

  # The fallback access point, nobody on it: try the client network again.
  # With a phone on it, leave it be; that phone's only way in is this network.
  def handle_info(:retry_client, %{phase: :own, known: [_ | _]} = state) do
    if (VintageNet.get(@clients) || []) == [] do
      {:noreply, try_client(state)}
    else
      Process.send_after(self(), :retry_client, retry())
      {:noreply, state}
    end
  end

  def handle_info(:retry_client, state), do: {:noreply, state}

  def handle_info(:power_save_off, state) do
    result = power_save_off()
    if result != :ok, do: Logger.warning("Wi-Fi power save could not be turned off: #{inspect(result)}")
    {:noreply, %{state | power_save: if(result == :ok, do: :off, else: :unknown)}}
  end

  def handle_info(_, state), do: {:noreply, state}

  @impl true
  def handle_call(:own_network, _from, state) do
    state = go_own(%{state | timer: cancel(state.timer)})
    {:reply, :ok, state}
  end

  def handle_call(:history, _from, state), do: {:reply, Enum.reverse(state.history), state}

  def handle_call(:state, _from, state) do
    left = if state.phase == :window and state.window_ends, do: max(div(state.window_ends - now(), 1000), 0)
    {:reply, %{known: state.known, phase: state.phase, power_save: state.power_save, window_left_s: left}, state}
  end

  def handle_call({:join, ssid, password}, _from, state) do
    network =
      if password == "",
        do: %{ssid: ssid, key_mgmt: :none},
        else: %{ssid: ssid, key_mgmt: :wpa_psk, psk: password}

    known = Enum.reject(state.known, &(&1.ssid == ssid)) ++ [network]
    save_known(known)
    {:reply, :ok, try_client(%{state | known: known, timer: cancel(state.timer)})}
  end

  def handle_call({:forget, ssid}, _from, state) do
    known = Enum.reject(state.known, &(&1.ssid == ssid))
    save_known(known)
    state = %{state | known: known, timer: cancel(state.timer)}

    cond do
      known == [] -> {:reply, :ok, go_own(state)}
      state.phase == :client -> {:reply, :ok, try_client(state)}
      true -> {:reply, :ok, state}
    end
  end

  # -- the jobs ---------------------------------------------------------------------------

  defp try_client(state) do
    case VintageNet.configure("wlan0", client_config(state.known), persist: false) do
      :ok ->
        VintageNet.subscribe(@connection)
        # start waiting now; a join cancels it
        enter(%{state | timer: Process.send_after(self(), :give_up, wait())}, :client)

      error ->
        Logger.error("Could not configure the Wi-Fi client: #{inspect(error)}; staying the access point")
        go_own(state)
    end
  end

  defp go_own(state) do
    VintageNet.unsubscribe(@connection)
    _ = VintageNet.configure("wlan0", own_config(), persist: false)
    enter(state, :own)
  end

  defp enter(state, phase), do: %{state | phase: phase, history: [{phase, uptime_ms()} | state.history]}

  # Joined: stop the countdown, keep the radio awake, and from now on this boot
  # a drop is only ever rejoined. Not yet joined: the countdown started when
  # the client was configured keeps running; a flap does not restart it.
  defp watch(state, connection) when connection in [:lan, :internet] do
    send(self(), :power_save_off)
    %{state | timer: cancel(state.timer), joined: true}
  end

  defp watch(state, connection) do
    case on_drop(state.joined) do
      :rejoin ->
        Logger.warning("Wi-Fi client dropped (#{inspect(connection)}); rejoining, not falling back")
        state

      :countdown ->
        if state.timer, do: state, else: %{state | timer: Process.send_after(self(), :give_up, wait())}
    end
  end

  defp cancel(nil), do: nil

  defp cancel(timer) do
    Process.cancel_timer(timer)
    nil
  end

  # -- client networks, kept on /data -----------------------------------------------------

  defp load_known do
    with path when is_binary(path) <- Application.get_env(:firmware, :wifi_file),
         {:ok, bin} <- File.read(path),
         list when is_list(list) <- safe_decode(bin) do
      list
    else
      _ -> Application.get_env(:firmware, :client_networks, [])
    end
  end

  defp safe_decode(bin) do
    :erlang.binary_to_term(bin, [:safe])
  rescue
    _ -> nil
  end

  defp save_known(known) do
    if path = Application.get_env(:firmware, :wifi_file) do
      File.mkdir_p!(Path.dirname(path))
      File.write!(path, :erlang.term_to_binary(known))
      File.chmod!(path, 0o600)
    end
  end

  # -- power save -------------------------------------------------------------------------

  @doc """
  Turn Wi-Fi power save off on `wlan0`, through wpa_supplicant's control
  socket (`SET ps 0`, which it passes to the driver as nl80211 power save).

  The Pi 3's radio dozes between beacons by default. Asleep, it still wakes for
  broadcast and multicast, so it answers mDNS and ARP and looks present; but
  unicast (ping, the page, SSH) is buffered at the access point and, on this
  driver, often never delivered. A box that is joined, announced by name, and
  unreachable is exactly that. `iw` is not in the system image, so this goes
  the way wpa_supplicant itself would. Called on every join: the driver can
  put power save back after a reassociation.

  Its own socket path, never VintageNet's: binding that one would steal
  wpa_supplicant's notifications from VintageNet.
  """
  def power_save_off(ifname \\ "wlan0") do
    ctrl = "/tmp/vintage_net/wpa_supplicant/" <> ifname
    ours = "/tmp/vintage_net/wpa_supplicant/observatory-" <> ifname
    _ = File.rm(ours)

    case :gen_udp.open(0, [:local, :binary, active: false, ip: {:local, ours}]) do
      {:ok, socket} ->
        try do
          with :ok <- :gen_udp.send(socket, {:local, ctrl}, 0, "SET ps 0"),
               {:ok, {_, _, reply}} <- :gen_udp.recv(socket, 0, 2_000) do
            if String.starts_with?(reply, "OK"), do: :ok, else: {:error, String.trim(reply)}
          end
        after
          :gen_udp.close(socket)
          File.rm(ours)
        end

      error ->
        error
    end
  end

  # -- settings ---------------------------------------------------------------------------

  defp window, do: Application.get_env(:firmware, :ap_window_ms, 120_000)
  defp wait, do: Application.get_env(:firmware, :home_wifi_ms, 45_000)
  defp retry, do: Application.get_env(:firmware, :client_retry_ms, 180_000)
  defp own_config, do: Application.fetch_env!(:firmware, :own_network)
  defp now, do: System.monotonic_time(:millisecond)
  defp uptime_ms, do: :erlang.statistics(:wall_clock) |> elem(0)

  defp security(flags) do
    names = Enum.map(flags || [], &to_string/1)

    cond do
      Enum.any?(names, &String.contains?(&1, "sae")) -> "WPA3"
      Enum.any?(names, &String.contains?(&1, "wpa2")) -> "WPA2"
      Enum.any?(names, &String.contains?(&1, "wpa")) -> "WPA"
      Enum.any?(names, &String.contains?(&1, "eap")) -> "Enterprise"
      true -> "Open"
    end
  end
end
