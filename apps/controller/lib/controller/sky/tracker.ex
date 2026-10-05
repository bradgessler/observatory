defmodule Controller.Sky.Tracker do
  @moduledoc """
  Tracking through the pointing model instead of the mount's sidereal motor:
  twice a second, ask the model where the encoders should be for the target
  now and a little later, and run both axes at the rates that get there —
  plus a gentle correction of whatever error has crept in. On a polar-aligned
  mount that is one axis at sidereal; on a mount set down anyhow it is two
  axes at changing rates, which is the only way to hold a target with a
  crooked polar axis.

  Stays out of the way: while someone else is driving (a held slew, a goto)
  it pauses, and when they let go it holds *where the tube is now* — a hand
  that centred the star wins over the model. A STOP on any page or the pad
  (`estop_at` in the snapshot) ends it.

  Fail-safe: every slew it issues carries the driver's dead-man (`hold: true`)
  and is refreshed each tick, so if this process dies or stalls the motors
  stop within a second on their own. It never chases a large error: past a
  few degrees (a pier flip the model wants, a target the limits won't allow)
  it stops and says so rather than crawl across the sky at 16×. On a mount
  that was never zeroed (no soft limits) it also stops when the counterweight
  reaches the hard limit above level (`Pointing.meridian_hard/0`): the next Go
  To flips to the other side of the pier.

  State is per mount; the current readout is in `:persistent_term` so status
  strips can show it for free.
  """
  use GenServer
  require Logger

  alias Controller.Sky.{Astro, Pointing}

  # the driver's hold grace is 900 ms: refresh well inside it
  @tick_ms 500
  @lookahead_s 10.0
  # correct the accumulated error over this many seconds
  @correct_s 20.0
  @max_rate 16.0
  # further off than this and something else is wrong: stop, don't chase
  @give_up_deg 5.0
  @sidereal_deg_s 360.0 / 86_164.0905
  # what is being held, per mount, for after a restart
  @hold_key "hold"

  def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc "Follow `obj` (`%{ra_deg, dec_deg, name}`) with mount `id`."
  def track(id, obj), do: GenServer.cast(__MODULE__, {:track, id, obj})

  @doc """
  Hold where the tube is (`here`, its RA/Dec now) while naming what it's on
  (`target`, the catalogue object): after a search or a nudge found it, so a
  Centered records the object, not the spot.
  """
  def track(id, here, target), do: GenServer.cast(__MODULE__, {:track, id, Map.put(here, :target, target)})

  @doc """
  Stop following (synchronous, so a goto issued right after cannot be undone
  by our own axis stops). `halt: false` drops the entry without touching the
  motors — for a caller that is about to command the axes itself.
  """
  def stop(id, opts \\ []) do
    GenServer.call(__MODULE__, {:stop, id, Keyword.get(opts, :halt, true)}, 5_000)
  catch
    :exit, _ -> :ok
  end

  def stop_all do
    GenServer.call(__MODULE__, :stop_all, 5_000)
  catch
    :exit, _ -> :ok
  end

  @doc "Readout for a mount: nil, or `%{name, ra_rate, dec_rate, error_arcmin, paused, since}`."
  def status(id), do: :persistent_term.get({__MODULE__, id}, nil)

  def active?(id), do: status(id) != nil

  @doc "Why the last hold on a mount ended, if it ended on its own: `%{name, why, at}` or nil."
  def ended(id), do: :persistent_term.get({__MODULE__, :ended, id}, nil)

  @doc """
  A hold the box went down in the middle of (a firmware upgrade, a crash, a
  reboot), for a page to offer back: `%{target, since}` or nil (#99). Kept
  in Settings, so it survives the restart; cleared when a person or a limit
  ends the hold, and ignored when the mount itself has been switched on
  since, because then its counts no longer point where they did. Nothing
  moves on its own: resuming is a Go To someone taps.
  """
  def interrupted(id) do
    with false <- active?(id),
         %{"target" => t, "since" => since} <- Map.get(Controller.Settings.get(@hold_key, %{}), id),
         {:ok, at, _} <- DateTime.from_iso8601(since),
         false <- switched_on_since?(id, at) do
      %{target: %{id: t["id"], name: t["name"], ra_deg: t["ra_deg"], dec_deg: t["dec_deg"]}, since: at}
    else
      _ -> nil
    end
  end

  @doc "Forget an interrupted hold (resumed, or declined)."
  def forget_interrupted(id), do: Controller.Settings.put(@hold_key, Map.delete(Controller.Settings.get(@hold_key, %{}), id))

  defp switched_on_since?(id, at) do
    on = Controller.MountPower.last_on(id)
    is_integer(on) and on > DateTime.to_unix(at, :millisecond)
  rescue
    _ -> false
  catch
    :exit, _ -> false
  end

  defp remember(id, target) do
    t = for {k, v} <- target, into: %{}, do: {to_string(k), v}
    held = Map.put(Controller.Settings.get(@hold_key, %{}), id, %{"target" => t, "since" => DateTime.to_iso8601(DateTime.utc_now())})
    Controller.Settings.put(@hold_key, held)
  rescue
    _ -> :ok
  end

  @impl true
  def init(_) do
    Process.flag(:trap_exit, true)
    Telescope.Events.tag("tracking")
    :timer.send_interval(@tick_ms, :tick)
    {:ok, %{}}
  end

  @impl true
  def handle_cast({:track, id, obj}, s) do
    case ref_for(id) do
      nil ->
        {:noreply, s}

      ref ->
        # the driver's own sidereal tracking would fight ours; the driver
        # keeps a goto in flight alive when the mode is turned off
        case safe(fn -> Mount.snapshot(ref) end) do
          %{tracking: mode} when mode != :off -> safe(fn -> Mount.track(ref, :off) end)
          _ -> :ok
        end

        entry = %{
          ref: ref,
          obj: obj,
          # the catalogue object, untouched by re-basing: for "that's centred" and "about"
          target: Map.take(obj[:target] || obj, [:id, :name, :ra_deg, :dec_deg]),
          cmd: %{ra: 0.0, dec: 0.0},
          paused: false,
          settled: false,
          since: DateTime.utc_now(),
          started_ms: System.monotonic_time(:millisecond)
        }

        Telescope.Events.emit(:tracker, :start, %{id: id, target: obj.name})
        :persistent_term.erase({__MODULE__, :ended, id})
        remember(id, entry.target)
        publish(id, entry, nil)
        send(self(), {:tick_one, id})
        {:noreply, Map.put(s, id, entry)}
    end
  end

  @impl true
  def handle_call({:stop, id, halt?}, _from, s),
    do: {:reply, :ok, drop(s, id, if(halt?, do: :stop, else: :handoff))}

  def handle_call(:stop_all, _from, s),
    do: {:reply, :ok, Enum.reduce(Map.keys(s), s, &drop(&2, &1, :stop))}

  @impl true
  def handle_info(:tick, s), do: {:noreply, Enum.reduce(Map.keys(s), s, &step/2)}

  def handle_info({:tick_one, id}, s),
    do: {:noreply, if(Map.has_key?(s, id), do: step(id, s), else: s)}

  def handle_info(_, s), do: {:noreply, s}

  # Going away for any reason: leave nothing running in our name.
  @impl true
  # (the hold stays remembered: this is the box going down, not a person)
  def terminate(_reason, s), do: Enum.reduce(Map.keys(s), s, &drop(&2, &1, :shutdown))

  defp step(id, s) do
    entry = s[id]

    case safe(fn -> Mount.snapshot(entry.ref) end) do
      %{connected: true, axes: axes} = snap ->
        cond do
          # STOP was pressed somewhere since we started: that is the end of it
          is_integer(snap[:estop_at]) and snap.estop_at > entry.started_ms ->
            Logger.info("tracker: #{id} stop pressed — ending")
            drop(s, id, :estop)

          # our own goto (or a nudge) still in flight, or a hand on a control:
          # stand back; the readout says which
          busy?(axes) ->
            {:noreply_entry, %{entry | paused: :goto}} |> commit(id, s, nil)

          driven_by_someone_else?(axes, entry.cmd) ->
            {:noreply_entry, %{entry | paused: :hand}} |> commit(id, s, nil)

          true ->
            case drive(id, entry, snap) do
              {:ok, entry, readout} -> {:noreply_entry, entry} |> commit(id, s, readout)
              {:give_up, why} -> drop(s, id, why)
            end
        end

      _ ->
        drop(s, id, :gone)
    end
  rescue
    e ->
      Logger.error("tracker: #{id} #{Exception.message(e)} — ending")
      drop(s, id, :error)
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

    # The goto that started us lands a little off; that error we correct.
    # Any pause after that was a hand (a nudge, a pull) centring the object:
    # from then on hold where the tube is, not where the model says — the
    # hand knows better than the fit.
    entry = if entry.paused == :hand and entry.settled, do: rebase(entry, snap, ctx), else: entry

    {r1, d1} = Pointing.axes_for(entry.obj, ctx, near: {:stay, cur})
    {r2, d2} = Pointing.axes_for(entry.obj, later, near: {:stay, {r1, d1}})

    err_ra = Astro.norm180(r1 - elem(cur, 0))
    err_dec = d1 - elem(cur, 1)
    cw = Pointing.counterweight(ctx, r1)
    # where this hold had it a moment ago: as far behind as `later` is ahead
    cw_was = Pointing.counterweight(ctx, r1 - Astro.norm180(r2 - r1))

    cond do
      # never zeroed: no soft limits, so the counterweight is the limit. With its side only
      # guessed, that is a limit the hold has to reach itself: where it starts is not refused
      not snap.homed and Pointing.hold_limit?(ctx, cw_was, cw) ->
        {:give_up, :meridian}

      abs(err_ra) > @give_up_deg or abs(err_dec) > @give_up_deg ->
        {:give_up, :lost}

      true ->
        rate_ra = (Astro.norm180(r2 - r1) / @lookahead_s + err_ra / @correct_s) / @sidereal_deg_s
        rate_dec = ((d2 - d1) / @lookahead_s + err_dec / @correct_s) / @sidereal_deg_s
        cmd = %{ra: clamp(rate_ra), dec: clamp(rate_dec)}

        # every running axis is re-issued each tick (that feeds the dead-man;
        # the driver says nothing to the board when nothing changed); an axis
        # that should be still is stopped once
        for {axis, rate} <- cmd do
          cond do
            abs(rate) >= 0.02 ->
              safe(fn -> Mount.slew(entry.ref, axis, rate, hold: true, quiet: true) end)

            abs(Map.get(entry.cmd, axis)) >= 0.02 ->
              safe(fn -> Mount.stop(entry.ref, axis) end)

            true ->
              :ok
          end
        end

        # the log gets a line when a rate really changes, not every tick
        if abs(cmd.ra - entry.cmd.ra) > 0.5 or abs(cmd.dec - entry.cmd.dec) > 0.5,
          do:
            Telescope.Events.emit(:tracker, :rates, %{
              id: id,
              target: entry.obj.name,
              ra: Float.round(cmd.ra, 2),
              dec: Float.round(cmd.dec, 2)
            })

        error_arcmin = :math.sqrt(err_ra * err_ra + err_dec * err_dec) * 60

        {:ok, %{entry | cmd: cmd, paused: false, settled: true},
         %{error_arcmin: error_arcmin, cw: cw}}
    end
  end

  defp rebase(entry, snap, ctx) do
    case Pointing.scope_radec(snap, ctx) do
      {ra, dec} ->
        %{entry | obj: %{entry.obj | ra_deg: ra, dec_deg: dec}, cmd: %{ra: 0.0, dec: 0.0}}

      _ ->
        entry
    end
  end

  defp clamp(r), do: r |> max(-@max_rate) |> min(@max_rate)

  # a goto still in flight: the driver clears the flag once it has landed
  defp busy?(axes), do: Enum.any?(axes, fn {_, ax} -> Map.get(ax, :goto_pending, false) end)

  # an axis moving at a rate we did not ask for means a hand on a control;
  # the driver's rate estimate is too coarse to tell 1× from 2×, so the game
  # pad (whose slowest band is 2×) is asked directly whether it is holding
  defp driven_by_someone_else?(axes, cmd) do
    held = pad_held()

    Enum.any?(axes, fn {axis, ax} ->
      actual = Map.get(ax, :deg_per_s, 0.0) / @sidereal_deg_s
      axis in held or (ax.running and abs(abs(actual) - abs(Map.get(cmd, axis))) > 3.0)
    end)
  end

  defp pad_held do
    case Input.status() do
      %{held: held} when is_list(held) -> held
      _ -> []
    end
  rescue
    _ -> []
  catch
    :exit, _ -> []
  end

  defp drop(s, id, why) do
    if entry = s[id] do
      Telescope.Events.emit(:tracker, :end, %{id: id, target: entry.obj.name, why: why})

      # :handoff — the caller is about to command the axes itself; every other end stops what we ran
      if why != :handoff,
        do: for(axis <- [:ra, :dec], do: safe(fn -> Mount.stop(entry.ref, axis) end))

      :persistent_term.erase({__MODULE__, id})
      # a person or a limit ended it: nothing to offer back after a restart
      if why in [:stop, :estop, :meridian, :lost], do: forget_interrupted(id)
      # ended on its own (not a person's stop or a Go To taking over): the pages say why
      if why in [:meridian, :lost, :gone, :error, :estop],
        do:
          :persistent_term.put({__MODULE__, :ended, id}, %{
            name: entry.obj.name,
            why: why,
            at: DateTime.utc_now()
          })

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
      cw: readout && readout[:cw],
      paused: entry.paused,
      since: entry.since,
      target: entry.target
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
