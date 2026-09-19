defmodule Controller.Sky.ModelTest do
  @moduledoc """
  The line-up loop, without a sky: a hidden "true" mount geometry stands in for
  a mount set down anyhow. We centre stars on it by maths (true encoders for
  the star), hand the model only what a person would — encoders plus which
  star — and check the fit recovers the truth and a goto to something else
  lands.
  """
  use ExUnit.Case, async: true

  alias Controller.Sky.{Astro, Model, Stars}

  @signs %{ha_sign: 1, dec_sign: -1}
  @lat 37.88
  @lon -122.18
  @now ~U[2026-09-20 05:30:00Z]

  defp lst(now \\ @now), do: Astro.lst_deg(now, @lon)

  defp star(name), do: Enum.find(Stars.all(), &(&1.name == name))

  # what the person does: centre the star, tap "that's it" → encoders + the star's alt/az then
  defp centre(truth, name, now \\ @now) do
    s = star(name)
    {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, @lat, lst(now))
    {r, d} = Model.encoders(truth, @signs, alt, az)
    %{theta_ra: r, theta_dec: d, alt: alt, az: az, name: name}
  end

  describe "geometry" do
    test "ideal mount agrees with the first-order model in Pointing" do
      ideal = Model.ideal(@lat)
      ctx = %{now: @now, site: %{lat: @lat, lon: @lon}, pointing: @signs}

      for name <- ["Vega", "Altair", "Deneb", "Arcturus", "Fomalhaut"] do
        s = star(name)
        {r0, d0} = Controller.Sky.Pointing.raw_axes_for(s, ctx)
        {alt, az} = Astro.alt_az(s.ra_deg, s.dec_deg, @lat, lst())
        # the first-order model's encoders put the tube on the star in the new model
        assert Astro.separation(Model.tube_vec(ideal, @signs, r0, d0), Astro.altaz_vec(alt, az)) < 0.01, name
        # and the inverse gives those encoders back (same side)
        {r1, d1} = Model.encoders(ideal, @signs, alt, az, {r0, d0})
        assert_in_delta r1, r0, 0.01
        assert_in_delta d1, d0, 0.01
      end
    end

    test "forward and inverse round-trip on a badly set-up mount" do
      truth = %{axis_alt: 25.0, axis_az: 72.0, off_ra: 14.0, off_dec: -6.5}

      for {alt, az} <- [{60, 120}, {30, 200}, {80, 10}, {15, 300}] do
        for {r, d} <- Model.solutions(truth, @signs, alt / 1, az / 1) do
          {a2, z2} = Model.altaz(truth, @signs, r, d)
          assert Astro.separation(Astro.altaz_vec(alt / 1, az / 1), Astro.altaz_vec(a2, z2)) < 0.001
        end
      end
    end

    test "radec ↔ altaz inverse closes" do
      for {ra, dec} <- [{279.2, 38.8}, {10.0, -20.0}, {200.0, 70.0}] do
        {alt, az} = Astro.alt_az(ra, dec, @lat, lst())
        {ra2, dec2} = Astro.radec_from_altaz(alt, az, @lat, lst())
        assert Astro.separation_radec(ra, dec, ra2, dec2) < 0.001
      end
    end
  end

  describe "line-up" do
    test "one star: offsets only, like the old one-star sync" do
      truth = %{Model.ideal(@lat) | off_ra: 3.0, off_dec: -2.0}
      {:ok, p, q} = Model.fit([centre(truth, "Vega")], @signs, Model.ideal(@lat))
      assert q.rms_arcmin < 0.01
      assert_in_delta p.off_ra, 3.0, 0.01
      assert_in_delta p.off_dec, -2.0, 0.01
    end

    for {label, truth} <- [
          {"a bit off (5°)", %{axis_alt: 41.0, axis_az: 4.0, off_ra: 2.0, off_dec: 1.0}},
          {"30° off", %{axis_alt: 50.0, axis_az: 330.0, off_ra: -20.0, off_dec: 7.0}},
          {"72° off in azimuth", %{axis_alt: 35.0, axis_az: 72.0, off_ra: 14.0, off_dec: -6.5}},
          {"90° off, pointing east", %{axis_alt: 20.0, axis_az: 90.0, off_ra: 0.0, off_dec: 0.0}}
        ] do
      @truth truth
      test "three stars recover a mount #{label} and a goto lands" do
        truth = @truth
        samples = Enum.map(["Vega", "Altair", "Arcturus"], &centre(truth, &1))
        {:ok, p, q} = Model.fit(samples, @signs, Model.ideal(@lat))
        assert q.rms_arcmin < 0.1, "rms #{q.rms_arcmin}′"

        # now go to Saturn-ish (a point we did not sample) 40 minutes later
        later = DateTime.add(@now, 40 * 60, :second)
        {ra, dec} = {23.5 * 15, -8.0}
        {alt, az} = Astro.alt_az(ra, dec, @lat, lst(later))
        {r, d} = Model.encoders(p, @signs, alt, az)
        # where the real mount ends up with those encoders
        {alt_true, az_true} = Model.altaz(truth, @signs, r, d)
        miss = Astro.separation(Astro.altaz_vec(alt, az), Astro.altaz_vec(alt_true, az_true)) * 60
        assert miss < 1.0, "missed by #{miss}′"
      end
    end

    test "two stars is enough for a fix, three tells you how good it is" do
      truth = %{axis_alt: 45.0, axis_az: 20.0, off_ra: 5.0, off_dec: -3.0}
      {:ok, p2, _} = Model.fit(Enum.map(["Vega", "Arcturus"], &centre(truth, &1)), @signs, Model.ideal(@lat))
      assert Model.axis_error(p2, @lat) |> Kernel.-(Model.axis_error(truth, @lat)) |> abs() < 0.5
      {:ok, _p3, q3} = Model.fit(Enum.map(["Vega", "Arcturus", "Fomalhaut"], &centre(truth, &1)), @signs, Model.ideal(@lat))
      assert length(q3.residuals_arcmin) == 3
    end

    test "a sloppy centring shows up as the worst residual, not a wrong axis" do
      truth = %{axis_alt: 40.0, axis_az: 10.0, off_ra: 1.0, off_dec: 0.5}
      good = Enum.map(["Vega", "Altair", "Arcturus", "Fomalhaut"], &centre(truth, &1))
      [first | rest] = good
      sloppy = %{first | theta_dec: first.theta_dec + 0.5}
      {:ok, _p, q} = Model.fit([sloppy | rest], @signs, Model.ideal(@lat))
      assert q.worst_arcmin > 10
      assert hd(q.residuals_arcmin) == Enum.max(q.residuals_arcmin)
    end

    test "axis error reads in degrees from the pole" do
      assert_in_delta Model.axis_error(Model.ideal(@lat), @lat), 0.0, 1.0e-4
      assert Model.axis_error(%{axis_alt: @lat, axis_az: 10.0, off_ra: 0.0, off_dec: 0.0}, @lat) < 10.0
    end
  end
end
