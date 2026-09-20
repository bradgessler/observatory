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

  @max_age_ms 400
  @watchdog_ms 600
  @call_timeout 1_500
  @min_interval_ms 60

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Last published status; never blocks on a busy mapper."
  def status do
    :persistent_term.get({__MODULE__, :status}, %{armed: false, target: nil, action: :idle, action_text: Gamepad.describe(:idle), held: [], map: Gamepad.defaults(), off_reason: nil, ignoring: false})
  end

  def arm(on?) when is_boolean(on?), do: GenServer.call(__MODULE__, {:arm, on?})
  def target(mount_id), do: GenServer.call(__MODULE__, {:target, mount_id})
  def configure(map) when is_map(map), do: GenServer.call(__MODULE__, {:configure, map})

  @impl true
  def init(_) do
    # calls into the driver run in linked tasks: a driver that dies mid-call
    # must not take the mapper down with it (it would come back disarmed and silent)
    Process.flag(:trap_exit, true)
    Telescope.subscribe("input")
    Telescope.Events.tag("game pad")
    # monotonic time can be negative; "long ago" must be relative to now, not 0
    long_ago = System.monotonic_time(:millisecond) - 60_000
    s = %{armed: false, target: nil, map: %{}, device_map: %{}, held: [], action: :idle, last_cmd: long_ago, last_fresh: long_ago, failures: 0, off_reason: nil}
    Process.send_after(self(), :watchdog, @watchdog_ms)
    {:ok, announce(s)}
  end

  @impl true
  def handle_call({:arm, on?}, _from, s) do
    # a freshly armed pad must never have its first command rate-limited away
    long_ago = System.monotonic_time(:millisecond) - 60_000
    s = if on?, do: Map.merge(s, %{armed: true, failures: 0, off_reason: nil, last_cmd: long_ago}), else: Map.merge(release(s), %{armed: false, off_reason: nil})
    Telescope.Events.emit(:input, if(on?, do: :armed, else: :off), %{target: (ref(s) || %{})[:id], why: if(on?, do: "pad moves scope", else: "watch only")})
    {:reply, :ok, announce(s)}
  end

  def handle_call({:target, id}, _from, s) do
    long_ago = System.monotonic_time(:millisecond) - 60_000
    {:reply, :ok, announce(Map.merge(release(s), %{target: id, last_cmd: long_ago}))}
  end
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
        {:noreply, note_stale(s, age)}

      true ->
        s = note_buttons(s, info)
        s = note_trigger(s, info)
        action = Gamepad.interpret(info.state, Map.merge(device_defaults(info), s.map))
        s = %{s | action: action, device_map: device_defaults(info), last_fresh: now}

        s =
          cond do
            # the pad's STOP button is a STOP button, armed or not
            action == :stop -> act(s, :stop, now)
            s.armed -> act(s, action, now)
            # a hand on a pad that is off: say so once per hold, in the log and on the page
            action != :idle and not Map.get(s, :ignoring, false) ->
              Telescope.Events.emit(:input, :ignored, %{action: Gamepad.describe(action), why: "pad is off (watch only)"})
              Map.put(s, :ignoring, true)
            action == :idle -> Map.put(s, :ignoring, false)
            true -> s
          end

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
    {:noreply, announce(turn_off(s, "turned off: the controller was unplugged"))}
  end

  # a linked task died abnormally: the driver went away under a call
  def handle_info({:EXIT, _pid, :normal}, s), do: {:noreply, s}

  def handle_info({:EXIT, _pid, reason}, s) do
    Logger.warning("input mapper: a driver call died (#{inspect(reason)}) — turning the pad off")
    {:noreply, announce(turn_off(%{s | held: []}, "turned off: the mount stopped answering"))}
  end

  def handle_info(_, s), do: {:noreply, s}

  # Every change of a button or the hat goes to the events log with the raw
  # report, so "I pressed it and nothing happened" can be read back later:
  # which bit moved, what the parser made of it, what the mapper decided.
  defp note_buttons(s, %{state: st} = info) do
    pressed = st[:buttons] |> List.wrap() |> Enum.with_index() |> Enum.filter(&elem(&1, 0)) |> Enum.map(&elem(&1, 1))
    key = {pressed, st[:hat]}

    if key != Map.get(s, :last_buttons) do
      Telescope.Events.emit(:input, :buttons, %{
        pressed: pressed,
        hat: st[:hat],
        axes: Enum.map(st[:axes] || [], &Float.round(&1 / 1, 2)),
        raw: Base.encode16(st[:raw] || <<>>),
        parser: info[:parser],
        armed: s.armed
      })
    end

    Map.put(s, :last_buttons, key)
  end

  defp note_buttons(s, _), do: s

  # The Dual Strike's head is not spring-centred: it stays where you leave
  # it. So the law is absolute: displacement from the physical centre is the
  # rate, the trigger is only the dead-man. (Re-zeroing at the squeeze was
  # tried and made the feel depend on where the head was left: pushing past
  # an end did nothing while the other way moved.) The squeeze is logged
  # with the head's position so the log can say what the hand asked for.
  defp note_trigger(s, %{state: st} = info) do
    m = Map.merge(Gamepad.defaults(), Map.merge(device_defaults(info), s.map))
    down? = Enum.at(st[:buttons] || [], m.trigger) == true

    cond do
      down? and not Map.get(s, :trigger_down, false) ->
        axes = st[:axes] || []
        at = [Enum.at(axes, m.x_axis) || 0.0, Enum.at(axes, m.y_axis) || 0.0]
        Telescope.Events.emit(:input, :trigger, %{head: Enum.map(at, &Float.round(&1 / 1, 2)), armed: s.armed})
        Map.put(s, :trigger_down, true)

      not down? ->
        Map.put(s, :trigger_down, false)

      true ->
        s
    end
  end

  defp note_trigger(s, _), do: s

  # stale reports are dropped by design; say so once a second, not per report
  defp note_stale(s, age) do
    now = System.monotonic_time(:millisecond)

    if now - Map.get(s, :last_stale_note, now - 10_000) > 1_000 do
      Telescope.Events.emit(:input, :stale, %{age_ms: age})
      Map.put(s, :last_stale_note, now)
    else
      s
    end
  end

  defp turn_off(s, why) do
    if s.armed, do: Telescope.Events.emit(:input, :off, %{target: (ref(s) || %{})[:id], why: why})
    Map.merge(release(s), %{armed: false, failures: 0, off_reason: why})
  end

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
              # one slow answer is not a dead mount; three in a row is
              # (Map.get: the running process may predate this key after a hot reload)
              failures = Map.get(s, :failures, 0) + 1

              if failures >= 3 do
                Logger.error("input mapper: mount not answering (#{failures}×) — turning the pad off")
                turn_off(%{s | held: []}, "turned off: the mount stopped answering")
              else
                Map.put(s, :failures, failures)
              end
            else
              Map.merge(s, %{held: Enum.map(rates, &elem(&1, 0)), last_cmd: now, failures: 0})
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

        # the trigger is a dead-man switch: release = halt now, no ramp
        for axis <- s.held do
          safe(fn -> Mount.stop(ref, axis, instant: true) end)
          if axis == :ra and is_map(snap) and snap.tracking != :off, do: safe(fn -> Mount.track(ref, snap.tracking) end)
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

  # The mount API can be momentarily missing (a code reload swapping the mount
  # app, or the app restarting). That is "no mount right now", not a crash.
  defp ref(%{target: nil}), do: mounts() |> List.first()
  defp ref(%{target: id}), do: Enum.find(mounts(), &(&1.id == id))

  defp mounts do
    Mount.list()
  rescue
    _ -> []
  catch
    _, _ -> []
  end

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
      off_reason: Map.get(s, :off_reason),
      ignoring: Map.get(s, :ignoring, false),
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
