defmodule Mount.Server do
  @moduledoc """
  One process per mount. Owns the transport, keeps a live picture of both axes,
  and turns high-level requests (slew at a rate, nudge, go to a relative
  position, track) into protocol frames.

  Position is polled every #{250} ms and broadcast on `"mount:<id>"` as
  `{:mount, snapshot}` so anything in the cluster can follow along.

  Safety: slews started with `hold: true` stop by themselves unless refreshed
  within #{900} ms — a held arrow button on a flaky link can't run away. A
  goto takes its axis over from any hold (the dead-man is cancelled, the axis
  stopped first) and answers `:ok` only once the axis is seen on its way: one
  the mount did not start is an error to the caller. An axis the board says
  is running whose count doesn't advance is a stall: both axes stop and the
  snapshot says which (`stalled`). The count is the board's own step counter,
  not a sensor on the axis: a tube pushed against a leg skips steps and the
  count carries on, so this catches a board that has stopped stepping, not a
  collision.
  """
  use GenServer
  require Logger

  alias Mount.Protocol, as: P

  @poll_ms 250
  @hold_grace_ms 900
  @stop_wait_ms 4_000
  # how long a goto has to be seen on its way before it counts as not started
  @goto_start_ms 1_000
  # as good as there: a short goto lands between two looks
  @goto_near_deg 0.01
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
    # events raised by the driver itself (connected, link lost, limit stop) say who
    Telescope.Events.tag("driver")
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
    state =
      state
      |> refresh()
      |> start_pending()
      |> enforce_limits()
      |> watch_stalls()
      |> maybe_resume_tracking()
      |> settle_gotos()

    Process.send_after(self(), :poll, @poll_ms)
    {:noreply, broadcast(state)}
  end

  # We trap exits (so terminate/2 can stop the motors), which turns the
  # serial port's own process closing into a message. A mount switched off
  # with its cable in did exactly that on every reconnect attempt, and with
  # no clause for it the driver crashed and restarted every few seconds: the
  # "disconnected" flicker on every page. A closed port shows up on the next
  # exchange anyway, and that is where a lost link is handled.
  def handle_info({:EXIT, _pid, :normal}, state), do: {:noreply, state}

  def handle_info({:EXIT, _pid, reason}, state) do
    Logger.warning("mount #{state.id}: serial process exited: #{inspect(reason)}")
    {:noreply, state}
  end

  # Only the dead-man armed now may stop its axis. Cancelling a timer does not
  # take back an expiry already in the mailbox: with the driver busy on the
  # cable as one fired, a goto that was waiting its turn started, and the old
  # expiry behind it stopped it a moment later, :ok already given (#122, the
  # Go To from Saturn to M31 that never left Saturn). So each expiry carries
  # its own timer's ref, and one that is no longer the axis's hold (a goto, a
  # stop or an un-held slew cancelled it, a refresh replaced it) is dropped.
  def handle_info({:timeout, ref, {:hold_expired, axis}}, state) do
    if state.holds[axis] == ref,
      do: {:noreply, %{stop_axis(state, axis) | holds: Map.delete(state.holds, axis)}},
      else: {:noreply, state}
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
        {:reply, :ok, broadcast(clear_stall(state))}
    end
  end

  # A page-level STOP of both axes is a "stop, whoever you are": it stamps
  # `estop_at` like the emergency stop so the model tracker ends too.
  def handle_call({:stop, :both}, _from, state) do
    state =
      state
      |> stop_axis(:ra)
      |> stop_axis(:dec)
      |> Map.merge(%{tracking: :off, estop_at: System.monotonic_time(:millisecond)})

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
      |> Map.merge(%{
        tracking: :off,
        holds: cancel_holds(state.holds),
        estop_at: System.monotonic_time(:millisecond)
      })

    {:reply, :ok, broadcast(refresh(state))}
  end

  def handle_call({:goto_relative, axis, degrees}, _from, state) when axis in [:ra, :dec] do
    ax = state.axes[axis]
    steps = abs(P.degrees_to_steps(degrees, ax.steps_per_rev))
    dir = if degrees >= 0, do: :forward, else: :reverse

    if within_limits?(state, axis, ax.degrees + degrees) do
      {reply, state} = state |> clear_stall() |> goto(axis, steps, dir)
      {:reply, reply, broadcast(state)}
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
      state = %{
        start_slew(state, :ra, rate)
        | tracking: mode,
          holds: cancel_hold(state.holds, :ra)
      }

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
      |> Map.merge(%{
        tracking: :off,
        homed: true,
        homed_at: System.os_time(:millisecond),
        estop_at: System.monotonic_time(:millisecond)
      })

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
        do:
          start_slew(
            state,
            :ra,
            signed(@tracking_rates[state.tracking], state.tracking_direction)
          ),
        else: state

    {:reply, :ok, broadcast(state)}
  end

  # -- motion ------------------------------------------------------------------------

  # A goto answers :ok only once the axis is seen on its way. In order: the
  # axis's dead-man is cancelled (a goto is not a held slew, and a hold left
  # armed by the last one, a tracker's or a pad's, would stop it a second
  # in); the axis is stopped and seen stopped, because the board refuses a
  # goto on a moving axis; the goto is sent; then the axis is watched until
  # it is under way. An axis that will not stop, a frame the board refuses
  # and a goto acknowledged but never started are errors to the caller, with
  # the axis left stopped so that nothing can start later by itself. Every
  # wait is bounded: @stop_wait_ms for the stop, @goto_start_ms for the start.
  defp goto(state, axis, steps, dir) do
    state = stop_axis(%{state | holds: cancel_hold(state.holds, axis)}, axis)
    from = state.axes[axis].steps

    frames = [
      {"G", P.motion_mode(:goto, dir)},
      {"H", P.from_int(steps)},
      {"M", P.from_int(min(3_500, div(steps, 2)))},
      {"J", ""}
    ]

    with false <- state.axes[axis].running,
         {:ok, state} <- send_each(state, axis, frames) do
      state
      |> put_axis(axis, :goto_pending, true)
      |> put_axis(axis, :goto_at, System.monotonic_time(:millisecond))
      |> put_axis(axis, :goto_to, from + if(dir == :forward, do: steps, else: -steps))
      |> goto_started(axis, dir, from, System.monotonic_time(:millisecond) + @goto_start_ms)
    else
      # still running after the stop's wait: told to stop, and no goto sent
      true -> goto_failed(state, axis, :motor_running)
      {:refused, state} -> goto_failed(stop_axis(state, axis), axis, :motor_running)
    end
  end

  # A goto's frames, in order, until one is refused. `!2` (motor running) is
  # the board saying no; anything else wrong on the wire is a lost link, as
  # it is for every other command.
  defp send_each(state, _axis, []), do: {:ok, state}

  defp send_each(state, axis, [{cmd, data} | rest]) do
    case query(state, cmd, axis, data) do
      {:ok, _, state} -> send_each(state, axis, rest)
      {:error, {_, _, :motor_running}, state} -> {:refused, state}
      {:error, reason, state} -> die(state, reason)
    end
  end

  # Acknowledged is not started. Under way means the board runs the axis as a
  # goto, or the count has moved toward the target, or the axis stands at the
  # target (a short one lands between two looks). A board that says it runs
  # while the count stays put is the stall watch's to catch, not this.
  defp goto_started(state, axis, dir, from, deadline) do
    state = refresh_axis(state, axis)
    ax = state.axes[axis]
    near = P.degrees_to_steps(@goto_near_deg, ax.steps_per_rev)
    toward = if dir == :forward, do: ax.steps - from, else: from - ax.steps

    cond do
      (ax.running and ax.mode == :goto) or toward >= near or
          (not ax.running and abs(ax.goto_to - ax.steps) <= near) ->
        {:ok, state}

      System.monotonic_time(:millisecond) > deadline ->
        goto_failed(stop_axis(state, axis), axis, :goto_not_started)

      true ->
        Process.sleep(50)
        goto_started(state, axis, dir, from, deadline)
    end
  end

  # Said in the log and in Events as well as to the caller, which may be a
  # page nobody is looking at. The driver's own tracking was stopped to make
  # way for the goto: it carries on from where the axis stands.
  defp goto_failed(state, axis, why) do
    Logger.warning("mount #{state.id}: #{axis} goto did not start: #{why}")
    Telescope.Events.emit(:mount, :goto_failed, %{id: state.id, axis: axis, why: why})
    state = put_axis(state, axis, :goto_pending, false)

    {{:error, why},
     if(axis == :ra and not state.axes.ra.running, do: resume_tracking(state), else: state)}
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
        ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == :fast and
            abs(rate) >= 4 ->
          :fast

        ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == :slow and
            abs(rate) <= 128 ->
          :slow

        true ->
          natural_mode
      end

    period = period_for(abs(rate), mode, ax)
    same_run? = ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == mode

    cond do
      # Same run and (nearly) the same speed: say nothing to the board. Held
      # controls refresh 4-5×/s; rewriting :I each time made the motor stutter.
      same_run? and close?(period, ax[:period]) ->
        put_axis(state, axis, :pending, nil)

      same_run? ->
        state
        |> send!("I", axis, P.from_int(period))
        |> put_axis(axis, :period, period)
        |> put_axis(axis, :pending, nil)

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
    (tf * if(mode == :fast, do: hs, else: 1) / steps_per_s) |> round() |> max(1) |> min(0xFFFFFF)
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

    if ax[:goto_pending] and not ax.running and not Map.has_key?(state.holds, :ra),
      do: resume_tracking(state),
      else: state
  end

  defp maybe_resume_tracking(state), do: state

  defp resume_tracking(%{tracking: :off} = state), do: state

  defp resume_tracking(%{tracking: mode} = state),
    do: start_slew(state, :ra, signed(@tracking_rates[mode], state.tracking_direction))

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

  # start_timer, not send_after: its expiry carries the timer's own ref, which
  # is how a stale one is told from the hold armed now (see :hold_expired)
  defp arm_hold(state, axis, true) do
    if ref = state.holds[axis], do: Process.cancel_timer(ref)
    ref = :erlang.start_timer(@hold_grace_ms, self(), {:hold_expired, axis})
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

      state =
        if was_homed && not fresh_boot?,
          do: %{state | homed: true, homed_at: if(is_integer(was_homed), do: was_homed)},
          else: state

      if fresh_boot?, do: :persistent_term.erase({__MODULE__, state.id, :homed})

      # Both counts at their power-on value: the mount itself was just switched
      # on, so anything measured against its old counts no longer holds (a Pi
      # reboot alone leaves the counts where they were). Say when, for anyone
      # holding an alignment on a mount that was never zeroed.
      state =
        if fresh_boot? do
          at = System.os_time(:millisecond)
          Telescope.Events.emit(:mount, :power_on, %{id: state.id})
          Telescope.broadcast("mount_power", {:mount_power_on, state.id, at})
          Map.put(state, :power_on_at, at)
        else
          state
        end

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

        Telescope.Events.emit(:mount, :limit_stop, %{
          id: state.id,
          axis: axis,
          degrees: Float.round(ax.degrees, 2)
        })

        state = stop_axis(state, axis)
        if axis == :ra, do: %{state | tracking: :off}, else: state
      else
        state
      end
    end)
  end

  # -- stalls ------------------------------------------------------------------------------------------
  # Told to move, count not moving: the board has stopped stepping (a fault,
  # a supply sagging under load) while still reporting "running". Every poll
  # compares the count's progress over the last window with the speed the
  # axis was commanded at. Only speeds that would cover a real distance in
  # the window are judged (a tracker's 1× moves 30″ in it, too little to
  # tell from a slow poll), and a goto only away from its braking zone at the
  # end. A stall stops both axes at once, tracking off, and stamps `estop_at`
  # so anything holding a target stands down; `stalled` stays in the
  # snapshot until the next command.
  #
  # What this cannot see: the EQ6-R's motors are steppers and the count is
  # the steps the board sent, so a tube against a tripod leg skips steps and
  # the count carries on. Seeing that takes something watching the tube
  # itself (the camera, a tilt sensor on the tube).

  @stall_window_ms 1_500
  @stall_min_steps 400
  # a goto runs far faster than this once under way
  @goto_floor_x 20
  @brake_steps 6_000

  defp watch_stalls(%{connected: true} = state) do
    now = System.monotonic_time(:millisecond)

    Enum.reduce([:ra, :dec], state, fn axis, st ->
      ax = st.axes[axis]

      case {ax.running, ax[:watch]} do
        {false, _} ->
          put_axis(st, axis, :watch, nil)

        {true, nil} ->
          put_axis(st, axis, :watch, {ax.steps, now})

        {true, {from, t0}} when now - t0 >= @stall_window_ms ->
          expected = expected_steps_per_s(ax) * (now - t0) / 1000
          moved = abs(ax.steps - from)

          if expected >= @stall_min_steps and moved < 0.2 * expected,
            do: stall(st, axis, moved, expected),
            else: put_axis(st, axis, :watch, {ax.steps, now})

        _ ->
          st
      end
    end)
  end

  defp watch_stalls(state), do: state

  defp expected_steps_per_s(%{mode: :goto} = ax) do
    if is_integer(ax[:goto_to]) and abs(ax.goto_to - ax.steps) > @brake_steps,
      do: P.sidereal_rate(ax.steps_per_rev) * @goto_floor_x,
      else: 0.0
  end

  defp expected_steps_per_s(%{period: period} = ax) when is_integer(period) and period > 0,
    do: ax.timer_freq * if(ax.speed == :fast, do: ax.high_speed_ratio, else: 1) / period

  defp expected_steps_per_s(_), do: 0.0

  defp stall(state, axis, moved, expected) do
    ax = state.axes[axis]
    deg = fn steps -> Float.round(steps * 360 / ax.steps_per_rev, 2) end

    Logger.error(
      "mount #{state.id}: #{axis} stalled: moved #{moved} steps of #{round(expected)} expected; stopping both axes"
    )

    Telescope.Events.emit(:mount, :stall, %{
      id: state.id,
      axis: axis,
      moved_deg: deg.(moved),
      expected_deg: deg.(expected)
    })

    state
    |> send!("L", :ra)
    |> send!("L", :dec)
    |> put_axis(:ra, :watch, nil)
    |> put_axis(:dec, :watch, nil)
    |> put_axis(:ra, :pending, nil)
    |> put_axis(:dec, :pending, nil)
    |> Map.merge(%{
      tracking: :off,
      holds: cancel_holds(state.holds),
      estop_at: System.monotonic_time(:millisecond),
      stalled: %{
        axis: axis,
        at: System.os_time(:millisecond),
        moved_deg: deg.(moved),
        expected_deg: deg.(expected)
      }
    })
    |> refresh()
  end

  defp clear_stall(state), do: Map.put(state, :stalled, nil)

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
      power_on_at: Map.get(state, :power_on_at),
      estop_at: Map.get(state, :estop_at),
      stalled: Map.get(state, :stalled),
      limits: if(state.homed, do: state.limits),
      axes:
        Map.new(state.axes, fn {k, ax} ->
          {k,
           Map.take(ax, [
             :degrees,
             :steps,
             :running,
             :mode,
             :direction,
             :speed,
             :blocked,
             :deg_per_s,
             :goto_pending
           ])}
        end)
    }
  end

  defp broadcast(state) do
    Telescope.broadcast("mount:#{state.id}", {:mount, snapshot(state)})
    state
  end
end
