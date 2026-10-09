defmodule Controller.Sky.Pointing do
  @moduledoc """
  Sky ↔ mount axes, in one place.

  Two models live behind the same functions:

  * the **first-order** model — homed at the pole with the counterweight down,
    axis signs from config, a persisted one-star sync offset. Good when the
    mount was polar-aligned.
  * the **lined-up** model (`Controller.Sky.Model`, fitted by
    `Controller.Sky.Lineup`) — the polar axis wherever it really is, plus
    encoder offsets, from a few stars centred by eye. Used automatically
    whenever a star alignment exists for the mount.

  A German equatorial reaches every point two ways. Zeroed, the pose that keeps
  the RA axis within ±90° of home keeps the counterweight below. Never zeroed,
  home is unknown and the lined-up model says where the counterweight hangs
  (`counterweight/2`): Go To stays on this side of the pier while it hangs
  below level, and flips to the other side (asking first) when it wouldn't.

  Which side of the mount the counterweight is on, the model cannot see: both
  sides look at the same sky. Until someone at the mount says
  (`Lineup.set_counterweight/3`), nothing moves by it (`side_guessed?/2`).
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Model}

  # EQ6-R goto: 800× sidereal, plus ramps
  @goto_deg_s 360.0 / 86_164.0905 * 800
  @goto_ramp_s 3.0

  @type ctx :: %{
          now: DateTime.t(),
          site: map,
          pointing: map,
          offset: map,
          model: map | nil,
          mount: String.t() | nil
        }

  @doc """
  Model context from config + persisted settings. Pass the mount id to pick up
  its star alignment; without one, a star alignment is used only if exactly one mount has one.
  """
  def context(now \\ DateTime.utc_now(), mount_id \\ nil) do
    %{
      now: now,
      site: site(),
      pointing: pointing(),
      offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0}),
      model: model_for(mount_id),
      mount: mount_id
    }
  end

  # No id: only when exactly one mount is connected does its alignment apply.
  # (Never "whichever mount has one" — a simulator's alignment must not steer
  # the real mount.)
  defp model_for(nil) do
    case safe(fn -> Mount.list() end) do
      [%{id: only}] -> Lineup.model(only)
      _ -> nil
    end
  end

  defp model_for(id), do: Lineup.model(id)

  def site do
    base = Application.get_env(:controller, :site, %{lat: 0.0, lon: 0.0, name: "nowhere"})

    case Settings.get("site") do
      %{"lat" => lat, "lon" => lon} when is_number(lat) and is_number(lon) ->
        %{base | lat: lat / 1, lon: lon / 1}

      _ ->
        base
    end
  end

  @doc "Whether a site has been given at all (typed, from a phone, or configured), or 0°, 0° is a stand-in."
  def site_set? do
    match?(
      %{"lat" => lat, "lon" => lon} when is_number(lat) and is_number(lon),
      Settings.get("site")
    ) or
      Application.get_env(:controller, :site) != nil
  end

  def pointing do
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    case Settings.get("pointing") do
      %{"ha_sign" => h, "dec_sign" => d} when h in [-1, 1] and d in [-1, 1] ->
        %{ha_sign: h, dec_sign: d}

      _ ->
        base
    end
  end

  @doc "Is a lined-up model in force for this context?"
  def lined_up?(%{model: m}), do: m != nil
  def lined_up?(_), do: false

  @doc "First-order axis targets (degrees from home) for an object, without the sync offset."
  def raw_axes_for(obj, %{now: now, site: site, pointing: p}) do
    lst = Astro.lst_deg(now, site.lon)
    ha = Astro.hour_angle(lst, obj.ra_deg)
    normal = {ha / p.ha_sign, (90 - obj.dec_deg) / p.dec_sign}
    flipped = {Astro.norm180(ha + 180) / p.ha_sign, -(90 - obj.dec_deg) / p.dec_sign}

    cond do
      abs(elem(normal, 0)) <= 90 -> normal
      abs(elem(flipped, 0)) <= 90 -> flipped
      abs(elem(normal, 0)) <= abs(elem(flipped, 0)) -> normal
      true -> flipped
    end
  end

  @doc """
  Axis targets for an object. With a star alignment, through the fitted geometry
  (`near:` the current encoders keeps the same side of the pier when both
  solutions are legal); otherwise first-order plus the sync offset.
  """
  def axes_for(obj, ctx, opts \\ [])

  def axes_for(obj, %{model: m, pointing: p, site: site, now: now}, opts) when is_map(m) do
    lst = Astro.lst_deg(now, site.lon)
    Model.encoders_radec(m, signs_of(m, p), obj.ra_deg, obj.dec_deg, site.lat, lst, opts[:near])
  end

  def axes_for(obj, %{offset: off} = ctx, _opts) do
    {ra, dec} = raw_axes_for(obj, ctx)
    {ra + off["ra"], dec + off["dec"]}
  end

  # Never zeroed there are no soft limits, so the counterweight is the guard.
  # A little above level is normal while tracking toward the meridian.
  @meridian_margin 3.0
  # where an EQ6-R's tube can reach the tripod legs, however carefully watched
  @meridian_hard 20.0

  @doc "How far above level the counterweight may go before the hold stops, in degrees of RA turn."
  def meridian_hard, do: @meridian_hard

  @doc """
  How high the counterweight sits with the RA axis at `ra_axis`, in degrees of
  RA turn above level (negative: below). Only a lined-up model knows; without
  one, -90 (hanging down: the zeroed rules and the soft limits apply).
  """
  def counterweight(%{model: m, pointing: p}, ra_axis) when is_map(m),
    do: Model.counterweight(m, signs_of(m, p), ra_axis)

  def counterweight(_ctx, _ra_axis), do: -90.0

  @doc """
  Has a hold on a never-zeroed mount carried the counterweight past its limit?
  `cw` is the counterweight now (`counterweight/2`). A hold only runs once the
  counterweight's side is told or home is set (`side_guessed?/2`), so the
  height is known to be the right way up.
  """
  def hold_limit?(cw), do: cw > @meridian_hard

  @doc """
  Is which side of the pier the counterweight is on only a guess, on a mount
  whose home was never set? Then nothing moves the mount by the model's idea
  of the pier side: Go To, the flip's legs and the hold all refuse (#113).

  A telescope on either side of the mount sees the same stars, so an
  alignment by stars, by photo or by the camera only guesses the side
  (`Model.cw_down/3`). On 3 October and again on 8 October the guess was
  upside down: a Go To drove the tube to the pose with the counterweight bar
  64° above level and the camera near a tripod leg, and the flip it planned
  would have swung it further the wrong way. Someone at the mount can answer
  by looking (`Lineup.set_counterweight/3`); until then, it waits.
  """
  def side_guessed?(%{homed: false}, %{model: %{cw_told: false}}), do: true
  def side_guessed?(_snap, _ctx), do: false

  @doc """
  Where a Go To to `obj` puts the axes of a never-zeroed, lined-up mount, and
  how it gets there. Both poses reach the object: the one on this side of the
  pier wins while its counterweight stays below level (within the margin; up
  to the hard limit with `watched: true`), otherwise the other one, a
  meridian flip. The RA axis turns whichever way keeps the counterweight
  lowest on the way; the Dec axis goes through the pole, never the ground.

      %{pose: :same | :flip, ra: deg, dec: deg, d_ra: deg, d_dec: deg,
        cw: counterweight at landing, cw_same: counterweight if it stayed}
  """
  def landing(obj, snap, %{model: m, pointing: p} = ctx, opts \\ []) when is_map(m) do
    sg = signs_of(m, p)
    cur_ra = snap.axes.ra.degrees
    cur_dec = snap.axes.dec.degrees
    lst = Astro.lst_deg(ctx.now, ctx.site.lon)
    {alt, az} = Astro.alt_az(obj.ra_deg, obj.dec_deg, ctx.site.lat, lst)

    [same, other] =
      Model.solutions(m, sg, alt, az)
      |> Enum.sort_by(fn {r, d} -> abs(Astro.norm180(r - cur_ra)) + abs(d - cur_dec) end)

    cw_same = counterweight(ctx, elem(same, 0))
    stay_limit = if Keyword.get(opts, :watched, false), do: @meridian_hard, else: @meridian_margin
    {pose, {ra, dec}} = if cw_same <= stay_limit, do: {:same, same}, else: {:flip, other}

    d_ra = ra_turn(ctx, cur_ra, ra)
    dec = dec_through_pole(m, sg, cur_dec, dec)

    %{
      pose: pose,
      ra: cur_ra + d_ra,
      dec: dec,
      d_ra: d_ra,
      d_dec: dec - cur_dec,
      cw: counterweight(ctx, ra),
      cw_same: cw_same
    }
  end

  @doc """
  The first leg of a meridian flip: home, with the counterweight straight down
  and the tube at the pole, the most compact pose the mount has. Nothing is
  tracked there; the second leg is a Go To with `flip: true`. Only for a
  never-zeroed, lined-up mount (a zeroed one has `Mount.goto_home`).
  """
  def home_leg(ref, snap, %{model: m, pointing: p} = ctx) when is_map(m) do
    # "counterweight straight down" is only where the model has it: on a guess, it may be straight up
    if side_guessed?(snap, ctx), do: {:error, :counterweight_unknown}, else: do_home_leg(ref, snap, m, p, ctx)
  end

  def home_leg(_ref, _snap, _ctx), do: {:error, :not_lined_up}

  defp do_home_leg(ref, snap, m, p, ctx) do
    sg = signs_of(m, p)
    cur_ra = snap.axes.ra.degrees
    cur_dec = snap.axes.dec.degrees
    # counterweight(h) = cw·asin(sin h) is -90 at h = -90·cw
    h_down = -90.0 * Map.get(m, :cw, 1)
    ra = (h_down - m.off_ra) / sg.ha_sign
    dec = dec_through_pole(m, sg, cur_dec, (0.0 - m.off_dec) / sg.dec_sign)
    go(ref, snap, nil, ctx, ra_turn(ctx, cur_ra, ra), dec - cur_dec, track: false)
  end

  @doc "One line for a Go To that didn't start, naming the object."
  def refusal_words(error, name) do
    case error do
      :not_connected ->
        "No mount connected"

      :not_homed ->
        "Not aligned yet: center any star or planet and tap Centered, or set home (Setup)"

      :limit ->
        "#{name} is outside the soft limits from here"

      :unreachable ->
        "The mount didn't answer"

      :motor_running ->
        "The mount was still moving and didn't take the Go To to #{name}: try again once it's still"

      :goto_not_started ->
        "The mount didn't start the Go To to #{name}: try again"

      # the one question someone at the mount can answer by looking (#113)
      :counterweight_unknown ->
        "Which side is the counterweight on? Say whether the bar is below or above level right now, then Go To again"

      {:flip, %{past: past}} ->
        "#{name} needs a meridian flip (on this side the counterweight would sit #{round(past)}° above level): open #{name} to flip in two legs"

      other ->
        "Go To didn't start: #{inspect(other)}"
    end
  end

  # the short way round, unless the long way keeps the counterweight lower
  defp ra_turn(ctx, from, to) do
    short = Astro.norm180(to - from)
    long = if short > 0, do: short - 360, else: short + 360
    Enum.min_by([short, long], &{Float.round(highest(ctx, from, &1), 0), abs(&1)})
  end

  defp highest(ctx, from, delta) do
    n = max(ceil(abs(delta) / 2), 1)
    Enum.reduce(0..n, -90.0, fn i, top -> max(top, counterweight(ctx, from + delta * i / n)) end)
  end

  # Dec 0 is the pole and 180 the point opposite it, below the horizon: a
  # path through 180 swings the tube through the ground and the tripod.
  defp dec_through_pole(m, sg, cur, target) do
    d_of = fn theta -> sg.dec_sign * theta + m.off_dec end
    theta_of = fn d -> (d - m.off_dec) / sg.dec_sign end
    d_cur = d_of.(cur)

    [-360, 0, 360]
    |> Enum.map(&theta_of.(d_of.(target) + &1))
    |> Enum.filter(fn theta -> not through_ground?(d_cur, d_of.(theta)) end)
    |> Enum.min_by(&abs(&1 - cur), fn -> target end)
  end

  defp through_ground?(a, b) do
    {lo, hi} = {min(a, b), max(a, b)}
    # an odd multiple of 180 strictly between the two
    k = Float.ceil((lo - 180) / 360)
    180 + 360 * k < hi and 180 + 360 * k > lo
  end

  @doc "Where the scope points now (RA/Dec degrees). nil until homed (first-order) or lined up."
  def scope_radec(%{axes: %{ra: ra, dec: dec}}, %{model: m, pointing: p, site: site, now: now})
      when is_map(m) do
    lst = Astro.lst_deg(now, site.lon)
    Model.radec(m, signs_of(m, p), ra.degrees, dec.degrees, site.lat, lst)
  end

  def scope_radec(%{homed: true, axes: %{ra: ra, dec: dec}}, %{
        now: now,
        site: site,
        pointing: p,
        offset: off
      }) do
    lst = Astro.lst_deg(now, site.lon)
    d = (dec.degrees - off["dec"]) * p.dec_sign
    ha = (ra.degrees - off["ra"]) * p.ha_sign

    if d >= 0,
      do: {Astro.norm360(lst - ha), 90 - d},
      else: {Astro.norm360(lst - ha - 180), 90 + d}
  end

  def scope_radec(_, _), do: nil

  # a fitted model only means something under the axis signs it was fitted with
  defp signs_of(%{signs: %{ha_sign: _, dec_sign: _} = sg}, _p), do: sg
  defp signs_of(_, p), do: p

  @doc """
  Slew `ref` to `obj`. Zeroed, the soft limits keep the cables safe; never
  zeroed, the lined-up model keeps the counterweight down (`landing/4`): a Go
  To that needs a meridian flip returns `{:error, {:flip, %{past:, stay?:}}}`
  until it is asked again with `flip: true` (or `watched: true` to stay on
  this side, up to the hard limit). Never zeroed with the counterweight's
  side only guessed, it moves nothing: `{:error, :counterweight_unknown}`
  (`side_guessed?/2`). With `track: true` (default) tracking follows:
  sidereal from the driver on a polar-aligned mount, the model tracker on a
  lined-up one. Returns `{:ok, d_ra, d_dec}` or an error.
  """
  def slew(ref, snap, obj, ctx, opts \\ []) do
    cond do
      is_nil(snap) or not snap.connected ->
        {:error, :not_connected}

      # lined up (star or photo alignment) the model knows where the axes'
      # zeros are without a zero; otherwise zeroing is what places the sky
      not snap.homed and not lined_up?(ctx) ->
        {:error, :not_homed}

      # never zeroed, and which side the counterweight is on only a guess: the guess was upside
      # down twice, and Go To drove the tube toward the tripod (#113). Nothing moves until told.
      side_guessed?(snap, ctx) ->
        {:error, :counterweight_unknown}

      # never zeroed, lined up: the model says where the counterweight hangs
      not snap.homed ->
        plan = landing(obj, snap, ctx, opts)
        # aim at where the object will be when the goto lands, not where it
        # is now: a 30 s slew is 7′ of sky
        later = %{
          ctx
          | now: DateTime.add(ctx.now, round(flight_s(plan.d_ra, plan.d_dec)), :second)
        }

        plan = landing(obj, snap, later, opts)

        cond do
          plan.pose == :flip and not Keyword.get(opts, :flip, false) ->
            {:error,
             {:flip, %{past: Float.round(plan.cw_same, 1), stay?: plan.cw_same <= @meridian_hard}}}

          true ->
            go(ref, snap, obj, ctx, plan.d_ra, plan.d_dec, opts)
        end

      true ->
        near = {snap.axes.ra.degrees, snap.axes.dec.degrees}
        {ra_axis, dec_axis} = axes_for(obj, ctx, near: near)

        later = %{
          ctx
          | now:
              DateTime.add(
                ctx.now,
                round(flight_s(ra_axis - elem(near, 0), dec_axis - elem(near, 1))),
                :second
              )
        }

        {ra_axis, dec_axis} = axes_for(obj, later, near: near)

        # both legs checked before either moves: never half a slew
        if within?(snap, :ra, ra_axis) and within?(snap, :dec, dec_axis),
          do: go(ref, snap, obj, ctx, ra_axis - elem(near, 0), dec_axis - elem(near, 1), opts),
          else: {:error, :limit}
    end
  end

  defp flight_s(d_ra, d_dec), do: max(abs(d_ra), abs(d_dec)) / @goto_deg_s + @goto_ramp_s

  defp go(ref, snap, obj, ctx, d_ra, d_dec, opts) do
    track? = Keyword.get(opts, :track, true)
    # a running model tracker would fight the goto (and its stop would
    # kill it): drop it synchronously first; it is restarted below
    Controller.Sky.Tracker.stop(snap.id, halt: false)

    if lined_up?(ctx) do
      # the driver's sidereal mode would restart RA under the tracker
      if snap.tracking != :off, do: safe(fn -> Mount.track(ref, :off) end)
    else
      if track? and snap.tracking == :off, do: safe(fn -> Mount.track(ref, :sidereal) end)
    end

    # :ok from the driver means the leg was seen on its way, so the tracker is
    # only ever started behind a Go To that really began (#122)
    with :ok <- safe(fn -> Mount.goto_relative(ref, :ra, d_ra) end),
         :ok <- dec_leg(ref, d_dec) do
      if track? and lined_up?(ctx), do: Controller.Sky.Tracker.track(snap.id, obj)
      if obj, do: remember(snap.id, obj)
      {:ok, d_ra, d_dec}
    end
  end

  # never half a slew: when the Dec leg did not start, the RA leg that did is
  # stopped, so an error always means nothing is moving
  defp dec_leg(ref, d_dec) do
    with {:error, _} = error <- safe(fn -> Mount.goto_relative(ref, :dec, d_dec) end) do
      safe(fn -> Mount.stop(ref, :ra) end)
      error
    end
  end

  @doc "The last few objects a Go To went to on mount `id`, newest first: `[%{\"id\", \"name\"}]`."
  def recent(id), do: Settings.get("recent_targets", %{}) |> Map.get(id, [])

  # for going back after slewing away on purpose (the return-to-target test)
  defp remember(id, %{name: name} = obj) when is_binary(name) do
    entry = %{"id" => obj[:id], "name" => name}
    list = [entry | Enum.reject(recent(id), &(&1["name"] == name))] |> Enum.take(5)
    Settings.put("recent_targets", Map.put(Settings.get("recent_targets", %{}), id, list))
  end

  defp remember(_, _), do: :ok

  defp within?(%{limits: %{} = limits}, axis, degrees) do
    case limits[axis] do
      {lo, hi} -> degrees >= lo and degrees <= hi
      _ -> true
    end
  end

  defp within?(_, _, _), do: true

  @doc """
  "The scope is centred on `obj` right now." Adds a star alignment sample (one sample
  behaves like the old one-star sync; more make the geometry). Returns the
  star alignment status.
  """
  def sync(snap, obj, _ctx), do: Lineup.add(snap, obj)

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end
end
