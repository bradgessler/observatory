defmodule Mount.ServerTest do
  use ExUnit.Case

  setup do
    id = "sim-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    %{id: id}
  end

  test "reports firmware and both axes", %{id: id} do
    snap = Mount.snapshot(id)
    assert snap.firmware == "020B05"
    assert snap.axes.ra.degrees == 0.0
    assert snap.axes.dec.degrees == 0.0
  end

  test "goto moves the axis and lands", %{id: id} do
    :ok = Mount.goto_relative(id, :dec, 2.0)

    assert_eventually(
      fn -> Mount.snapshot(id).axes.dec end,
      &(not &1.running and abs(&1.degrees - 2.0) < 0.01)
    )
  end

  test "slew runs until stopped, negative rate reverses", %{id: id} do
    :ok = Mount.slew(id, :ra, -800)
    assert_eventually(fn -> Mount.snapshot(id).axes.ra end, &(&1.running and &1.degrees < -0.5))
    :ok = Mount.stop(id, :ra)
    refute Mount.snapshot(id).axes.ra.running
  end

  test "instant stop halts one axis without a ramp", %{id: id} do
    :ok = Mount.slew(id, :ra, 800)
    assert Mount.snapshot(id).axes.ra.running
    :ok = Mount.stop(id, :ra, instant: true)
    refute Mount.snapshot(id).axes.ra.running
  end

  test "held slews stop on their own", %{id: id} do
    :ok = Mount.slew(id, :ra, 64, hold: true)
    assert Mount.snapshot(id).axes.ra.running
    assert_eventually(fn -> Mount.snapshot(id).axes.ra end, &(not &1.running), 3_000)
  end

  test "a goto after a held slew is not killed by the old dead-man", %{id: id} do
    # the night the third alignment star landed 9° short: the tracker's held
    # slews left a hold timer armed, and it stopped the goto a second in
    :ok = Mount.slew(id, :ra, 16, hold: true)
    :ok = Mount.goto_relative(id, :ra, 12.0)
    Process.sleep(1_500)
    assert Mount.snapshot(id).axes.ra.running, "goto stopped early"

    assert_eventually(
      fn -> Mount.snapshot(id).axes.ra end,
      &(not &1.running and abs(&1.degrees - 12.0) < 0.05),
      8_000
    )
  end

  test "an un-held slew replaces a held one and keeps running", %{id: id} do
    :ok = Mount.slew(id, :dec, 16, hold: true)
    :ok = Mount.slew(id, :dec, 16)
    Process.sleep(1_500)
    assert Mount.snapshot(id).axes.dec.running
    :ok = Mount.stop(id, :dec)
  end

  test "STOP of both axes stamps estop_at so a tracker ends", %{id: id} do
    before = Mount.snapshot(id).estop_at
    :ok = Mount.stop(id)
    assert is_integer(Mount.snapshot(id).estop_at)
    assert Mount.snapshot(id).estop_at != before
  end

  test "tracking survives a goto", %{id: id} do
    :ok = Mount.track(id, :sidereal)
    :ok = Mount.goto_relative(id, :ra, 1.0)

    assert_eventually(
      fn -> Mount.snapshot(id) end,
      &(&1.axes.ra.running and &1.axes.ra.speed == :slow and &1.axes.ra.degrees > 0.99),
      5_000
    )
  end

  describe "soft limits" do
    setup %{id: _id} do
      # tight box so the sim crosses it fast
      id = "lim-#{System.unique_integer([:positive])}"

      start_supervised!(
        {Mount.Server,
         id: id,
         transport: {Mount.Transport.Sim, []},
         limits: %{ra: {-1.0, 1.0}, dec: {-1.0, 1.0}}}
      )

      assert_eventually(fn -> Mount.snapshot(id) end, & &1.connected)
      %{id: id}
    end

    test "nothing is enforced until home is set", %{id: id} do
      refute Mount.snapshot(id).homed
      :ok = Mount.goto_relative(id, :dec, 3.0)

      assert_eventually(
        fn -> Mount.snapshot(id).axes.dec end,
        &(not &1.running and &1.degrees > 2.9)
      )
    end

    test "goto past a limit is refused, inside is fine", %{id: id} do
      :ok = Mount.set_home(id)
      assert Mount.snapshot(id).homed
      assert {:error, :limit} = Mount.goto_relative(id, :ra, 2.0)
      assert :ok = Mount.goto_relative(id, :ra, 0.5)
    end

    test "a running slew is stopped at the limit", %{id: id} do
      :ok = Mount.set_home(id)
      :ok = Mount.slew(id, :dec, 800)
      assert_eventually(fn -> Mount.snapshot(id).axes.dec end, &(not &1.running), 5_000)
      deg = Mount.snapshot(id).axes.dec.degrees
      # stopped near the 1° edge, never far past it (sim has no ramp-down)
      assert deg > 0.0 and deg < 2.0
      # coming back is always allowed
      assert :ok = Mount.slew(id, :dec, -64)
    end
  end

  test "a serial process closing does not take the driver down (a mount switched off, cable in)", %{id: id} do
    [{pid, _}] = Registry.lookup(Mount.Registry, id)
    send(pid, {:EXIT, self(), :normal})
    send(pid, {:EXIT, self(), :port_closed})
    Process.sleep(100)
    assert Process.alive?(pid)
    assert Mount.snapshot(id).connected
  end

  describe "stalls" do
    # the simulator's jam: the motor "runs", the count stays put
    defp jam(id, axis, on),
      do:
        Mount.Server.call(
          id,
          {:raw, Mount.Protocol.encode("Z", axis, if(on, do: "1", else: "0"))}
        )

    test "a slew whose count stops moving stops both axes and says which", %{id: id} do
      :ok = Mount.slew(id, :dec, 64)
      :ok = Mount.slew(id, :ra, 16)
      jam(id, :dec, true)
      assert_eventually(fn -> Mount.snapshot(id) end, &(&1.stalled != nil), 4_000)
      snap = Mount.snapshot(id)
      assert snap.stalled.axis == :dec
      refute snap.axes.ra.running
      refute snap.axes.dec.running
      assert snap.tracking == :off
      assert is_integer(snap.estop_at)

      # the next command clears it
      jam(id, :dec, false)
      :ok = Mount.goto_relative(id, :dec, 1.0)
      assert Mount.snapshot(id).stalled == nil
    end

    test "a goto that doesn't move is a stall", %{id: id} do
      jam(id, :ra, true)
      :ok = Mount.goto_relative(id, :ra, 30.0)

      assert_eventually(
        fn -> Mount.snapshot(id) end,
        &(&1.stalled != nil and &1.stalled.axis == :ra),
        4_000
      )
    end

    test "tracking at the sky's rate is too slow to judge, and never trips it", %{id: id} do
      :ok = Mount.track(id, :sidereal)
      Process.sleep(2_500)
      snap = Mount.snapshot(id)
      assert snap.stalled == nil
      assert snap.axes.ra.running
    end

    test "fast slews that do move are left alone", %{id: id} do
      :ok = Mount.slew(id, :ra, 400)
      Process.sleep(2_200)
      assert Mount.snapshot(id).stalled == nil
      assert Mount.snapshot(id).axes.ra.running
      :ok = Mount.stop(id, :ra)
    end
  end

  defp assert_eventually(get, ok?, timeout \\ 2_000) do
    deadline = System.monotonic_time(:millisecond) + timeout
    poll(get, ok?, deadline)
  end

  defp poll(get, ok?, deadline) do
    v = get.()

    cond do
      ok?.(v) ->
        :ok

      System.monotonic_time(:millisecond) > deadline ->
        flunk("never satisfied, last: #{inspect(v)}")

      true ->
        Process.sleep(50)
        poll(get, ok?, deadline)
    end
  end
end
