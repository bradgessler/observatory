defmodule Controller.Sky.PolarTest do
  @moduledoc """
  The polar alignment readout without a sky: a hidden mount, set down with
  its axis a little off the pole of date, is "photographed" by maths (where
  its tube truly points at those encoders, turned into the J2000 centre a
  plate solver would report), with centring noise added. The fit sees only
  what the page would hand it and must say how far to turn which bolt.
  """
  use ExUnit.Case, async: true

  alias Controller.Sky.{Astro, Model, Polar}

  @lat 37.88
  @lon -122.18
  @site %{lat: @lat, lon: @lon}
  @signs %{ha_sign: 1, dec_sign: -1}
  @now ~U[2026-09-20 05:30:00Z]

  # 0.5° too low, 0.8° (of azimuth) east of the pole of date, encoders not zeroed exactly
  @truth %{axis_alt: @lat - 0.5, axis_az: 0.8, off_ra: 3.0, off_dec: -1.5}

  # encoders (degrees from home) spread over the sky east and west of the meridian
  @spots [{-40, -30}, {25, -40}, {-10, -50}, {50, -25}, {0, -60}, {35, -55}, {-25, -20}, {10, -35}]

  # What a photo at these encoders reports: where the tube truly points (the
  # sky of date), as the J2000 centre a plate solver gives, plus noise.
  defp photo(truth, {r, d}, at, noise_arcmin, site) do
    {alt, az} = Model.altaz(truth, @signs, r / 1, d / 1)
    {ra, dec} = Astro.radec_from_altaz(alt, az, site.lat, Astro.lst_deg(at, site.lon))
    {ra, dec} = Astro.precess_to_j2000(ra, dec, at)
    {n1, n2} = {:rand.normal(), :rand.normal()}
    ddec = n2 * noise_arcmin / 60
    dra = n1 * noise_arcmin / 60 / :math.cos(dec * :math.pi() / 180)
    %{theta_ra: r / 1, theta_dec: d / 1, ra_deg: ra + dra, dec_deg: dec + ddec, at: at}
  end

  # one photo a minute, as a person would take them
  defp photos(truth, spots, noise \\ 0.0, site \\ @site) do
    spots |> Enum.with_index() |> Enum.map(fn {s, i} -> photo(truth, s, DateTime.add(@now, 60 * i, :second), noise, site) end)
  end

  defp fit(samples, opts \\ []), do: Polar.fit(samples, Keyword.merge([site: @site, signs: @signs], opts))

  defp move(r, knob), do: Enum.find(r.moves, &(&1.knob == knob))

  setup do
    :rand.seed(:exsss, {88, 1, 2})
    :ok
  end

  test "precession: the pole of date sits about 0.15° from the J2000 pole in 2026" do
    {ra, dec} = Astro.precess_to_j2000(0.0, 90.0, @now)
    assert_in_delta 90 - dec, 0.149, 0.003
    # and back again: that J2000 point is the pole of date
    {_, dec2} = Astro.precess_from_j2000(ra, dec, @now)
    assert_in_delta dec2, 90.0, 1.0e-6
    # Vega: 2.016 s/yr in RA and 3.2″/yr in Dec (the annual formulae), 23.8″ a year
    # on the sky, so 10.6′ by September 2026
    {vra, vdec} = Astro.precess_from_j2000(279.2347, 38.7837, @now)
    assert_in_delta Astro.separation_radec(279.2347, 38.7837, vra, vdec) * 60, 10.6, 0.2
    assert vdec > 38.7837
  end

  test "three clean photos: the axis error of date, to well under an arcminute" do
    {:ok, r} = photos(@truth, Enum.take(@spots, 3)) |> fit()

    assert_in_delta r.alt_error_deg, -0.5, 0.01
    assert_in_delta r.east_error_deg, 0.8, 0.01
    assert_in_delta r.error_deg, Model.axis_error(@truth, @lat), 0.01
    assert %{dir: :raise, deg: alt} = move(r, :altitude)
    assert_in_delta alt, 0.5, 0.01
    assert %{dir: :west, deg: az} = move(r, :azimuth)
    assert_in_delta az, 0.8, 0.01
    assert r.rms_arcmin < 0.5
    assert r.spread_ok?

    # against the J2000 pole the same fit would be about 0.15° wrong: the precession matters
    {pra, pdec} = {0.0, 90.0}
    lst = Astro.lst_deg(DateTime.add(@now, 60, :second), @lon)
    {jalt, jaz} = Astro.alt_az(pra, pdec, @lat, lst)
    naive = Astro.separation(Astro.altaz_vec(r.pole.alt, r.pole.az), Astro.altaz_vec(jalt, jaz))
    assert_in_delta naive, 0.149, 0.01
  end

  test "worst-case drift is the sidereal rate times the error" do
    assert_in_delta Polar.drift_arcmin_per_min(1.0), 0.2625, 0.001
    {:ok, r} = photos(@truth, Enum.take(@spots, 3)) |> fit()
    assert_in_delta r.drift_arcmin_per_min, Polar.drift_arcmin_per_min(r.error_deg), 1.0e-9
  end

  test "with a few arcminutes of noise: within the margin, and the margin shrinks with more photos" do
    reports =
      for n <- [2, 4, 8] do
        {:ok, r} = photos(@truth, Enum.take(@spots, n), 2.0) |> fit()
        r
      end

    [m2, m4, m8] = Enum.map(reports, &move(&1, :altitude).margin_deg)
    [z2, z4, z8] = Enum.map(reports, &move(&1, :azimuth).margin_deg)
    assert m8 < m4 and m4 < m2, "altitude margins #{inspect([m2, m4, m8])}"
    assert z8 < z4 and z4 < z2, "azimuth margins #{inspect([z2, z4, z8])}"

    for r <- Enum.drop(reports, 1) do
      assert abs(r.alt_error_deg + 0.5) <= move(r, :altitude).margin_deg
      assert abs(r.east_error_deg - 0.8) <= move(r, :azimuth).margin_deg
      assert move(r, :altitude).dir == :raise
      assert move(r, :azimuth).dir == :west
    end

    # and eight photos pin it down to a few arcminutes
    assert m8 < 0.1 and z8 < 0.15
  end

  test "two photos fit exactly, so their margin is the assumption; a third can say the photos are worse" do
    {:ok, two} = photos(@truth, Enum.take(@spots, 2), 1.0) |> fit()
    assert two.rms_arcmin < 0.01
    assert two.noise_from == :assumed
    assert two.sigma_arcmin == 3.0

    # a sloppy photo among four: it stands out, and the noise estimate comes from the photos
    [a, b, c, d] = photos(@truth, Enum.take(@spots, 4), 0.5)
    bad = %{b | dec_deg: b.dec_deg + 0.4}
    {:ok, r} = fit([a, bad, c, d])
    assert r.noise_from == :photos
    assert r.sigma_arcmin > 3.0
    assert Enum.at(r.residuals_arcmin, 1) == Enum.max(r.residuals_arcmin)
  end

  test "photos close together in RA get a warning and a wide margin" do
    {:ok, near} = photos(@truth, [{0, -40}, {5, -45}]) |> fit()
    {:ok, far} = photos(@truth, [{-20, -40}, {25, -45}]) |> fit()
    refute near.spread_ok?
    assert_in_delta near.spread_deg, 5.0, 1.0e-9
    assert far.spread_ok?
    assert move(near, :altitude).margin_deg > 3 * move(far, :altitude).margin_deg
    assert Polar.min_spread_deg() == 20.0
  end

  test "one photo is offsets only: no polar readout yet" do
    {:ok, r} = photos(@truth, [{0, -40}]) |> fit()
    assert r.n == 1
    refute Map.has_key?(r, :moves)
    assert r.spread_deg == 0.0
  end

  test "an axis high and west asks to lower it and turn east" do
    truth = %{@truth | axis_alt: @lat + 0.7, axis_az: -1.1}
    {:ok, r} = photos(truth, Enum.take(@spots, 3)) |> fit()
    assert %{dir: :lower, deg: alt} = move(r, :altitude)
    assert_in_delta alt, 0.7, 0.01
    assert %{dir: :east, deg: az} = move(r, :azimuth)
    assert_in_delta az, 1.1, 0.01
  end

  test "south of the equator the pole is the south one, and east and west swap sides" do
    site = %{lat: -33.87, lon: 151.21}
    # 0.5° low, and 0.8° east of the south celestial pole (azimuth 180 is south, 90 east)
    truth = %{axis_alt: 33.87 - 0.5, axis_az: 180.0 - 0.8, off_ra: 2.0, off_dec: 1.0}
    spots = [{-40, 30}, {25, 40}, {-10, 50}, {40, 35}]
    {:ok, r} = photos(truth, spots, 0.0, site) |> Polar.fit(site: site, signs: @signs)
    assert r.pole.alt > 0 and abs(Astro.norm180(r.pole.az - 180)) < 1
    assert %{dir: :raise, deg: alt} = move(r, :altitude)
    assert_in_delta alt, 0.5, 0.02
    assert %{dir: :west, deg: az} = move(r, :azimuth)
    assert_in_delta az, 0.8, 0.02
  end
end
