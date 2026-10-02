defmodule Controller.Sky.EphemerisTest do
  # The Moon against JPL Horizons (astrometric RA/Dec, ICRF, 2026-09-26),
  # geocentric and from a test site at 40° N, 105° W, 1600 m. The first field
  # night aimed at a geocentric Moon of date: 22′ of precession and 45′ of
  # parallax from where the eyepiece saw it.
  use ExUnit.Case, async: true

  alias Controller.Sky.{Astro, Ephemeris}

  @site %{lat: 40.0, lon: -105.0, elevation_m: 1600}
  @au_km 149_597_870.7

  # {time, geocentric {ra, dec, distance au}, topocentric {ra, dec}}
  @horizons [
    {~U[2026-09-26 05:00:00Z], {355.933221523, 0.849199865, 0.00254971834682}, {356.202924840, 0.241119955}},
    {~U[2026-10-18 03:00:00Z], {290.404141463, -25.380700987, 0.00269930391731}, {289.947211640, -26.146372473}},
    {~U[2027-03-10 12:00:00Z], {11.330970804, 9.461868949, 0.00258871145168}, {11.899284742, 8.795110054}}
  ]

  defp arcmin(ra1, dec1, ra2, dec2), do: Astro.separation_radec(ra1, dec1, ra2, dec2) * 60

  # the shift from one position to another, in arcminutes on the sky
  defp shift(ra1, dec1, ra2, dec2), do: {Astro.norm180(ra2 - ra1) * :math.cos(dec1 * :math.pi() / 180) * 60, (dec2 - dec1) * 60}

  test "without a site the Moon is geocentric, J2000, within a few arcminutes of Horizons" do
    for {t, {ra, dec, _}, _} <- @horizons do
      p = Ephemeris.position(:moon, t)
      assert arcmin(p.ra_deg, p.dec_deg, ra, dec) < 5, "#{t}: #{arcmin(p.ra_deg, p.dec_deg, ra, dec)}′"
    end
  end

  test "from a site the Moon is where that observer sees it" do
    for {t, _, {ra, dec}} <- @horizons do
      p = Ephemeris.position(:moon, t, @site)
      assert arcmin(p.ra_deg, p.dec_deg, ra, dec) < 5, "#{t}: #{arcmin(p.ra_deg, p.dec_deg, ra, dec)}′"
    end
  end

  test "the parallax itself matches Horizons to a fraction of an arcminute" do
    for {t, {gra, gdec, _}, {tra, tdec}} <- @horizons do
      geo = Ephemeris.position(:moon, t)
      topo = Ephemeris.position(:moon, t, @site)
      {x, y} = shift(geo.ra_deg, geo.dec_deg, topo.ra_deg, topo.dec_deg)
      {hx, hy} = shift(gra, gdec, tra, tdec)
      assert :math.sqrt((x - hx) ** 2 + (y - hy) ** 2) < 0.5, "#{t}: ours #{inspect({x, y})}′, Horizons #{inspect({hx, hy})}′"
    end
  end

  test "the Moon's distance is good to a few hundred km" do
    for {t, {_, _, au}, _} <- @horizons do
      assert_in_delta Ephemeris.position(:moon, t).distance_km, au * @au_km, 500
    end
  end

  test "objects/2 carries the site through to the Moon and leaves the planets alone" do
    t = ~U[2026-09-26 05:00:00Z]
    moon = fn objs -> Enum.find(objs, &(&1.kind == :moon)) end
    geo = moon.(Ephemeris.objects(t))
    topo = moon.(Ephemeris.objects(t, @site))
    assert arcmin(geo.ra_deg, geo.dec_deg, topo.ra_deg, topo.dec_deg) > 30

    saturn = fn objs -> Enum.find(objs, &(&1.name == "Saturn")) end
    assert saturn.(Ephemeris.objects(t)) == saturn.(Ephemeris.objects(t, @site))
  end
end
