defmodule Controller.FramesTest do
  @moduledoc """
  Frames the camera keeps go to the card, then to the Mac, then get their
  stars measured, each step a queue with its own numbers; the box serves a
  waiting frame over HTTP; and the Queues page names the steps and the
  slow one. Here the "box" and the "Mac" are the same machine, which is
  also how a Mac with the simulated camera runs.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{Frames, ScopeCamera}

  setup do
    id = "sim-frames-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    ScopeCamera.simulate(true)

    on_exit(fn ->
      ScopeCamera.keep(false)
      ScopeCamera.live(false)
      ScopeCamera.simulate(false)
    end)

    %{id: id}
  end

  defp eventually(fun, tries \\ 300) do
    cond do
      fun.() -> true
      tries == 0 -> flunk("never happened")
      true -> Process.sleep(50) && eventually(fun, tries - 1)
    end
  end

  defp done(name), do: Queues.stats(name).counts.done

  @tag timeout: 60_000
  test "kept frames go to the card, to this Mac, and get measured", %{id: id} do
    before = done("frames.measure")
    :ok = ScopeCamera.keep(true)
    {:ok, _} = ScopeCamera.grab(mount: id)
    {:ok, _} = ScopeCamera.grab(mount: id)

    eventually(fn -> done("frames.measure") >= before + 2 end)

    # FITS files, everything about each frame in its own header, nothing beside them
    files = Path.wildcard(Path.join([Frames.dir(), "*", "*.fits"]))
    assert Path.wildcard(Path.join([Frames.dir(), "*", "*.json"])) == []

    headers =
      for f <- files, {:ok, fits} = Controller.Fits.read(File.read!(f)), h = Map.new(fits.header), h["INSTRUME"] == "Simulated camera", do: {fits, h}

    assert length(headers) >= 2
    {fits, h} = hd(headers)
    assert {fits.w, fits.h} == {960, 540}
    # the standard keywords
    assert h["ROWORDER"] == "TOP-DOWN" and h["IMAGETYP"] == "LIGHT"
    settings = ScopeCamera.status().settings
    assert h["EXPTIME"] == settings["exposure_ms"] / 1000 and h["NCOMBINE"] == 1 and h["GAIN"] == settings["gain"]
    assert {:ok, _} = NaiveDateTime.from_iso8601(h["DATE-OBS"])
    assert is_float(h["SITELAT"]) and h["TELESCOP"] =~ "EQ6-R"
    # ours: the frame, the mount at the start and end, the copy, the second measurement
    assert is_integer(h["OBS FRAME SEQ"]) and h["OBS FRAME VERDICT"] == "stars" and h["OBS FRAME STARS"] > 0
    assert h["OBS MOUNT ID"] == id
    assert is_number(h["OBS MOUNT START RA DEG"]) and is_number(h["OBS MOUNT END DEC STEPS"])
    assert h["OBS COPY TO"] == to_string(node()) and String.length(h["OBS COPY SHA256 A"] <> h["OBS COPY SHA256 B"]) == 64
    assert h["OBS MEASURED STARS"] > 0

    # and each is a row in this machine's database, its header with it
    rows = Controller.Frames.copied(limit: 100) |> Enum.filter(&(&1.header["INSTRUME"] == "Simulated camera"))
    assert length(rows) >= 2
    r = hd(rows)
    assert r.place == "copied" and r.seq > 0 and r.stars > 0 and r.verdict == "stars" and r.gain == ScopeCamera.status().settings["gain"]
    assert r.state in ["copied", "measured"] and File.exists?(r.path)
    assert Enum.any?(rows, &(&1.state == "measured" and &1.measured_stars > 0))
    assert Controller.Frames.copied(with_stars: true, limit: 100) != []

    # each step timed it
    for name <- ~w(frames.write frames.fetch frames.measure), do: assert(Queues.stats(name).work_ms.p50 != nil)
    assert Queues.stats("frames").counts.taken >= 2
  end

  test "a frame not kept costs nothing; turning keep off stops it", %{id: id} do
    :ok = ScopeCamera.keep(false)
    before = Queues.stats("frames.write").counts.pushed
    {:ok, _} = ScopeCamera.grab(mount: id)
    assert Queues.stats("frames.write").counts.pushed == before
  end

  test "the box serves a waiting frame from disk, and nothing outside the spool", %{conn: conn} do
    {:ok, e} = Queues.Spool.put("frames", "123-1.pgm", "P5\n1 1\n255\n" <> <<7>>, %{})
    body = conn |> get("/spool/frames/#{e.id}") |> response(200)
    assert body == "P5\n1 1\n255\n" <> <<7>>
    assert conn |> get("/spool/frames/nope.pgm") |> response(404)
    assert build_conn() |> get("/spool/frames/..%2F..%2Fetc%2Fpasswd") |> response(404)
  end

  test "frames have pages of their own: a list, and each frame's picture and record", %{conn: conn, id: id} do
    {:ok, a} = ScopeCamera.grab(mount: id)
    {:ok, b} = ScopeCamera.grab(mount: id)
    {n, m} = {a.record.seq, b.record.seq}

    {:ok, _view, html} = live(conn, ~p"/cameras/telescope/frames")
    assert html =~ "Frame #{n}" and html =~ "Frame #{m}"
    # newest first
    assert :binary.match(html, "Frame #{m} ") < :binary.match(html, "Frame #{n} ")

    {:ok, _view, html} = live(conn, ~p"/cameras/telescope/frames/#{m}")
    assert html =~ "Frame #{m}"
    assert html =~ "/cameras/telescope/frames/#{m}/frame.png"
    assert html =~ "Background" and html =~ "Exposure"
    assert conn |> get("/cameras/telescope/frames/#{m}/frame.png") |> response(200) =~ <<137, 80, 78, 71>>
    assert build_conn() |> get("/cameras/telescope/frames/999999/frame.png") |> response(404)

    # the camera page links to them rather than listing them
    {:ok, _view, html} = live(conn, ~p"/cameras/telescope")
    assert html =~ ~s(href="/cameras/telescope/frames")
  end

  test "the Queues page shows every step, in words and a bar", %{conn: conn} do
    Process.sleep(1_200)
    {:ok, view, html} = live(conn, ~p"/queues")
    assert html =~ "Write to the SD card"
    assert html =~ "Waiting on the SD card for the Mac"
    assert html =~ "Copy to this Mac"
    assert html =~ "Find the stars"
    assert render(view) =~ ~r/Keeping up|Bottleneck/
  end
end
