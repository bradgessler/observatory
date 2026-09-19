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

  A German equatorial reaches every point two ways; both models pick the one
  that keeps the RA axis within ±90° of home so the counterweight stays below.
  """

  alias Controller.Settings
  alias Controller.Sky.{Astro, Lineup, Model}

  # EQ6-R goto: 800× sidereal, plus ramps
  @goto_deg_s 360.0 / 86_164.0905 * 800
  @goto_ramp_s 3.0

  @type ctx :: %{now: DateTime.t(), site: map, pointing: map, offset: map, model: map | nil, mount: String.t() | nil}

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
      %{"lat" => lat, "lon" => lon} when is_number(lat) and is_number(lon) -> %{base | lat: lat / 1, lon: lon / 1}
      _ -> base
    end
  end

  def pointing do
    base = Application.get_env(:controller, :pointing, %{ha_sign: 1, dec_sign: -1})

    case Settings.get("pointing") do
      %{"ha_sign" => h, "dec_sign" => d} when h in [-1, 1] and d in [-1, 1] -> %{ha_sign: h, dec_sign: d}
      _ -> base
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

  @doc "Where the scope points now (RA/Dec degrees). nil until homed (first-order) or lined up."
  def scope_radec(%{axes: %{ra: ra, dec: dec}}, %{model: m, pointing: p, site: site, now: now}) when is_map(m) do
    lst = Astro.lst_deg(now, site.lon)
    Model.radec(m, signs_of(m, p), ra.degrees, dec.degrees, site.lat, lst)
  end

  def scope_radec(%{homed: true, axes: %{ra: ra, dec: dec}}, %{now: now, site: site, pointing: p, offset: off}) do
    lst = Astro.lst_deg(now, site.lon)
    d = (dec.degrees - off["dec"]) * p.dec_sign
    ha = (ra.degrees - off["ra"]) * p.ha_sign
    if d >= 0, do: {Astro.norm360(lst - ha), 90 - d}, else: {Astro.norm360(lst - ha - 180), 90 + d}
  end

  def scope_radec(_, _), do: nil

  # a fitted model only means something under the axis signs it was fitted with
  defp signs_of(%{signs: %{ha_sign: _, dec_sign: _} = sg}, _p), do: sg
  defp signs_of(_, p), do: p

  @doc """
  Slew `ref` to `obj`. Home must be set (that is what arms the soft limits that
  keep cables safe). With `track: true` (default) tracking follows: sidereal
  from the driver on a polar-aligned mount, the model tracker on a lined-up
  one. Returns `{:ok, d_ra, d_dec}` or an error.
  """
  def slew(ref, snap, obj, ctx, opts \\ []) do
    cond do
      is_nil(snap) or not snap.connected ->
        {:error, :not_connected}

      not snap.homed ->
        {:error, :not_homed}

      true ->
        near = {snap.axes.ra.degrees, snap.axes.dec.degrees}
        {ra_axis, dec_axis} = axes_for(obj, ctx, near: near)
        d_ra = ra_axis - snap.axes.ra.degrees
        d_dec = dec_axis - snap.axes.dec.degrees

        # aim at where the object will be when the goto lands, not where it
        # is now: a 30 s slew is 7′ of sky, which is the difference between
        # "in the eyepiece" and "hunt for it"
        flight_s = max(abs(d_ra), abs(d_dec)) / @goto_deg_s + @goto_ramp_s
        later = %{ctx | now: DateTime.add(ctx.now, round(flight_s), :second)}
        {ra_axis, dec_axis} = axes_for(obj, later, near: near)
        d_ra = ra_axis - snap.axes.ra.degrees
        d_dec = dec_axis - snap.axes.dec.degrees
        track? = Keyword.get(opts, :track, true)

        cond do
          # both legs checked before either moves: never half a slew
          not within?(snap, :ra, ra_axis) or not within?(snap, :dec, dec_axis) ->
            {:error, :limit}

          true ->
            # a running model tracker would fight the goto (and its stop would
            # kill it): drop it synchronously first; it is restarted below
            Controller.Sky.Tracker.stop(snap.id, halt: false)

            if lined_up?(ctx) do
              # the driver's sidereal mode would restart RA under the tracker
              if snap.tracking != :off, do: safe(fn -> Mount.track(ref, :off) end)
            else
              if track? and snap.tracking == :off, do: safe(fn -> Mount.track(ref, :sidereal) end)
            end

            with :ok <- safe(fn -> Mount.goto_relative(ref, :ra, d_ra) end),
                 :ok <- safe(fn -> Mount.goto_relative(ref, :dec, d_dec) end) do
              if track? and lined_up?(ctx), do: Controller.Sky.Tracker.track(snap.id, obj)
              {:ok, d_ra, d_dec}
            end
        end
    end
  end

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
