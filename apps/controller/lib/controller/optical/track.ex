defmodule Controller.Optical.Track do
  @moduledoc """
  Follow the same spots on the moving body through a sequence of frames.

  Features are the textured blocks that moved between the first two frames;
  each is then followed frame to frame with a local search, the patch
  refreshed from the frame it was last found in. A feature that cannot be
  found again (match too poor, or it left the frame) is dropped. The result
  is a list of trajectories: one image position per frame, in the frames'
  own pixels.
  """

  alias Controller.Optical.{Flow, Frame}

  @block 8
  @search 10
  # a re-match must be at least this good relative to a perfect match to count
  @max_sad_per_px 18

  @doc """
  Trajectories through `frames` (a list, in sweep order). Returns
  `[%{points: [{x, y}, ...]}]` with one point per frame, only for features
  found in every frame.
  """
  def trajectories(frames, opts \\ [])

  def trajectories([f0, f1 | _] = frames, opts) do
    block = opts[:block] || @block
    search = opts[:search] || @search

    seeds = Flow.between(f0, f1, block: block, search: max(search, 14))

    seeds
    |> Enum.map(fn %{x: x, y: y} -> follow(frames, {x - block / 2, y - block / 2}, block, search) end)
    |> Enum.reject(&is_nil/1)
    |> Enum.map(fn pts -> %{points: Enum.map(pts, fn {x, y} -> {x + block / 2, y + block / 2} end)} end)
  end

  def trajectories(_, _), do: []

  # top-left corner positions frame by frame; nil if lost. The search is
  # centred on where the spot is heading (last step repeated): steps of
  # several degrees move a spot further than the window, but about the same
  # amount each time.
  defp follow([f0 | rest], start, block, search) do
    Enum.reduce_while(rest, {[start], f0, start, {0.0, 0.0}}, fn frame, {acc, prev_frame, prev_pos, vel} ->
      {px, py} = prev_pos
      {vx, vy} = vel
      guess = {px + vx, py + vy}

      case find(prev_frame, prev_pos, guess, frame, block, search) do
        {:ok, {nx, ny} = pos} -> {:cont, {[pos | acc], frame, pos, {nx - px, ny - py}}}
        :lost -> {:halt, nil}
      end
    end)
    |> case do
      nil -> nil
      {acc, _, _, _} -> Enum.reverse(acc)
    end
  end

  defp find(prev, {px, py}, {gx, gy}, frame, block, search) do
    x0 = round(px)
    y0 = round(py)
    cx = round(gx)
    cy = round(gy)
    patch = for y <- y0..(y0 + block - 1), x <- x0..(x0 + block - 1), do: Frame.at(prev, x, y)

    {bx, by, best} =
      for dy <- -search..search, dx <- -search..search, reduce: {0, 0, 1.0e18} do
        {bdx, bdy, bbest} ->
          s = sad(patch, frame, cx + dx, cy + dy, block)
          if s < bbest, do: {dx, dy, s}, else: {bdx, bdy, bbest}
      end

    inside = cx + bx >= 0 and cy + by >= 0 and cx + bx + block <= frame.w and cy + by + block <= frame.h

    if inside and best / (block * block) <= @max_sad_per_px,
      do: {:ok, {cx + bx + 0.0, cy + by + 0.0}},
      else: :lost
  end

  defp sad(patch, frame, x0, y0, block) do
    Enum.zip_reduce(patch, for(y <- y0..(y0 + block - 1), x <- x0..(x0 + block - 1), do: Frame.at(frame, x, y)), 0, fn p, q, acc -> acc + abs(p - q) end)
  end
end
