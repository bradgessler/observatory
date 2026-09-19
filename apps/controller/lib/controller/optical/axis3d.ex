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
  def fit(trajectories, angles_deg, cam, opts \\ [])

  def fit(trajectories, angles_deg, cam, opts) when length(trajectories) >= 4 do
    n_frames = length(angles_deg)
    tracks = Enum.filter(trajectories, &(length(&1.points) == n_frames))

    if length(tracks) < 4 do
      {:error, :too_few_tracks}
    else
      thetas = Enum.map(angles_deg, &(&1 * @deg))
      [az0, el0, u0, v0] = initial_axis(tracks, cam)

      # both senses of rotation and both signs of tilt: a small sweep sees
      # arcs that are nearly straight, and then "toward" and "away" fit
      # equally well — the mirror solution must be tried, and if it is as
      # good, the tilt is not known and we say so
      fits =
        for sense <- [1.0, -1.0], el <- [el0, -el0] do
          {Fit.lm(&outer_residuals(&1, tracks, thetas, cam, sense), [az0, el, u0, v0], max_iter: opts[:max_iter] || 40), sense}
        end
        |> Enum.sort_by(fn {res, _} -> res.cost end)

      {res, sense} = hd(fits)
      [_, el_best | _] = res.x

      mirror_cost =
        fits
        |> Enum.filter(fn {r, _} -> [_, e | _] = r.x; e * el_best < 0 end)
        |> Enum.map(fn {r, _} -> r.cost end)
        |> Enum.min(fn -> :infinity end)

      # the mirror fits within 10% as well: the sweep is too small to tell toward from away
      tilt_ambiguous = mirror_cost != :infinity and mirror_cost < res.cost * 1.1

      [az, el, u0, v0] = res.x
      dir = dir_from(az, el)
      point = point_from(u0, v0, cam)
      rms = :math.sqrt(res.cost / max(length(res.residuals), 1))
      sd_az = Fit.sd(res.cov, 0)
      sd_el = if tilt_ambiguous, do: 90.0 * @deg, else: Fit.sd(res.cov, 1)
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
         tilt_ambiguous: tilt_ambiguous,
         bootstrap_sd_deg: boot,
         iterations: res.iterations
       }}
    end
  end

  def fit(_, _, _, _), do: {:error, :too_few_tracks}

  @doc """
  Both axes at once, perpendicular by construction: the polar axis as before,
  the Dec axis as an angle around it in its perpendicular plane, each with its
  own point. Removes the degeneracy a lone axis near the line of sight has.
  Returns `{:ok, %{polar: fit, dec: fit, rms_px}}` with the same fields per
  axis as `fit/4` (bootstrap over both track sets).
  """
  def fit_pair(ra_tracks, dec_tracks, angles_deg, cam, opts \\ []) do
    n = length(angles_deg)
    ra_t = Enum.filter(ra_tracks, &(length(&1.points) == n))
    dec_t = Enum.filter(dec_tracks, &(length(&1.points) == n))

    if length(ra_t) < 4 or length(dec_t) < 4 do
      {:error, :too_few_tracks}
    else
      thetas = Enum.map(angles_deg, &(&1 * @deg))

      # start from the single-axis fits when we have them (their in-picture
      # directions and senses are reliable even when their tilts are not)
      {az0, el0, up0, vp0, sp0} =
        case opts[:polar] do
          %{dir: {x, y, z}, point: {px, py, pz}, sense: s} -> {:math.atan2(y, x), :math.asin(z), cam.f * px / pz + cam.cx, cam.f * py / pz + cam.cy, s}
          _ -> [a, e, u, v] = initial_axis(ra_t, cam); {a, e, u, v, nil}
        end

      {ud0, vd0, sd0} =
        case opts[:dec] do
          %{point: {px, py, pz}, sense: s} -> {cam.f * px / pz + cam.cx, cam.f * py / pz + cam.cy, s}
          _ -> [_, _, u, v] = initial_axis(dec_t, cam); {u, v, nil}
        end

      senses = fn known -> if known, do: [known], else: [1.0, -1.0] end
      els = if opts[:polar] && !opts[:polar][:tilt_ambiguous], do: [el0], else: [el0, -el0]
      starts = for el <- els, phi <- [0.0, 0.5 * :math.pi(), :math.pi(), 1.5 * :math.pi()], do: [az0, el, up0, vp0, ud0, vd0, phi]

      fits =
        for x0 <- starts, sp <- senses.(sp0), sd <- senses.(sd0) do
          res = Fit.lm(&pair_residuals(&1, ra_t, dec_t, thetas, cam, sp, sd), x0, max_iter: opts[:max_iter] || 25)
          {res, sp, sd}
        end
        |> Enum.sort_by(fn {res, _, _} -> res.cost end)

      {res, sp, sd} = hd(fits)
      [az, el, up, vp, ud, vd, phi] = res.x
      p = dir_from(az, el)
      d = dec_from(p, phi)
      rms = :math.sqrt(res.cost / max(length(res.residuals), 1))
      # mirror check on the polar tilt, as for a single axis
      mirror = fits |> Enum.filter(fn {r, _, _} -> [_, e | _] = r.x; e * el < 0 end) |> Enum.map(fn {r, _, _} -> r.cost end) |> Enum.min(fn -> :infinity end)
      ambiguous = mirror != :infinity and mirror < res.cost * 1.1

      mk = fn dir, point, sense, sd_img, sd_tilt ->
        %{
          dir: dir,
          point: point,
          sense: sense,
          n: nil,
          rms_px: rms,
          image_angle_deg: image_angle(dir),
          tilt_deg: tilt(dir),
          image_angle_sd_deg: sd_img,
          tilt_sd_deg: if(ambiguous, do: 90.0, else: sd_tilt),
          tilt_ambiguous: ambiguous,
          bootstrap_sd_deg: nil,
          iterations: res.iterations
        }
      end

      sd_az = Fit.sd(res.cov, 0) && Fit.sd(res.cov, 0) / @deg
      sd_el = Fit.sd(res.cov, 1) && Fit.sd(res.cov, 1) / @deg
      sd_phi = Fit.sd(res.cov, 6) && Fit.sd(res.cov, 6) / @deg

      {:ok,
       %{
         polar: %{mk.(p, point_from(up, vp, cam), sp, sd_az, sd_el) | n: length(ra_t)},
         dec: %{mk.(d, point_from(ud, vd, cam), sd, sd_phi, sd_phi) | n: length(dec_t)},
         rms_px: rms,
         between_deg: 90.0
       }}
    end
  end

  @doc """
  What the camera says each frame's turn actually was: with the axis and every
  spot's circle fixed, the single rotation angle per frame that best fits all
  the spots — compared with what the encoders were commanded. Returns
  `[%{commanded_deg, measured_deg, sd_deg}]`. This is the offset-confirmation
  number: does the hardware do what it was told, as seen from outside.
  """
  def measured_angles(fit, tracks, angles_deg, cam) do
    n = length(angles_deg)
    tracks = Enum.filter(tracks, &(length(&1.points) == n))
    thetas = Enum.map(angles_deg, &(&1 * @deg))
    a = fit.dir
    c = fit.point
    sense = fit.sense
    {e1, e2} = basis(a)

    # each spot's circle under this axis, from the full sweep
    circles =
      Enum.map(tracks, fn track ->
        x0 = spot_initial(track, a, c, e1, e2, cam)
        Fit.lm(&spot_residuals(&1, track, thetas, a, c, e1, e2, cam, sense), x0, max_iter: 20).x
      end)

    for {th, k} <- Enum.with_index(thetas) do
      res =
        Fit.lm(
          fn [t] ->
            Enum.zip(circles, tracks)
            |> Enum.flat_map(fn {[h, r, phi], %{points: pts}} ->
              {u, v} = Enum.at(pts, k)
              ang = phi + sense * t
              x = add(add(c, scale(a, h)), add(scale(e1, r * :math.cos(ang)), scale(e2, r * :math.sin(ang))))
              {pu, pv} = project(x, cam)
              [pu - u, pv - v]
            end)
          end,
          [th],
          max_iter: 15
        )

      [t] = res.x
      %{commanded_deg: Float.round(th / @deg, 2), measured_deg: Float.round(t / @deg, 2), sd_deg: (Fit.sd(res.cov, 0) && Float.round(Fit.sd(res.cov, 0) / @deg, 2)) || nil}
    end
  end

  # the Dec axis: an angle in the plane perpendicular to the polar axis
  defp dec_from(p, phi) do
    {e1, e2} = basis(p)
    add(scale(e1, :math.cos(phi)), scale(e2, :math.sin(phi)))
  end

  defp pair_residuals([az, el, up, vp, ud, vd, phi], ra_t, dec_t, thetas, cam, sp, sd) do
    p = dir_from(az, el)
    d = dec_from(p, phi)
    axis_residuals(p, point_from(up, vp, cam), ra_t, thetas, cam, sp) ++ axis_residuals(d, point_from(ud, vd, cam), dec_t, thetas, cam, sd)
  end

  defp axis_residuals(a, c, tracks, thetas, cam, sense) do
    {e1, e2} = basis(a)

    Enum.flat_map(tracks, fn track ->
      x0 = spot_initial(track, a, c, e1, e2, cam)
      Fit.lm(&spot_residuals(&1, track, thetas, a, c, e1, e2, cam, sense), x0, max_iter: 20).residuals
    end)
  end

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

  # in-picture direction of the axis (undirected, 0..180, y down) and its tilt out
  # of the image plane: positive = the far end points away from the camera
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
