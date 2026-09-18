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
      mod: mod,
      topts: topts,
      tstate: nil,
      connected: false,
      error: nil,
      firmware: nil,
      axes: %{},
      tracking: :off,
      holds: %{}
    }

    send(self(), :connect)
    {:ok, state}
  end

  @impl true
  def handle_info(:connect, state) do
    case connect(state) do
      {:ok, state} ->
        Logger.info("mount #{state.id}: connected, firmware #{state.firmware}")
        send(self(), :poll)
        {:noreply, broadcast(state)}

      {:error, reason} ->
        Logger.warning("mount #{state.id}: #{inspect(reason)}, retrying")
        Process.send_after(self(), :connect, @reconnect_ms)
        {:noreply, broadcast(%{state | connected: false, error: reason})}
    end
  end

  def handle_info(:poll, state) do
    state = state |> refresh() |> enforce_limits() |> maybe_resume_tracking()
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

  def handle_call({:stop, :both}, _from, state) do
    state = state |> stop_axis(:ra) |> stop_axis(:dec) |> Map.put(:tracking, :off)
    {:reply, :ok, broadcast(state)}
  end

  def handle_call({:stop, axis}, _from, state) do
    state = stop_axis(state, axis)
    state = if axis == :ra, do: %{state | tracking: :off}, else: state
    {:reply, :ok, broadcast(state)}
  end

  def handle_call(:emergency_stop, _from, state) do
    state = state |> send!("L", :both) |> Map.merge(%{tracking: :off, holds: cancel_holds(state.holds)})
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
      state = %{start_slew(state, :ra, rate) | tracking: mode}
      {:reply, :ok, broadcast(state)}
    end
  end

  def handle_call({:track, :off}, _from, state) do
    {:reply, :ok, broadcast(%{stop_axis(state, :ra) | tracking: :off})}
  end

  def handle_call(:set_home, _from, state) do
    state =
      state
      |> stop_axis(:ra)
      |> stop_axis(:dec)
      |> send!("E", :both, P.from_int(P.center()))
      |> Map.merge(%{tracking: :off, homed: true})

    {:reply, :ok, broadcast(refresh(state))}
  end

  def handle_call({:raw, frame}, _from, state) do
    {reply, state} = exchange(state, frame)
    {:reply, reply, state}
  end

  # -- motion ------------------------------------------------------------------------

  defp goto(state, axis, steps, dir) do
    state =
      state
      |> stop_axis(axis)
      |> send!("G", axis, P.motion_mode(:goto, dir))
      |> send!("H", axis, P.from_int(steps))
      |> send!("M", axis, P.from_int(min(3_500, div(steps, 2))))
      |> send!("J", axis)
      |> put_axis(axis, :goto_pending, true)
      |> refresh_axis(axis)
  end

  defp start_slew(state, axis, rate) do
    ax = state.axes[axis]
    dir = if rate >= 0, do: :forward, else: :reverse
    {mode, period} = P.slew_params(abs(rate), ax)

    # In slew mode the period can change live; anything else needs a stop first.
    same_run? = ax.running and ax.mode == :slew and ax.direction == dir and ax.speed == mode

    if same_run? do
      send!(state, "I", axis, P.from_int(period))
    else
      state
      |> stop_axis(axis)
      |> send!("G", axis, P.motion_mode(mode, dir))
      |> send!("I", axis, P.from_int(period))
      |> send!("J", axis)
    end
    |> put_axis(axis, :goto_pending, false)
    |> refresh_axis(axis)
  end

  defp stop_axis(state, axis) do
    state = send!(state, "K", axis)
    wait_stopped(state, axis, System.monotonic_time(:millisecond) + @stop_wait_ms)
  end

  defp wait_stopped(state, axis, deadline) do
    state = refresh_axis(state, axis)

    cond do
      not state.axes[axis].running -> state
      System.monotonic_time(:millisecond) > deadline -> state
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

  defp arm_hold(state, _axis, false), do: state

  defp arm_hold(state, axis, true) do
    if ref = state.holds[axis], do: Process.cancel_timer(ref)
    ref = Process.send_after(self(), {:hold_expired, axis}, @hold_grace_ms)
    %{state | holds: Map.put(state.holds, axis, ref)}
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
         {:ok, _, state} <- query(state, "F", :both) do
      state = %{state | connected: true, error: nil, firmware: fw, axes: %{ra: ra, dec: dec}}
      {:ok, refresh(state)}
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

      if ax.running and (at_limit?(state, axis, ax.direction) or not within_limits?(state, axis, ahead)) do
        Logger.warning("mount #{state.id}: #{axis} hit soft limit at #{Float.round(ax.degrees, 2)}°, stopping")
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
      limits: if(state.homed, do: state.limits),
      axes:
        Map.new(state.axes, fn {k, ax} ->
          {k, Map.take(ax, [:degrees, :steps, :running, :mode, :direction, :speed, :blocked])}
        end)
    }
  end

  defp broadcast(state) do
    Telescope.broadcast("mount:#{state.id}", {:mount, snapshot(state)})
    state
  end
end
