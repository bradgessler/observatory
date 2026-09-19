defmodule Controller.Optical.Flow do
  @moduledoc """
  What moved between two frames, and which way: block matching.

  The frame is cut into blocks; each block with some texture is searched for
  in the second frame within a small window; the best match (least sum of
  absolute differences) gives its displacement. Blocks that did not move, or
  had nothing to match on, are dropped. What remains is a sparse flow field:
  `[%{x, y, dx, dy}]` in the frame's own (downsampled) pixels.

  Deterministic and dumb on purpose. Good enough to see a telescope tube
  swing; not an optical-flow library.
  """

  alias Controller.Optical.Frame

  @block 8
  @search 6
  # a block needs at least this much contrast to be worth matching
  @min_texture 12
  # and must have moved at least this far to count
  @min_move 1.5

  @doc "Sparse displacement field from `a` to `b`."
  def between(%{w: w, h: h} = a, %{w: w, h: h} = b, opts \\ []) do
    block = opts[:block] || @block
    search = opts[:search] || @search
    min_texture = opts[:min_texture] || @min_texture

    for by <- 0..(div(h, block) - 1),
        bx <- 0..(div(w, block) - 1),
        x0 = bx * block,
        y0 = by * block,
        x0 >= search and y0 >= search and x0 + block + search <= w and y0 + block + search <= h,
        patch = patch(a, x0, y0, block),
        texture(patch) >= min_texture,
        {dx, dy, best, base} = best_match(patch, b, x0, y0, block, search),
        :math.sqrt(dx * dx + dy * dy) >= @min_move,
        # the match must be clearly better than staying put
        best < base * 0.6 do
      %{x: x0 + block / 2, y: y0 + block / 2, dx: dx / 1, dy: dy / 1}
    end
  end

  defp patch(frame, x0, y0, block) do
    for y <- y0..(y0 + block - 1), x <- x0..(x0 + block - 1), do: Frame.at(frame, x, y)
  end

  # spread of values inside a block: flat sky and blank walls score ~0
  defp texture(patch) do
    {mn, mx} = Enum.min_max(patch)
    mx - mn
  end

  defp best_match(patch, b, x0, y0, block, search) do
    base = sad(patch, b, x0, y0, block)

    {dx, dy, best} =
      for dy <- -search..search, dx <- -search..search, reduce: {0, 0, base} do
        {bdx, bdy, bbest} ->
          s = sad(patch, b, x0 + dx, y0 + dy, block)
          if s < bbest, do: {dx, dy, s}, else: {bdx, bdy, bbest}
      end

    {dx, dy, best, base}
  end

  defp sad(patch, b, x0, y0, block) do
    Enum.zip_reduce(patch, for(y <- y0..(y0 + block - 1), x <- x0..(x0 + block - 1), do: Frame.at(b, x, y)), 0, fn p, q, acc -> acc + abs(p - q) end)
  end
end
