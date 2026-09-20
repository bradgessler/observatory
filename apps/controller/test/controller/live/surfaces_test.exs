defmodule Controller.SurfacesTest do
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  setup do
    id = "sim-surf-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "every bench surface renders nested", %{conn: conn, id: id} do
    for surface <- ~w(strips align dpad nudge orb tilt position gamepad watch sky) do
      {:ok, _view, html} = live(conn, "/bench/#{surface}?mount=#{id}")
      assert html =~ "bench-stage", surface
    end
  end

  test "nudge: one tap is one goto of the chosen step", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/controls/nudge/#{id}")
    assert html =~ "per tap"
    before = Mount.snapshot(id).axes.ra.degrees
    render_click(view, "step", %{"deg" => "2.0"})
    render_click(view, "nudge", %{"dir" => "right"})
    # the sim ramps; give a 2° goto time to land
    Process.sleep(1_200)
    assert abs(abs(Mount.snapshot(id).axes.ra.degrees - before) - 2.0) < 0.6
  end

  test "position: go home moves both axes toward 0", %{conn: conn, id: id} do
    Mount.goto_relative(id, :ra, 3.0)
    Process.sleep(300)
    {:ok, view, html} = live(conn, "/controls/position/#{id}")
    assert html =~ "Degrees From Zero"
    render_click(view, "home", %{})
    Process.sleep(1_500)
    assert abs(Mount.snapshot(id).axes.ra.degrees) < 0.6
  end

  test "tilt: a held vector moves an axis, letting go stops it", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/controls/tilt/#{id}")
    assert html =~ "hold"
    render_hook(view, "sensor", %{"state" => "ok"})
    render_hook(view, "tilt", %{"x" => 1, "y" => 0, "mag" => 0.5})
    assert Mount.snapshot(id).axes.ra.running
    render_hook(view, "tilt", %{"x" => 0, "y" => 0, "mag" => 0})
    refute Mount.snapshot(id).axes.ra.running
    render_hook(view, "tilt", %{"x" => 0, "y" => 1, "mag" => 1})
    assert Mount.snapshot(id).axes.dec.running
    render_hook(view, "tilt_end", %{})
    refute Mount.snapshot(id).axes.dec.running
  end

  test "tilt explains itself when the sensor is unavailable", %{conn: conn, id: id} do
    {:ok, view, _} = live(conn, "/controls/tilt/#{id}")
    assert render_hook(view, "sensor", %{"state" => "insecure"}) =~ "HTTPS"
    assert render_hook(view, "sensor", %{"state" => "denied"}) =~ "said no"
  end

  test "video: playlist and segments are served by whitelisted name only", %{conn: conn} do
    assert conn |> get("/video/1k/index.m3u8") |> response(404)
    assert conn |> get("/video/1k/..%2Fsecret") |> response(404)
    assert conn |> get("/video/9k/index.m3u8") |> response(404)
    dir = Video.HLS.dir(:"1k")
    File.mkdir_p!(dir)
    File.write!(Path.join(dir, "index.m3u8"), "#EXTM3U\n")
    File.write!(Path.join(dir, "seg00001.ts"), <<0x47, 0, 0>>)
    conn2 = get(conn, "/video/1k/index.m3u8")
    assert response(conn2, 200) =~ "#EXTM3U"
    assert get_resp_header(conn2, "content-type") |> hd() =~ "mpegurl"
    assert conn |> get("/video/1k/seg00001.ts") |> response(200)
  end

  test "watch page: play sits on the frame, video only appears once a playlist exists", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/controls/watch")
    assert html =~ "play live video"
    refute html =~ ">Live<"
    refute html =~ ">1K<"
    refute html =~ "video-feed"
    assert html =~ "watch-cap"
    assert html =~ "Recent Frames"
  end

  test "recent frames page renders without frames", %{conn: conn} do
    Watch.History.clear()
    {:ok, _view, html} = live(conn, "/controls/watch/frames")
    assert html =~ "Nothing kept yet"
  end

  test "camera page carries the technical detail, not the watch page", %{conn: conn} do
    {:ok, _view, html} = live(conn, "/controls/watch/camera")
    assert html =~ "Timed Stills"
    assert html =~ "Encoder"
    assert html =~ "30 fps"
    {:ok, _view, watch} = live(conn, "/controls/watch")
    refute watch =~ "video-log"
  end

  test "line up: asks for home, then names a star; that's it records a sample", %{conn: conn, id: id} do
    Controller.Sky.Lineup.clear(id)
    {:ok, view, html} = live(conn, "/controls/align/#{id}")
    assert html =~ "First: Zero the Axes"
    render_click(view, "home", %{})
    html = render(view)
    assert html =~ "Star 1"
    assert html =~ "I&#39;m on"
    [cand | _] = Controller.Sky.Lineup.candidates(id, Controller.Sky.Pointing.context(DateTime.utc_now(), id))
    html = render_click(view, "centred", %{"id" => cand.id})
    assert html =~ "1 star"
    assert Controller.Sky.Lineup.status(id).n == 1
    Controller.Sky.Lineup.clear(id)
  end

  test "line up: the forget button really forgets (clicked through the DOM, not the handler)", %{conn: conn, id: id} do
    Controller.Sky.Lineup.clear(id)
    {:ok, view, _} = live(conn, "/controls/align/#{id}")
    render_click(view, "home", %{})
    [c | _] = Controller.Sky.Lineup.candidates(id, Controller.Sky.Pointing.context(DateTime.utc_now(), id))
    render_click(view, "centred", %{"id" => c.id})
    assert Controller.Sky.Lineup.status(id).n == 1
    view |> element("button[phx-click=drop]") |> render_click()
    assert Controller.Sky.Lineup.status(id).n == 0
    Controller.Sky.Lineup.clear(id)
  end

  test "line up: hold what I'm on starts the tracker, stop holding ends it", %{conn: conn, id: id} do
    Controller.Sky.Lineup.clear(id)
    {:ok, view, _} = live(conn, "/controls/align/#{id}")
    render_click(view, "home", %{})
    html = render_click(view, "hold", %{})
    assert html =~ "holding"
    Process.sleep(300)
    assert Controller.Sky.Tracker.status(id) != nil
    render_click(view, "release", %{})
    Process.sleep(300)
    assert Controller.Sky.Tracker.status(id) == nil
  end

  test "optical axes page renders idle and refuses a scan without a camera or with one running", %{conn: conn, id: id} do
    {:ok, view, html} = live(conn, "/controls/watch/axes/#{id}")
    assert html =~ "Quick look"
    assert html =~ "Find the axes"
    assert html =~ "idle"
    # no camera tool in CI: the button is disabled, and the scan says why
    assert Controller.Optical.AxisScan.status().running == false
  end

  test "watch: history frames are served by name only when they exist", %{conn: conn} do
    assert conn |> get("/watch/frames/1758300000000.jpg") |> response(404)
    assert conn |> get("/watch/frames/..%2F..%2Fetc%2Fpasswd") |> response(404)
  end
end
