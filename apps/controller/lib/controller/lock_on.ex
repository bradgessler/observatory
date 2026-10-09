defmodule Controller.LockOn do
  @moduledoc """
  Lock On: hold a target still in the telescope camera's picture by driving
  both motors, whatever the mount's alignment. No polar alignment, no level
  tripod: it measures how the target drifts and how each motor moves the
  picture, then steers from what the camera sees (`Controller.LockOn.Law`).

      Controller.LockOn.start("ttyUSB0")             # calibrate (about a minute), then hold
      Controller.LockOn.start("ttyUSB0", saved: true) # hold at once on the last calibration
      Controller.LockOn.aim({200, 0})                 # hold it 200 px right of the middle (mosaics)
      Controller.LockOn.release()

  It reads the camera's frames as they're analysed (`Controller.ScopeCamera`:
  each frame's `bright` target, or its brightest star), or anything that calls
  `observe/1`.

  **States** (`status/0`, broadcast on `"lock_on"`, and on every page through
  `Controller.Modes` while it isn't off):

    * `:calibrating`: two frames with the motors still for the drift, then a
      short nudge of each axis;
    * `:holding`: both motors set again on every frame;
    * `:coasting`: the target isn't seen (a cloud, the edge of a door): the
      motors keep cancelling the drift so it's still there when it comes back;
      after `coast_ms` (5 min) the motors stop (`:lost`), still watching;
    * `:waiting`: no fresh pictures: motors stopped until pictures return
      (a picture gap is not a lost target; it never ends the lock);
    * `:stepped_aside`: a hand on the pad: no commands until it lets go;
    * `:resuming`: it was holding when the box went down (a firmware update, a
      crash, a power cut) or the mount's link dropped: waiting for the mount
      and the clock, then catching up and holding again (see below);
    * `:off`: released, STOP, or calibration failed; `why` says which.

  **It picks up where it left off.** While it holds, a heartbeat is saved
  every ten seconds (`Controller.Settings`, `"lock_on_resume"`): the mount,
  the target, where both axes were and when, and the two rates that keep the
  sky still. When the process starts and finds one, it waits for the mount
  to answer, then moves each axis to where it would be by now had it never
  stopped (where it was + rate x the time since), and holds again on the
  saved calibration. It does not wait for network time: a box that has just
  booted counts from its own saved clock, which is only seconds behind after
  a restart, close enough to land the target in the picture. When network
  time arrives and the clock turns out to have been behind, it moves by the
  difference, unless the target is already in hand. A mount that kept
  running through the outage is already there, so it barely moves; one that
  stopped is caught up; one that lost power too is moved by rate x time from
  where it stands. It gives up, in words, rather than guess: down longer than
  `revive_max_s` (20 min), a catch-up larger than `revive_max_deg` (10), a
  clock that never gets set, three pick-ups in ten minutes. Releasing it or
  pressing STOP forgets the heartbeat: only a lock that was cut off resumes.

  The rules come from the night of 2026-10-02, when a hand-built version of
  this held the Moon on an EQ6-R pointed nowhere near the pole: name every
  stop's real cause; never let a missing picture look like a missing target;
  never keep the motors running on old pictures; a STOP anywhere ends it.
  """
  use GenServer
  require Logger

  alias Controller.LockOn.Law
  alias Controller.{Clock, Recovery, Settings}

  @topic "lock_on"
  @resume "lock_on_resume"
  # degrees per second at 1x sidereal
  @sidereal 360 / 86_164.0905

  @defaults [
    tick_ms: 250,
    stale_ms: 45_000,
    coast_ms: 300_000,
    nudge_rate: 4.0,
    nudge_ms: 5_000,
    # after a nudge, the mount's last steps and its position report need a moment before the measuring frame
    settle_ms: 1_500,
    drift_min_ms: 5_000,
    k: 1 / 40,
    ki: 1 / 3000,
    max_rate: 2.0,
    target: :bright,
    # which camera's frames to steer by: :scope (the telescope camera) or :still (the stills camera)
    source: :scope,
    follow_camera: true,
    # picking up after the box or the mount's link went down (see the moduledoc)
    revive: true,
    beat_ms: 10_000,
    revive_max_s: 1_200,
    revive_max_deg: 10.0,
    revive_wait_ms: 180_000,
    # how long to wait for network time before going by the box's own clock
    revive_clock_ms: 5_000,
    # how long the catch-up move itself takes, about: the sky moves on meanwhile
    revive_lead_s: 4.0
  ]

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Lock on with mount `id`. Options: `saved: true` to hold at once on this
  mount's last calibration (when the mount hasn't been moved since);
  `target: :bright | :star`; and any of the timing and gain knobs (`k:`,
  `ki:`, `max_rate:`, `nudge_rate:`, `nudge_ms:`, `coast_ms:`, `stale_ms:`).
  """
  def start(id, opts \\ []), do: GenServer.call(__MODULE__, {:start, id, opts})

  @doc "Let go: both axes stop."
  def release(why \\ "released"), do: GenServer.call(__MODULE__, {:release, why})

  @doc "Hold the target `{dx, dy}` px from the middle of the picture (to walk a mosaic)."
  def aim(offset), do: GenServer.call(__MODULE__, {:aim, offset})

  @doc """
  A frame record as the cameras make them (`at`, `w`, `h`, `bright`, `marks`,
  and `source: :scope | :still`): used when it comes from the camera Lock On
  was started with.
  """
  def frame(record), do: GenServer.cast(__MODULE__, {:frame, record})

  @doc """
  One analysed picture: `%{at: monotonic_ms, w, h, target: %{x, y} | nil}`
  (or `stars: [%{x, y}]` for `target: :star`).
  """
  def observe(obs), do: GenServer.cast(__MODULE__, {:observe, obs})

  @doc "Where it stands (read without asking the process: pages draw it on every render)."
  def status, do: :persistent_term.get({__MODULE__, :status}, %{state: :off, why: "not running"})

  def subscribe, do: Telescope.subscribe(@topic)

  @doc "This mount's saved calibration, or nil."
  def calibration(id), do: Settings.get("lock_on", %{})[id]

  # -- the process -------------------------------------------------------------------------------

  @impl true
  def init(opts) do
    opts =
      Keyword.merge(
        @defaults,
        Keyword.merge(Application.get_env(:controller, :lock_on, []), opts)
      )

    if opts[:follow_camera], do: safe(fn -> Controller.ScopeCamera.subscribe() end)
    :timer.send_interval(opts[:tick_ms], :tick)
    Recovery.boot()
    if opts[:revive], do: send(self(), :revive)
    {:ok, idle(opts, "not started")}
  end

  defp idle(opts, why) do
    %{
      opts: opts,
      state: :off,
      why: why,
      id: nil,
      estop0: nil,
      cal: nil,
      step: nil,
      rates: {0.0, 0.0},
      integral: {0.0, 0.0},
      offset: {0.0, 0.0},
      last: nil,
      # when the last fresh picture arrived, whatever it showed: staleness is about pictures, not targets
      heard: nil,
      last_seq: nil,
      error: nil,
      since: now(),
      lost_since: nil,
      resume: nil,
      nudge: nil,
      seen: 0,
      # the heartbeat last saved, and (while :resuming) what is being picked up
      beat_at: nil,
      revive: nil,
      # after a pick-up on the box's own clock: when it was, to correct by once network time arrives
      clock_fix: nil
    }
  end

  @impl true
  def handle_call(:status, _from, s), do: {:reply, public(s), s}

  def handle_call({:start, id, opts}, _from, s) do
    opts = Keyword.merge(s.opts, opts)

    case safe(fn -> Mount.snapshot(id) end) do
      %{connected: true} = snap ->
        s = %{idle(opts, nil) | id: id, estop0: snap[:estop_at]}
        safe(fn -> Mount.track(id, :off) end)

        forget()

        s =
          case opts[:saved] && load(id) do
            # from the first tick the motors follow the sky: the target doesn't slide while the first picture comes
            %{} = cal -> enter(%{s | cal: cal, rates: Law.cancel(cal.minv, cal.drift)}, :holding, "on the calibration from #{cal.at}")
            _ -> enter(%{s | step: :drift}, :calibrating, "measuring the drift: motors still")
          end

        {:reply, :ok, s}

      _ ->
        {:reply, {:error, "mount #{id} isn't answering"}, s}
    end
  end

  def handle_call({:release, why}, _from, s), do: {:reply, :ok, off(s, why)}

  def handle_call({:aim, {dx, dy}}, _from, s),
    do: {:reply, :ok, announce(%{s | offset: {dx / 1, dy / 1}, integral: {0.0, 0.0}})}

  @impl true
  def handle_cast({:observe, obs}, s), do: {:noreply, observe(s, obs)}

  def handle_cast({:frame, f}, %{state: st} = s) when st != :off do
    if Map.get(f, :source, :scope) == s.opts[:source] and f[:ok] != false,
      do: {:noreply, observe(s, from_frame(f, s.opts[:target], s))},
      else: {:noreply, s}
  end

  def handle_cast({:frame, _}, s), do: {:noreply, s}

  @impl true
  def handle_info(:tick, s), do: {:noreply, tick(s)}

  # at start: was a lock cut off? (only when nothing has been started since)
  def handle_info(:revive, %{state: :off} = s) do
    case heartbeat() do
      %{mount: id} = r ->
        Recovery.note(:lock_found, %{mount: id, heartbeat: DateTime.to_iso8601(r.at)})
        {:noreply, enter(%{s | id: id, revive: Map.put(r, :since, now())}, :resuming, "was holding when it went down: waiting for the mount")}
      _ -> {:noreply, s}
    end
  end

  def handle_info(:revive, s), do: {:noreply, s}

  # frames as the telescope camera analyses them; never another machine's simulated camera,
  # whose stars are not this telescope's (the motors would be steered by a sky that isn't there)
  def handle_info({:scope_camera, %{frames: [f | _]} = cam}, %{state: st} = s) when st != :off do
    if s.opts[:source] == :scope and Controller.ScopeCamera.listed?(cam), do: scope_frame(f, s), else: {:noreply, s}
  end

  def handle_info(_, s), do: {:noreply, s}

  defp scope_frame(f, s) do
    if f[:seq] != s.last_seq and f[:ok] != false do
      {:noreply, observe(%{s | last_seq: f[:seq]}, from_frame(f, s.opts[:target], s))}
    else
      {:noreply, s}
    end
  end

  # -- what the camera saw -----------------------------------------------------------------------

  defp from_frame(f, :bright, _s),
    do: %{
      at: mono(f[:at]),
      w: f[:w],
      h: f[:h],
      target: f[:bright] && Map.take(f.bright, [:x, :y, :edge])
    }

  defp from_frame(f, :star, s) do
    stars = get_in(f, [:marks, :stars]) || []

    # keep to the same star: the one nearest where it was, else the brightest
    target =
      case {s.last, stars} do
        {_, []} ->
          nil

        {%{p: {px, py}}, _} ->
          Enum.min_by(stars, fn st -> (st.x - px) ** 2 + (st.y - py) ** 2 end)

        _ ->
          hd(stars)
      end

    %{at: mono(f[:at]), w: f[:w], h: f[:h], target: target && %{x: target.x / 1, y: target.y / 1}}
  end

  defp mono(%DateTime{} = at), do: now() - DateTime.diff(DateTime.utc_now(), at, :millisecond)
  defp mono(_), do: now()

  defp observe(%{state: :off} = s, _obs), do: s
  # still catching up: there is nothing to steer by until the calibration is back in force
  defp observe(%{state: :resuming} = s, _obs), do: s

  defp observe(s, obs) do
    fresh = now() - obs.at < s.opts[:stale_ms] and (s.last == nil or obs.at > s.last.at)

    s = if fresh, do: %{s | heard: obs.at}, else: s

    cond do
      not fresh ->
        s

      s.state == :waiting ->
        # pictures again: pick up where it was (a calibration in progress starts over)
        s = if s.resume == :calibrating, do: %{s | step: :drift, nudge: nil}, else: s
        observe(enter(s, s.resume, "pictures again"), obs)

      true ->
        p = obs[:target] && {obs.target.x / 1, obs.target.y / 1}

        seen(s, %{
          at: obs.at,
          p: p,
          w: obs[:w] || 960,
          h: obs[:h] || 540,
          edge: obs[:target][:edge]
        })
    end
  end

  # -- calibrating ---------------------------------------------------------------------------------

  defp seen(%{state: :calibrating, step: :drift} = s, %{p: nil} = o), do: %{s | last: o}

  defp seen(%{state: :calibrating, step: :drift} = s, o) do
    min_ms = s.opts[:drift_min_ms]

    case s.last do
      %{p: {_, _} = p0, at: t0} when o.at - t0 >= min_ms ->
        drift = vdiv(vsub(o.p, p0), (o.at - t0) / 1000)
        Logger.info("lock on: drift #{inspect(round2(drift))} px/s")
        nudge(%{s | cal: %{drift: drift}, last: o}, :ra)

      %{p: {_, _}} ->
        s

      _ ->
        %{s | last: o}
    end
  end

  defp seen(%{state: :calibrating, step: {:measure, axis}} = s, o) do
    %{from: from, until: until} = s.nudge

    cond do
      o.at <= until + s.opts[:settle_ms] ->
        s

      o.p == nil ->
        enter(
          %{s | step: :drift, last: nil, nudge: nil},
          :calibrating,
          "lost the target while calibrating: starting over"
        )

      true ->
        col =
          Law.column(
            vsub(o.p, from.p),
            s.cal.drift,
            (o.at - from.at) / 1000,
            s.opts[:nudge_rate],
            s.opts[:nudge_ms] / 1000
          )

        cal = Map.put(s.cal, axis, col)
        Logger.info("lock on: #{axis} moves the picture #{inspect(round2(col))} px/s per 1×")
        s = %{s | cal: cal, last: o, nudge: nil}
        if axis == :ra, do: nudge(s, :dec), else: calibrated(s, o)
    end
  end

  defp seen(%{state: :calibrating} = s, o), do: %{s | last: o}

  # -- holding, coasting, lost ---------------------------------------------------------------------

  defp seen(s, %{p: nil} = o) do
    s = %{s | last: o}

    case s.state do
      :holding ->
        enter(
          %{s | rates: Law.cancel(s.cal.minv, s.cal.drift), lost_since: now()},
          :coasting,
          "target not seen: holding the sky still until it's back"
        )

      _ ->
        s
    end
  end

  defp seen(s, o) do
    {cx, cy} = {o.w / 2, o.h / 2}
    {ox, oy} = s.offset
    {x, y} = o.p
    e = {x - cx - ox, y - cy - oy}
    dt = if s.last, do: max(o.at - s.last.at, 0) / 1000, else: 0.0
    integral = Law.integrate(s.integral, e, dt)
    rates = Law.rates(s.cal, e, integral, Keyword.take(s.opts, [:k, :ki, :max_rate]))
    s = target_back(%{s | last: o, integral: integral, rates: rates, error: e, seen: s.seen + 1}, e)

    if s.state in [:coasting, :lost],
      do: enter(s, :holding, "target back in view"),
      else: announce(s)
  end

  # the first sight of the target after a pick-up: how long the whole thing took, for the record
  defp target_back(%{revive: %{waiting_for_target: true, since: since}} = s, {ex, ey}) do
    Recovery.note(:lock_target_seen, %{mount: s.id, since_found_ms: now() - since, error_px: [Float.round(ex / 1, 1), Float.round(ey / 1, 1)]})
    %{s | revive: nil}
  end

  defp target_back(s, _), do: s

  defp calibrated(s, o) do
    m = Law.matrix(s.cal.ra, s.cal.dec)

    case Law.inverse(m) do
      :singular ->
        off(s, "calibration failed: the two motors move the picture the same way")

      minv ->
        cal = %{
          drift: s.cal.drift,
          m: m,
          minv: minv,
          w: o.w,
          h: o.h,
          at: DateTime.utc_now() |> DateTime.truncate(:second)
        }

        save(s.id, cal)

        safe(fn ->
          Telescope.Events.emit(:lock_on, :calibrated, %{
            mount: s.id,
            drift: round2(cal.drift),
            m: round2(m)
          })
        end)

        enter(
          %{s | cal: cal, step: nil, rates: Law.cancel(minv, cal.drift)},
          :holding,
          "calibrated: holding"
        )
    end
  end

  defp nudge(s, axis) do
    enter(
      %{
        s
        | step: {:measure, axis},
          nudge: %{axis: axis, from: s.last, until: now() + s.opts[:nudge_ms]}
      },
      :calibrating,
      "nudging #{axis_words(axis)} to see how it moves the picture"
    )
  end

  # -- every tick: STOP, the pad, stale pictures, and the motors -----------------------------------

  defp tick(%{state: :off} = s), do: s
  defp tick(%{state: :resuming} = s), do: revive(s)

  defp tick(s) do
    snap = safe(fn -> Mount.snapshot(s.id) end)

    cond do
      not match?(%{connected: true}, snap) ->
        # a lock that was holding picks up when the link is back; anything else ends
        case s.state in [:holding, :coasting] && heartbeat() do
          %{mount: id} = r when id == s.id ->
            enter(%{idle(s.opts, nil) | id: s.id, revive: Map.put(r, :since, now())}, :resuming, "the mount stopped answering: picking up when it's back")

          _ ->
            off(s, "the mount stopped answering")
        end

      snap[:estop_at] != s.estop0 ->
        off(s, "STOP was pressed")

      pad_held?() ->
        if s.state == :stepped_aside,
          do: s,
          else: enter(%{s | resume: s.state}, :stepped_aside, "a hand on the pad: stepping aside")

      s.state == :stepped_aside ->
        enter(s, s.resume || :holding, "pad let go")

      s.state in [:holding, :coasting, :calibrating] and s.heard != nil and
          now() - s.heard > s.opts[:stale_ms] ->
        stop_motors(s)

        enter(
          %{s | resume: s.state},
          :waiting,
          "no new pictures: motors stopped until they come back"
        )

      s.state == :coasting and now() - (s.lost_since || now()) > s.opts[:coast_ms] ->
        stop_motors(s)

        enter(
          s,
          :lost,
          "target gone for #{div(s.opts[:coast_ms], 60_000)} min: motors stopped, still watching"
        )

      true ->
        s |> clock_fix(snap) |> beat(snap) |> drive()
    end
  end

  # -- the heartbeat, and picking up from it -------------------------------------------------------

  # every beat_ms while holding: enough to carry on from, should everything stop right now
  defp beat(%{state: st, cal: %{minv: minv, drift: drift}} = s, %{axes: %{ra: ra, dec: dec}}) when st in [:holding, :coasting] do
    if s.beat_at == nil or now() - s.beat_at >= s.opts[:beat_ms] do
      {rra, rdec} = Law.cancel(minv, drift)
      {ox, oy} = s.offset
      old = Settings.get(@resume)

      Settings.put(@resume, %{
        "mount" => s.id,
        "at" => DateTime.utc_now() |> DateTime.to_iso8601(),
        "ra_deg" => ra.degrees / 1,
        "dec_deg" => dec.degrees / 1,
        "ra_steps" => ra[:steps],
        "dec_steps" => dec[:steps],
        "rates" => [rra, rdec],
        "offset" => [ox, oy],
        "source" => to_string(s.opts[:source]),
        "target" => to_string(s.opts[:target]),
        "revives" => (is_map(old) && old["revives"]) || []
      })

      %{s | beat_at: now()}
    else
      s
    end
  end

  defp beat(s, _), do: s

  defp forget, do: if(Settings.get(@resume) != nil, do: Settings.put(@resume, nil))

  defp heartbeat do
    with %{"mount" => id, "at" => at, "ra_deg" => ra, "dec_deg" => dec, "rates" => [rra, rdec]} = r when is_binary(id) <- Settings.get(@resume),
         {:ok, at, _} <- DateTime.from_iso8601(at) do
      [ox, oy] = r["offset"] || [0.0, 0.0]

      %{
        mount: id,
        at: at,
        axes: {ra / 1, dec / 1},
        steps: {r["ra_steps"], r["dec_steps"]},
        rates: {rra / 1, rdec / 1},
        offset: {ox / 1, oy / 1},
        source: if(r["source"] == "still", do: :still, else: :scope),
        target: if(r["target"] == "star", do: :star, else: :bright),
        revives: for(t <- r["revives"] || [], {:ok, d, _} <- [DateTime.from_iso8601(t)], do: d)
      }
    else
      _ -> nil
    end
  end

  # Picking up, a tick at a time: wait for the mount and the clock, move each axis to where it would
  # be by now, wait for the move, hold. Every way out says why.
  defp revive(%{revive: r} = s) do
    snap = safe(fn -> Mount.snapshot(r.mount) end)
    connected? = match?(%{connected: true}, snap)
    waited = now() - r.since
    # STOP while it waits or catches up ends it, as everywhere
    r = if connected? and not Map.has_key?(r, :estop0), do: Map.merge(r, %{estop0: snap[:estop_at], connected_at: now()}), else: r
    s = %{s | revive: r}
    down = DateTime.diff(DateTime.utc_now(), r.at, :millisecond) / 1000

    cond do
      connected? and snap[:estop_at] != r.estop0 ->
        give_up(s, "STOP was pressed: not picking up")

      Map.get(r, :moving) ->
        if connected? and not busy?(snap), do: revived(s), else: s

      not connected? ->
        if waited > s.opts[:revive_wait_ms], do: give_up(s, "the mount didn't come back in #{div(s.opts[:revive_wait_ms], 60_000)} min: not picking up"), else: s

      Clock.synced?() ->
        catch_up(s, snap, :network)

      # no network time yet: after a short wait, go by the box's own clock when what it says is believable
      now() - r.connected_at >= s.opts[:revive_clock_ms] and down >= 0 and down <= s.opts[:revive_max_s] ->
        catch_up(s, snap, :own)

      waited > s.opts[:revive_wait_ms] ->
        give_up(s, "the clock was never set and its own time can't be right (#{words_for(down)} since the heartbeat): not picking up")

      true ->
        s
    end
  end

  defp catch_up(%{revive: r} = s, snap, clock) do
    # where each axis would be a few seconds from now (the move takes that long) had it never stopped
    down = DateTime.diff(DateTime.utc_now(), r.at, :millisecond) / 1000
    lead = down + s.opts[:revive_lead_s]
    {ra0, dec0} = r.axes
    {rra, rdec} = r.rates
    {ra, dec} = {snap.axes.ra.degrees, snap.axes.dec.degrees}
    recent = Enum.count(r.revives, &(DateTime.diff(DateTime.utc_now(), &1) < 600))

    # a mount that lost power too counts from its power-on zero again, but stands where it stopped
    fresh? = fresh?(snap) and r.steps != {snap.axes.ra[:steps], snap.axes.dec[:steps]}
    {dra, ddec} = if fresh?, do: {rra * @sidereal * lead, rdec * @sidereal * lead}, else: {ra0 + rra * @sidereal * lead - ra, dec0 + rdec * @sidereal * lead - dec}

    cond do
      down < 0 or down > s.opts[:revive_max_s] ->
        give_up(s, "it was down #{words_for(down)}: too long to pick up where it left off")

      recent >= 3 ->
        give_up(s, "picked up three times in ten minutes: staying off")

      abs(dra) > s.opts[:revive_max_deg] or abs(ddec) > s.opts[:revive_max_deg] ->
        give_up(s, "catching up would take a #{Float.round(max(abs(dra), abs(ddec)), 1)}° move: not picking up")

      load(r.mount) == nil ->
        give_up(s, "no saved calibration for #{r.mount}: not picking up")

      true ->
        safe(fn -> Mount.track(r.mount, :off) end)
        if abs(ddec) > 0.0005, do: safe(fn -> Mount.goto_relative(r.mount, :dec, ddec) end)
        if abs(dra) > 0.0005, do: safe(fn -> Mount.goto_relative(r.mount, :ra, dra) end)
        Logger.info("lock on: picking up after #{words_for(down)} (#{clock} clock): RA #{signed(dra)}°, Dec #{signed(ddec)}°")
        Recovery.note(:lock_catch_up, %{mount: r.mount, down_s: Float.round(down, 1), clock: clock, ra_deg: dra, dec_deg: ddec, waited_ms: now() - r.since, mount_fresh: fresh?})
        fix = if clock == :own, do: %{utc: DateTime.utc_now(), mono: now()}
        r = Map.merge(r, %{moving: now(), down: down, moved: {dra, ddec}, clock: clock, fix: fix})
        enter(%{s | revive: r, estop0: snap[:estop_at]}, :resuming, "back after #{words_for(down)}: catching up (RA #{signed(dra)}°, Dec #{signed(ddec)}°)")
    end
  end

  defp revived(%{revive: r} = s) do
    cal = load(r.mount)
    {dra, ddec} = r.moved
    opts = Keyword.merge(s.opts, source: r.source, target: r.target)
    remember()
    safe(fn -> Telescope.Events.emit(:lock_on, :resumed, %{mount: r.mount, down_s: round(r.down), ra_deg: dra, dec_deg: ddec}) end)
    Recovery.note(:lock_holding, %{mount: r.mount, since_found_ms: now() - r.since})
    by = if r[:clock] == :own, do: " (by the box's own clock)", else: ""

    enter(
      %{idle(opts, nil) | id: r.mount, estop0: s.estop0, cal: cal, offset: r.offset, rates: Law.cancel(cal.minv, cal.drift), clock_fix: r[:fix], revive: %{since: r.since, waiting_for_target: true}},
      :holding,
      "back after #{words_for(r.down)}#{by}: caught up RA #{signed(dra)}°, Dec #{signed(ddec)}°, holding again"
    )
  end

  # Network time has arrived after a pick-up on the box's own clock. If the clock was behind, the
  # catch-up fell short by rate x that much: make it up, unless the target is already in the picture
  # (then the pictures are steering, and a second move would throw it out).
  defp clock_fix(%{clock_fix: %{utc: utc0, mono: mono0}, state: st, cal: %{minv: minv, drift: drift}} = s, snap) when st in [:holding, :coasting] do
    if Clock.synced?() do
      behind = (DateTime.diff(DateTime.utc_now(), utc0, :millisecond) - (now() - mono0)) / 1000
      {rra, rdec} = Law.cancel(minv, drift)
      {dra, ddec} = {rra * @sidereal * behind, rdec * @sidereal * behind}
      seen? = match?(%{p: {_, _}}, s.last)
      s = %{s | clock_fix: nil}

      cond do
        abs(behind) < 2 or seen? ->
          Recovery.note(:clock_set, %{behind_s: Float.round(behind, 1), moved: false, target_in_hand: seen?})
          s

        abs(dra) > s.opts[:revive_max_deg] or abs(ddec) > s.opts[:revive_max_deg] or abs(behind) > s.opts[:revive_max_s] ->
          Recovery.note(:clock_set, %{behind_s: Float.round(behind, 1), moved: false, why: "too far"})
          give_up(%{s | revive: %{mount: s.id}}, "the clock was #{words_for(abs(behind))} off: too far to make up, not holding")

        true ->
          stop_motors(s)
          if abs(ddec) > 0.0005, do: safe(fn -> Mount.goto_relative(s.id, :dec, ddec) end)
          if abs(dra) > 0.0005, do: safe(fn -> Mount.goto_relative(s.id, :ra, dra) end)
          Recovery.note(:clock_set, %{behind_s: Float.round(behind, 1), moved: true, ra_deg: dra, dec_deg: ddec})
          {ox, oy} = s.offset
          r = %{mount: s.id, since: now(), moving: now(), down: behind, moved: {dra, ddec}, offset: {ox, oy}, source: s.opts[:source], target: s.opts[:target], estop0: snap[:estop_at], clock: :network, fix: nil}
          enter(%{s | revive: r}, :resuming, "the clock was #{words_for(behind)} behind: making that up (RA #{signed(dra)}°, Dec #{signed(ddec)}°)")
      end
    else
      s
    end
  end

  defp clock_fix(s, _snap), do: s

  # this pick-up goes on the record, so three in ten minutes can be told apart from one
  defp remember do
    case Settings.get(@resume) do
      %{} = saved -> Settings.put(@resume, Map.put(saved, "revives", Enum.take([DateTime.utc_now() |> DateTime.to_iso8601() | saved["revives"] || []], 5)))
      _ -> :ok
    end
  end

  defp give_up(s, why) do
    Recovery.note(:lock_gave_up, %{mount: s.revive && s.revive[:mount], why: why})
    forget()
    off(%{s | id: (s.revive && s.revive[:mount]) || s.id}, why)
  end

  defp busy?(%{axes: axes}), do: Enum.any?(axes, fn {_, a} -> a[:goto_pending] == true or a[:running] == true end)
  defp busy?(_), do: true

  # both counters exactly at the board's power-on value: the mount has just been switched on
  defp fresh?(%{axes: %{ra: %{steps: 0x800000}, dec: %{steps: 0x800000}}}), do: true
  defp fresh?(_), do: false

  defp words_for(seconds) when seconds < 120, do: "#{round(seconds)} s"
  defp words_for(seconds), do: "#{Float.round(seconds / 60, 1)} min"
  defp signed(v), do: :erlang.float_to_binary(v / 1, decimals: 3) |> then(&if(v >= 0, do: "+" <> &1, else: &1))

  # the nudge runs exactly its time: stopped outright at the end, not left to lapse (a held slew
  # runs on up to 0.9 s, and the calibration would count motion it didn't time)
  defp drive(%{state: :calibrating, nudge: %{axis: axis, until: until} = n} = s) do
    cond do
      now() < until ->
        slew(s.id, axis, s.opts[:nudge_rate])
        s

      not Map.get(n, :stopped, false) ->
        safe(fn -> Mount.stop(s.id, axis, instant: true) end)
        %{s | nudge: Map.put(n, :stopped, true)}

      true ->
        s
    end
  end

  defp drive(%{state: st, rates: {ra, dec}} = s) when st in [:holding, :coasting] do
    slew(s.id, :ra, ra)
    slew(s.id, :dec, dec)
    s
  end

  defp drive(s), do: s

  # a held slew lapses by itself within a second unless refreshed: an axis meant to be still is left alone
  defp slew(id, axis, rate) when abs(rate) > 0.005,
    do: safe(fn -> Mount.slew(id, axis, rate, hold: true, quiet: true) end)

  defp slew(_, _, _), do: :ok

  defp stop_motors(%{id: id}) when is_binary(id) do
    safe(fn -> Mount.stop(id, :ra, instant: true) end)
    safe(fn -> Mount.stop(id, :dec, instant: true) end)
  end

  defp stop_motors(_), do: :ok

  defp pad_held? do
    match?(%{held: [_ | _]}, safe(fn -> Input.Mapper.status() end))
  end

  defp off(s, why) do
    stop_motors(s)
    # ended on purpose or for a stated reason: nothing to pick up later
    forget()

    if s.state != :off,
      do: safe(fn -> Telescope.Events.emit(:lock_on, :off, %{mount: s.id, why: why}) end)

    announce(%{idle(s.opts, why) | id: s.id})
  end

  defp enter(s, state, why) do
    if state != s.state,
      do: safe(fn -> Telescope.Events.emit(:lock_on, state, %{mount: s.id, why: why}) end)

    announce(%{s | state: state, why: why, since: if(state != s.state, do: now(), else: s.since)})
  end

  defp announce(s) do
    p = public(s)

    if :persistent_term.get({__MODULE__, :status}, nil) != p do
      :persistent_term.put({__MODULE__, :status}, p)
      safe(fn -> Telescope.broadcast(@topic, {:lock_on, p}) end)
    end

    s
  end

  defp public(s) do
    %{
      state: s.state,
      why: s.why,
      mount: s.id,
      step: s.step,
      error_px: s.error && round2(s.error),
      rates: round2(s.rates),
      offset: s.offset,
      frames: s.seen,
      calibration:
        s.cal && Map.get(s.cal, :m) &&
          %{drift: round2(s.cal.drift), m: round2(s.cal.m), at: s.cal[:at]},
      target: s.opts[:target]
    }
  end

  # -- the saved calibration -----------------------------------------------------------------------

  defp save(id, cal) do
    {{a, b}, {c, d}} = cal.m
    {dx, dy} = cal.drift

    entry = %{
      "m" => [[a, b], [c, d]],
      "drift" => [dx, dy],
      "w" => cal.w,
      "h" => cal.h,
      "at" => DateTime.to_iso8601(cal.at)
    }

    Settings.put("lock_on", Map.put(Settings.get("lock_on", %{}) || %{}, id, entry))
  end

  defp load(id) do
    with %{"m" => [[a, b], [c, d]], "drift" => [dx, dy]} = e <- calibration(id),
         m = {{a, b}, {c, d}},
         {{_, _}, {_, _}} = minv <- Law.inverse(m) do
      %{m: m, minv: minv, drift: {dx, dy}, w: e["w"], h: e["h"], at: e["at"]}
    else
      _ -> nil
    end
  end

  # -- small things --------------------------------------------------------------------------------

  defp now, do: System.monotonic_time(:millisecond)
  defp vsub({a, b}, {c, d}), do: {a - c, b - d}
  defp vdiv({a, b}, k), do: {a / k, b / k}
  defp axis_words(:ra), do: "RA"
  defp axis_words(:dec), do: "Dec"

  defp round2({a, b}) when is_number(a), do: {Float.round(a / 1, 2), Float.round(b / 1, 2)}
  defp round2({{a, b}, {c, d}}), do: {round2({a, b}), round2({c, d})}
  defp round2(other), do: other

  defp safe(fun) do
    fun.()
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end
end

defmodule Controller.LockOn.Supervisor do
  @moduledoc """
  Lock On's own branch: restarted a few times if it crashes, then left down
  (its parent starts it `:temporary`), so a fault in steering by the camera
  can never take the app, or the mount, with it. A restart begins released:
  it never resumes moving the mount by itself.
  """
  use Supervisor

  def start_link(_), do: Supervisor.start_link(__MODULE__, nil, name: __MODULE__)

  @impl true
  def init(_),
    do:
      Supervisor.init([Controller.LockOn],
        strategy: :one_for_one,
        max_restarts: 5,
        max_seconds: 60
      )
end
