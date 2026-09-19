defmodule Controller.Optical.Axis3DTest do
  @moduledoc "A synthetic body of spots turning about a known 3-D axis in front of a pinhole camera: the sweep fit must find the axis and say how sure it is."
  use ExUnit.Case, async: true

  alias Controller.Optical.Axis3D

  @deg :math.pi() / 180
  @cam Axis3D.camera(640, 360, 70)

  # spots on a body around axis `a` through point `c`, projected at each angle (with a little pixel noise)
  defp synth(a, c, angles, n, noise) do
    :rand.seed(:exsss, {3, 5, 8})
    {e1, e2} = basis(a)

    spots =
      for _ <- 1..n do
        h = :rand.uniform() * 0.6 - 0.3
        r = 0.1 + :rand.uniform() * 0.35
        phi = :rand.uniform() * 2 * :math.pi()
        {h, r, phi}
      end

    for {h, r, phi} <- spots do
      pts =
        for th <- angles do
          ang = phi + th * @deg
          x = add(add(c, scale(a, h)), add(scale(e1, r * :math.cos(ang)), scale(e2, r * :math.sin(ang))))
          {u, v} = project(x)
          {u + (:rand.uniform() - 0.5) * noise, v + (:rand.uniform() - 0.5) * noise}
        end

      %{points: pts}
    end
  end

  test "an axis at an angle to the camera is recovered from five known positions" do
    a = unit({0.5, -0.7, 0.4})
    c = {0.1, 0.05, 1.0}
    angles = [-6, -3, 0, 3, 6]
    tracks = synth(a, c, angles, 30, 0.6)
    {:ok, fit} = Axis3D.fit(tracks, angles, @cam)
    sep = :math.acos(abs(dot(fit.dir, a))) / @deg
    IO.puts("\n  angled axis: off by #{Float.round(sep, 2)}° · reported ±#{Float.round(fit.bootstrap_sd_deg, 2)}° (boot) ±#{Float.round(fit.tilt_sd_deg || 0.0, 2)}° tilt · rms #{Float.round(fit.rms_px, 2)} px · #{fit.iterations} it")
    assert sep < max(3.0, 3 * fit.bootstrap_sd_deg), "axis off by #{sep}°, margin #{fit.bootstrap_sd_deg}°"
    assert fit.rms_px < 1.0
    assert fit.n == 30
    assert is_number(fit.image_angle_sd_deg)
    refute fit.tilt_ambiguous
    assert fit.bootstrap_sd_deg < 5.0
  end

  test "an axis lying almost across the view is still found, with a wider margin on its tilt" do
    a = unit({0.9, 0.3, 0.05})
    c = {0.0, 0.0, 1.0}
    angles = [-6, -3, 0, 3, 6]
    tracks = synth(a, c, angles, 40, 0.6)
    {:ok, fit} = Axis3D.fit(tracks, angles, @cam)
    sep = :math.acos(abs(dot(fit.dir, a))) / @deg
    true_img = :math.atan2(elem(a, 1), elem(a, 0)) / @deg
    d = abs(fit.image_angle_deg - if(true_img < 0, do: true_img + 180, else: true_img))
    d = min(d, 180 - d)
    IO.puts("  across-view axis: off by #{Float.round(sep, 2)}° · in-picture off #{Float.round(d, 2)}° (reported ±#{Float.round(fit.image_angle_sd_deg || 0.0, 2)}°) · tilt #{Float.round(fit.tilt_deg, 1)}° ±#{Float.round(fit.tilt_sd_deg || 0.0, 1)}° · boot ±#{Float.round(fit.bootstrap_sd_deg, 2)}°")
    assert sep < max(6.0, 3 * fit.bootstrap_sd_deg), "axis off by #{sep}°"
    # the in-picture direction is tight even when depth is not
    assert d < max(3.0, 3 * (fit.image_angle_sd_deg || 1.0))
  end

  test "two perpendicular axes read as 90° apart" do
    a1 = unit({0.5, -0.7, 0.4})
    a2 = unit(cross(a1, {0.0, 0.0, 1.0}))
    angles = [-6, -3, 0, 3, 6]
    {:ok, f1} = Axis3D.fit(synth(a1, {0.1, 0.05, 1.0}, angles, 30, 0.5), angles, @cam, bootstrap: false)
    {:ok, f2} = Axis3D.fit(synth(a2, {0.1, 0.05, 1.0}, angles, 30, 0.5), angles, @cam, bootstrap: false)
    between = Axis3D.angle_between(f1, f2)
    IO.puts("  two axes: #{Float.round(between, 1)}° apart (tilt sds #{Float.round(f1.tilt_sd_deg || 0.0, 1)}°, #{Float.round(f2.tilt_sd_deg || 0.0, 1)}°)")
    assert_in_delta between, 90.0, max(5.0, 3 * ((f1.tilt_sd_deg || 0.0) + (f2.tilt_sd_deg || 0.0)))
  end

  test "the joint fit keeps the axes perpendicular and reads the commanded steps back" do
    a1 = unit({0.5, -0.7, 0.4})
    a2 = unit(cross(a1, {0.0, 0.0, 1.0}))
    angles = [-20, -10, 0, 10, 20]
    ra = synth(a1, {0.1, 0.05, 1.0}, angles, 20, 0.5)
    dec = synth(a2, {0.1, 0.05, 1.0}, angles, 20, 0.5)
    {:ok, f1} = Axis3D.fit(ra, angles, @cam, bootstrap: false)
    {:ok, f2} = Axis3D.fit(dec, angles, @cam, bootstrap: false)
    {:ok, pair} = Axis3D.fit_pair(ra, dec, angles, @cam, polar: f1, dec: f2, max_iter: 15)
    assert_in_delta Axis3D.angle_between(pair.polar, pair.dec), 90.0, 0.01
    assert :math.acos(abs(dot(pair.polar.dir, a1))) / @deg < 3.0
    steps = Axis3D.measured_angles(pair.polar, ra, angles, @cam)
    for s <- steps, do: assert_in_delta(s.measured_deg, s.commanded_deg, 1.0)
  end

  test "too few tracks is an error, not a guess" do
    assert {:error, :too_few_tracks} = Axis3D.fit([%{points: [{1, 1}]}], [0], @cam)
  end

  # -- helpers (mirror the module's geometry) --
  defp project({x, y, z}), do: {@cam.f * x / z + @cam.cx, @cam.f * y / z + @cam.cy}
  defp basis(a) do
    helper = if abs(elem(a, 2)) < 0.9, do: {0.0, 0.0, 1.0}, else: {1.0, 0.0, 0.0}
    e1 = unit(cross(a, helper))
    {e1, cross(a, e1)}
  end
  defp unit(v), do: scale(v, 1 / :math.sqrt(dot(v, v)))
  defp dot({a, b, c}, {d, e, f}), do: a * d + b * e + c * f
  defp add({a, b, c}, {d, e, f}), do: {a + d, b + e, c + f}
  defp scale({a, b, c}, k), do: {a * k, b * k, c * k}
  defp cross({a, b, c}, {d, e, f}), do: {b * f - c * e, c * d - a * f, a * e - b * d}
end
