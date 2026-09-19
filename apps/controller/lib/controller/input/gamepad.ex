defmodule Controller.Input.Gamepad do
  @moduledoc """
  Turns a gamepad's state into mount motion. Pure functions; the state arrives
  from whatever node the pad is plugged into (browser Gamepad API on a laptop,
  evdev on a Pi) as `%{axes: [floats -1..1], buttons: [%{pressed, value}], hat: ...}`.

  Default mapping (SideWinder Dual Strike, but any pad with two axes works):

    * hold the **trigger** (button 0) and tilt the ball → RA from X, Dec from Y;
      tilt sets speed on a log scale, dead zone 12%, up to `max_rate`
    * **hat / D-pad** → fine nudges at `fine_rate` (no trigger needed)
    * button 1 → STOP

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
    dead: 0.12,
    max_rate: 800.0,
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
        x = axis(axes, m.x_axis) |> flip(m.invert_x)
        y = axis(axes, m.y_axis) |> flip(m.invert_y)
        mag = :math.sqrt(x * x + y * y)

        if mag < m.dead do
          :idle
        else
          # 0 at the dead zone edge → 1 at full tilt, then log speed 1×..max
          t = min((mag - m.dead) / (1 - m.dead), 1.0)
          rate = :math.pow(m.max_rate, t)
          scale = rate / max(abs(x), abs(y))
          {:move, [{:ra, x * scale}, {:dec, y * scale}] |> Enum.reject(fn {_, r} -> abs(r) < 0.5 end)}
        end

      hat(state) != nil ->
        {hx, hy} = hat(state)
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

  defp pressed?(buttons, i) do
    case Enum.at(buttons, i) do
      %{"pressed" => p} -> p == true
      %{pressed: p} -> p == true
      _ -> false
    end
  end

  # Hats arrive either as {x, y} in -1..1 or as a 0..7 direction; nil when centred.
  defp hat(%{hat: {x, y}}) when x != 0 or y != 0, do: {x, y}
  defp hat(%{"hat" => [x, y]}) when x != 0 or y != 0, do: {x, y}
  defp hat(%{"hat" => d}) when is_integer(d) and d in 0..7, do: Enum.at([{0, 1}, {1, 1}, {1, 0}, {1, -1}, {0, -1}, {-1, -1}, {-1, 0}, {-1, 1}], d)
  defp hat(_), do: nil
end
