defmodule Controller.Sky.Solve.Clean do
  @moduledoc """
  A phone photo through an eyepiece, cut down to the stars: the same steps
  that made the first night's plates solve with ImageMagick, in Elixir, so
  the Pi (which has no ImageMagick) solves them too.

  A phone held to an eyepiece gives a bright disc (moonlight, light
  pollution) with a hard rim, in a black frame. Raw, the star finder counts
  the rim and the grain as thousands of stars. So:

    1. **The disc**, from a small copy (djpeg's 1/8 scale): blurred a
       little, thresholded at 8%, eroded by the equivalent of 50 full-size
       pixels so the rim is gone, and split into connected regions. The
       biggest is the eyepiece, as long as it covers 5% of the frame (less is
       the halo of a bright star); moonlight flaring off the edge is a second
       blob and is left out.
    2. **The moonlight**, from the same small copy blurred hard (about 25
       full-size pixels), taken off the photo.
    3. **Crop** to the disc, black outside it.

  Works on 8-bit PGM (`P5`) bytes: `small` at an eighth of the photo's size
  and `work`, the copy the stars come from, `ratio` times bigger (8: the
  photo itself, 4: half size). Returns the cleaned PGM and where it came from.

      Clean.eyepiece(small_pgm, photo_pgm, 8)
      #=> {:ok, pgm, %{box: {x, y, w, h}, disc_share: 0.27}}   # in `work` pixels
      #=> :no_eyepiece
  """

  # 8% of full scale, as ImageMagick's -threshold 8%
  @threshold 0.08 * 255
  # ImageMagick's Disk:50 at full size, in small pixels
  @erode 50 / 8
  @min_disc 0.05

  def eyepiece(small_pgm, work_pgm, ratio \\ 8) do
    with {:ok, {sw, sh, small}} <- pgm(small_pgm),
         {:ok, {hw, hh, half}} <- pgm(work_pgm) do
      rows = rows(small, sw, sh)
      soft = rows |> box_blur(1) |> box_blur(1)
      runs = Enum.map(soft, &runs_over(&1, @threshold))
      eroded = erode(runs, sw, @erode)

      case biggest(eroded, sw * sh) do
        nil ->
          :no_eyepiece

        %{runs: disc_runs, box: {x0, y0, x1, y1}, area: area} ->
          # the moonlight, one line per small row, each small pixel repeated
          # across the photo pixels it covers
          moon =
            rows
            |> box_blur(3)
            |> box_blur(3)
            |> Enum.map(fn line -> for b <- line, into: <<>>, do: :binary.copy(<<b>>, ratio) end)
            |> List.to_tuple()

          mask = disc_runs

          # the disc's box in half-size pixels, inside the photo
          bx0 = min(x0 * ratio, hw - 1)
          by0 = min(y0 * ratio, hh - 1)
          bx1 = min((x1 + 1) * ratio - 1, hw - 1)
          by1 = min((y1 + 1) * ratio - 1, hh - 1)

          # no stretch to full range after: the counts are already bytes, and
          # the star finder works in multiples of the noise, not in counts
          body = subtract(half, hw, moon, mask, {bx0, by0, bx1, by1}, ratio)
          w = bx1 - bx0 + 1
          h = by1 - by0 + 1
          {:ok, ["P5\n#{w} #{h}\n255\n", body] |> IO.iodata_to_binary(), %{box: {bx0, by0, w, h}, disc_share: area / (sw * sh)}}
      end
    end
  end

  # -- PGM ------------------------------------------------------------------------------

  @doc "Width, height and pixels of an 8-bit binary PGM."
  def pgm(<<"P5", rest::binary>>) do
    case header(rest, []) do
      {[w, h, 255], pixels} when byte_size(pixels) >= w * h -> {:ok, {w, h, binary_part(pixels, 0, w * h)}}
      _ -> {:error, :unsupported_image}
    end
  end

  def pgm(_), do: {:error, :unsupported_image}

  # three numbers, whitespace and comments between, then one whitespace byte
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

  defp rows(pixels, w, h), do: for(y <- 0..(h - 1), do: :binary.bin_to_list(pixels, y * w, w))

  # -- blur: a box of radius r across, then down (two passes approach a Gaussian) -----
  # Sliding sums over lists, whole counts throughout: no tuples to index,
  # no floats to box, no transposes. The Pi has no JIT to hide any of that.

  defp box_blur(rows, r), do: rows |> Enum.map(&blur_line(&1, r)) |> blur_down(r)

  # the ends repeated, a window of 2r+1 sliding along
  defp blur_line(line, r) do
    k = 2 * r + 1
    padded = List.duplicate(hd(line), r) ++ line ++ List.duplicate(List.last(line), r)
    {window, lead} = Enum.split(padded, k)
    slide(padded, lead, Enum.sum(window), k, [])
  end

  defp slide(_trail, [], sum, k, acc), do: Enum.reverse([div(sum, k) | acc])
  defp slide([t | trail], [l | lead], sum, k, acc), do: slide(trail, lead, sum - t + l, k, [div(sum, k) | acc])

  # the same down the columns, a row at a time
  defp blur_down(rows, r) do
    k = 2 * r + 1
    padded = List.duplicate(hd(rows), r) ++ rows ++ List.duplicate(List.last(rows), r)
    {window, lead} = Enum.split(padded, k)
    sum = Enum.reduce(tl(window), hd(window), fn row, acc -> :lists.zipwith(&(&1 + &2), acc, row) end)
    slide_down(padded, lead, sum, k, [])
  end

  defp slide_down(_trail, [], sum, k, acc), do: Enum.reverse([Enum.map(sum, &div(&1, k)) | acc])

  defp slide_down([t | trail], [l | lead], sum, k, acc) do
    next = :lists.zipwith3(fn s, a, b -> s - a + b end, sum, t, l)
    slide_down(trail, lead, next, k, [Enum.map(sum, &div(&1, k)) | acc])
  end

  # -- the disc as runs of pixels per row -------------------------------------------------

  defp runs_over(line, level) do
    {runs, open} =
      line
      |> Enum.with_index()
      |> Enum.reduce({[], nil}, fn
        {v, x}, {acc, nil} when v > level -> {acc, x}
        {v, _x}, {acc, start} when v > level -> {acc, start}
        {_v, x}, {acc, start} when start != nil -> {[{start, x - 1} | acc], nil}
        _, state -> state
      end)

    runs = if open != nil, do: [{open, length(line) - 1} | runs], else: runs
    Enum.reverse(runs)
  end

  # Erosion by a disc of radius r: a pixel stays when every pixel within r is
  # set. Row by row: row y's survivors are the runs of each row y+dy shrunk
  # by the disc's half-width at dy, all intersected. Beyond the photo's edge
  # the edge repeats (as ImageMagick's default), so a disc running off the
  # frame is not eaten from that side.
  defp erode(runs, w, r) do
    rows = List.to_tuple(runs)
    h = tuple_size(rows)
    reach = trunc(r)

    for y <- 0..(h - 1) do
      Enum.reduce(-reach..reach, [{0, w - 1}], fn dy, acc ->
        half = trunc(:math.sqrt(max(r * r - dy * dy, 0)))
        row = elem(rows, (y + dy) |> max(0) |> min(h - 1))
        shrunk = for {a, b} <- row, a2 = if(a > 0, do: a + half, else: a), b2 = if(b < w - 1, do: b - half, else: b), a2 <= b2, do: {a2, b2}
        intersect(acc, shrunk)
      end)
    end
  end

  defp intersect(a, b) do
    for {a0, a1} <- a, {b0, b1} <- b, lo = max(a0, b0), hi = min(a1, b1), lo <= hi, do: {lo, hi}
  end

  # Connected regions (8-connected) from the runs, by union-find over runs;
  # the biggest, if it's an eyepiece's worth of the frame.
  defp biggest(runs_by_row, frame) do
    runs =
      runs_by_row
      |> Enum.with_index()
      |> Enum.flat_map(fn {runs, y} -> Enum.map(runs, fn {a, b} -> {y, a, b} end) end)
      |> Enum.with_index()

    by_row = Enum.group_by(runs, fn {{y, _, _}, _} -> y end)

    parent =
      Enum.reduce(runs, %{}, fn {{y, a, b}, id}, parent ->
        parent = Map.put_new(parent, id, id)

        for({{_, pa, pb}, pid} <- Map.get(by_row, y - 1, []), pa <= b + 1 and pb + 1 >= a, do: pid)
        |> Enum.reduce(parent, fn pid, p -> union(p, id, pid) end)
      end)

    runs
    |> Enum.group_by(fn {_, id} -> root(parent, id) end, fn {run, _} -> run end)
    |> Enum.map(fn {_, rs} ->
      %{
        area: Enum.sum(for {_, a, b} <- rs, do: b - a + 1),
        box: {Enum.min(for {_, a, _} <- rs, do: a), Enum.min(for {y, _, _} <- rs, do: y), Enum.max(for {_, _, b} <- rs, do: b), Enum.max(for {y, _, _} <- rs, do: y)},
        runs: Enum.group_by(rs, &elem(&1, 0), fn {_, a, b} -> {a, b} end)
      }
    end)
    |> Enum.max_by(& &1.area, fn -> nil end)
    |> case do
      %{area: a} = disc when a >= @min_disc * frame -> disc
      _ -> nil
    end
  end

  defp root(parent, id) do
    case Map.fetch!(parent, id) do
      ^id -> id
      up -> root(parent, up)
    end
  end

  defp union(parent, a, b) do
    {ra, rb} = {root(parent, a), root(parent, b)}
    if ra == rb, do: parent, else: Map.put(parent, max(ra, rb), min(ra, rb))
  end

  # -- the photo, less its moonlight, inside the disc ----------------------------------

  # Row by row, as binaries (the Pi has no JIT: per-pixel Elixir is what
  # makes this slow, binary matching is what keeps it quick). The moonlight
  # is held across each small pixel's 8×8 block: it changes by a fraction of
  # a count over that distance, far under what the star finder looks for.
  # Outside the disc: black.
  defp subtract(photo, pw, moon, mask, {x0, y0, x1, y1}, ratio) do
    for y <- y0..y1 do
      line = :binary.part(photo, y * pw + x0, x1 - x0 + 1)
      light = elem(moon, min(div(y, ratio), tuple_size(moon) - 1))

      # the disc's spans on this row, in photo pixels inside the box
      spans =
        for {a, b} <- Map.get(mask, div(y, ratio), []),
            lo = max(a * ratio, x0),
            hi = min((b + 1) * ratio - 1, x1),
            lo <= hi,
            do: {lo - x0, hi - x0}

      span_rows(line, spans, 0, fn lo, hi ->
        n = min(hi - lo + 1, byte_size(light) - (lo + x0))
        minus(:binary.part(line, lo, n), :binary.part(light, lo + x0, n), <<>>)
      end)
    end
    |> IO.iodata_to_binary()
  end

  # a row: black between the spans, the photo less the moonlight inside them
  defp span_rows(line, [], at, _f), do: zeros(byte_size(line) - at)

  defp span_rows(line, [{lo, hi} | rest], at, f),
    do: [zeros(lo - at), f.(lo, hi) | span_rows(line, rest, hi + 1, f)]

  defp zeros(n) when n > 0, do: :binary.copy(<<0>>, n)
  defp zeros(_), do: <<>>

  defp minus(<<p, ps::binary>>, <<b, bs::binary>>, acc) when p > b, do: minus(ps, bs, <<acc::binary, p - b>>)
  defp minus(<<_, ps::binary>>, <<_, bs::binary>>, acc), do: minus(ps, bs, <<acc::binary, 0>>)
  defp minus(<<>>, _, acc), do: acc
end
