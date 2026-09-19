defmodule Controller.Optical.RigTest do
  use ExUnit.Case, async: true
  alias Controller.Optical.Rig

  @sweep %{
    "hfov_deg" => 70,
    "ra" => %{"w" => 640, "h" => 360, "scale" => 2, "fit" => %{"dir" => [0.0, -0.8, 0.6], "point" => [0.0, 0.0, 1.0], "sense" => 1.0, "tilt_ambiguous" => false}},
    "dec" => %{"fit" => %{"dir" => [1.0, 0.0, 0.0], "point" => [0.05, 0.0, 1.0], "sense" => 1.0, "tilt_ambiguous" => false}}
  }

  test "a rig is built from a resolved sweep and the Dec axis turns about the polar axis with RA" do
    rig = Rig.from_sweep(@sweep, %{ra: 10.0, dec: 0.0})
    assert rig
    p0 = Rig.pose(rig, %{ra: 10.0, dec: 0.0})
    p1 = Rig.pose(rig, %{ra: 100.0, dec: 0.0})
    # at the reference the Dec axis is the fitted one; 90° of RA later it is perpendicular to that
    dot = Enum.zip(Tuple.to_list(p0.dec_dir), Tuple.to_list(p1.dec_dir)) |> Enum.map(fn {a, b} -> a * b end) |> Enum.sum()
    assert_in_delta dot, 0.0, 0.05
    # the polar line does not move
    assert p0.polar == p1.polar
  end

  test "an unresolved tilt gives no rig" do
    sweep = put_in(@sweep, ["ra", "fit", "tilt_ambiguous"], true)
    assert Rig.from_sweep(sweep, %{ra: 0.0, dec: 0.0}) == nil
  end
end
