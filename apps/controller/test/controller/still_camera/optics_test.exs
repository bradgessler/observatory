defmodule Controller.StillCamera.OpticsTest do
  @moduledoc """
  The telescope's focal length as a plate solve measures it: worked out from
  the sky a pixel covers and the size of the pixel, kept with the optics in
  Settings, and said to be from the solve or from the label.
  """
  use ExUnit.Case, async: false

  alias Controller.Settings
  alias Controller.StillCamera.Optics

  # the a6000's pixel: 23.5 mm of sensor across 6000 of them, 3.9 microns to one place
  @pixel_um 23.5 / 6000 * 1000

  setup do
    was = {Settings.get("focal_length_mm"), Settings.get("focal_length_solved")}

    on_exit(fn ->
      Settings.put("focal_length_mm", elem(was, 0))
      Settings.put("focal_length_solved", elem(was, 1))
    end)

    Settings.put("focal_length_mm", 2032)
    Settings.put("focal_length_solved", nil)
    :ok
  end

  test "the focal length is the pixel over the sky it covers: 0.388 arcsec a pixel through 3.9 micron pixels is 2,084 mm" do
    assert_in_delta @pixel_um, 3.9, 0.02
    assert_in_delta Optics.focal_length_mm(0.388, @pixel_um), 2084, 5
    # and it is the other way round from the scale a focal length gives (`Focus.arcsec_per_px/3`)
    assert_in_delta Controller.StillCamera.Focus.arcsec_per_px(Optics.focal_length_mm(0.388, @pixel_um), 23.5, 6000), 0.388, 1.0e-6

    # what is no scale or no pixel is no focal length
    for {scale, px} <- [{0, 3.9}, {-0.4, 3.9}, {0.388, 0}, {nil, 3.9}, {0.388, "3.9"}], do: assert(Optics.focal_length_mm(scale, px) == nil)
  end

  test "the first solve replaces the label and says so; later solves leave it alone" do
    assert Optics.focal_length() == %{mm: 2032, from: "label"}

    assert {:ok, mm} = Optics.learn(0.388, @pixel_um)
    assert_in_delta mm, 2084, 5
    assert Optics.focal_length() == %{mm: mm, from: "solve", label_mm: 2032}
    # it is the optics' focal length now: whatever reads it gets the measured one
    assert Settings.get("focal_length_mm") == mm
    assert %{"mm" => ^mm, "label_mm" => 2032, "arcsec_per_px" => 0.388, "pixel_um" => px, "at" => at} = Settings.get("focal_length_solved")
    assert_in_delta px, 3.917, 0.001
    assert {:ok, _, 0} = DateTime.from_iso8601(at)

    # learned from the first solve: the next one, a little different, doesn't move it
    assert Optics.learn(0.391, @pixel_um) == :kept
    assert Optics.focal_length().mm == mm
    # unless asked to
    assert {:ok, again} = Optics.learn(0.391, @pixel_um, again: true)
    assert again < mm
    assert %{mm: ^again, from: "solve", label_mm: 2032} = Optics.focal_length()
  end

  test "a focal length typed in afterwards (another telescope, a reducer) is a label again, until a solve measures that one" do
    {:ok, _} = Optics.learn(0.388, @pixel_um)
    Settings.put("focal_length_mm", 714)
    assert Optics.focal_length() == %{mm: 714, from: "label"}

    assert {:ok, mm} = Optics.learn(1.12, @pixel_um)
    assert_in_delta mm, 721, 2
    assert %{from: "solve", label_mm: 714} = Optics.focal_length()
  end

  test "with no focal length set there is none to give, and the first solve gives one" do
    Settings.put("focal_length_mm", nil)
    assert Optics.focal_length() == nil
    assert {:ok, mm} = Optics.learn(0.388, @pixel_um)
    assert Optics.focal_length() == %{mm: mm, from: "solve"}
  end

  test "a scale that is no scale teaches nothing" do
    assert Optics.learn(0, @pixel_um) == {:error, :no_scale}
    assert Optics.learn(0.388, nil) == {:error, :no_scale}
    assert Optics.focal_length() == %{mm: 2032, from: "label"}
  end
end
