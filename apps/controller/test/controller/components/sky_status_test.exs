defmodule Controller.Components.SkyStatusTest do
  @moduledoc """
  The solar graph in the Sky toolbar: the Sun's height from noon to noon,
  drawn in line. The horizon across, the Sun's path bright above it and dim
  below, the daylight under the path while the Sun is up, a step under the
  horizon while it is in twilight, a dot at the time shown. No ground slab:
  it was a filled rectangle the lower half of the graph, the one thing in
  the toolbar that wasn't line or type. The tones are checked from the
  stylesheet in design_test.exs; this checks what is drawn.
  """
  use ExUnit.Case, async: true
  import Phoenix.LiveViewTest

  alias Controller.Components.SkyStatus

  # the graph's own geometry: 144 by 40, the horizon half way down, 18° of twilight under it
  @w 144.0
  @horizon 20.0
  @twilight 4.7

  @home %{lat: 37.877, lon: -122.180, set: true}
  # 01:00 in the morning there (UTC-7), early October: dark, a night with twilight at both ends
  @night ~U[2026-10-04 08:00:00Z]

  defp info(at, site \\ @home, off \\ -420), do: SkyStatus.sun_info(at, site, off)

  defp xy(points), do: for(p <- String.split(points), do: p |> String.split(",") |> Enum.map(&String.to_float/1) |> List.to_tuple())

  test "the Sun's path is cut at the horizon: up, down through the night, up again" do
    sun = info(@night)
    assert [:up, :down, :up] = Enum.map(sun.runs, &elem(&1, 0))
    [day1, night, day2] = for {_, points} <- sun.runs, do: xy(points)

    # one line, noon to noon: each run starts where the last ended, on the horizon
    assert hd(day1) |> elem(0) == 0.0
    assert List.last(day2) |> elem(0) == @w
    assert List.last(day1) == hd(night) and List.last(night) == hd(day2)
    assert {_, @horizon} = hd(night)
    assert {_, @horizon} = List.last(night)

    # above the horizon is up the graph (a smaller y), below it is down
    assert Enum.all?(day1 ++ day2, fn {_, y} -> y <= @horizon end)
    assert Enum.all?(night, fn {_, y} -> y >= @horizon end)
  end

  test "daylight is the area under the path while the Sun is up, closed along the horizon" do
    sun = info(@night)
    assert length(sun.day) == 2

    for points <- sun.day do
      shape = xy(points)
      assert {_, @horizon} = hd(shape)
      assert {_, @horizon} = List.last(shape)
      assert Enum.all?(shape, fn {_, y} -> y <= @horizon end)
    end
  end

  test "twilight is a step at each end of the night, and the dark is the gap between them" do
    sun = info(@night)
    {_, night} = Enum.at(sun.runs, 1)
    {sunset, _} = hd(xy(night))
    {sunrise, _} = List.last(xy(night))

    assert [dusk, dawn] = sun.twilight
    # dusk starts at sunset, dawn ends at sunrise, each about an hour and a half (6 px an hour)
    assert dusk.x == sunset
    assert_in_delta dawn.x + dawn.width, sunrise, 0.11
    for t <- [dusk, dawn], do: assert(t.width > 6 and t.width < 14)
    # the time shown is in the gap: it is dark
    assert sun.key == :dark
    assert sun.x > dusk.x + dusk.width and sun.x < dawn.x
    assert sun.y > @horizon + @twilight
  end

  test "a night that never gets dark is twilight from sunset to sunrise" do
    # 60° north at midsummer: the Sun dips 6.6° under the horizon and no further
    sun = info(~U[2026-06-21 22:00:00Z], %{lat: 60.0, lon: 0.0, set: true}, 0)
    assert [:up, :down, :up] = Enum.map(sun.runs, &elem(&1, 0))
    {_, night} = Enum.at(sun.runs, 1)
    {sunset, _} = hd(xy(night))
    {sunrise, _} = List.last(xy(night))

    assert [all_night] = sun.twilight
    assert all_night.x == sunset
    assert_in_delta all_night.x + all_night.width, sunrise, 0.11
  end

  test "the midnight Sun is one run above the horizon, the polar night one below it and dark" do
    summer = info(~U[2026-06-21 12:00:00Z], %{lat: 78.0, lon: 15.0, set: true}, 60)
    assert [{:up, _}] = summer.runs
    assert [_] = summer.day
    assert summer.twilight == []

    winter = info(~U[2026-12-21 12:00:00Z], %{lat: 88.0, lon: 15.0, set: true}, 60)
    assert [{:down, _}] = winter.runs
    assert winter.day == []
    assert winter.twilight == []
    assert winter.key == :dark
  end

  test "it draws in line, at the size the toolbar is laid out for, with nothing filled under the horizon but twilight" do
    html =
      render_component(&SkyStatus.bar/1,
        at: @night,
        shift_min: 0,
        lst: 10.0,
        utc_offset_min: -420,
        site: @home,
        sun: info(@night)
      )

    svg = html |> LazyHTML.from_fragment() |> LazyHTML.query(".ss-sun svg")
    assert LazyHTML.attribute(svg, "width") == ["144"]
    assert LazyHTML.attribute(svg, "height") == ["40"]

    drawn = for {tag, attrs, _} <- hd(LazyHTML.to_tree(svg)) |> elem(2), do: {tag, Enum.find_value(attrs, fn {k, v} -> k == "class" && v end)}

    # back to front: daylight, twilight, the horizon, the path, the dot on its halo
    assert drawn == [
             {"polygon", "sg-day"},
             {"polygon", "sg-day"},
             {"rect", "sg-twilight"},
             {"rect", "sg-twilight"},
             {"line", "sg-horizon"},
             {"polyline", "sg-curve sg-up"},
             {"polyline", "sg-curve sg-down"},
             {"polyline", "sg-curve sg-up"},
             {"circle", "sg-halo"},
             {"circle", "sg-sun"}
           ]

    # the only rectangles are the twilight steps: under the horizon, as deep as twilight goes, a few px wide
    for rect <- LazyHTML.query(svg, "rect") do
      assert LazyHTML.attribute(rect, "y") == ["#{@horizon}"]
      assert LazyHTML.attribute(rect, "height") == ["#{@twilight}"]
      [width] = LazyHTML.attribute(rect, "width")
      assert String.to_float(width) < 14
    end

    # the words say the same without the picture
    assert html =~ ~s(role="img")
    assert html =~ ~s(aria-label="Dark. Astronomical twilight at)
    assert html =~ "ss-dark"
  end
end
