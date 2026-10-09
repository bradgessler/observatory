defmodule Input.GamepadTest do
  use ExUnit.Case, async: true
  alias Input.Gamepad

  defp state(axes, pressed, hat \\ nil) do
    %{axes: axes, buttons: for(i <- 0..8, do: i in pressed), hat: hat}
  end

  test "nothing happens without the trigger" do
    assert Gamepad.interpret(state([0.9, 0.0], [])) == :idle
  end

  test "trigger + tilt moves; more tilt steps up the bands to full speed" do
    {:move, [ra: slow]} = Gamepad.interpret(state([0.45, 0.0], [0]))
    {:move, [ra: fast]} = Gamepad.interpret(state([0.9, 0.0], [0]))
    assert slow == 8.0
    assert fast == 800.0
  end

  test "null zone: a ball that looks centred (or is 0.17 off) does nothing even with the trigger held" do
    assert Gamepad.interpret(state([0.05, -0.08], [0])) == :idle
    assert Gamepad.interpret(state([0.17, 0.02], [0])) == :idle
  end

  test "a pull that is mostly one axis moves only that axis" do
    assert {:move, [ra: _]} = Gamepad.interpret(state([1.0, 0.2], [0]))
  end

  test "Y is inverted by default so pushing forward is +Dec" do
    {:move, [dec: r]} = Gamepad.interpret(state([0.0, -1.0], [0]))
    assert r > 0
  end

  test "hat nudges without the trigger at the fine rate" do
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0})) == {:nudge, [ra: 8.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, -1})) == {:nudge, [dec: -8.0]}
  end

  test "in eyepiece mode the hat moves the view: down is RA forward, right is Dec back (the first night's map)" do
    eye = %{hat: :eyepiece}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, -1}), eye) == {:nudge, [ra: 2.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, 1}), eye) == {:nudge, [ra: -2.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0}), eye) == {:nudge, [dec: -2.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {-1, 1}), eye) == {:nudge, [ra: -2.0, dec: 2.0]}
  end

  test "a tap crawls, a hold past the ramp goes at the fine rate" do
    eye = %{hat: :eyepiece}
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0}), Map.put(eye, :hat_held_ms, 400)) == {:nudge, [dec: -2.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0}), Map.put(eye, :hat_held_ms, 2_000)) == {:nudge, [dec: -8.0]}
    # held on, across something the size of the Pleiades
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0}), Map.put(eye, :hat_held_ms, 5_000)) == {:nudge, [dec: -32.0]}
  end

  test "RA carries on from tracking, so up and down move the view the same speed against the sky" do
    eye = %{hat: :eyepiece, track_units: 1.0}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, -1}), eye) == {:nudge, [ra: 3.0]}
    assert Gamepad.interpret(state([0.0, 0.0], [], {0, 1}), eye) == {:nudge, [ra: -1.0]}
  end

  test "the view map is a parameter: a flipped pair drives the other way" do
    flipped = %{hat: :eyepiece, view_right: {:dec, 1}}
    assert Gamepad.interpret(state([0.0, 0.0], [], {1, 0}), flipped) == {:nudge, [dec: 2.0]}
  end

  test "the Dual Strike says it's centred with button 0" do
    assert Input.Parsers.DualStrike.default_map().centered == 0
  end

  test "stop button wins over everything" do
    assert Gamepad.interpret(state([1.0, 1.0], [0, 1])) == :stop
  end

  test "mapping is a parameter" do
    assert {:move, _} = Gamepad.interpret(state([0.0, 0.0, 0.8, 0.0], [5]), %{trigger: 5, x_axis: 2})
  end
end

defmodule Input.Parsers.DualStrikeTest do
  use ExUnit.Case, async: true
  alias Input.Parsers.DualStrike

  # build a 5-byte report from fields, the inverse of the parser's bit layout
  defp report(x, y, buttons, hat) do
    import Bitwise
    bx = band(x, 0x3FF)
    by = band(y, 0x3FF)
    b = Enum.with_index(buttons) |> Enum.reduce(0, fn {on, i}, acc -> if on, do: bor(acc, bsl(1, i)), else: acc end)
    bits = bx ||| bsl(by, 10) ||| bsl(b, 24) ||| bsl(hat, 36)
    <<bits::little-unsigned-40>>
  end

  test "centred, nothing pressed, hat null" do
    s = DualStrike.parse(report(0, 0, List.duplicate(false, 9), 8))
    assert s.axes == [0.0, 0.0]
    assert s.buttons == List.duplicate(false, 9)
    assert s.hat == nil
  end

  test "full left and full forward" do
    s = DualStrike.parse(report(-512, -512, List.duplicate(false, 9), 8))
    assert s.axes == [-1.0, -1.0]
    s = DualStrike.parse(report(511, 511, List.duplicate(false, 9), 8))
    assert_in_delta Enum.at(s.axes, 0), 0.998, 0.001
  end

  test "buttons and hat" do
    s = DualStrike.parse(report(0, 0, [true, false, false, false, false, false, false, false, true], 2))
    assert Enum.at(s.buttons, 0) and Enum.at(s.buttons, 8)
    assert s.hat == {1, 0}
  end

  test "the real idle report from the pad parses to centre" do
    # captured from the SideWinder with the ball at rest
    <<_::binary>> = raw = <<0x00, 0x00, 0x00, 0x00, 0x80>>
    s = DualStrike.parse(raw)
    assert s.axes == [0.0, 0.0]
    assert s.hat == nil
  end
end
