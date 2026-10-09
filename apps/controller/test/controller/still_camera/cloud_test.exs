defmodule Controller.StillCamera.CloudTest do
  @moduledoc """
  Cloud, on pictures and runs made here. A star's light is checked on stars
  whose light is known (made in light, then bent into a JPEG's levels the way
  a camera bends them), and the verdict on runs of frames where the stars'
  light and the sky's are set by hand: thin cloud dims the one and brightens
  the other, and only both together are cloud.
  """
  use ExUnit.Case, async: true

  alias Controller.StillCamera.Cloud

  # -- pictures -----------------------------------------------------------------------------------

  # A grey picture made in light and bent into levels as a camera's JPEG is (a power of 1/2.2):
  # a sky of `sky` light, and Gaussian stars `{x, y, peak light}` 1.5 px in sigma, each `stars`
  # times as bright.
  defp picture(w, h, at, opts \\ []) do
    sky = Keyword.get(opts, :sky, 2.0)
    dim = Keyword.get(opts, :stars, 1.0)
    sigma = Keyword.get(opts, :sigma, 1.5)

    light =
      for {cx, cy, peak} <- at, y <- (cy - 8)..(cy + 8), x <- (cx - 8)..(cx + 8), reduce: %{} do
        acc -> Map.update(acc, {x, y}, peak * dim * :math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma * sigma)), &(&1 + peak * dim * :math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma * sigma))))
      end

    px = for y <- 0..(h - 1), x <- 0..(w - 1), into: <<>>, do: <<level(sky + Map.get(light, {x, y}, 0.0))>>
    %{w: w, h: h, px: px}
  end

  defp level(light), do: round(255 * :math.pow(min(light, 255.0) / 255, 1 / 2.2))

  @stars [{40, 40, 60.0}, {120, 50, 120.0}, {200, 45, 30.0}, {60, 130, 90.0}, {150, 140, 45.0}, {230, 120, 75.0}]
  defp marks(stars \\ @stars), do: for({x, y, _} <- stars, do: %{x: x, y: y})

  describe "a star's light" do
    test "is what stands above the sky in a disc round it, in light: twice the star reads twice, whatever the sky" do
      lights = Cloud.light(picture(280, 180, @stars), marks())
      assert length(lights) == 6
      by = Map.new(lights, &{{&1.x, &1.y}, &1.light})
      # 60 against 120 against 30 of peak light
      assert_in_delta by[{120, 50}] / by[{40, 40}], 2.0, 0.06
      assert_in_delta by[{40, 40}] / by[{200, 45}], 2.0, 0.08
      # and the sky round each, in levels (2 of 255 of light is level 28)
      assert Enum.all?(lights, &(abs(&1.sky - 28) < 1.0))
    end

    test "the same stars 25 percent dimmer under a sky twice as bright read 25 percent dimmer" do
      clear = Cloud.light(picture(280, 180, @stars), marks())
      cloudy = Cloud.light(picture(280, 180, @stars, stars: 0.75, sky: 4.0), marks())

      for {a, b} <- Enum.zip(clear, cloudy) do
        assert_in_delta b.light / a.light, 0.75, 0.04
        # twice the light of sky is 1.37 times the level
        assert_in_delta b.sky / a.sky, 1.37, 0.05
      end

      # Read in the JPEG's own levels the answer is another one: a brighter sky sits where the
      # camera's curve is flatter, so the same light is fewer levels. Levels are straightened first.
      level = fn pic -> Cloud.light(pic, marks(), gamma: 1.0) |> Enum.map(& &1.light) |> Enum.sum() end
      refute_in_delta level.(picture(280, 180, @stars, stars: 0.75, sky: 4.0)) / level.(picture(280, 180, @stars)), 0.75, 0.03
    end

    test "a saturated star, one at the edge, and a place with no star are left out; the rest keep their order" do
      stars = [{40, 40, 60.0}, {120, 50, 400.0}, {200, 45, 30.0}]
      pic = picture(280, 180, stars)
      marks = marks(stars) ++ [%{x: 3, y: 90}, %{x: 100, y: 140}]
      assert [%{x: 40, y: 40}, %{x: 200, y: 45}] = Cloud.light(pic, marks)
      # the level a star is left out at is a knob
      assert [_, %{x: 120, y: 50}, _] = Cloud.light(pic, marks(stars), saturation: 256)
      # so are the disc and the window: a wider disc holds more of a star's light
      [narrow] = Cloud.light(pic, [%{x: 40, y: 40}], radius: 2)
      [wide] = Cloud.light(pic, [%{x: 40, y: 40}], radius: 5)
      assert wide.light > narrow.light
    end

    test "a PGM is read as well as a picture, and odd input is no stars, never a crash" do
      pic = picture(280, 180, @stars)
      assert Cloud.light(Controller.ScopeCamera.Image.pgm(pic), marks()) == Cloud.light(pic, marks())
      assert Cloud.light("not a picture", marks()) == []
      assert Cloud.light(pic, nil) == []
      assert Cloud.light(pic, [%{x: nil, y: 4}, :nonsense]) == []
      assert Cloud.light(nil, []) == []
    end
  end

  # -- runs of frames -----------------------------------------------------------------------------

  # A frame as the still camera hands it over: each star's light and the sky round it, the whole
  # picture's sky, and where it was taken from. `stars` and `sky` are how many times as bright
  # each is as in the clear frame; `shift` moves every star (the pointing drifting).
  defp frame(opts \\ []) do
    dim = Keyword.get(opts, :stars, 1.0)
    sky = Keyword.get(opts, :sky, 1.0)
    {dx, dy} = Keyword.get(opts, :shift, {0, 0})

    stars =
      for {{x, y, light}, i} <- Enum.with_index(@stars), i < Keyword.get(opts, :count, 6) do
        %{x: x + dx, y: y + dy, light: light * dim, sky: 15.0 * sky}
      end

    %{stars: stars, sky: 15 * sky, place: Keyword.get(opts, :place)}
  end

  # a run through `Cloud.judge/3`: every frame's verdict
  defp run(frames, opts \\ []) do
    {verdicts, _field} = Enum.map_reduce(frames, nil, fn frame, field -> Cloud.judge(field, frame, opts) end)
    verdicts
  end

  describe "a run of frames" do
    test "star light down 25 percent and the sky doubled for three frames: those three are flagged, and the count of good frames does not move for them" do
      cloud = frame(stars: 0.75, sky: 2.0)
      verdicts = run([frame(), frame(), frame(), frame(), cloud, cloud, cloud, frame(), frame()])

      assert Enum.map(verdicts, & &1.cloud) == [false, false, false, false, true, true, true, false, false]
      assert Enum.map(verdicts, & &1.transparency) == [1.0, 1.0, 1.0, 1.0, 0.75, 0.75, 0.75, 1.0, 1.0]
      assert %{stars: 6, sky_ratio: 2.0} = Enum.at(verdicts, 4)
      # the first picture of a field is its own yardstick, and says so
      assert hd(verdicts)[:first] == true

      # good frames, counted as the still camera counts them: every one that isn't flagged
      counts = verdicts |> Enum.scan(0, fn v, n -> if v.cloud == true, do: n, else: n + 1 end)
      assert counts == [1, 2, 3, 4, 4, 4, 4, 5, 6]
    end

    test "only both together are cloud: dimmer stars under the same sky are not (focus, dew), nor a brighter sky over the same stars (the Moon, a lamp)" do
      assert [_, %{cloud: false, transparency: 0.7, sky_ratio: 1.0}] = run([frame(), frame(stars: 0.7)])
      assert [_, %{cloud: false, transparency: 1.0, sky_ratio: 3.0}] = run([frame(), frame(sky: 3.0)])
      assert [_, %{cloud: true}] = run([frame(), frame(stars: 0.7, sky: 1.2)])
      # 20 percent dimmer is the line, and it is not crossed at 15
      assert [_, %{cloud: false, transparency: 0.85}] = run([frame(), frame(stars: 0.85, sky: 1.5)])
    end

    test "the limits are the caller's: how much dimmer, how much brighter a sky" do
      thin = [frame(), frame(stars: 0.88, sky: 1.3)]
      assert [_, %{cloud: false}] = run(thin)
      assert [_, %{cloud: true}] = run(thin, dimmer: 0.1)
      assert [_, %{cloud: false}] = run(thin, dimmer: 0.1, sky: 1.5)
      # and how many stars it takes to say anything: two of them say nothing by default
      assert [_, %{cloud: nil, transparency: nil}] = run([frame(), frame(stars: 0.5, sky: 1.2, count: 2)])
      assert [_, %{cloud: true, transparency: 0.5, stars: 2}] = run([frame(), frame(stars: 0.5, sky: 1.2, count: 2)], min_stars: 2)
    end

    test "thick cloud: the stars it knew are gone under a far brighter sky. Cloud, with no transparency to give" do
      gone = %{stars: [], sky: 60}
      assert [_, %{cloud: true, transparency: nil, stars: 0, sky_ratio: 4.0}] = run([frame(), gone])
      # gone under the same sky is something else (a cap, a dew shield): it can't be said
      assert [_, %{cloud: nil, transparency: nil}] = run([frame(), %{stars: [], sky: 15}])
      # how much brighter counts as "far" is a knob
      assert [_, %{cloud: nil}] = run([frame(), gone], lost_sky: 5.0)
      # and the field is still there when the stars come back
      assert [_, _, %{cloud: false, transparency: 1.0}] = run([frame(), gone, frame()])
    end

    test "a clearer picture than the clearest so far becomes the yardstick" do
      # the run starts in thin cloud: nothing to hold the first picture against
      verdicts = run([frame(stars: 0.6, sky: 1.8), frame(stars: 0.6, sky: 1.8), frame(), frame(stars: 0.6, sky: 1.8), frame()])
      assert Enum.map(verdicts, & &1.cloud) == [false, false, false, true, false]
      assert [1.0, 1.0, clearer, 0.6, 1.0] = Enum.map(verdicts, & &1.transparency)
      assert_in_delta clearer, 1 / 0.6, 0.01
    end

    test "a field the pointing drifts across is followed, a few pixels a picture" do
      drifting = for i <- 0..9, do: frame(shift: {3 * i, -2 * i}, stars: if(i == 6, do: 0.7, else: 1.0), sky: if(i == 6, do: 1.5, else: 1.0))
      verdicts = run(drifting)
      assert Enum.map(verdicts, & &1.stars) == List.duplicate(6, 10)
      assert Enum.map(verdicts, & &1.cloud) == [false, false, false, false, false, false, true, false, false, false]
      # further in one step than a star may be from where it was last seen: other stars are where
      # those were, there is nothing to compare, and nothing is said (thick cloud leaves no stars at all)
      assert [_, %{cloud: nil, stars: 0}] = run([frame(), frame(shift: {40, 0}, stars: 0.5, sky: 2.0)])
      assert [_, %{cloud: true, stars: 6}] = run([frame(), frame(shift: {40, 0}, stars: 0.5, sky: 2.0)], tolerance: 50)
    end

    test "a star not seen before joins as bright as it would be in the clearest picture" do
      # two stars come out from behind a tree in a cloudy frame, and are held to that from then on
      verdicts = run([frame(count: 4), frame(stars: 0.5, sky: 2.0), frame(), frame(stars: 0.5, sky: 2.0)])
      assert [%{stars: 4}, %{stars: 4, transparency: 0.5}, %{stars: 6, transparency: 1.0}, %{stars: 6, transparency: 0.5}] = verdicts
    end
  end

  describe "a field" do
    @place %{camera: "a6000", mount: "eq6r", target: "M31", settings: {3200, "20"}, slewed: {12.0, -30.0}}
    defp cloudy(place), do: frame(stars: 0.6, sky: 2.0, place: place)

    test "starts again when the mount has slewed further than the field is wide, and not for a nudge" do
      nudged = %{@place | slewed: {12.2, -30.1}}
      away = %{@place | slewed: {14.0, -30.0}}
      assert [_, %{cloud: true}] = run([frame(place: @place), cloudy(nudged)], field_deg: 0.66)
      # another field: these stars have nothing to do with those, and this picture is the yardstick now
      assert [_, %{cloud: false, transparency: 1.0, first: true}] = run([frame(place: @place), cloudy(away)], field_deg: 0.66)
      # with no field width to go by, any slew is another field
      assert [_, %{first: true}] = run([frame(place: @place), cloudy(nudged)])
      assert Cloud.moved?(@place, nudged, nil) and not Cloud.moved?(@place, nudged, 0.66) and Cloud.moved?(@place, away, 0.66)
      # the move is measured from the picture before, so a field nudged across the sky is one field
      steps = for i <- 0..5, do: frame(place: %{@place | slewed: {12.0 + 0.3 * i, -30.0}})
      assert run(steps, field_deg: 0.66) |> tl() |> Enum.all?(&(&1[:first] != true))
    end

    test "starts again when the target, the camera, the mount, or the ISO or shutter speed changes" do
      for other <- [%{@place | target: "M33"}, %{@place | camera: "other"}, %{@place | mount: "other"}, %{@place | settings: {800, "20"}}, %{@place | settings: {3200, "10"}}] do
        assert Cloud.moved?(@place, other, 0.66)
        assert [_, %{first: true, cloud: false}] = run([frame(place: @place), cloudy(other)], field_deg: 0.66)
      end

      # what a place doesn't say is taken to be the same: no mount, no target, no place at all
      refute Cloud.moved?(@place, %{@place | target: nil, mount: nil, slewed: nil}, 0.66)
      refute Cloud.moved?(nil, @place, 0.66)
      assert [_, %{cloud: true}] = run([frame(place: @place), cloudy(nil)], field_deg: 0.66)
    end

    test "with no stars in it is no yardstick: the first picture that has some starts one" do
      assert [%{cloud: nil, transparency: nil, stars: 0}, %{cloud: false, transparency: 1.0, first: true}, %{cloud: true}] =
               run([%{stars: [], sky: 15}, frame(stars: 0.5, sky: 2.0), frame(stars: 0.3, sky: 3.0)])
    end

    test "remembers only so many stars, the ones seen last" do
      many = for i <- 0..79, do: %{x: 20 * rem(i, 10), y: 20 * div(i, 10), light: 100.0, sky: 15.0}
      {_, field} = Cloud.judge(nil, %{stars: many, sky: 15})
      assert length(field.stars) == 80
      {_, field} = Cloud.judge(field, %{stars: Enum.take(many, 30), sky: 15})
      assert length(field.stars) == 60
      assert Enum.all?(Enum.take(many, 30), fn s -> Enum.any?(field.stars, &(&1.x == s.x and &1.y == s.y)) end)
      {_, field} = Cloud.judge(field, %{stars: Enum.take(many, 30), sky: 15}, keep: 30)
      assert length(field.stars) == 30
    end
  end

  test "odd input says nothing and leaves the field as it was" do
    {_, field} = Cloud.judge(nil, frame())
    assert {%{cloud: nil, transparency: nil}, ^field} = Cloud.judge(field, nil)
    assert {%{cloud: nil}, ^field} = Cloud.judge(field, %{stars: :nonsense, sky: 15})
    assert {%{cloud: nil}, ^field} = Cloud.judge(field, %{stars: [], sky: nil})
    # stars that are no stars are passed over
    assert {%{stars: 6, transparency: 1.0}, _} = Cloud.judge(field, %{frame() | stars: frame().stars ++ [%{x: 1}, nil, %{x: 5, y: 5, light: -3.0}]})
  end
end
