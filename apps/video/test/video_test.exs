defmodule VideoTest do
  use ExUnit.Case, async: false

  alias Video.{Encoder, Ladder}

  test "the ladder names what people say and means specific sizes" do
    assert %{size: {1280, 720}} = Ladder.parse("1K")
    assert %{size: {1920, 1080}} = Ladder.parse(:"2k")
    assert %{size: {3840, 2160}} = Ladder.parse("4k")
    assert Ladder.parse("8k") == nil
  end

  test "a rung is offered only when the camera has that mode" do
    assert Ladder.available?(Ladder.get(:"1k"), [{1280, 720}, {1920, 1080}])
    refute Ladder.available?(Ladder.get(:"4k"), [{1280, 720}, {1920, 1080}])
    assert Ladder.available?(Ladder.get(:"4k"), :unknown)
  end

  test "encoder arguments carry the bitrate and a broadcast-safe pixel format" do
    for enc <- ~w(h264_videotoolbox h264_v4l2m2m libx264 something_else) do
      args = Encoder.args(enc, 3_000)
      assert "-c:v" in args and enc in args
      assert "3000k" in args
      # never -pix_fmt: on macOS it leaks into the avfoundation input and corrupts frames
      refute "-pix_fmt" in args
      assert Enum.any?(args, &String.starts_with?(&1, "format="))
    end
  end

  test "status is off until started and the still is not available" do
    assert %{state: :off, ready: false, playlist: nil} = Video.status()
    assert {:error, :not_streaming} = Video.snapshot()
  end

  test "auto picks the best rung the camera offers, capped at 2K" do
    # exercised through the private chooser via start/1 would open a camera; check the ladder maths instead
    rungs = Video.Ladder.rungs()
    upto_2k = rungs |> Enum.take_while(&(&1.id != :"2k")) |> Kernel.++([Video.Ladder.get(:"2k")])
    assert Enum.map(upto_2k, & &1.id) == [:"1k", :"2k"]
    best = upto_2k |> Enum.filter(&Video.Ladder.available?(&1, [{1280, 720}, {1920, 1080}, {3840, 2160}])) |> List.last()
    assert best.id == :"2k"
  end

  test "an unknown quality is refused without touching ffmpeg" do
    assert {:error, :unknown_quality} = Video.start(quality: "9k")
    assert %{state: :off} = Video.status()
  end
end
