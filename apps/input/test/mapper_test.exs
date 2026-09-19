defmodule Input.MapperTest do
  @moduledoc "The fail-safes: stale input never moves the scope; silence releases; loss disarms."
  use ExUnit.Case, async: false

  setup do
    id = "sim-map-#{System.unique_integer([:positive])}"
    start_supervised!({Mount.Server, id: id, transport: {Mount.Transport.Sim, []}})
    Mount.subscribe(id)
    assert_receive {:mount, %{connected: true}}, 2_000
    Input.target(id)
    Input.arm(true)
    on_exit(fn -> Input.arm(false) end)
    %{id: id}
  end

  defp report(pressed, axes, at \\ System.monotonic_time(:millisecond)) do
    %{
      id: "test-pad",
      parser: "test",
      parser_mod: nil,
      state: %{axes: axes, buttons: for(i <- 0..8, do: i in pressed), hat: nil},
      reports: 1,
      node: node(),
      at: at
    }
  end

  defp push(info), do: send(Input.Mapper, {:input, "test-pad", info})
  defp settle, do: :sys.get_state(Input.Mapper)

  test "a fresh trigger+tilt moves RA; letting go stops it", %{id: id} do
    push(report([0], [1.0, 0.0]))
    settle()
    assert Mount.snapshot(id).axes.ra.running
    push(report([], [0.0, 0.0]))
    settle()
    refute Mount.snapshot(id).axes.ra.running
  end

  test "stale reports are ignored even if the trigger looks held", %{id: id} do
    push(report([0], [1.0, 0.0], System.monotonic_time(:millisecond) - 2_000))
    settle()
    refute Mount.snapshot(id).axes.ra.running
  end

  test "a backlog collapses to the newest report", %{id: id} do
    for _ <- 1..50, do: push(report([0], [1.0, 0.0]))
    push(report([], [0.0, 0.0]))
    settle()
    refute Mount.snapshot(id).axes.ra.running
  end

  test "silence while holding releases within the watchdog window", %{id: id} do
    push(report([0], [0.0, 1.0]))
    settle()
    assert Mount.snapshot(id).axes.dec.running
    Process.sleep(1_000)
    refute Mount.snapshot(id).axes.dec.running
    assert Input.status().held == []
  end

  test "device gone disarms", %{id: _id} do
    send(Input.Mapper, {:input_gone, "test-pad"})
    settle()
    refute Input.status().armed
  end
end
