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

  # asks until `fun` answers (anything but nil or false), and gives the answer back; `tries` × 50 ms at most
  defp eventually(fun, tries \\ 300) do
    cond do
      answer = fun.() -> answer
      tries == 0 -> flunk("never happened")
      true -> Process.sleep(50) && eventually(fun, tries - 1)
    end
  end

  # the kept frames that are on this machine and through every step, as `{fits, header}`, of those numbered `seqs`
  defp through(seqs) do
    for file <- Path.wildcard(Path.join([Frames.dir(), "*", "*.fits"])),
        {:ok, bin} <- [File.read(file)],
        {:ok, fits} <- [Controller.Fits.read(bin)],
        h = Map.new(fits.header),
        h["OBS FRAME SEQ"] in seqs,
        # the last thing the last step does is write what it measured into the frame's own header
        h["OBS MEASURED ON"] != nil,
        do: {fits, h}
  end

  @tag timeout: 60_000
  test "kept frames go to the card, to this Mac, and get measured", %{id: id} do
    :ok = ScopeCamera.keep(true)
    {:ok, first} = ScopeCamera.grab(mount: id)
    {:ok, second} = ScopeCamera.grab(mount: id)
    asked = first.record
    seqs = [first.record.seq, second.record.seq]

    # These two frames, by their numbers, and no others. Another can be kept beside them: any
    # frame that arrives while keep is on is kept, and the camera may still be taking one for
    # the test before this one (the focus page's live view; the last picture of a Find Where
    # It's Pointing that was stopped, taken a second later at its own gain). It carries that
    # test's mount in its header. This used to wait until two more frames had been measured,
    # then read the first file and the newest row. Now and then those were not this test's
    # frames, and now and then this test's second frame was not through yet.
    frames = eventually(fn -> both = through(seqs); length(both) == 2 and both end, 600)

    # FITS files, everything about each frame in its own header, nothing beside them
    assert Path.wildcard(Path.join([Frames.dir(), "*", "*.json"])) == []

    for {fits, h} <- frames do
      assert {fits.w, fits.h} == {960, 540}
      # the standard keywords, saying what the camera was asked for
      assert h["ROWORDER"] == "TOP-DOWN" and h["IMAGETYP"] == "LIGHT" and h["INSTRUME"] == "Simulated camera"
      assert h["EXPTIME"] == asked.exposure_ms / 1000 and h["NCOMBINE"] == asked.stack and h["GAIN"] == asked.gain
      assert {:ok, _} = NaiveDateTime.from_iso8601(h["DATE-OBS"])
      assert is_float(h["SITELAT"]) and h["TELESCOP"] =~ "EQ6-R"
      # ours: the frame, the mount at the start and end, the copy, the second measurement
      assert h["OBS FRAME VERDICT"] == "stars" and h["OBS FRAME STARS"] > 0
      assert h["OBS MOUNT ID"] == id
      assert is_number(h["OBS MOUNT START RA DEG"]) and is_number(h["OBS MOUNT END DEC STEPS"])
      assert h["OBS COPY TO"] == to_string(node()) and String.length(h["OBS COPY SHA256 A"] <> h["OBS COPY SHA256 B"]) == 64
      assert h["OBS MEASURED STARS"] > 0
    end

    # and each is a row in this machine's database, its header with it, measured
    rows = Controller.Frames.copied(limit: 100) |> Enum.filter(&(&1.seq in seqs))
    assert length(rows) == 2

    for r <- rows do
      assert r.place == "copied" and r.header["INSTRUME"] == "Simulated camera"
      assert r.stars > 0 and r.verdict == "stars" and r.gain == asked.gain
      assert r.state == "measured" and r.measured_stars > 0 and File.exists?(r.path)
    end

    assert Enum.any?(Controller.Frames.copied(with_stars: true, limit: 100), &(&1.seq in seqs))

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
    # the page lists the steps it has heard from, and each says its numbers once a second
    steps = ~w(frames.write frames frames.fetch frames.measure)
    eventually(fn -> Enum.all?(steps, &(&1 in Enum.map(Queues.board(), fn step -> step.name end))) end)
    {:ok, view, html} = live(conn, ~p"/queues")
    assert html =~ "Write to the SD card"
    assert html =~ "Waiting on the SD card for the Mac"
    assert html =~ "Copy to this Mac"
    assert html =~ "Find the stars"
    assert render(view) =~ ~r/Keeping up|Bottleneck/
  end
end
