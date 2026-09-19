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

  @doc "Plain words for a fit."
  def words(nil), do: "nothing moved enough to tell"

  def words(%{quality: q, coherence: c, cx: cx}) do
    cond do
      is_nil(cx) or c > 0.9 -> "slides across the picture — the axis lies across the view; the pivot is off-frame or ill-defined"
      q > 0.9 and c < 0.6 -> "turns about a point in the picture — the axis points roughly at the camera"
      true -> "somewhere between a spin and a slide — the axis is at an angle to the camera"
    end
  end
end
