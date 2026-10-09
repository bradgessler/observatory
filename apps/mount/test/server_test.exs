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

  test "a held slew refreshed as its dead-man fired keeps running, and still stops on its own", %{id: id} do
    # the refresh waits its turn while the old dead-man fires behind it (the
    # driver held busy, as in "a goto under a held slew" below): the old
    # expiry must not stop what was just refreshed, and the new one must
    [{pid, _}] = Registry.lookup(Mount.Registry, id)
    :ok = Mount.slew(id, :ra, 64, hold: true)
    armed = System.monotonic_time(:millisecond)
    Process.sleep(800)
    :sys.suspend(pid)
    refresh = Task.async(fn -> Mount.slew(id, :ra, 64, hold: true) end)
    Process.sleep(max(armed + 960 - System.monotonic_time(:millisecond), 0))
    :sys.resume(pid)
    assert :ok = Task.await(refresh)
    Process.sleep(300)
    assert Mount.snapshot(id).axes.ra.running, "the old dead-man stopped a slew that had just been refreshed"
    assert_eventually(fn -> Mount.snapshot(id).axes.ra end, &(not &1.running), 2_000)
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

    # 8 October 2026: a Go To issued under a tracker's slow held slew, late in a stall window, was
    # judged over the whole window at the goto's speed and stopped 175 ms in as a "stall"
    test "a new command starts the window again: a goto late in a slow slew's window is judged on its own", %{id: id} do
      :ok = Mount.slew(id, :dec, 1.0)
      Process.sleep(1_300)
      # from here the count can't move: a real stall, but one the goto's own window must find
      jam(id, :dec, true)
      t0 = System.monotonic_time(:millisecond)
      :ok = Mount.goto_relative(id, :dec, 30.0)
      assert_eventually(fn -> Mount.snapshot(id) end, &(&1.stalled != nil), 4_000)
      took = System.monotonic_time(:millisecond) - t0
      assert took >= 1_400, "called a stall #{took} ms into the goto, judged by the slew's window"
      jam(id, :dec, false)
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

  # The Go To from Saturn to M31 that answered :ok and never left Saturn
  # (#122). A tracker feeds a dead-man on each axis twice a second, and a
  # goto has to get past it whenever in its 900 ms it is issued.
  describe "a goto under a held slew" do
    @delays [0, 100, 200, 300, 400, 500, 600, 700, 800, 850, 880, 895]

    test "arrives, whenever in the dead-man's 900 ms it is issued" do
      lost =
        each_on_its_own_mount(@delays, [], fn id, delay ->
          :ok = Mount.slew(id, :ra, 1.0, hold: true)
          Process.sleep(delay)
          from = Mount.snapshot(id).axes.ra.degrees
          reply = Mount.goto_relative(id, :ra, 4.0)
          {reply, [ra: landed(id, :ra) - from]}
        end)
        |> not_arrived(ra: 4.0)

      assert lost == [], "gotos lost, as {ms after the held slew, reply, degrees moved}: #{inspect(lost)}"
    end

    # How it was lost. Cancelling a timer does not take back an expiry already
    # in the mailbox: the driver is held busy here (as a poll over the cable
    # holds it) until the dead-man has fired behind the waiting goto.
    test "arrives when the dead-man fired while it waited its turn" do
      lost =
        each_on_its_own_mount(@delays, [], fn id, delay ->
          [{pid, _}] = Registry.lookup(Mount.Registry, id)
          :ok = Mount.slew(id, :ra, 1.0, hold: true)
          armed = System.monotonic_time(:millisecond)
          Process.sleep(delay)
          from = Mount.snapshot(id).axes.ra.degrees
          :sys.suspend(pid)
          goto = Task.async(fn -> Mount.goto_relative(id, :ra, 4.0) end)
          Process.sleep(max(armed + 960 - System.monotonic_time(:millisecond), 0))
          :sys.resume(pid)
          {Task.await(goto), [ra: landed(id, :ra) - from]}
        end)
        |> not_arrived(ra: 4.0)

      assert lost == [], "gotos lost, as {ms after the held slew, reply, degrees moved}: #{inspect(lost)}"
    end

    # The same loss with nothing forced, on a link as slow as the EQDIR cable.
    # The model tracker feeds both axes every 500 ms (Dec first), and a Go To
    # takes over, RA leg then Dec leg, at every point of that half second and
    # of the driver's own poll. The Dec leg waits its turn behind the RA leg
    # and a poll, long enough for the Dec dead-man to fire behind it: before
    # the fix a quarter of these lost the Dec leg, with :ok given for both.
    test "both legs of a Go To arrive after a tracker's held slews, on a link as slow as the real one" do
      feed = fn id ->
        Mount.slew(id, :dec, -0.36, hold: true, quiet: true)
        Mount.slew(id, :ra, 0.95, hold: true, quiet: true)
      end

      lost =
        each_on_its_own_mount(for(delay <- 0..480//20, phase <- [0, 100, 200, 300], do: {delay, phase}), [latency_ms: 40], fn id, {delay, phase} ->
          # the poll keeps its own time from the moment the mount answers
          Mount.snapshot(id)
          Process.sleep(phase)
          tick = System.monotonic_time(:millisecond)
          feed.(id)
          Process.sleep(max(tick + 500 - System.monotonic_time(:millisecond), 0))
          feed.(id)
          Process.sleep(delay)
          from = Mount.snapshot(id).axes
          ra = Mount.goto_relative(id, :ra, 1.0)
          dec = Mount.goto_relative(id, :dec, 3.0)
          moved = [ra: landed(id, :ra) - from.ra.degrees, dec: landed(id, :dec) - from.dec.degrees]
          {if(ra == :ok, do: dec, else: ra), moved}
        end)
        |> not_arrived(ra: 1.0, dec: 3.0)

      assert lost == [], "Go Tos lost, as {{ms after the tracker's last tick, ms into the poll}, reply, degrees moved}: #{inspect(lost)}"
    end

    test "waits for a moving axis to stop: the board refuses a goto on one still running" do
      id = sim(stop_ms: 400)
      :ok = Mount.slew(id, :dec, 16)
      assert_eventually(fn -> Mount.snapshot(id).axes.dec end, & &1.running)
      from = Mount.snapshot(id).axes.dec.degrees
      asked = System.monotonic_time(:millisecond)
      assert :ok = Mount.goto_relative(id, :dec, 2.0)
      assert System.monotonic_time(:millisecond) - asked >= 400
      # the 2° of the goto, on top of the little the slew ran on while it stopped
      moved = landed(id, :dec) - from
      assert moved >= 2.0 and moved < 2.3
      assert Mount.snapshot(id).axes.dec.mode == :goto
    end

    test "an axis that will not stop gets no goto, and the caller is told" do
      id = sim(stop_ms: 6_000)
      :ok = Mount.slew(id, :dec, 64)
      assert {:error, :motor_running} = Mount.goto_relative(id, :dec, 2.0)
      refute Mount.snapshot(id).axes.dec.goto_pending
    end
  end

  describe "a goto the mount did not start" do
    # the simulator's swallowed goto: every frame acknowledged, nothing moves
    defp swallow(id, axis),
      do: Mount.Server.call(id, {:raw, Mount.Protocol.encode("Z", axis, "2")})

    test "is an error within 2 s, the axis is left stopped, and the next one goes", %{id: id} do
      Telescope.Events.subscribe()
      # under a held slew, as it was on the night
      :ok = Mount.slew(id, :ra, 1.0, hold: true)
      swallow(id, :ra)
      asked = System.monotonic_time(:millisecond)
      assert {:error, :goto_not_started} = Mount.goto_relative(id, :ra, 23.0)
      assert System.monotonic_time(:millisecond) - asked < 2_000

      ax = Mount.snapshot(id).axes.ra
      refute ax.running
      refute ax.goto_pending
      assert_receive {:event, %{module: :mount, name: :goto_failed, data: %{axis: :ra, why: :goto_not_started}}}, 1_000
      refute_received {:event, %{module: :mount, name: :goto}}

      from = ax.degrees
      assert :ok = Mount.goto_relative(id, :ra, 1.0)
      assert_in_delta landed(id, :ra) - from, 1.0, 0.02
    end

    test "leaves the driver's own tracking running", %{id: id} do
      :ok = Mount.track(id, :sidereal)
      swallow(id, :ra)
      assert {:error, :goto_not_started} = Mount.goto_relative(id, :ra, 5.0)
      snap = Mount.snapshot(id)
      assert snap.tracking == :sidereal
      assert snap.axes.ra.running and snap.axes.ra.mode == :slew
    end
  end

  # another simulated mount: for a slow one, or for many at once
  defp sim(opts) do
    id = "sim-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, opts}})
    id
  end

  # Runs `fun.(id, value)` for every value at the same time, each on a mount
  # of its own, so a sweep of timings costs one run's wait. `fun` answers
  # `{reply, moved}`; back comes `{value, reply, moved}` for each.
  defp each_on_its_own_mount(values, sim_opts, fun) do
    values
    |> Enum.map(&{&1, sim(sim_opts)})
    |> Enum.map(fn {value, id} ->
      Task.async(fn ->
        {reply, moved} = fun.(id, value)
        {value, reply, moved}
      end)
    end)
    |> Task.await_many(60_000)
  end

  # the runs that were not :ok or did not end up `want` degrees on, per axis
  defp not_arrived(runs, want) do
    for {value, reply, moved} <- runs,
        reply != :ok or Enum.any?(want, fn {axis, deg} -> abs(moved[axis] - deg) > 0.02 end),
        do: {value, reply, Enum.map(moved, fn {axis, deg} -> {axis, Float.round(deg, 2)} end)}
  end

  # where an axis is once its goto has come and gone (or 10 s have)
  defp landed(id, axis, deadline \\ System.monotonic_time(:millisecond) + 10_000) do
    ax = Mount.snapshot(id).axes[axis]

    if (not ax.running and not ax.goto_pending) or System.monotonic_time(:millisecond) > deadline do
      ax.degrees
    else
      Process.sleep(50)
      landed(id, axis, deadline)
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
