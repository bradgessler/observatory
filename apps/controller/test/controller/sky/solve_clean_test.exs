defmodule Controller.Sky.SolveCleanTest do
  @moduledoc """
  The eyepiece cleaning in Elixir, for the Pi (no ImageMagick there): the
  disc found and kept, its rim and the frame around it gone, the moonlight
  taken off, the stars left. And a match below the horizon refused, whatever
  cleaned it.
  """
  use ExUnit.Case, async: true

  alias Controller.Sky.{Astro, Solve}
  alias Controller.Sky.Solve.Clean

  @w 800
  @h 600

  # a moonlit disc (with a gradient across it) and a hard rim, stars inside,
  # one bright star outside it
  defp photo(opts \\ []) do
    {cx, cy, r} = Keyword.get(opts, :disc, {430, 280, 220})
    stars = [{400, 250}, {500, 300}, {350, 350}, {460, 180}]
    outside = {60, 60}

    pixels =
      for y <- 0..(@h - 1), x <- 0..(@w - 1), into: <<>> do
        d = :math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy))
        glow = if r > 0 and d <= r, do: 60 + div(x - cx + r, 20), else: 2
        rim = if r > 0 and abs(d - r) < 3, do: 120, else: 0
        star = if Enum.any?(stars, fn {sx, sy} -> abs(x - sx) <= 1 and abs(y - sy) <= 1 end) and d < r, do: 120, else: 0
        out = if abs(x - elem(outside, 0)) <= 1 and abs(y - elem(outside, 1)) <= 1, do: 250, else: 0
        <<min(glow + rim + star + out, 255)>>
      end

    {pgm(@w, @h, pixels), small(pixels)}
  end

  defp pgm(w, h, pixels), do: "P5\n#{w} #{h}\n255\n" <> pixels

  # an eighth-size copy, as djpeg -scale 1/8 makes it (block averages)
  defp small(pixels) do
    {sw, sh} = {div(@w, 8), div(@h, 8)}

    body =
      for sy <- 0..(sh - 1), sx <- 0..(sw - 1), into: <<>> do
        sum = for y <- (sy * 8)..(sy * 8 + 7), x <- (sx * 8)..(sx * 8 + 7), reduce: 0, do: (s -> s + :binary.at(pixels, y * @w + x))
        <<div(sum, 64)>>
      end

    pgm(sw, sh, body)
  end

  defp at({w, _h, px}, x, y), do: :binary.at(px, y * w + x)

  test "the disc is kept and cropped to, the rim and the frame are gone, the stars stand out" do
    {full, small} = photo()
    assert {:ok, out, %{box: {bx, by, bw, bh}, disc_share: share}} = Clean.eyepiece(small, full, 8)
    {:ok, img} = Clean.pgm(out)
    {w, h, _} = img
    assert {w, h} == {bw, bh}

    # the crop sits on the disc (220 px radius, less the 50 px erosion)
    assert_in_delta bx + bw / 2, 430, 16
    assert_in_delta by + bh / 2, 280, 16
    assert bw < 2 * 220 and bw > 2 * 150
    assert share > 0.05

    # a star inside is bright, the moonlit background around it is near black
    assert at(img, 400 - bx, 250 - by) > 80
    assert at(img, 420 - bx, 270 - by) < 30
    # the star outside the eyepiece is not in the picture at all
    refute 60 - bx in 0..(w - 1) and 60 - by in 0..(h - 1) and at(img, 60 - bx, 60 - by) > 30
  end

  test "a frame with no eyepiece in it goes the plain way" do
    {full, small} = photo(disc: {430, 280, 0})
    assert Clean.eyepiece(small, full, 8) == :no_eyepiece
  end

  test "a PGM header with a comment reads" do
    assert {:ok, {2, 1, <<1, 2>>}} = Clean.pgm("P5\n# from djpeg\n2 1\n255\n" <> <<1, 2>>)
    assert {:error, :unsupported_image} = Clean.pgm("P6\n2 1\n255\n")
  end

  describe "a match below the horizon" do
    defmodule Stub do
      def solve("at " <> radec, _opts) do
        [ra, dec] = radec |> String.split() |> Enum.map(&String.to_float/1)
        {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 1.0, height_deg: 1.0}}
      end
    end

    @site %{lat: 38.0, lon: -122.0}

    test "is refused when the photo's time and place say it can't be" do
      at = ~U[2026-09-26 06:30:00Z]
      sky = %{at: at, site: @site}
      assert {:error, :below_horizon} = Solve.run("at 299.87 -69.16", backend: Stub, sky: sky)

      # straight overhead at that moment
      lst = Astro.lst_deg(at, @site.lon)
      assert {:ok, _} = Solve.run("at #{Float.round(lst * 1.0, 3)} 38.0", backend: Stub, sky: sky)
    end

    test "without a time and place it can't be judged, and passes" do
      assert {:ok, _} = Solve.run("at 299.87 -69.16", backend: Stub)
    end
  end
end
