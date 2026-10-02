defmodule Controller.ScopeCamera.Sim do
  @moduledoc """
  A telescope camera on a simulated mount, for trying everything with no
  camera and no sky: sky glow, noise, and a field of stars that moves when
  the mount does and blurs when `defocus` goes up.

  It isn't a real star field (no plate solver would match it), so each frame
  says in a PGM comment where the simulated tube truly points
  (`# sim-sky ra=… dec=…`, from `Controller.Sim.Truth`). A test solver reads
  that back, which is enough to run the whole find-where-it's-pointing loop
  in a test.
  """

  alias Controller.Sim.Truth
  alias Controller.Sky.{Astro, Model, Pointing}

  @w 960
  @h 540

  @doc "One frame for mount `id`: `{:ok, pgm}`. Options: `defocus:` (0 is sharp), `stars:`, `now:`."
  def grab(id, opts \\ []) do
    now = Keyword.get(opts, :now, DateTime.utc_now())
    {ra, dec} = pointing(id, now) || {0.0, 0.0}
    sigma = 1.2 + Keyword.get(opts, :defocus, 0.0) * 2.5
    n = Keyword.get(opts, :stars, 25)

    # the same patch of sky gives the same stars
    :rand.seed(:exsss, {round(ra * 20), round(dec * 20) + 7, 42})
    stars = for _ <- 1..n, do: {:rand.uniform() * (@w - 40) + 20, :rand.uniform() * (@h - 40) + 20, 40 + :rand.uniform() * 200}

    # out of focus, the same light spreads wider and so gets fainter, as it does through a real tube
    dim = 1.2 * 1.2 / (sigma * sigma)
    stars = for {x, y, b} <- stars, do: {x, y, b * dim}

    # each star painted only where it shows (a few sigma around it; past 40 px it's below the noise anyway)
    r = min(ceil(4 * sigma), 40)

    light =
      Enum.reduce(stars, %{}, fn {sx, sy, b}, acc ->
        for y <- max(round(sy) - r, 0)..min(round(sy) + r, @h - 1),
            x <- max(round(sx) - r, 0)..min(round(sx) + r, @w - 1),
            reduce: acc do
          acc ->
            d2 = (x - sx) * (x - sx) + (y - sy) * (y - sy)
            Map.update(acc, y * @w + x, b * :math.exp(-d2 / (2 * sigma * sigma)), &(&1 + b * :math.exp(-d2 / (2 * sigma * sigma))))
        end
      end)

    px =
      for i <- 0..(@w * @h - 1), into: <<>> do
        <<min(round(18 + :rand.uniform(5) + Map.get(light, i, 0.0)), 255)>>
      end

    comment = "# sim-sky ra=#{Float.round(ra * 1.0, 5)} dec=#{Float.round(dec * 1.0, 5)}"
    {:ok, IO.iodata_to_binary(["P5\n", comment, "\n#{@w} #{@h}\n255\n", px])}
  end

  @doc "Where the simulated tube truly points: through the simulator's own truth, zeroed or not."
  def pointing(id, now) do
    with %{} = truth <- Truth.get(id),
         %{axes: %{ra: ra, dec: dec}} <- safe_snapshot(id) do
      site = Pointing.site()
      Model.radec(truth, Pointing.pointing(), ra.degrees, dec.degrees, site.lat, Astro.lst_deg(now, site.lon))
    else
      _ -> nil
    end
  end

  @doc "The pointing a sim frame says it was taken at, or nil."
  def said(pgm) do
    case Regex.run(~r/# sim-sky ra=(-?[\d.]+) dec=(-?[\d.]+)/, binary_part(pgm, 0, min(byte_size(pgm), 200))) do
      [_, ra, dec] -> {String.to_float(ra), String.to_float(dec)}
      _ -> nil
    end
  end

  defp safe_snapshot(id) do
    Mount.snapshot(id)
  catch
    :exit, _ -> nil
  end
end
