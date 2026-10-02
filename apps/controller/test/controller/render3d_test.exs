defmodule Controller.Render3DTest do
  @moduledoc "A small 3-D renderer to SVG: solids, a perspective camera, the far side dropped, far painted before near."
  use ExUnit.Case, async: true

  alias Controller.Render3D, as: R

  @cam R.camera({0.0, 0.0, 0.0}, az: 150.0, el: 20.0, distance: 4.0, focal: 300.0)

  test "a box seen from outside shows at most three faces, and never its far side" do
    faces = R.box({0.0, 0.0, 0.0}, {1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {1.0, 1.0, 1.0}, :metal)
    assert length(faces) == 6
    seen = R.render(faces, @cam)
    assert length(seen) in 1..3
  end

  test "a cylinder has a face per side and two caps; about half its sides face the camera" do
    faces = R.cylinder({0.0, 0.0, -0.5}, {0.0, 0.0, 0.5}, 0.2, :tube, sides: 12)
    assert length(faces) == 14
    seen = R.render(faces, @cam)
    assert length(seen) in 6..9
  end

  test "far is painted before near" do
    near = R.box({0.6, -0.6, 0.0}, {1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.2, 0.2, 0.2}, :near)
    far = R.box({-0.6, 0.6, 0.0}, {1.0, 0.0, 0.0}, {0.0, 1.0, 0.0}, {0.2, 0.2, 0.2}, :far)
    order = R.render(near ++ far, @cam) |> Enum.map(& &1.mat) |> Enum.dedup()
    assert order == [:far, :near]
  end

  test "faces are shaded in eight steps by how squarely they face the light" do
    seen = R.render(R.cylinder({0.0, 0.0, -0.5}, {0.0, 0.0, 0.5}, 0.2, :tube, sides: 24), @cam)
    levels = Enum.map(seen, & &1.level)
    assert Enum.all?(levels, &(&1 in 0..7))
    assert Enum.max(levels) - Enum.min(levels) >= 3
  end

  test "perspective: the same thing nearer the camera is bigger" do
    {x1, _, _} = R.project({0.1, 0.0, 0.0}, @cam)
    {x0, _, _} = R.project({0.0, 0.0, 0.0}, @cam)
    near_cam = R.camera({0.0, 0.0, 0.0}, az: 150.0, el: 20.0, distance: 2.0, focal: 300.0)
    {n1, _, _} = R.project({0.1, 0.0, 0.0}, near_cam)
    {n0, _, _} = R.project({0.0, 0.0, 0.0}, near_cam)
    assert abs(n1 - n0) > abs(x1 - x0)
  end
end
