defmodule Controller.Sky.Ephemeris do
  @moduledoc """
  Low-precision positions for the Sun, Moon and naked-eye planets, good to a
  few arcminutes, which is what a slew-and-look needs. Sun and Moon follow
  Meeus' simplified series; planets use Keplerian elements (Standish, JPL
  approximate positions 1800–2050). Everything returns RA/Dec in degrees in
  the J2000 frame the star catalogs, the plate solver and the pointing model
  use.

  The Moon is close enough that where you stand moves it by up to a degree
  (its horizontal parallax, about 57′). Pass a site and it comes back as seen
  from there; without one it is geocentric. The first field night found both
  of these the hard way: a geocentric Moon of date was 45′ from where the
  eyepiece saw it, and a mount model fitted to it was off by 23′ rms instead
  of 7′.
  """

  alias Controller.Sky.Astro

  @deg :math.pi() / 180
  @obliquity 23.4393
  # general precession in longitude, degrees per Julian century (IAU 1976)
  @precession 1.3969713
  @earth_radius_km 6378.14

  @type body :: :sun | :moon | :mercury | :venus | :mars | :jupiter | :saturn

  @planets [:mercury, :venus, :mars, :jupiter, :saturn]

  def bodies, do: [:moon | @planets]

  @doc """
  RA/Dec (degrees, J2000) and apparent magnitude of `body` at `dt`. With a
  `site` (`%{lat:, lon:}`, east positive, optional `elevation_m`) the Moon is
  topocentric; planets and the Sun are far enough that it changes nothing.
  """
  def position(body, dt, site \\ nil)

  def position(:sun, dt, _site) do
    d = days(dt)
    {lon, _r} = sun_ecliptic(d)
    to_radec(to_j2000(lon, d), 0.0) |> Map.put(:mag, -26.7)
  end

  def position(:moon, dt, site) do
    d = days(dt)
    {lon, lat, dist} = moon_ecliptic(d)
    {slon, _} = sun_ecliptic(d)
    elong = Astro.norm180(lon - slon)
    # phase angle i ≈ 180 - elongation; the lit fraction is (1 + cos i) / 2:
    # 0 at new (elongation 0), 1 at full (elongation 180)
    illum = (1 + :math.cos((180 - abs(elong)) * @deg)) / 2

    to_radec(to_j2000(lon, d), lat)
    |> Map.merge(%{
      distance_km: dist,
      mag: Float.round(-12.7 + 5 * (1 - illum), 1),
      illumination: illum,
      waxing: elong > 0
    })
    |> topocentric(dt, site)
  end

  def position(planet, dt, _site) when planet in @planets do
    d = days(dt)
    t = d / 36525
    {xe, ye, ze} = helio(:earth, t)
    {xp, yp, zp} = helio(planet, t)
    {x, y, z} = {xp - xe, yp - ye, zp - ze}
    lon = Astro.norm360(:math.atan2(y, x) / @deg)
    lat = :math.atan2(z, :math.sqrt(x * x + y * y)) / @deg
    dist = :math.sqrt(x * x + y * y + z * z)
    r = :math.sqrt(xp * xp + yp * yp + zp * zp)
    to_radec(lon, lat) |> Map.put(:mag, magnitude(planet, r, dist, phase_angle(r, dist)))
  end

  @doc "The Sun's altitude in degrees seen from `site` at `dt`. Below −6° (civil twilight over) is dark enough to look."
  def sun_alt(dt, %{lat: lat, lon: lon}) do
    %{ra_deg: ra, dec_deg: dec} = position(:sun, dt)
    {alt, _} = Controller.Sky.Astro.alt_az(ra, dec, lat, Controller.Sky.Astro.lst_deg(dt, lon))
    alt
  end

  @doc """
  `p` (RA/Dec J2000 and `distance_km`) as seen from `site` at `dt` rather
  than from the centre of the Earth: the observer's own position, on the
  ellipsoid and turned by sidereal time, taken off the body's.
  """
  def topocentric(p, _dt, nil), do: p

  def topocentric(%{distance_km: dist} = p, dt, %{lat: lat, lon: lon} = site) do
    phi = lat * @deg
    h = Map.get(site, :elevation_m, 0) / 1000 / @earth_radius_km
    # Meeus 11: the observer's distance from the axis and the equator, in Earth radii
    u = :math.atan(0.99664719 * :math.tan(phi))
    rho_sin = 0.99664719 * :math.sin(u) + h * :math.sin(phi)
    rho_cos = :math.cos(u) + h * :math.cos(phi)
    # sidereal time is of date and the body is J2000; the 22′ between the
    # frames moves a 1° parallax by well under an arcsecond
    lst = Astro.lst_deg(dt, lon) * @deg

    {x, y, z} = vec(p.ra_deg, p.dec_deg, dist / @earth_radius_km)
    {x, y, z} = {x - rho_cos * :math.cos(lst), y - rho_cos * :math.sin(lst), z - rho_sin}
    ra = Astro.norm360(:math.atan2(y, x) / @deg)
    dec = :math.asin(z / :math.sqrt(x * x + y * y + z * z)) / @deg
    %{p | ra_deg: ra, dec_deg: dec}
  end

  @doc "Every body as a catalog-shaped object (id, name, ra_deg, dec_deg, mag, kind); the Moon from `site` when given."
  def objects(%DateTime{} = dt, site \\ nil) do
    for b <- bodies() do
      p = position(b, dt, site)

      %{
        id: "sol-#{b}",
        name: name(b, p),
        ra_deg: p.ra_deg,
        dec_deg: p.dec_deg,
        mag: p.mag,
        kind: if(b == :moon, do: :moon, else: :planet)
      }
    end
  end

  @doc "Moon illuminated fraction 0..1 and whether it's waxing."
  def moon_phase(dt) do
    p = position(:moon, dt)
    %{illumination: p.illumination, waxing: p.waxing, name: phase_name(p.illumination, p.waxing)}
  end

  # -- Sun & Moon (Meeus, simplified) ---------------------------------------------

  defp days(dt), do: Astro.julian_date(dt) - 2_451_545.0

  defp sun_ecliptic(d) do
    g = Astro.norm360(357.529 + 0.98560028 * d) * @deg
    q = Astro.norm360(280.459 + 0.98564736 * d)
    lon = Astro.norm360(q + 1.915 * :math.sin(g) + 0.020 * :math.sin(2 * g))
    r = 1.00014 - 0.01671 * :math.cos(g) - 0.00014 * :math.cos(2 * g)
    {lon, r}
  end

  # longitude, latitude (ecliptic of date, degrees) and distance (km)
  defp moon_ecliptic(d) do
    t = d / 36525
    lp = Astro.norm360(218.3164477 + 481_267.88123421 * t)
    dd = Astro.norm360(297.8501921 + 445_267.1114034 * t) * @deg
    m = Astro.norm360(357.5291092 + 35_999.0502909 * t) * @deg
    mp = Astro.norm360(134.9633964 + 477_198.8675055 * t) * @deg
    f = Astro.norm360(93.2720950 + 483_202.0175233 * t) * @deg

    lon =
      lp + 6.289 * :math.sin(mp) + 1.274 * :math.sin(2 * dd - mp) + 0.658 * :math.sin(2 * dd) +
        0.214 * :math.sin(2 * mp) - 0.186 * :math.sin(m) - 0.114 * :math.sin(2 * f) +
        0.059 * :math.sin(2 * dd - 2 * mp) + 0.057 * :math.sin(2 * dd - m - mp) +
        0.053 * :math.sin(2 * dd + mp) + 0.046 * :math.sin(2 * dd - m) - 0.041 * :math.sin(m - mp) -
        0.035 * :math.sin(dd) - 0.031 * :math.sin(m + mp)

    lat =
      5.128 * :math.sin(f) + 0.281 * :math.sin(mp + f) + 0.278 * :math.sin(mp - f) +
        0.173 * :math.sin(2 * dd - f) + 0.055 * :math.sin(2 * dd - mp + f) +
        0.046 * :math.sin(2 * dd - mp - f) + 0.033 * :math.sin(2 * dd + f) +
        0.017 * :math.sin(2 * mp + f)

    # Meeus 47.A, the terms over 100 km of 385,000
    dist =
      385_000.56 - 20_905.355 * :math.cos(mp) - 3_699.111 * :math.cos(2 * dd - mp) -
        2_955.968 * :math.cos(2 * dd) - 569.925 * :math.cos(2 * mp) + 48.888 * :math.cos(m) +
        246.158 * :math.cos(2 * dd - 2 * mp) - 152.138 * :math.cos(2 * dd - m - mp) -
        170.733 * :math.cos(2 * dd + mp) - 204.586 * :math.cos(2 * dd - m) -
        129.620 * :math.cos(m - mp) + 108.743 * :math.cos(dd) + 104.755 * :math.cos(m + mp)

    {Astro.norm360(lon), lat, dist}
  end

  # The Sun and Moon series are referred to the equinox of date; the catalogs
  # are J2000. Precession is a slide along the ecliptic, 22′ by 2026.
  defp to_j2000(lon, d), do: Astro.norm360(lon - @precession * d / 36_525)

  # -- Planets (Standish approximate elements, J2000 ecliptic) ---------------------------

  # {a, e, I, L, long.peri, long.node} and per-century rates
  defp elements(:mercury),
    do:
      {{0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593},
       {0.00000037, 0.00001906, -0.00594749, 149_472.67411175, 0.16047689, -0.12534081}}

  defp elements(:venus),
    do:
      {{0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255},
       {0.00000390, -0.00004107, -0.00078890, 58_517.81538729, 0.00268329, -0.27769418}}

  defp elements(:earth),
    do:
      {{1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0},
       {0.00000562, -0.00004392, -0.01294668, 35_999.37244981, 0.32327364, 0.0}}

  defp elements(:mars),
    do:
      {{1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891},
       {0.00001847, 0.00007882, -0.00813131, 19_140.30268499, 0.44441088, -0.29257343}}

  defp elements(:jupiter),
    do:
      {{5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909},
       {-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106}}

  defp elements(:saturn),
    do:
      {{9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448},
       {-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794}}

  defp helio(body, t) do
    {{a0, e0, i0, l0, w0, o0}, {da, de, di, dl, dw, do_}} = elements(body)
    a = a0 + da * t
    e = e0 + de * t
    i = (i0 + di * t) * @deg
    l = l0 + dl * t
    wbar = w0 + dw * t
    omega = (o0 + do_ * t) * @deg
    w = (wbar - (o0 + do_ * t)) * @deg
    m = Astro.norm180(l - wbar) * @deg
    ea = kepler(m, e)
    xp = a * (:math.cos(ea) - e)
    yp = a * :math.sqrt(1 - e * e) * :math.sin(ea)

    x =
      (:math.cos(w) * :math.cos(omega) - :math.sin(w) * :math.sin(omega) * :math.cos(i)) * xp +
        (-:math.sin(w) * :math.cos(omega) - :math.cos(w) * :math.sin(omega) * :math.cos(i)) * yp

    y =
      (:math.cos(w) * :math.sin(omega) + :math.sin(w) * :math.cos(omega) * :math.cos(i)) * xp +
        (-:math.sin(w) * :math.sin(omega) + :math.cos(w) * :math.cos(omega) * :math.cos(i)) * yp

    z = :math.sin(w) * :math.sin(i) * xp + :math.cos(w) * :math.sin(i) * yp
    {x, y, z}
  end

  defp kepler(m, e), do: kepler(m, e, m + e * :math.sin(m), 0)
  defp kepler(_m, _e, ea, 20), do: ea

  defp kepler(m, e, ea, n) do
    d = (ea - e * :math.sin(ea) - m) / (1 - e * :math.cos(ea))
    if abs(d) < 1.0e-8, do: ea - d, else: kepler(m, e, ea - d, n + 1)
  end

  defp phase_angle(r, dist) do
    # planet–sun–earth geometry with earth at 1 AU (close enough for magnitudes)
    c = (r * r + dist * dist - 1) / (2 * r * dist)
    :math.acos(max(-1.0, min(1.0, c))) / @deg
  end

  defp magnitude(p, r, d, ph) do
    base = 5 * :math.log10(r * d)

    case p do
      :mercury -> -0.6 + base + 0.0498 * ph - 0.000488 * ph * ph + 0.00000302 * ph * ph * ph
      :venus -> -4.47 + base + 0.0103 * ph + 0.000057 * ph * ph + 0.00000013 * ph * ph * ph
      :mars -> -1.52 + base + 0.016 * ph
      :jupiter -> -9.40 + base + 0.005 * ph
      :saturn -> -8.88 + base + 0.044 * ph
    end
    |> Float.round(1)
  end

  # -- helpers ------------------------------------------------------------------------------------

  defp vec(ra, dec, r) do
    {a, d} = {ra * @deg, dec * @deg}
    {r * :math.cos(d) * :math.cos(a), r * :math.cos(d) * :math.sin(a), r * :math.sin(d)}
  end

  defp to_radec(lon, lat) do
    l = lon * @deg
    b = lat * @deg
    e = @obliquity * @deg

    ra =
      :math.atan2(:math.sin(l) * :math.cos(e) - :math.tan(b) * :math.sin(e), :math.cos(l)) / @deg

    dec =
      :math.asin(:math.sin(b) * :math.cos(e) + :math.cos(b) * :math.sin(e) * :math.sin(l)) / @deg

    %{ra_deg: Astro.norm360(ra), dec_deg: dec}
  end

  defp name(:moon, %{illumination: i, waxing: w}), do: "Moon · #{phase_name(i, w)}"
  defp name(b, _), do: b |> Atom.to_string() |> String.capitalize()

  defp phase_name(i, waxing) do
    cond do
      i < 0.03 -> "new"
      i < 0.35 -> if(waxing, do: "waxing crescent", else: "waning crescent")
      i < 0.65 -> if(waxing, do: "first quarter", else: "last quarter")
      i < 0.97 -> if(waxing, do: "waxing gibbous", else: "waning gibbous")
      true -> "full"
    end
  end
end
