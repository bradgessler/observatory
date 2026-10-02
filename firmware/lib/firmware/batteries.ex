defmodule Firmware.Batteries do
  @moduledoc """
  The charge of every Anker SOLIX battery the box can hear, with nothing to
  pick or pair: plug the box into one, and its charge, draw and temperature
  are on the Bluetooth page and in the flight log.

  Every 10 s this looks at what the radio hears (`Firmware.Bluetooth.Nearby`)
  for names starting "Anker SOLIX" and starts a `Firmware.Solix.Session` for
  each one that has none. Two at most: BlueZ gives three connection slots,
  and one stays free for a game pad. A session that ends is tried again in
  10 s; one that keeps ending before its first reading waits 30 s, then
  2 min. Sessions are temporary children of `Firmware.Batteries.Sessions`
  and are only ever watched from here, never linked, so a battery can cost
  its own reading and nothing else.

  Numbered by address, from 1: the same battery is Battery 1 for as long as
  it is around. Each is

    * `:connecting`: no reading yet
    * `:live`: a reading in the last minute
    * `:stale`: its last reading is older than that; still trying
    * `:lost`: no session, and not heard for two minutes. Forgotten after 15.

  Changes go out on `"power"` as `{:batteries, list}`, on this machine only.

  **Off switch.** The setting `"battery_watch"` (true by default) set to
  false starts no sessions. On a Pi 3, Bluetooth and Wi-Fi share one radio,
  and sessions that drop and reconnect all night crowd the Wi-Fi a phone is
  using (one night: pings to the box from 24 ms average, 178 ms worst, to
  11 and 30 with the watcher stopped).

      Firmware.Batteries.list()
  """
  use GenServer
  require Logger

  alias Firmware.Solix.Session

  @compile {:no_warn_undefined, [Firmware.Bluetooth, Firmware.Bluetooth.Nearby, Telescope, Bluez.Gatt]}

  @scan_ms 10_000
  @max_sessions 2
  @backoff_ms [10_000, 30_000, 120_000]
  @stale_ms 60_000
  # Nearby forgets a device after two minutes; a battery in a session may
  # stop advertising, so the session counts as hearing it
  @heard_ms 120_000
  @forget_ms 15 * 60_000

  @doc "The supervisor sessions run under."
  def sessions, do: Firmware.Batteries.Sessions

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: Keyword.get(opts, :name, __MODULE__))

  @doc """
  Every battery, numbered by address:
  `[%{n: 1, address:, name:, state:, reading: %{charge:, watts_out:, ...} | nil}]`,
  or `[]` while this is not running.
  """
  def list(server \\ __MODULE__) do
    GenServer.call(server, :list, 1_000)
  catch
    :exit, _ -> []
  end

  # -- the process ------------------------------------------------------------------------

  @impl true
  def init(opts) do
    scan_ms = Keyword.get(opts, :scan_ms, @scan_ms)
    :timer.send_interval(scan_ms, :scan)

    {:ok,
     %{
       batteries: %{},
       sessions: %{},
       published: nil,
       # what the world is, injectable for tests
       nearby: Keyword.get(opts, :nearby, &Firmware.Bluetooth.Nearby.list/0),
       up?: Keyword.get(opts, :up?, &bluetooth_up?/0),
       sup: Keyword.get(opts, :sup, sessions()),
       session: Keyword.get(opts, :session, Session),
       gatt: Keyword.get(opts, :gatt, Bluez.Gatt),
       broadcast: Keyword.get(opts, :broadcast, &Telescope.local_broadcast("power", {:batteries, &1}))
     }}
  end

  @impl true
  def handle_call(:list, _from, s), do: {:reply, number(Map.values(s.batteries), now()), s}

  @doc "Is the battery watcher on? The setting `\"battery_watch\"` (true unless set false)."
  def watching? do
    if Code.ensure_loaded?(Controller.Settings) and Process.whereis(Controller.Settings),
      do: apply(Controller.Settings, :get, ["battery_watch", true]) != false,
      else: true
  end

  @impl true
  def handle_info(:scan, s) do
    now = now()
    heard = safe(s.nearby, []) |> Enum.filter(&solix?/1)
    s = %{s | batteries: s.batteries |> heard(heard) |> forget(now)}
    s = if safe(s.up?, false) and watching?(), do: Enum.reduce(to_start(Map.values(s.batteries), now), s, &start(&2, &1)), else: s
    {:noreply, publish(s)}
  end

  def handle_info({:solix, pid, address, event}, s) do
    case s.sessions do
      %{^pid => ^address} -> {:noreply, s |> event(address, event) |> publish()}
      _ -> {:noreply, s}
    end
  end

  def handle_info({:DOWN, _ref, :process, pid, why}, s) do
    case Map.pop(s.sessions, pid) do
      {nil, _} -> {:noreply, s}
      {address, sessions} -> {:noreply, %{s | sessions: sessions} |> ended(address, why) |> publish()}
    end
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- what happens -------------------------------------------------------------------------

  defp heard(batteries, devices) do
    Enum.reduce(devices, batteries, fn d, acc ->
      entry = Map.get(acc, d.address, entry(d.address))
      Map.put(acc, d.address, %{entry | name: d.name || entry.name, heard_at: d.at})
    end)
  end

  defp forget(batteries, now), do: Map.reject(batteries, fn {_, e} -> forgotten?(e, now) end)

  defp start(s, entry) do
    opts = [address: entry.address, report_to: self()]

    case safe(fn -> DynamicSupervisor.start_child(s.sup, {s.session, opts}) end, {:error, :no_supervisor}) do
      {:ok, pid} ->
        Process.monitor(pid)
        put(%{s | sessions: Map.put(s.sessions, pid, entry.address)}, entry.address, session: pid)

      other ->
        Logger.warning("Batteries: could not start a session for #{entry.address} (#{inspect(other)})")
        retry_later(s, entry.address, entry.failures + 1)
    end
  end

  defp event(s, address, {:reading, reading}), do: put(s, address, reading: reading, failures: 0, read: true)
  defp event(s, _, _), do: s

  defp ended(s, address, why) do
    # the session lets the link go itself; this is for one that was killed
    safe(fn -> s.gatt.disconnect(Session.address_int(address)) end, :ok)

    case s.batteries do
      %{^address => entry} ->
        failures = if entry.read, do: 0, else: entry.failures + 1
        Logger.info("Batteries: #{address} session ended (#{words(why)}); again in #{div(backoff(failures), 1000)} s")
        retry_later(s, address, failures)

      _ ->
        s
    end
  end

  defp retry_later(s, address, failures) do
    delay = backoff(failures)
    Process.send_after(self(), :scan, delay)
    put(s, address, session: nil, read: false, failures: failures, retry_at: now() + delay)
  end

  defp put(s, address, fields) do
    case s.batteries do
      %{^address => entry} -> %{s | batteries: Map.put(s.batteries, address, Map.merge(entry, Map.new(fields)))}
      _ -> s
    end
  end

  # tell the pages, and the log when a battery's state changes
  defp publish(s) do
    list = number(Map.values(s.batteries), now())

    if list != s.published do
      was = Map.new(s.published || [], &{&1.address, &1.state})

      for b <- list, was[b.address] != b.state do
        Logger.info("Batteries: Battery #{b.n} (#{b.address}) #{b.state}#{if b.reading, do: ": " <> figures(b.reading)}")
      end

      safe(fn -> s.broadcast.(list) end, :ok)
      %{s | published: list}
    else
      s
    end
  end

  # -- the rules, pure -------------------------------------------------------------------------

  @doc false
  def entry(address),
    do: %{address: address, name: nil, heard_at: nil, reading: nil, session: nil, failures: 0, read: false, retry_at: nil}

  @doc "Whether an advert is a SOLIX battery's."
  def solix?(%{name: "Anker SOLIX" <> _}), do: true
  def solix?(_), do: false

  @doc """
  How long to wait before the next session, after `failures` in a row that
  ended without a reading: 10 s after none (a session that read, then
  ended) or one, 30 s after two, then 2 min.
  """
  def backoff(failures), do: Enum.at(@backoff_ms, max(failures - 1, 0), List.last(@backoff_ms))

  @doc "`:live`, `:connecting`, `:stale` or `:lost` (see the moduledoc)."
  def state(entry, now) do
    cond do
      entry.reading != nil and now - entry.reading.at <= @stale_ms -> :live
      not present?(entry, now) -> :lost
      entry.reading == nil -> :connecting
      true -> :stale
    end
  end

  defp present?(entry, now), do: entry.session != nil or heard?(entry, now)

  # monotonic time is negative: the latest of what there is, never against 0
  defp forgotten?(entry, now) do
    last = [entry.heard_at, entry.reading && entry.reading.at] |> Enum.reject(&is_nil/1) |> Enum.max(fn -> nil end)
    entry.session == nil and (last == nil or now - last > @forget_ms)
  end

  @doc "Which batteries to start a session for now: heard, due, and no more than two at once, lowest address first."
  def to_start(entries, now) do
    running = Enum.count(entries, & &1.session)

    entries
    |> Enum.filter(&(&1.session == nil and (&1.retry_at == nil or &1.retry_at <= now) and heard?(&1, now)))
    |> Enum.sort_by(& &1.address)
    |> Enum.take(max(@max_sessions - running, 0))
  end

  defp heard?(entry, now), do: entry.heard_at != nil and now - entry.heard_at <= @heard_ms

  @doc "Battery 1, Battery 2, ...: sorted by address, so the numbers hold."
  def number(entries, now) do
    entries
    |> Enum.sort_by(& &1.address)
    |> Enum.with_index(1)
    |> Enum.map(fn {e, n} -> %{n: n, address: e.address, name: e.name, reading: e.reading, state: state(e, now)} end)
  end

  @doc """
  One battery per word, for the flight log: `1:100%/0W/25C`, with watts in
  when charging (`1:80%/13W/in60W/25C`), `2:stale/16%/13W/26C`,
  `3:connecting`, `4:lost`.
  """
  def brief(list) do
    Enum.map_join(list, " ", fn
      %{n: n, state: :live, reading: r} -> "#{n}:#{figures(r)}"
      %{n: n, state: :stale, reading: r} when r != nil -> "#{n}:stale/#{figures(r)}"
      %{n: n, state: state} -> "#{n}:#{state}"
    end)
  end

  defp figures(r) do
    [
      "#{v(r.charge)}%",
      "#{v(r.watts_out)}W",
      if(r.watts_in not in [nil, 0], do: "in#{r.watts_in}W"),
      "#{v(r.temp_c)}C"
    ]
    |> Enum.reject(&is_nil/1)
    |> Enum.join("/")
  end

  defp v(nil), do: "?"
  defp v(x), do: x

  defp words({:shutdown, why}), do: words(why)
  defp words({why, detail}) when is_atom(why), do: "#{why} #{inspect(detail)}"
  defp words(why) when is_atom(why), do: to_string(why)
  defp words(why), do: inspect(why, limit: 8)

  defp bluetooth_up?, do: match?(%{state: :running}, Firmware.Bluetooth.status())

  defp safe(fun, default) do
    fun.()
  rescue
    _ -> default
  catch
    _, _ -> default
  end

  defp now, do: System.monotonic_time(:millisecond)
end
