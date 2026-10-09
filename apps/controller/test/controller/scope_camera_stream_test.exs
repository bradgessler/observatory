defmodule Controller.ScopeCamera.StreamTest do
  @moduledoc """
  The camera kept open: frames as they come, a frame for a caller only when
  its light arrived after the call, the stream let go when nobody asks, and
  started again (within limits) when it dies. A shell script stands in for
  ffmpeg reading the camera.
  """
  use ExUnit.Case, async: false

  alias Controller.ScopeCamera.{Image, Stream}

  @fake Path.expand("../support/bin/fake-ffmpeg", __DIR__)

  setup do
    old = Application.get_env(:controller, :scope_camera, [])
    Application.put_env(:controller, :scope_camera, Keyword.put(old, :ffmpeg, @fake))
    Stream.stop()

    on_exit(fn ->
      Stream.stop()
      Application.put_env(:controller, :scope_camera, old)
      System.delete_env("FAKE_FFMPEG_FRAMES")
    end)
  end

  test "a frame whose light came after the ask, then the next one, from one camera opening" do
    {:ok, pgm, %{arrived: t1}} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    assert {:ok, %{w: 4, h: 2}} = Image.from_pgm(pgm)
    {:ok, _, %{arrived: t2}} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    assert t2 > t1
    s = Stream.status()
    assert s.running and s.restarts == 0
    # one stream served both: frames kept coming between the two asks
    assert s.frames >= 2
  end

  test "a stacked picture waits for every frame in its average to be newer than the ask" do
    asked = System.monotonic_time(:millisecond)
    {:ok, _, %{arrived: t}} = Stream.frame("/dev/fake", nil, exposure_ms: 50, stack: 4)
    assert t - asked >= 4 * 50
    # a different stack is a different average: the stream started again with it
    assert Stream.status().stack == 4
  end

  test "live view takes the next frame without waiting out an exposure; a picture waits" do
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    t0 = System.monotonic_time(:millisecond)
    {:ok, _, %{arrived: quick}} = Stream.frame("/dev/fake", nil, exposure_ms: 1_000, fresh: false)
    assert quick - t0 < 500
    t1 = System.monotonic_time(:millisecond)
    {:ok, _, %{arrived: strict}} = Stream.frame("/dev/fake", nil, exposure_ms: 300)
    assert strict - t1 >= 300
  end

  test "changing the stack starts a new reader only once the old one has let go" do
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50, stack: 4)
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50, stack: 2)
    assert Stream.status().restarts == 0 and Stream.status().stack == 2
  end

  test "letting it go: stop ends the stream, and the next ask opens it again" do
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    :ok = Stream.stop()
    refute Stream.status().running
    {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50)
    assert Stream.status().running
  end

  test "a stream that dies under a caller is started again for it" do
    # each run dies after half a second of frames, before any is new enough
    System.put_env("FAKE_FFMPEG_FRAMES", "10")
    # ask for a frame far enough ahead that the first stream dies first
    assert {:ok, _, _} = Stream.frame("/dev/fake", nil, exposure_ms: 50, skip: 3)
    assert Stream.status().restarts >= 1
  end

  test "a stream that keeps dying is given up on, and everyone waiting is told" do
    System.put_env("FAKE_FFMPEG_FRAMES", "1")
    assert {:error, :keeps_failing} = Stream.frame("/dev/fake", nil, exposure_ms: 50, skip: 20)
    assert Stream.status().error == :keeps_failing
  end
end
