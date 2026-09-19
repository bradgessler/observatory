defmodule Controller.Optical.Pivot do
  @moduledoc """
  Where in the picture did the thing turn about?

  For a rotation in the image plane, every displacement is perpendicular to
  the line from the centre to the point: `(p − c) · v = 0`. Each moving
  block gives one such equation; the least-squares centre is a 2×2 solve.
  The fit quality says how much the field really looks like a rotation
  (1 = perfect) versus a slide (0). A 3-D axis seen at an angle is somewhere
  between; the number tells you which.
  """

  @type fit :: %{cx: float, cy: float, quality: float, n: non_neg_integer, mean_dx: float, mean_dy: float, coherence: float}

  @doc "Fit a rotation centre to a sparse flow field. nil with fewer than 4 vectors."
  def fit(vectors) when length(vectors) < 4, do: nil

  def fit(vectors) do
    n = length(vectors)
    mdx = Enum.sum(Enum.map(vectors, & &1.dx)) / n
    mdy = Enum.sum(Enum.map(vectors, & &1.dy)) / n
    # coherence: 1 when every vector points the same way (a slide), ~0 when they fan out (a spin)
    mean_len = Enum.sum(Enum.map(vectors, fn v -> :math.sqrt(v.dx * v.dx + v.dy * v.dy) end)) / n
    coherence = if mean_len < 1.0e-6, do: 0.0, else: :math.sqrt(mdx * mdx + mdy * mdy) / mean_len

    # weights: longer displacements are measured more reliably
    {a11, a12, a22, b1, b2} =
      Enum.reduce(vectors, {0.0, 0.0, 0.0, 0.0, 0.0}, fn %{x: x, y: y, dx: dx, dy: dy}, {a11, a12, a22, b1, b2} ->
        pv = x * dx + y * dy
        {a11 + dx * dx, a12 + dx * dy, a22 + dy * dy, b1 + pv * dx, b2 + pv * dy}
      end)

    det = a11 * a22 - a12 * a12
    base = %{n: n, mean_dx: mdx, mean_dy: mdy, coherence: coherence}

    # all vectors parallel → the normal equations are singular: a slide, no centre
    if abs(det) < 1.0e-6 * max(a11 * a22, 1.0) do
      Map.merge(base, %{cx: nil, cy: nil, quality: 0.0})
    else
      cx = (b1 * a22 - b2 * a12) / det
      cy = (a11 * b2 - a12 * b1) / det

      # quality: how perpendicular each vector is to its radius, 1 = all of them
      perp =
        vectors
        |> Enum.map(fn %{x: x, y: y, dx: dx, dy: dy} ->
          rx = x - cx
          ry = y - cy
          rn = :math.sqrt(rx * rx + ry * ry)
          vn = :math.sqrt(dx * dx + dy * dy)
          if rn < 1.0e-6 or vn < 1.0e-6, do: 0.0, else: abs(rx * dy - ry * dx) / (rn * vn)
        end)

      Map.merge(base, %{cx: cx, cy: cy, quality: Enum.sum(perp) / length(perp)})
    end
  end

  @doc """
  Throw out arrows that disagree with the crowd: keep those within 60° of
  the median direction. A shelf that happened to match itself one block over
  should not vote on where the tube went.
  """
  def coherent(vectors) when length(vectors) < 6, do: vectors

  def coherent(vectors) do
    angles = Enum.map(vectors, fn v -> :math.atan2(v.dy, v.dx) end)
    # circular median: the angle with the least total angular distance to the rest
    median = Enum.min_by(angles, fn a -> Enum.sum(Enum.map(angles, &abs(wrap(&1 - a)))) end)
    kept = Enum.filter(vectors, fn v -> abs(wrap(:math.atan2(v.dy, v.dx) - median)) <= :math.pi() / 3 end)
    if length(kept) >= 4, do: kept, else: vectors
  end

  @pi :math.pi()
  defp wrap(a) when a > @pi, do: wrap(a - 2 * @pi)
  defp wrap(a) when a < -@pi, do: wrap(a + 2 * @pi)
  defp wrap(a), do: a

  @doc """
  What one camera can say about an axis that lies across its view: the axis
  projects to a line at right angles to the flow, through the moving body.
  Its position along the flow is not knowable from one view (depth); the
  direction is. `%{x, y, ux, uy}`: a point on the line and its unit direction.
  """
  def axis_line(vectors) when length(vectors) < 4, do: nil

  def axis_line(vectors) do
    n = length(vectors)
    cx = Enum.sum(Enum.map(vectors, & &1.x)) / n
    cy = Enum.sum(Enum.map(vectors, & &1.y)) / n
    mdx = Enum.sum(Enum.map(vectors, & &1.dx)) / n
    mdy = Enum.sum(Enum.map(vectors, & &1.dy)) / n
    len = :math.sqrt(mdx * mdx + mdy * mdy)
    if len < 1.0e-6, do: nil, else: %{x: cx, y: cy, ux: -mdy / len, uy: mdx / len}
  end

  @doc "Plain words for a fit."
  def words(nil), do: "nothing moved enough to tell"

  def words(%{quality: q, coherence: c, cx: cx}) do
    cond do
      is_nil(cx) or c > 0.85 -> "slides across the picture: the axis lies across the view — its direction is the dashed line; how far in or out, one camera can't say"
      q > 0.9 and c < 0.5 -> "turns about a point in the picture: the axis points roughly at the camera — the cross is where it comes through"
      c > 0.5 -> "mostly a slide with some turn: the axis crosses the view at an angle — the dashed line is its direction, the cross is a rough pivot"
      true -> "mostly a turn with some slide: the axis is tilted toward the camera — the cross is a rough pivot"
    end
  end
end
