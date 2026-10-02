defmodule Controller.Sky.Model do
  @moduledoc """
  A mount that was set down anyhow: the geometric model behind the star alignment.

  The polar axis points *somewhere* (alt/az, not assumed to be the pole), each
  encoder has a zero offset, and the axis signs come from config. Given that,
  the two encoder angles say exactly where the tube points in the sky, and any
  sky position says where the encoders must go. Fit the four numbers from a
  few stars the person has centred by eye and the mount can be steered in
  sky coordinates without ever having seen Polaris.

  Frame: east-north-up unit vectors. `H` is the hour-angle-like rotation of
  the RA axis (degrees, positive west), `D` the pole distance along the Dec
  axis (positive on the normal side). With an ideal mount (axis at the pole,
  zero offsets) this reduces to the first-order model in `Pointing`.

  Parameters:
      %{axis_alt: deg, axis_az: deg, off_ra: deg, off_dec: deg}
  """

  alias Controller.Sky.Astro

  # centring by eye in a low-power eyepiece: a few arcminutes (residuals are
  # unit-vector differences, so this is in radians)
  @noise_rad 5.0 / 60 * :math.pi() / 180

  @deg :math.pi() / 180
  @type params :: %{axis_alt: float, axis_az: float, off_ra: float, off_dec: float}
  @type signs :: %{ha_sign: integer, dec_sign: integer}

  @doc "The ideal set-up at this latitude: axis on the pole, no offsets."
  def ideal(lat),
    do: %{
      axis_alt: lat / 1,
      axis_az: if(lat >= 0, do: 0.0, else: 180.0),
      off_ra: 0.0,
      off_dec: 0.0
    }

  # -- forward: encoders → sky -----------------------------------------------------

  @doc "Where the tube points (ENU unit vector) for encoder angles in degrees from home."
  def tube_vec(params, signs, theta_ra, theta_dec) do
    h = (signs.ha_sign * theta_ra + params.off_ra) * @deg
    d = (signs.dec_sign * theta_dec + params.off_dec) * @deg
    {p, e, s} = frame(params)
    # u(H) sweeps from the meridian (s) toward the west (−e) as H grows
    u = add(scale(s, :math.cos(h)), scale(e, -:math.sin(h)))
    add(scale(p, :math.cos(d)), scale(u, :math.sin(d)))
  end

  @doc "Alt/az in degrees for encoder angles."
  def altaz(params, signs, theta_ra, theta_dec),
    do: params |> tube_vec(signs, theta_ra, theta_dec) |> Astro.vec_altaz()

  @doc "RA/Dec in degrees for encoder angles, seen from `lat` at sidereal time `lst`."
  def radec(params, signs, theta_ra, theta_dec, lat, lst) do
    {alt, az} = altaz(params, signs, theta_ra, theta_dec)
    Astro.radec_from_altaz(alt, az, lat, lst)
  end

  # -- inverse: sky → encoders -----------------------------------------------------

  @doc """
  Both encoder solutions for an alt/az direction, as `{theta_ra, theta_dec}`
  in degrees from home: the normal side first, then through the pole.
  """
  def solutions(params, signs, alt, az) do
    {p, e, s} = frame(params)
    t = Astro.altaz_vec(alt, az)
    cos_d = dot(p, t)
    perp = sub(t, scale(p, cos_d))
    n = norm(perp)

    {h, d} =
      if n < 1.0e-9 do
        {0.0, if(cos_d >= 0, do: 0.0, else: 180.0)}
      else
        u = scale(perp, 1 / n)
        {:math.atan2(-dot(u, e), dot(u, s)) / @deg, :math.atan2(n, cos_d) / @deg}
      end

    for {hh, dd} <- [{h, d}, {h + 180, -d}] do
      {Astro.norm180((hh - params.off_ra) / signs.ha_sign),
       (dd - params.off_dec) / signs.dec_sign}
    end
  end

  @doc """
  The encoder target for an alt/az: the solution that keeps the RA axis within
  ±90° of home (counterweight below the mount), else the one nearer `near`
  (the current encoders) when given, else the smaller RA swing.
  """
  def encoders(params, signs, alt, az, near \\ nil)

  # `{:stay, {ra, dec}}`: tracking. Never change sides of the pier on its own —
  # the two solutions differ by 180° in RA, and chasing that at 16× is a flip
  # nobody asked for. The nearest solution wins; the soft limits end it.
  def encoders(params, signs, alt, az, {:stay, near}) do
    solutions(params, signs, alt, az)
    |> Enum.min_by(fn {r, d} ->
      abs(Astro.norm180(r - elem(near, 0))) + abs(d - elem(near, 1))
    end)
  end

  def encoders(params, signs, alt, az, near) do
    [a, b] = solutions(params, signs, alt, az)

    cond do
      abs(elem(a, 0)) <= 90 and abs(elem(b, 0)) > 90 ->
        a

      abs(elem(b, 0)) <= 90 and abs(elem(a, 0)) > 90 ->
        b

      near != nil ->
        Enum.min_by([a, b], fn {r, d} -> abs(r - elem(near, 0)) + abs(d - elem(near, 1)) end)

      true ->
        Enum.min_by([a, b], fn {r, _} -> abs(r) end)
    end
  end

  @doc "Encoder target for an RA/Dec at sidereal time `lst` from latitude `lat`."
  def encoders_radec(params, signs, ra, dec, lat, lst, near \\ nil) do
    {alt, az} = Astro.alt_az(ra, dec, lat, lst)
    encoders(params, signs, alt, az, near)
  end

  # -- the counterweight ----------------------------------------------------------

  @doc """
  How high the counterweight sits for RA encoder `theta_ra`, in degrees of RA
  turn above level: negative is below (normal), 0 level, 90 straight up.

  The counterweight shaft *is* the Dec axis. With the tube on the meridian
  (H = 0 or 180) the shaft lies level; at H = ±90 it hangs straight down or
  points straight up. Which of those two is down is not in the pointing: the
  two poses that reach a star see exactly the same sky. `params.cw` says
  which, read from the alignment points by `cw_down/3`.
  """
  def counterweight(params, signs, theta_ra) do
    h = (signs.ha_sign * theta_ra + params.off_ra) * @deg
    Map.get(params, :cw, 1) * :math.asin(:math.sin(h)) / @deg
  end

  @doc """
  Which way the counterweight hangs, from where the alignment points were
  taken (`thetas`: their RA encoders): a person centring a star at the
  eyepiece had it below level, so the sign that puts most of them below is
  the one. 1 when they can't say.
  """
  def cw_down(params, signs, thetas) do
    lean = thetas |> Enum.map(&counterweight(Map.put(params, :cw, 1), signs, &1)) |> Enum.sum()
    if lean > 0, do: -1, else: 1
  end

  @doc """
  The same polar axis written the usual way: a fit can land "over the
  zenith" (altitude above 90 at the opposite azimuth), which is the same
  line in the sky and the same model, but reads as nonsense.
  """
  def canonical(%{axis_alt: alt, axis_az: az} = params) when alt > 90,
    do: %{params | axis_alt: 180 - alt, axis_az: Astro.norm360(az + 180)}

  def canonical(%{axis_alt: alt, axis_az: az} = params) when alt < -90,
    do: %{params | axis_alt: -180 - alt, axis_az: Astro.norm360(az + 180)}

  def canonical(%{axis_az: az} = params), do: %{params | axis_az: Astro.norm360(az)}

  # -- fit: samples → parameters ---------------------------------------------------

  @doc """
  Fit the model to samples `%{theta_ra, theta_dec, alt, az}` (encoders when the
  tube was centred on something whose alt/az at that moment is known). With one
  sample only the offsets move (axis stays at `start`); with two or more all
  four parameters are free. Returns `{:ok, params, %{rms_arcmin, worst_arcmin, residuals_arcmin}}`.
  """
  def fit(samples, signs, start) when is_list(samples) and samples != [] do
    free =
      if length(samples) == 1,
        do: [:off_ra, :off_dec],
        else: [:axis_alt, :axis_az, :off_ra, :off_dec]

    # a badly-placed mount can sit in the wrong basin from the ideal start:
    # try a ring of axis headings and keep the best
    starts =
      if length(samples) >= 2,
        do:
          for(
            az <- [start.axis_az, 45, 90, 135, 180, 225, 270, 315],
            alt <- Enum.uniq([start.axis_alt, 30.0, 60.0]),
            do: %{start | axis_az: az / 1, axis_alt: alt / 1}
          ),
        else: [start]

    # two stars can be satisfied exactly by more than one geometry, and a
    # couple of arcminutes of centring noise makes the wrong one "win" on
    # cost alone; among fits within centring noise of the best, take the one
    # nearest the ideal set-up
    # An unzeroed mount counts from wherever it powered up, so its offsets
    # can be anything: find each start's offsets on a coarse 10° sweep
    # first (cheap: a few thousand evaluations), then refine from there.
    starts = Enum.flat_map(starts, &[&1, sweep_offsets(samples, signs, &1)])
    fits = Enum.map(starts, &lm(samples, signs, &1, free))
    best = fits |> Enum.map(&elem(&1, 1)) |> Enum.min()
    tol = length(samples) * @noise_rad * @noise_rad

    {params, _} =
      fits
      |> Enum.filter(fn {_, cost} -> cost <= best + tol end)
      |> Enum.min_by(fn {p, _} -> axis_distance(p, start) end)

    res = Enum.map(samples, &(residual_deg(params, signs, &1) * 60))
    rms = :math.sqrt(Enum.sum(Enum.map(res, &(&1 * &1))) / length(res))
    {:ok, params, %{rms_arcmin: rms, worst_arcmin: Enum.max(res), residuals_arcmin: res}}
  end

  def fit([], _signs, _start), do: {:error, :no_samples}

  # the offsets (to 10°) that best fit the samples with this start's axis
  defp sweep_offsets(samples, signs, start) do
    for(ra <- 0..350//10, dec <- -180..170//10, do: %{start | off_ra: ra / 1, off_dec: dec / 1})
    |> Enum.min_by(fn p -> Enum.reduce(samples, 0.0, &(&2 + residual_deg(p, signs, &1))) end)
  end

  @doc "Angular error in degrees between the model's tube direction and a sample's true direction."
  def residual_deg(params, signs, %{theta_ra: r, theta_dec: d, alt: alt, az: az}) do
    Astro.separation(tube_vec(params, signs, r, d), Astro.altaz_vec(alt, az))
  end

  @doc "How far the fitted polar axis is from the celestial pole, in degrees."
  def axis_error(params, lat), do: axis_distance(params, ideal(lat))

  @doc "Angle in degrees between two models' polar axes."
  def axis_distance(a, b),
    do:
      Astro.separation(
        Astro.altaz_vec(a.axis_alt, a.axis_az),
        Astro.altaz_vec(b.axis_alt, b.axis_az)
      )

  # Levenberg–Marquardt on the residual vector (three ENU components per
  # sample), numeric Jacobian. Tiny problem; simplicity over speed.
  defp lm(samples, signs, start, free) do
    x0 = Enum.map(free, &Map.fetch!(start, &1))
    f = fn x -> residuals(samples, signs, put(start, free, x)) end
    {x, cost} = lm_loop(f, x0, 1.0e-3, 0, cost(f.(x0)))
    {put(start, free, x), cost}
  end

  defp lm_loop(_f, x, _lambda, iter, cost) when iter >= 60 or cost < 1.0e-14, do: {x, cost}

  defp lm_loop(f, x, lambda, iter, cost) do
    r = f.(x)
    j = jacobian(f, x, r)
    n = length(x)
    jtj = for a <- 0..(n - 1), do: for(b <- 0..(n - 1), do: col_dot(j, a, b))

    jtr =
      for a <- 0..(n - 1),
          do:
            Enum.zip(Enum.map(j, &Enum.at(&1, a)), r)
            |> Enum.map(fn {ja, ri} -> ja * ri end)
            |> Enum.sum()

    damped =
      jtj
      |> Enum.with_index()
      |> Enum.map(fn {row, i} -> List.update_at(row, i, &(&1 * (1 + lambda) + 1.0e-12)) end)

    case solve(damped, Enum.map(jtr, &(-&1))) do
      nil ->
        {x, cost}

      step ->
        x1 = Enum.zip(x, step) |> Enum.map(fn {a, b} -> a + b end)
        c1 = cost(f.(x1))

        cond do
          c1 < cost and Enum.all?(step, &(abs(&1) < 1.0e-9)) -> {x1, c1}
          c1 < cost -> lm_loop(f, x1, max(lambda / 4, 1.0e-9), iter + 1, c1)
          lambda > 1.0e6 -> {x, cost}
          true -> lm_loop(f, x, lambda * 8, iter + 1, cost)
        end
    end
  end

  defp residuals(samples, signs, params) do
    Enum.flat_map(samples, fn %{theta_ra: r, theta_dec: d, alt: alt, az: az} ->
      {mx, my, mz} = tube_vec(params, signs, r, d)
      {tx, ty, tz} = Astro.altaz_vec(alt, az)
      [mx - tx, my - ty, mz - tz]
    end)
  end

  defp cost(r), do: Enum.reduce(r, 0.0, &(&2 + &1 * &1))

  defp jacobian(f, x, r0) do
    h = 1.0e-4

    cols =
      Enum.with_index(x)
      |> Enum.map(fn {_, i} ->
        f.(List.update_at(x, i, &(&1 + h)))
        |> Enum.zip(r0)
        |> Enum.map(fn {a, b} -> (a - b) / h end)
      end)

    # rows = residual index, cols = parameter
    Enum.zip(cols) |> Enum.map(&Tuple.to_list/1)
  end

  defp col_dot(j, a, b),
    do: Enum.reduce(j, 0.0, fn row, acc -> acc + Enum.at(row, a) * Enum.at(row, b) end)

  # Gauss–Jordan with partial pivoting; nil when singular.
  defp solve(a, b) do
    n = length(b)
    m = Enum.zip(a, b) |> Enum.map(fn {row, bi} -> row ++ [bi] end)

    result =
      Enum.reduce_while(0..(n - 1), m, fn i, m ->
        {pivot_row, pivot_idx} =
          m
          |> Enum.drop(i)
          |> Enum.with_index(i)
          |> Enum.max_by(fn {row, _} -> abs(Enum.at(row, i)) end)

        p = Enum.at(pivot_row, i)

        if abs(p) < 1.0e-14 do
          {:halt, nil}
        else
          m = m |> List.replace_at(pivot_idx, Enum.at(m, i)) |> List.replace_at(i, pivot_row)
          prow = Enum.map(pivot_row, &(&1 / p))

          m =
            m
            |> Enum.with_index()
            |> Enum.map(fn {row, k} ->
              if k == i,
                do: prow,
                else:
                  (
                    fct = Enum.at(row, i)
                    Enum.zip(row, prow) |> Enum.map(fn {x, y} -> x - fct * y end)
                  )
            end)

          {:cont, m}
        end
      end)

    result && Enum.map(result, &List.last/1)
  end

  defp put(params, free, x),
    do: Enum.zip(free, x) |> Enum.reduce(params, fn {k, v}, acc -> Map.put(acc, k, v / 1) end)

  # -- geometry --------------------------------------------------------------------

  # p: polar axis; e: the Dec axis at home (east for a north-facing mount);
  # s: from the pole along the meridian toward the zenith side.
  defp frame(params) do
    p = Astro.altaz_vec(params.axis_alt, params.axis_az)
    up = {0.0, 0.0, 1.0}
    e0 = cross(p, up)

    e =
      if norm(e0) < 1.0e-6,
        do: {1.0, 0.0, 0.0},
        else: scale(e0, 1 / norm(e0))

    s = cross(e, p)
    {p, e, s}
  end

  defp dot({a, b, c}, {d, e, f}), do: a * d + b * e + c * f
  defp add({a, b, c}, {d, e, f}), do: {a + d, b + e, c + f}
  defp sub({a, b, c}, {d, e, f}), do: {a - d, b - e, c - f}
  defp scale({a, b, c}, k), do: {a * k, b * k, c * k}
  defp cross({a, b, c}, {d, e, f}), do: {b * f - c * e, c * d - a * f, a * e - b * d}
  defp norm(v), do: :math.sqrt(dot(v, v))
end
