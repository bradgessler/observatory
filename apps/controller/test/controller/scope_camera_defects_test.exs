defmodule Controller.ScopeCamera.DefectsTest do
  @moduledoc """
  A speck at the same place in the picture whichever way the telescope
  points is the sensor's, not a star: the first night's 284 false stars.
  """
  use ExUnit.Case, async: true

  alias Controller.ScopeCamera.Defects

  # the warm cluster at (732, 70) on the first night, seen while the mount moved 25° in RA
  @spot %{x: 732, y: 70}

  test "a speck at the same pixels from three pointings a field apart becomes a defect" do
    d = Defects.new()
    {d, false} = Defects.learn(d, [@spot], {9_028_952, 8_211_532})
    {d, false} = Defects.learn(d, [@spot], {9_400_000, 8_500_000})
    refute Defects.defect?(d, 732, 70)
    {d, true} = Defects.learn(d, [%{x: 733, y: 69}], {9_667_728, 8_802_096})
    assert Defects.defect?(d, 731, 71)
    refute Defects.defect?(d, 700, 70)
  end

  test "a star the mount holds still (tracking, or near the pole) is never one: one pointing, however many pictures" do
    d = Enum.reduce(1..50, Defects.new(), fn _, d -> d |> Defects.learn([@spot], {9_028_952, 8_211_532}) |> elem(0) end)
    refute Defects.defect?(d, 732, 70)
  end

  test "nudges within a field don't count as different pointings" do
    d = Enum.reduce([0, 2_000, 4_000, 6_000], Defects.new(), fn step, d -> d |> Defects.learn([@spot], {11_000 * 800 + step, 0}) |> elem(0) end)
    refute Defects.defect?(d, 732, 70)
  end

  test "with no mount nothing is learned, and the known ones survive a restart" do
    assert {%Defects{seen: seen}, false} = Defects.learn(Defects.new(), [@spot], nil)
    assert seen == %{}
    d = Defects.new([[183, 17]])
    assert Defects.defect?(d, 732, 70)
    assert Defects.cells(d) == [[183, 17]]
    assert Defects.new(Defects.cells(d)) == d
  end

  test "split keeps the stars and sets the defects aside" do
    d = Defects.new([[183, 17]])
    assert {[%{x: 400, y: 300}], [%{x: 732, y: 70}]} = Defects.split(d, [%{x: 400, y: 300}, %{x: 732, y: 70}])
  end

  test "a mount snapshot's pointing: its two axes in steps, only while connected" do
    assert Defects.pointing(%{connected: true, axes: %{ra: %{steps: 1}, dec: %{steps: 2}}}) == {1, 2}
    assert Defects.pointing(%{connected: false, axes: %{ra: %{steps: 1}, dec: %{steps: 2}}}) == nil
    assert Defects.pointing(nil) == nil
  end
end
