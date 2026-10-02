defmodule Firmware.Blackbox do
  @moduledoc """
  What the box was doing when it went down, kept where a reset cannot reach:
  the SD card.

  Everything else about a running box lives in memory: the log, the events,
  the mount's state. An app that crashes inside the VM keeps all of that. Only
  the whole box going down wipes it, and that is exactly the failure worth
  explaining: power sagging as the motors start (an instant reset, nothing
  written), the VM freezing until `heart` reboots the board (30 s later), or
  the kernel falling over. So this keeps three things in `:blackbox_dir`:

    * `flight.log`: a line every 250 ms while any axis runs, every 5 s when
      idle, and one for every event (a slew, a stop, a link lost) the moment
      it happens. Each line: seconds since the kernel booted, the Pi's
      under-voltage and throttling flags, the Wi-Fi connection, VM memory and
      run queue, and each mount's axes. Written and synced, so a reset loses
      at most the line being written. The five boots before are
      `flight.1.log` (the last) to `flight.5.log`.
    * `boots.log`: one line per boot, saying whether the one before it shut
      down cleanly or just stopped, and its last flight line.
    * `log`, `log.0`...: the Elixir log, info and up, rotated at 4 × 512 KB.

  Reading the end of `flight.1.log` after a reset: lines that stop mid-move
  with under-voltage set is power; lines that stop ~30 s before the next boot
  is a frozen VM; a clean shutdown says so in `boots.log`.

  A boot also emits a `:system, :boot` event, so the Events page opens on it.
  """
  use GenServer
  require Logger

  @compile {:no_warn_undefined, [VintageNet, Mount]}

  @moving_ms 250
  @idle_ms 5_000
  @throttled "/sys/devices/platform/soc/soc:firmware/get_throttled"

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "How the previous boot ended, and its last flight lines."
  def previous(lines \\ 20) do
    dir = dir()

    %{
      ended: read_ending(dir),
      tail: tail(Path.join(dir, "flight.1.log"), lines)
    }
  end

  @doc "The last lines of this boot's flight log."
  def current(lines \\ 20), do: tail(Path.join(dir(), "flight.log"), lines)

  @doc "One line per boot, newest last."
  def boots(lines \\ 20), do: tail(Path.join(dir(), "boots.log"), lines)

  # -- the process ------------------------------------------------------------------------

  @impl true
  def init(_) do
    # terminate/2 runs on a clean shutdown only if exits are trapped; a reset
    # or a heart reboot never gets here, and that is the point
    Process.flag(:trap_exit, true)
    dir = dir()
    File.mkdir_p!(dir)

    marker = Path.join(dir, "running")
    flight = Path.join(dir, "flight.log")
    last = tail(flight, 1) |> List.first()

    ended =
      cond do
        File.exists?(marker) -> :unclean
        last -> :clean
        true -> :first
      end

    # the last five boots' flight logs, newest first: a crash's detail must
    # survive the reboot after it, and the one after that
    if File.exists?(flight) do
      for n <- 4..1//-1, File.exists?(Path.join(dir, "flight.#{n}.log")),
          do: File.rename(Path.join(dir, "flight.#{n}.log"), Path.join(dir, "flight.#{n + 1}.log"))

      File.rename(flight, Path.join(dir, "flight.1.log"))
    end

    boot_line = "#{DateTime.utc_now() |> DateTime.to_iso8601()} boot; previous: #{ended}#{if last, do: "; last: " <> last, else: ""}"
    append_sync(Path.join(dir, "boots.log"), boot_line <> "\n")
    File.write!(Path.join(dir, "ending"), to_string(ended))
    File.write!(marker, "")

    Telescope.Events.emit(:system, :boot, %{previous: ended, last: last})
    if ended == :unclean, do: Logger.error("Previous boot ended without a shutdown. Its last record: #{last}")

    add_log_file(dir)
    Telescope.Events.subscribe()

    {:ok, io} = File.open(flight, [:append, :binary, :raw])
    send(self(), :sample)
    {:ok, %{io: io, marker: marker, snaps: %{}, subscribed: MapSet.new(), timer: nil, kmsg: kmsg()}}
  end

  # The kernel's own messages, as they happen: a USB device dropping (the
  # mount's serial cable), the Wi-Fi driver complaining, the watchdog. The ring
  # buffer they live in is memory, gone at a reset; these lines are not.
  defp kmsg do
    if File.exists?("/dev/kmsg") and System.find_executable("cat") do
      Port.open({:spawn_executable, System.find_executable("cat")}, [:binary, {:line, 400}, args: ["/dev/kmsg"]])
    end
  end

  @kmsg_worth ~r/volt|usb|ftdi|ttyUSB|brcmf|mmc|watchdog|heart|oom|error|fail|reset|disconnect/i

  @impl true
  def handle_info(:sample, state) do
    state = watch_mounts(state)
    write(state.io, sample(state))
    ms = if moving?(state), do: @moving_ms, else: @idle_ms
    {:noreply, %{state | timer: Process.send_after(self(), :sample, ms)}}
  end

  # the mount starting to move: sample now and every 250 ms from here
  def handle_info({:mount, snap}, state) do
    was = moving?(state)
    state = %{state | snaps: Map.put(state.snaps, snap.id, snap)}

    if moving?(state) and not was do
      if state.timer, do: Process.cancel_timer(state.timer)
      send(self(), :sample)
      {:noreply, %{state | timer: nil}}
    else
      {:noreply, state}
    end
  end

  def handle_info({port, {:data, {_, line}}}, %{kmsg: port} = state) do
    if line =~ @kmsg_worth, do: write(state.io, "#{uptime()} kernel #{line}")
    {:noreply, state}
  end

  # every command, stop, link lost: written the moment it happens
  def handle_info({:event, e}, state) do
    write(state.io, "#{uptime()} event #{e.module}.#{e.name} by #{e.by} #{inspect(e.data, limit: 20)}")
    {:noreply, state}
  end

  def handle_info(_, state), do: {:noreply, state}

  @impl true
  def terminate(_reason, state) do
    write(state.io, "#{uptime()} shutdown")
    File.rm(state.marker)
  end

  # -- the record -------------------------------------------------------------------------

  defp sample(state) do
    mounts =
      state.snaps
      |> Enum.sort()
      |> Enum.map_join(" ", fn {id, s} -> "#{id}:#{if s.connected, do: "up", else: "down"} #{axes(s.axes)}" end)

    wlan = safe(fn -> VintageNet.get(["interface", "wlan0", "connection"]) end)

    "#{uptime()} thr=#{throttled()} wlan0=#{wlan} #{radio()} mem=#{div(:erlang.memory(:total), 1_048_576)}M rq=#{:erlang.statistics(:run_queue)} #{mounts}"
  end

  # Which access point it is on and how strong, and how many it can hear: a
  # slow join says whether the network was even there.
  defp radio do
    cur =
      case safe(fn -> VintageNet.get(["interface", "wlan0", "wifi", "current_ap"]) end) do
        %{ssid: ssid, signal_dbm: dbm} -> "on=#{ssid}/#{dbm}"
        _ -> "on=-"
      end

    heard = safe(fn -> VintageNet.get(["interface", "wlan0", "wifi", "access_points"]) end) || []
    strongest = heard |> Enum.sort_by(& &1.signal_dbm, :desc) |> Enum.take(3) |> Enum.map_join(",", &"#{&1.ssid}/#{&1.signal_dbm}")
    "#{cur} heard=#{length(heard)}[#{strongest}]"
  end

  defp axes(axes) do
    Enum.map_join(axes, " ", fn {axis, a} ->
      if a[:running], do: "#{axis}=run #{a[:speed]} #{a[:direction]}", else: "#{axis}=stop"
    end)
  end

  defp moving?(state), do: Enum.any?(state.snaps, fn {_, s} -> Enum.any?(s.axes, fn {_, a} -> a[:running] end) end)

  defp watch_mounts(state) do
    refs = safe(fn -> Mount.list() end) || []

    subscribed =
      Enum.reduce(refs, state.subscribed, fn ref, acc ->
        if MapSet.member?(acc, ref.id), do: acc, else: (Mount.subscribe(ref); MapSet.put(acc, ref.id))
      end)

    %{state | subscribed: subscribed}
  end

  # seconds since the kernel booted: a VM restart without a reboot shows as a
  # small VM uptime on a large kernel one
  defp uptime do
    case File.read("/proc/uptime") do
      {:ok, text} -> text |> String.split(" ") |> hd()
      _ -> "?"
    end
  end

  defp throttled do
    case File.read(@throttled) do
      {:ok, text} -> String.trim(text)
      _ -> "?"
    end
  end

  defp write(io, line) do
    _ = :file.write(io, line <> "\n")
    _ = :file.datasync(io)
    :ok
  end

  defp append_sync(path, text) do
    {:ok, io} = File.open(path, [:append, :binary, :raw])
    :file.write(io, text)
    :file.datasync(io)
    File.close(io)
  end

  defp add_log_file(dir) do
    _ = :logger.remove_handler(:blackbox)

    :logger.add_handler(:blackbox, :logger_std_h, %{
      level: :info,
      config: %{
        file: String.to_charlist(Path.join(dir, "log")),
        max_no_bytes: 512_000,
        max_no_files: 4,
        # synced every second: a reset loses at most the last second of log
        filesync_repeat_interval: 1_000
      },
      formatter: Logger.Formatter.new(format: "$date $time [$level] $message\n")
    })
  end

  defp read_ending(dir) do
    case File.read(Path.join(dir, "ending")) do
      {:ok, "unclean"} -> :unclean
      {:ok, "clean"} -> :clean
      _ -> :first
    end
  end

  defp tail(path, n) do
    case File.read(path) do
      {:ok, text} -> text |> String.split("\n", trim: true) |> Enum.take(-n)
      _ -> []
    end
  end

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end

  defp dir, do: Application.get_env(:firmware, :blackbox_dir, "/data/observatory/blackbox")
end
