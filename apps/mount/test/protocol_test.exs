defmodule Mount.ProtocolTest do
  use ExUnit.Case, async: true
  alias Mount.Protocol, as: P

  @eq6r %{steps_per_rev: 9_216_000, timer_freq: 53_694, high_speed_ratio: 32}

  test "frames" do
    assert P.encode("e", :ra) == ":e1\r"
    assert P.encode("I", :dec, "3F0000") == ":I23F0000\r"
    assert P.decode("=020B05\r") == {:ok, "020B05"}
    assert P.decode("!2\r") == {:error, :motor_running}
  end

  test "24-bit numbers are byte reversed" do
    assert P.to_int("563412") == 0x123456
    assert P.from_int(0x123456) == "563412"
    assert P.to_int("00A08C") == 9_216_000
    assert P.to_int("20") == 32
  end

  test "status nibbles" do
    assert %{mode: :slew, running: false, initialized: false} = P.decode_status("100")
    assert %{mode: :slew, speed: :fast, running: true} = P.decode_status("510")
    assert %{direction: :reverse, initialized: true} = P.decode_status("301")
  end

  test "positions" do
    assert P.steps_to_degrees(P.center(), 9_216_000) == 0.0
    assert_in_delta P.steps_to_degrees(8_644_608, 9_216_000), 10.0, 1.0e-9
    assert P.degrees_to_steps(5, 9_216_000) == 128_000
  end

  test "slew params reproduce what the real mount accepted" do
    assert P.slew_params(1, @eq6r) == {:slow, 502}
    assert P.slew_params(8, @eq6r) == {:slow, 63}
    assert P.slew_params(200, @eq6r) == {:fast, 80}
    assert_in_delta P.rate_for(:fast, 80, @eq6r), 200, 1
  end
end
