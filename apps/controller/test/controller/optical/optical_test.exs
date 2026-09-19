defmodule Controller.OpticalTest do
  @moduledoc "The axis finder against synthetic scenes where the truth is known: a textured plate turned about a chosen point, or slid."
  use ExUnit.Case, async: true

  alias Controller.Optical.{Flow, Frame, Pivot}

  @w 160
  @h 120

  # a textured scene: smooth blobs plus noise, deterministic
  defp scene do
    :rand.seed(:exsss, {1, 2, 3})
    noise = for _ <- 1..(@w * @h), do: :rand.uniform(60)

    px =
      for {n, i} <- Enum.with_index(noise), into: <<>> do
        x = rem(i, @w)
        y = div(i, @w)
        v = 100 + 60 * :math.sin(x / 7) * :math.cos(y / 5) + n
        <<round(min(max(v, 0), 255))>>
      end

    Frame.from_grey(@w, @h, px)
  end

  # sample the scene under an inverse transform: rotation about (cx, cy) by theta, plus a shift
  defp warp(frame, cx, cy, theta, sx, sy) do
    c = :math.cos(theta)
    s = :math.sin(theta)

    px =
      for y <- 0..(@h - 1), x <- 0..(@w - 1), into: <<>> do
        # where did this output pixel come from?
        ux = x - sx - cx
        uy = y - sy - cy
        srcx = round(c * ux + s * uy + cx)
        srcy = round(-s * ux + c * uy + cy)
        <<Frame.at(frame, srcx, srcy)>>
      end

    Frame.from_grey(@w, @h, px)
  end

  test "a small rotation about a point is found within a couple of pixels" do
    a = scene()
    {cx, cy} = {70.0, 55.0}
    b = warp(a, cx, cy, 0.05, 0, 0)
    vectors = Flow.between(a, b)
    assert length(vectors) > 20
    fit = Pivot.fit(vectors)
    assert fit != nil
    assert_in_delta fit.cx, cx, 4.0
    assert_in_delta fit.cy, cy, 4.0
    assert fit.quality > 0.85
    assert fit.coherence < 0.7
  end

  test "a slide is recognised as a slide, not a spin" do
    a = scene()
    b = warp(a, 0.0, 0.0, 0.0, 3, 1)
    vectors = Flow.between(a, b)
    assert length(vectors) > 20
    fit = Pivot.fit(vectors)
    assert fit.cx == nil or fit.coherence > 0.9
    assert fit.coherence > 0.9
    assert_in_delta fit.mean_dx, 3.0, 0.6
    assert_in_delta fit.mean_dy, 1.0, 0.6
    assert Pivot.words(fit) =~ "slides"
  end

  test "nothing moved, nothing found" do
    a = scene()
    assert Flow.between(a, a) == []
    assert Pivot.fit([]) == nil
  end

  test "frames decode and downsample" do
    # a 32×16 RGB gradient through the real decoder path
    data = for y <- 0..15, x <- 0..31, into: <<>>, do: <<x * 8, y * 16, 128>>
    img = StbImage.new(data, {16, 32, 3})
    frame = Frame.from_image(img, 4)
    assert {frame.w, frame.h, frame.scale} == {8, 4, 4}
    assert byte_size(frame.pixels) == 32
    # left is darker than right
    assert Frame.at(frame, 0, 0) < Frame.at(frame, 7, 0)
  end
end
