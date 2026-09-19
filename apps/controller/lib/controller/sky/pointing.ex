defmodule Controller.Sky.Pointing do
  @moduledoc """
  The first-order pointing model, in one place: sky ↔ mount axes.

  Assumes the mount was homed at the pole with the counterweight down and knows
  the sign of each axis (`ctx.pointing`) plus a persisted one-star sync offset
  (`ctx.offset`). A German equatorial reaches every point two ways; we pick the
  one that keeps the RA axis within ±90° of home so the counterweight stays
  below the mount. Plate solving will replace all of this.
  """

  alias Controller.Settings
  alias Controller.Sky.Astro

  @type ctx :: %{now: DateTime.t(), site: map, pointing: map, offset: map}

  @doc "Current model context from config + persisted settings."
  def context(now \\ DateTime.utc_now()) do
    %{now: now, site: site(), pointing: pointing(), offset: Settings.get("pointing_offset", %{"ra" => 0.0, "dec" => 0.0})}
  end

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

  @doc "Axis targets (degrees from home) for an object, without the sync offset."
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

  @doc "Axis targets with the sync offset applied."
  def axes_for(obj, %{offset: off} = ctx) do
    {ra, dec} = raw_axes_for(obj, ctx)
    {ra + off["ra"], dec + off["dec"]}
  end

  @doc "Where the scope points now (RA/Dec degrees), or nil until homed."
  def scope_radec(%{homed: true, axes: %{ra: ra, dec: dec}}, %{now: now, site: site, pointing: p, offset: off}) do
    lst = Astro.lst_deg(now, site.lon)
    d = (dec.degrees - off["dec"]) * p.dec_sign
    ha = (ra.degrees - off["ra"]) * p.ha_sign
    if d >= 0, do: {Astro.norm360(lst - ha), 90 - d}, else: {Astro.norm360(lst - ha - 180), 90 + d}
  end

  def scope_radec(_, _), do: nil

  @doc """
  Slew `ref` to `obj`. Arms sidereal tracking first when asked (the driver
  re-arms it after the RA goto lands). Returns `{:ok, d_ra, d_dec}` or an error.
  """
  def slew(ref, snap, obj, ctx, opts \\ []) do
    cond do
      is_nil(snap) or not snap.connected -> {:error, :not_connected}
      not snap.homed -> {:error, :not_homed}
      true ->
        {ra_axis, dec_axis} = axes_for(obj, ctx)
        d_ra = ra_axis - snap.axes.ra.degrees
        d_dec = dec_axis - snap.axes.dec.degrees

        if Keyword.get(opts, :track, true) and snap.tracking == :off, do: safe(fn -> Mount.track(ref, :sidereal) end)

        with :ok <- safe(fn -> Mount.goto_relative(ref, :ra, d_ra) end),
             :ok <- safe(fn -> Mount.goto_relative(ref, :dec, d_dec) end) do
          {:ok, d_ra, d_dec}
        end
    end
  end

  @doc "One-star sync: make the model agree that the scope is on `obj` right now. Returns the new offset."
  def sync(snap, obj, ctx) do
    {ra_raw, dec_raw} = raw_axes_for(obj, ctx)
    off = %{"ra" => snap.axes.ra.degrees - ra_raw, "dec" => snap.axes.dec.degrees - dec_raw}
    Settings.put("pointing_offset", off)
    off
  end

  defp safe(fun) do
    try do
      fun.()
    catch
      :exit, _ -> {:error, :unreachable}
    end
  end
end
