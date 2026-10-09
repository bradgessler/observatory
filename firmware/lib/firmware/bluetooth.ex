defmodule Firmware.Bluetooth do
  @moduledoc """
  The box's Bluetooth: BlueZ, the standard Linux stack, driven from Elixir by
  the `bluez` package, which starts and supervises `dbus-daemon` and
  `bluetoothd` itself (`rest_for_one`: the daemons, then its clients).

  This process owns that whole tree and is its circuit breaker. Bluetooth is
  a convenience on a telescope, never a dependency: a radio that will not
  start, a daemon that keeps dying, a firmware that is missing must cost the
  box its Bluetooth and nothing else. So the tree is started linked, with
  exits trapped: when it dies this process notes why, waits (5 s, 30 s,
  2 min, then every 10 min) and starts it again. It never crashes itself,
  so nothing above it ever sees Bluetooth fail, and the mount, the Wi-Fi and
  the pad keep going.

  ## Power-on

  The Pi 3's Bluetooth and Wi-Fi are one chip on one 2.4 GHz antenna, and
  joining Wi-Fi is the one thing a box must get right at power-on. So the
  stack starts `start_after_ms` after this process (20 s on a box), with
  the radio idle until then.

  ## The radio watchdog

  The Pi's radio driver is built into the kernel, and attaches `hci0` 1.5 s
  into boot: before the root filesystem is mounted, so the chip's firmware
  patch (`/lib/firmware/brcm/*.hcd`) cannot be found, and while the camera
  and codec drivers load, so a long reply from the chip can be lost
  (`firmware Patch file not found`, `command 0x1003 tx timeout`, `Reading
  local name failed`: seen on the box, a different one each boot). `hci0`
  exists, but it never finished setting up, and BlueZ never shows an
  adapter. Detaching and attaching the driver again with the box up and
  quiet brings it up every time.

  So the first start of the stack does exactly that first
  (`reattach_at_start`, on by default): power-on is the same every time, no
  waiting to notice. And for anything else, every 5 s, off to the side,
  this checks:

    * an adapter in BlueZ: running; nothing to do.
    * `hci0` in the kernel but no adapter for 20 s: reattach its driver
      (whichever it is: the Pi's UART radio, a USB dongle), up to 3 times a
      boot. Then stop the stack and say so (`:radio_failed`);
      `restart/0`, the Restart Radio key, is the manual path.
    * no `hci*` at all for 30 s: no radio on this board (`:no_radio`). The
      stack stops rather than log its search every 20 s onto the SD card,
      and the kernel is looked at again every minute, for a dongle plugged
      in later.

  ## Scanning

  Passive by default: the radio only listens, about 10% of the time
  (`/etc/bluetooth/main.conf`). Measured on the box, that leaves Wi-Fi
  as it was (16-23 ms ping against 14-19 ms with Bluetooth off), and every
  reading a device broadcasts still arrives. Active scanning asks each
  device for its scan response, where some put their name, and more than
  doubles Wi-Fi latency (44 ms), so it runs only as a burst, `active_scan/1`.
  BlueZ keeps the names it learns on `/data`, so a device named once stays
  named.

      Firmware.Bluetooth.status()
      Firmware.Bluetooth.active_scan(20_000)
      Firmware.Bluetooth.restart()
  """
  use GenServer
  require Logger

  alias Firmware.Bluetooth.Radio

  @compile {:no_warn_undefined, [Bluez, Bluez.Client]}

  @backoff_ms [5_000, 30_000, 120_000, 600_000]
  @bluetoothd "/usr/libexec/bluetooth/bluetoothd"
  @check_ms 5_000
  @look_again_ms 60_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  What Bluetooth is doing:

    * `state`: `:starting`, `:running` (an adapter is up), `{:restarting,
      in_ms}` (the stack died), `:no_radio`, `:radio_failed` (the kernel's
      radio never came up), `:unavailable` (no BlueZ in this system).
    * `adapter`: `%{address:, name:, path:, powered:}` once one is up.
    * `scan`: `:passive`, or `:active` during a burst (`active_left_ms`).
    * `resets`: driver reattaches this boot; `failures`: stack restarts.
  """
  def status do
    GenServer.call(__MODULE__, :status)
  catch
    :exit, _ ->
      %{state: :not_running, adapter: nil, scan: nil, active_left_ms: 0, resets: 0, failures: 0, last_error: nil}
  end

  @doc """
  The radios BlueZ is driving: `[%{address:, name:, powered:, path:}]`, or
  `[]` while it is down or the kernel found none. Asked of the scanner
  directly, never through this process, so a slow stack cannot hold up
  `status/0`.
  """
  def adapters, do: Bluez.Client.adapters_info()

  @doc """
  Scan actively for `ms` (default 20 s), then back to passive. Returns
  `:ok`, or `{:error, :not_running}` when there is no adapter to scan with.
  """
  def active_scan(ms \\ 20_000) when is_integer(ms) and ms > 0, do: call({:active_scan, ms})

  @doc """
  Start over: stop the stack, forget the driver resets this boot, reattach
  the radio's driver, and start again. The manual path after
  `:radio_failed`, and harmless any other time.
  """
  def restart, do: call(:restart)

  defp call(msg) do
    GenServer.call(__MODULE__, msg)
  catch
    :exit, _ -> {:error, :not_running}
  end

  # -- the process ------------------------------------------------------------------

  @impl true
  def init(opts) do
    Process.flag(:trap_exit, true)
    # a system without BlueZ says so at once, not after the wait
    bluez? = File.exists?(@bluetoothd)
    if bluez?, do: Process.send_after(self(), :start, Keyword.get(opts, :start_after_ms, 0))
    :timer.send_interval(@check_ms, :check)

    {:ok,
     %{
       opts: opts,
       tree: nil,
       state: if(bluez?, do: :starting, else: :unavailable),
       failures: 0,
       last_error: nil,
       adapter: nil,
       active_until: nil,
       radio: Radio.new(now()),
       checking: nil,
       scan_asked: nil,
       scan_asked_at: 0,
       reattach_first: Keyword.get(opts, :reattach_at_start, true)
     }}
  end

  @impl true
  def handle_call(:status, _from, s) do
    left = if s.active_until, do: max(s.active_until - now(), 0), else: 0

    reply = %{
      state: s.state,
      adapter: s.adapter,
      scan: if(s.state == :running, do: desired_scan(s)),
      active_left_ms: left,
      resets: s.radio.resets,
      failures: s.failures,
      last_error: s.last_error
    }

    {:reply, reply, s}
  end

  def handle_call({:active_scan, ms}, _from, %{adapter: %{}} = s) do
    apply_scan(:active)
    {:reply, :ok, %{s | active_until: now() + ms, scan_asked: :active, scan_asked_at: now()}}
  end

  def handle_call({:active_scan, _}, _from, s), do: {:reply, {:error, :not_running}, s}

  def handle_call(:restart, _from, s) do
    Logger.info("Bluetooth: restart asked for")
    s = stop_tree(s)
    # the next start sets the radio up again first, as at power-on
    Process.send_after(self(), :start, 1_000)
    {:reply, :ok, %{s | state: :starting, adapter: nil, failures: 0, last_error: nil, radio: Radio.new(now()), reattach_first: true}}
  end

  @impl true
  def handle_info(:start, %{tree: pid} = s) when is_pid(pid), do: {:noreply, s}

  # the first start: set the radio up again now that /lib/firmware is there,
  # then start the stack (off to the side: it sleeps between unbind and bind)
  def handle_info(:start, %{reattach_first: true} = s) do
    me = self()

    spawn(fn ->
      if kernel_radio?() do
        Logger.info("Bluetooth: setting the radio up again, now that its firmware can be read")
        reattach_driver()
      end

      send(me, :start)
    end)

    {:noreply, %{s | reattach_first: false}}
  end

  def handle_info(:start, s) do
    cond do
      not File.exists?(@bluetoothd) ->
        Logger.info("Bluetooth: this system has no BlueZ; off")
        {:noreply, %{s | state: :unavailable}}

      # the old tree is still shutting down; its name is not free yet
      Process.whereis(Bluez) ->
        Process.send_after(self(), :start, 500)
        {:noreply, s}

      true ->
        case Bluez.start_link(bluez_opts(s.opts)) do
          {:ok, pid} ->
            Logger.info("Bluetooth: stack started")
            {:noreply, %{s | tree: pid, state: :starting, radio: Radio.started(s.radio, now())}}

          {:error, why} ->
            {:noreply, retry(s, why)}
        end
    end
  end

  # every 5 s while the stack runs (every minute while there is no radio):
  # look at the radio off to the side, since the scanner can be slow to
  # answer, one look at a time
  def handle_info(:check, %{checking: nil} = s) do
    cond do
      is_pid(s.tree) -> {:noreply, look(s, true)}
      s.state == :no_radio and now() - s.radio.last_look >= @look_again_ms -> {:noreply, look(s, false)}
      true -> {:noreply, s}
    end
  end

  def handle_info(:check, s), do: {:noreply, s}

  def handle_info({:checked, ref, seen}, %{checking: ref} = s) do
    s = %{s | checking: nil}

    cond do
      s.state == :no_radio and seen.hci ->
        Logger.info("Bluetooth: a radio appeared; starting")
        send(self(), :start)
        {:noreply, %{s | state: :starting, radio: Radio.new(now())}}

      s.state == :no_radio ->
        {:noreply, %{s | radio: %{s.radio | last_look: now()}}}

      is_pid(s.tree) ->
        {:noreply, act(Radio.decide(s.radio, seen, now()), seen, s)}

      # the stack stopped while we looked
      true ->
        {:noreply, s}
    end
  end

  def handle_info({:checked, _, _}, s), do: {:noreply, s}

  # the BlueZ tree went down (it gives up after its own restart budget)
  def handle_info({:EXIT, pid, why}, %{tree: pid} = s),
    do: {:noreply, retry(%{s | tree: nil, adapter: nil}, why)}

  def handle_info({:EXIT, _pid, _why}, s), do: {:noreply, s}
  def handle_info(_, s), do: {:noreply, s}

  @impl true
  def terminate(_why, s), do: stop_tree(s)

  # -- what a look at the radio leads to ------------------------------------------------

  defp act({:up, radio}, seen, s) do
    adapter = hd(seen.adapters)
    if s.adapter == nil, do: Logger.info("Bluetooth: adapter #{adapter.address} up (#{adapter.name})")
    s = %{s | state: :running, adapter: adapter, radio: radio}
    s = if s.active_until && s.active_until <= now(), do: %{s | active_until: nil}, else: s
    want = desired_scan(s)

    # set the scan the scanner is not doing; a refusal is tried again after
    # 30 s, not on every look
    if seen.mode != want and (s.scan_asked != want or now() - s.scan_asked_at >= 30_000) do
      apply_scan(want)
      %{s | scan_asked: want, scan_asked_at: now()}
    else
      s
    end
  end

  defp act({:wait, radio}, _seen, s), do: %{s | radio: radio}

  defp act({:reattach, radio}, _seen, s) do
    Logger.warning("Bluetooth: hci0 is there but never came up; reattaching its driver (#{radio.resets} of #{Radio.max_resets()})")
    spawn(fn -> reattach_driver() end)
    %{s | radio: radio, adapter: nil}
  end

  defp act({:failed, radio}, _seen, s) do
    Logger.error("Bluetooth: the radio did not come up after #{radio.resets} driver resets; stopped until Restart Radio")
    %{stop_tree(s) | state: :radio_failed, radio: radio, adapter: nil, last_error: "radio did not come up"}
  end

  defp act({:no_radio, radio}, _seen, s) do
    Logger.info("Bluetooth: no radio on this board; looking again every minute")
    %{stop_tree(s) | state: :no_radio, radio: radio, adapter: nil}
  end

  defp look(s, running?) do
    me = self()
    ref = make_ref()

    spawn(fn ->
      seen = %{hci: kernel_radio?(), adapters: if(running?, do: adapters(), else: []), mode: scan_mode()}
      send(me, {:checked, ref, seen})
    end)

    %{s | checking: ref}
  end

  defp desired_scan(s), do: if(s.active_until && s.active_until > now(), do: :active, else: :passive)

  defp stop_tree(%{tree: pid} = s) when is_pid(pid) do
    Process.unlink(pid)
    Process.exit(pid, :shutdown)
    %{s | tree: nil}
  end

  defp stop_tree(s), do: s

  defp retry(s, why) do
    failures = s.failures + 1
    delay = Enum.at(@backoff_ms, failures - 1, List.last(@backoff_ms))
    Logger.warning("Bluetooth: stopped (#{inspect(why, limit: 8)}); starting again in #{div(delay, 1000)} s")
    Process.send_after(self(), :start, delay)
    %{s | state: {:restarting, delay}, failures: failures, last_error: inspect(why, limit: 8)}
  end

  # The scanner answers only once its own setup is done, and a mode change
  # waits on BlueZ, so it is asked from a throwaway process: this one never
  # blocks on the stack it guards. Unlinked, and every exit caught.
  defp apply_scan(mode) do
    spawn(fn ->
      try do
        case Bluez.Client.set_mode(mode) do
          :ok -> Logger.info("Bluetooth: scanning #{mode}")
          other -> Logger.warning("Bluetooth: #{mode} scan refused (#{inspect(other)})")
        end
      catch
        :exit, why -> Logger.warning("Bluetooth: #{mode} scan not set (#{inspect(why, limit: 8)})")
      end
    end)
  end

  defp scan_mode do
    Bluez.Client.configured_mode()
  rescue
    _ -> nil
  end

  defp bluez_opts(opts) do
    [
      # no bluez-alsa in this system: scanning, GATT and pairing only
      audio: false,
      client: [on_advertisement: &Firmware.Bluetooth.Nearby.heard/1]
    ] ++ Keyword.get(opts, :bluez, [])
  end

  # -- the kernel's side -----------------------------------------------------------------

  defp kernel_radio?, do: Path.wildcard("/sys/class/bluetooth/hci*") != []

  @doc """
  Detach and attach the driver behind each `hci*`, the way unplugging and
  plugging it back would: the Pi's UART radio (`hci_uart_bcm`, device
  `serial0-0`) or a USB dongle (`btusb`, its interface). Whatever the
  driver, the kernel runs the radio's setup again from the start.
  """
  def reattach_driver(root \\ "/sys") do
    for hci <- Path.wildcard(Path.join(root, "class/bluetooth/hci*")),
        {:ok, device} <- [realpath(Path.join(hci, "device"))],
        {:ok, driver} <- [realpath(Path.join(device, "driver"))] do
      id = Path.basename(device)
      unbind = File.write(Path.join(driver, "unbind"), id)
      Process.sleep(1_000)
      bind = File.write(Path.join(driver, "bind"), id)
      Logger.info("Bluetooth: reattached #{id} to #{Path.basename(driver)} (#{inspect({unbind, bind})})")
      {id, unbind, bind}
    end
  end

  @doc """
  A path with every symlink in it resolved, like `realpath(3)`. sysfs is
  links all the way down (`/sys/class/bluetooth/hci0` is one, and its
  `device` is `../../../serial0-0` from where the first one lands), so a
  link is only ever read relative to a directory already resolved.
  """
  def realpath(path), do: walk(Path.split(Path.expand(path)), [], 0)

  defp walk(_, _, hops) when hops > 40, do: {:error, :eloop}
  defp walk([], done, _), do: {:ok, Path.join(Enum.reverse(done))}

  defp walk([part | rest], done, hops) do
    here = Path.join(Enum.reverse([part | done]))

    case File.read_link(here) do
      {:ok, target} ->
        base = if done == [], do: "/", else: Path.join(Enum.reverse(done))
        walk(Path.split(Path.expand(target, base)) ++ rest, [], hops + 1)

      {:error, :einval} ->
        walk(rest, [part | done], hops)

      {:error, _} = error ->
        error
    end
  end

  defp now, do: System.monotonic_time(:millisecond)
end

defmodule Firmware.Bluetooth.Radio do
  @moduledoc """
  What to do about the radio, given one look at it: pure, so every case is
  a test. `Firmware.Bluetooth` looks every 5 s and acts on the answer.

  A look is `%{hci: kernel has an hci*, adapters: BlueZ's adapters}`.
  """

  @grace_ms 20_000
  @no_radio_ms 30_000
  @max_resets 3

  def max_resets, do: @max_resets

  @doc "A radio just started watching at `now`."
  def new(now), do: %{since: now, resets: 0, last_look: now}

  @doc "The stack (re)started: give the radio its grace period again, resets kept."
  def started(radio, now), do: %{radio | since: now}

  @doc """
  `{:up | :wait | :reattach | :failed | :no_radio, radio}`.

    * an adapter: `:up`.
    * no `hci*` for 30 s: `:no_radio`.
    * `hci*` but no adapter for 20 s: `:reattach` (a fresh 20 s after
      each), and after #{@max_resets} of those, `:failed`.
    * otherwise `:wait`.
  """
  def decide(radio, seen, now) do
    radio = %{radio | last_look: now}
    waited = now - radio.since

    cond do
      seen.adapters != [] -> {:up, %{radio | since: now}}
      not seen.hci and waited >= @no_radio_ms -> {:no_radio, radio}
      not seen.hci -> {:wait, radio}
      waited < @grace_ms -> {:wait, radio}
      radio.resets >= @max_resets -> {:failed, radio}
      true -> {:reattach, %{radio | resets: radio.resets + 1, since: now}}
    end
  end
end

defmodule Firmware.Bluetooth.Nearby do
  @moduledoc """
  Every Bluetooth Low Energy device heard lately: address, name, signal,
  and the manufacturer and service data it broadcasts (where batteries and
  sensors put their readings). Its own process, apart from the BlueZ tree,
  so the list survives Bluetooth restarting; adverts arrive by cast, so a
  slow reader never holds up the scanner.
  """
  use GenServer

  @forget_ms 120_000

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Devices heard in the last two minutes, strongest first."
  def list do
    GenServer.call(__MODULE__, :list)
  catch
    :exit, _ -> []
  end

  @doc false
  def heard(advert), do: GenServer.cast(__MODULE__, {:heard, advert, System.monotonic_time(:millisecond)})

  @impl true
  def init(_), do: {:ok, %{}}

  @impl true
  def handle_call(:list, _from, devices) do
    cutoff = System.monotonic_time(:millisecond) - @forget_ms
    devices = Map.filter(devices, fn {_, d} -> d.at > cutoff end)
    {:reply, devices |> Map.values() |> Enum.sort_by(&(-&1.rssi)), devices}
  end

  @impl true
  def handle_cast({:heard, %{address: address, rss: rssi, raw_data: raw} = advert, at}, devices) do
    ad = parse_ad(raw)
    key = mac(address)
    old = Map.get(devices, key, %{address: key, name: nil, manufacturer: %{}, service: %{}, uuids: []})

    device = %{
      old
      | name: ad[:name] || old.name,
        manufacturer: Map.merge(old.manufacturer, ad[:manufacturer] || %{}),
        service: Map.merge(old.service, ad[:service] || %{}),
        uuids: Enum.uniq(old.uuids ++ (ad[:uuids] || []))
    }

    {:noreply, Map.put(devices, key, Map.merge(device, %{rssi: rssi, random: advert[:address_type] == 1, at: at}))}
  end

  def handle_cast(_, devices), do: {:noreply, devices}

  defp mac(n) when is_integer(n) do
    <<n::48>> |> :binary.bin_to_list() |> Enum.map_join(":", &(Integer.to_string(&1, 16) |> String.pad_leading(2, "0")))
  end

  defp mac(s), do: to_string(s)

  @doc """
  Advertising data: length, type, value, repeated. Name, 16-bit service
  UUIDs, service data, and manufacturer data by company id (kept as hex
  until we know how a given device lays its readings out).
  """
  def parse_ad(data), do: parse_ad(data, %{})

  defp parse_ad(<<len, rest::binary>>, acc) when len > 0 and byte_size(rest) >= len do
    n = len - 1
    <<type, value::binary-size(^n), tail::binary>> = rest

    acc =
      case type do
        t when t in [0x08, 0x09] ->
          Map.put(acc, :name, value)

        t when t in [0x02, 0x03] ->
          Map.update(acc, :uuids, uuids16(value), &(&1 ++ uuids16(value)))

        0x16 when byte_size(value) >= 2 ->
          <<uuid::little-16, sdata::binary>> = value
          Map.update(acc, :service, %{hex4(uuid) => Base.encode16(sdata)}, &Map.put(&1, hex4(uuid), Base.encode16(sdata)))

        0xFF when byte_size(value) >= 2 ->
          <<company::little-16, mdata::binary>> = value
          Map.update(acc, :manufacturer, %{hex4(company) => Base.encode16(mdata)}, &Map.put(&1, hex4(company), Base.encode16(mdata)))

        _ ->
          acc
      end

    parse_ad(tail, acc)
  end

  defp parse_ad(_, acc), do: acc

  defp uuids16(value), do: for(<<u::little-16 <- value>>, do: hex4(u))
  defp hex4(n), do: n |> Integer.to_string(16) |> String.pad_leading(4, "0")
end
