defmodule Input.CurveTest do
  use ExUnit.Case, async: true
  alias Input.Curve

  test "the null zone is generous: a ball that looks centred does nothing" do
    for m <- [0.0, 0.1, 0.17, 0.29], do: assert(Curve.rate(m) == 0.0)
  end

  test "pedal to the metal is full speed well before the end of travel" do
    assert Curve.rate(0.85) == 800.0
    assert Curve.rate(0.97) == 800.0
    assert Curve.rate(1.0) == 800.0
  end

  test "just past the null zone is the slowest band, then it steps up" do
    assert Curve.rate(0.31) == 2.0
    rates = for m <- [0.31, 0.45, 0.55, 0.66, 0.77], do: Curve.rate(m)
    assert rates == [2.0, 8.0, 32.0, 200.0, 800.0]
  end

  test "bands are monotonic across the whole travel" do
    rates = for i <- 0..100, do: Curve.rate(i / 100)
    assert rates == Enum.sort(rates)
  end

  test "everything is a parameter" do
    opts = %{dead: 0.1, full: 0.5, bands: [1.0, 10.0]}
    assert Curve.rate(0.05, opts) == 0.0
    assert Curve.rate(0.2, opts) == 1.0
    assert Curve.rate(0.4, opts) == 10.0
    assert Curve.band(0.4, opts) == 2
    assert Curve.band(0.05, opts) == 0
  end
end
