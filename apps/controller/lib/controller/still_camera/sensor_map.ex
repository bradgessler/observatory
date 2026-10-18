defmodule Controller.StillCamera.SensorMap do
  @moduledoc """
  The camera's sensor as a service with an uptime: which parts of it are dimmed by dust (or worse),
  measured from the night's own pictures, and the dither that steps past them.

  17 October 2026: dark blotches 30 to 70 arcseconds across sat in the same place in an hour of the
  Dumbbell Nebula and an hour of the Triangulum Galaxy. Brad saw them on the camera's screen before
  anything here did. A patch of sensor that dims what lands on it is a partial outage: the sky behind
  it is degraded, not lost, and moving the telescope between pictures (`Controller.Sky.Dither`)
  routes round it.

  How: each long exposure's grey copy (960 px wide, the sensor's way up) is shrunk to 240 px and
  kept, its stars hidden and its sky scaled to 1. Dust is stuck to the sensor and the sky is not, so
  once the kept pictures come from at least two pointings (two targets, or dither steps far enough
  apart), the median of them is the sky with the stars gone and the dust left. Divided by its own
  large-scale glow, what stays darker than `@dim` is dust. Each spot is reported with its size in
  arcseconds and how much light it takes.

    * `uptime`: the fraction of the sensor dimmed by less than `@dim` (1.0: no outage);
    * `dither_arcmin`: a disc wide enough to step past the biggest spot, or nil when there is
      nothing to step past.

  The answer is kept on the card (`sensor_map.json`), because dust stays from night to night until
  someone cleans the sensor. Pure functions (`shrink/2`, `spots/2`) do the work; the process only
  keeps pictures and decides when to look.
  """
  use GenServer
  require Logger

  # 960 / 4: dust of 30" is still 3 pixels across at 0.39"/px full size
  @factor 4
  @keep 48
  # look again after this many new pictures
  @every 6
  # a pixel dimmed by more than this is dust
  @dim 0.03
  # spots smaller than this many shrunk pixels are noise
  @min_px 4
  # the large-scale glow a spot is judged against: a box this many shrunk pixels each way
  @glow_px 12
  # pointings: two kept pictures count as different pointings when their dither steps are this far apart (arcmin)
  @apart_arcmin 1.0

  def start_link(opts \\ []), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

  @doc """
  Keep a picture's grey copy (`pgm`, 8-bit) for the map. `meta`: `exposure_s`, `frame` (nil for a light
  frame), `settling`, `stars` (how many), `target` (the hold's name), `dither` (`%{east_arcmin, north_arcmin}`
  or nil), `arcsec_per_px` of the copy. Only steady light frames of 2 s and longer with stars in them are kept.
  """
  def add(pgm, meta) when is_binary(pgm) do
    if keep?(meta), do: GenServer.cast(__MODULE__, {:add, pgm, meta})
    :ok
  end

  def add(_, _), do: :ok

  @doc "The map: `%{spots, uptime, dither_arcmin, frames, pointings, at}`, or nil before there is one."
  def status, do: :persistent_term.get({__MODULE__, :map}, nil)

  @doc "The dither radius the sensor needs now: arcminutes, nil when it is clean, `:unknown` before there is a map."
  def dither_arcmin do
    case status() do
      nil -> :unknown
      %{dither_arcmin: d} -> d
    end
  end

  @doc "What a page says about the sensor: `%{spots, biggest_arcsec, uptime, dither_arcmin}`, or nil before there is a map."
  def summary do
    case status() do
      %{spots: spots} = m ->
        %{spots: length(spots), biggest_arcsec: spots |> Enum.map(& &1.diameter_arcsec) |> Enum.max(fn -> nil end), uptime: m.uptime, dither_arcmin: m.dither_arcmin}

      _ ->
        nil
    end
  end

  @doc "Forget the map (after cleaning the sensor): the next pictures build a new one."
  def reset, do: GenServer.call(__MODULE__, :reset)

  defp keep?(meta) do
    meta[:frame] in [nil, ""] and meta[:settling] != true and is_number(meta[:exposure_s]) and meta[:exposure_s] >= 2 and
      (meta[:stars] || 0) >= 5
  end

  # -- the process --------------------------------------------------------------------------------

  @impl true
  def init(_opts) do
    map = load()
    if map, do: :persistent_term.put({__MODULE__, :map}, map)
    {:ok, %{frames: [], since: 0}}
  end

  @impl true
  def handle_cast({:add, pgm, meta}, s) do
    s =
      case shrink(pgm, @factor) do
        {:ok, img} ->
          frame = %{img: normalise(img), name: meta[:name], target: meta[:target], dither: meta[:dither], scale: (meta[:arcsec_per_px] || 2.42) * @factor}
          %{s | frames: Enum.take([frame | s.frames], @keep), since: s.since + 1}

        _ ->
          s
      end

    {:noreply, if(s.since >= @every, do: look(%{s | since: 0}), else: s)}
  end

  @impl true
  def handle_call(:reset, _from, s) do
    :persistent_term.erase({__MODULE__, :map})
    File.rm(file())
    {:reply, :ok, %{s | frames: []}}
  end

  defp look(%{frames: frames} = s) do
    n = pointings(frames)

    if n >= 2 and length(frames) >= 8 do
      scale = hd(frames).scale
      found = spots(Enum.map(frames, & &1.img), scale)
      # the pictures it was made from, by name: the map can be made again from them and checked
      map = Map.merge(found, %{frames: length(frames), pointings: n, at: DateTime.utc_now(), from: Enum.map(frames, & &1.name), method: %{shrink: @factor, dim: @dim, glow_px: @glow_px, min_px: @min_px}})
      :persistent_term.put({__MODULE__, :map}, map)
      save(map)
      Logger.info("sensor map: #{length(map.spots)} spots, uptime #{Float.round(map.uptime * 100, 2)}%, dither #{inspect(map.dither_arcmin)}")
    end

    s
  rescue
    e ->
      Logger.warning("sensor map: #{Exception.message(e)}")
      s
  end

  # how many different places in the sky the kept pictures were taken at: targets, and dither steps a
  # good way apart within one
  defp pointings(frames) do
    frames
    |> Enum.map(fn f ->
      {e, n} = if is_map(f.dither), do: {f.dither[:east_arcmin] || 0.0, f.dither[:north_arcmin] || 0.0}, else: {0.0, 0.0}
      {f.target, round(e / @apart_arcmin), round(n / @apart_arcmin)}
    end)
    |> Enum.uniq()
    |> length()
  end

  # -- the work, pure -----------------------------------------------------------------------------

  @doc "A PGM (8-bit) shrunk by `factor` each way, each pixel the mean of its block: `{:ok, %{w, h, px}}`."
  def shrink(pgm, factor) do
    with {:ok, %{w: w, h: h, px: px}} <- Controller.ScopeCamera.Image.from_pgm(pgm) do
      sw = div(w, factor)
      sh = div(h, factor)
      n = factor * factor

      rows =
        for by <- 0..(sh - 1) do
          sums =
            Enum.reduce(0..(factor - 1), List.duplicate(0, sw), fn dy, acc ->
              row = binary_part(px, (by * factor + dy) * w, sw * factor)
              block_sums(row, factor, acc)
            end)

          for v <- sums, into: <<>>, do: <<div(v, n)>>
        end

      {:ok, %{w: sw, h: sh, px: IO.iodata_to_binary(rows)}}
    end
  end

  defp block_sums(row, factor, acc) do
    sums = for <<block::binary-size(^factor) <- row>>, do: sum_bytes(block, 0)
    Enum.zip_with(acc, sums, &+/2)
  end

  defp sum_bytes(<<>>, t), do: t
  defp sum_bytes(<<b, rest::binary>>, t), do: sum_bytes(rest, t + b)

  @doc """
  A shrunk picture with its sky scaled to 1.0 and its stars hidden (nil): a tuple of floats, row
  after row, plus its size.
  """
  def normalise(%{w: w, h: h, px: px}) do
    vals = :binary.bin_to_list(px)
    sky = median(Enum.take_every(vals, 7)) |> max(1)
    # anything well above the sky is a star or the target's bright middle: not the sensor
    cut = sky * 1.25 + 3

    %{w: w, h: h, v: vals |> Enum.map(fn v -> if v > cut, do: nil, else: v / sky end) |> List.to_tuple()}
  end

  @doc """
  The spots: from normalised pictures (`normalise/1`) taken at different pointings, the median of each
  pixel, divided by its own smoothed glow; connected pixels dimmer than `@dim` make a spot.
  `%{spots: [%{x, y, diameter_arcsec, depth}], uptime, dither_arcmin}`, `x`/`y` as fractions of the sensor.
  """
  def spots([%{w: w, h: h} | _] = imgs, scale) do
    med =
      for i <- 0..(w * h - 1) do
        vals = for %{v: v} <- imgs, x = elem(v, i), x != nil, do: x
        if length(vals) >= 3, do: median(vals), else: nil
      end
      |> List.to_tuple()

    glow = smooth(med, w, h, @glow_px)
    # the telescope's own darkening towards the corners is steeper than the glow can follow within
    # its own width of the edge (17 October: a ring of false spots round the frame), so that border
    # is not judged
    m = @glow_px
    inside = fn i -> rem(i, w) >= m and rem(i, w) < w - m and div(i, w) >= m and div(i, w) < h - m end
    rel = for i <- 0..(w * h - 1), do: if(inside.(i), do: ratio(elem(med, i), elem(glow, i)))
    judged = Enum.count(0..(w * h - 1), inside)
    dark = rel |> Enum.with_index() |> Enum.filter(fn {r, _} -> r != nil and r < 1 - @dim end) |> MapSet.new(fn {_, i} -> i end)
    rel = List.to_tuple(rel)

    blobs =
      components(dark, w, h)
      |> Enum.filter(&(length(&1) >= @min_px))
      |> Enum.map(fn pix ->
        {sx, sy} = Enum.reduce(pix, {0, 0}, fn i, {a, b} -> {a + rem(i, w), b + div(i, w)} end)
        depth = 1 - (pix |> Enum.map(&elem(rel, &1)) |> Enum.min())

        %{
          x: Float.round(sx / length(pix) / w, 3),
          y: Float.round(sy / length(pix) / h, 3),
          diameter_arcsec: round(2 * :math.sqrt(length(pix) / :math.pi()) * scale),
          depth: Float.round(depth, 3)
        }
      end)
      |> Enum.sort_by(& &1.diameter_arcsec, :desc)

    uptime = 1 - MapSet.size(dark) / max(judged, 1)
    biggest = Enum.map(blobs, & &1.diameter_arcsec) |> Enum.max(fn -> 0 end)

    %{
      spots: blobs,
      uptime: uptime,
      # a disc whose steps clear the biggest spot: its width and a quarter, in half arcminutes, at least 1'
      dither_arcmin: if(blobs == [], do: nil, else: max(1.0, Float.ceil(biggest * 1.25 / 60 * 2) / 2))
    }
  end

  defp ratio(nil, _), do: nil
  defp ratio(_, nil), do: nil
  defp ratio(_, g) when g <= 0, do: nil
  defp ratio(m, g), do: m / g

  # a box blur of radius r that skips the holes (nil), separable: rows then columns
  defp smooth(t, w, h, r) do
    rows = for y <- 0..(h - 1), x <- 0..(w - 1), do: mean_of(for(dx <- -r..r//3, xx = x + dx, xx >= 0 and xx < w, do: elem(t, y * w + xx)))
    rows = List.to_tuple(rows)
    for(y <- 0..(h - 1), x <- 0..(w - 1), do: mean_of(for(dy <- -r..r//3, yy = y + dy, yy >= 0 and yy < h, do: elem(rows, yy * w + x)))) |> List.to_tuple()
  end

  defp mean_of(vals) do
    case Enum.reject(vals, &is_nil/1) do
      [] -> nil
      v -> Enum.sum(v) / length(v)
    end
  end

  # 4-connected groups of pixel indices
  defp components(set, w, h) do
    {groups, _} =
      Enum.reduce(set, {[], MapSet.new()}, fn i, {groups, seen} ->
        if MapSet.member?(seen, i), do: {groups, seen}, else: flood([i], set, w, h, seen, []) |> then(fn {g, seen} -> {[g | groups], seen} end)
      end)

    groups
  end

  defp flood([], _set, _w, _h, seen, acc), do: {acc, seen}

  defp flood([i | rest], set, w, h, seen, acc) do
    if MapSet.member?(seen, i) or not MapSet.member?(set, i) do
      flood(rest, set, w, h, MapSet.put(seen, i), acc)
    else
      x = rem(i, w)
      y = div(i, w)
      next = for {nx, ny} <- [{x - 1, y}, {x + 1, y}, {x, y - 1}, {x, y + 1}], nx >= 0 and nx < w and ny >= 0 and ny < h, do: ny * w + nx
      flood(next ++ rest, set, w, h, MapSet.put(seen, i), [i | acc])
    end
  end

  defp median(vals) do
    s = Enum.sort(vals)
    n = length(s)
    if rem(n, 2) == 1, do: Enum.at(s, div(n, 2)), else: (Enum.at(s, div(n, 2) - 1) + Enum.at(s, div(n, 2))) / 2
  end

  # -- on the card --------------------------------------------------------------------------------

  defp file, do: Path.join(Controller.StillCamera.dir(), "sensor_map.json")

  defp save(map) do
    File.mkdir_p!(Path.dirname(file()))
    File.write!(file(), Jason.encode!(map))
  rescue
    _ -> :ok
  end

  defp load do
    with {:ok, raw} <- File.read(file()), {:ok, m} <- Jason.decode(raw) do
      %{
        spots: Enum.map(m["spots"] || [], fn s -> %{x: s["x"], y: s["y"], diameter_arcsec: s["diameter_arcsec"], depth: s["depth"]} end),
        uptime: m["uptime"],
        dither_arcmin: m["dither_arcmin"],
        frames: m["frames"],
        pointings: m["pointings"],
        at: m["at"],
        from: m["from"],
        method: m["method"]
      }
    else
      _ -> nil
    end
  end
end
