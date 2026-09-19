defmodule Input.Mapper do
  @moduledoc """
  Drives a mount from input devices, server-side, no browser required.

  Subscribes to every device's state, runs `Input.Gamepad.interpret/2`, and
  turns the result into held slews, nudges, or an emergency stop.

  Fail-safe rules, learned the hard way:
    * **Only fresh input moves the scope.** Every report carries a monotonic
      timestamp; anything older than #{250} ms is dropped, and the mailbox is
      coalesced to the newest report before acting. A backlog can never replay.
    * **Own watchdog.** While holding, if no fresh report arrives within
      #{600} ms the hold is released — independent of the driver's deadman.
    * **Starts disarmed**, disarms itself if the mount stops answering or the
      device disappears, and a restart of this process is a disarm.
    * Mount calls are bounded: a call that doesn't return in #{1_500} ms is a
      failure, not a stall.
  """
  use GenServer
  require Logger

  alias Input.Gamepad

  @max_age_ms 250
  @watchdog_ms 600
  @call_timeout 1_500
  @min_interval_ms 60

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Last published status; never blocks on a busy mapper."
  def status do
    :persistent_term.get({__MODULE__, :status}, %{armed: false, target: nil, action: :idle, action_text: Gamepad.describe(:idle), held: [], map: Gamepad.defaults()})
  end

  def arm(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:arm, on?})
  def target(mount_id), do: GenServer.call(__MODULE__, {:target, mount_id})
  def configure(map) when is_map(map), do: GenServer.call(__MODULE__, {:configure, map})

  @impl true
  def init(_) do
    Telescope.subscribe("input")
    # monotonic time can be negative; "long ago" must be relative to now, not 0
    long_ago = System.monotonic_time(:millisecond) - 60_000
    s = %{armed: false, target: nil, map: %{}, device_map: %{}, held: [], action: :idle, last_cmd: long_ago, last_fresh: long_ago}
    Process.send_after(self(), :watchdog, @watchdog_ms)
    {:ok, announce(s)}
  end

  @impl true
  def handle_call({:arm, on?}, _from, s) do
    s = if on?, do: %{s | armed: true}, else: %{release(s) | armed: false}
    {:reply, :ok, announce(s)}
  end

  def handle_call({:target, id}, _from, s), do: {:reply, :ok, announce(%{release(s) | target: id})}
  def handle_call({:configure, map}, _from, s), do: {:reply, :ok, announce(%{s | map: Map.merge(s.map, map)})}

  @impl true
  def handle_info({:input, _id, _info} = msg, s) do
    # coalesce: act on the newest report only
    {:input, _id, info} = drain_latest(msg)
    now = System.monotonic_time(:millisecond)
    age = now - (info[:at] || 0)

    cond do
      age > @max_age_ms ->
        # stale — never act on old intent; but a stale "idle" is still a fine reason to release
        {:noreply, s}

      true ->
        action = Gamepad.interpret(info.state, Map.merge(device_defaults(info), s.map))
        s = %{s | action: action, device_map: device_defaults(info), last_fresh: now}
        s = if s.armed, do: act(s, action, now), else: s
        {:noreply, announce(s)}
    end
  end

  def handle_info(:watchdog, s) do
    Process.send_after(self(), :watchdog, div(@watchdog_ms, 2))
    now = System.monotonic_time(:millisecond)

    if s.held != [] and now - s.last_fresh > @watchdog_ms do
      Logger.warning("input mapper: no fresh input for #{now - s.last_fresh} ms while holding — releasing")
      {:noreply, announce(release(s))}
    else
      {:noreply, s}
    end
  end

  def handle_info({:input_gone, _id}, s) do
    Logger.warning("input mapper: device gone — releasing and disarming")
    {:noreply, announce(%{release(s) | armed: false})}
  end

  def handle_info(_, s), do: {:noreply, s}

  # -- acting -------------------------------------------------------------------------

  defp act(s, :stop, _now) do
    with ref when not is_nil(ref) <- ref(s), do: safe(fn -> Mount.emergency_stop(ref) end)
    %{s | held: []}
  end

  defp act(s, {_kind, rates}, now) do
    cond do
      now - s.last_cmd < @min_interval_ms ->
        s

      true ->
        case ref(s) do
          nil ->
            s

          ref ->
            results = for {axis, r} <- rates, do: safe(fn -> Mount.slew(ref, axis, r, hold: true) end)

            if Enum.any?(results, &match?({:error, :unreachable}, &1)) do
              Logger.error("input mapper: mount not answering — disarming")
              %{s | held: [], armed: false}
            else
              %{s | held: Enum.map(rates, &elem(&1, 0)), last_cmd: now}
            end
        end
    end
  end

  defp act(s, :idle, _now), do: release(s)

  defp release(%{held: []} = s), do: s

  defp release(s) do
    case ref(s) do
      nil ->
        :ok

      ref ->
        snap = safe(fn -> Mount.snapshot(ref) end)

        for axis <- s.held do
          if axis == :ra and is_map(snap) and snap.tracking != :off,
            do: safe(fn -> Mount.track(ref, snap.tracking) end),
            else: safe(fn -> Mount.stop(ref, axis) end)
        end
    end

    %{s | held: []}
  end

  # Newest {:input, _, _} in the mailbox wins; everything older is discarded.
  defp drain_latest(msg) do
    receive do
      {:input, _, _} = newer -> drain_latest(newer)
    after
      0 -> msg
    end
  end

  defp ref(%{target: nil}), do: Mount.list() |> List.first()
  defp ref(%{target: id}), do: Enum.find(Mount.list(), &(&1.id == id))

  defp device_defaults(%{parser_mod: mod}) when is_atom(mod) and not is_nil(mod) do
    if function_exported?(mod, :default_map, 0), do: mod.default_map(), else: %{}
  end

  defp device_defaults(_), do: %{}

  defp public(s) do
    %{
      armed: s.armed,
      target: (ref(s) || %{})[:id],
      action: s.action,
      action_text: Gamepad.describe(s.action),
      held: s.held,
      map: Gamepad.defaults() |> Map.merge(s.device_map) |> Map.merge(s.map)
    }
  end

  defp announce(s) do
    status = public(s)
    :persistent_term.put({__MODULE__, :status}, status)
    Telescope.broadcast("input", {:mapper, status})
    s
  end

  # Bounded calls: a mount that doesn't answer quickly is treated as gone.
  defp safe(fun) do
    task = Task.async(fn -> fun.() end)

    case Task.yield(task, @call_timeout) || Task.shutdown(task, :brutal_kill) do
      {:ok, v} -> v
      {:exit, _} -> {:error, :unreachable}
      nil -> {:error, :unreachable}
    end
  catch
    _, _ -> {:error, :unreachable}
  end
end
