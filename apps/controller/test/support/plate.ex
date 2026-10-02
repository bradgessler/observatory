defmodule Controller.Test.Plate do
  @moduledoc """
  Synthetic photos of the sky for testing the plate solver, in pure Elixir:
  real stars from the index files (`query-starkd`), projected gnomonically
  around a chosen centre with a chosen scale and rotation, drawn as Gaussian
  blobs over a noisy background, written as a binary PGM. No image library.

      stars = Plate.stars(83.82, -5.39, 0.9)
      pgm = Plate.render(stars, center: {83.82, -5.39}, fov_deg: 1.0, rotation_deg: 37)

  East is left and north up at rotation 0, as the sky looks with the naked
  eye; `rotation_deg` turns the field counter-clockwise (north toward east),
  `mirror: true` flips it the way a star diagonal does.
  """

  @deg :math.pi() / 180

  def index_dir, do: Path.join([System.user_home!(), ".observatory", "astrometry"])
  def index(n \\ 4107), do: Path.join(index_dir(), "index-#{n}.fits")

  @doc "Can plates be made and solved here? The tools and the index files."
  def available? do
    System.find_executable("query-starkd") != nil and File.regular?(index()) and
      Controller.Sky.Solve.Local.available?()
  end

  @doc "Stars within `radius_deg` of a centre: `[{ra, dec, mag}]`, brightest first."
  def stars(ra, dec, radius_deg, index \\ index()) do
    {out, 0} =
      System.cmd("query-starkd", ["-T", "-r", num(ra), "-d", num(dec), "-R", num(radius_deg), index], stderr_to_stdout: true)

    out
    |> String.split("\n")
    |> Enum.reject(&(String.starts_with?(&1, "#") or not String.contains?(&1, ",")))
    |> Enum.flat_map(fn line ->
      case line |> String.split(",") |> Enum.map(&Float.parse(String.trim(&1))) do
        [{r, _}, {d, _} | rest] ->
          mag = case List.last(rest) do
            {m, _} when m > 0 -> m
            _ -> 10.0
          end

          [{r, d, mag}]

        _ ->
          []
      end
    end)
    |> Enum.sort_by(&elem(&1, 2))
  end

  @doc """
  A PGM (P5) of the stars. Options: `center:` `{ra, dec}` (required),
  `width:` 800, `height:` 600 (pixels), `fov_deg:` 1.0 (across the width),
  `rotation_deg:` 0, `mirror:` false, `sigma_px:` 1.6, `background:` 20,
  `noise:` 3, `seed:` 1.
  """
  def render(stars, opts) do
    {ra0, dec0} = Keyword.fetch!(opts, :center)
    w = Keyword.get(opts, :width, 800)
    h = Keyword.get(opts, :height, 600)
    scale = Keyword.get(opts, :fov_deg, 1.0) * @deg / w
    rot = Keyword.get(opts, :rotation_deg, 0.0) * @deg
    mirror = Keyword.get(opts, :mirror, false)
    sigma = Keyword.get(opts, :sigma_px, 1.6)
    bg = Keyword.get(opts, :background, 20)
    noise = Keyword.get(opts, :noise, 3)
    :rand.seed(:exsss, {Keyword.get(opts, :seed, 1), 7, 11})

    # pixel centres at integers; the image centre sits between them when the size is even
    {cx, cy} = {(w - 1) / 2, (h - 1) / 2}
    m_min = stars |> Enum.map(&elem(&1, 2)) |> Enum.min(fn -> 8.0 end)

    blobs =
      Enum.reduce(stars, %{}, fn {ra, dec, mag}, acc ->
        case project(ra, dec, ra0, dec0) do
          nil ->
            acc

          {xi, eta} ->
            xi = if mirror, do: -xi, else: xi
            {xr, er} = {xi * :math.cos(rot) - eta * :math.sin(rot), xi * :math.sin(rot) + eta * :math.cos(rot)}
            {x, y} = {cx - xr / scale, cy - er / scale}
            # a phone squashes the range: faint stars still show, bright ones do not blind
            peak = 230 * :math.pow(10, -0.25 * (mag - m_min))
            splat(acc, x, y, peak, sigma, w, h)
        end
      end)

    pixels =
      for y <- 0..(h - 1), into: <<>> do
        for x <- 0..(w - 1), into: <<>> do
          v = bg + noise * :rand.normal() + Map.get(blobs, y * w + x, 0.0)
          <<v |> round() |> max(0) |> min(255)>>
        end
      end

    "P5\n#{w} #{h}\n255\n" <> pixels
  end

  defp splat(acc, x, y, peak, sigma, w, h) do
    r = ceil(4 * sigma)

    for px <- (floor(x) - r)..(floor(x) + r), py <- (floor(y) - r)..(floor(y) + r), px >= 0 and px < w and py >= 0 and py < h, reduce: acc do
      acc ->
        d2 = (px - x) * (px - x) + (py - y) * (py - y)
        Map.update(acc, py * w + px, peak * :math.exp(-d2 / (2 * sigma * sigma)), &(&1 + peak * :math.exp(-d2 / (2 * sigma * sigma))))
    end
  end

  # gnomonic: standard coordinates (radians) of a star about the tangent point; nil behind it
  defp project(ra, dec, ra0, dec0) do
    {a, d, a0, d0} = {ra * @deg, dec * @deg, ra0 * @deg, dec0 * @deg}
    cosc = :math.sin(d0) * :math.sin(d) + :math.cos(d0) * :math.cos(d) * :math.cos(a - a0)

    if cosc <= 0 do
      nil
    else
      xi = :math.cos(d) * :math.sin(a - a0) / cosc
      eta = (:math.cos(d0) * :math.sin(d) - :math.sin(d0) * :math.cos(d) * :math.cos(a - a0)) / cosc
      {xi, eta}
    end
  end

  defp num(x), do: :erlang.float_to_binary(x / 1, decimals: 6)
end
