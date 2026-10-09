defmodule Controller.StillCameraTest do
  @moduledoc """
  The stills camera with a simulated a6000 (the real camera's bytes): a
  picture is kept whole, RAW and JPEG, measured like the telescope camera's
  frames, shown on its page, and fed to Lock On.
  """
  use Controller.ConnCase, async: false
  import Phoenix.LiveViewTest

  alias Controller.{LockOn, StillCamera}

  setup do
    cam = "sim-still-#{System.unique_integer([:positive])}"
    StillCamera.subscribe()
    start_supervised!({Camera.Server, id: cam, transport: {Camera.Transport.Sim, []}})
    assert_receive {:still_camera, %{camera: %{id: ^cam, state: :ready}}}, 5_000
    LockOn.release()

    on_exit(fn ->
      StillCamera.continuous(false)
      LockOn.release()
    end)
    # a picture from the test before may still be coming down
    Enum.find(1..300, fn _ -> not StillCamera.status().busy or (Process.sleep(50) && false) end)
    %{cam: cam}
  end

  # this test's picture, not one still coming down from the test before
  defp picture do
    before = (StillCamera.status().last || %{})[:seq] || 0
    StillCamera.shoot()
    assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000
    last
  end

  @tag timeout: 60_000
  test "a picture is kept whole, RAW and JPEG, and measured: the Moon in it is found" do
    last = picture()
    assert Enum.all?(last.files, &File.exists?/1)

    assert Enum.any?(last.names, &String.ends_with?(&1, ".JPG")) and
             Enum.any?(last.names, &String.ends_with?(&1, ".ARW"))

    assert String.starts_with?(hd(last.files), StillCamera.dir())
    # the grey copy, measured: the simulated camera's picture is the Moon
    assert last.w == 960
    assert %{fraction: f} = last.bright
    assert f > 0.05
    assert <<137, "PNG", _::binary>> = StillCamera.png()
  end

  @tag timeout: 60_000
  test "the page shows the camera, takes a picture, and serves it", %{conn: conn} do
    {:ok, view, html} = live(conn, ~p"/cameras/stills")
    assert html =~ "Stills Camera" and html =~ "Take Picture" and html =~ "Lock On"
    assert html =~ ~s(aria-label="ISO")

    view |> element("button", "Take Picture") |> render_click()
    assert_receive {:still_camera, %{busy: false, last: %{w: 960}}}, 15_000
    assert render(view) =~ "bright target"
    assert conn |> get(~p"/cameras/stills/latest.png") |> response(200) =~ <<137, "PNG">>
  end

  @tag timeout: 60_000
  test "Lock On from the page steers by this camera's pictures", %{conn: conn} do
    id = "sim-still-mount-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000

    {:ok, view, _} = live(conn, ~p"/cameras/stills?#{[id: id]}")
    view |> element("button", "Lock On the Bright Target") |> render_click()
    assert %{state: :calibrating, mount: ^id} = LockOn.status()
    assert StillCamera.status().shooting
    view |> element("button", "Release") |> render_click()
    assert LockOn.status().state == :off
  end

  @tag timeout: 60_000
  test "what was known when it was taken is written beside the picture: time, camera, the mount through the exposure, each file's hash" do
    mount = "sim-still-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(mount)
    assert_receive {:mount, %{connected: true}}, 2_000

    last = picture()
    assert String.ends_with?(last.sidecar, ".json") and Path.dirname(last.sidecar) == Path.dirname(hd(last.files))
    side = last.sidecar |> File.read!() |> Jason.decode!()
    assert side["schema"] == "observatory.still/1"

    # the camera's files, untouched: what's on the card hashes to what the sidecar says
    assert length(side["files"]) == 2

    for f <- side["files"] do
      bytes = File.read!(Path.join(Path.dirname(last.sidecar), f["name"]))
      assert byte_size(bytes) == f["bytes"]
      assert Base.encode16(:crypto.hash(:sha256, bytes), case: :lower) == f["sha256"]
    end

    assert %{"shutter_pressed" => pressed, "exposure_end" => ended, "picture_ready" => _, "exposure_s" => exp} = side["time"]
    {:ok, t0, 0} = DateTime.from_iso8601(pressed)
    {:ok, t1, 0} = DateTime.from_iso8601(ended)
    assert_in_delta DateTime.diff(t1, t0, :millisecond) / 1000, exp, 0.01
    assert %{"model" => "ILCE-6000", "iso" => iso, "shutter" => _, "quality" => "RAW+JPEG"} = side["camera"]
    assert is_integer(iso)

    # the mount at both ends of the exposure: degrees and encoder steps on both axes
    assert %{"id" => id, "start" => start, "end" => finish, "track" => track} = side["mount"]
    assert is_binary(id) and is_list(track)

    for snap <- [start, finish], axis <- ["ra", "dec"] do
      assert %{"deg" => deg, "steps" => steps} = snap[axis]
      assert is_number(deg) and is_integer(steps)
    end

    assert %{"w" => 960, "bright" => %{"fraction" => _}} = side["measured"]
    assert %{"state" => "off", "holding" => false} = side["lock_on"]
    assert Map.has_key?(side, "pointing") and is_binary(side["box"]["node"])

    # and the night's index has the same record on one line
    index = Path.join(Path.dirname(last.sidecar), "index.jsonl") |> File.read!() |> String.split("\n", trim: true)
    assert Enum.any?(index, &(Jason.decode!(&1)["files"] == side["files"]))
  end

  # The simulated camera, telling the test (by name) the moment its shutter has been pressed.
  defmodule Pressed do
    @behaviour Camera.Transport
    alias Camera.Transport.Sim

    @impl true
    defdelegate open(opts), to: Sim

    @impl true
    def write(s, bin, timeout) do
      with {:ok, %{shots: n}} = pressed when n > s.shots <- Sim.write(s, bin, timeout) do
        if pid = Process.whereis(:still_camera_test), do: send(pid, :shutter_pressed)
        pressed
      end
    end

    @impl true
    defdelegate read(s, max, timeout), to: Sim
    @impl true
    defdelegate event(s, timeout), to: Sim
    @impl true
    defdelegate close(s), to: Sim
  end

  @tag timeout: 60_000
  test "the sidecar has the settings the picture was taken at, not what the dial was turned to while it came down", %{cam: cam} do
    stop_supervised!({Camera.Server, cam})
    told = "sim-still-told-#{System.unique_integer([:positive])}"
    start_supervised!({Camera.Server, id: told, transport: {Pressed, []}})
    assert_receive {:still_camera, %{camera: %{id: ^told, state: :ready}}}, 10_000
    assert {:ok, %{settings: %{iso: 3200}}} = StillCamera.set(iso: 3200)
    Process.register(self(), :still_camera_test)

    before = (StillCamera.status().last || %{})[:seq] || 0
    StillCamera.shoot()
    assert_receive :shutter_pressed, 5_000
    # the night it happened: ISO 3200 turned to 800 between the shutter and the sidecar being written
    assert {:ok, %{settings: %{iso: 800}}} = StillCamera.set(iso: 800)
    assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000

    side = last.sidecar |> File.read!() |> Jason.decode!()
    assert %{"iso" => 3200, "settings_from" => "shutter"} = side["camera"]
    # the camera itself says 800 by now, and the next picture is taken at that
    assert Camera.status(told).settings.iso == 800
    assert %{"iso" => 800} = (picture().sidecar |> File.read!() |> Jason.decode!())["camera"]
  end

  @tag timeout: 60_000
  test "nothing is ever written over: two pictures with the same name in the same second are both kept" do
    a = picture()
    b = picture()
    assert MapSet.disjoint?(MapSet.new(a.files), MapSet.new(b.files))
    assert Enum.all?(a.files ++ b.files, &File.exists?/1)
    assert a.sidecar != b.sidecar
  end

  describe "the first picture after a slew" do
    test "a shutter that opened within the settle time of the mount's last slew is settling: one second after is, three seconds after is not" do
      # as the BEAM gives it, which is negative: nothing here may compare a time against 0
      t = System.monotonic_time(:millisecond)
      assert StillCamera.settling?(t, t + 1_000)
      refute StillCamera.settling?(t, t + 3_000)
      assert StillCamera.settling?(-9_000, -8_000) and not StillCamera.settling?(-9_000, -6_000)
      # still slewing when the shutter opened
      assert StillCamera.settling?(t, t)
      # the settle time is a parameter
      refute StillCamera.settling?(t, t + 1_000, 500)
      assert StillCamera.settling?(t, t + 3_000, 5_000)
      # a mount never seen slewing has nothing to settle from
      refute StillCamera.settling?(nil, t)
    end

    test "a slew is a Go To in flight or an axis faster than a tracker drives it; tracking is not" do
      axis = fn rate, goto -> %{degrees: 10.0, deg_per_s: rate, running: rate != 0.0, goto_pending: goto} end
      still = %{id: "m", axes: %{ra: axis.(0.0, false), dec: axis.(0.0, false)}}
      refute StillCamera.slewing?(still)
      assert StillCamera.slewing?(put_in(still.axes.ra, axis.(3.3, true)))
      assert StillCamera.slewing?(put_in(still.axes.dec, axis.(-0.2, false)))
      # a Go To that has been asked for and not yet got going
      assert StillCamera.slewing?(put_in(still.axes.ra, axis.(0.0, true)))
      # sidereal tracking, and Lock On steering both motors at about that
      refute StillCamera.slewing?(put_in(still.axes.ra, axis.(0.0042, false)))
      refute StillCamera.slewing?(%{still | axes: %{ra: axis.(0.0041, false), dec: axis.(-0.0016, false)}})
      # the speed that counts as a slew is a parameter
      assert StillCamera.slewing?(put_in(still.axes.ra, axis.(0.0042, false)), 0.001)
      # no mount, or one that isn't answering, isn't slewing
      refute StillCamera.slewing?(nil)
      refute StillCamera.slewing?(%{id: "m", connected: false})
    end

    # when a slew just asked for has ended, by this VM's clock (which is what the still camera stamps with)
    defp slew_ended(mount, seen \\ false, tries \\ 600) do
      slewing = StillCamera.slewing?(Mount.snapshot(mount))

      cond do
        seen and not slewing -> System.monotonic_time(:millisecond)
        tries == 0 -> flunk("the slew never ended")
        true -> Process.sleep(20) && slew_ended(mount, seen or slewing, tries - 1)
      end
    end

    defp sleep_until(mono), do: Process.sleep(max(mono - System.monotonic_time(:millisecond), 0))

    @tag timeout: 60_000
    test "a picture one second after a simulated slew ends is marked settling in its sidecar and not counted; one three seconds after is neither" do
      mount = "sim-still-settle-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(mount)
      assert_receive {:mount, %{connected: true}}, 2_000

      # a picture through this mount, which stands still: the still camera follows the mount from here on
      first = picture()
      assert first.mount == mount and first.settling == false
      assert (first.sidecar |> File.read!() |> Jason.decode!())["settling"] == false
      good = StillCamera.status().good

      :ok = Mount.goto_relative(mount, :ra, 2.0)
      t = slew_ended(mount)

      sleep_until(t + 1_000)
      soon = picture()
      assert soon.settling == true
      side = soon.sidecar |> File.read!() |> Jason.decode!()
      assert side["settling"] == true
      assert %{"since_slew_s" => since, "settle_s" => 2.0} = side["settle"]
      # (a tenth of slack: the still camera stamps the mount's last moving report as it reads it)
      assert since >= 0.9 and since < 2.0
      # marked, never deleted, and not counted as a good picture
      assert Enum.all?(soon.files, &File.exists?/1)
      assert StillCamera.status().good == good

      sleep_until(t + 3_000)
      later = picture()
      assert later.settling == false
      assert %{"settling" => false, "settle" => %{"since_slew_s" => since}} = later.sidecar |> File.read!() |> Jason.decode!()
      assert since >= 2.9
      assert StillCamera.status().good == good + 1
    end

    @tag timeout: 60_000
    test "the settle time is the caller's: a picture one second after a slew is not settling when half a second is asked for" do
      mount = "sim-still-settle-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(mount)
      assert_receive {:mount, %{connected: true}}, 2_000
      picture()

      :ok = Mount.goto_relative(mount, :dec, 2.0)
      t = slew_ended(mount)
      sleep_until(t + 1_000)
      before = StillCamera.status().last.seq
      StillCamera.shoot(settle_ms: 500)
      assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000
      assert last.settling == false
      assert %{"settling" => false, "settle" => %{"settle_s" => 0.5}} = last.sidecar |> File.read!() |> Jason.decode!()
    end

    @tag timeout: 60_000
    test "a picture the mount slewed under is marked too, though nothing moved before the shutter opened", %{cam: cam} do
      mount = "sim-still-settle-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(mount)
      assert_receive {:mount, %{connected: true}}, 2_000

      # a camera whose shutter is open for a second (its 4 s at a quarter of real time), and says when it is pressed
      stop_supervised!({Camera.Server, cam})
      slow = "sim-still-slow-#{System.unique_integer([:positive])}"
      start_supervised!({Camera.Server, id: slow, transport: {Pressed, [time_scale: 0.25]}})
      assert_receive {:still_camera, %{camera: %{id: ^slow, state: :ready}}}, 10_000
      Process.register(self(), :still_camera_test)
      good = StillCamera.status().good

      before = (StillCamera.status().last || %{})[:seq] || 0
      StillCamera.shoot()
      assert_receive :shutter_pressed, 5_000
      :ok = Mount.goto_relative(mount, :ra, 2.0)
      assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000

      assert last.mount == mount and last.settling == true and last.since_slew_s == 0.0
      assert %{"settling" => true, "settle" => %{"since_slew_s" => since}} = last.sidecar |> File.read!() |> Jason.decode!()
      assert since == 0.0
      assert StillCamera.status().good == good
    end

    @tag timeout: 60_000
    test "the page says in one line why the last picture isn't counted", %{conn: conn} do
      last = picture()
      {:ok, view, html} = live(conn, ~p"/cameras/stills")
      refute html =~ "Mount settling"

      status = StillCamera.status()
      send(view.pid, {:still_camera, %{status | last: Map.merge(last, %{settling: true, since_slew_s: 1.04})}})
      html = render(view)
      assert html =~ "Mount settling: taken 1.0 s after a slew. Kept, not counted"
      assert html =~ ~r/<p[^>]*role="status"[^>]*>\s*Mount settling/

      # the mount slewed with the shutter open
      send(view.pid, {:still_camera, %{status | last: Map.merge(last, %{settling: true, since_slew_s: 0.0})}})
      assert render(view) =~ "Mount slewing during the exposure. Kept, not counted"
    end
  end

  describe "cloud" do
    # The simulated camera with a roll of pictures in it: each press of the shutter takes the next
    # (and the last one again after that).
    defmodule Roll do
      @behaviour Camera.Transport
      alias Camera.Transport.Sim

      @impl true
      def open(opts), do: with({:ok, s} <- Sim.open(opts), do: {:ok, Map.put(s, :roll, Keyword.fetch!(opts, :pictures))})
      @impl true
      def write(s, bin, timeout), do: Sim.write(%{s | picture: Enum.at(s.roll, min(s.shots, length(s.roll) - 1))}, bin, timeout)
      @impl true
      defdelegate read(s, max, timeout), to: Sim
      @impl true
      defdelegate event(s, timeout), to: Sim
      @impl true
      defdelegate close(s), to: Sim
    end

    # A star field as the camera would send it: made in light, then bent into a JPEG's levels the
    # way a camera bends them (a power of 1/2.2). Its stars are `stars` times as bright as a clear
    # sky's, over a sky `sky` times as bright.
    defp sky_picture(stars, sky) do
      {w, h, sigma} = {1200, 800, 2.5}
      at = [{150, 120, 100}, {420, 200, 80}, {700, 150, 60}, {1000, 180, 110}, {250, 420, 70}, {560, 500, 50}, {860, 440, 90}, {1050, 650, 40}, {380, 680, 75}, {720, 660, 65}]

      light =
        for {cx, cy, peak} <- at, y <- (cy - 15)..(cy + 15), x <- (cx - 15)..(cx + 15), into: %{} do
          {{x, y}, stars * peak * :math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma * sigma))}
        end

      px = for y <- 0..(h - 1), x <- 0..(w - 1), into: <<>>, do: <<round(255 * :math.pow(min(2.0 * sky + Map.get(light, {x, y}, 0.0), 255.0) / 255, 1 / 2.2))>>
      pgm = Path.join(System.tmp_dir!(), "sky-picture-#{System.unique_integer([:positive])}.pgm")
      File.write!(pgm, ["P5\n#{w} #{h}\n255\n", px])
      {jpeg, 0} = System.cmd("ffmpeg", ~w(-loglevel error -i #{pgm} -q:v 2 -frames:v 1 -f image2pipe -vcodec mjpeg -))
      File.rm(pgm)
      jpeg
    end

    # this test's camera, with these pictures in it
    defp roll(cam, pictures) do
      stop_supervised!({Camera.Server, cam})
      id = "sim-still-roll-#{System.unique_integer([:positive])}"
      start_supervised!({Camera.Server, id: id, transport: {Roll, pictures: pictures}})
      assert_receive {:still_camera, %{camera: %{id: ^id, state: :ready}}}, 10_000
      id
    end

    defp side(record), do: record.sidecar |> File.read!() |> Jason.decode!()

    @tag timeout: 120_000
    test "three pictures with the stars 25 percent dimmer under a sky twice as bright are flagged in their sidecars, not counted, and the page says so while it lasts", %{cam: cam, conn: conn} do
      {clear, cloudy} = {sky_picture(1.0, 1.0), sky_picture(0.75, 2.0)}
      roll(cam, [clear, clear, cloudy, cloudy, cloudy, clear])
      {:ok, view, _html} = live(conn, ~p"/cameras/stills")
      good = StillCamera.status().good

      # the first picture of a field is its own yardstick; the next, as clear, reads the same
      first = picture()
      assert first.cloud == false and first.transparency == 1.0
      assert %{"cloud" => false, "transparency" => 1.0, "transparency_from" => %{"first" => true, "stars" => 10}} = side(first)
      second = picture()
      assert second.cloud == false
      assert_in_delta second.transparency, 1.0, 0.02
      assert StillCamera.status().good == good + 2
      refute render(view) =~ "cloud"

      for _ <- 1..3 do
        through = picture()
        assert through.cloud == true
        assert_in_delta through.transparency, 0.75, 0.04
        assert %{"cloud" => true, "transparency" => t, "transparency_from" => %{"stars" => 10, "sky_ratio" => sky}} = side(through)
        assert t == through.transparency
        # twice the light of sky is 1.37 times the level
        assert_in_delta sky, 1.37, 0.08
        # kept, like every picture
        assert Enum.all?(through.files, &File.exists?/1)
        html = render(view)
        assert html =~ ~r/Thin cloud: stars 2\d percent dimmer\. Kept, not counted/
        assert html =~ ~r/<p[^>]*role="status"[^>]*>\s*Thin cloud/
      end

      # the count of good pictures has not moved
      assert StillCamera.status().good == good + 2

      after_it = picture()
      assert after_it.cloud == false
      assert_in_delta after_it.transparency, 1.0, 0.02
      assert StillCamera.status().good == good + 3
      refute render(view) =~ "cloud"
    end

    @tag timeout: 120_000
    test "the limits are the caller's: stars 25 percent dimmer are not cloud when 40 percent is asked for", %{cam: cam} do
      roll(cam, [sky_picture(1.0, 1.0), sky_picture(0.75, 2.0)])
      picture()
      before = StillCamera.status().last.seq
      StillCamera.shoot(cloud: [dimmer: 0.4])
      assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000
      assert last.cloud == false
      assert_in_delta last.transparency, 0.75, 0.04
    end

    @tag timeout: 120_000
    test "the field starts again when the mount slews further than a picture is wide, and not for a nudge", %{cam: cam} do
      mount = "sim-still-cloud-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(mount)
      assert_receive {:mount, %{connected: true}}, 2_000
      roll(cam, [sky_picture(1.0, 1.0), sky_picture(0.75, 2.0)])

      # a picture's width at 2032 mm: 0.66 degrees
      shoot = fn ->
        before = (StillCamera.status().last || %{})[:seq] || 0
        StillCamera.shoot(cloud: [field_deg: 0.66])
        assert_receive {:still_camera, %{busy: false, last: %{seq: seq} = last}} when seq > before, 15_000
        last
      end

      first = shoot.()
      assert first.mount == mount and first.transparency == 1.0

      # nudged a tenth of a degree: the same stars, held against the clear picture
      :ok = Mount.goto_relative(mount, :ra, 0.1)
      slew_ended(mount)
      nudged = shoot.()
      assert nudged.cloud == true
      assert_in_delta nudged.transparency, 0.75, 0.04

      # two degrees away: another field, with nothing yet to hold its stars against
      :ok = Mount.goto_relative(mount, :ra, 2.0)
      slew_ended(mount)
      away = shoot.()
      assert away.cloud == false and away.transparency == 1.0
      assert %{"transparency_from" => %{"first" => true}} = side(away)
    end

    test "in the sidecar, what was said about cloud is written and what couldn't be said is left out" do
      alias Controller.StillCamera.Sidecar
      build = fn sky -> Sidecar.build(%{saved_at: DateTime.utc_now(), files: [%{name: "20261004-074708-DSC01383.JPG"}], sky: sky}) end

      # thick cloud: the stars are gone, so there is no transparency, and it is cloud all the same
      gone = build.(%{cloud: true, transparency: nil, stars: 0, sky_ratio: 4.2})
      assert %{"cloud" => true, "transparency_from" => %{"stars" => 0, "sky_ratio" => 4.2}} = gone
      refute Map.has_key?(gone, "transparency")

      # nothing to go by (no stars, the Moon): no word about cloud at all, rather than "no cloud"
      for sky <- [%{cloud: nil, transparency: nil, stars: 0, sky_ratio: 1.0}, nil] do
        refute Enum.any?(~w(cloud transparency transparency_from), &Map.has_key?(build.(sky), &1))
      end
    end

    @tag timeout: 60_000
    test "the page says how much dimmer the stars are, or that they are gone", %{conn: conn} do
      last = picture()
      {:ok, view, _html} = live(conn, ~p"/cameras/stills")
      status = StillCamera.status()
      show = fn more -> send(view.pid, {:still_camera, %{status | last: Map.merge(last, more)}}) && render(view) end

      assert show.(%{cloud: true, transparency: 0.8}) =~ "Thin cloud: stars 20 percent dimmer. Kept, not counted"
      assert show.(%{cloud: true, transparency: 0.31}) =~ "Cloud: stars 69 percent dimmer. Kept, not counted"
      assert show.(%{cloud: true, transparency: nil}) =~ "Cloud: no stars left to measure. Kept, not counted"
      # dimmer stars that aren't cloud say nothing, and a settling picture through cloud says both
      refute show.(%{cloud: false, transparency: 0.7}) =~ "loud"
      both = show.(%{cloud: true, transparency: 0.75, settling: true, since_slew_s: 1.0})
      assert both =~ "Mount settling" and both =~ "Thin cloud: stars 25 percent dimmer"
    end
  end

  describe "star size" do
    # A star field as the camera would send it: 1200 x 800, a dark sky, Gaussian stars 3 px in sigma
    # (a half-flux diameter of 7.06 px), made into a JPEG by ffmpeg.
    defp star_field do
      {w, h, sigma} = {1200, 800, 3.0}
      stars = [{150, 120, 200}, {420, 200, 180}, {700, 150, 160}, {1000, 180, 190}, {250, 420, 170}, {560, 500, 150}, {860, 440, 185}, {1050, 650, 140}, {380, 680, 175}]

      light =
        for {cx, cy, peak} <- stars, y <- (cy - 15)..(cy + 15), x <- (cx - 15)..(cx + 15), into: %{} do
          {{x, y}, peak * :math.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma * sigma))}
        end

      px = for y <- 0..(h - 1), x <- 0..(w - 1), into: <<>>, do: <<min(round(8 + Map.get(light, {x, y}, 0)), 255)>>
      pgm = Path.join(System.tmp_dir!(), "star-field-#{System.unique_integer([:positive])}.pgm")
      File.write!(pgm, ["P5\n#{w} #{h}\n255\n", px])
      {jpeg, 0} = System.cmd("ffmpeg", ~w(-loglevel error -i #{pgm} -q:v 2 -frames:v 1 -f image2pipe -vcodec mjpeg -))
      File.rm(pgm)
      jpeg
    end

    @tag timeout: 60_000
    test "a picture says how wide its stars are, or cleanly that it has none to measure: in the status and beside the picture" do
      a = picture()
      # the simulated camera's picture is the Moon: no stars to focus by, and that is nil, not a failure
      assert Map.has_key?(a, :star_size)
      assert Enum.all?(a.files, &File.exists?/1) and a.w == 960
      side = a.sidecar |> File.read!() |> Jason.decode!()

      case a.star_size do
        nil ->
          refute Map.has_key?(side["measured"], "star_size")

        %{px: px, n: n} ->
          assert px > 0 and n >= 1
          assert %{"px" => ^px, "n" => ^n} = side["measured"]["star_size"]
      end

      # the next picture carries this one's, so a page can say which way the focus went
      b = picture()
      assert b.star_size_was == a.star_size
    end

    test "the stars of a star field are measured at the picture's own size, in pixels and, with a focal length, in arcseconds" do
      jpeg = star_field()
      assert StillCamera.jpeg_width(jpeg) == 1200
      assert %{px: px, n: 9, w: 1200, arcsec: arcsec, arcsec_per_px: scale} = StillCamera.star_size(jpeg, focal_length_mm: 2032)
      # 2.3548 sigma, within a tenth
      assert_in_delta px, 7.06, 0.7
      # 23.5 mm of sensor across 1200 px behind 2032 mm
      assert_in_delta scale, 206_264.8 * 23.5 / (2032 * 1200), 0.001
      assert_in_delta arcsec, px * scale, 0.02

      # the knobs reach the measuring: three stars asked for, three measured
      assert %{n: 3} = StillCamera.star_size(jpeg, focal_length_mm: 2032, max_stars: 3)

      # with no focal length in Settings there are no arcseconds to give, and the pixels still stand
      was = Controller.Settings.get("focal_length_mm")
      on_exit(fn -> Controller.Settings.put("focal_length_mm", was) end)
      Controller.Settings.put("focal_length_mm", nil)
      assert %{px: ^px, arcsec: nil, arcsec_per_px: nil} = StillCamera.star_size(jpeg)
      Controller.Settings.put("focal_length_mm", 2032)
      assert %{px: ^px, arcsec: ^arcsec} = StillCamera.star_size(jpeg)
    end

    test "whatever goes wrong measuring star size is nil, never a crash: no picture, no stars, out of time" do
      assert StillCamera.star_size("not a jpeg") == nil
      assert StillCamera.star_size(<<>>) == nil
      assert StillCamera.star_size(File.read!(Path.join(:code.priv_dir(:camera), "sim/a6000/moon.jpg"))) == nil
      # a deadline that has already passed: nil at once, and the process that takes pictures is unharmed
      jpeg = star_field()
      assert StillCamera.star_size(jpeg, timeout: 0) == nil
      assert Process.alive?(Process.whereis(StillCamera))
      assert %{n: 9} = StillCamera.star_size(jpeg)
    end

    @tag timeout: 60_000
    test "the page says the star size under the picture, the one before it, and how many stars; or that there are none", %{conn: conn} do
      {:ok, view, _html} = live(conn, ~p"/cameras/stills")
      view |> element("button", "Take Picture") |> render_click()
      assert_receive {:still_camera, %{busy: false, last: %{w: 960}}}, 15_000
      html = render(view)
      # the Moon: no stars, said in a few words, with what to do and where it is explained
      assert html =~ "Star size: no stars to measure"
      assert html =~ "Smaller is sharper. Turn the focus knob a little, take a picture, compare."
      assert html =~ ~s(href="/docs/still-camera#focusing") and html =~ ~s(aria-label="help: focusing")

      # a picture with stars, as the camera's process would announce it
      status = StillCamera.status()
      now = %{arcsec: 8.23, px: 10.42, n: 12, w: 3000, arcsec_per_px: 0.7951}
      send(view.pid, {:still_camera, put_in(status.last, Map.merge(status.last, %{star_size: now, star_size_was: %{now | arcsec: 9.49, px: 11.94}}))})
      assert render(view) =~ "Star size 8.2 arcsec, was 9.5 (12 stars)"

      # the first picture with stars has nothing before it; one star is one star
      send(view.pid, {:still_camera, put_in(status.last, Map.merge(status.last, %{star_size: %{now | n: 1}, star_size_was: nil}))})
      assert render(view) =~ "Star size 8.2 arcsec (1 star)"

      # no focal length: pixels, against pixels
      px = %{now | arcsec: nil, arcsec_per_px: nil}
      send(view.pid, {:still_camera, put_in(status.last, Map.merge(status.last, %{star_size: px, star_size_was: %{px | px: 11.94}}))})
      assert render(view) =~ "Star size 10.4 px, was 11.9 (12 stars)"
    end

    test "the docs explain focusing where the page's ? points", %{conn: conn} do
      html = conn |> get(~p"/docs/still-camera") |> html_response(200)
      assert html =~ ~s(id="focusing")
      assert html =~ "Finish with a counter-clockwise turn"
    end
  end

  test "shutter speeds as the camera words them, in seconds" do
    alias Controller.StillCamera.Sidecar
    assert_in_delta Sidecar.seconds("1/60"), 1 / 60, 1.0e-9
    assert Sidecar.seconds("4") == 4.0
    assert Sidecar.seconds("2.5") == 2.5
    assert Sidecar.seconds("Bulb") == nil
    assert Sidecar.seconds(nil) == nil
  end

  @tag timeout: 60_000
  test "pictures leave the box over HTTP: the nights, a night's files, each file whole", %{conn: conn} do
    last = picture()
    night = last.files |> hd() |> Path.dirname() |> Path.basename()

    assert [%{"night" => ^night, "files" => n, "bytes" => total} | _] = conn |> get(~p"/cameras/stills/files") |> json_response(200)
    assert n >= 3 and total > 0

    listed = conn |> get(~p"/cameras/stills/files/#{night}") |> json_response(200)
    raw = Enum.find(last.files, &String.ends_with?(&1, ".ARW"))
    assert %{"bytes" => bytes} = Enum.find(listed, &(&1["name"] == Path.basename(raw)))
    assert bytes == File.stat!(raw).size
    assert Enum.any?(listed, &(&1["name"] == "index.jsonl"))

    assert conn |> get(~p"/cameras/stills/files/#{night}/#{Path.basename(raw)}") |> response(200) == File.read!(raw)
    assert conn |> get(~p"/cameras/stills/files/#{night}/#{Path.basename(last.sidecar)}") |> response(200) =~ "observatory.still/1"

    # nothing outside a night's folder
    assert conn |> get("/cameras/stills/files/#{night}/..%2F..%2Fsettings.json") |> response(404)
    assert conn |> get(~p"/cameras/stills/files/nope") |> response(404)
  end

  test "a nearly full card stops pictures, and says so", %{conn: conn} do
    was = Application.get_env(:controller, :still_camera_floor_mb)
    Application.put_env(:controller, :still_camera_floor_mb, 1_000_000_000)
    on_exit(fn -> if was, do: Application.put_env(:controller, :still_camera_floor_mb, was), else: Application.delete_env(:controller, :still_camera_floor_mb) end)

    :ok = StillCamera.continuous(true)
    assert_receive {:still_camera, %{shooting: false, busy: false, why: why, room_for: 0}}, 5_000
    assert why =~ "SD card is nearly full"
    {:ok, _view, html} = live(conn, ~p"/cameras/stills")
    assert html =~ "SD card is nearly full"
    assert html =~ "room for about 0 pictures"
  end

  describe "plate solving" do
    # stand-in solvers: one that always knows where the picture is (straight overhead: a match
    # below the horizon is thrown out, whatever the time of day the tests run), one that sees no stars
    defmodule Solved do
      def overhead do
        site = Controller.Sky.Pointing.site()
        {Float.round(Controller.Sky.Astro.lst_deg(DateTime.utc_now(), site.lon), 3), site.lat * 1.0}
      end

      def solve(_image, opts) do
        {ra, dec} = Keyword.get(opts, :says, overhead())
        {:ok, %{ra_deg: ra, dec_deg: dec, width_deg: 0.66, height_deg: 0.44, rotation_deg: -143.0, parity: "neg", seconds: 2.5, stars: 30, solver: "stand-in"}}
      end
    end

    defmodule Starless do
      def solve(_image, _opts), do: {:error, :too_few_stars}
    end

    # the last picture's plate, once it is solved or failed (it can be either before the picture's
    # own "done" arrives, so this asks rather than waits for a message)
    defp solve_outcome do
      Enum.find_value(1..300, fn _ ->
        case StillCamera.status().solve do
          %{state: st} = solve when st in [:solved, :failed] -> solve
          _ -> Process.sleep(50) && nil
        end
      end)
    end

    setup do
      mount = "sim-still-solve-#{System.unique_integer([:positive])}"
      start_supervised!({Mount.Server, id: mount, transport: {Mount.Transport.Sim, []}})
      Mount.subscribe(mount)
      assert_receive {:mount, %{connected: true}}, 2_000
      solver = Application.get_env(:controller, :solver)
      # a solved picture measures the focal length and keeps it in Settings: what was there goes back
      optics = {Controller.Settings.get("focal_length_mm"), Controller.Settings.get("focal_length_solved")}

      on_exit(fn ->
        if solver, do: Application.put_env(:controller, :solver, solver), else: Application.delete_env(:controller, :solver)
        StillCamera.solving(false)
        Controller.Settings.put("focal_length_mm", elem(optics, 0))
        Controller.Settings.put("focal_length_solved", elem(optics, 1))
      end)

      :ok
    end

    @tag timeout: 60_000
    test "a solved picture says where the telescope pointed, joins the mount's plates, and the answer is written beside it", %{conn: conn} do
      Application.put_env(:controller, :solver, backend: Solved)
      :ok = StillCamera.solving(true)
      last = picture()
      assert %{mount: mount, n: n} = last.plate
      on_exit(fn -> Controller.Plates.clear(mount) end)
      {_, dec} = Solved.overhead()
      assert %{state: :solved, n: ^n, solution: %{ra_deg: ra, dec_deg: ^dec, stars: 30}} = solve_outcome()
      assert StillCamera.status().solving

      answer = (last.base <> ".solve.json") |> File.read!() |> Jason.decode!()
      assert %{"schema" => "observatory.still.solve/1", "state" => "solved", "plate" => ^n, "solution" => %{"ra_deg" => ^ra, "width_deg" => 0.66}} = answer
      assert Enum.any?(Controller.Plates.view(mount).plates, &(&1.n == n and &1.state == :solved))

      # the sidecar says which plate the picture became and where its answer is
      side = last.sidecar |> File.read!() |> Jason.decode!()
      assert %{"queued" => true, "plate" => ^n, "answer_in" => name} = side["plate_solve"]
      assert name == Path.basename(last.base) <> ".solve.json"

      {:ok, _view, html} = live(conn, ~p"/cameras/stills")
      assert html =~ ~r/Picture \d+: RA \d\dh \d\dm \d\ds, Dec \+\d\d° \d\d′ \d\d″ · 0\.66° × 0\.44° · 30 stars · 2\.5 s/
      assert html =~ "Solving On"
    end

    @tag timeout: 60_000
    test "a picture with too few stars says so, and what to change", %{conn: conn} do
      Application.put_env(:controller, :solver, backend: Starless)
      :ok = StillCamera.solving(true)
      last = picture()
      assert %{mount: mount} = last.plate
      on_exit(fn -> Controller.Plates.clear(mount) end)
      assert %{state: :failed, reason: "too_few_stars"} = solve_outcome()
      assert (last.base <> ".solve.json") |> File.read!() |> Jason.decode!() |> Map.get("state") == "failed"
      {:ok, _view, html} = live(conn, ~p"/cameras/stills")
      assert html =~ "not solved: too few stars. A longer shutter or a higher ISO shows more"
    end

    # The simulated camera with another picture in it (the simulator keeps its picture in its state).
    defmodule StarCamera do
      @behaviour Camera.Transport
      alias Camera.Transport.Sim

      @impl true
      def open(opts), do: with({:ok, s} <- Sim.open(opts), do: {:ok, %{s | picture: Keyword.fetch!(opts, :picture)}})
      @impl true
      defdelegate write(s, bin, timeout), to: Sim
      @impl true
      defdelegate read(s, max, timeout), to: Sim
      @impl true
      defdelegate event(s, timeout), to: Sim
      @impl true
      defdelegate close(s), to: Sim
    end

    # a solver that shows the test what it was handed, then answers as Solved does
    defmodule Shown do
      def solve(image, opts) do
        if pid = Process.whereis(:still_camera_test), do: send(pid, {:solver_given, image})
        Controller.StillCameraTest.Solved.solve(image, opts)
      end
    end

    @tag timeout: 60_000
    test "a picture of stars is measured and solved from one decode: the solver's copy is made from the star-size copy, and is byte for byte what it was", %{cam: cam} do
      jpeg = star_field()
      # this test's camera has stars in it, not the Moon
      stop_supervised!({Camera.Server, cam})
      stars = "sim-still-stars-#{System.unique_integer([:positive])}"
      start_supervised!({Camera.Server, id: stars, transport: {StarCamera, picture: jpeg}})
      assert_receive {:still_camera, %{camera: %{id: ^stars, state: :ready}}}, 10_000

      Process.register(self(), :still_camera_test)
      Application.put_env(:controller, :solver, backend: Shown)
      :ok = StillCamera.solving(true)
      # watch for the solver's copy being made from a copy already decoded (a private step, by name)
      :erlang.trace_pattern({StillCamera, :regrey, 2}, true, [:local])
      :erlang.trace(:all, true, [:call])
      on_exit(fn -> :erlang.trace_pattern({StillCamera, :regrey, 2}, false, [:local]) end)
      last = picture()
      :erlang.trace(:all, false, [:call])
      assert %{mount: mount} = last.plate
      on_exit(fn -> Controller.Plates.clear(mount) end)
      assert_received {:trace, _, :call, {StillCamera, :regrey, [<<"P5\n1200 800\n255\n", _::binary>>, "median=radius=1"]}}

      # how wide its stars are (2.3548 sigma of 3 px), in the status and beside the picture
      assert %{px: px, n: 9, w: 1200} = last.star_size
      assert_in_delta px, 7.06, 0.7
      side = last.sidecar |> File.read!() |> Jason.decode!()
      assert %{"px" => ^px, "n" => 9, "w" => 1200, "measure" => "half-flux diameter" <> _} = side["measured"]["star_size"]
      assert Enum.all?(last.files, &File.exists?/1)

      # the solver was handed its copy all the same: exactly what ffmpeg makes of the JPEG itself
      assert_receive {:solver_given, given}, 15_000
      path = Path.join(System.tmp_dir!(), "star-field-#{System.unique_integer([:positive])}.jpg")
      File.write!(path, jpeg)
      {direct, 0} = System.cmd("ffmpeg", ~w(-loglevel error -noautorotate -lowres 0 -i #{path} -vf format=gray,median=radius=1 -frames:v 1 -f image2pipe -vcodec pgm -))
      File.rm(path)
      assert <<"P5\n1200 800\n255\n", _::binary>> = given
      assert given == direct
      assert %{state: :solved} = solve_outcome()
    end

    # a solver whose field is 0.388 arcsec a pixel across the a6000's 6000 pixels: what the 8SE's plates said
    defmodule Measured do
      def solve(image, opts) do
        with {:ok, sol} <- Controller.StillCameraTest.Solved.solve(image, opts), do: {:ok, %{sol | width_deg: 0.388 * 6000 / 3600, height_deg: 0.388 * 4000 / 3600}}
      end
    end

    @tag timeout: 60_000
    test "the focal length is learned from the first solve, kept with the optics, and each sidecar says which it is" do
      alias Controller.Settings
      alias Controller.StillCamera.Optics
      # the label on the tube
      Settings.put("focal_length_mm", 2032)
      Settings.put("focal_length_solved", nil)
      Application.put_env(:controller, :solver, backend: Measured)
      :ok = StillCamera.solving(true)

      first = picture()
      assert %{mount: mount} = first.plate
      on_exit(fn -> Controller.Plates.clear(mount) end)
      # written before its own solve came back: the label, said to be one
      assert %{"focal_length_mm" => 2032, "focal_length_from" => "label"} = (first.sidecar |> File.read!() |> Jason.decode!())["optics"]
      assert %{state: :solved} = solve_outcome()

      # one solve at 0.388 arcsec per 3.9 micron pixel: 2,084 mm, within 5
      assert %{mm: mm, from: "solve", label_mm: 2032} = Optics.focal_length()
      assert_in_delta mm, 2084, 5
      assert Settings.get("focal_length_mm") == mm
      # the solve's own answer says what it measured
      assert %{"focal_length_mm" => ^mm} = (first.base <> ".solve.json") |> File.read!() |> Jason.decode!()

      # every picture from here on carries the measured one, and says where it came from
      second = picture()
      assert %{"focal_length_mm" => ^mm, "focal_length_from" => "solve", "focal_length_label_mm" => 2032} = (second.sidecar |> File.read!() |> Jason.decode!())["optics"]
    end

    # a solver that never answers
    defmodule Hangs do
      def solve(_image, _opts), do: Process.sleep(:infinity)
    end

    @tag timeout: 60_000
    test "a finder picture whose solver hangs gives {:error, :deadline} at its own deadline, the page says so, and the queue takes the next picture's plate", %{conn: conn} do
      Application.put_env(:controller, :solver, backend: Hangs)
      t0 = System.monotonic_time(:millisecond)
      assert StillCamera.finder(deadline: 500) == {:error, :deadline}
      took = System.monotonic_time(:millisecond) - t0
      # the picture, then its half second: not the solver's minute and a half
      assert took >= 500 and took < 5_000

      last = StillCamera.status().last
      assert %{mount: mount, n: n} = last.plate
      on_exit(fn -> Controller.Plates.clear(mount) end)
      assert %{state: :failed, reason: "deadline", finder: true} = Enum.find(Controller.Plates.view(mount).plates, &(&1.n == n))
      assert Controller.Plates.status().solving == 0
      # the picture is kept like any other, and its answer says why it has none
      assert Enum.all?(last.files, &File.exists?/1)
      assert %{"state" => "failed", "reason" => "deadline"} = (last.base <> ".solve.json") |> File.read!() |> Jason.decode!()
      {:ok, _view, html} = live(conn, ~p"/cameras/stills")
      assert html =~ "not solved: the finder solve missed its deadline. The model&#39;s aim stands"

      # the queue has moved on: the next picture's plate is solved
      Application.put_env(:controller, :solver, backend: Solved)
      :ok = StillCamera.solving(true)
      picture()
      assert %{state: :solved} = solve_outcome()
    end

    @tag timeout: 60_000
    test "shoot anyway: a finder that isn't solved hands back the model's aim instead, and the caller carries on" do
      Application.put_env(:controller, :solver, backend: Hangs)
      assert {:ok, %{from: :model, why: :deadline, seq: seq} = aim} = StillCamera.finder(deadline: 300, shoot_anyway: true)
      assert Map.has_key?(aim, :ra_deg) and Map.has_key?(aim, :dec_deg)
      last = StillCamera.status().last
      assert last.seq == seq
      on_exit(fn -> Controller.Plates.clear(last.plate.mount) end)

      # the solver's own reasons come back as they are, and can be shot through the same way
      Application.put_env(:controller, :solver, backend: Starless)
      assert StillCamera.finder(deadline: 5_000) == {:error, :too_few_stars}
      assert {:ok, %{from: :model, why: :too_few_stars}} = StillCamera.finder(deadline: 5_000, shoot_anyway: true)
    end

    @tag timeout: 60_000
    test "a finder picture that solves says where the telescope points, well inside its 30 seconds, whether or not pictures are being solved" do
      Application.put_env(:controller, :solver, backend: Solved)
      :ok = StillCamera.solving(false)
      {_, dec} = Solved.overhead()
      assert {:ok, %{from: :solve, ra_deg: ra, dec_deg: ^dec, width_deg: 0.66, stars: 30, seq: seq}} = StillCamera.finder()
      assert is_number(ra)
      last = StillCamera.status().last
      assert last.seq == seq
      on_exit(fn -> Controller.Plates.clear(last.plate.mount) end)
      # and the pictures after it are not solved, as before
      refute StillCamera.status().solving
      assert picture().plate == nil
    end

    @tag timeout: 60_000
    @tag capture_log: true
    test "a finder's caller is answered at the deadline even when the plate queue is restarted under it and forgets it was a finder" do
      Application.put_env(:controller, :solver, backend: Hangs)
      asked = Task.async(fn -> StillCamera.finder(deadline: 500) end)
      # its plate is with the solver: now the queue dies, and comes back with a plate like any other
      assert Enum.find(1..200, fn _ -> match?(%{solving: 1}, Controller.Plates.status()) or (Process.sleep(25) && false) end)
      queue = Process.whereis(Controller.Plates)
      Process.exit(queue, :kill)

      assert Task.await(asked, 15_000) == {:error, :deadline}
      assert Enum.find(1..200, fn _ -> Process.whereis(Controller.Plates) not in [nil, queue] or (Process.sleep(25) && false) end)
      on_exit(fn -> Controller.Plates.clear(StillCamera.status().last.plate.mount) end)
    end

    @tag timeout: 60_000
    test "a finder that can't take its picture says so at once: no camera, or a picture already being taken", %{cam: cam} do
      # this camera's shutter is open for a second and a half
      stop_supervised!({Camera.Server, cam})
      slow = "sim-still-slow-#{System.unique_integer([:positive])}"
      start_supervised!({Camera.Server, id: slow, transport: {Pressed, [time_scale: 0.4]}})
      assert_receive {:still_camera, %{camera: %{id: ^slow, state: :ready}}}, 10_000
      Process.register(self(), :still_camera_test)

      before = (StillCamera.status().last || %{})[:seq] || 0
      StillCamera.shoot()
      assert_receive :shutter_pressed, 5_000
      assert StillCamera.finder(deadline: 300) == {:error, :busy}
      assert_receive {:still_camera, %{busy: false, last: %{seq: seq}}} when seq > before, 15_000

      stop_supervised!({Camera.Server, slow})
      assert_receive {:still_camera, %{camera: nil}}, 10_000
      assert StillCamera.finder(deadline: 300) == {:error, :no_camera}
    end

    test "with solving off a picture is not sent to the solver" do
      :ok = StillCamera.solving(false)
      last = picture()
      assert last.plate == nil
      refute File.exists?(last.base <> ".solve.json")
    end

    test "how much sky a picture covers comes from the focal length: 0.66 degrees across at 2032 mm" do
      was = Controller.Settings.get("focal_length_mm")
      on_exit(fn -> Controller.Settings.put("focal_length_mm", was) end)
      Controller.Settings.put("focal_length_mm", 2032)
      {lo, hi} = StillCamera.field_scale()
      assert lo < 0.66 and hi > 0.66 and lo > 0.45 and hi < 0.9
      Controller.Settings.put("focal_length_mm", nil)
      assert StillCamera.field_scale() == {0.1, 5.0}
    end
  end

  test "the copy is measured the sensor's way up, and a big JPEG is decoded small: the width is read past the EXIF thumbnail" do
    sof = fn w, h -> <<0xFF, 0xC0, 17::16, 8, h::16, w::16, 3, 0::size(9 * 8)>> end
    exif = <<"Exif", 0, 0>> <> sof.(160, 120)
    jpeg = <<0xFF, 0xD8, 0xFF, 0xE1, byte_size(exif) + 2::16>> <> exif <> sof.(6000, 4000) <> <<0xFF, 0xDA>>
    assert StillCamera.jpeg_width(jpeg) == 6000
    assert StillCamera.jpeg_width("not a jpeg") == nil
    assert StillCamera.lowres(6000) == 2
    assert StillCamera.lowres(960) == 0
    assert StillCamera.lowres(nil) == 0
    assert StillCamera.jpeg_width(File.read!(Path.join(:code.priv_dir(:camera), "sim/a6000/moon.jpg"))) == 240
  end
end
