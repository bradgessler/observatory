defmodule Controller.ScopeCamera.Image do
  @moduledoc """
  A frame from the telescope camera, as 8-bit gray: `%{w, h, px}` with `px`
  one byte per pixel, row after row. What the focus page and the solver need
  from it, in plain Elixir (the frame is already small and gray when it gets
  here: ffmpeg scales and converts it in C).

      {:ok, img} = Image.from_pgm(pgm)
      Image.stats(img)          # %{background, noise, max, saturated}
      Image.stars(img)          # [%{x, y, peak, flux, hfr}], brightest first
      Image.png(Image.stretch(img))

  **HFR** (half-flux radius) is how focus is measured: the radius, in
  pixels, inside which half a star's light falls. A sharp star is a small
  number; turning the focuser the wrong way makes it grow.
  """

  import Bitwise

  # -- PGM in and out -------------------------------------------------------------------

  @doc "An 8-bit binary PGM (`P5`)."
  def from_pgm(<<"P5", rest::binary>>) do
    case header(rest, []) do
      {[w, h, 255], pixels} when byte_size(pixels) >= w * h -> {:ok, %{w: w, h: h, px: binary_part(pixels, 0, w * h)}}
      _ -> {:error, :unsupported_image}
    end
  end

  def from_pgm(_), do: {:error, :unsupported_image}

  defp header(bin, nums) when length(nums) == 3, do: {Enum.reverse(nums), bin}
  defp header(<<c, rest::binary>>, nums) when c in ~c" \t\r\n", do: header(rest, nums)
  defp header(<<"#", rest::binary>>, nums), do: header(skip_line(rest), nums)

  defp header(bin, nums) do
    case Integer.parse(bin) do
      {n, <<_ws, rest::binary>>} when length(nums) == 2 -> header(rest, [n | nums])
      {n, rest} -> header(rest, [n | nums])
      :error -> {[], bin}
    end
  end

  defp skip_line(<<"\n", rest::binary>>), do: rest
  defp skip_line(<<_, rest::binary>>), do: skip_line(rest)
  defp skip_line(<<>>), do: <<>>

  @doc "As an 8-bit binary PGM, for the solver."
  def pgm(%{w: w, h: h, px: px}), do: IO.iodata_to_binary(["P5\n#{w} #{h}\n255\n", px])

  # -- how bright, how noisy ---------------------------------------------------------------

  @doc """
  The sky background (median), its noise, the brightest pixel, the share of
  pixels at 255, and the background patch by patch (`:patches`).

  The sky isn't flat. A webcam-style camera corrects its own lens's
  vignetting and lifts the corners even with the cap on; the Moon or a town
  lifts one side. So the background is also measured on a grid of patches
  (16 × 9), and the noise is how far pixels stray from their own patch's
  level, not from the whole frame's. Everything is read from samples (every
  4th pixel of every 4th row, and about 20,000 for the whole-frame numbers):
  one step of the loop per sample, not per pixel, because a Pi 3 runs Elixir
  without a JIT and a frame is half a million pixels.

  The noise is at least one level: a camera that smooths its own noise
  hands back frames flatter than any real sky, and a threshold a fraction of
  a level above the background would light up every gentle gradient.
  """
  def stats(%{px: px} = img) do
    skip = max(div(byte_size(px), 20_000), 1) - 1
    sample = for(<<p, _::binary-size(^skip) <- px>>, do: p) |> Enum.sort()
    n = length(sample)
    patches = patches(img, {16, 9})

    %{
      background: Enum.at(sample, div(n, 2)) || 0,
      noise: max(patches.mad * 1.4826, 1.0),
      max: List.last(sample) || 0,
      saturated: Enum.count(sample, &(&1 >= 255)) / max(n, 1),
      patches: patches
    }
  end

  # The frame cut into a grid: each patch's median, the boundaries (so a
  # pixel can find its patch), and, over every sample, how far a pixel sits
  # from its own patch's median: the middle of that (the noise) and the
  # 95th percentile above it (more than that lit means more than 5% lit).
  defp patches(%{w: w, h: h, px: px}, {cols, rows}) do
    cols = max(min(cols, w), 1)
    rows = max(min(rows, h), 1)
    xb = for i <- 0..cols, do: div(i * w, cols)
    yb = for i <- 0..rows, do: div(i * h, rows)

    tiles =
      for {y0, y1} <- Enum.zip(yb, tl(yb)), {x0, x1} <- Enum.zip(xb, tl(xb)) do
        len = x1 - x0
        skip = if len >= 8, do: 3, else: 0
        ystep = if y1 - y0 >= 8, do: 4, else: 1

        samples =
          for y <- y0..(y1 - 1)//ystep, len > 0, <<p, _::binary-size(^skip) <- binary_part(px, y * w + x0, len)>>, do: p

        med = samples |> Enum.sort() |> Enum.at(div(length(samples), 2)) || 0
        {med, Enum.map(samples, &(&1 - med))}
      end

    resid = tiles |> Enum.flat_map(&elem(&1, 1)) |> Enum.sort()
    n = length(resid)
    mad = resid |> Enum.map(&abs/1) |> Enum.sort() |> Enum.at(div(n, 2)) || 0

    %{
      cols: cols,
      rows: rows,
      xb: List.to_tuple(xb),
      yb: List.to_tuple(yb),
      level: tiles |> Enum.map(&elem(&1, 0)) |> List.to_tuple(),
      mad: mad,
      lit95: Enum.at(resid, div(n * 95, 100)) || 0
    }
  end

  @doc "The background where (`x`, `y`) is: its patch's median."
  def background_at(%{patches: p}, x, y), do: elem(p.level, find_band(p.yb, y, 0) * p.cols + find_band(p.xb, x, 0))
  def background_at(%{background: bg}, _x, _y), do: bg

  defp find_band(bounds, v, i) do
    if i + 2 < tuple_size(bounds) and v >= elem(bounds, i + 1), do: find_band(bounds, v, i + 1), else: i
  end

  # a dark sky's background is drawn this bright (of 255): its grain shows the camera is alive
  @sky_floor 28

  @doc """
  For looking at on a phone, as a table of 256 levels (`png/2` takes it as
  the image's palette, so the frame itself is never rewritten).

  The background is drawn **at least as bright as it really is**, never
  darker: a bright, even picture (a light shone straight in, the sensor
  bare under a lamp) shows bright, not black. A dark sky's background is
  lifted to a dim grey (#{@sky_floor} of 255), so its grain says the
  camera is working. Above the background, anything up to 25 noise steps
  brighter is spread to white on a gentle curve, so faint stars show.

  With `lo:` and `hi:` given, it's the plain stretch instead: `lo` black,
  `hi` white (a star's close-up).
  """
  def curve(stats, opts \\ []) do
    if Keyword.has_key?(opts, :lo) do
      lo = opts[:lo]
      ramp(lo, Keyword.get(opts, :hi, lo + 8), 0, 255, fn _ -> 0 end)
    else
      b = stats.background
      n = stats.noise
      # the background's own level, or the sky floor; what's darker goes from black up to it
      shown = max(b, @sky_floor)
      lo = if b >= @sky_floor, do: 0, else: max(b - 3 * n, 0)
      hi = min(max(b + 25 * n, b + 8), 255)
      below = fn p -> if p <= lo, do: 0, else: round((p - lo) / max(b - lo, 1) * shown) end
      ramp(b, hi, shown, 255, below)
    end
  end

  # from `lo` (drawn `from`) to `hi` (drawn `to`) on a curve that lifts the faint end; `below` draws what's under `lo`
  defp ramp(lo, hi, from, to, below) do
    span = max(hi - lo, 1)

    0..255
    |> Enum.map(fn
      p when p < lo -> below.(p)
      p -> round(from + :math.pow(min((p - lo) / span, 1.0), 0.5) * (to - from))
    end)
    |> List.to_tuple()
  end

  @doc "The frame with `curve/2` applied to every pixel (for small crops; a whole frame goes through `png(img, curve: ...)`)."
  def stretch(%{px: px} = img, opts \\ []) do
    lut = curve(Keyword.get_lazy(opts, :stats, fn -> stats(img) end), opts)
    %{img | px: for(<<p <- px>>, into: <<>>, do: <<elem(lut, p)>>)}
  end

  # -- stars and focus --------------------------------------------------------------------

  @doc """
  The stars in a frame, brightest first: pixels a clear step above the sky
  (`sigma:` noise steps, 6 by default), grouped into blobs, each measured
  for its center, peak, total light and half-flux radius. A blob touching
  the border is left out (`margin:`, a fortieth of the width: half a star
  is missing there, and a camera that corrects its lens lifts the corners
  into false stars), and so is a blob of fewer than `min_pixels:` (4) or
  sharper than `min_hfr:` (0.9 px): hot pixels and noise, not stars. At
  most `limit:` (40).
  """
  def stars(img, opts \\ []), do: find(img, opts).stars

  @doc """
  The stars and everything turned away, with why: `%{stars, rejected,
  border}`. `rejected` is `[%{x, y, why}]` (`:border`, `:small` for fewer
  lit pixels than a star, `:sharp` for sharper than these optics make: hot
  pixels and noise), at most 40, so a page can show what was ignored.
  `border` is the width of the edge kept clear, in pixels.
  """
  def find(%{w: w, h: h} = img, opts \\ []) do
    s = Keyword.get_lazy(opts, :stats, fn -> stats(img) end)
    margin = Keyword.get(opts, :sigma, 6) * s.noise
    limit = Keyword.get(opts, :limit, 40)
    # a border kept clear: half a star lost off the edge, and the corners a camera lifts to correct its lens
    border = Keyword.get_lazy(opts, :margin, fn -> max(div(w, 40), 2) end)
    min_px = Keyword.get(opts, :min_pixels, 4)
    min_hfr = Keyword.get(opts, :min_hfr, 0.9)

    # too much lit is not stars (the Moon, a street light, daylight): the
    # samples say so before the frame is searched
    lit = if lit_share_high?(s, margin), do: :too_many, else: lit(img, s, margin)

    if lit == :too_many or length(lit) > div(w * h, 20) do
      %{stars: [], rejected: [], border: border}
    else
      {kept, rejected} =
        lit
        |> blobs(w)
        |> Enum.map_reduce([], fn b, rej ->
          cond do
            Enum.any?(b, &edge?(&1, w, h, border)) -> {nil, [mark(b, w, :border) | rej]}
            # fewer lit pixels than any star these optics make: a hot pixel or two, or noise
            length(b) < min_px -> {nil, [mark(b, w, :small) | rej]}
            true -> {b, rej}
          end
        end)

      {stars, rejected} =
        kept
        |> Enum.reject(&is_nil/1)
        |> Enum.map(&measure(&1, img, s))
        |> Enum.reject(&is_nil/1)
        # a couple of hot pixels side by side: sharper than any star the optics can make
        |> Enum.split_with(&(&1.hfr >= min_hfr))
        |> then(fn {ok, sharp} -> {ok, rejected ++ Enum.map(sharp, &%{x: &1.x, y: &1.y, why: :sharp})} end)

      %{stars: stars |> Enum.sort_by(& &1.flux, :desc) |> Enum.take(limit), rejected: Enum.take(rejected, 40), border: border}
    end
  end

  defp mark(blob, w, why) do
    n = length(blob)
    %{x: Enum.sum(Enum.map(blob, &rem(&1, w))) / n, y: Enum.sum(Enum.map(blob, &div(&1, w))) / n, why: why}
  end

  @doc """
  How much crisp detail the picture holds: the mean squared brightness step
  between neighbouring pixels (every other pixel, both ways), counting only
  steps bigger than `sigma:` (8) noise steps, so noise alone scores near
  zero. Anything with edges (stars, craters, a distant light) scores higher
  the sharper it is, so it peaks at focus whatever's in the picture. A
  relative number: compare it with itself as the focuser turns.
  """
  def detail(%{w: w, h: h, px: px}, stats, opts \\ []) do
    t = Keyword.get(opts, :sigma, 8) * Map.get(stats, :noise, 1.0)

    {sum, n} =
      for y <- 0..(h - 3)//2, reduce: {0, 0} do
        acc -> detail_row(binary_part(px, y * w, w), binary_part(px, (y + 2) * w, w), t, acc)
      end

    if n == 0, do: 0.0, else: Float.round(sum / n, 3)
  end

  @doc """
  A bright extended target (the Moon, a planet, a lit window): the middle of
  everything at least half as bright as its brightest part (`%{x, y}`), how
  much of the frame that is (`fraction`), its box (`x0, y0, x1, y1`), whether
  that box reaches the frame's edge (`edge`: then the middle is only the middle
  of what shows), and its `peak`. Read from every other pixel of every other
  row. `nil` when nothing stands `min_contrast:` (20) levels above the
  background, or it covers less than `min_fraction:` (0.0005) of the frame.

  This is what `Controller.LockOn` holds still.
  """
  def bright(%{w: w, h: h, px: px}, stats, opts \\ []) do
    top = Map.get(stats, :max, 0)
    bg = Map.get(stats, :background, 0)

    if top - bg < Keyword.get(opts, :min_contrast, 20) do
      nil
    else
      t = bg + div(top - bg, 2)

      {n, sx, sy, box} =
        for y <- 0..(h - 1)//2, reduce: {0, 0, 0, nil} do
          acc -> bright_row(binary_part(px, y * w, w), 0, y, t, acc)
        end

      total = div(w + 1, 2) * div(h + 1, 2)

      if n == 0 or n / total < Keyword.get(opts, :min_fraction, 0.0005) do
        nil
      else
        {x0, y0, x1, y1} = box
        margin = 4

        %{
          x: sx / n,
          y: sy / n,
          fraction: n / total,
          peak: top,
          x0: x0,
          y0: y0,
          x1: x1,
          y1: y1,
          edge: x0 <= margin or y0 <= margin or x1 >= w - 1 - margin or y1 >= h - 1 - margin
        }
      end
    end
  end

  defp bright_row(<<p, _, rest::binary>>, x, y, t, {n, sx, sy, box}) when p >= t do
    box =
      case box do
        nil -> {x, y, x, y}
        {x0, y0, x1, y1} -> {min(x0, x), min(y0, y), max(x1, x), max(y1, y)}
      end

    bright_row(rest, x + 2, y, t, {n + 1, sx + x, sy + y, box})
  end

  defp bright_row(<<_, _, rest::binary>>, x, y, t, acc), do: bright_row(rest, x + 2, y, t, acc)
  defp bright_row(_, _, _, _, acc), do: acc

  # every other pixel along a row: the step to the right and the step down
  defp detail_row(<<a, _, rest::binary>>, <<c, _, below::binary>>, t, {sum, n}) when byte_size(rest) > 0 do
    <<b, _::binary>> = rest
    g = abs(b - a) + abs(c - a)
    detail_row(rest, below, t, if(g > t, do: {sum + g * g, n + 1}, else: {sum, n + 1}))
  end

  defp detail_row(_, _, _, acc), do: acc

  defp lit_share_high?(%{patches: p}, margin), do: p.lit95 > margin
  defp lit_share_high?(_, _), do: false

  # every pixel a margin above its own patch's background, found row by row
  # within each patch by the VM's own byte search (in C) rather than a step
  # of Elixir per pixel
  defp lit(%{w: w, px: px}, %{patches: p}, margin) do
    xb = Tuple.to_list(p.xb)
    yb = Tuple.to_list(p.yb)

    for {{y0, y1}, ty} <- Enum.with_index(Enum.zip(yb, tl(yb))),
        {{x0, x1}, tx} <- Enum.with_index(Enum.zip(xb, tl(xb))),
        x1 > x0,
        pattern = above(elem(p.level, ty * p.cols + tx) + margin),
        pattern != nil,
        y <- y0..(y1 - 1)//1,
        {at, _} <- :binary.matches(px, pattern, scope: {y * w + x0, x1 - x0}),
        do: at
  end

  defp above(thr) do
    case floor(thr) + 1 do
      v when v > 255 -> nil
      v -> :binary.compile_pattern(Enum.map(max(v, 0)..255, &<<&1>>))
    end
  end

  defp edge?(i, w, h, m) do
    {x, y} = {rem(i, w), div(i, w)}
    x < m or y < m or x > w - 1 - m or y > h - 1 - m
  end

  # 8-connected groups of lit pixels, by flood fill over a set
  defp blobs(indices, w) do
    set = MapSet.new(indices)
    do_blobs(indices, set, w, [])
  end

  defp do_blobs([], _set, _w, acc), do: acc

  defp do_blobs([i | rest], set, w, acc) do
    if MapSet.member?(set, i) do
      {blob, set} = fill([i], MapSet.delete(set, i), w, [])
      do_blobs(rest, set, w, [blob | acc])
    else
      do_blobs(rest, set, w, acc)
    end
  end

  defp fill([], set, _w, blob), do: {blob, set}

  defp fill([i | todo], set, w, blob) do
    x = rem(i, w)

    near =
      for dy <- [-w, 0, w], dx <- [-1, 0, 1], dx != 0 or dy != 0,
          # no wrapping round the row ends
          not (dx == -1 and x == 0) and not (dx == 1 and x == w - 1),
          j = i + dy + dx,
          MapSet.member?(set, j),
          do: j

    fill(near ++ todo, Enum.reduce(near, set, &MapSet.delete(&2, &1)), w, [i | blob])
  end

  # center, peak, light above the sky, and the half-flux radius within a box
  # a little bigger than the blob
  defp measure(blob, %{w: w, h: h, px: px}, stats) do
    xs = Enum.map(blob, &rem(&1, w))
    ys = Enum.map(blob, &div(&1, w))
    r = max(max(Enum.max(xs) - Enum.min(xs), Enum.max(ys) - Enum.min(ys)), 3) + 3
    cx0 = div(Enum.min(xs) + Enum.max(xs), 2)
    cy0 = div(Enum.min(ys) + Enum.max(ys), 2)
    bg = background_at(stats, cx0, cy0)
    # light within a noise step of the sky is the sky, not the star: counting it would widen every star
    floor = Map.get(stats, :noise, 0)

    pixels =
      for y <- max(cy0 - r, 0)..min(cy0 + r, h - 1),
          x <- max(cx0 - r, 0)..min(cx0 + r, w - 1),
          f = :binary.at(px, y * w + x) - bg,
          f > floor,
          do: {x, y, f}

    flux = Enum.reduce(pixels, 0, fn {_, _, f}, s -> s + f end)

    if flux <= 0 do
      nil
    else
      cx = Enum.reduce(pixels, 0, fn {x, _, f}, s -> s + x * f end) / flux
      cy = Enum.reduce(pixels, 0, fn {_, y, f}, s -> s + y * f end) / flux
      hfr = Enum.reduce(pixels, 0, fn {x, y, f}, s -> s + :math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)) * f end) / flux
      peak = Enum.reduce(pixels, 0, fn {_, _, f}, m -> max(m, f) end) + bg

      %{x: cx, y: cy, peak: peak, flux: flux, hfr: hfr, pixels: length(blob)}
    end
  end

  @doc """
  One focus number for a frame: the median half-flux radius of its
  brightest unsaturated stars (a saturated star's core is clipped, so it
  reads wider than it is), and how many stars there were.
  """
  def focus(stars) do
    usable = stars |> Enum.reject(&(&1.peak >= 250)) |> Enum.take(8)
    usable = if usable == [], do: Enum.take(stars, 3), else: usable

    case usable |> Enum.map(& &1.hfr) |> Enum.sort() do
      [] -> %{hfr: nil, stars: length(stars)}
      hfrs -> %{hfr: Enum.at(hfrs, div(length(hfrs), 2)), stars: length(stars)}
    end
  end

  @doc """
  Is this worth giving to a plate solver? A telescope pointed at a garage,
  a cloud, the Moon or a street light doesn't see stars, and a solver will
  grind on it for minutes or, worse, "find" somewhere. So, before any of
  that, a plain answer:

    * `:too_bright`: a lot of the frame is white, or the sky itself is bright
      (the Moon, a light, daylight, a lit wall)
    * `:no_stars`: nothing stands out (clouds, a wall, trees, the lens cap)
    * `:blurry`: things stand out but they're big soft blobs, not points
      (out of focus, or something close up)
    * `:few_stars`: some stars, fewer than a solver needs (`min:`, 6)
    * `:stars`: go ahead
  """
  def verdict(stats, stars, opts \\ []) do
    min = Keyword.get(opts, :min, 6)
    %{hfr: hfr} = focus(stars)

    cond do
      stats.saturated > 0.02 or stats.background > 180 -> :too_bright
      stars == [] -> :no_stars
      is_number(hfr) and hfr > 6 -> :blurry
      length(stars) < min -> :few_stars
      true -> :stars
    end
  end

  @doc "The verdict in words, with what to do about it."
  def verdict_words(:too_bright), do: "Too bright: the Moon, a light, daylight or a lit wall. Point somewhere darker, or shorten the exposure"
  def verdict_words(:no_stars), do: "No stars: clouds, a wall, trees or the lens cap"
  def verdict_words(:blurry), do: "Blurry blobs, not stars: focus first, or it's looking at something close"
  def verdict_words(:few_stars), do: "Only a few stars: a longer exposure or more stacking will show more"
  def verdict_words(:stars), do: "Stars"

  @doc "A square around (`cx`, `cy`), `size` pixels a side, clipped to the frame."
  def crop(%{w: w, h: h, px: px}, cx, cy, size) do
    half = div(size, 2)
    x0 = (round(cx) - half) |> max(0) |> min(max(w - size, 0))
    y0 = (round(cy) - half) |> max(0) |> min(max(h - size, 0))
    cw = min(size, w)
    ch = min(size, h)
    rows = for y <- y0..(y0 + ch - 1), do: binary_part(px, y * w + x0, cw)
    %{w: cw, h: ch, px: IO.iodata_to_binary(rows)}
  end

  # -- PNG, so a browser can show it -----------------------------------------------------

  @doc """
  As a grayscale PNG. With `curve:` (from `curve/2`) the pixels go in as
  they are and the curve goes in as the palette, so the browser does the
  stretching.
  """
  def png(%{w: w, h: h, px: px}, opts \\ []) do
    rows = for y <- 0..(h - 1), do: [0, binary_part(px, y * w, w)]

    {type, palette} =
      case opts[:curve] do
        nil -> {0, []}
        lut -> {3, [chunk("PLTE", for(v <- Tuple.to_list(lut), into: <<>>, do: <<v, v, v>>))]}
      end

    IO.iodata_to_binary([
      <<137, 80, 78, 71, 13, 10, 26, 10>>,
      chunk("IHDR", <<w::32, h::32, 8, type, 0, 0, 0>>),
      palette,
      chunk("IDAT", :zlib.compress(IO.iodata_to_binary(rows))),
      chunk("IEND", <<>>)
    ])
  end

  defp chunk(type, data) do
    <<byte_size(data)::32, type::binary, data::binary, :erlang.crc32(type <> data)::32>>
  end

  @doc "Average of several frames of the same size (a longer exposure's worth of light, with less noise)."
  def average([one]), do: one

  def average([%{w: w, h: h} | _] = frames) do
    n = length(frames)
    sums = Enum.reduce(frames, :binary.copy(<<0::16>>, w * h), fn %{px: px}, acc -> add16(acc, px, <<>>) end)
    %{w: w, h: h, px: for(<<s::16 <- sums>>, into: <<>>, do: <<min(div(s + (n >>> 1), n), 255)>>)}
  end

  defp add16(<<s::16, ss::binary>>, <<p, ps::binary>>, acc), do: add16(ss, ps, <<acc::binary, s + p::16>>)
  defp add16(<<>>, _, acc), do: acc
end
