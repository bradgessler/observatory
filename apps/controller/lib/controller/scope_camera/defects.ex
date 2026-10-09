defmodule Controller.ScopeCamera.Defects do
  @moduledoc """
  Specks that are the sensor's, not the sky's: a warm pixel or a small hot
  cluster sits on the same pixels whichever way the telescope points, while
  a star moves with the telescope. So a speck the star finder keeps calling
  a star, at the same place in pictures taken at three or more pointings at
  least a field apart, is a defect; from then on it's ignored (drawn with
  the other ignored specks), and its "size" never stands in for a star's.

  Found on the first night with the SV105C: of 362 "stars" in 3,800 frames,
  284 were four such spots, seen at up to eight pointings 25° apart.

      d = Defects.new()
      {d, new?} = Defects.learn(d, [%{x: 732, y: 70}], {878, 771})
      Defects.defect?(d, 731, 69)

  Positions are in the picture as kept (960 × 540), in 4-pixel cells, a
  neighbouring cell counting too (a speck's centre wobbles with the noise).
  A pointing is the mount's two axes in steps, in buckets about a field
  wide (`@bucket` steps: on an EQ6-R, 0.44°, the SV105C's field at 714 mm).
  Pure: `Controller.ScopeCamera` keeps one, learns from every picture taken
  while the mount is connected, and saves the defects it finds.
  """

  @cell 4
  @bucket 11_000
  @pointings 3
  # cells remembered while learning; past this, only those already seen at two pointings are kept
  @max_seen 3_000

  defstruct defects: MapSet.new(), seen: %{}

  @doc "Knowing the given defect cells (`[[cx, cy]]`, as saved) and nothing else yet."
  def new(cells \\ []) do
    %__MODULE__{defects: MapSet.new(for [cx, cy] <- cells || [], is_integer(cx) and is_integer(cy), do: {cx, cy})}
  end

  @doc "Whether (`x`, `y`) is on a known defect."
  def defect?(%__MODULE__{defects: d}, x, y) do
    {cx, cy} = cell(x, y)
    Enum.any?(for(dx <- -1..1, dy <- -1..1, do: {cx + dx, cy + dy}), &MapSet.member?(d, &1))
  end

  @doc "`stars` split into `{stars, defects}`."
  def split(d, stars), do: Enum.split_with(stars, &(not defect?(d, &1.x, &1.y)))

  @doc """
  Learn from one picture: the stars the finder kept, and the pointing it was
  taken at (`{ra_steps, dec_steps}`, or nil when the mount isn't known, and
  then nothing is learned). `{defects, true}` when a new defect was found.
  """
  def learn(d, _stars, nil), do: {d, false}

  def learn(%__MODULE__{} = d, stars, {ra, dec}) when is_integer(ra) and is_integer(dec) do
    pointing = {div(ra, @bucket), div(dec, @bucket)}

    {seen, found} =
      Enum.reduce(stars, {d.seen, []}, fn %{x: x, y: y}, {seen, found} ->
        c = cell(x, y)
        at = seen |> Map.get(c, MapSet.new()) |> MapSet.put(pointing)
        if MapSet.size(at) >= @pointings, do: {Map.delete(seen, c), [c | found]}, else: {Map.put(seen, c, at), found}
      end)

    seen = if map_size(seen) > @max_seen, do: Map.filter(seen, fn {_, at} -> MapSet.size(at) >= 2 end), else: seen
    {%{d | seen: seen, defects: Enum.into(found, d.defects)}, found != []}
  end

  def learn(d, _stars, _), do: {d, false}

  @doc "The defects, for saving: `[[cx, cy]]`."
  def cells(%__MODULE__{defects: d}), do: d |> Enum.sort() |> Enum.map(&Tuple.to_list/1)

  @doc "The pointing a mount snapshot is at, for `learn/3`: nil when it isn't connected."
  def pointing(%{connected: true, axes: %{ra: %{steps: ra}, dec: %{steps: dec}}}) when is_integer(ra) and is_integer(dec), do: {ra, dec}
  def pointing(_), do: nil

  defp cell(x, y), do: {trunc(x) |> div(@cell), trunc(y) |> div(@cell)}
end
