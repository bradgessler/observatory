defmodule Controller.Sky.DitherTest do
  use ExUnit.Case, async: true
  alias Controller.Sky.Dither

  test "the offsets fill the disc and never repeat within a round" do
    offsets = for k <- 0..23, do: Dither.offset(k, 1.5)
    assert Enum.all?(offsets, fn {e, n} -> :math.sqrt(e * e + n * n) <= 1.5 end)
    # no two closer than the dust they are meant to step over would let through: a third of the radius
    pairs = for {a, i} <- Enum.with_index(offsets), {b, j} <- Enum.with_index(offsets), i < j, do: {a, b}
    assert Enum.all?(pairs, fn {{e1, n1}, {e2, n2}} -> :math.sqrt((e1 - e2) ** 2 + (n1 - n2) ** 2) > 0.2 end)
    # the next round starts again
    assert Dither.offset(24, 1.5) == Dither.offset(0, 1.5)
  end

  test "an offset east widens with the declination; north is plain arcminutes" do
    base = %{name: "M33", ra_deg: 23.46, dec_deg: 30.66}
    aim = Dither.aim(base, {1.0, 1.0})
    assert_in_delta aim.dec_deg - base.dec_deg, 1 / 60, 1.0e-9
    assert_in_delta (aim.ra_deg - base.ra_deg) * :math.cos(base.dec_deg * :math.pi() / 180), 1 / 60, 1.0e-9
    assert aim.name == "M33"
  end

  test "an aim across 0h of right ascension wraps" do
    aim = Dither.aim(%{ra_deg: 359.99, dec_deg: 0.0}, {1.2, 0.0})
    assert aim.ra_deg >= 0 and aim.ra_deg < 1
  end
end
