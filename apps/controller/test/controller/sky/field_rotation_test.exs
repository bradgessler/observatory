defmodule Controller.Sky.FieldRotationTest do
  use ExUnit.Case, async: true
  alias Controller.Sky.{Astro, FieldRotation}

  @site %{lat: 37.34, lon: -121.64}
  @at ~U[2026-10-18 06:00:00Z]

  test "a polar axis on the pole turns nothing" do
    # the pole of date, so precession doesn't count as an error
    {ra, dec} = Astro.precess_from_j2000(0.0, 90.0, @at) |> then(fn {r, d} -> {r, d} end)
    {alt, az} = Astro.alt_az(ra, dec, @site.lat, Astro.lst_deg(@at, @site.lon))
    rate = FieldRotation.rate_deg_per_h(%{alt: alt, az: az}, 23.46, 30.66, @site, @at)
    assert abs(rate) < 0.05
  end

  test "an alt-az mount (the axis straight up) turns as the textbook says: sidereal x cos(lat) x cos(az) / cos(alt)" do
    for {ra, dec} <- [{23.46, 30.66}, {83.82, -5.39}, {299.9, 22.72}] do
      lst = Astro.lst_deg(@at, @site.lon)
      {alt, az} = Astro.alt_az(ra, dec, @site.lat, lst)

      if alt > 15 and alt < 75 do
        expected = 15.041 * :math.cos(@site.lat * :math.pi() / 180) * :math.cos(az * :math.pi() / 180) / :math.cos(alt * :math.pi() / 180)
        rate = FieldRotation.rate_deg_per_h(%{alt: 90.0, az: 0.0}, ra, dec, @site, @at)
        assert_in_delta abs(rate), abs(expected), 0.02 * abs(expected) + 0.05
      end
    end
  end

  test "ten degrees off the pole turns the field a few degrees an hour, as the 17 October stack measured" do
    {alt, az} = {@site.lat - 4.6, 360 - 11.8}
    rate = FieldRotation.rate_deg_per_h(%{alt: alt, az: az}, 23.46, 30.66, @site, @at)
    assert abs(rate) > 0.5 and abs(rate) < 6
  end

  test "smear and the longest exposure: 1 arcsec in the corners of the 8SE and a6000" do
    corner = FieldRotation.corner_arcsec(2084)
    assert_in_delta corner, 1400, 30
    # 2.5 degrees an hour: half an arcsecond in 30 s, about 70 s for one arcsecond
    assert_in_delta FieldRotation.smear_arcsec(2.5, 30, corner), 0.51, 0.05
    assert_in_delta FieldRotation.max_exposure_s(2.5, corner, 1.0), 59, 5
    assert FieldRotation.max_exposure_s(0.0, corner, 1.0) == nil
  end
end
