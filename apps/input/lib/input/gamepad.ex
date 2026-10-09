defmodule Input.Gamepad do
  @moduledoc """
  Turns a gamepad's state into mount motion. Pure functions; the state comes
  from `Input.Device` (server-side HID) as `%{axes: [floats -1..1],
  buttons: [bool], hat: {x, y} | nil}`.

  Default mapping (SideWinder Dual Strike, but any pad with two axes works):

    * hold the **trigger** (button index `trigger`) and tilt the ball → RA from X,
      Dec from Y; tilt sets speed on a log scale, dead zone, up to `max_rate`
    * **hat / D-pad** → fine nudges at `fine_rate` (no trigger needed; it
      springs back to centre, so letting go is the stop). With `hat:
      :eyepiece` it moves the view as it looks in the eyepiece instead of the
      axes as they are: `view_down`/`view_right` say which axis and sign move
      the view down and right (the Center page's map), a tap crawls at
      `fine_slow`, a hold past `fine_ramp_ms` goes at `fine_rate` and past
      `fine_top_ms` at `fine_top`, and RA
      carries on from `track_units` so the view moves against the sky
    * **centered** button (nil: none) → "it's on the crosshair"
    * button `stop` → STOP

  Everything is a parameter so a different pad is a different map, not code.
  """

  @type rates :: [{:ra | :dec, float}]

  @defaults %{
    trigger: 0,
    stop: 1,
    x_axis: 0,
    y_axis: 1,
    invert_x: false,
    invert_y: true,
    # feel: see Input.Curve — null zone, where full speed starts, the bands
    dead: 0.30,
    full: 0.85,
    # where the ball rested when the trigger was squeezed; the mapper sets it on each press
    center: [0.0, 0.0],
    bands: [2.0, 8.0, 32.0, 200.0, 800.0],
    fine_rate: 8.0,
    hat: :axes,
    view_down: {:ra, 1},
    view_right: {:dec, -1},
    fine_slow: 2.0,
    fine_ramp_ms: 1_500,
    # held on past this, a big object's worth of sky: across the Pleiades in seconds
    fine_top: 32.0,
    fine_top_ms: 4_000,
    # what RA already runs at (× sidereal): the mapper sets it when the hat goes down
    track_units: 0.0,
    hat_held_ms: 0,
    centered: nil
  }

  def defaults, do: @defaults

  @doc """
  `{:move, rates}` while the trigger is held and the ball is off centre,
  `{:nudge, rates}` for the hat, `:stop` for the stop button, `:idle` otherwise.
  """
  def interpret(state, map \\ %{}) do
    m = Map.merge(@defaults, map)
    axes = state[:axes] || []
    buttons = state[:buttons] || []

    cond do
      pressed?(buttons, m.stop) ->
        :stop

      pressed?(buttons, m.trigger) ->
        [cx, cy] = m.center
        x = (axis(axes, m.x_axis) - cx) |> flip(m.invert_x)
        y = (axis(axes, m.y_axis) - cy) |> flip(m.invert_y)
        mag = :math.sqrt(x * x + y * y)
        # the feel lives in Input.Curve: null zone, saturation, speed bands
        rate = Input.Curve.rate(mag, %{dead: m.dead, full: m.full, bands: m.bands})

        if rate == 0.0 do
          :idle
        else
          scale = rate / max(abs(x), abs(y))
          # an axis under a third of the pull doesn't move: a pull is mostly one axis
          {:move,
           [{:ra, x * scale}, {:dec, y * scale}]
           |> Enum.reject(fn {_, r} -> abs(r) < rate / 3 end)}
        end

      state[:hat] != nil ->
        {hx, hy} = state.hat
        {:nudge, hat_rates(m.hat, hx, hy, m)}

      true ->
        :idle
    end
  end

  defp hat_rates(:eyepiece, hx, hy, m) do
    rate =
      cond do
        m.hat_held_ms >= m.fine_top_ms -> m.fine_top
        m.hat_held_ms >= m.fine_ramp_ms -> m.fine_rate
        true -> m.fine_slow
      end
    {ax_r, s_r} = m.view_right
    {ax_d, s_d} = m.view_down
    # y is up on the hat; the map says what moves the view down
    rel = Enum.reduce([{ax_r, hx * s_r * rate}, {ax_d, -hy * s_d * rate}], %{}, fn {a, r}, acc -> Map.update(acc, a, r, &(&1 + r)) end)

    for axis <- [:ra, :dec], r = Map.get(rel, axis, 0.0), r != 0 do
      {axis, if(axis == :ra, do: m.track_units + r, else: r / 1)}
    end
  end

  defp hat_rates(_axes, hx, hy, m),
    do: [{:ra, hx * m.fine_rate}, {:dec, hy * m.fine_rate}] |> Enum.reject(fn {_, r} -> r == 0 end)

  @doc "Human line for the UI: what the pad is asking for."
  def describe(:idle), do: "idle · hold the trigger and tilt"
  def describe(:stop), do: "STOP"
  def describe({:move, rates}), do: "move " <> rates_text(rates)
  def describe({:nudge, rates}), do: "nudge " <> rates_text(rates)

  defp rates_text(rates),
    do: Enum.map_join(rates, " · ", fn {a, r} -> "#{a} #{if r >= 0, do: "+", else: "−"}#{round(abs(r))}×" end)

  defp axis(axes, i) do
    case Enum.at(axes, i) do
      v when is_number(v) -> v |> max(-1.0) |> min(1.0)
      _ -> 0.0
    end
  end

  defp flip(v, true), do: -v
  defp flip(v, false), do: v

  defp pressed?(buttons, i), do: Enum.at(buttons, i) == true
end
