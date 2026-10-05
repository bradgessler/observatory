defmodule Controller.LockOn.Law do
  @moduledoc """
  The arithmetic of holding a target still in the picture, whatever the
  mount's alignment. Pure: numbers in, numbers out.

  Two things are measured, in picture pixels per second:

    * the **drift**: how the target moves with the motors still (the sky
      turning, seen through however the mount is set up);
    * the **response**: how each motor moves the picture per 1× sidereal
      (`M`, a column per axis), from one short nudge of each.

  The picture then moves at `drift + M · rates`. Holding still is choosing
  rates that cancel the drift (`cancel/2`) plus a gentle pull of the target
  back to its spot (`rates/4`): proportional to how far off it is now, and a
  slow integral of how far off it has been. No polar alignment, no level
  tripod, no model of the sky: what the camera sees is the whole story.

  Vectors are `{x, y}`; matrices `{{a, b}, {c, d}}` (rows), so `M · {ra, dec}`
  is `{a·ra + b·dec, c·ra + d·dec}`.
  """

  @doc "A motor's column of `M`: how far the target `moved` (px) in `dt` s while that axis ran at `rate`× for `secs` s, net of the drift."
  def column({mx, my}, {dx, dy}, dt, rate, secs) do
    k = rate * secs
    {(mx - dx * dt) / k, (my - dy * dt) / k}
  end

  @doc "Two columns (RA, Dec) as `M`."
  def matrix({a, c}, {b, d}), do: {{a, b}, {c, d}}

  def det({{a, b}, {c, d}}), do: a * d - b * c

  @doc "`M⁻¹`, or `:singular` when the two motors move the picture the same way (no way to steer)."
  def inverse({{a, b}, {c, d}} = m) do
    dt = det(m)

    # relative to the columns' size: two columns far from parallel give |det| near |a||d|
    scale = :math.sqrt((a * a + c * c) * (b * b + d * d))

    if scale == 0 or abs(dt) / scale < 0.2,
      do: :singular,
      else: {{d / dt, -b / dt}, {-c / dt, a / dt}}
  end

  def mul({{a, b}, {c, d}}, {x, y}), do: {a * x + b * y, c * x + d * y}

  @doc "The rates that cancel the drift: the target stays where it is."
  def cancel(minv, {dx, dy}), do: mul(minv, {-dx, -dy})

  @doc """
  The rates for this moment: cancel the drift, and pull the target back by
  `k` of its offset per second plus `ki` of its accumulated offset, each
  axis clamped to `max_rate` (× sidereal).
  """
  def rates(cal, {ex, ey}, {ix, iy}, opts \\ []) do
    k = Keyword.get(opts, :k, 1 / 40)
    ki = Keyword.get(opts, :ki, 1 / 3000)
    max = Keyword.get(opts, :max_rate, 2.0)
    {ra0, dec0} = cancel(cal.minv, cal.drift)
    {pra, pdec} = mul(cal.minv, {-k * ex - ki * ix, -k * ey - ki * iy})
    {clamp(ra0 + pra, max), clamp(dec0 + pdec, max)}
  end

  @doc "The integral, kept from winding up while the target can't be reached."
  def integrate({ix, iy}, {ex, ey}, dt, limit \\ 3000.0) do
    {clamp(ix + ex * dt, limit), clamp(iy + ey * dt, limit)}
  end

  defp clamp(v, max), do: v |> min(max) |> max(-max)
end
