defmodule Controller.LockOnTest do
  @moduledoc """
  Lock On against a simulated mount and a simulated sky: a target that drifts
  across the picture like the Moon did on 2026-10-02 (an EQ6-R pointed nowhere
  near the pole), and moves with the simulated motors through a picture-space
  mapping Lock On doesn't know. It has to measure both, then hold the target
  still, and stand down in the right way for each thing that can go wrong.
  """
  use ExUnit.Case, async: false

  alias Controller.LockOn
  alias Controller.LockOn.Law
  alias Controller.ScopeCamera.Image

  # the sky: px per degree of each axis (RA column, Dec column), and the drift with the motors still
  @a {{-900.0, 40.0}, {60.0, -1000.0}}
  @drift {6.0, -4.0}
  @fast [
    tick_ms: 50,
    drift_min_ms: 600,
    nudge_ms: 800,
    settle_ms: 500,
    nudge_rate: 8.0,
    k: 1 / 1.2,
    ki: 0.0,
    max_rate: 20.0,
    stale_ms: 1_000,
    coast_ms: 1_500
  ]

  # -- the arithmetic ----------------------------------------------------------------------------

  test "a motor's column is the move it made, net of the drift, per 1× per second" do
    # 8× for 2 s on an axis that moves the picture 3 px/s per 1×, with 1 px/s of drift over 2.5 s
    assert {3.0, -1.0} == Law.column({48.0 + 2.5, -16.0}, {1.0, 0.0}, 2.5, 8.0, 2.0)
  end

  test "two motors that move the picture the same way can't steer it" do
    assert Law.inverse({{3.0, 3.1}, {1.0, 1.02}}) == :singular
    assert {{_, _}, {_, _}} = Law.inverse({{-7.6, 0.45}, {0.04, -11.5}})
  end

  test "the rates cancel the drift, and push a target that's off back toward its spot" do
    minv = Law.inverse({{-7.6, 0.45}, {0.04, -11.5}})
    cal = %{minv: minv, drift: {1.73, -6.15}}
    # tonight's numbers: the rates that held the Moon
    {ra0, dec0} = Law.rates(cal, {0, 0}, {0, 0})
    assert_in_delta ra0, 0.196, 0.01
    assert_in_delta dec0, -0.534, 0.01
    # off to the right: RA (which moves the picture left) speeds up
    {ra, _} = Law.rates(cal, {100.0, 0.0}, {0, 0})
    assert ra > ra0
  end

  test "a bright target's middle is found, and so is whether it runs off the edge of the picture" do
    w = 200
    h = 120

    disc = fn cx, cy, r ->
      for y <- 0..(h - 1),
          x <- 0..(w - 1),
          into: <<>>,
          do: <<if((x - cx) ** 2 + (y - cy) ** 2 <= r * r, do: 200, else: 12)>>
    end

    img = %{w: w, h: h, px: disc.(120, 50, 20)}
    b = Image.bright(img, Image.stats(img))
    assert_in_delta b.x, 120, 2
    assert_in_delta b.y, 50, 2
    refute b.edge

    img = %{w: w, h: h, px: disc.(195, 60, 25)}
    assert Image.bright(img, Image.stats(img)).edge

    flat = %{w: w, h: h, px: :binary.copy(<<12>>, w * h)}
    assert Image.bright(flat, Image.stats(flat)) == nil
  end

  # -- the loop on a simulated mount and sky -----------------------------------------------------

  setup do
    id = "sim-lock-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    saved = Controller.Settings.get("lock_on")

    # a lock left holding would wait for its (gone) mount and be picked up by whatever runs next
    on_exit(fn ->
      LockOn.release()
      Controller.Settings.put("lock_on", saved)
    end)

    LockOn.release()

    {:ok, sky} =
      Agent.start_link(fn ->
        %{on: true, hidden: false, t0: System.monotonic_time(:millisecond), axes0: axes(id)}
      end)

    pid = spawn_link(fn -> feed(id, sky) end)
    on_exit(fn -> Process.exit(pid, :kill) end)
    %{id: id, sky: sky}
  end

  defp axes(id) do
    s = Mount.snapshot(id)
    {s.axes.ra.degrees, s.axes.dec.degrees}
  end

  # a picture every 100 ms: where the target is, from the sky's drift and the motors' actual positions
  defp feed(id, sky) do
    st = Agent.get(sky, & &1)

    if st.on do
      {ra, dec} = axes(id)
      {ra0, dec0} = st.axes0
      t = (System.monotonic_time(:millisecond) - st.t0) / 1000
      {{a, b}, {c, d}} = @a
      {dx, dy} = @drift
      x = 480 + 30 + a * (ra - ra0) + b * (dec - dec0) + dx * t
      y = 270 - 20 + c * (ra - ra0) + d * (dec - dec0) + dy * t
      target = if st.hidden, do: nil, else: %{x: x, y: y}
      LockOn.observe(%{at: System.monotonic_time(:millisecond), w: 960, h: 540, target: target})
    end

    Process.sleep(100)
    feed(id, sky)
  end

  defp until(fun, ms \\ 8_000) do
    deadline = System.monotonic_time(:millisecond) + ms

    Stream.repeatedly(fn ->
      Process.sleep(50)
      fun.()
    end)
    |> Enum.find(fn r -> r || System.monotonic_time(:millisecond) > deadline end)
  end

  @tag timeout: 60_000
  test "it measures the drift and both motors, then holds the target on its spot", %{id: id} do
    :ok = LockOn.start(id, @fast)
    assert LockOn.status().state == :calibrating
    until(fn -> LockOn.status().state == :holding end)
    assert LockOn.status().state == :holding

    # the calibration found the sky's mapping (1× sidereal = 0.004178°/s), near enough to steer by
    %{calibration: %{m: {{a, _b}, {_c, d}}, drift: {dx, dy}}} = LockOn.status()
    assert_in_delta a, -900 * 0.004178, 1.2
    assert_in_delta d, -1000 * 0.004178, 1.2
    assert_in_delta dx, 6.0, 1.5
    assert_in_delta dy, -4.0, 1.5

    # and it pulls the target onto its spot and keeps it there
    Process.sleep(4_000)
    {ex, ey} = LockOn.status().error_px
    assert abs(ex) < 4 and abs(ey) < 4, "still #{ex}, #{ey} px off"
  end

  @tag timeout: 60_000
  test "a hidden target: it coasts on the drift, gives up the motors after a while, and takes it back when it shows",
       %{id: id, sky: sky} do
    :ok = LockOn.start(id, @fast)
    until(fn -> LockOn.status().state == :holding end)
    Agent.update(sky, &%{&1 | hidden: true})
    until(fn -> LockOn.status().state == :coasting end, 2_000)
    assert LockOn.status().state == :coasting
    until(fn -> LockOn.status().state == :lost end, 4_000)
    assert LockOn.status().state == :lost
    Agent.update(sky, &%{&1 | hidden: false})
    until(fn -> LockOn.status().state == :holding end, 2_000)
    assert LockOn.status().state == :holding
  end

  @tag timeout: 60_000
  test "no pictures is not a lost target: the motors stop, and it carries on when pictures come back",
       %{id: id, sky: sky} do
    :ok = LockOn.start(id, @fast)
    until(fn -> LockOn.status().state == :holding end)
    Agent.update(sky, &%{&1 | on: false})
    until(fn -> LockOn.status().state == :waiting end, 3_000)
    assert %{state: :waiting, why: why} = LockOn.status()
    assert why =~ "no new pictures"
    Process.sleep(300)
    assert Enum.all?(Map.values(Mount.snapshot(id).axes), &(&1[:running] != true))
    Agent.update(sky, &%{&1 | on: true})
    until(fn -> LockOn.status().state == :holding end, 3_000)
    assert LockOn.status().state == :holding
  end

  @tag timeout: 60_000
  test "STOP anywhere ends it, and says so", %{id: id} do
    :ok = LockOn.start(id, @fast)
    until(fn -> LockOn.status().state == :holding end)
    :ok = Mount.stop(id)
    until(fn -> LockOn.status().state == :off end, 2_000)
    assert %{state: :off, why: "STOP was pressed"} = LockOn.status()
  end

  @tag timeout: 60_000
  test "a saved calibration holds at once, without nudging the mount again", %{id: id} do
    :ok = LockOn.start(id, @fast)
    until(fn -> LockOn.status().state == :holding end)
    LockOn.release()
    :ok = LockOn.start(id, Keyword.put(@fast, :saved, true))
    assert LockOn.status().state == :holding
  end

  describe "cut off while holding" do
    setup do
      env = Application.get_env(:controller, :lock_on, [])
      # the process that comes back reads its knobs from config, like a box after a reboot
      Application.put_env(:controller, :lock_on, Keyword.merge(env, @fast ++ [beat_ms: 100, revive_lead_s: 0.3]))

      on_exit(fn ->
        Application.put_env(:controller, :lock_on, env)
        Controller.Settings.put("lock_on_resume", nil)
      end)

      :ok
    end

    @tag timeout: 60_000
    test "it picks up by itself: the mount is caught up for the time it was down, and it holds again", %{id: id} do
      :ok = LockOn.start(id, @fast ++ [beat_ms: 100])
      until(fn -> LockOn.status().state == :holding end)
      until(fn -> match?(%{error_px: {ex, ey}} when abs(ex) < 6 and abs(ey) < 6, LockOn.status()) end, 6_000)
      until(fn -> match?(%{"mount" => ^id}, Controller.Settings.get("lock_on_resume")) end, 2_000)
      assert %{"mount" => ^id, "rates" => [rra, _], "target" => "bright"} = Controller.Settings.get("lock_on_resume")
      assert rra > 0.5
      {ra0, _} = axes(id)

      # the box goes down: no goodbye, nothing cleaned up. Three seconds of sky pass; the motors, unfed, stop
      :ok = Supervisor.terminate_child(Controller.LockOn.Supervisor, LockOn)
      Process.sleep(3_000)
      {ra1, _} = axes(id)
      {:ok, _} = Supervisor.restart_child(Controller.LockOn.Supervisor, LockOn)

      until(fn -> LockOn.status().state == :holding end, 10_000)
      assert %{state: :holding, why: why, mount: ^id} = LockOn.status()
      assert why =~ "back after" and why =~ "holding again"
      # the RA axis was moved on by about what it would have turned in that time
      {ra2, _} = axes(id)
      assert ra2 - ra1 > 0.5 * rra * 0.004178 * 3, "RA went from #{ra0} to #{ra1} (down) to #{ra2}"
      # and the target is back on its spot
      until(fn -> match?(%{error_px: {ex, ey}} when abs(ex) < 8 and abs(ey) < 8, LockOn.status()) end, 8_000)
      {ex, ey} = LockOn.status().error_px
      assert abs(ex) < 8 and abs(ey) < 8, "still #{ex}, #{ey} px off after picking up"
    end

    @tag timeout: 60_000
    test "with no network time yet it goes by the box's own clock, says so, and keeps its own record of the recovery", %{id: id} do
      env = Application.get_env(:controller, :lock_on)
      Application.put_env(:controller, :lock_on, Keyword.put(env, :revive_clock_ms, 300))
      on_exit(fn -> Application.delete_env(:controller, :clock_synced) end)

      :ok = LockOn.start(id, @fast ++ [beat_ms: 100])
      until(fn -> LockOn.status().state == :holding end)
      until(fn -> is_map(Controller.Settings.get("lock_on_resume")) end, 2_000)
      :ok = Supervisor.terminate_child(Controller.LockOn.Supervisor, LockOn)
      Process.sleep(1_500)
      # the box comes up with a clock nobody has set
      Application.put_env(:controller, :clock_synced, false)
      {:ok, _} = Supervisor.restart_child(Controller.LockOn.Supervisor, LockOn)

      until(fn -> LockOn.status().state == :holding end, 10_000)
      assert %{state: :holding, why: why} = LockOn.status()
      assert why =~ "by the box's own clock"
      until(fn -> match?(%{error_px: {ex, ey}} when abs(ex) < 8 and abs(ey) < 8, LockOn.status()) end, 8_000)

      # network time arrives: the clock was not behind (this is a Mac), and the target is in hand, so nothing moves
      Application.put_env(:controller, :clock_synced, true)
      until(fn -> Enum.any?(Controller.Recovery.recent(40), &(&1["event"] == "clock_set")) end, 3_000)
      events = Controller.Recovery.recent(40)
      assert %{"data" => %{"clock" => "own", "mount" => ^id, "down_s" => down}, "clock" => "not set"} = Enum.find(Enum.reverse(events), &(&1["event"] == "lock_catch_up"))
      assert down >= 1.0
      assert %{"data" => %{"moved" => false}} = Enum.find(Enum.reverse(events), &(&1["event"] == "clock_set"))
      assert Enum.any?(events, &(&1["event"] == "lock_target_seen" and &1["data"]["mount"] == id))
      assert LockOn.status().state == :holding
    end

    @tag timeout: 60_000
    test "a lock that was released, or stopped, is not picked up", %{id: id} do
      :ok = LockOn.start(id, @fast ++ [beat_ms: 100])
      until(fn -> LockOn.status().state == :holding end)
      until(fn -> is_map(Controller.Settings.get("lock_on_resume")) end, 2_000)
      LockOn.release()
      assert Controller.Settings.get("lock_on_resume") == nil

      :ok = Supervisor.terminate_child(Controller.LockOn.Supervisor, LockOn)
      {:ok, _} = Supervisor.restart_child(Controller.LockOn.Supervisor, LockOn)
      Process.sleep(500)
      assert LockOn.status().state == :off
    end

    @tag timeout: 60_000
    test "down too long, it says so and stays off", %{id: id} do
      :ok = LockOn.start(id, @fast ++ [beat_ms: 100])
      until(fn -> LockOn.status().state == :holding end)
      until(fn -> is_map(Controller.Settings.get("lock_on_resume")) end, 2_000)
      :ok = Supervisor.terminate_child(Controller.LockOn.Supervisor, LockOn)
      # the heartbeat says it stopped half an hour ago
      old = Controller.Settings.get("lock_on_resume")
      Controller.Settings.put("lock_on_resume", %{old | "at" => DateTime.utc_now() |> DateTime.add(-1800) |> DateTime.to_iso8601()})
      {:ok, _} = Supervisor.restart_child(Controller.LockOn.Supervisor, LockOn)
      until(fn -> LockOn.status().state == :off and LockOn.status().why =~ "too long" end, 5_000)
      assert %{state: :off, why: why} = LockOn.status()
      assert why =~ "30.0 min" and why =~ "too long"
      assert Controller.Settings.get("lock_on_resume") == nil
    end
  end

  test "the box's record of its recoveries is kept line by line, and read back over HTTP" do
    Controller.Recovery.note(:test_event, %{n: 1})
    assert %{"event" => "test_event", "data" => %{"n" => 1}, "clock" => "network", "at" => _} = List.last(Controller.Recovery.recent(5))
    conn = Phoenix.ConnTest.build_conn() |> Phoenix.ConnTest.dispatch(Controller.Endpoint, :get, "/recoveries.json?n=3")
    assert [_ | _] = body = Jason.decode!(conn.resp_body)
    assert List.last(body)["event"] == "test_event"
  end

  test "every page says Lock On is running, in its own words", %{id: id} do
    :ok = LockOn.start(id, @fast)
    assert Enum.any?(Controller.Modes.active(), fn {label, _} -> label =~ "Lock On" end)
    LockOn.release()
    refute Enum.any?(Controller.Modes.active(), fn {label, _} -> label =~ "Lock On" end)
  end
end
