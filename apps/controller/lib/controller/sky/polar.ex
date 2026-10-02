defmodule Controller.Sky.Polar do
  @moduledoc """
  How the polar axis really sits, from photos the plate solver has placed.

  Each solved photo is the same kind of observation Star Align collects: the
  encoder angles at that moment and exactly where the tube pointed. Fit
  `Controller.Sky.Model` to them (axis direction plus both encoder offsets)
  and the fitted axis, set against the celestial pole, is the polar
  alignment error: split into altitude and azimuth, it is how far to turn
  which bolt.

      Polar.fit(samples, site: %{lat: 37.9, lon: -122.2}, signs: %{ha_sign: 1, dec_sign: -1})
      #=> {:ok, %{error_deg: 0.94, moves: [%{knob: :altitude, dir: :raise, deg: 0.5, margin_deg: 0.1}, ...], ...}}

  A sample is `%{theta_ra, theta_dec, ra_deg, dec_deg, at}`: encoders in
  degrees from home, the solved J2000 centre, and the UTC moment the pair
  belongs to.

  ## Frames, and the pole of date

  The index files are J2000, and so is everything else here (the catalogs,
  GoTo): RA/Dec are turned into alt/az with the sidereal time of date but no
  precession. The model is fitted in that frame, so it is exactly the one
  GoTo needs. The sky, though, turns about the pole *of date*, about 0.15°
  from the J2000 pole in 2026, and that is where the axis has to point for
  a star to stay put. So the readout compares the fitted axis with the pole
  of date expressed in the same J2000 frame (`Astro.precess_to_j2000/3`),
  at the photos' mean time. Nutation and aberration (under 30″) are
  ignored, and so is refraction (about 1′ at the pole's altitude here),
  which is well inside the margin.

  ## Margin

  The fit's covariance, scaled by how far off one photo's centre can be
  (`noise_arcmin`, 3′ by default: a phone held to an eyepiece is rarely
  square to it) or by the photos' own disagreement when three or more say
  it is worse. Reported as ± two standard deviations, about 95%. Two photos
  fit exactly, so their margin is the assumption alone; a third checks it.
  """

  alias Controller.Sky.{Astro, Model}

  # arcminutes of sky per minute of time
  @sidereal_arcmin_per_min 360 * 60 / (86_164.0905 / 60)
  @noise_arcmin 3.0
  @min_spread_deg 20.0
  @deg :math.pi() / 180

  @doc "The RA-axis swing (degrees) under which the axis is poorly pinned down."
  def min_spread_deg, do: @min_spread_deg

  @doc """
  Fit and report. Options: `site:` `%{lat, lon}` (required), `signs:` the
  axis signs (required), `noise_arcmin:` (#{@noise_arcmin}), `min_spread_deg:`
  (#{@min_spread_deg}), `start:` the model to start from (ideal for the site).

  Returns `{:ok, report}`:

    * `n`, `params` (the fitted model), `signs` (the ones that fit: a wrong RA
      sign shows itself with three photos), `rms_arcmin`, `residuals_arcmin`
    * `spread_deg`, `spread_ok?`: how far the RA axis swung across the photos
    * with two or more photos: `axis` and `pole` (`%{alt, az}`), `error_deg`,
      `alt_error_deg` (+ too high), `east_error_deg` (+ east of the pole,
      degrees of azimuth), `moves` (one per knob, with `margin_deg`),
      `sigma_arcmin` and `noise_from` (`:assumed` or `:photos`),
      `drift_arcmin_per_min` (the worst case, for plain sidereal tracking)
  """
  def fit(samples, opts)

  def fit([], _opts), do: {:error, :no_samples}

  def fit(samples, opts) do
    site = Keyword.fetch!(opts, :site)
    signs = Keyword.fetch!(opts, :signs)
    start = Keyword.get(opts, :start, Model.ideal(site.lat))
    min_spread = Keyword.get(opts, :min_spread_deg, @min_spread_deg)
    model_samples = Enum.map(samples, &model_sample(&1, site))

    {params, q, signs} = fit_model(model_samples, signs, start)
    spread = spread(samples)

    base = %{
      n: length(samples),
      params: params,
      signs: signs,
      rms_arcmin: q.rms_arcmin,
      residuals_arcmin: q.residuals_arcmin,
      spread_deg: spread,
      spread_ok?: spread >= min_spread
    }

    if length(samples) < 2 do
      {:ok, base}
    else
      {:ok,
       Map.merge(
         base,
         polar(samples, model_samples, params, signs, q.residuals_arcmin, site, opts)
       )}
    end
  end

  @doc "A sample in the model's terms: alt/az of the solved centre at its moment (J2000 frame, see the moduledoc)."
  def model_sample(%{theta_ra: r, theta_dec: d, ra_deg: ra, dec_deg: dec, at: at}, site) do
    {alt, az} = Astro.alt_az(ra, dec, site.lat, Astro.lst_deg(at, site.lon))
    %{theta_ra: r / 1, theta_dec: d / 1, alt: alt, az: az}
  end

  # Model.fit, plus what Star Align does about signs, without touching any
  # setting: a wrong RA sign cannot be absorbed by the geometry and shows as
  # degrees of disagreement once there are three photos; a wrong Dec sign is
  # absorbed as an RA offset of 180°, which does not move the axis at all.
  defp fit_model(samples, signs, start) do
    {:ok, p, q} = Model.fit(samples, signs, start)

    {p, q, signs} =
      if length(samples) >= 3 and q.rms_arcmin > 30.0 do
        for(
          h <- [1, -1],
          d <- [1, -1],
          %{ha_sign: h, dec_sign: d} != signs,
          do: %{ha_sign: h, dec_sign: d}
        )
        |> Enum.map(fn sg -> {sg, Model.fit(samples, sg, start)} end)
        |> Enum.min_by(fn {_, {:ok, _, q2}} -> q2.rms_arcmin end)
        |> case do
          {sg, {:ok, p2, q2}} when q2.rms_arcmin < q.rms_arcmin / 5 -> {p2, q2, sg}
          _ -> {p, q, signs}
        end
      else
        {p, q, signs}
      end

    {%{p | off_ra: Astro.norm180(p.off_ra)}, q, signs}
  end

  defp spread([_]), do: 0.0

  defp spread(samples) do
    rs = Enum.map(samples, & &1.theta_ra)
    Enum.max(rs) - Enum.min(rs)
  end

  defp polar(samples, model_samples, params, signs, residuals, site, opts) do
    # the pole the sky turns about, at the photos' mean moment, in the fit's frame
    mid = mean_time(Enum.map(samples, & &1.at))
    lst = Astro.lst_deg(mid, site.lon)
    {pra, pdec} = Astro.precess_to_j2000(0.0, if(site.lat >= 0, do: 90.0, else: -90.0), mid)
    {palt, paz} = Astro.alt_az(pra, pdec, site.lat, lst)
    pole = Astro.altaz_vec(palt, paz)

    # the axis is a line: take the end that points at the visible pole
    a = Astro.altaz_vec(params.axis_alt, params.axis_az)
    a = if dot(a, pole) < 0, do: scale(a, -1.0), else: a
    {aalt, aaz} = Astro.vec_altaz(a)

    alt_err = aalt - palt
    daz = Astro.norm180(aaz - paz)
    # facing the pole, east is +azimuth in the north and −azimuth in the south
    east_err = if site.lat >= 0, do: daz, else: -daz
    error = Astro.separation(a, pole)

    {sigma, from} = sigma_arcmin(residuals, Keyword.get(opts, :noise_arcmin, @noise_arcmin))
    {s_alt, s_az} = axis_sigmas(model_samples, params, signs, sigma)

    %{
      axis: %{alt: aalt, az: aaz},
      pole: %{alt: palt, az: paz},
      error_deg: error,
      alt_error_deg: alt_err,
      east_error_deg: east_err,
      sigma_arcmin: sigma,
      noise_from: from,
      moves: [
        %{
          knob: :altitude,
          dir: if(alt_err > 0, do: :lower, else: :raise),
          deg: abs(alt_err),
          margin_deg: s_alt && 2 * s_alt
        },
        %{
          knob: :azimuth,
          dir: if(east_err > 0, do: :west, else: :east),
          deg: abs(daz),
          margin_deg: s_az && 2 * s_az
        }
      ],
      drift_arcmin_per_min: drift_arcmin_per_min(error)
    }
  end

  @doc """
  The worst-case drift of a star under plain sidereal tracking, arcminutes
  per minute, for a polar axis `error_deg` off the pole: the sky turns about
  the pole, the mount about its own axis, and the difference is the sidereal
  rate times the angle between them. (The model tracker, which runs both
  axes, takes it out; field rotation remains.)
  """
  def drift_arcmin_per_min(error_deg), do: @sidereal_arcmin_per_min * error_deg * @deg

  # One photo's centring noise, per sky axis, arcminutes: the assumption, or
  # what the photos themselves say when they can (three or more) and it is
  # worse. Residuals are angular (two sky axes each); four parameters are fitted.
  defp sigma_arcmin(residuals, prior) do
    dof = 2 * length(residuals) - 4

    from_photos = if dof > 0, do: :math.sqrt(Enum.sum(Enum.map(residuals, &(&1 * &1))) / dof)

    if from_photos && from_photos > prior, do: {from_photos, :photos}, else: {prior / 1, :assumed}
  end

  # Standard deviations of the axis altitude and azimuth (degrees) from the
  # fit's covariance: sigma² (JᵀJ)⁻¹ at the solution, J numeric. nil when the
  # photos cannot pin the axis down at all (no swing between them).
  defp axis_sigmas(model_samples, params, signs, sigma_arcmin) do
    keys = [:axis_alt, :axis_az, :off_ra, :off_dec]
    x0 = Enum.map(keys, &Map.fetch!(params, &1))

    f = fn x ->
      residual_vector(model_samples, signs, Map.merge(params, Map.new(Enum.zip(keys, x))))
    end

    h = 1.0e-3

    # columns: d(residuals)/d(parameter), central differences
    cols =
      for i <- 0..3 do
        up = f.(List.update_at(x0, i, &(&1 + h)))
        down = f.(List.update_at(x0, i, &(&1 - h)))
        Enum.zip_with(up, down, fn a, b -> (a - b) / (2 * h) end)
      end

    jtj = for a <- cols, do: for(b <- cols, do: Enum.zip_with(a, b, &(&1 * &2)) |> Enum.sum())

    case invert(jtj) do
      nil ->
        {nil, nil}

      inv ->
        s = sigma_arcmin / 60 * @deg
        [c00, c11] = [Enum.at(Enum.at(inv, 0), 0), Enum.at(Enum.at(inv, 1), 1)]
        if c00 > 0 and c11 > 0, do: {:math.sqrt(c00) * s, :math.sqrt(c11) * s}, else: {nil, nil}
    end
  end

  defp residual_vector(samples, signs, params) do
    Enum.flat_map(samples, fn %{theta_ra: r, theta_dec: d, alt: alt, az: az} ->
      {mx, my, mz} = Model.tube_vec(params, signs, r, d)
      {tx, ty, tz} = Astro.altaz_vec(alt, az)
      [mx - tx, my - ty, mz - tz]
    end)
  end

  # Gauss–Jordan with partial pivoting; nil when (numerically) singular.
  defp invert(m) do
    n = length(m)
    scale = m |> List.flatten() |> Enum.map(&abs/1) |> Enum.max()

    aug =
      m
      |> Enum.with_index()
      |> Enum.map(fn {row, i} ->
        row ++ for(j <- 0..(n - 1), do: if(i == j, do: 1.0, else: 0.0))
      end)

    Enum.reduce_while(0..(n - 1), aug, fn i, a ->
      {prow, pidx} =
        a
        |> Enum.drop(i)
        |> Enum.with_index(i)
        |> Enum.max_by(fn {row, _} -> abs(Enum.at(row, i)) end)

      p = Enum.at(prow, i)

      if abs(p) <= scale * 1.0e-12 do
        {:halt, nil}
      else
        a = a |> List.replace_at(pidx, Enum.at(a, i)) |> List.replace_at(i, prow)
        prow = Enum.map(prow, &(&1 / p))

        {:cont,
         a
         |> Enum.with_index()
         |> Enum.map(fn {row, k} ->
           if k == i,
             do: prow,
             else:
               (
                 fct = Enum.at(row, i)
                 Enum.zip_with(row, prow, fn x, y -> x - fct * y end)
               )
         end)}
      end
    end)
    |> case do
      nil -> nil
      a -> Enum.map(a, &Enum.drop(&1, n))
    end
  end

  defp mean_time(times) do
    ms = Enum.map(times, &DateTime.to_unix(&1, :millisecond))
    DateTime.from_unix!(div(Enum.sum(ms), length(ms)), :millisecond)
  end

  defp dot({a, b, c}, {d, e, f}), do: a * d + b * e + c * f
  defp scale({a, b, c}, k), do: {a * k, b * k, c * k}
end
