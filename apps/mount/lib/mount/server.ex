defmodule Mount.Server do
  @moduledoc """
  One process per mount. Owns the transport, keeps a live picture of both axes,
  and turns high-level requests (slew at a rate, nudge, go to a relative
  position, track) into protocol frames.

  Position is polled every #{250} ms and broadcast on `"mount:<id>"` as
  `{:mount, snapshot}` so anything in the cluster can follow along.

  Safety: slews started with `hold: true` stop by themselves unless refreshed
  within #{900} ms — a held arrow button on a flaky link can't run away.
  """
  use GenServer
  require Logger

  alias Mount.Protocol, as: P

  @poll_ms 250
  @hold_grace_ms 900
  @stop_wait_ms 4_000
  @reconnect_ms 2_000

  # rates in × sidereal
  @tracking_rates %{sidereal: 1.0, lunar: 0.9663, solar: 0.9973}

  # -- API -----------------------------------------------------------------------

  def start_link(opts) do
    id = Keyword.fetch!(opts, :id)
    GenServer.start_link(__MODULE__, opts, name: via(id))
  end

  def via(id), do: {:via, Registry, {Mount.Registry, id}}

  def call(id, msg, timeout \\ 10_000), do: GenServer.call(via(id), msg, timeout)

  def child_spec(opts) do
    %{id: {__MODULE__, Keyword.fetch!(opts, :id)}, start: {__MODULE__, :start_link, [opts]}}
  end

  # -- init ----------------------------------------------------------------------

  @impl true
  def init(opts) do
    {mod, topts} = Keyword.fetch!(opts, :transport)

    state = %{
      id: Keyword.fetch!(opts, :id),
      tracking_direction: Keyword.get(opts, :tracking_direction, :forward),
      # Soft limits in degrees from home, per axis. Only enforced once someone
      # has called set_home — before that the counts mean nothing.
      limits: Keyword.get(opts, :limits, Application.get_env(:mount, :limits)),
      homed: false,
      homed_at: nil,
      mod: mod,
      topts: topts,
      tstate: nil,
      connected: false,
      error: nil,
      firmware: nil,
      axes: %{},
      tracking: :off,
      holds: %{},
      # wall-clock ms of the last emergency stop; anything tracking through
      # the model reads it and stands down
      estop_at: nil
    }

    # so terminate/2 runs on supervisor shutdown and we can stop the motors
    Process.flag(:trap_exit, true)
    send(self(), :connect)
    {:ok, state}
  end

  # Best effort on the way out: if the link still works, stop both axes so a
  # driver restart (or a VM shutdown) doesn't leave the mount slewing.
  @impl true
  def terminate(_reason, %{connected: true, tstate: t} = state) when not is_nil(t) do
    for axis <- [:ra, :dec] do
      try do
        exchange(state, P.encode("L", axis))
      catch
        _, _ -> :ok
      end
    end

    safe_close(state)
  end

  def terminate(_reason, state), do: safe_close(state)

  @impl true
  def handle_info(:connect, state) do
    case connect(state) do
      {:ok, state} ->
        Logger.info("mount #{state.id}: connected, firmware #{state.firmware}")
        Telescope.Events.emit(:mount, :connected, %{id: state.id, firmware: state.firmware})
        send(self(), :poll)
        {:noreply, broadcast(state)}

      {:error, reason} ->
        Logger.warning("mount #{state.id}: #{inspect(reason)}, retrying")
        Process.send_after(self(), :connect, @reconnect_ms)
        {:noreply, broadcast(%{state | connected: false, error: reason})}
    end
  end

  def handle_info(:poll, state) do
    state = state |> refresh() |> start_pending() |> enforce_limits() |> maybe_resume_tracking() |> settle_gotos()
    Process.send_after(self(), :poll, @poll_ms)
    {:noreply, broadcast(state)}
  end

  def handle_info({:hold_expired, axis}, state) do
    {:noreply, state |> stop_axis(axis) |> Map.update!(:holds, &Map.delete(&1, axis))}
  end

  # -- calls -----------------------------------------------------------------------

  @impl true
  def handle_call(:snapshot, _from, state), do: {:reply, snapshot(state), state}

  def handle_call(_msg, _from, %{connected: false} = state),
    do: {:reply, {:error, :not_connected}, state}

  def handle_call({:slew, axis, rate, opts}, _from, state) when axis in [:ra, :dec] do
    cond do
      rate == 0 ->
        {:reply, :ok, broadcast(stop_axis(state, axis))}

      at_limit?(state, axis, dir_of(rate)) ->
        {:reply, {:error, :limit}, state}

      true ->
        state = state |> start_slew(axis, rate) |> arm_hold(axis, Keyword.get(opts, :hold, false))
        {:reply, :ok, broadcast(state)}
    end
  end

  # A page-level STOP of both axes is a "stop, whoever you are": it stamps
  # `estop_at` like the emergency stop so the model tracker ends too.
  def handle_call({:stop, :both}, _from, state) do
    state = state |> stop_axis(:ra) |> stop_axis(:dec) |> Map.merge(%{tracking: :off, estop_at: System.monotonic_time(:millisecond)})
    {:reply, :ok, broadcast(state)}
  end

  def handle_call({:stop, axis}, _from, state) do
    state = %{stop_axis(state, axis) | holds: cancel_hold(state.holds, axis)}
    state = if axis == :ra, do: %{state | tracking: :off}, else: state
    {:reply, :ok, broadcast(state)}
  end

  # Dead-man release: no ramp. :L halts the axis where it is.
  def handle_call({:stop, axis, :instant}, _from, state) when axis in [:ra, :dec] do
    state =
      state
      |> put_axis(axis, :pending, nil)
      |> send!("L", axis)
      |> refresh_axis(axis)

    state = if axis == :ra, do: %{state | tracking: :off}, else: state
    {:reply, :ok, broadcast(state)}
  end

  def handle_call(:emergency_stop, _from, state) do
    state =
      state
      |> send!("L", :ra)
      |> send!("L", :dec)
      |> Map.merge(%{tracking: :off, holds: cancel_holds(state.holds), estop_at: System.monotonic_time(:millisecond)})

    {:reply, :ok, broadcast(refresh(state))}
  end

  def handle_call({:goto_relative, axis, degrees}, _from, state) when axis in [:ra, :dec] do
    ax = state.axes[axis]
    steps = abs(P.degrees_to_steps(degrees, ax.steps_per_rev))
    dir = if degrees >= 0, do: :forward, else: :reverse

    if within_limits?(state, axis, ax.degrees + degrees) do
      {:reply, :ok, broadcast(goto(state, axis, steps, dir))}
    else
      {:reply, {:error, :limit}, state}
    end
  end

  def handle_call({:track, mode}, _from, state) when is_map_key(@tracking_rates, mode) do
    rate = signed(@tracking_rates[mode], state.tracking_direction)

    if at_limit?(state, :ra, dir_of(rate)) do
      {:reply, {:error, :limit}, state}
    else
      # tracking is not a held slew: a hold left over from a pull that was
      # just released would stop the axis 900 ms later and leave the badge lying
      state = %{start_slew(state, :ra, rate) | tracking: mode, holds: cancel_hold(state.holds, :ra)}
      {:reply, :ok, broadcast(state)}
    end
  end

  # Turning tracking off while a goto is in flight must not kill the goto:
  # just forget the mode, so the poll won't resume it when the goto lands.
  def handle_call({:track, :off}, _from, state) do
    if state.axes.ra[:goto_pending],
      do: {:reply, :ok, broadcast(%{state | tracking: :off})},
      else: {:reply, :ok, broadcast(%{stop_axis(state, :ra) | tracking: :off})}
  end

  def handle_call(:set_home, _from, state) do
    state =
      state
      |> stop_axis(:ra)
      |> stop_axis(:dec)
      |> send!("E", :ra, P.from_int(P.center()))
      |> send!("E", :dec, P.from_int(P.center()))
      |> Map.merge(%{tracking: :off, homed: true, homed_at: System.os_time(:millisecond)})

    # Survives a driver restart (USB hiccup) within this VM; see connect/1.
    :persistent_term.put({__MODULE__, state.id, :homed}, state.homed_at)
    {:reply, :ok, broadcast(refresh(state))}
  end

  def handle_call({:raw, frame}, _from, state) do
    {reply, state} = exchange(state, frame)
    {:reply, reply, state}
  end

  # Runtime knobs (tracking direction, limits) so a wrong guess can be fixed
  # from the UI in the field instead of restarting with new config.
  def handle_call({:configure, opts}, _from, state) do
    state =
      Enum.reduce(opts, state, fn
        {:tracking_direction, d}, s when d in [:forward, :reverse] -> %{s | tracking_direction: d}
        {:limits, l}, s when is_map(l) or is_nil(l) -> %{s | limits: l}
        _, s -> s
      end)

    # tracking is running the old way? re-issue it
    state =
      if state.tracking != :off and Keyword.has_key?(opts, :tracking_direction),
        do: start_slew(state, :ra, signed(@tracking_rates[state.tracking], state.tracking_direction)),
        else: state

    {:reply, :ok, broadcast(state)}
  end

  # -- motion ------------------------------------------------------------------------

  defp goto(state, axis, steps, dir) do
    # a goto is not a held slew: a dead-man left armed by the last hold
    # (a tracker's, a pad's) would stop it a second in
    %{state | holds: cancel_hold(state.holds, axis)}
    |> stop_axis(axis)
    |> send!("G", axis, P.motion_mode(:goto, dir))
    |> send!("H", axis, P.from_int(steps))
    |> send!("M", axis, P.from_int(min(3_500, div(steps, 2))))
    |> send!("J", axis)
    |> put_axis(axis, :goto_pending, true)
    |> put_axis(axis, :goto_at, System.monotonic_time(:millisecond))
    |> refresh_axis(axis)
  end

  # Slews never block the caller. Same direction and microstep mode: change the
  # period live. Anything else: send the stop now, remember the wanted slew,
  # and start it from the next poll once the axis reports stopped. (The old
  # stop-and-wait here took seconds per change and jammed every input path.)
  #
  # Mode hysteresis: fast microstep mode can run any rate, slow mode only up to
  # 128×. If the axis is already running in a mode that can do the wanted
  # rate, keep it — flapping between modes on every wobble of a stick is what
  # made continuous control feel like it "decayed".
  defp start_slew(state, axis, rate) do
    ax = state.axes[axis]
    dir = if rate >= 0, do: :forward, else: :reverse
    {natural_mode, _} = P.slew_params(abs(rate), ax)

    mode =
      cond do
        ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == :fast and abs(rate) >= 4 -> :fast
        ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == :slow and abs(rate) <= 128 -> :slow
        true -> natural_mode
      end

    period = period_for(abs(rate), mode, ax)
    same_run? = ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == mode

    cond do
      # Same run and (nearly) the same speed: say nothing to the board. Held
      # controls refresh 4-5×/s; rewriting :I each time made the motor stutter.
      same_run? and close?(period, ax[:period]) ->
        put_axis(state, axis, :pending, nil)

      same_run? ->
        state |> send!("I", axis, P.from_int(period)) |> put_axis(axis, :period, period) |> put_axis(axis, :pending, nil)

      ax.running ->
        # stop now, start the new slew when the poll sees the axis stopped
        state |> send!("K", axis) |> put_axis(axis, :pending, {mode, dir, period})

      true ->
        begin_slew(state, axis, mode, dir, period)
    end
    |> put_axis(axis, :goto_pending, false)
    |> refresh_axis(axis)
  end

  defp begin_slew(state, axis, mode, dir, period) do
    state
    |> send!("G", axis, P.motion_mode(mode, dir))
    |> send!("I", axis, P.from_int(period))
    |> send!("J", axis)
    |> put_axis(axis, :period, period)
    |> put_axis(axis, :pending, nil)
  end

  # within ~2%: not worth a command
  defp close?(_new, nil), do: false
  defp close?(new, old), do: abs(new - old) <= max(old * 0.02, 1)

  # The period is a 24-bit register: a rate tiny enough to overflow it (well
  # under a thousandth of sidereal) is clamped to the slowest the board can do.
  defp period_for(rate, mode, %{steps_per_rev: cpr, timer_freq: tf, high_speed_ratio: hs}) do
    steps_per_s = P.sidereal_rate(cpr) * rate
    tf * if(mode == :fast, do: hs, else: 1) / steps_per_s |> round() |> max(1) |> min(0xFFFFFF)
  end

  # Called every poll: an axis that was told to stop for a direction/mode
  # change starts its pending slew as soon as it reports stopped.
  defp start_pending(state) do
    Enum.reduce([:ra, :dec], state, fn axis, s ->
      case s.axes[axis][:pending] do
        {mode, dir, period} ->
          if s.axes[axis].running, do: s, else: begin_slew(s, axis, mode, dir, period)

        _ ->
          s
      end
    end)
  end

  defp stop_axis(state, axis) do
    state = state |> put_axis(axis, :pending, nil) |> send!("K", axis)
    wait_stopped(state, axis, System.monotonic_time(:millisecond) + @stop_wait_ms)
  end

  defp wait_stopped(state, axis, deadline) do
    state = refresh_axis(state, axis)

    cond do
      not state.axes[axis].running ->
        state

      System.monotonic_time(:millisecond) > deadline ->
        state

      true ->
        Process.sleep(50)
        wait_stopped(state, axis, deadline)
    end
  end

  # A goto on RA kills tracking; re-arm it once the goto lands.
  defp maybe_resume_tracking(%{tracking: mode} = state) when mode != :off do
    ax = state.axes[:ra]

    if ax[:goto_pending] and not ax.running and not Map.has_key?(state.holds, :ra) do
      start_slew(state, :ra, signed(@tracking_rates[mode], state.tracking_direction))
    else
      state
    end
  end

  defp maybe_resume_tracking(state), do: state

  # A goto that has landed is no longer pending, whether or not tracking
  # resumes — anything waiting for the mount to be free (the model tracker)
  # reads this flag. Give a fresh goto a couple of polls to start moving.
  defp settle_gotos(state) do
    now = System.monotonic_time(:millisecond)

    Enum.reduce(state.axes, state, fn {axis, ax}, st ->
      if ax[:goto_pending] and not ax.running and now - (ax[:goto_at] || now) > 600,
        do: put_axis(st, axis, :goto_pending, false),
        else: st
    end)
  end

  # an un-held slew replaces a held one: its dead-man must not outlive it
  defp arm_hold(state, axis, false), do: %{state | holds: cancel_hold(state.holds, axis)}

  defp arm_hold(state, axis, true) do
    if ref = state.holds[axis], do: Process.cancel_timer(ref)
    ref = Process.send_after(self(), {:hold_expired, axis}, @hold_grace_ms)
    %{state | holds: Map.put(state.holds, axis, ref)}
  end

  defp cancel_hold(holds, axis) do
    if ref = holds[axis], do: Process.cancel_timer(ref)
    Map.delete(holds, axis)
  end

  defp cancel_holds(holds) do
    Enum.each(holds, fn {_, ref} -> Process.cancel_timer(ref) end)
    %{}
  end

  defp signed(rate, :forward), do: rate
  defp signed(rate, :reverse), do: -rate

  # -- connection ----------------------------------------------------------------------

  defp connect(state) do
    with {:ok, tstate} <- state.mod.open(state.topts),
         state = %{state | tstate: tstate},
         {:ok, fw, state} <- query(state, "e", :ra),
         {:ok, ra, state} <- read_axis_constants(state, :ra),
         {:ok, dec, state} <- read_axis_constants(state, :dec),
         # the EQ6-R doesn't answer axis "3" (both) for F — initialize one at a time
         {:ok, _, state} <- query(state, "F", :ra),
         {:ok, _, state} <- query(state, "F", :dec) do
      state = %{state | connected: true, error: nil, firmware: fw, axes: %{ra: ra, dec: dec}}
      # Fail-safe: never inherit motion from before a (re)connect. A driver
      # restart mid-slew must not leave the motors running with no owner.
      state = state |> refresh() |> stop_axis(:ra) |> stop_axis(:dec)

      # If we were homed before a driver restart and the mount still counts from
      # somewhere other than its power-on value, it wasn't power-cycled: keep home.
      fresh_boot? = state.axes.ra.steps == P.center() and state.axes.dec.steps == P.center()
      was_homed = :persistent_term.get({__MODULE__, state.id, :homed}, false)
      state = if was_homed && not fresh_boot?, do: %{state | homed: true, homed_at: if(is_integer(was_homed), do: was_homed)}, else: state
      if fresh_boot?, do: :persistent_term.erase({__MODULE__, state.id, :homed})

      {:ok, state}
    else
      {:error, reason, state} ->
        safe_close(state)
        {:error, reason}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp read_axis_constants(state, axis) do
    with {:ok, cpr, state} <- query(state, "a", axis),
         {:ok, tf, state} <- query(state, "b", axis),
         {:ok, hs, state} <- query(state, "g", axis) do
      ax = %{
        steps_per_rev: P.to_int(cpr),
        timer_freq: P.to_int(tf),
        high_speed_ratio: P.to_int(hs),
        steps: P.center(),
        degrees: 0.0,
        running: false,
        mode: :slew,
        direction: :forward,
        speed: :slow,
        goto_pending: false
      }

      {:ok, ax, state}
    end
  end

  defp safe_close(%{tstate: nil}), do: :ok
  defp safe_close(%{mod: mod, tstate: t}), do: mod.close(t)

  # -- polling -------------------------------------------------------------------------------

  defp refresh(state), do: state |> refresh_axis(:ra) |> refresh_axis(:dec)

  defp refresh_axis(%{connected: false} = state, _axis), do: state

  defp refresh_axis(state, axis) do
    with {:ok, pos, state} <- query(state, "j", axis),
         {:ok, status, state} <- query(state, "f", axis) do
      ax = state.axes[axis]
      steps = P.to_int(pos)
      degrees = P.steps_to_degrees(steps, ax.steps_per_rev)
      now = System.monotonic_time(:millisecond)

      # Observed velocity, so limits can be applied with lookahead.
      deg_per_s =
        case ax[:seen_at] do
          nil -> 0.0
          t when now - t < 50 -> ax[:deg_per_s] || 0.0
          t -> (degrees - ax.degrees) * 1000 / (now - t)
        end

      ax =
        ax
        |> Map.merge(P.decode_status(status))
        |> Map.merge(%{steps: steps, degrees: degrees, deg_per_s: deg_per_s, seen_at: now})

      %{state | axes: Map.put(state.axes, axis, ax)}
    else
      {:error, reason, state} -> die(state, reason)
    end
  end

  # -- wire --------------------------------------------------------------------------------------

  defp query(state, cmd, axis, data \\ "") do
    case exchange(state, P.encode(cmd, axis, data)) do
      {{:ok, reply}, state} -> {:ok, reply, state}
      {{:error, reason}, state} -> {:error, {cmd, axis, reason}, state}
    end
  end

  # Fire a command whose failure means the link is gone: let the supervisor restart us.
  defp send!(state, cmd, axis, data \\ "") do
    case query(state, cmd, axis, data) do
      {:ok, _, state} -> state
      {:error, {_, _, :motor_running}, state} -> state
      {:error, reason, state} -> die(state, reason)
    end
  end

  defp exchange(%{mod: mod, tstate: t} = state, frame) do
    case mod.exchange(t, frame) do
      {:ok, raw, t} -> {P.decode(raw), %{state | tstate: t}}
      {:error, reason, t} -> {{:error, reason}, %{state | tstate: t}}
    end
  end

  defp die(state, reason) do
    Logger.error("mount #{state.id}: #{inspect(reason)}; restarting driver")
    Telescope.Events.emit(:mount, :link_lost, %{id: state.id, reason: inspect(reason)})
    safe_close(state)
    exit({:mount_link_lost, reason})
  end

  defp put_axis(state, axis, key, value),
    do: %{state | axes: Map.update!(state.axes, axis, &Map.put(&1, key, value))}

  # -- soft limits ----------------------------------------------------------------------------------
  # Degrees from home per axis, e.g. %{ra: {-100.0, 100.0}, dec: {-95.0, 95.0}}.
  # Nothing is enforced until set_home has been called: before that the counts
  # are wherever the mount happened to be at power-on.

  defp limits_for(%{homed: true, limits: limits}, axis) when is_map(limits), do: limits[axis]
  defp limits_for(_state, _axis), do: nil

  defp within_limits?(state, axis, degrees) do
    case limits_for(state, axis) do
      {lo, hi} -> degrees >= lo and degrees <= hi
      nil -> true
    end
  end

  # Already at/over the edge and asked to keep going that way?
  defp at_limit?(state, axis, dir) do
    case limits_for(state, axis) do
      {lo, hi} ->
        deg = state.axes[axis].degrees
        (dir == :forward and deg >= hi) or (dir == :reverse and deg <= lo)

      nil ->
        false
    end
  end

  defp dir_of(rate) when rate >= 0, do: :forward
  defp dir_of(_), do: :reverse

  # Runs every poll: a slew about to cross a limit is stopped. Looks one
  # second ahead at the observed velocity — a full-speed slew covers ~3° in
  # that time and the real mount needs most of it to ramp down.
  @lookahead_s 1.0

  defp enforce_limits(state) do
    Enum.reduce([:ra, :dec], state, fn axis, state ->
      ax = state.axes[axis]
      ahead = ax.degrees + (ax[:deg_per_s] || 0.0) * @lookahead_s

      if ax.running and
           (at_limit?(state, axis, ax.direction) or not within_limits?(state, axis, ahead)) do
        Logger.warning(
          "mount #{state.id}: #{axis} hit soft limit at #{Float.round(ax.degrees, 2)}°, stopping"
        )

        Telescope.Events.emit(:mount, :limit_stop, %{id: state.id, axis: axis, degrees: Float.round(ax.degrees, 2)})
        state = stop_axis(state, axis)
        if axis == :ra, do: %{state | tracking: :off}, else: state
      else
        state
      end
    end)
  end

  # -- snapshot ----------------------------------------------------------------------------------------

  defp snapshot(state) do
    %{
      id: state.id,
      node: node(),
      connected: state.connected,
      error: state.error,
      firmware: state.firmware,
      tracking: state.tracking,
      homed: state.homed,
      homed_at: Map.get(state, :homed_at),
      estop_at: Map.get(state, :estop_at),
      limits: if(state.homed, do: state.limits),
      axes:
        Map.new(state.axes, fn {k, ax} ->
          {k, Map.take(ax, [:degrees, :steps, :running, :mode, :direction, :speed, :blocked, :deg_per_s, :goto_pending])}
        end)
    }
  end

  defp broadcast(state) do
    Telescope.broadcast("mount:#{state.id}", {:mount, snapshot(state)})
    state
  end
end
