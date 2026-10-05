defmodule Controller.Sky.TrackerTest do
  @moduledoc "Model tracking against the simulated mount: it runs the axes, holds the error small, and gets out of the way."
  use ExUnit.Case, async: false

  alias Controller.Sky.{Pointing, Tracker}

  setup do
    id = "sim-trk-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    on_exit(fn -> Tracker.stop(id) end)
    %{id: id}
  end

  # a target the first-order model can point at from home without a long slew
  defp target(id), do: target_at(id, 3.0, -5.0, "test-target")

  # one a Go To has to reach: 8° off in Dec from home, further than the tracker will chase
  @far {6.0, -8.0}
  defp far(id), do: target_at(id, elem(@far, 0), elem(@far, 1), "far-target")

  # the object that sits where the axes read `ra_axis`, `dec_axis` degrees from home
  defp target_at(id, ra_axis, dec_axis, name) do
    ctx = Pointing.context(DateTime.utc_now(), id)
    snap = Mount.snapshot(id)
    {ra, dec} = Pointing.scope_radec(%{snap | axes: %{ra: %{degrees: ra_axis}, dec: %{degrees: dec_axis}}}, ctx)
    %{name: name, ra_deg: ra, dec_deg: dec}
  end

  test "tracks a target: RA runs near sidereal and the error stays small", %{id: id} do
    t = target(id)
    ref = Enum.find(Mount.list(), &(&1.id == id))
    {:ok, _, _} = Pointing.slew(ref, Mount.snapshot(id), t, Pointing.context(DateTime.utc_now(), id), track: false)
    wait_until(fn -> snap = Mount.snapshot(id); not snap.axes.ra.running and not snap.axes.dec.running end, 20_000)

    Tracker.track(id, t)
    wait_until(fn -> (Tracker.status(id) || %{})[:error_arcmin] != nil end, 6_000)
    st = Tracker.status(id)
    assert st.name == "test-target"
    assert_in_delta abs(st.ra_rate), 1.0, 0.3
    assert st.error_arcmin < 2.0
    assert Mount.snapshot(id).axes.ra.running
  end

  test "a STOP ends tracking instead of being fought", %{id: id} do
    t = target(id)
    Tracker.track(id, t)
    wait_until(fn -> Mount.snapshot(id).axes.ra.running end, 6_000)
    Mount.emergency_stop(id)
    wait_until(fn -> Tracker.status(id) == nil end, 8_000)
    refute Mount.snapshot(id).axes.ra.running
  end

  test "stop/1 halts the axes and clears the readout", %{id: id} do
    Tracker.track(id, target(id))
    wait_until(fn -> Mount.snapshot(id).axes.ra.running end, 6_000)
    Tracker.stop(id)
    wait_until(fn -> Tracker.status(id) == nil end, 3_000)
    wait_until(fn -> not Mount.snapshot(id).axes.ra.running end, 5_000)
  end

  # #122: the Go To from Saturn to M31. A new target is 23° off until its Go
  # To lands, and a tracker that calls that lost stops both axes for good.
  describe "a new target" do
    test "is not given up on while its Go To is in flight", %{id: id} do
      go_far(id)
      Tracker.track(id, far(id))
      assert_held_until_landed(id)
    end

    test "is not given up on before its Go To shows", %{id: id} do
      Tracker.track(id, far(id))
      # 8° off and nothing moving yet: this was :lost, and the end, on the first tick
      Process.sleep(1_200)
      assert %{paused: :goto} = Tracker.status(id)
      refute Mount.snapshot(id).axes.dec.running
      go_far(id)
      assert_held_until_landed(id)
    end

    test "far off with no Go To in sight, it gives up and says so to Events and the pages", %{id: id} do
      Telescope.Events.subscribe()
      Telescope.subscribe("tracker")
      Tracker.track(id, far(id))
      wait_until(fn -> Tracker.ended(id) != nil end, 8_000)

      assert %{name: "far-target", why: :lost, off_deg: off} = Tracker.ended(id)
      assert_in_delta off, 8.0, 0.5
      assert Tracker.status(id) == nil
      assert_receive {:event, %{module: :tracker, name: :end, data: %{target: "far-target", why: :lost, off_deg: ^off}}}, 1_000
      assert_receive {:tracker, ^id, nil}, 1_000
      snap = Mount.snapshot(id)
      refute snap.axes.ra.running or snap.axes.dec.running
    end

    test "a Go To the mount did not start is an error, nothing is left moving and no tracking is started", %{id: id} do
      ref = Enum.find(Mount.list(), &(&1.id == id))
      # the Dec leg is swallowed: acknowledged by the board, never started
      Mount.raw(id, Mount.Protocol.encode("Z", :dec, "2"))

      assert {:error, :goto_not_started} = Pointing.slew(ref, Mount.snapshot(id), far(id), Pointing.context(DateTime.utc_now(), id))

      # never half a slew: the RA leg had started, 6° of it
      snap = Mount.snapshot(id)
      refute snap.axes.ra.running or snap.axes.dec.running
      refute Tracker.active?(id)
      assert Pointing.refusal_words(:goto_not_started, "M31") =~ "didn't start the Go To to M31"
    end
  end

  # both legs, as Pointing.slew sends them
  defp go_far(id) do
    {ra, dec} = @far
    :ok = Mount.goto_relative(id, :ra, ra)
    :ok = Mount.goto_relative(id, :dec, dec)
  end

  # looked at ten times a second through the flight: never ended, standing
  # back while a leg flies, and tracking the target once both have landed
  defp assert_held_until_landed(id) do
    wait_until(fn -> Tracker.status(id) != nil end, 3_000)

    wait_until(
      fn ->
        st = Tracker.status(id)
        assert st, "gave up in flight: #{inspect(Tracker.ended(id))}"
        st.error_arcmin != nil
      end,
      15_000
    )

    assert Tracker.ended(id) == nil
    st = Tracker.status(id)
    # arcminutes off after the flight, not the degrees it started with, and RA driven with the sky
    assert st.error_arcmin < 30.0
    assert abs(st.ra_rate) > 0.5 and abs(st.ra_rate) < 3.0
    snap = Mount.snapshot(id)
    assert_in_delta snap.axes.dec.degrees, elem(@far, 1), 0.1
    assert snap.axes.ra.running
  end

  defp wait_until(fun, ms) do
    deadline = System.monotonic_time(:millisecond) + ms

    Stream.repeatedly(fn -> Process.sleep(100); fun.() end)
    |> Enum.find(fn ok -> ok or System.monotonic_time(:millisecond) > deadline end)
    |> then(fn ok -> assert ok, "timed out after #{ms} ms" end)
  end
end
