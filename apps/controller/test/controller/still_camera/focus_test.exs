defmodule Controller.StillCamera.FocusTest do
  @moduledoc """
  Star size, on pictures made here: a Gaussian star's half-flux diameter is
  known exactly (2.3548 sigma), so the measure can be checked against it; a
  ring with the same peak must read far wider; and what is not a star to
  focus by (a hot pixel, a saturated star, one at the edge, one in glare, a
  bright target's face) must be left out.
  """
  use ExUnit.Case, async: true

  alias Controller.ScopeCamera.Image
  alias Controller.StillCamera.Focus

  # a Gaussian's half-flux diameter, in sigmas (it is also its width at half its peak)
  @hfd 2.3548

  # A grey picture: the sky (`sky:` a level, or a function of x and y), each shape's light added on
  # top, noise if asked for (`noise:` its standard deviation, the same every run), cut off at 255.
  defp picture(w, h, shapes, opts \\ []) do
    sky = Keyword.get(opts, :sky, 10)
    noise = Keyword.get(opts, :noise, 0.0)
    :rand.seed(:exsss, {11, 22, 33})

    light =
      for shape <- shapes, {at, v} <- stamp(shape), reduce: %{} do
        acc -> Map.update(acc, at, v, &(&1 + v))
      end

    px =
      for y <- 0..(h - 1), x <- 0..(w - 1), into: <<>> do
        level = if is_function(sky), do: sky.(x, y), else: sky

        <<(level + Map.get(light, {x, y}, 0) + noise * :rand.normal())
          |> round()
          |> max(0)
          |> min(255)>>
      end

    %{w: w, h: h, px: px}
  end

  defp stamp({:star, cx, cy, sigma, peak}) do
    r = ceil(5 * sigma)

    for y <- (round(cy) - r)..(round(cy) + r),
        x <- (round(cx) - r)..(round(cx) + r),
        do: {{x, y}, peak * :math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma * sigma))}
  end

  # out of focus in a Schmidt-Cassegrain: a ring of light `radius` out, as thick as a sharp star
  defp stamp({:ring, cx, cy, radius, sigma, peak}) do
    r = ceil(radius + 5 * sigma)

    for y <- (round(cy) - r)..(round(cy) + r), x <- (round(cx) - r)..(round(cx) + r) do
      d = :math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
      {{x, y}, peak * :math.exp(-((d - radius) ** 2) / (2 * sigma * sigma))}
    end
  end

  defp stamp({:pixel, x, y, v}), do: [{{x, y}, v}]

  describe "a star's half-flux diameter" do
    test "a Gaussian star of a known width reads 2.355 sigma, within a tenth, whatever its width" do
      for sigma <- [1.5, 2.0, 3.0, 4.0, 5.0] do
        img = picture(160, 160, [{:star, 80.3, 79.6, sigma, 200}])
        assert %{hfd_px: hfd, x: x, y: y, peak: peak} = Focus.star(img, 80, 80)
        assert_in_delta hfd, @hfd * sigma, 0.1 * @hfd * sigma, "sigma #{sigma}: #{hfd} px"
        # and it says where the star's middle really is, and how bright
        assert_in_delta x, 80.3, 0.2
        assert_in_delta y, 79.6, 0.2
        assert peak in 195..210
      end
    end

    test "and still does on a noisy sky" do
      for sigma <- [2.0, 4.0] do
        img = picture(160, 160, [{:star, 80.3, 79.6, sigma, 180}], sky: 20, noise: 2.0)
        assert %{hfd_px: hfd} = Focus.star(img, 80, 80)
        assert_in_delta hfd, @hfd * sigma, 0.1 * @hfd * sigma, "sigma #{sigma}: #{hfd} px"
      end
    end

    test "a ring with a small bright core reads far wider than a sharp star with the same peak" do
      sharp = picture(160, 160, [{:star, 80, 80, 1.5, 180}])
      ring = picture(160, 160, [{:ring, 80, 80, 9, 1.5, 60}, {:star, 80, 80, 1.5, 180}])
      assert %{hfd_px: tight, peak: peak} = Focus.star(sharp, 80, 80)
      assert %{hfd_px: wide, peak: ^peak} = Focus.star(ring, 80, 80)

      # the core alone is as narrow as ever: most of the light is out in the ring, and the number says so
      assert_in_delta tight, @hfd * 1.5, 0.4
      assert wide > 15 and wide > 4 * tight
    end

    test "a position found on a smaller copy is scaled up, and the window is cut again round where the star is" do
      img = picture(400, 300, [{:star, 250, 150, 2.0, 200}, {:star, 100, 60, 2.0, 150}])
      # the copy is 3.125 times smaller, its marks rounded to a pixel
      marks = [%{x: 80, y: 48}, %{x: 32, y: 19}]
      assert %{hfd_px: hfd, n: 2} = Focus.measure(img, marks, scale: 3.125)
      assert_in_delta hfd, @hfd * 2.0, 0.4
      # a position well off the star still finds it
      assert %{x: x, y: y} = Focus.star(img, 238, 160)
      assert_in_delta x, 250, 0.5
      assert_in_delta y, 150, 0.5
    end
  end

  describe "a picture's star size" do
    test "is the median over its stars, and says how many" do
      stars = [{60, 60, 2.0}, {180, 60, 2.0}, {300, 60, 2.0}, {60, 180, 3.0}, {180, 180, 4.0}]
      img = picture(360, 240, for({x, y, s} <- stars, do: {:star, x, y, s, 190}))
      assert %{hfd_px: hfd, n: 5} = Focus.measure(img, for({x, y, _} <- stars, do: %{x: x, y: y}))
      assert_in_delta hfd, @hfd * 2.0, 0.4
      # the PGM itself does as well as the image
      assert Focus.measure(Image.pgm(img), for({x, y, _} <- stars, do: %{x: x, y: y})) == %{
               hfd_px: hfd,
               n: 5
             }
    end

    test "at most max_stars, the brightest first" do
      at = for i <- 0..5, do: {60 + i * 100, 60}
      # the first three are sharp, the rest wide: only the first three are asked for
      img =
        picture(
          640,
          120,
          for(
            {{x, y}, i} <- Enum.with_index(at),
            do: {:star, x, y, if(i < 3, do: 2.0, else: 5.0), 190}
          )
        )

      marks = for {x, y} <- at, do: %{x: x, y: y}
      assert %{hfd_px: sharp, n: 3} = Focus.measure(img, marks, max_stars: 3)
      assert %{hfd_px: all, n: 6} = Focus.measure(img, marks)
      assert_in_delta sharp, @hfd * 2.0, 0.4
      assert all > sharp + 2
    end

    test "a hot pixel is not a star: one or two pixels wide is left out" do
      img =
        picture(360, 120, [
          {:star, 60, 60, 2.0, 190},
          {:pixel, 180, 60, 220},
          {:pixel, 300, 60, 200},
          {:pixel, 301, 60, 200}
        ])

      assert Focus.star(img, 180, 60) == nil
      assert Focus.star(img, 300, 60) == nil

      assert %{n: 1, hfd_px: hfd} =
               Focus.measure(img, [%{x: 180, y: 60}, %{x: 300, y: 60}, %{x: 60, y: 60}])

      assert_in_delta hfd, @hfd * 2.0, 0.4
      assert Focus.measure(img, [%{x: 180, y: 60}, %{x: 300, y: 60}]) == nil
    end

    test "a saturated star is left out: its top is cut off, so it would read wide" do
      img = picture(240, 120, [{:star, 60, 60, 3.0, 600}, {:star, 180, 60, 3.0, 150}])
      assert Focus.star(img, 60, 60) == nil
      assert %{n: 1, hfd_px: hfd} = Focus.measure(img, [%{x: 60, y: 60}, %{x: 180, y: 60}])
      assert_in_delta hfd, @hfd * 3.0, 0.7

      # where saturation starts is a knob: told that nothing is saturated, it measures the clipped star, wide
      assert %{hfd_px: clipped} = Focus.star(img, 60, 60, saturation: 256)
      assert clipped > hfd + 1
    end

    test "a star too close to the edge is left out" do
      img =
        picture(240, 120, [
          {:star, 20, 60, 2.0, 190},
          {:star, 120, 60, 2.0, 190},
          {:star, 225, 100, 2.0, 190}
        ])

      assert Focus.star(img, 20, 60) == nil
      assert Focus.star(img, 225, 100) == nil
      assert %{n: 1} = Focus.measure(img, [%{x: 20, y: 60}, %{x: 225, y: 100}, %{x: 120, y: 60}])
      # the window's size is a knob: a smaller one fits
      assert %{hfd_px: _} = Focus.star(img, 20, 60, window: 32)
    end

    test "what was set aside as a bright target is left out" do
      img = picture(240, 120, [{:star, 60, 60, 2.0, 190}, {:star, 180, 60, 4.0, 190}])
      marks = [%{x: 60, y: 60, why: :bright_target}, %{x: 180, y: 60}]
      assert %{n: 1, hfd_px: hfd} = Focus.measure(img, marks)
      assert_in_delta hfd, @hfd * 4.0, 0.9
      assert Focus.measure(img, [%{x: 60, y: 60, why: :bright_target}]) == nil
    end

    test "two stars in one window are left out: they would be measured as one wide star" do
      img =
        picture(360, 120, [
          {:star, 60, 60, 2.0, 190},
          {:star, 78, 66, 2.0, 150},
          {:star, 250, 60, 2.0, 190}
        ])

      assert %{n: 1, hfd_px: hfd} =
               Focus.measure(img, [%{x: 60, y: 60}, %{x: 78, y: 66}, %{x: 250, y: 60}])

      assert_in_delta hfd, @hfd * 2.0, 0.4
    end

    test "a star in something's glare is left out: the sky on the sides of its window doesn't agree" do
      glare = fn x, _y -> 10 + x / 4 end
      img = picture(240, 120, [{:star, 120, 60, 2.0, 150}], sky: glare)
      assert Focus.star(img, 120, 60) == nil
      assert %{hfd_px: _} = Focus.star(picture(240, 120, [{:star, 120, 60, 2.0, 150}]), 120, 60)
    end

    test "an empty picture is nil, with or without noise, and so is a picture with nowhere to look" do
      empty = picture(240, 160, [])
      noisy = picture(240, 160, [], sky: 20, noise: 3.0)
      marks = [%{x: 60, y: 60}, %{x: 120, y: 80}, %{x: 180, y: 100}]
      assert Focus.measure(empty, marks) == nil
      assert Focus.measure(noisy, marks) == nil
      assert Focus.measure(empty, []) == nil
      assert Focus.measure(picture(240, 160, [{:star, 120, 80, 2.0, 190}]), []) == nil
    end

    test "odd input is nil, never a crash" do
      img = picture(120, 120, [{:star, 60, 60, 2.0, 190}])
      marks = [%{x: 60, y: 60}]
      assert %{n: 1} = Focus.measure(img, marks)

      assert Focus.measure(nil, marks) == nil
      assert Focus.measure("not a picture", marks) == nil
      assert Focus.measure(<<"P5\n10 10\n255\n", 0, 0, 0>>, marks) == nil
      assert Focus.measure(%{w: 120, h: 120, px: <<1, 2, 3>>}, marks) == nil
      assert Focus.measure(%{w: 0, h: 0, px: <<>>}, marks) == nil
      assert Focus.measure(img, :stars) == nil

      assert Focus.measure(img, [nil, %{}, %{x: "a", y: 2}, {60, 60}, %{x: -500, y: 9.0e9}]) ==
               nil

      assert Focus.measure(img, marks, window: "wide") == nil
      assert Focus.measure(img, marks, window: 0) == nil
      assert Focus.measure(img, marks, window: 4096) == nil
      assert Focus.measure(img, marks, max_stars: :all) == nil
      assert Focus.measure(img, marks, scale: nil) == nil
      assert Focus.measure(img, marks, :opts) == nil
      assert Focus.star(img, nil, 60) == nil
      assert Focus.star(:img, 60, 60) == nil
      assert Focus.star(img, 60, 60, border: 40) == nil
    end
  end

  test "arcseconds a pixel, from the focal length, the sensor's width and the picture's: 0.8 for the a6000 at half size on 2032 mm" do
    assert_in_delta Focus.arcsec_per_px(2032, 23.5, 3000), 0.795, 0.001
    assert_in_delta Focus.arcsec_per_px(2032, 23.5, 6000), 0.3976, 0.001
    assert Focus.arcsec_per_px(nil, 23.5, 3000) == nil
    assert Focus.arcsec_per_px(0, 23.5, 3000) == nil
    assert Focus.arcsec_per_px("2032", 23.5, 3000) == nil
  end
end
