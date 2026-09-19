defmodule Controller.Optical.AxisScanTest do
  @moduledoc "The scan against a simulated mount: whatever goes wrong on the way, the axes end where they started."
  use ExUnit.Case

  alias Controller.Optical.{AxisScan, Frame}

  setup do
    id = "scan-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    :ok = Mount.set_home(id)
    AxisScan.subscribe()
    # the scanner is one process for the whole VM: leave it idle for the next test
    on_exit(fn -> AxisScan.cancel(return: false); AxisScan.reset() end)
    %{id: id}
  end

  # a camera that gives one still and then dies
  defp failing_capture(at_step) do
    {:ok, counter} = Agent.start_link(fn -> 0 end)
    frame = Frame.from_grey(16, 16, :binary.copy(<<0>>, 256))

    fn ->
      n = Agent.get_and_update(counter, &{&1 + 1, &1 + 1})
      if n == at_step, do: {:error, "camera unplugged"}, else: {:ok, frame, "f#{n}.jpg"}
    end
  end

  test "a sweep whose camera fails at the second position puts both axes back where they started", %{id: id} do
    before = Mount.snapshot(id).axes
    assert :ok = AxisScan.sweep(id, range: 1.0, capture: failing_capture(2))

    assert_receive {:optical, %{running: false, step: :failed, error: error}}, 30_000
    assert error =~ "camera unplugged"

    after_ = Mount.snapshot(id).axes
    assert_in_delta after_.ra.degrees, before.ra.degrees, 0.05
    assert_in_delta after_.dec.degrees, before.dec.degrees, 0.05
    refute after_.ra.running
    refute after_.dec.running
  end

  test "a scan is refused until home is set and while the mount moves" do
    id = "cold-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000

    assert {:error, words} = AxisScan.sweep(id, capture: fn -> {:error, "never called"} end)
    assert words =~ "home"

    :ok = Mount.set_home(id)
    :ok = Mount.track(id, :sidereal)
    assert {:error, words} = AxisScan.run(id, capture: fn -> {:error, "never called"} end)
    assert words =~ "tracking"
    :ok = Mount.stop(id)
  end

  test "STOP pressed during a sweep ends it where it stands, and cancel puts it back", %{id: id} do
    frame = Frame.from_grey(16, 16, :binary.copy(<<0>>, 256))
    test = self()

    # the first still is the cue to press STOP; the scan must not move again after it
    # (a beat before returning, so the STOP lands before the scan asks for its next move)
    capture = fn ->
      send(test, :captured)
      Process.sleep(500)
      {:ok, frame, "f.jpg"}
    end

    assert :ok = AxisScan.sweep(id, range: 1.0, capture: capture)
    assert_receive :captured, 10_000
    :ok = Mount.emergency_stop(id)
    assert_receive {:optical, %{running: false, step: :failed, error: error}}, 10_000
    assert error =~ "STOP"
    # abandoned at the first position, −1°: nothing moved it back
    assert_in_delta Mount.snapshot(id).axes.ra.degrees, -1.0, 0.05

    # cancel from the page: back to where this scan began
    assert :ok = AxisScan.sweep(id, range: 1.0, capture: capture)
    assert_receive :captured, 10_000
    assert :ok = AxisScan.cancel()
    assert_receive {:optical, %{running: false, step: :cancelled}}, 5_000
    Process.sleep(4_000)
    assert_in_delta Mount.snapshot(id).axes.ra.degrees, -1.0, 0.05
    refute Mount.snapshot(id).axes.ra.running
  end
end
