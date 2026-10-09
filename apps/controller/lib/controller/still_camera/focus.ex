defmodule Controller.StillCamera.Focus do
  @moduledoc """
  How wide the stars in a picture are: the one number to focus by.

  A square window is cut round each star. The sky there is the median of the
  window's border, and anything less than two of the border's noise steps
  (and one level) above it is sky and counts for nothing; nor does a lit
  pixel with no lit pixel beside it, which is noise. What is left is the
  star: its middle is its light's centre of gravity, and its size is the
  **half-flux diameter** (HFD), the diameter of the circle about that middle
  that holds half its light. A picture's number is the median over its
  brightest usable stars.

  On made-up Gaussian stars it reads within a few percent of the true width
  from 3 px across upward when the star is bright, and up to a tenth narrow
  when it is faint (the faint skirts of a star are under the floor).

  Half-flux diameter, not the width at half the peak: a star out of focus in
  a Schmidt-Cassegrain is a ring or a fan with a small bright core. The core
  alone still reads narrow (3.7 arcsec, the night this was written); the
  half-flux diameter counts all the light the focus has spread out (8
  arcsec), so it keeps shrinking right up to focus.

  Pure: a grey image and positions in, a number out. Nothing here raises;
  odd input is `nil`. Only the windows are read, and within them the VM's
  own byte search finds the lit pixels, so a dozen stars cost a few
  milliseconds whatever the picture's size.

      {:ok, img} = Controller.ScopeCamera.Image.from_pgm(pgm)
      Focus.measure(img, [%{x: 512, y: 300}, %{x: 90, y: 41}])
      #=> %{hfd_px: 10.4, n: 2}
  """

  alias Controller.ScopeCamera.Image

  @window 64
  @max_stars 12
  @saturation 250
  @hot_px 2
  @border 2

  @doc """
  The median half-flux diameter of the stars at `stars`, in pixels of
  `image`, and how many stars it is the median of: `%{hfd_px: float, n:
  integer}`. `nil` when none could be measured.

  `image` is `%{w, h, px}` (8-bit grey, a byte a pixel, row after row: what
  `Controller.ScopeCamera.Image.from_pgm/1` gives) or the PGM itself.
  `stars` is `[%{x, y}]`, brightest first, as `Controller.ScopeCamera.analyse/2`
  marks them. They are taken in that order until `max_stars:` have been
  measured. Left out:

    * a mark with a `:why` (what `analyse/2` set aside: a bright target's
      face, a known defect);
    * a star with another of `stars` inside its window (the two would be
      measured as one wide star);
    * a star whose window doesn't fit in the picture (too close to the edge);
    * a saturated star (a pixel in its window at `saturation:` or above:
      its top is cut off, so it reads wider than it is);
    * a hot pixel (`hot_px:` or fewer pixels at half its peak or more: no
      star through a telescope is one or two pixels wide);
    * a star whose sky isn't even (the four sides of its window don't
      agree: it sits in the glare of something bright);
    * a star too faint to stand clear of the sky (its brightest pixel less
      than three times the floor above it: its width would be the noise's);
    * a star wider than half its window (it doesn't fit, or it is only noise).

  Options:

    * `window:` the side of the square cut round each star, in pixels (#{@window});
    * `max_stars:` how many stars at most (#{@max_stars});
    * `saturation:` the level at which a pixel counts as saturated (#{@saturation});
    * `hot_px:` the widest core that is still a hot pixel, in pixels (#{@hot_px});
    * `border:` how much of the window's edge the sky is read from, in pixels (#{@border});
    * `scale:` what to multiply the positions by, when the stars were found
      on a smaller copy of the same picture (1.0).
  """
  def measure(image, stars, opts \\ []) do
    with {:ok, img} <- image(image), true <- is_list(stars) do
      scale = Keyword.get(opts, :scale, 1.0)
      reach = div(Keyword.get(opts, :window, @window), 2)

      # pixel centres: 0 in a smaller copy is the middle of its first pixel, not the picture's corner
      at =
        stars
        |> Enum.filter(&mark?/1)
        |> Enum.map(&{(&1.x + 0.5) * scale - 0.5, (&1.y + 0.5) * scale - 0.5})
        |> Enum.uniq()

      hfds =
        at
        |> Stream.reject(fn {x, y} = one ->
          Enum.any?(at, fn {ox, oy} = other ->
            other != one and abs(ox - x) <= reach and abs(oy - y) <= reach
          end)
        end)
        |> Stream.map(fn {x, y} -> star(img, x, y, opts) end)
        |> Stream.filter(&is_map/1)
        |> Enum.take(Keyword.get(opts, :max_stars, @max_stars))
        |> Enum.map(& &1.hfd_px)

      if hfds == [], do: nil, else: %{hfd_px: median(hfds), n: length(hfds)}
    else
      _ -> nil
    end
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end

  @doc """
  One star: the window round (`x`, `y`), measured. `%{hfd_px, x, y, peak,
  flux}` (its half-flux diameter, the middle it was found to have, its
  brightest pixel, its light above the sky), or `nil` when it is left out
  (see `measure/3`, whose options this takes).
  """
  def star(image, x, y, opts \\ []) do
    with {:ok, img} <- image(image), true <- is_number(x) and is_number(y) do
      cfg = %{
        size: Keyword.get(opts, :window, @window),
        saturation: Keyword.get(opts, :saturation, @saturation),
        hot_px: Keyword.get(opts, :hot_px, @hot_px),
        border: Keyword.get(opts, :border, @border)
      }

      if is_integer(cfg.size) and cfg.size >= 8 and is_integer(cfg.border) and cfg.border >= 1 and
           4 * cfg.border <= cfg.size,
         do: window(img, x, y, cfg, 1)
    else
      _ -> nil
    end
  rescue
    _ -> nil
  catch
    _, _ -> nil
  end

  @doc """
  How much sky one pixel covers, in arcseconds, on a picture `width_px` wide
  that shows the whole width of a sensor `sensor_mm` wide behind `focal_mm`
  of focal length. `nil` unless all three are positive numbers.

      Focus.arcsec_per_px(2032, 23.5, 3000)
      #=> 0.795
  """
  def arcsec_per_px(focal_mm, sensor_mm, width_px)
      when is_number(focal_mm) and is_number(sensor_mm) and is_number(width_px) and focal_mm > 0 and
             sensor_mm > 0 and width_px > 0,
      do: 206_264.806 * sensor_mm / (focal_mm * width_px)

  def arcsec_per_px(_, _, _), do: nil

  # -- one window ---------------------------------------------------------------------------------

  # How far off its window's middle a star may sit before the window is cut again round it.
  @off_centre 3
  # How far a star's brightest pixel must stand above the sky, in floors (the level under which
  # light counts as sky): fainter than that, its width would be the noise's, not its own.
  @clear 3

  # The window round (x, y). When the star turns out to sit well off its middle (a position from a
  # smaller copy, or two specks that were taken for one), the window is cut once more round where
  # the star really is, so the sky is read the same distance out on every side.
  defp window(%{w: w, h: h, px: px} = img, x, y, %{size: size, border: b} = cfg, again) do
    half = div(size, 2)
    x0 = round(x) - half
    y0 = round(y) - half

    if x0 >= 0 and y0 >= 0 and x0 + size <= w and y0 + size <= h do
      row = fn j -> (y0 + j) * w + x0 end
      # the border, side by side: the rows at the top and the bottom, the ends of the rows between
      sides = [
        for(j <- 0..(b - 1), v <- :binary.bin_to_list(px, row.(j), size), do: v),
        for(j <- (size - b)..(size - 1), v <- :binary.bin_to_list(px, row.(j), size), do: v),
        for(j <- b..(size - b - 1), v <- :binary.bin_to_list(px, row.(j), b), do: v),
        for(j <- b..(size - b - 1), v <- :binary.bin_to_list(px, row.(j) + size - b, b), do: v)
      ]

      edge = Enum.concat(sides)
      sky = median(edge)
      noise = noise(edge, sky, 3)
      {low, high} = sides |> Enum.map(&median/1) |> Enum.min_max()

      floor = 2 * noise + 1

      # every pixel standing clear of the sky, found a row at a time by the VM's byte search
      lit =
        with true <- high - low <= 1 + noise / 2,
             pattern when pattern != nil <- at_least(sky + floor) do
          for(
            j <- 0..(size - 1),
            from = row.(j),
            {pos, 1} <- :binary.matches(px, pattern, scope: {from, size}),
            do: {pos - from, j, :binary.at(px, pos) - sky}
          )
          |> together()
        else
          _ -> []
        end

      top = Enum.reduce(lit, 0, fn {_, _, f}, m -> max(f, m) end)

      if top >= @clear * floor and top + sky < cfg.saturation do
        flux = Enum.reduce(lit, 0, fn {_, _, f}, s -> s + f end)
        {{cx, cy}, radius} = settle(lit, flux)

        if again > 0 and (abs(cx - half) > @off_centre or abs(cy - half) > @off_centre) do
          window(img, x0 + cx, y0 + cy, cfg, again - 1)
        else
          core = Enum.count(lit, fn {_, _, f} -> 2 * f >= top end)

          if core > cfg.hot_px and 2 * radius <= half,
            do: %{hfd_px: 2 * radius, x: x0 + cx, y: y0 + cy, peak: round(top + sky), flux: flux}
        end
      end
    end
  end

  # The star's middle, and the radius about it that holds half the light. The middle is the lit
  # pixels' centre of gravity. A few noise pixels far out in the window pull that off a small sharp
  # star, and a star measured about the wrong middle reads wide; so the middle is taken again, twice,
  # from only the light within three half-flux radii of where it was put. The size still counts all
  # the light: a ring far out from a bright core is the star's, and is what being out of focus is.
  defp settle(lit, flux) do
    first = centre(lit)

    Enum.reduce(1..2, {first, half_flux_radius(lit, first, flux)}, fn _, {{cx, cy}, radius} ->
      reach = max(3 * radius, 2.0)

      case Enum.filter(lit, fn {i, j, _} ->
             (i - cx) * (i - cx) + (j - cy) * (j - cy) <= reach * reach
           end) do
        # nothing that far out (or nothing at all): the middle stands
        near when near == [] or length(near) == length(lit) -> {{cx, cy}, radius}
        near -> near |> centre() |> then(&{&1, half_flux_radius(lit, &1, flux)})
      end
    end)
  end

  defp centre(lit) do
    flux = Enum.reduce(lit, 0, fn {_, _, f}, s -> s + f end)

    {Enum.reduce(lit, 0, fn {i, _, f}, s -> s + i * f end) / flux,
     Enum.reduce(lit, 0, fn {_, j, f}, s -> s + j * f end) / flux}
  end

  # A lit pixel with no lit pixel beside it is noise: one in a few hundred sky pixels strays above
  # the floor, all over the window, and counted as the star's light they would widen a sharp faint
  # star by half. A star's own pixels, a ring's too, have neighbours.
  defp together(lit) do
    set = MapSet.new(lit, fn {i, j, _} -> {i, j} end)

    Enum.filter(lit, fn {i, j, _} ->
      Enum.any?([{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}], fn {di,
                                                                                            dj} ->
        MapSet.member?(set, {i + di, j + dj})
      end)
    end)
  end

  # The radius about (cx, cy) inside which half the light falls: pixels nearest first, their light
  # added up until half is reached, and the last step shared out between that pixel and the one
  # before it (so the number moves smoothly as the focus does, not a pixel's distance at a time).
  defp half_flux_radius(lit, {cx, cy}, flux) do
    lit
    |> Enum.map(fn {i, j, f} -> {:math.sqrt((i - cx) * (i - cx) + (j - cy) * (j - cy)), f} end)
    |> Enum.sort()
    |> Enum.reduce_while({0.0, 0}, fn {r, f}, {r0, sum} ->
      if 2 * (sum + f) >= flux,
        do: {:halt, r0 + (r - r0) * (flux / 2 - sum) / f},
        else: {:cont, {r, sum + f}}
    end)
  end

  # The border's standard deviation. A neighbour's light lying on the border would pass for noise
  # and raise the floor under the star, so what stands more than three deviations off is left out
  # and it is taken again (a few times at most).
  defp noise(values, _sky, 0), do: deviation(values)

  defp noise(values, sky, rounds) do
    s = deviation(values)

    case Enum.filter(values, &(abs(&1 - sky) <= 3 * s)) do
      kept when kept == [] or length(kept) == length(values) -> s
      kept -> noise(kept, sky, rounds - 1)
    end
  end

  defp deviation(values) do
    n = length(values)
    mean = Enum.sum(values) / n
    :math.sqrt(Enum.reduce(values, 0, fn v, s -> s + (v - mean) * (v - mean) end) / n)
  end

  defp median(values) do
    sorted = Enum.sort(values)
    n = length(sorted)

    if rem(n, 2) == 1,
      do: Enum.at(sorted, div(n, 2)),
      else: (Enum.at(sorted, div(n, 2) - 1) + Enum.at(sorted, div(n, 2))) / 2
  end

  # every byte value at `level` or above, as one search pattern; nil when no byte is that bright
  defp at_least(level) do
    case max(ceil(level), 0) do
      v when v > 255 -> nil
      v -> :binary.compile_pattern(for(b <- v..255, do: <<b>>))
    end
  end

  # -- what comes in ------------------------------------------------------------------------------

  defp image(%{w: w, h: h, px: px} = img)
       when is_integer(w) and is_integer(h) and w > 0 and h > 0 and is_binary(px) and
              byte_size(px) >= w * h,
       do: {:ok, img}

  defp image(pgm) when is_binary(pgm), do: Image.from_pgm(pgm)
  defp image(_), do: :error

  defp mark?(%{x: x, y: y} = mark),
    do: is_number(x) and is_number(y) and Map.get(mark, :why) == nil

  defp mark?(_), do: false
end
