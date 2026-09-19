defmodule Input.Curve do
  @moduledoc """
  Raw displacement (0..1 from any control — ball, touch stick, tilt) → slew
  rate (× sidereal). One place for the feel, with everything as a parameter:

    * `dead`  — the null zone; inside it nothing moves (default 0.30, a ball
                that "looks centred" is often 0.15 off)
    * `full`  — where full speed begins (default 0.85; pedal to the metal
                shouldn't require the last 15% of travel)
    * `bands` — the rates available between `dead` and `full`, slowest first;
                the travel is split evenly across them. Bands make the feel
                predictable and keep the mount from flapping between its
                slow and fast microstep modes on every wobble.

  `rate/2` returns 0.0 inside the dead zone.
  """

  @defaults %{dead: 0.30, full: 0.85, bands: [2.0, 8.0, 32.0, 200.0, 800.0]}

  def defaults, do: @defaults

  @spec rate(number, map) :: float
  def rate(mag, opts \\ %{}) do
    %{dead: dead, full: full, bands: bands} = Map.merge(@defaults, opts)
    mag = mag |> abs() |> min(1.0)

    cond do
      mag < dead -> 0.0
      mag >= full -> List.last(bands) * 1.0
      true ->
        n = length(bands)
        t = (mag - dead) / max(full - dead, 1.0e-9)
        i = min(trunc(t * n), n - 1)
        Enum.at(bands, i) * 1.0
    end
  end

  @doc "Which band (1-based) a magnitude lands in, or 0 in the dead zone — for showing on a UI."
  def band(mag, opts \\ %{}) do
    %{dead: dead, full: full, bands: bands} = Map.merge(@defaults, opts)
    mag = mag |> abs() |> min(1.0)
    n = length(bands)

    cond do
      mag < dead -> 0
      mag >= full -> n
      true -> min(trunc((mag - dead) / max(full - dead, 1.0e-9) * n), n - 1) + 1
    end
  end
end
