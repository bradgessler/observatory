defmodule Controller.Sky.SceneTest do
  use ExUnit.Case, async: true

  alias Controller.Sky.Scene

  # mid-latitude north, an October noon (19:00 UTC is noon in California)
  @site %{lat: 37.9, lon: -122.2, name: "test"}
  @noon ~U[2026-10-02 19:00:00Z]
  @flat Map.new(~w(N NE E SE S SW W NW), &{&1, 0})

  describe "night_path/4: one object's night, by how dark the sky is" do
    test "from a daytime moment it runs through the whole night ahead to dawn" do
      scene = Scene.build(@noon, @site, @flat, view: :dome, trees: false, sky: false)
      # Capella: up most of the night from here, and in the sky at noon too
      path = Scene.night_path(scene, 79.17, 45.998, -420)

      assert DateTime.diff(path.until, @noon, :hour) in 16..19
      # it passes through all three: daylight now, twilight, then full dark
      assert Enum.sort(path.classes) == ~w(dark day twilight)
      # the first stretch is daylight; the line never breaks between kinds
      assert hd(path.segments).class == "day"
      assert Enum.all?(path.segments, &(&1.class in ~w(dark twilight day)))
    end

    test "a dot at each whole hour of the viewer's time while it's up, named by that time" do
      scene = Scene.build(@noon, @site, @flat, view: :horizon, trees: false, sky: false)
      path = Scene.night_path(scene, 79.17, 45.998, -420)

      assert path.hours != []
      assert Enum.all?(path.hours, &String.ends_with?(&1.label, ":00"))
      # 19:00 UTC is 12:00 at -7 h; the first whole hour after it is 13:00 local
      assert hd(path.hours).label == "13:00"
    end

    test "below the horizon now: no ring, and its path starts where it rises" do
      scene = Scene.build(@noon, @site, @flat, view: :dome, trees: false, sky: false)
      # Fomalhaut in October: near its lowest at noon, up in the evening
      path = Scene.night_path(scene, 344.413, -29.622, -420)

      assert path.now == nil
      assert path.segments != []
    end

    test "a chart with no stars: the frame, the grid and the trees only" do
      scene = Scene.build(@noon, @site, @flat, view: :dome, trees: false, sky: false)
      assert scene.stars == [] and scene.dsos == [] and scene.lines == []
      assert scene.grid.lines != []
    end
  end
end
