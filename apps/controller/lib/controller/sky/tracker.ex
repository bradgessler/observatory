defmodule Controller.Sky.Tracker do
  @moduledoc """
  Tracking through the pointing model instead of the mount's sidereal motor:
  every couple of seconds, ask the model where the encoders should be for the
  target now and a little later, and run both axes at the rates that get
  there — plus a gentle correction of whatever error has crept in. On a
  polar-aligned mount that is one axis at sidereal; on a mount set down
  anyhow it is two axes at changing rates, which is the only way to hold a
  target with a crooked polar axis.

  Stays out of the way: while someone else is driving (a held slew, a goto)
  it pauses and resumes when they let go; an emergency stop on the driver
  (`estop_at` in the snapshot, from any surface or the pad) ends it. State is
  per mount; the current readout is in `:persistent_term` so status strips
  can show it for free.
  """
  use GenServer
  require Logger

  alias Controller.Sky.{Astro, Pointing}

  @tick_ms 2_000
  @lookahead_s 10.0
  # correct the accumulated error over this many seconds
  @correct_s 20.0
  @max_rate 16.0
  @sidereal_deg_s 360.0 / 86_164.0905

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Follow `obj` (`%{ra_deg, dec_deg, name}`) with mount `id`."
  def track(id, obj), do: GenServer.cast(__MODULE__, {:track, id, obj})
  def stop(id), do: GenServer.cast(__MODULE__, {:stop, id})
  def stop_all, do: GenServer.cast(__MODULE__, :stop_all)

  @doc "Readout for a mount: nil, or `%{name, ra_rate, dec_rate, error_arcmin, paused, since}`."
  def status(id), do: :persistent_term.get({__MODULE__, id}, nil)

  def active?(id), do: status(id) != nil

  @impl true
  def init(_) do
    :timer.send_interval(@tick_ms, :tick)
    {:ok, %{}}
  end

  @impl true
  def handle_cast({:track, id, obj}, s) do
    case ref_for(id) do
      nil ->
        {:noreply, s}

      ref ->
        # the driver's own sidereal tracking would fight ours — but turning it
        # off stops the RA axis, which would kill a goto in flight, so only
        # do it when it is actually on
        case safe(fn -> Mount.snapshot(ref) end) do
          %{tracking: mode} when mode != :off -> safe(fn -> Mount.track(ref, :off) end)
          _ -> :ok
        end

        entry = %{ref: ref, obj: obj, cmd: %{ra: 0.0, dec: 0.0}, paused: false, since: DateTime.utc_now(), started_ms: System.os_time(:millisecond)}
        publish(id, entry, nil)
        send(self(), {:tick_one, id})
        {:noreply, Map.put(s, id, entry)}
    end
  end

  def handle_cast({:stop, id}, s), do: {:noreply, drop(s, id, :stop)}
  def handle_cast(:stop_all, s), do: {:noreply, Enum.reduce(Map.keys(s), s, &drop(&2, &1, :stop))}

  @impl true
  def handle_info(:tick, s), do: {:noreply, Enum.reduce(Map.keys(s), s, &step/2)}
  def handle_info({:tick_one, id}, s), do: {:noreply, if(Map.has_key?(s, id), do: step(id, s), else: s)}
  def handle_info(_, s), do: {:noreply, s}

  defp step(id, s) do
    entry = s[id]

    case safe(fn -> Mount.snapshot(entry.ref) end) do
      %{connected: true, axes: axes} = snap ->
        cond do
          # STOP was pressed somewhere since we started: that is the end of it
          is_integer(snap[:estop_at]) and snap.estop_at >= entry.started_ms ->
            Logger.info("tracker: #{id} emergency stop — ending")
            drop(s, id, :estop)

          busy?(axes) ->
            {:noreply_entry, %{entry | paused: true}} |> commit(id, s, nil)

          driven_by_someone_else?(axes, entry.cmd) ->
            {:noreply_entry, %{entry | paused: true}} |> commit(id, s, nil)

          true ->
            # a keypad release leaves an axis stopped: re-command as needed
            {entry, readout} = drive(id, entry, snap)
            {:noreply_entry, entry} |> commit(id, s, readout)
        end

      _ ->
        drop(s, id, :gone)
    end
  end

  defp commit({:noreply_entry, entry}, id, s, readout) do
    publish(id, entry, readout)
    Map.put(s, id, entry)
  end

  # Where should the encoders be now and in a moment? Rates from the difference,
  # error from where they actually are.
  defp drive(id, entry, snap) do
    now = DateTime.utc_now()
    ctx = Pointing.context(now, id)
    later = Pointing.context(DateTime.add(now, round(@lookahead_s), :second), id)
    cur = {snap.axes.ra.degrees, snap.axes.dec.degrees}
    {r1, d1} = Pointing.axes_for(entry.obj, ctx, near: cur)
    {r2, d2} = Pointing.axes_for(entry.obj, later, near: {r1, d1})

    err_ra = Astro.norm180(r1 - elem(cur, 0))
    err_dec = d1 - elem(cur, 1)
    rate_ra = (Astro.norm180(r2 - r1) / @lookahead_s + err_ra / @correct_s) / @sidereal_deg_s
    rate_dec = ((d2 - d1) / @lookahead_s + err_dec / @correct_s) / @sidereal_deg_s
    cmd = %{ra: clamp(rate_ra), dec: clamp(rate_dec)}

    # re-issue when the wanted rate changed, or when an axis that should be
    # running has been stopped by a hand (release after a nudge)
    for {axis, rate} <- cmd,
        abs(rate - Map.get(entry.cmd, axis)) > 0.02 or (abs(rate) >= 0.02 and not snap.axes[axis].running) do
      if abs(rate) < 0.02,
        do: safe(fn -> Mount.stop(entry.ref, axis) end),
        else: safe(fn -> Mount.slew(entry.ref, axis, rate) end)
    end

    error_arcmin = :math.sqrt(err_ra * err_ra + err_dec * err_dec) * 60
    {%{entry | cmd: cmd, paused: false}, %{error_arcmin: error_arcmin}}
  end

  defp clamp(r), do: r |> max(-@max_rate) |> min(@max_rate)

  # a goto still in flight: the driver clears the flag once it has landed
  defp busy?(axes), do: Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end)

  # an axis moving at a rate we did not ask for means a hand on a control
  defp driven_by_someone_else?(axes, cmd) do
    Enum.any?(axes, fn {axis, ax} ->
      actual = Map.get(ax, :deg_per_s, 0.0) / @sidereal_deg_s
      ax.running and abs(abs(actual) - abs(Map.get(cmd, axis))) > 3.0
    end)
  end

  defp drop(s, id, why) do
    if entry = s[id] do
      if why == :stop, do: for(axis <- [:ra, :dec], do: safe(fn -> Mount.stop(entry.ref, axis) end))
      :persistent_term.erase({__MODULE__, id})
      Telescope.broadcast("tracker", {:tracker, id, nil})
    end

    Map.delete(s, id)
  end

  defp publish(id, entry, readout) do
    status = %{
      name: entry.obj.name,
      ra_rate: entry.cmd.ra,
      dec_rate: entry.cmd.dec,
      error_arcmin: readout && readout.error_arcmin,
      paused: entry.paused,
      since: entry.since
    }

    :persistent_term.put({__MODULE__, id}, status)
    Telescope.broadcast("tracker", {:tracker, id, status})
  end

  defp ref_for(id), do: Enum.find(safe(fn -> Mount.list() end) || [], &(&1.id == id))

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> nil
    end
  end
end
