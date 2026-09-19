defmodule Controller.Input.GamepadTest do
  use ExUnit.Case, async: true
  alias Controller.Input.Gamepad

  defp state(axes, pressed, hat \\ nil) do
    buttons = for i <- 0..8, do: %{pressed: i in pressed, value: if(i in pressed, do: 1.0, else: 0.0)}
    %{axes: axes, buttons: buttons, hat: hat}
  end

  test "nothing happens without the trigger" do
    assert Gamepad.interpret(state([0.9, 0.0], [])) == :idle
  end

  test "trigger + tilt moves; more tilt is faster, on a log scale" do
    {:move, [ra: slow]} = Gamepad.interpret(state([0.3, 0.0], [0]))
    {:move, [ra: fast]} = Gamepad.interpret(state([1.0, 0.0], [0]))
    assert slow > 1 and slow < 50
    assert_in_delta fast, 800, 1
  end

  test "dead zone" do
    assert Gamepad.interpret(state([0.05, -0.08], [0])) == :idle
  end

  test "Y is inverted by default so pushing forward is +Dec" do
    {:move, [dec: r]} = Gamepad.interpret(state([0.0, -1.0], [0]))
    assert r > 0
  end

  test "hat nudges without the trigger at the fine rate" do
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0})) == {:nudge, [ra: 8.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, -1})) == {:nudge, [dec: -8.0]}
  end

  test "stop button wins over everything" do
    assert Gamepad.interpret(state([1.0, 1.0], [0, 1])) == :stop
  end

  test "mapping is a parameter" do
    assert {:move, _} = Gamepad.interpret(state([0.0, 0.0, 0.8, 0.0], [5]), %{trigger: 5, x_axis: 2})
  end
end
