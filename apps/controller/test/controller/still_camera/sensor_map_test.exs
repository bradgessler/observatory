defmodule Controller.StillCamera.SensorMapTest do
  use ExUnit.Case, async: true
  alias Controller.StillCamera.SensorMap

  @w 960
  @h 640

  # a grey copy: sky at 40, stars scattered by `seed` (a different place in the sky), and, when
  # `dust` is given, a disc of the sensor `{x, y, r}` passing 88% of the light
  defp picture(seed, dust) do
    :rand.seed(:exsss, {seed, seed * 7, seed * 13})
    stars = for _ <- 1..60, do: {:rand.uniform(@w) - 1, :rand.uniform(@h) - 1}
    star_px = MapSet.new(for {sx, sy} <- stars, dx <- -2..2, dy <- -2..2, do: {sx + dx, sy + dy})

    px =
      for y <- 0..(@h - 1), x <- 0..(@w - 1), into: <<>> do
        v = if MapSet.member?(star_px, {x, y}), do: 220, else: 40 + :rand.uniform(5) - 3

        v =
          case dust do
            {dx, dy, r} when (x - dx) * (x - dx) + (y - dy) * (y - dy) <= r * r -> round(v * 0.88)
            _ -> v
          end

        <<v>>
      end

    "P5\n#{@w} #{@h}\n255\n" <> px
  end

  defp map(dust) do
    imgs =
      for seed <- 1..10 do
        {:ok, img} = SensorMap.shrink(picture(seed, dust), 4)
        SensorMap.normalise(img)
      end

    # 2.42"/px in the 960 copy, 4x shrunk
    SensorMap.spots(imgs, 2.42 * 4)
  end

  test "a dark spot that stays put while the stars move is found, with its size and where it is" do
    m = map({300, 200, 30})
    assert [spot] = m.spots
    assert_in_delta spot.x, 300 / @w, 0.02
    assert_in_delta spot.y, 200 / @h, 0.02
    # 60 px across at 2.42"/px is 145"
    assert_in_delta spot.diameter_arcsec, 145, 30
    assert_in_delta spot.depth, 0.12, 0.05
    assert m.uptime < 1.0 and m.uptime > 0.98
    # steps that clear 145" and a quarter: 3 arcminutes and change, in half arcminutes
    assert m.dither_arcmin >= 3.0
  end

  test "a clean sensor has no spots, full uptime and needs no dither" do
    m = map(nil)
    assert m.spots == []
    assert m.uptime == 1.0
    assert m.dither_arcmin == nil
  end
end
