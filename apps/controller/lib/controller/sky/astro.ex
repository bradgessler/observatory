defmodule Controller.Sky.Astro do
  @moduledoc """
  Just enough positional astronomy for a sky map: sidereal time, equatorial ↔
  horizontal coordinates, and a stereographic all-sky projection. Accurate to
  a few arcminutes, which is plenty to point a scope and then plate solve.
  """

  @deg :math.pi() / 180

  @doc "Julian date for a DateTime (UTC)."
  def julian_date(%DateTime{} = dt) do
    unix = DateTime.to_unix(dt, :millisecond) / 1000
    2_440_587.5 + unix / 86_400
  end

  @doc "Local sidereal time in degrees for longitude `lon` (east positive)."
  def lst_deg(%DateTime{} = dt, lon) do
    d = julian_date(dt) - 2_451_545.0
    gmst = 280.46061837 + 360.98564736629 * d
    norm360(gmst + lon)
  end

  @doc "Hour angle in degrees, normalized to (-180, 180]."
  def hour_angle(lst, ra_deg), do: norm180(lst - ra_deg)

  @doc "Alt/az in degrees for an object at `ra_deg`/`dec_deg` seen from `lat` at sidereal time `lst`."
  def alt_az(ra_deg, dec_deg, lat, lst) do
    ha = hour_angle(lst, ra_deg) * @deg
    dec = dec_deg * @deg
    phi = lat * @deg

    sin_alt = :math.sin(dec) * :math.sin(phi) + :math.cos(dec) * :math.cos(phi) * :math.cos(ha)
    alt = :math.asin(clamp(sin_alt))

    y = -:math.sin(ha) * :math.cos(dec)
    x = :math.sin(dec) * :math.cos(phi) - :math.cos(dec) * :math.sin(phi) * :math.cos(ha)
    az = norm360(:math.atan2(y, x) / @deg)

    {alt / @deg, az}
  end

  @doc """
  Stereographic projection of alt/az onto a unit disc: zenith at the centre,
  horizon on the rim, north up, east to the LEFT (as when you look up).
  Returns `{x, y}` in [-1, 1] with y down (screen coordinates).
  """
  def project(alt, az) do
    z = (90 - alt) * @deg
    r = :math.tan(z / 2) / :math.tan(45 * @deg)
    a = az * @deg
    {-r * :math.sin(a), -r * :math.cos(a)}
  end

  @doc "The inverse of `alt_az/4`: RA/Dec in degrees for a horizontal direction seen from `lat` at `lst`."
  def radec_from_altaz(alt, az, lat, lst) do
    a = alt * @deg
    z = az * @deg
    phi = lat * @deg

    sin_dec = :math.sin(a) * :math.sin(phi) + :math.cos(a) * :math.cos(phi) * :math.cos(z)
    dec = :math.asin(clamp(sin_dec))
    y = -:math.sin(z) * :math.cos(a)
    x = :math.sin(a) * :math.cos(phi) - :math.cos(a) * :math.sin(phi) * :math.cos(z)
    ha = :math.atan2(y, x) / @deg
    {norm360(lst - ha), dec / @deg}
  end

  @doc "Unit vector for alt/az in an east-north-up frame."
  def altaz_vec(alt, az) do
    a = alt * @deg
    z = az * @deg
    {:math.cos(a) * :math.sin(z), :math.cos(a) * :math.cos(z), :math.sin(a)}
  end

  @doc "Alt/az in degrees for an east-north-up unit vector."
  def vec_altaz({x, y, z}) do
    {:math.asin(clamp(z)) / @deg, norm360(:math.atan2(x, y) / @deg)}
  end

  @doc "Angular separation in degrees between two unit vectors."
  def separation({ax, ay, az}, {bx, by, bz}) do
    dot = ax * bx + ay * by + az * bz
    :math.acos(clamp(dot)) / @deg
  end

  @doc "Angular separation in degrees between two RA/Dec points."
  def separation_radec(ra1, dec1, ra2, dec2) do
    separation(altaz_vec(dec1, ra1), altaz_vec(dec2, ra2))
  end

  def norm360(x) do
    r = :math.fmod(x, 360.0)
    if r < 0, do: r + 360, else: r
  end

  def norm180(x) do
    r = norm360(x)
    if r > 180, do: r - 360, else: r
  end

  defp clamp(v), do: v |> max(-1.0) |> min(1.0)
end
