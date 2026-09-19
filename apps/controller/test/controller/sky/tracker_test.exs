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
  defp target(id) do
    ctx = Pointing.context(DateTime.utc_now(), id)
    snap = Mount.snapshot(id)
    {ra, dec} = Pointing.scope_radec(%{snap | axes: %{ra: %{degrees: 3.0}, dec: %{degrees: -5.0}}}, ctx)
    %{name: "test-target", ra_deg: ra, dec_deg: dec}
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

  defp wait_until(fun, ms) do
    deadline = System.monotonic_time(:millisecond) + ms

    Stream.repeatedly(fn -> Process.sleep(100); fun.() end)
    |> Enum.find(fn ok -> ok or System.monotonic_time(:millisecond) > deadline end)
    |> then(fn ok -> assert ok, "timed out after #{ms} ms" end)
  end
end
