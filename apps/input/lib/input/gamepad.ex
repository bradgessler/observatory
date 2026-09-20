defmodule Input.Gamepad do
  @moduledoc """
  Turns a gamepad's state into mount motion. Pure functions; the state comes
  from `Input.Device` (server-side HID) as `%{axes: [floats -1..1],
  buttons: [bool], hat: {x, y} | nil}`.

  Default mapping (SideWinder Dual Strike, but any pad with two axes works):

    * hold the **trigger** (button index `trigger`) and tilt the ball → RA from X,
      Dec from Y; tilt sets speed on a log scale, dead zone, up to `max_rate`
    * **hat / D-pad** → fine nudges at `fine_rate` (no trigger needed)
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
    fine_rate: 8.0
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
        {:nudge, [{:ra, hx * m.fine_rate}, {:dec, hy * m.fine_rate}] |> Enum.reject(fn {_, r} -> r == 0 end)}

      true ->
        :idle
    end
  end

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
