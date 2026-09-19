defmodule Controller.Optical.Axis3D do
  @moduledoc """
  The axis in space, from one camera and a sweep of known angles.

  Every tracked spot on the moving body rides a circle around the axis; the
  camera sees an arc of that circle. With the turn angle known at every
  frame (the encoders say so), the arcs' curvature pins the axis down in
  depth as well as in the picture — a single-axis "turntable" calibration.

  Camera: pinhole, x right, y down, z forward, focal length from the field
  of view. Axis: unit direction `a` (two angles) through a point `c` at
  depth 1 on the ray through image point (u0, v0) — depth is the one thing
  a lone camera cannot scale, so everything is in units of the distance to
  `c`. Each spot: height along the axis, radius, phase. Levenberg–Marquardt
  over all of it; the margins of error are 1σ from the covariance at the
  solution, plus a bootstrap over the spots as a sanity check.
  """

  alias Controller.Optical.Fit

  @deg :math.pi() / 180

  @type camera :: %{f: float, cx: float, cy: float}

  @doc "Pinhole camera for a frame of `w`×`h` and a horizontal field of view in degrees."
  def camera(w, h, hfov_deg), do: %{f: w / 2 / :math.tan(hfov_deg * @deg / 2), cx: w / 2, cy: h / 2}

  @doc """
  Fit the axis to trajectories at `angles_deg` (one per frame, same order).

  Separable: for a given axis, each spot's circle (height, radius, phase) is
  its own tiny least-squares problem, so the outer search is over just the
  four axis numbers and the inner solves are cheap and independent.

  Returns `{:ok, %{dir, point, image_angle_deg, image_angle_sd_deg, tilt_deg,
  tilt_sd_deg, bootstrap_sd_deg, rms_px, n, sense}}` or `{:error, why}`.
  """
  def fit(trajectories, angles_deg, cam, opts \\ []) when length(trajectories) >= 4 do
    n_frames = length(angles_deg)
    tracks = Enum.filter(trajectories, &(length(&1.points) == n_frames))

    if length(tracks) < 4 do
      {:error, :too_few_tracks}
    else
      thetas = Enum.map(angles_deg, &(&1 * @deg))
      x0 = initial_axis(tracks, cam)

      # try both senses of rotation, keep the better
      {res, sense} =
        for sense <- [1.0, -1.0] do
          {Fit.lm(&outer_residuals(&1, tracks, thetas, cam, sense), x0, max_iter: opts[:max_iter] || 40), sense}
        end
        |> Enum.min_by(fn {res, _} -> res.cost end)

      [az, el, u0, v0] = res.x
      dir = dir_from(az, el)
      point = point_from(u0, v0, cam)
      rms = :math.sqrt(res.cost / max(length(res.residuals), 1))
      sd_az = Fit.sd(res.cov, 0)
      sd_el = Fit.sd(res.cov, 1)
      boot = if opts[:bootstrap] == false, do: nil, else: bootstrap(tracks, thetas, cam, sense, res.x)

      {:ok,
       %{
         dir: dir,
         point: point,
         sense: sense,
         n: length(tracks),
         rms_px: rms,
         image_angle_deg: image_angle(dir),
         tilt_deg: tilt(dir),
         image_angle_sd_deg: sd_az && sd_az / @deg,
         tilt_sd_deg: sd_el && sd_el / @deg,
         bootstrap_sd_deg: boot,
         iterations: res.iterations
       }}
    end
  end

  def fit(_, _, _, _), do: {:error, :too_few_tracks}

  @doc "Angle in degrees between two fitted axes (90° for a healthy mount)."
  def angle_between(%{dir: a}, %{dir: b}), do: :math.acos(min(max(dot(a, b), -1.0), 1.0)) / @deg

  # -- model -------------------------------------------------------------------------

  # residuals for an axis guess, with every spot's own circle solved for that axis
  defp outer_residuals([az, el, u0, v0], tracks, thetas, cam, sense) do
    a = dir_from(az, el)
    c = point_from(u0, v0, cam)
    {e1, e2} = basis(a)

    Enum.flat_map(tracks, fn track ->
      x0 = spot_initial(track, a, c, e1, e2, cam)
      res = Fit.lm(&spot_residuals(&1, track, thetas, a, c, e1, e2, cam, sense), x0, max_iter: 20)
      res.residuals
    end)
  end

  # one spot: [h, r, phi] → image residuals across the sweep
  defp spot_residuals([h, r, phi], %{points: pts}, thetas, a, c, e1, e2, cam, sense) do
    base = add(c, scale(a, h))

    Enum.zip(pts, thetas)
    |> Enum.flat_map(fn {{u, v}, th} ->
      ang = phi + sense * th
      x = add(base, add(scale(e1, r * :math.cos(ang)), scale(e2, r * :math.sin(ang))))
      {pu, pv} = project(x, cam)
      [pu - u, pv - v]
    end)
  end

  # back-project the spot's first position at depth 1 and read off its circle
  defp spot_initial(%{points: [{u, v} | _]}, a, c, e1, e2, cam) do
    x = {(u - cam.cx) / cam.f, (v - cam.cy) / cam.f, 1.0}
    d = sub(x, c)
    h = dot(d, a)
    rad = sub(d, scale(a, h))
    [h, max(norm(rad), 0.02), :math.atan2(dot(rad, e2), dot(rad, e1))]
  end

  # a start in the right neighbourhood: the axis in the image plane at right
  # angles to the mean motion, through the centroid, tipped a little out of
  # the plane so the search has a gradient in depth
  defp initial_axis(tracks, cam) do
    firsts = Enum.map(tracks, fn %{points: [p | _]} -> p end)
    lasts = Enum.map(tracks, fn %{points: pts} -> List.last(pts) end)
    n = length(tracks)
    cxu = Enum.sum(Enum.map(firsts, &elem(&1, 0))) / n
    cxv = Enum.sum(Enum.map(firsts, &elem(&1, 1))) / n
    mdx = Enum.zip(firsts, lasts) |> Enum.map(fn {{p, _}, {q, _}} -> q - p end) |> Enum.sum() |> Kernel./(n)
    mdy = Enum.zip(firsts, lasts) |> Enum.map(fn {{_, p}, {_, q}} -> q - p end) |> Enum.sum() |> Kernel./(n)
    len = :math.sqrt(mdx * mdx + mdy * mdy) + 1.0e-9
    [:math.atan2(mdx / len, -mdy / len), 0.3, cxu, cxv]
    |> then(fn [az, el, u, v] -> [az, el, u / 1, v / 1] end)
    |> then(fn x -> ensure_cam(x, cam) end)
  end

  defp ensure_cam(x, _cam), do: x

  defp bootstrap(tracks, thetas, cam, sense, x_full) do
    :rand.seed(:exsss, {7, 11, 13})
    n = length(tracks)
    keep = max(4, div(n * 7, 10))

    dirs =
      for _ <- 1..4 do
        sub_tracks = Enum.take_random(tracks, keep)
        res = Fit.lm(&outer_residuals(&1, sub_tracks, thetas, cam, sense), x_full, max_iter: 15)
        [baz, bel | _] = res.x
        dir_from(baz, bel)
      end

    mean = dirs |> Enum.reduce({0.0, 0.0, 0.0}, &add/2) |> then(fn v -> scale(v, 1 / max(norm(v), 1.0e-9)) end)
    spread = Enum.map(dirs, fn d -> :math.acos(min(max(abs(dot(d, mean)), -1.0), 1.0)) / @deg end)
    :math.sqrt(Enum.sum(Enum.map(spread, &(&1 * &1))) / length(spread))
  end

  # -- geometry helpers --------------------------------------------------------------

  # az around the optical axis (in the image plane), el toward the camera
  defp dir_from(az, el), do: {:math.cos(el) * :math.cos(az), :math.cos(el) * :math.sin(az), :math.sin(el)}
  defp point_from(u0, v0, cam), do: {(u0 - cam.cx) / cam.f, (v0 - cam.cy) / cam.f, 1.0}

  # in-picture direction of the axis (undirected, 0..180, y down) and its tilt out of the image plane
  defp image_angle({x, y, _}) do
    a = :math.atan2(y, x) / @deg
    if a < 0, do: a + 180, else: a
  end

  defp tilt({x, y, z}), do: :math.atan2(z, :math.sqrt(x * x + y * y)) / @deg

  defp basis(a) do
    helper = if abs(elem(a, 2)) < 0.9, do: {0.0, 0.0, 1.0}, else: {1.0, 0.0, 0.0}
    e1 = cross(a, helper) |> then(&scale(&1, 1 / norm(&1)))
    e2 = cross(a, e1)
    {e1, e2}
  end

  defp project({x, y, z}, cam), do: {cam.f * x / z + cam.cx, cam.f * y / z + cam.cy}

  defp dot({a, b, c}, {d, e, f}), do: a * d + b * e + c * f
  defp add({a, b, c}, {d, e, f}), do: {a + d, b + e, c + f}
  defp sub({a, b, c}, {d, e, f}), do: {a - d, b - e, c - f}
  defp scale({a, b, c}, k), do: {a * k, b * k, c * k}
  defp cross({a, b, c}, {d, e, f}), do: {b * f - c * e, c * d - a * f, a * e - b * d}
  defp norm(v), do: :math.sqrt(dot(v, v))
end
